"""Backfill ChemicalEvent.volume_numeric / area_numeric from their legacy string twins.

`volume` / `area` are the CharFields the event wizard has always posted; `volume_numeric` /
`area_numeric` are what every computation reads — the certifier packet's rate-per-area, the
audit CSV, the CA PUR export, record completeness. Nothing derived the numeric pair on write
until 2026-08-19, so every spray a farmer entered through the UI stored the string and left
the numeric NULL, and the packet printed a total with no rate beside it. Seeded demo events
set both directly, which is why the gap never showed in a demo.

The write path is fixed (`_leading_number` in history/serializers.py). This command repairs
the records written before it.

    poetry run python manage.py backfill_chemical_numeric_twins --dry-run
    poetry run python manage.py backfill_chemical_numeric_twins

Only fills a NULL twin — an existing value is never overwritten, and a string with no leading
number is left alone rather than becoming a zero measurement.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from history.models import ChemicalEvent
from history.serializers import _leading_number

#: Rows per UPDATE. Large enough that the run is a handful of statements, small enough that
#: no single transaction holds locks for long.
BATCH_SIZE = 500


class Command(BaseCommand):
    help = "Populate ChemicalEvent.volume_numeric / area_numeric from the legacy volume / area strings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        pairs = (("volume", "volume_numeric"), ("area", "area_numeric"))

        candidates = (
            ChemicalEvent.objects.filter(Q(volume_numeric__isnull=True) | Q(area_numeric__isnull=True))
            .only("pk", "volume", "volume_numeric", "area", "area_numeric")
            .order_by("pk")
        )

        filled = {"volume_numeric": 0, "area_numeric": 0}
        unparseable = []
        touched = 0
        batch = []

        def _flush(rows):
            """Write one batch with bulk_update — deliberately NOT save().

            `save(update_fields=[...])` still fires `post_save`, so an earlier draft of this
            command recalculated the carbon entry of every one of the 223 records it touched.
            These are records already filed with a certifier; a backfill that repairs a
            derived column must not rewrite anything else about them. `bulk_update` issues a
            single UPDATE and fires no signals, which is what the intent was all along.
            """
            if rows and not dry_run:
                ChemicalEvent.objects.bulk_update(rows, ["volume_numeric", "area_numeric"])

        # One transaction per batch, not one across the whole table: on a production-sized
        # table a single atomic block would hold locks for the length of the run.
        for event in candidates.iterator(chunk_size=BATCH_SIZE):
            updates = []
            for string_field, numeric_field in pairs:
                if getattr(event, numeric_field) is not None:
                    continue
                raw = getattr(event, string_field)
                if raw in (None, ""):
                    continue
                parsed = _leading_number(raw)
                if parsed is None:
                    unparseable.append((event.pk, string_field, raw))
                    continue
                setattr(event, numeric_field, parsed)
                updates.append(numeric_field)
                filled[numeric_field] += 1
            if updates:
                touched += 1
                batch.append(event)
            if len(batch) >= BATCH_SIZE:
                with transaction.atomic():
                    _flush(batch)
                batch = []

        if batch:
            with transaction.atomic():
                _flush(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Would fill' if dry_run else 'Filled'} volume_numeric on {filled['volume_numeric']} "
                f"and area_numeric on {filled['area_numeric']} record(s) across {touched} event(s)."
            )
        )
        if unparseable:
            self.stdout.write(
                self.style.WARNING(f"{len(unparseable)} value(s) had no leading number and were left NULL:")
            )
            for pk, field, raw in unparseable[:20]:
                self.stdout.write(f"  event {pk} {field}={raw!r}")
            if len(unparseable) > 20:
                self.stdout.write(f"  ... and {len(unparseable) - 20} more")
