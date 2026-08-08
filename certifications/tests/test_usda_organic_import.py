"""Guards on the USDA Organic Integrity import.

`import_usda_organic_data` REPLACES the whole table (delete-then-insert). Before 2026-08-07 it
had no tests and no safety check, so a parse that matched nothing — an upstream column rename is
enough — deleted every row, inserted none, and printed `Import complete: 0 …` styled as SUCCESS.

That is not a cosmetic failure. `consumer_claim_validator` gates the USDA Organic badge on a
database match, so an empty table silently downgrades every certified farm to
"Farmer-reported organic practices. Not independently verified." in one command.

These tests pin the rule: a refused import leaves the previous snapshot intact. Stale-but-true
beats empty-and-false.
"""

from datetime import date
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from certifications.management.commands.import_usda_organic_data import (
    MIN_PLAUSIBLE_RECORDS,
    MIN_RETAINED_FRACTION,
    Command,
    normalize_name,
)
from certifications.models import USDAOrganicOperation


def _make_operations(count, *, state="CA"):
    USDAOrganicOperation.objects.bulk_create(
        [
            USDAOrganicOperation(
                op_name=f"Farm {i}",
                op_name_normalized=normalize_name(f"Farm {i}"),
                state=state,
                country="United States of America",
                status="Certified",
                data_snapshot_date=date(2026, 3, 1),
            )
            for i in range(count)
        ]
    )


class ReplacementSafetyTests(TestCase):
    """`_check_replacement_is_safe` runs BEFORE the delete, so a refusal preserves the table."""

    def setUp(self):
        self.check = Command()._check_replacement_is_safe

    def test_zero_records_is_refused_even_when_the_table_is_empty(self):
        with self.assertRaises(CommandError) as ctx:
            self.check(new_count=0, existing_count=0, allow_shrink=False)
        self.assertIn("Parsed 0 operations", str(ctx.exception))

    def test_zero_records_is_refused_against_a_populated_table(self):
        with self.assertRaises(CommandError) as ctx:
            self.check(new_count=0, existing_count=37071, allow_shrink=False)
        message = str(ctx.exception)
        self.assertIn("37071", message)
        # The operator needs to know WHY this matters, not just that it was blocked.
        self.assertIn("badge", message)

    def test_zero_records_is_refused_even_with_allow_shrink(self):
        # --allow-shrink permits a smaller export. It never permits an empty one: there is no
        # legitimate USDA snapshot containing zero certified operations.
        with self.assertRaises(CommandError):
            self.check(new_count=0, existing_count=37071, allow_shrink=True)

    def test_catastrophic_shrink_is_refused(self):
        # The zero-row case is one point on a spectrum; a partial parse fails identically but
        # with a number that looks superficially real.
        with self.assertRaises(CommandError) as ctx:
            self.check(new_count=500, existing_count=37071, allow_shrink=False)
        self.assertIn("500", str(ctx.exception))

    def test_shrink_just_under_the_threshold_is_refused(self):
        existing = 10000
        just_under = int(existing * MIN_RETAINED_FRACTION) - 1
        with self.assertRaises(CommandError):
            self.check(new_count=just_under, existing_count=existing, allow_shrink=False)

    def test_shrink_at_the_threshold_is_allowed(self):
        existing = 10000
        at_threshold = int(existing * MIN_RETAINED_FRACTION)
        self.check(new_count=at_threshold, existing_count=existing, allow_shrink=False)

    def test_allow_shrink_permits_a_genuine_contraction(self):
        self.check(new_count=500, existing_count=37071, allow_shrink=True)

    def test_growth_is_always_fine(self):
        self.check(new_count=40000, existing_count=37071, allow_shrink=False)

    def test_small_first_load_into_empty_table_is_refused(self):
        with self.assertRaises(CommandError) as ctx:
            self.check(new_count=MIN_PLAUSIBLE_RECORDS - 1, existing_count=0, allow_shrink=False)
        self.assertIn("partial parse", str(ctx.exception))

    def test_small_first_load_is_permitted_with_allow_shrink_for_fixtures(self):
        self.check(new_count=10, existing_count=0, allow_shrink=True)

    def test_plausible_first_load_into_empty_table_is_allowed(self):
        self.check(new_count=MIN_PLAUSIBLE_RECORDS, existing_count=0, allow_shrink=False)


