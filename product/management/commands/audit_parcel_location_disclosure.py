"""Who is publishing a field boundary, and did anyone at that farm ever choose to?

WHY THIS EXISTS
---------------
`Parcel.location_disclosure_level` decides what the PUBLIC consumer page may show:

    exact       full polygon + precise map
    approximate centre rounded to ~1 km, no boundary, zoom capped
    hidden      no geodata

It gates the consumer surface only — `public_parcel_geo` is called from the transparency
endpoint, `PublicHistorySerializer` and the QR summary, and from nowhere else. The parcel
application, the parcel dashboard and the add/update parcel form read `Parcel.polygon`
directly through `CreateParcelSerializer` and are unaffected by anything this command does.

Two facts make the `exact` population worth auditing rather than assuming:

1. Migration 0013 wrote `exact` onto every parcel that existed when the setting shipped.
2. The setting was never exposed in the producer app, so nobody at those farms has seen it.

A published field boundary is not a provenance claim, it is an operating detail: the consumer
page carries the boundary, a satellite view, the harvest date and the lot quantity together.
Town and state already establish that a lot came from a real place, and the people who
genuinely need the parcel map — the certifier, the inspector — get it from the packet, which
is audience-gated. So the default is `approximate`, and `exact` should be a decision somebody
made, not one they inherited.

USAGE
-----
    poetry run python manage.py audit_parcel_location_disclosure
        Report only. Counts, and the operations affected.

    poetry run python manage.py audit_parcel_location_disclosure --apply --to-approximate
        Narrow every UNSETTLED `exact` parcel to `approximate`. Never touches a parcel whose
        farm has actually chosen `exact` — that is their call and this command must not
        overrule it. Reversible: the farm can restore `exact` from the same control that
        records the choice.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from product.models import Parcel


class Command(BaseCommand):
    help = "Report (and optionally narrow) parcels publishing a field boundary nobody chose to publish."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without it, nothing is written.",
        )
        parser.add_argument(
            "--to-approximate",
            action="store_true",
            help=(
                "Narrow UNSETTLED exact parcels to approximate. Requires --apply. Parcels whose "
                "farm explicitly chose exact are never touched."
            ),
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        narrow = options["to_approximate"]

        total = Parcel.objects.count()
        by_level = {
            level: Parcel.objects.filter(location_disclosure_level=level).count()
            for level, _label in Parcel.LOCATION_DISCLOSURE_CHOICES
        }
        exact_qs = Parcel.objects.filter(location_disclosure_level="exact")
        unsettled = exact_qs.filter(location_disclosure_choice_made=False)
        chosen = exact_qs.filter(location_disclosure_choice_made=True)
        # A level of `exact` with no polygon on file publishes no boundary in practice — the
        # gate would hand out `None`. Worth separating so the number that matters is the number
        # of farms actually exposed, not the number of rows carrying a string.
        unsettled_with_boundary = unsettled.exclude(polygon__isnull=True).exclude(polygon=[])

        self.stdout.write(f"parcels: {total}")
        for level, count in by_level.items():
            self.stdout.write(f"  {level:<12} {count}")
        self.stdout.write("")
        self.stdout.write(f"exact, chosen by the farm      : {chosen.count()}")
        self.stdout.write(f"exact, inherited (never asked) : {unsettled.count()}")
        self.stdout.write(f"  ...of those, actually publishing a boundary: {unsettled_with_boundary.count()}")

        operations = sorted(
            {
                (p.establishment.company.name, p.establishment.name)
                for p in unsettled_with_boundary.select_related("establishment__company")
                if p.establishment and p.establishment.company
            }
        )
        if operations:
            self.stdout.write("")
            self.stdout.write("operations publishing an inherited boundary:")
            for company, establishment in operations:
                self.stdout.write(f"  {company} — {establishment}")

        if not narrow:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Report only. Re-run with --apply --to-approximate to narrow the inherited set, "
                    "or leave it and let the in-app prompt collect a real answer from each farm."
                )
            )
            return

        if not apply_changes:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("--to-approximate needs --apply. Nothing written."))
            return

        with transaction.atomic():
            # `choice_made` is deliberately NOT set here. Narrowing on the farm's behalf is a
            # safety default, not a decision they made, so the prompt must still ask — otherwise
            # this command would silently consume the very consent it exists to obtain.
            changed = unsettled.update(location_disclosure_level="approximate")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Narrowed {changed} parcel(s) to approximate."))
        self.stdout.write(
            "Polygons are untouched on the model — the parcel application, the dashboard map and "
            "the parcel form still read them. Only the public consumer page changes, and any farm "
            "can restore exact from the prompt."
        )
