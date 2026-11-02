"""
Flag OMRIProduct and WSDAMaterial rows that are also CDFA OIM registered.

Why a flat flag rather than a separate model:

    CDFA OIM is **registration metadata** about a fertilizer/amendment — not
    an independent catalog. A product registered in CA is normally OMRI or WSDA
    listed as well, so the flag rides on the catalog rows the detector already
    resolves, keeping its lookup path single-hop.

Source:
    - Program page: https://www.cdfa.ca.gov/is/ffldrs/fertilizer_OIM.html
    - Registered products list (PDF, "Updated 8/7/2026", 91 pages):
      https://www.cdfa.ca.gov/is/ffldrs/pdfs/RegisteredOrganicInputMaterial2026.pdf
    - Committed CSV: certifications/data/cdfa_oim_seed.csv — 2,800 rows transcribed
      from that edition on 2026-09-06.

⛔ THERE IS NO REGISTRATION NUMBER. The published list has exactly three columns —
   Firm | Product Name, Brand or Trademark | Applicable Annotations. CDFA publishes no
   identifier, so this command writes `is_cdfa_oim_registered` and NOTHING ELSE. Every
   `CDFA-OIM-NH-231`-style value this seeder used to stamp onto catalog rows was a
   brand-name mnemonic invented by Trazo. `cdfa_oim_reg_number` is never written here.

⛔ MATCHING IS EXACT, NEVER FUZZY. Until 2026-09-06 this command called
   `_resolve_omri_by_name` / `_resolve_wsda_by_name` — the token-subsequence matcher — and
   PERSISTED the winner. Replayed, it stamped the CDFA registration of *Kelp Meal 1-0.2-2*
   onto OMRI's *Kelp Meal 1-0.1-2* row: a different registered product, marked registered
   on the strength of a guess. The repo's own rule is that the fuzzy matcher is right for
   search and wrong as a persisted claim (`InputVerifyHelper.tsx`). So:

     - names are compared after case/whitespace normalisation ONLY (`_normalize`);
     - a CDFA row that matches nothing is SKIPPED AND COUNTED, never widened to a guess;
     - a CDFA row whose name matches MORE THAN ONE catalog row is skipped too — an
       ambiguous match cannot say which product carries the registration.

Usage:
    poetry run python manage.py seed_cdfa_oim
    poetry run python manage.py seed_cdfa_oim --reset
"""

import csv
import os
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from certifications.models import OMRIProduct, WSDAMaterial
from certifications.services.omri_verifier import _normalize

_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "cdfa_oim_seed.csv",
)


def _index(queryset, name_field):
    """Map normalized name -> list of pks. A name held by two rows stays ambiguous."""
    index = defaultdict(list)
    for pk, name in queryset.values_list("pk", name_field):
        index[_normalize(name)].append(pk)
    return index


class Command(BaseCommand):
    help = "Flag OMRIProduct and WSDAMaterial rows that are also CDFA OIM registered (exact name match)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear all CDFA OIM flags before seeding (both catalogs).",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if not os.path.exists(_DATA_FILE):
            # CommandError, not a stderr line and a bare return. The orchestrator records any
            # step that returns normally as IngestionRun(status="ok"), and the certifier packet
            # prints that row as "last synced" with today's date.
            raise CommandError(f"Seed CSV not found at {_DATA_FILE}. Ensure the file is committed to the repository.")

        if opts.get("reset"):
            OMRIProduct.objects.update(is_cdfa_oim_registered=False, cdfa_oim_reg_number=None)
            WSDAMaterial.objects.update(is_cdfa_oim_registered=False, cdfa_oim_reg_number=None)
            self.stdout.write(self.style.WARNING("Cleared CDFA OIM flags on both catalogs."))

        omri_index = _index(OMRIProduct.objects.all(), "product_name")
        wsda_index = _index(WSDAMaterial.objects.all(), "brand_name")

        omri_hits, wsda_hits = set(), set()
        rows = matched = ambiguous = unmatched = 0

        with open(_DATA_FILE, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                product = (row.get("product_name") or "").strip()
                if not product:
                    continue
                rows += 1
                key = _normalize(product)
                o, w = omri_index.get(key, []), wsda_index.get(key, [])
                if len(o) > 1 or len(w) > 1:
                    ambiguous += 1
                    continue
                if not o and not w:
                    unmatched += 1
                    continue
                omri_hits.update(o)
                wsda_hits.update(w)
                matched += 1

        # `cdfa_oim_reg_number` is deliberately absent from both updates: CDFA
        # publishes no number, so there is none to write.
        OMRIProduct.objects.filter(pk__in=omri_hits).update(is_cdfa_oim_registered=True)
        WSDAMaterial.objects.filter(pk__in=wsda_hits).update(is_cdfa_oim_registered=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"CDFA OIM seed complete: {len(omri_hits)} OMRI rows and {len(wsda_hits)} WSDA "
                f"rows flagged registered, from {rows} published CDFA rows "
                f"({matched} matched exactly, {ambiguous} skipped as ambiguous, "
                f"{unmatched} matched no catalog row)."
            )
        )
