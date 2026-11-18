"""
Seed the WSDAMaterial table from the committed CSV snapshot.

Source: WSDA Organic Input Material List — a FREE public PDF, no licence needed:
  https://cms.agr.wa.gov/WSDAKentico/Documents/FSCS/Organic/Pubs_organic/WSDA_Organic_Input_Material_List.pdf
  - Program page: https://agr.wa.gov/departments/organic/input-material-registration
  - Committed CSV: certifications/data/wsda_seed.csv — 782 rows transcribed from the
    March 06, 2026 edition (parsed 2026-09-06), one row per published product. Its
    `annotation` column, WSDA's own Annotation column verbatim ("NONE" where WSDA prints
    it), was transcribed from the same edition on 2026-11-17.

The CSV's `wsda_id` is the list's own **WSDA Product #**, a bare integer. It is NOT
decorative: `registry_identifiers.wsda_identifier_label` prints an identifier only when
it matches `^\\d+$`, so these values are exactly what makes a WSDA identifier appear in
a certifier packet at all. The 42 hand-typed `WSDA-REG-BIOAG-2025-001`-style rows this
file used to carry were a shape WSDA does not issue, and most named products that are
not on the list.

WSDA is treated co-equally with OMRI by CCOF and most US certifiers — the two
programs have different review cadences and fee structures, so many products
are listed on only one. Checking both eliminates a large source of
false-positive drift findings for CA/PNW growers.

This command is idempotent (upsert by wsda_id) — safe to re-run as often as
the CSV is refreshed. WSDA republishes quarterly; `list_effective_date` and
`source_url` record which edition each row came from. For automation, see
refresh_organic_input_catalogs.

Usage:
    poetry run python manage.py seed_wsda_materials
    poetry run python manage.py seed_wsda_materials --reset
"""

import csv
import os
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from certifications.models import WSDAMaterial
from certifications.services.catalog_integrity import assert_safe_to_reset
from certifications.services.registry_identifiers import WSDA_PRODUCT_NUMBER_RE

_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "wsda_seed.csv",
)

# `manufacturer` is NOT required: it is present in this list (WSDA groups products under a
# registrant heading) but a future edition or a certifier-supplied export may not carry one,
# and a missing registrant must leave the column empty rather than invite a guess.
REQUIRED_COLUMNS = {"wsda_id", "brand_name"}

#: Below this many rows a CSV is a fragment, not an edition, and absence from it proves nothing.
#: The March 06, 2026 list held 782 products.
MIN_FULL_EDITION_ROWS = 500

#: WSDA registrants renew every year by October 31 and a lapsed registration leaves the next
#: edition, so a yearly edition can drop far more than OMRI's three-week attrition. A run proposing
#: to drop more than this fraction has still almost certainly read the wrong file or a bad parse.
MAX_DELIST_FRACTION = 0.15


