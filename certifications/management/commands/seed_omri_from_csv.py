"""
Load OMRIProduct rows from an arbitrary CSV file supplied by the operator.

Intended for future use when:
  a) Trazo obtains a licensed OMRI data export, OR
  b) A certifier provides a client-specific approved-inputs list in CSV form.

The CSV must have at minimum an 'omri_id' column.  All other columns are
optional — missing values are stored as NULL.  Recognized columns:

    omri_id       (required) OMRI listing identifier, e.g. "dow-2900"
    product_name  (optional) Commercial product name
    manufacturer  (optional) Manufacturer or distributor name
    category      (optional) OMRI category code, e.g. "crop-pest-control"

Extra columns in the CSV are silently ignored so that a large certifier export
can be loaded without pre-processing.

Farmer-upload note (not built yet):
  A future workflow may allow individual farmers to upload their certifier's
  approved-inputs list.  That use-case should be implemented as a separate API
  endpoint (not this management command) so the uploaded data is scoped to the
  farmer's establishment rather than the global catalog.

Usage:
    poetry run python manage.py seed_omri_from_csv --path=/path/to/products.csv
    poetry run python manage.py seed_omri_from_csv --path=/path/to/products.csv --dry-run
    poetry run python manage.py seed_omri_from_csv --path=/path/to/products.csv --reset
"""

import csv
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from certifications.models import OMRIProduct


class Command(BaseCommand):
    help = "Load OMRIProduct rows from an arbitrary CSV file. " "Upserts by omri_id — safe to re-run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            required=True,
            help="Absolute or relative path to the CSV file to import.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and validate the CSV without writing to the database.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing OMRIProduct rows before importing.",
        )

    def handle(self, *args, **opts):
        path = opts["path"]
        dry_run = opts.get("dry_run", False)

        if not os.path.isfile(path):
            raise CommandError(f"File not found: {path}")

        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "omri_id" not in reader.fieldnames:
                raise CommandError("CSV must contain an 'omri_id' column. " f"Found columns: {reader.fieldnames}")

            rows = list(reader)

        # Validate omri_id presence on every row before committing anything.
        bad_rows = [i + 2 for i, r in enumerate(rows) if not r.get("omri_id", "").strip()]
        if bad_rows:
            raise CommandError(
                f"The following CSV rows have a blank omri_id and will be skipped: "
                f"rows {bad_rows[:10]}{'...' if len(bad_rows) > 10 else ''}. "
                "Fix the CSV and re-run, or accept that these rows will be skipped."
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(f"Dry run: {len(rows)} rows parsed from {path}. " "No database writes performed.")
            )
            return

        with transaction.atomic():
            if opts.get("reset"):
                deleted, _ = OMRIProduct.objects.all().delete()
                self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing OMRIProduct rows."))

            created = 0
            updated = 0

            for row in rows:
                omri_id = row.get("omri_id", "").strip()
                if not omri_id:
                    continue

                defaults = {}
                if row.get("product_name", "").strip():
                    defaults["product_name"] = row["product_name"].strip()
                if row.get("manufacturer", "").strip():
                    defaults["manufacturer"] = row["manufacturer"].strip()
                if row.get("category", "").strip():
                    defaults["category"] = row["category"].strip()

                if not defaults.get("product_name"):
                    # product_name is a non-null field; skip if missing.
                    self.stderr.write(self.style.WARNING(f"Skipping omri_id={omri_id!r}: missing product_name."))
                    continue

                _, was_created = OMRIProduct.objects.update_or_create(
                    omri_id=omri_id,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {created} created, {updated} updated. " f"Total rows: {OMRIProduct.objects.count()}"
            )
        )
