"""Report Company/Establishment rows whose `state` will not resolve.

Read-only. Run this against production BEFORE the state-normalization data
migration to size the blast radius, and again afterwards to see what is left
for a human to fix.

Why it matters: every regional lookup (irrigation depth, precipitation, USDA
regional factors, the CA-only compliance surfaces) keys on the canonical
2-letter code. A row holding "California" or "" resolves to nothing, so the
farm silently falls back to national defaults — which is correct behavior, but
only if somebody knows it is happening.

    poetry run python manage.py audit_state_values
    poetry run python manage.py audit_state_values --unresolved-only
"""

from django.core.management.base import BaseCommand

from common.us_states import normalize_state
from company.models import Company, Establishment


class Command(BaseCommand):
    help = "Report Company/Establishment rows whose state value does not resolve to a US state code."

    def add_arguments(self, parser):
        parser.add_argument(
            "--unresolved-only",
            action="store_true",
            help="Only list rows that cannot be resolved at all (skip ones the migration will fix).",
        )

    def handle(self, *args, **options):
        unresolved_only = options["unresolved_only"]

        total = 0
        already_canonical = 0
        fixable = []
        unresolved = []

        for model in (Company, Establishment):
            for row in model.objects.all().only("id", "name", "state"):
                total += 1
                raw = row.state or ""
                resolved = normalize_state(raw)

                if resolved and resolved == raw:
                    already_canonical += 1
                elif resolved:
                    fixable.append((model.__name__, row.pk, getattr(row, "name", ""), raw, resolved))
                else:
                    unresolved.append((model.__name__, row.pk, getattr(row, "name", ""), raw))

        if fixable and not unresolved_only:
            self.stdout.write(self.style.WARNING(f"\nNormalizable by the migration ({len(fixable)}):"))
            for model_name, pk, name, raw, resolved in fixable:
                self.stdout.write(f"  {model_name} #{pk} {name!r}: {raw!r} -> {resolved!r}")

        if unresolved:
            self.stdout.write(self.style.ERROR(f"\nUNRESOLVED — needs a human ({len(unresolved)}):"))
            for model_name, pk, name, raw in unresolved:
                label = "blank" if not raw.strip() else repr(raw)
                self.stdout.write(f"  {model_name} #{pk} {name!r}: {label}")

        self.stdout.write("")
        self.stdout.write(f"Rows checked:      {total}")
        self.stdout.write(f"Already canonical: {already_canonical}")
        self.stdout.write(f"Migration fixes:   {len(fixable)}")
        self.stdout.write(f"Unresolved:        {len(unresolved)}")

        if unresolved:
            self.stdout.write(
                self.style.WARNING(
                    "\nUnresolved rows fall back to national defaults. That is safe, but they get "
                    "no regional factors and no state-specific compliance surfaces until corrected."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS("\nEvery row resolves to a US state code."))
