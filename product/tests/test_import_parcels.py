"""Bulk parcel creation for white-glove migration onboarding.

Trazo has one parcel-creation path in the UI: a four-step wizard, one at a time. A mid-size
California orchard maps one block to one Parcel, so a COG Pro migration meant 15-25 wizard runs
while the farmer waited.

The unit handling is the sharp edge. `Parcel.area` is stored in HECTARES and the column carries
no unit of its own, so an unlabelled acre figure is silently 2.47x wrong everywhere downstream —
a bug this codebase has shipped twice, and the reason 42% of establishments with both figures are
arithmetically impossible.
"""

import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


def _csv(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return handle.name


class ImportParcelsTests(TestCase):
    def setUp(self):
        from company.models import Company, Establishment
        from subscriptions.models import Plan, Subscription

        self.company = Company.objects.create(name="Orchard Co")
        plan, _ = Plan.objects.update_or_create(
            slug="test-unlimited",
            defaults={
                "name": "t",
                "description": "t",
                "price": 0,
                "interval": "monthly",
                "features": {"max_parcels_per_establishment": -1},
                "is_active": True,
            },
        )
        Subscription.objects.create(company=self.company, plan=plan, status="active")
        self.farm = Establishment.objects.create(name="Home Ranch", company=self.company, country="US", state="CA")

    def _run(self, csv_text, commit=False):
        args = ["import_parcels", "--farm", str(self.farm.id), "--file", _csv(csv_text)]
        if commit:
            args.append("--commit")
        call_command(*args)

    def test_dry_run_writes_nothing(self):
        self._run("name,area,area_unit\nBlock 1,10,ha\n")
        self.assertEqual(self.farm.parcels.count(), 0)

    def test_commit_creates_parcels(self):
        self._run("name,area,area_unit\nBlock 1,10,ha\nBlock 2,12,ha\n", commit=True)
        self.assertEqual(
            sorted(self.farm.parcels.values_list("name", flat=True)),
            ["Block 1", "Block 2"],
        )

    def test_acres_are_converted_to_hectares(self):
        self._run("name,area,area_unit\nBlock 1,42.5,ac\n", commit=True)
        parcel = self.farm.parcels.get(name="Block 1")
        self.assertAlmostEqual(parcel.area, 42.5 * 0.40468564224, places=4)

    def test_hectares_are_stored_unchanged(self):
        self._run("name,area,area_unit\nBlock 1,18,ha\n", commit=True)
        self.assertAlmostEqual(self.farm.parcels.get(name="Block 1").area, 18.0, places=4)

    def test_an_area_without_a_unit_is_refused_not_guessed(self):
        # THE point of the command. Defaulting to hectares would understate an acre figure by
        # 2.47x; defaulting to acres would overstate a hectare figure. Neither is detectable
        # afterwards, because the stored number carries no unit.
        with self.assertRaises(CommandError) as ctx:
            self._run("name,area\nBlock 1,250\n", commit=True)
        self.assertIn("area_unit", str(ctx.exception))
        self.assertEqual(self.farm.parcels.count(), 0)

    def test_an_unrecognised_unit_is_refused(self):
        with self.assertRaises(CommandError):
            self._run("name,area,area_unit\nBlock 1,250,row feet\n", commit=True)

    def test_a_non_numeric_area_is_refused(self):
        with self.assertRaises(CommandError):
            self._run("name,area,area_unit\nBlock 1,large,ha\n", commit=True)

    def test_a_negative_area_is_refused(self):
        with self.assertRaises(CommandError):
            self._run("name,area,area_unit\nBlock 1,-5,ha\n", commit=True)

    def test_area_may_be_omitted_entirely(self):
        # COG Pro carries no field size, so requiring an area would block the migration path.
        self._run("name\nBlock 1\n", commit=True)
        self.assertEqual(self.farm.parcels.count(), 1)

    def test_existing_parcel_names_are_skipped_not_duplicated(self):
        from product.models import Parcel

        Parcel.objects.create(name="Block 1", establishment=self.farm, area=5.0)
        self._run("name,area,area_unit\nBlock 1,10,ha\nBlock 2,10,ha\n", commit=True)
        self.assertEqual(self.farm.parcels.count(), 2)
        # The pre-existing parcel keeps its own area — an import must not silently rewrite it.
        self.assertAlmostEqual(Parcel.objects.get(name="Block 1").area, 5.0, places=4)

    def test_name_matching_for_duplicates_ignores_case_and_spacing(self):
        from product.models import Parcel

        Parcel.objects.create(name="Block 1", establishment=self.farm, area=5.0)
        self._run("name,area,area_unit\n  block 1  ,10,ha\n", commit=True)
        self.assertEqual(self.farm.parcels.count(), 1)

    def test_duplicates_within_the_input_are_collapsed(self):
        self._run("name,area,area_unit\nBlock 1,10,ha\nBlock 1,12,ha\n", commit=True)
        self.assertEqual(self.farm.parcels.count(), 1)

    def test_a_missing_name_column_is_refused(self):
        with self.assertRaises(CommandError):
            self._run("area,area_unit\n10,ha\n", commit=True)

    def test_an_unknown_farm_is_refused(self):
        with self.assertRaises(CommandError):
            call_command("import_parcels", "--farm", "999999", "--file", _csv("name\nBlock 1\n"))

    def test_file_and_from_cogpro_are_mutually_exclusive(self):
        with self.assertRaises(CommandError):
            call_command(
                "import_parcels",
                "--farm",
                str(self.farm.id),
                "--file",
                _csv("name\nA\n"),
                "--from-cogpro",
                tempfile.mkdtemp(),
            )

    def test_one_of_file_or_from_cogpro_is_required(self):
        with self.assertRaises(CommandError):
            call_command("import_parcels", "--farm", str(self.farm.id))

    def test_a_missing_file_is_refused(self):
        with self.assertRaises(CommandError):
            call_command("import_parcels", "--farm", str(self.farm.id), "--file", "/nonexistent.csv")

    def test_help_renders(self):
        # argparse %-formats help strings, so a literal "%" raises only when help is rendered.
        from product.management.commands.import_parcels import Command

        text = Command().create_parser("manage.py", "import_parcels").format_help()
        self.assertIn("--from-cogpro", text)
        self.assertIn("--commit", text)


class QuotaWarningTests(TestCase):
    """The operator must learn about the plan ceiling BEFORE hitting a 403 mid-import."""

    def setUp(self):
        from company.models import Company, Establishment

        self.company = Company.objects.create(name="Orchard Co")
        self.farm = Establishment.objects.create(name="Home Ranch", company=self.company, country="US", state="CA")

    def _capture(self, limit=None):
        import io

        from subscriptions.models import Plan, Subscription

        if limit is not None:
            plan, _ = Plan.objects.update_or_create(
                slug=f"t-limit-{limit}",
                defaults={
                    "name": "t",
                    "description": "t",
                    "price": 0,
                    "interval": "monthly",
                    "features": {"max_parcels_per_establishment": limit},
                    "is_active": True,
                },
            )
            Subscription.objects.create(company=self.company, plan=plan, status="active")

        out = io.StringIO()
        call_command(
            "import_parcels",
            "--farm",
            str(self.farm.id),
            "--file",
            _csv("name\nBlock 1\nBlock 2\nBlock 3\n"),
            stdout=out,
        )
        return out.getvalue()

    def test_warns_when_the_import_would_exceed_the_plan(self):
        output = self._capture(limit=1)
        self.assertIn("403", output)
        self.assertIn("pilot", output, "the warning must name the fix, not just the problem")

    def test_no_warning_on_an_unlimited_plan(self):
        output = self._capture(limit=-1)
        self.assertIn("unlimited", output)
        self.assertNotIn("403", output)

    def test_warns_when_there_is_no_active_subscription(self):
        output = self._capture(limit=None)
        self.assertIn("no active subscription plan", output)


class CogProSourceTests(TestCase):
    def setUp(self):
        from company.models import Company, Establishment

        company = Company.objects.create(name="Orchard Co")
        self.farm = Establishment.objects.create(name="Home Ranch", company=company, country="US", state="CA")

    def test_a_directory_with_no_csvs_is_refused(self):
        with self.assertRaises(CommandError):
            call_command("import_parcels", "--farm", str(self.farm.id), "--from-cogpro", tempfile.mkdtemp())

    def test_a_non_directory_is_refused(self):
        with self.assertRaises(CommandError):
            call_command(
                "import_parcels",
                "--farm",
                str(self.farm.id),
                "--from-cogpro",
                str(Path(_csv("name\nA\n"))),
            )