class ExistingDataSurvivesARefusedImportTests(TestCase):
    """End-to-end: the rows are still there after the command rejects a bad parse."""

    def test_table_is_untouched_when_the_parse_yields_nothing(self):
        _make_operations(5)
        self.assertEqual(USDAOrganicOperation.objects.count(), 5)

        command = Command()
        with self.assertRaises(CommandError):
            command._check_replacement_is_safe(new_count=0, existing_count=5, allow_shrink=False)

        # The guard runs before any delete, so the previous snapshot is intact.
        self.assertEqual(USDAOrganicOperation.objects.count(), 5)
        self.assertEqual(USDAOrganicOperation.objects.first().data_snapshot_date, date(2026, 3, 1))


class DryRunDiagnosesBeforeItRefusesTests(TestCase):
    """--dry-run is what an operator reaches for BECAUSE an import was refused."""

    def test_dry_run_branch_precedes_the_enforcing_check(self):
        # Regression: the safety check originally ran before the dry-run branch, so
        # `--dry-run` on a suspicious file raised the very error whose message tells the
        # operator to "inspect with --dry-run". The advice was impossible to follow.
        source = Path(__file__).resolve().parents[1] / "management" / "commands" / "import_usda_organic_data.py"
        text = source.read_text()
        dry_run_at = text.index('if options.get("dry_run")')
        enforcing_call_at = text.index("# Refuse BEFORE deleting anything")
        self.assertLess(
            dry_run_at,
            enforcing_call_at,
            "the dry-run branch must come before the enforcing safety check",
        )
        # The row/state breakdown is printed before the verdict, so a refused dry run still
        # tells the operator WHAT it parsed...
        self.assertIn("DRY RUN — nothing written", text)
        self.assertIn("WOULD BE REFUSED", text)
        # ...but still exits non-zero, so `--dry-run && <real import>` cannot sail past it.
        self.assertIn("raise", text[text.index("WOULD BE REFUSED") : enforcing_call_at])


class SnapshotDateTests(TestCase):
    """`data_snapshot_date` is the only record of how fresh the badge evidence is."""

    def setUp(self):
        self.parse = Command()._parse_snapshot_date

    def test_accepts_compact_form(self):
        self.assertEqual(self.parse("20260801"), date(2026, 8, 1))

    def test_accepts_hyphenated_form(self):
        self.assertEqual(self.parse("2026-08-01"), date(2026, 8, 1))

    def test_rejects_garbage_rather_than_guessing(self):
        for value in ("august", "2026-13-01", "", "20260"):
            with self.subTest(value=value):
                with self.assertRaises(CommandError):
                    self.parse(value)


class CommandInterfaceTests(TestCase):
    """Flags an operator relies on under time pressure."""

    def test_dry_run_and_allow_shrink_and_no_us_only_are_accepted(self):
        # A missing file exits via CommandError, which proves argument parsing succeeded
        # without performing any network or database work.
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "import_usda_organic_data",
                "--file",
                "/nonexistent/usda.xlsx",
                "--dry-run",
                "--allow-shrink",
                "--no-us-only",
                "--date",
                "2026-08-01",
            )
        self.assertIn("File not found", str(ctx.exception))

    def test_help_renders(self):
        # Regression: argparse runs %-formatting over help strings, so a literal "%" in a help
        # message raises `TypeError: %o format: an integer is required, not dict` — but only
        # when --help is actually rendered. create_parser() alone does not catch it.
        parser = Command().create_parser("manage.py", "import_usda_organic_data")
        help_text = parser.format_help()
        self.assertIn("--dry-run", help_text)
        self.assertIn("--allow-shrink", help_text)
        self.assertIn("--no-us-only", help_text)

    def test_us_only_can_actually_be_disabled(self):
        # Regression: --us-only was `store_true` with `default=True`, so it could never be
        # turned off and the flag was decorative. BooleanOptionalAction gives --no-us-only.
        parser = Command().create_parser("manage.py", "import_usda_organic_data")
        self.assertTrue(parser.parse_args([]).us_only)
        self.assertFalse(parser.parse_args(["--no-us-only"]).us_only)
