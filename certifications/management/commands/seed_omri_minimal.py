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

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.functions import Lower

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

#: Below this many rows a CSV is a fragment, not an edition, and absence from it proves
#: nothing. The published Crop Products List held 9,278 products on 2026-09-26.
MIN_FULL_EDITION_ROWS = 5000

#: Normal attrition measured across the 2026-09-05 -> 2026-09-26 editions was 6 products in
#: three weeks. A run proposing to drop more than this fraction of the catalogue has almost
#: certainly read the wrong file.
MAX_DELIST_FRACTION = 0.02


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
            "--force-delist",
            action="store_true",
            help=(
                "Allow an edition to delist more products than normal attrition explains. "
                "Only when the mass withdrawal is real, never to push a bad parse through."
            ),
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
            # CommandError, not a stderr line and a bare return. The orchestrator records any
            # step that returns normally as IngestionRun(status="ok"), and the certifier packet
            # prints that row as "last synced" with today's date.
            raise CommandError(f"Seed CSV not found at {_DATA_FILE}. Ensure the file is committed to the repository.")

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
        seen_codes = set()
        editions = set()

        with open(_DATA_FILE, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV is missing required columns: {sorted(missing)}")

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
                seen_codes.add(omri_id.lower())
                edition = _parse_date(row.get("list_edition_date"))
                if edition:
                    editions.add(edition)
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
        self._reconcile_delistings(seen_codes, editions, force=bool(opts.get("force_delist")))

        self.stdout.write(
            self.style.SUCCESS(
                f"OMRI seed complete: {created} created, {updated} updated, "
                f"{len(rejected)} refused. Total rows: {OMRIProduct.objects.count()}"
            )
        )

    def _reconcile_delistings(self, seen_codes, editions, force=False):
        """Mark rows that have fallen off the published list, and un-mark any that returned.

        OMRI listings lapse. Measured on the September 5 -> September 26, 2026 editions:
        54 products added, 6 removed, and all six returned HTTP 404 at their own
        certificate URL. Roughly a hundred a year. Re-seeding alone never noticed, because
        `update_or_create` only ever touches rows the file contains, so a product OMRI had
        dropped kept rendering in Trazo as an OMRI listing: a third-party claim nobody had
        earned any more.

        NEVER deletes. A delisted row is still cited by whatever OSP approved it, and
        removing it cascades the approved-inputs M2M and empties that plan's
        7 CFR 205.201(a)(2) materials list. The listing is what lapsed, not the record that
        the operator once approved the material.

        Delisting is inferred from ABSENCE, which makes a truncated or partial CSV
        catastrophic: it would mark thousands of live products as dropped in one pass. Two
        guards stand in the way, and neither is optional.
        """
        if not seen_codes:
            self.stdout.write(self.style.WARNING("No rows read; skipping delisting reconciliation."))
            return

        # Guard 1 - the file must plausibly BE a full edition. The published list has run
        # well over nine thousand products; anything near the 55 rows this catalogue used to
        # carry is a fragment, and absence from a fragment means nothing at all.
        if len(seen_codes) < MIN_FULL_EDITION_ROWS:
            self.stdout.write(
                self.style.WARNING(
                    f"CSV holds {len(seen_codes)} rows, below the {MIN_FULL_EDITION_ROWS} that marks a "
                    "full edition. Skipping delisting reconciliation: absence from a partial "
                    "file is not evidence a product was dropped."
                )
            )
            return

        edition = max(editions) if editions else None
        if edition is None:
            self.stdout.write(
                self.style.WARNING(
                    "CSV carries no list_edition_date; skipping delisting reconciliation. "
                    "A delisting has to be dated to the edition that revealed it."
                )
            )
            return

        # NEVER compare `omri_id` case-sensitively here. `looks_like_omri_code` normalizes
        # before matching its shape, so "DOW-2900" passes validation and is written verbatim,
        # while `seen_codes` holds "dow-2900". A case-sensitive `__in` therefore misses the
        # row and stamps `delisted_on` on a product the very same run just re-seeded, with no
        # way to clear it afterwards. `seed_omri_from_csv` writes arbitrary codes with no
        # shape check at all, so an uppercase row is reachable. The rest of the codebase
        # already matches this column case-insensitively (`omri_id__iexact` in
        # `omri_verifier`); annotating here keeps that convention without touching the write
        # path, where lowercasing would fork an existing row into a second one.
        listed = OMRIProduct.objects.annotate(_code=Lower("omri_id"))

        returned = listed.filter(delisted_on__isnull=False, _code__in=seen_codes)
        restored = returned.count()
        if restored:
            self.stdout.write(f"{restored} previously delisted product(s) are on this edition again; clearing.")
            returned.update(delisted_on=None)

        missing = listed.filter(delisted_on__isnull=True).exclude(_code__in=seen_codes)
        count = missing.count()
        if not count:
            self.stdout.write("No delistings on this edition.")
            return

        # Guard 2 - a plausible edition can still be the WRONG list (the Livestock file, a
        # half-finished parse). Real attrition ran 6 in three weeks; a run proposing to drop
        # a large slice of the catalogue has misread something, and says so instead.
        ceiling = max(50, int(OMRIProduct.objects.count() * MAX_DELIST_FRACTION))
        if count > ceiling and not force:
            self.stdout.write(
                self.style.ERROR(
                    f"REFUSED: this edition would delist {count} products, over the {ceiling} "
                    "expected at normal attrition. That usually means the wrong file or a bad "
                    "parse, not a mass withdrawal. Re-run with --force-delist if it is real."
                )
            )
            return

        cited = [row for row in missing.prefetch_related("approving_osps") if row.approving_osps.exists()]
        self.stdout.write(self.style.WARNING(f"{count} product(s) are no longer on the OMRI list as of {edition}:"))
        for row in missing[:20]:
            self.stdout.write(self.style.WARNING(f"  {row.omri_id} {row.product_name}"))
        if count > 20:
            self.stdout.write(self.style.WARNING(f"  ... and {count - 20} more"))

        missing.update(delisted_on=edition)

        if cited:
            # The operational finding. Everything above is catalogue hygiene; this is a
            # material on somebody's filed plan that no longer carries the listing the plan
            # relies on, and a human has to tell the certifier.
            self.stdout.write(self.style.ERROR(f"\n{len(cited)} of them are on a filed OSP and need a human:"))
            for row in cited:
                plans = list(row.approving_osps.values_list("pk", flat=True))
                self.stdout.write(self.style.ERROR(f"  {row.omri_id} {row.product_name} -> OSP {plans}"))
