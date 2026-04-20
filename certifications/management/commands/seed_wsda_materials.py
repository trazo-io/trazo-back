"""
Seed the WSDAMaterial table from the committed CSV snapshot.

Source: WSDA Organic Brand Name Materials List
  - Public list (PDF/Excel):
    https://cms.agr.wa.gov/getmedia/6322228c-c949-44a2-926c-2a86739269e3/
    WSDA_Organic_Input_Material_List
  - Program page: https://agr.wa.gov/departments/organic/input-material-registration
  - Committed CSV: certifications/data/wsda_seed.csv

WSDA is treated co-equally with OMRI by CCOF and most US certifiers — the two
programs have different review cadences and fee structures, so many products
are listed on only one. Checking both eliminates a large source of
false-positive drift findings for CA/PNW growers.

This command is idempotent (upsert by wsda_id) — safe to re-run as often as
the CSV is refreshed. Refresh cadence: monthly, aligned with WSDA's list
publication. For automation, see refresh_organic_input_catalogs.

Future upgrade (Phase 3):
    Replace the committed CSV with a direct fetch of the WSDA
    upstream CSV/Excel when WSDA publishes a stable machine-readable URL.
    The current committed snapshot captures only the common-subset most
    relevant for a CA organic pilot (~40 products); the full list has
    ~1,500.

Usage:
    poetry run python manage.py seed_wsda_materials
    poetry run python manage.py seed_wsda_materials --reset
"""

import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from certifications.models import WSDAMaterial

_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "wsda_seed.csv",
)

REQUIRED_COLUMNS = {"wsda_id", "brand_name", "manufacturer", "category"}


def _parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


class Command(BaseCommand):
    help = (
        "Seed the WSDAMaterial table from the committed WSDA CSV snapshot "
        "(certifications/data/wsda_seed.csv). Idempotent — safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing WSDAMaterial rows before seeding.",
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
            deleted, _ = WSDAMaterial.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing WSDAMaterial rows."))

        created = 0
        updated = 0

        with open(_DATA_FILE, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                self.stderr.write(self.style.ERROR(f"CSV is missing required columns: {sorted(missing)}"))
                return

            for row in reader:
                wsda_id = (row.get("wsda_id") or "").strip()
                if not wsda_id:
                    continue

                _, was_created = WSDAMaterial.objects.update_or_create(
                    wsda_id=wsda_id,
                    defaults={
                        "brand_name": (row.get("brand_name") or "").strip(),
                        "manufacturer": (row.get("manufacturer") or "").strip() or None,
                        "category": (row.get("category") or "").strip() or None,
                        "list_effective_date": _parse_date(row.get("list_effective_date")),
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"WSDA seed complete: {created} created, {updated} updated. "
                f"Total rows: {WSDAMaterial.objects.count()}"
            )
        )
