"""
Recalculate stored CarbonEntry rows from the current emission factors.

Why this exists: carbon is computed by post_save signals and PERSISTED to CarbonEntry. The
consumer QR page and the audit export both read those stored rows, so correcting an emission
factor changes nothing that anyone can see until each event is saved again. After the 2026-07
irrigation-factor correction the Loewen sample page still reported 30,030 kg for irrigation
against a corrected 9,524 kg, because the row was written under the old factor.

Re-saving an event re-runs its signal, which deletes the stale entry and writes a fresh one.
This command does that deliberately and reports the delta, rather than leaving people to
discover the mismatch.

Usage:
    # See what would change (default — nothing is written)
    poetry run python manage.py recalculate_event_carbon --production <id|public_id>
    poetry run python manage.py recalculate_event_carbon --all

    # Apply
    poetry run python manage.py recalculate_event_carbon --production <id> --apply
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from history.models import Production

# Every event family that writes a CarbonEntry, as (label, related_name).
EVENT_SOURCES = (
    ("Production", "history_productionevent_events"),
    ("Chemical", "history_chemicalevent_events"),
    ("Soil", "history_soilmanagementevent_events"),
    ("Pest", "history_pestmanagementevent_events"),
    ("Equipment", "history_equipmentevent_events"),
    ("Weather", "history_weatherevent_events"),
    ("General", "history_generalevent_events"),
    ("Business", "history_businessevent_events"),
)


class Command(BaseCommand):
    help = "Recalculate stored CarbonEntry rows from current emission factors (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--production",
            help="History id or public_id to recalculate. Omit with --all to do every production.",
        )
        parser.add_argument("--all", action="store_true", help="Recalculate every production.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write the changes. Without this the command only reports.",
        )

    def handle(self, *args, **options):
        if not options["production"] and not options["all"]:
            raise CommandError("Pass --production <id|public_id> or --all.")

        productions = self._resolve_productions(options)
        apply_changes = options["apply"]

        grand_before = grand_after = 0.0
        for production in productions:
            before, after = self._recalculate(production, apply_changes)
            grand_before += before
            grand_after += after

        self.stdout.write("")
        verb = "would change" if not apply_changes else "changed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(productions)} production(s) {verb}: " f"{grand_before:.1f} kg -> {grand_after:.1f} kg CO2e"
            )
        )
        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run — nothing written. Re-run with --apply."))

    def _resolve_productions(self, options):
        if options["all"]:
            return list(Production.objects.all())

        key = options["production"]
        query = Production.objects.filter(public_id=key) if "-" in str(key) else Production.objects.filter(pk=key)
        production = query.first()
        if not production:
            raise CommandError(f"No production found for {key!r}.")
        return [production]

    def _stored_total(self, production):
        from carbon.models import CarbonEntry

        total = 0.0
        for entry in CarbonEntry.objects.filter(production=production):
            total += float(entry.co2e_amount or entry.amount or 0.0)
        return total

    def _recalculate(self, production, apply_changes):
        before = self._stored_total(production)
        self.stdout.write("")
        self.stdout.write(f"{production.id}  {production.name}")
        self.stdout.write(f"  stored total before: {before:.1f} kg CO2e")

        if not apply_changes:
            # Report only. Computing the prospective total would mean running every
            # calculator twice, so the honest dry-run output is the current state plus a
            # count of what will be touched.
            touched = sum(
                getattr(production, accessor).count() for _, accessor in EVENT_SOURCES if hasattr(production, accessor)
            )
            self.stdout.write(f"  {touched} event(s) would be re-saved")
            return before, before

        with transaction.atomic():
            for label, accessor in EVENT_SOURCES:
                manager = getattr(production, accessor, None)
                if manager is None:
                    continue
                for event in manager.all():
                    # save() fires the post_save signal, which deletes the stale entry and
                    # writes a fresh one from the current factors.
                    event.save()

        after = self._stored_total(production)
        delta = after - before
        arrow = self.style.SUCCESS(f"{delta:+.1f} kg") if delta else "no change"
        self.stdout.write(f"  stored total after:  {after:.1f} kg CO2e  ({arrow})")
        return before, after
