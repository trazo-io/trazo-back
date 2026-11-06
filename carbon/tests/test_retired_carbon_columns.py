"""The dead CarbonEntry columns (carbon/retired_columns.py), step 2 of 3: out of the model (0048).

Step 1 (#318) stopped every writer and cleared every value through a logged data operation. Step 2
takes the fields out of the model but keeps the table columns, nullable, so a container still
running the step 1 model can write while the deploy rolls. These tests hold that state: the model
and its indexes carry none of them, the step 1 model and the current one both still write, the
migration refuses to run over a held value, and the census compare still refuses a column that
leaves holding one.
"""

import importlib
import json

from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from carbon.models import CarbonEntry
from carbon.retired_columns import RETIRED_CARBON_ENTRY_COLUMNS
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from common.services import census
from company.models import Company, Establishment
from history.models import History, PestManagementEvent
from product.models import Parcel

LABEL = "carbon.CarbonEntry"


class _FarmMixin:
    def setUp(self):
        company = Company.objects.create(name="Retire Co")
        self.est = Establishment.objects.create(name="Retire Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=self.est, area=1)
        self.season = History.objects.create(parcel=parcel, name="2026", start_date=timezone.now())
        self.event = PestManagementEvent.objects.create(
            history=self.season, type="SC", description="scouting", date=timezone.now()
        )
        CarbonEntry.objects.all().delete()  # whatever the save receivers wrote


class TheFieldsAreGoneTests(TestCase):
    def test_no_retired_column_is_left_in_the_model(self):
        fields = {f.name for f in CarbonEntry._meta.get_fields()}
        self.assertEqual(fields & set(RETIRED_CARBON_ENTRY_COLUMNS), set())

    def test_the_table_keeps_them_nullable_until_step_3(self):
        with connection.cursor() as cursor:
            columns = {c.name: c for c in connection.introspection.get_table_description(cursor, "carbon_carbonentry")}
            constraints = connection.introspection.get_constraints(cursor, "carbon_carbonentry")
        self.assertIn("calculation_details", columns)  # the guard read the real table
        for column in RETIRED_CARBON_ENTRY_COLUMNS:
            self.assertTrue(columns[column].null_ok, column)
        indexed = {c for constraint in constraints.values() if constraint["index"] for c in constraint["columns"]}
        self.assertIn("year", indexed)
        self.assertEqual(indexed & set(RETIRED_CARBON_ENTRY_COLUMNS), set())  # 0028's raw index too

    def test_no_model_index_on_a_retired_column_is_left(self):
        indexed = {f for index in CarbonEntry._meta.indexes for f in index.fields}
        self.assertIn("registry_verification_id", indexed)
        self.assertEqual(indexed & set(RETIRED_CARBON_ENTRY_COLUMNS), set())

    def test_calculation_details_is_not_retired(self):
        """recompute_soil_carbon writes its method marker there."""
        self.assertNotIn("calculation_details", RETIRED_CARBON_ENTRY_COLUMNS)


class TheWritersStillWriteTests(_FarmMixin, TestCase):
    def test_an_entry_is_written_from_an_event(self):
        entry = EventCarbonCalculator().create_carbon_entry_from_event(
            self.event, {"co2e": 1.5, "verification_status": "estimated", "data_source": "test"}
        )
        self.assertTrue(CarbonEntry.objects.filter(pk=entry.pk, amount=1.5).exists())


def _step_1_model():
    """CarbonEntry as the containers still running #318 see it: every retired field named."""
    return MigrationLoader(connection).project_state(("carbon", "0047_backfill_activity_link")).apps


class TheRollingDeployTests(_FarmMixin, TestCase):
    def _old_entry(self, **kw):
        values = dict(
            production_id=self.season.pk,
            establishment_id=self.est.pk,
            type="emission",
            amount=2,
            co2e_amount=2,
            year=timezone.now().year,
            description="Diesel",
        )
        values.update(kw)
        return _step_1_model().get_model("carbon", "CarbonEntry").objects.create(**values)

    def test_a_container_on_the_step_1_model_still_writes(self):
        """Its INSERT and UPDATE name all 16 columns: they must still exist while it serves."""
        entry = self._old_entry()
        entry.description = "Diesel, corrected"
        entry.save()
        self.assertEqual(CarbonEntry.objects.get(pk=entry.pk).description, "Diesel, corrected")

    def test_the_migration_refuses_to_run_over_a_held_value(self):
        migration = importlib.import_module("carbon.migrations.0048_retire_columns_from_model")
        self._old_entry()
        migration.refuse_if_a_value_is_held(_step_1_model(), None)  # defaults only: runs

        self._old_entry(verification_notes="USDA verified fuel consumption data")
        with self.assertRaisesMessage(RuntimeError, "{'verification_notes': 1}"):
            migration.refuse_if_a_value_is_held(_step_1_model(), None)

    def test_the_migration_freezes_the_same_list(self):
        migration = importlib.import_module("carbon.migrations.0048_retire_columns_from_model")
        self.assertEqual({c: empty for c, (empty, _) in migration.RETIRED.items()}, RETIRED_CARBON_ENTRY_COLUMNS)


class TheDemoSeederTests(_FarmMixin, TestCase):
    def test_the_demo_seeder_writes_no_fabricated_claim(self):
        """It wrote fabricated registry and USDA verification claims into these columns (review of #318)."""
        from pathlib import Path

        import carbon.management.commands.seed_comprehensive_demo_v2 as seeder

        source = Path(seeder.__file__).read_text()
        for claim in ("usda.gov/verify", "registry.verra.org/report", "USDA Event Registry", '"EXT-', '"SUB-'):
            self.assertNotIn(claim, source)
        for column in RETIRED_CARBON_ENTRY_COLUMNS:
            self.assertNotIn(column, source)

    def test_the_demo_seeders_raw_inserts_name_only_live_columns(self):
        """Its two INSERTs name columns by hand, so a dropped name would fail at run time.

        Read from the source, not run: both INSERTs have failed since carbon migration 0028 added
        NOT NULL columns they do not name (`calculation_details`), and the seeder logs the error
        and moves on. Making them write again would bring back the registry claims they carry.
        """
        import ast
        import re
        from pathlib import Path

        import carbon.management.commands.seed_comprehensive_demo_v2 as seeder

        live = {f.column for f in CarbonEntry._meta.concrete_fields}
        inserts = []
        for node in ast.walk(ast.parse(Path(seeder.__file__).read_text())):
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "execute" and node.args):
                continue
            sql = node.args[0]
            if isinstance(sql, ast.Constant) and "INSERT INTO carbon_carbonentry" in str(sql.value):
                inserts.append((sql.value, node.args[1]))
        self.assertEqual(len(inserts), 2)
        for sql, values in inserts:
            named = [
                c.strip() for c in re.search(r"carbon_carbonentry \((.*?)\) VALUES", sql, re.S).group(1).split(",")
            ]
            self.assertEqual(set(named) - live, set())
            self.assertEqual(sql.count("%s"), len(named))
            self.assertEqual(len(values.elts), len(named))


