"""Recompute carbon for TP / BU / SS events written before the 2026-08-22 routing fix.

`calculate_production_event_impact` used to hand `PRODUCTION_TYPE_MAPPING` the literal string
"general production" for any subtype without an explicit branch, which threw away the event's
own code. TP, BU and SS were the three subtypes that fell there, so each one was charged the
2.5 gal diesel/hectare general-production estimate — read off the PARCEL's acreage, since none
of them carries an `area_covered` of its own. A seed search on a 16.4-acre block stored
169.4 kg CO2e.

Carbon is calculated ONCE, at save time, by the signals in `history/signals.py`, and the
serializer only reads what those wrote. So fixing the calculator corrects new records and
leaves every existing row exactly as wrong as it was. Those rows aggregate into farm and
production totals (`carbon/views.py`, `carbon/tasks.py`, `carbon/production_phases.py`), so
the stale figures keep inflating reported emissions until they are rewritten.

Re-saving each event re-fires `calculate_production_event_carbon`, which deletes the old
CarbonEntry and writes a fresh one. `save()` rather than a bulk update precisely because the
signal is the thing we want to run.

    poetry run python manage.py recalculate_non_area_driven_carbon --dry-run
    poetry run python manage.py recalculate_non_area_driven_carbon
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from history.models import ProductionEvent

# The subtypes the routing bug hit. Sourced from the same reasoning as
# `_calculate_reported_fuel_only_emissions`: none is area-driven.
AFFECTED_SUBTYPES = ("TP", "BU", "SS")


class Command(BaseCommand):
    help = "Recompute stored carbon for Transport / Buffer Use / Seed Search production events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        events = ProductionEvent.objects.filter(type__in=AFFECTED_SUBTYPES).select_related("history", "history__parcel")
        total = events.count()

        if not total:
            self.stdout.write(self.style.SUCCESS("No TP/BU/SS events found — nothing to recompute."))
            return

        self.stdout.write(f"Found {total} TP/BU/SS event(s).")

        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calculator = EventCarbonCalculator()
        changed = 0
        reclaimed = 0.0

        for event in events.iterator():
            # What the row says now, read the same way the serializer reads it.
            stored = self._stored_co2e(event)
            try:
                corrected = float(calculator.calculate_production_event_impact(event).get("co2e", 0.0))
            except Exception as exc:  # noqa: BLE001 — report and continue; one bad row must not abort the sweep
                self.stderr.write(self.style.ERROR(f"  {event.type} id={event.id}: recalculation failed: {exc}"))
                continue

            # No stored row AND nothing to store is already correct: a zero-emission event
            # writes no CarbonEntry at all, so `None` here means "settled at 0", not
            # "never calculated". Treating None as a change made the command report 13
            # events as pending on every subsequent run, each with a 0.00 kg delta.
            if stored is None and abs(corrected) < 0.001:
                continue
            if stored is not None and abs(stored - corrected) < 0.001:
                continue

            changed += 1
            if stored is not None:
                reclaimed += stored - corrected
            self.stdout.write(
                f"  {event.type} id={event.id}: "
                f"{'—' if stored is None else f'{stored:.2f}'} kg -> {corrected:.2f} kg"
            )

            if not dry_run:
                with transaction.atomic():
                    # Re-fires the post_save carbon signal, which deletes the stale
                    # CarbonEntry and writes a corrected one.
                    event.save()

        verb = "would be corrected" if dry_run else "corrected"
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{changed} of {total} event(s) {verb}; " f"{reclaimed:.2f} kg CO2e of fabricated emissions removed."
            )
        )
        if dry_run:
            self.stdout.write("Dry run — nothing written. Re-run without --dry-run to apply.")

    @staticmethod
    def _stored_co2e(event):
        """The figure currently on the record, or None if no entry exists yet."""
        from carbon.event_link import entries_for_event

        entry = entries_for_event(event, link=False).order_by("-created_at", "-pk").first()
        if entry is None:
            return None
        return float(entry.co2e_amount or entry.amount or 0.0)