def _parse_year(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _parse_annotation(value):
    """WSDA's Annotation cell: its text, "" for WSDA's NONE, None for an empty cell (not transcribed).

    NONE is stored as "", never as None: WSDA printed it, so the absence of an annotation is a fact
    about the listing. It is still never read as "no restrictions" (the label can restrict use)."""
    value = " ".join((value or "").split())
    if not value:
        return None
    return "" if value.upper() == "NONE" else value


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
        parser.add_argument(
            "--force-delist",
            action="store_true",
            help=(
                "Allow an edition to mark more products as no longer listed than normal attrition "
                "explains. Only when the drop is real, never to push a bad parse through."
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
            forced = assert_safe_to_reset(WSDAMaterial, force=bool(opts.get("force")))
            if forced:
                self.stdout.write(
                    self.style.WARNING(
                        f"--force: deleting {len(forced)} row(s) cited by an OSP. " "Those plans lose these materials:"
                    )
                )
                for line in forced:
                    self.stdout.write(self.style.WARNING(f"  {line}"))
            deleted, _ = WSDAMaterial.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Deleted {deleted} existing WSDAMaterial rows."))

        created = 0
        updated = 0
        rejected = []
        seen_ids = set()
        editions = set()

        with open(_DATA_FILE, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"CSV is missing required columns: {sorted(missing)}")

            # A CSV without the column (an older snapshot, or an export that does not carry it) leaves
            # every stored annotation as it is, rather than blanking it to "not transcribed".
            has_annotation = "annotation" in (reader.fieldnames or [])

            for row in reader:
                wsda_id = (row.get("wsda_id") or "").strip()
                if not wsda_id:
                    continue

                if not WSDA_PRODUCT_NUMBER_RE.match(wsda_id):
                    # A non-integer id is withheld from every reader anyway, so seeding one
                    # would only put an unprintable row in the catalogue.
                    rejected.append(wsda_id)
                    continue

                defaults = {
                    "brand_name": (row.get("brand_name") or "").strip(),
                    "manufacturer": (row.get("manufacturer") or "").strip() or None,
                    "category": (row.get("category") or "").strip() or None,
                    "subtype": (row.get("subtype") or "").strip() or None,
                    "initial_approval_year": _parse_year(row.get("initial_approval_year")),
                    "list_effective_date": _parse_date(row.get("list_effective_date")),
                    "source_url": (row.get("source_url") or "").strip() or None,
                }
                if has_annotation:
                    defaults["annotation"] = _parse_annotation(row.get("annotation"))
                seen_ids.add(wsda_id)
                if defaults["list_effective_date"]:
                    editions.add(defaults["list_effective_date"])
                _, was_created = WSDAMaterial.objects.update_or_create(wsda_id=wsda_id, defaults=defaults)
                if was_created:
                    created += 1
                else:
                    updated += 1

        if rejected:
            self.stderr.write(
                self.style.ERROR(
                    f"Refused {len(rejected)} row(s) whose wsda_id is not a WSDA Product # "
                    f"(a bare integer): {rejected[:10]}"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"WSDA seed complete: {created} created, {updated} updated, "
                f"{len(rejected)} refused. Total rows: {WSDAMaterial.objects.count()}"
            )
        )
        self._reconcile_delistings(seen_ids, editions, force=bool(opts.get("force_delist")))

    def _reconcile_delistings(self, seen_ids, editions, force=False):
        """Mark the rows this edition no longer carries, and clear the ones it carries again.

        Overall review 2026-11, OV-MT-C04: OMRI rows carried `delisted_on` and WSDA rows had nothing,
        so a product WSDA dropped in a later edition kept reading as WSDA-listed on the plan, the
        record, the dossier and the buyer page. Same rules as `seed_omri_minimal`:

        NEVER deletes. A row a plan cites is part of that plan's 7 CFR 205.201(a)(2) materials list;
        what lapsed is the listing, not the record that the operator once approved the material.

        Delisting is inferred from ABSENCE, so a partial or wrong file would mark live products as
        dropped. Three guards: the file must be a full edition (MIN_FULL_EDITION_ROWS), it must carry
        an edition date, and it may not drop more than MAX_DELIST_FRACTION without --force-delist.
        Only rows that came from an earlier edition are candidates: a row entered by hand, with no
        edition date, was never on a list Trazo read, so its absence from this one says nothing.
        """
        if not seen_ids:
            self.stdout.write(self.style.WARNING("No rows read; skipping delisting reconciliation."))
            return
        if len(seen_ids) < MIN_FULL_EDITION_ROWS:
            self.stdout.write(
                self.style.WARNING(
                    f"CSV holds {len(seen_ids)} rows, below the {MIN_FULL_EDITION_ROWS} that mark a full "
                    "edition. Skipping delisting reconciliation: absence from a partial file is not "
                    "evidence a product was dropped."
                )
            )
            return
        edition = max(editions) if editions else None
        if edition is None:
            self.stdout.write(
                self.style.WARNING(
                    "CSV carries no list_effective_date; skipping delisting reconciliation. A delisting "
                    "has to be dated to the edition that revealed it."
                )
            )
            return

        returned = WSDAMaterial.objects.filter(delisted_on__isnull=False, wsda_id__in=seen_ids)
        restored = returned.count()
        if restored:
            self.stdout.write(f"{restored} previously delisted product(s) are on this edition again; clearing.")
            returned.update(delisted_on=None)

        missing = WSDAMaterial.objects.filter(
            delisted_on__isnull=True, list_effective_date__isnull=False, list_effective_date__lt=edition
        ).exclude(wsda_id__in=seen_ids)
        count = missing.count()
        if not count:
            self.stdout.write("No delistings on this edition.")
            return

        ceiling = max(25, int(WSDAMaterial.objects.count() * MAX_DELIST_FRACTION))
        if count > ceiling and not force:
            self.stdout.write(
                self.style.ERROR(
                    f"REFUSED: this edition would delist {count} products, over the {ceiling} expected "
                    "from yearly renewals. That usually means the wrong file or a bad parse, not a mass "
                    "withdrawal. Re-run with --force-delist if it is real."
                )
            )
            return

        cited = [row for row in missing.prefetch_related("approving_osps") if row.approving_osps.exists()]
        self.stdout.write(self.style.WARNING(f"{count} product(s) are no longer on the WSDA list as of {edition}:"))
        for row in missing[:20]:
            self.stdout.write(self.style.WARNING(f"  {row.wsda_id} {row.brand_name}"))
        if count > 20:
            self.stdout.write(self.style.WARNING(f"  ... and {count - 20} more"))
        missing.update(delisted_on=edition)
        if cited:
            self.stdout.write(self.style.ERROR(f"\n{len(cited)} of them are on a filed OSP and need a human:"))
            for row in cited:
                plans = list(row.approving_osps.values_list("pk", flat=True))
                self.stdout.write(self.style.ERROR(f"  {row.wsda_id} {row.brand_name} -> OSP {plans}"))
