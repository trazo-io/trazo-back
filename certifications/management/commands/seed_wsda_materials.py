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
