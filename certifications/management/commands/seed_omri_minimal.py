"""
Seed the OMRIProduct table from the committed hand-curated CSV.

Data source: certifications/data/omri_seed.csv
  - All entries verified against the OMRI Crop Products List PDF
    (updated April 14, 2026, downloaded from
    https://www.omri.org/sites/default/files/opl_pdf/CropByProduct-NOP-EN.pdf).
  - OMRI IDs follow the publisher's format: <3-char-mfg-code>-<numeric-id>
    (e.g., dow-2900, mgk-9643).  Farmers can cross-check any entry at
    https://www.omri.org by searching the product name.

Why a CSV rather than an API:
  - OMRI does not offer a public bulk CSV/JSON/API download.
  - The OMRI website ToS restricts automated scraping.
  - Trazo does not hold an OMRI data subscription.
  - The model's own docstring documents this design decision:
    "Future upgrade path: if Trazo subscribes to OMRI's licensed list,
    replace this model with a synced local cache."

Farmer-upload alternative (not built yet):
  - A future "My Approved Products" workflow could let farmers upload a
    PDF or CSV export of their certifier-approved input list (which certifiers
    like CCOF and Oregon Tilth provide).  That would populate OMRIProduct rows
    for that farm only, keyed to the farmer's account.  This command seeds a
    global catalog for search/autocomplete; the farmer-upload workflow would
    complement it, not replace it.

Usage:
    poetry run python manage.py seed_omri_minimal
    poetry run python manage.py seed_omri_minimal --reset
"""

import csv
import os

from django.core.management.base import BaseCommand
from django.db import transaction

from certifications.models import OMRIProduct

# Absolute path so the command works regardless of cwd.
_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "omri_seed.csv",
)

REQUIRED_COLUMNS = {"omri_id", "product_name", "manufacturer", "category"}


class Command(BaseCommand):
    help = (
        "Seed the OMRIProduct table from the committed CSV "
        "(certifications/data/omri_seed.csv). Idempotent — safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing OMRIProduct rows before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if not os.path.exists(_DATA_FILE):
            self.stderr.write(
                self.style.ERROR(
                    f"Seed CSV not found at {_DATA_FILE}. " "Ensure the file is committed to the repository."
                )
            )
            return

        if opts.get("reset"):
            deleted, _ = OMRIProduct.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing OMRIProduct rows."))

        created = 0
        updated = 0

        with open(_DATA_FILE, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                self.stderr.write(self.style.ERROR(f"CSV is missing required columns: {sorted(missing)}"))
                return

            for row in reader:
                omri_id = row["omri_id"].strip()
                if not omri_id:
                    continue

                _, was_created = OMRIProduct.objects.update_or_create(
                    omri_id=omri_id,
                    defaults={
                        "product_name": row["product_name"].strip(),
                        "manufacturer": row["manufacturer"].strip() or None,
                        "category": row["category"].strip() or None,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"OMRI seed complete: {created} created, {updated} updated. "
                f"Total rows: {OMRIProduct.objects.count()}"
            )
        )
