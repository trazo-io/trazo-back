"""
Seed CDFA OIM (Organic Input Material) registration status onto existing
OMRIProduct and WSDAMaterial rows.

Why a flat flag rather than a separate model:

    CDFA OIM is **registration metadata** about a fertilizer/amendment — not
    an independent catalog. Every CDFA-registered product is also either OMRI
    or WSDA listed (or both). Adding the reg-number + boolean to both catalogs
    keeps the detector's lookup path single-hop, and the audit PDF can render
    the reg number in the same column as the catalog ID.

Source:
    - Program page: https://www.cdfa.ca.gov/is/ffldrs/fertilizer_OIM.html
    - Labeling guide (Rev 2026-02-13):
      https://www.cdfa.ca.gov/is/ffldrs/pdfs/OIM-0047_LabelingGuide.pdf
    - CDFA publishes the registered-products list as a monthly PDF. The
      committed CSV (`certifications/data/cdfa_oim_seed.csv`) is a
      hand-curated cross-reference that pairs product brand names with
      their known CDFA OIM reg numbers. Automated PDF scraping is deferred
      to Phase 3 (see refresh_organic_input_catalogs).

Matching:
    We match by case-insensitive brand_name + manufacturer pair against both
    catalogs. Brand names are stable across the two programs (OMRI and WSDA
    both list by the manufacturer's trade name), so the join is reliable.

Usage:
    poetry run python manage.py seed_cdfa_oim
    poetry run python manage.py seed_cdfa_oim --reset
"""

import csv
import os

from django.core.management.base import BaseCommand
from django.db import transaction

from certifications.models import OMRIProduct, WSDAMaterial

_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "cdfa_oim_seed.csv",
)


class Command(BaseCommand):
    help = "Tag OMRIProduct and WSDAMaterial rows with CDFA OIM registration numbers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear all CDFA OIM flags before seeding (both catalogs).",
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
            OMRIProduct.objects.update(is_cdfa_oim_registered=False, cdfa_oim_reg_number=None)
            WSDAMaterial.objects.update(is_cdfa_oim_registered=False, cdfa_oim_reg_number=None)
            self.stdout.write(self.style.WARNING("Cleared CDFA OIM flags on both catalogs."))

        # Re-use the existing token-subsequence matcher so OMRI rows with
        # marketing-word differences ("Organic", "Fertilizer") still tag
        # correctly against the CDFA CSV's canonical brand names.
        from certifications.services.omri_verifier import _resolve_omri_by_name, _resolve_wsda_by_name

        tagged_omri = 0
        tagged_wsda = 0

        with open(_DATA_FILE, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                brand = (row.get("brand_name") or "").strip()
                reg = (row.get("cdfa_oim_reg_number") or "").strip()
                if not brand or not reg:
                    continue

                # OMRI — fuzzy resolve by brand.
                matched_omri = _resolve_omri_by_name(brand)
                if matched_omri is not None:
                    OMRIProduct.objects.filter(pk=matched_omri.pk).update(
                        is_cdfa_oim_registered=True, cdfa_oim_reg_number=reg
                    )
                    tagged_omri += 1

                # WSDA — fuzzy resolve by brand.
                matched_wsda = _resolve_wsda_by_name(brand)
                if matched_wsda is not None:
                    WSDAMaterial.objects.filter(pk=matched_wsda.pk).update(
                        is_cdfa_oim_registered=True, cdfa_oim_reg_number=reg
                    )
                    tagged_wsda += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"CDFA OIM seed complete: {tagged_omri} OMRI rows tagged, {tagged_wsda} WSDA rows tagged."
            )
        )
