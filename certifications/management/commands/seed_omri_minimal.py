"""
Seed the OMRIProduct table from the committed hand-curated CSV.

Data source: certifications/data/omri_seed.csv
  - Every row is transcribed from the FREE public OMRI Crop Products List PDF,
    https://www.omri.org/sites/default/files/opl_pdf/CropByProduct-NOP-EN.pdf
    (edition "Updated September 5, 2026"), and cross-checked for presence against
    the companion CropByCompany-NOP-EN.pdf. Re-verified row by row 2026-09-06.
  - OMRI IDs use the publisher's own format — company letters, hyphen, product
    number (dow-2900, mgk-9643) — documented at https://www.omri.org/using-omri-search.
    Shape is enforced here by `looks_like_omri_code`, the single definition of that
    pattern (certifications.services.omri_verifier), so this command cannot seed a
    code the rest of the system would refuse to recognise.

⛔ The "OMRI is paid / scraping is barred, so the list must be hand-typed" premise that
   used to stand here was FALSE, and it is what let 5 lapsed listings and 45 wrong
   name/company strings survive in this catalogue. The full list is a free download.

What this command will NOT do:
  - It never invents an expiration date. `listing_expiration_date` is absent from the
    PDF (it is printed only on the per-product certificate), so it is seeded NULL and a
    NULL means UNKNOWN — never "current".

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
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from certifications.models import OMRIProduct
from certifications.services.catalog_integrity import assert_safe_to_reset
from certifications.services.omri_verifier import looks_like_omri_code

# Absolute path so the command works regardless of cwd.
_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "omri_seed.csv",
)

REQUIRED_COLUMNS = {"omri_id", "product_name"}


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
        "Seed the OMRIProduct table from the committed CSV "
        "(certifications/data/omri_seed.csv). Idempotent — safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing OMRIProduct rows before seeding.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Allow --reset to delete rows that Organic System Plans cite. "
                "Those materials leave the plans; § 205.400(f)(2) makes that a "
                "change the operator must notify their certifier about."
            ),
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
            # ⛔ A catalog row an OSP cites is part of that operator's § 205.201(a)(2) filing.
            # `.all().delete()` cascades the approved-inputs M2M, so replacing the catalog used
            # to empty every plan's materials list in silence — four OMRI products and two WSDA
            # materials disappeared from the pilot farm's plans this way on 2026-09-07, leaving
            # only the append-only change log as evidence they had ever been there.
            forced = assert_safe_to_reset(OMRIProduct, force=bool(opts.get("force")))
            if forced:
                self.stdout.write(
                    self.style.WARNING(
                        f"--force: deleting {len(forced)} row(s) cited by an OSP. " "Those plans lose these materials:"
                    )
                )
                for line in forced:
                    self.stdout.write(self.style.WARNING(f"  {line}"))
            deleted, _ = OMRIProduct.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing OMRIProduct rows."))

        created = 0
        updated = 0
        rejected = []

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
                if not looks_like_omri_code(omri_id):
                    rejected.append(omri_id)
                    continue

                _, was_created = OMRIProduct.objects.update_or_create(
                    omri_id=omri_id,
                    defaults={
                        "product_name": row["product_name"].strip(),
                        "manufacturer": (row.get("manufacturer") or "").strip() or None,
                        "category": (row.get("category") or "").strip() or None,
                        "list_edition_date": _parse_date(row.get("list_edition_date")),
                        "listing_expiration_date": _parse_date(row.get("listing_expiration_date")),
                        "source_url": (row.get("source_url") or "").strip() or None,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        if rejected:
            self.stderr.write(
                self.style.ERROR(
                    f"Refused {len(rejected)} row(s) whose omri_id is not OMRI's published "
                    f"code shape: {rejected[:10]}"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"OMRI seed complete: {created} created, {updated} updated, "
                f"{len(rejected)} refused. Total rows: {OMRIProduct.objects.count()}"
            )
        )