def _with_columns(snapshot, columns, counted):
    """`snapshot` as a census would have read it while `columns` were still in the table.

    `counted` is {column: rows holding a value}, the `retiring_columns` fact the census stored for a
    declared column; a column missing from it was never declared.
    """
    before = json.loads(json.dumps(snapshot))
    table = before["tables"][LABEL]
    filler = "0" * census.CELL_HASH_CHARS * len(columns)
    for key, row in table["rows"].items():
        table["rows"][key] = row + filler
    table["columns"] = table["columns"] + list(columns)
    before["domain"]["retiring_columns"][LABEL] = dict(counted)
    return before


class CensusAcrossTheDropTests(_FarmMixin, TransactionTestCase):
    """`TransactionTestCase`: the census opens its own read-only snapshot transaction."""

    def setUp(self):
        super().setUp()
        CarbonEntry.objects.create(
            production=self.season,
            establishment=self.est,
            type="emission",
            amount=2,
            co2e_amount=2,
            year=timezone.now().year,
            description="Diesel",
        )
        self.now = census.take_census(label="after-drop")

    def test_the_census_counts_nothing_once_the_fields_are_gone(self):
        self.assertEqual(census._retiring_column_facts(), {LABEL: {}})
        self.assertEqual(self.now["domain"]["retiring_columns"], {LABEL: {}})

    def test_a_drop_of_columns_counted_empty_is_a_note(self):
        before = _with_columns(
            self.now, ["verification_notes", "gps_coordinates"], {"verification_notes": 0, "gps_coordinates": 0}
        )
        result = census.compare(before, self.now)
        self.assertTrue(result["ok"], result["losses"])
        self.assertTrue(any("retired columns dropped" in note for note in result["notes"]))

    def test_a_drop_of_a_column_still_holding_a_value_is_a_loss(self):
        before = _with_columns(
            self.now, ["verification_notes", "gps_coordinates"], {"verification_notes": 1, "gps_coordinates": 0}
        )
        result = census.compare(before, self.now)
        self.assertFalse(result["ok"])
        self.assertIn(
            f"{LABEL}: retired columns dropped while rows still held a value {{'verification_notes': 1}}",
            result["losses"],
        )

    def test_an_undeclared_column_still_counts_as_a_loss(self):
        before = _with_columns(self.now, ["description_extra"], {})
        result = census.compare(before, self.now)
        self.assertIn(f"{LABEL}: columns dropped ['description_extra']", result["losses"])
