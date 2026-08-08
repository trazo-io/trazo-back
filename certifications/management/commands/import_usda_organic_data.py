"""
Import USDA Organic Integrity Database from the monthly bulk XLSX export.

Downloads the latest monthly export from:
https://organic.ams.usda.gov/Integrity/MonthlyReports/INTEGRITY_Export_YYYYMM01.xlsx

Usage:
    poetry run python manage.py import_usda_organic_data
    poetry run python manage.py import_usda_organic_data --file /path/to/local.xlsx
    poetry run python manage.py import_usda_organic_data --date 2026-03-01
    poetry run python manage.py import_usda_organic_data --dry-run   # parse only, write nothing

This table is REPLACED on every run (delete-then-insert inside one transaction), which makes a
bad parse silently destructive: if the upstream export renames a column, the parser yields few
or no rows, every existing row is deleted, and the run still reports success. Every farm's
organic badge then flips to self-reported at once, because
`certifications/services/consumer_claim_validator.py` gates the badge on a database match.

So the import refuses to replace good data with implausible data — see `_check_replacement_is_safe`.
A refused import leaves the previous snapshot intact, which is stale but true; the alternative is
an empty table, which reads as "no farm in America is certified".
"""

from __future__ import annotations

import os
import re
import tempfile
from argparse import BooleanOptionalAction
from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import requests

from certifications.models import IngestionRun, USDAOrganicOperation
from certifications.services.reference_data_status import reset_reference_data_cache

USDA_MONTHLY_URL = "https://organic.ams.usda.gov/Integrity/MonthlyReports/INTEGRITY_Export_{date}.xlsx"

# Words to strip from farm names for normalized search
STRIP_WORDS = {
    "llc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "farm",
    "farms",
    "ranch",
    "ranches",
    "orchard",
    "orchards",
    "vineyard",
    "vineyards",
    "estate",
    "estates",
    "co",
    "company",
    "the",
    "and",
    "of",
    "dba",
    "ltd",
    "limited",
}


def normalize_name(name: str) -> str:
    """Normalize a farm name for fuzzy search."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name)
    words = [w for w in name.split() if w not in STRIP_WORDS]
    return " ".join(words).strip()


# A parse that yields fewer rows than this is not a real USDA export — the smallest plausible
# national snapshot is tens of thousands of operations. Used only when the table is empty, where
# there is no previous count to compare against.
MIN_PLAUSIBLE_RECORDS = 1000

# Replacing the table with less than this fraction of what it already held means the parser
# almost certainly lost columns or rows. Overridable with --allow-shrink for a genuine contraction.
MIN_RETAINED_FRACTION = 0.5


class Command(BaseCommand):
    help = "Import USDA Organic Integrity Database from monthly bulk XLSX export"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            help="Path to a local XLSX file instead of downloading",
        )
        parser.add_argument(
            "--date",
            type=str,
            help="Snapshot date in YYYYMMDD format (default: current month's 1st)",
        )
        parser.add_argument(
            "--us-only",
            action=BooleanOptionalAction,
            default=True,
            help="Only import US operations (default: enabled; disable with --no-us-only)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report what WOULD be imported, then exit without writing.",
        )
        parser.add_argument(
            "--allow-shrink",
            action="store_true",
            # NOTE: argparse runs %-formatting over help strings, so a literal "%" here raises
            # TypeError when --help is rendered. Spell the fraction out instead of interpolating
            # a percentage.
            help=(
                "Permit an import that would drop the operation count below "
                f"{MIN_RETAINED_FRACTION} of the current table. Required when USDA "
                "genuinely publishes a much smaller export; never use it to force through "
                "a parse you have not inspected."
            ),
        )

    def handle(self, *args, **options):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            raise CommandError("openpyxl is required for XLSX parsing. " "Install it with: poetry add openpyxl")

        file_path = options.get("file")

        if file_path:
            if not os.path.exists(file_path):
                raise CommandError(f"File not found: {file_path}")
            # Honour --date here too. Stamping a local file with today's date would claim the
            # data is current when it may be months old, and data_snapshot_date is the only
            # record of how fresh the badge evidence actually is.
            if options.get("date"):
                snapshot_date = self._parse_snapshot_date(options["date"])
            else:
                snapshot_date = date.today()
                self.stdout.write(
                    self.style.WARNING(
                        "No --date given with --file; stamping this snapshot as today "
                        f"({snapshot_date}). Pass --date YYYYMMDD to record when USDA "
                        "actually published it."
                    )
                )
            self.stdout.write(f"Using local file: {file_path}")
        else:
            # Determine the download URL
            if options.get("date"):
                snapshot_date = self._parse_snapshot_date(options["date"])
            else:
                snapshot_date = date.today().replace(day=1)

            date_str = snapshot_date.strftime("%Y%m%d")
            url = USDA_MONTHLY_URL.format(date=date_str)
            self.stdout.write(f"Downloading USDA data from: {url}")

            file_path = self._download_file(url)
            if not file_path:
                # Try previous month
                prev_month = snapshot_date.month - 1 or 12
                prev_year = snapshot_date.year if snapshot_date.month > 1 else snapshot_date.year - 1
                date_str = f"{prev_year}{prev_month:02d}01"
                snapshot_date = datetime.strptime(date_str, "%Y%m%d").date()
                url = USDA_MONTHLY_URL.format(date=date_str)
                self.stdout.write(f"Current month not available, trying: {url}")
                file_path = self._download_file(url)

            if not file_path:
                raise CommandError("Could not download USDA export. Try --file with a local copy.")

        self.stdout.write("Parsing XLSX file...")
        records = self._parse_xlsx(file_path, us_only=options.get("us_only", True))

        existing_count = USDAOrganicOperation.objects.count()
        self.stdout.write(f"Parsed {len(records)} operations (table currently holds {existing_count}).")

        allow_shrink = options.get("allow_shrink", False)

        # --dry-run is the tool an operator reaches for BECAUSE an import was refused, so the
        # parse breakdown has to be printed BEFORE the verdict. Checking first would make the
        # advice in _check_replacement_is_safe ("inspect with --dry-run") impossible to follow:
        # the dry run would die on the same error, showing nothing. The refusal is still raised
        # afterwards so the exit code stays honest.
        if options.get("dry_run"):
            states = {}
            for r in records:
                states[r["state"]] = states.get(r["state"], 0) + 1
            top = sorted(states.items(), key=lambda kv: -kv[1])[:5]
            summary = ", ".join("{}={}".format(state or "(blank)", count) for state, count in top)
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN — nothing written. Would replace {existing_count} row(s) with "
                    f"{len(records)} (snapshot: {snapshot_date}). Top states: {summary}"
                )
            )
            try:
                self._check_replacement_is_safe(
                    new_count=len(records),
                    existing_count=existing_count,
                    allow_shrink=allow_shrink,
                )
            except CommandError as exc:
                # The diagnostic above is already on stdout, which is the point of --dry-run.
                # Re-raise so the exit code is honest: a dry run that reports a refusal must not
                # exit 0, or `--dry-run && <real import>` would sail straight past it.
                self.stdout.write(self.style.ERROR("WOULD BE REFUSED — see below."))
                raise
            self.stdout.write(self.style.SUCCESS("Safety check passed — this import would proceed."))
            return

        # Refuse BEFORE deleting anything. The delete and the insert share a transaction, so a
        # crash would roll back — but an empty parse is not a crash, it commits happily.
        self._check_replacement_is_safe(
            new_count=len(records),
            existing_count=existing_count,
            allow_shrink=allow_shrink,
        )

        self.stdout.write("Importing...")
        self._import_records(records, snapshot_date)

        final_count = USDAOrganicOperation.objects.count()

        # Audit row so "when was the USDA mirror last synced?" has an answer. IngestionRun exists
        # exactly for this question but had no source for this dataset, which is part of why the
        # snapshot could go stale unnoticed for months.
        IngestionRun.objects.create(
            source="usda_organic",
            status="ok",
            rows_created=final_count,
            message=f"snapshot {snapshot_date}; replaced {existing_count} row(s)",
        )

        # The /health/ report memoises for 5 minutes; this process just invalidated it. Only
        # clears THIS process's memo — other workers expire on their own, which is fine for a
        # status report but means `/health/` may lag a fresh import briefly.
        reset_reference_data_cache()
        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {final_count} USDA organic operations loaded "
                f"(snapshot: {snapshot_date}, was {existing_count})"
            )
        )
        self.stdout.write(
            "Certification matches are NOT refreshed by this command and no scheduled job "
            "does it either — run `manage.py reverify_certifications --all` next."
        )

    @staticmethod
    def _parse_snapshot_date(value: str) -> date:
        """Parse a --date argument, accepting YYYYMMDD or YYYY-MM-DD."""
        cleaned = value.replace("-", "")
        try:
            return datetime.strptime(cleaned, "%Y%m%d").date()
        except ValueError:
            raise CommandError(f"Could not parse --date {value!r}. Use YYYYMMDD or YYYY-MM-DD.")

    def _check_replacement_is_safe(self, *, new_count: int, existing_count: int, allow_shrink: bool):
        """Refuse to replace a populated table with an implausibly small parse.

        The failure this exists for is silent: USDA renames a column upstream, `_parse_xlsx`
        matches nothing, and the import deletes every row and reports success. Because the
        organic badge is gated on a database match, that turns every certified pilot farm into
        "not independently verified" in one command, with no error to notice.
        """
        if new_count == 0:
            raise CommandError(
                "Parsed 0 operations — refusing to import. This would delete all "
                f"{existing_count} existing row(s) and leave the table empty, which reads "
                "downstream as 'no farm is certified' and silently strips every organic badge. "
                "The usual cause is an upstream column rename; check the header row with "
                "--dry-run against a known-good file."
            )

        if existing_count == 0:
            if new_count < MIN_PLAUSIBLE_RECORDS and not allow_shrink:
                raise CommandError(
                    f"Parsed only {new_count} operations into an empty table. A real USDA "
                    f"national export holds far more than {MIN_PLAUSIBLE_RECORDS}; this is "
                    "almost certainly a partial parse. Inspect with --dry-run, or pass "
                    "--allow-shrink if you are deliberately loading a small fixture."
                )
            return

        if allow_shrink:
            return

        if new_count < existing_count * MIN_RETAINED_FRACTION:
            raise CommandError(
                f"Refusing to replace {existing_count} operations with {new_count} "
                f"({new_count / existing_count:.0%} of current). A drop this large usually "
                "means the parser lost columns or rows rather than USDA publishing a smaller "
                "export. Verify with --dry-run; pass --allow-shrink if the contraction is real."
            )

    def _download_file(self, url: str) -> str | None:
        """Download the XLSX file to a temp location."""
        try:
            resp = requests.get(url, timeout=120, stream=True)
            if resp.status_code != 200:
                self.stderr.write(f"HTTP {resp.status_code} from {url}")
                return None

            content_type = resp.headers.get("Content-Type", "")
            if "html" in content_type:
                self.stderr.write(f"Got HTML instead of XLSX from {url}")
                return None

            tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp.close()

            size_mb = os.path.getsize(tmp.name) / (1024 * 1024)
            self.stdout.write(f"Downloaded {size_mb:.1f} MB to {tmp.name}")
            return tmp.name

        except Exception as e:
            self.stderr.write(f"Download error: {e}")
            return None

    def _parse_xlsx(self, file_path: str, us_only: bool = True) -> list:
        """Parse the USDA XLSX export into records."""
        import openpyxl

        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active

        # Read header row to build column mapping
        headers = []
        for cell in next(ws.iter_rows(min_row=1, max_row=1)):
            headers.append(str(cell.value or "").strip())

        col_map = {h: i for i, h in enumerate(headers)}

        # Key columns (from USDA Data Dictionary v6.1)
        name_col = col_map.get("op_name", col_map.get("op_Name"))
        state_col = col_map.get("opPA_state", col_map.get("opPA_State"))
        country_col = col_map.get("opPA_country", col_map.get("opPA_Country"))
        status_col = col_map.get("op_status", col_map.get("op_Status"))
        status_date_col = col_map.get("op_statusEffectiveDate")
        cert_name_col = col_map.get("Cert_name", col_map.get("ci_certName"))
        products_col = col_map.get("CR_CertifiedProducts")
        scope_cr_col = col_map.get("opSC_CR")
        scope_ls_col = col_map.get("opSC_LS")
        scope_hd_col = col_map.get("opSC_HANDLING")
        scope_wc_col = col_map.get("opSC_WC")
        acreage_col = col_map.get("op_totalAcreage")

        if name_col is None or status_col is None:
            # Try to find columns by partial match
            for h, i in col_map.items():
                h_lower = h.lower()
                if "op_name" in h_lower and name_col is None:
                    name_col = i
                if "op_status" in h_lower and "date" not in h_lower and status_col is None:
                    status_col = i
                if "oppa_state" in h_lower and state_col is None:
                    state_col = i
                if "oppa_country" in h_lower and country_col is None:
                    country_col = i

        if name_col is None or status_col is None:
            raise CommandError(f"Could not find required columns. Headers: {headers[:20]}")

        records = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            name = str(row[name_col] or "").strip() if name_col is not None and name_col < len(row) else ""
            if not name:
                continue

            country = str(row[country_col] or "").strip() if country_col is not None and country_col < len(row) else ""
            if us_only and "united states" not in country.lower():
                continue

            state = str(row[state_col] or "").strip() if state_col is not None and state_col < len(row) else ""
            status = str(row[status_col] or "").strip() if status_col is not None and status_col < len(row) else ""

            def safe_get(col):
                if col is not None and col < len(row):
                    return str(row[col] or "").strip()
                return ""

            acreage = None
            if acreage_col is not None and acreage_col < len(row) and row[acreage_col]:
                try:
                    acreage = float(row[acreage_col])
                except (ValueError, TypeError):
                    pass

            records.append(
                {
                    "op_name": name,
                    "op_name_normalized": normalize_name(name),
                    "state": state,
                    "country": country,
                    "status": status,
                    "status_effective_date": safe_get(status_date_col),
                    "certifier_name": safe_get(cert_name_col),
                    "certified_products": safe_get(products_col),
                    "scope_crops": safe_get(scope_cr_col),
                    "scope_livestock": safe_get(scope_ls_col),
                    "scope_handling": safe_get(scope_hd_col),
                    "scope_wild_crops": safe_get(scope_wc_col),
                    "total_acreage": acreage,
                }
            )

        wb.close()
        return records

    def _import_records(self, records: list, snapshot_date: date):
        """Bulk import records into USDAOrganicOperation."""
        with transaction.atomic():
            # Clear old data and bulk insert
            USDAOrganicOperation.objects.all().delete()

            batch_size = 1000
            for i in range(0, len(records), batch_size):
                batch = records[i : i + batch_size]  # noqa: E203
                USDAOrganicOperation.objects.bulk_create(
                    [
                        USDAOrganicOperation(
                            op_name=r["op_name"],
                            op_name_normalized=r["op_name_normalized"],
                            state=r["state"],
                            country=r["country"],
                            status=r["status"],
                            status_effective_date=r["status_effective_date"],
                            certifier_name=r["certifier_name"],
                            certified_products=r["certified_products"],
                            scope_crops=r["scope_crops"],
                            scope_livestock=r["scope_livestock"],
                            scope_handling=r["scope_handling"],
                            scope_wild_crops=r["scope_wild_crops"],
                            total_acreage=r["total_acreage"],
                            data_snapshot_date=snapshot_date,
                        )
                        for r in batch
                    ]
                )

                if (i + batch_size) % 10000 == 0:
                    self.stdout.write(f"  Imported {i + batch_size} records...")
