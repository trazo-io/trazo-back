"""The dead CarbonEntry columns (carbon/retired_columns.py), retired in three deploys.

#318 stopped every writer and cleared every value through a logged data operation; 0048 (#320)
took the fields out of the model and let the columns take NULL while containers on the #318 model
still served; 0049 drops the columns from the table. These tests hold the end state (no field, no
column, no index; the writers still write), each migration's refusal to run over a held value,
the chain reversing step by step, and the census compare refusing a column that leaves holding one.
"""

import importlib
import json
from types import SimpleNamespace

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
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

    def test_no_retired_column_or_index_is_left_in_the_table(self):
        with connection.cursor() as cursor:
            columns = {c.name for c in connection.introspection.get_table_description(cursor, "carbon_carbonentry")}
            constraints = connection.introspection.get_constraints(cursor, "carbon_carbonentry")
        self.assertIn("calculation_details", columns)  # the guard read the real table
        self.assertEqual(columns & set(RETIRED_CARBON_ENTRY_COLUMNS), set())
        indexed = {c for constraint in constraints.values() if constraint["index"] for c in constraint["columns"]}
        self.assertIn("year", indexed)
        self.assertEqual(indexed & set(RETIRED_CARBON_ENTRY_COLUMNS), set())

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


def _migration(name):
    return importlib.import_module(f"carbon.migrations.{name}")


def _migrate_carbon_to(name):
    """Migrate the test database's carbon app to `name` and return that state's apps."""
    executor = MigrationExecutor(connection)
    target = [("carbon", name)] if name else executor.loader.graph.leaf_nodes()
    executor.migrate(target)
    return MigrationExecutor(connection).loader.project_state(target).apps


def _table_columns():
    with connection.cursor() as cursor:
        return {c.name: c for c in connection.introspection.get_table_description(cursor, "carbon_carbonentry")}


class TheMigrationChainTests(_FarmMixin, TransactionTestCase):
    """Each step refuses a held value, and the chain reverses step by step.

    `TransactionTestCase`: migrating the test database cannot happen inside a test transaction.
    """

    def setUp(self):
        super().setUp()
        self.entry = CarbonEntry.objects.create(
            production=self.season,
            establishment=self.est,
            type="emission",
            amount=2,
            co2e_amount=2,
            year=timezone.now().year,
            description="Diesel",
        )

    def tearDown(self):
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM "carbon_carbonentry"')  # a held value would stop the way back
        _migrate_carbon_to(None)
        super().tearDown()

    def test_0049_refuses_a_held_value_and_reverses_to_nullable_columns(self):
        _migrate_carbon_to("0048_retire_columns_from_model")
        columns = _table_columns()
        for column in RETIRED_CARBON_ENTRY_COLUMNS:
            self.assertTrue(columns[column].null_ok, column)  # back as 0048 left them
        step_3 = _migration("0049_drop_retired_columns_from_table")
        editor = SimpleNamespace(connection=connection)
        step_3.refuse_if_a_value_is_held(None, editor)  # NULL everywhere: runs

        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE "carbon_carbonentry" SET "verification_notes" = \'USDA verified\', '
                "\"confidence_level\" = 'medium' WHERE id = %s",
                [self.entry.pk],
            )
        with self.assertRaisesMessage(RuntimeError, "{'verification_notes': 1}"):  # the default is not held
            step_3.refuse_if_a_value_is_held(None, editor)

    def test_0048_refuses_a_held_value_and_reverses_to_the_step_1_table(self):
        step_1 = _migrate_carbon_to("0047_backfill_activity_link")
        columns = _table_columns()
        for column in RETIRED_CARBON_ENTRY_COLUMNS:
            self.assertFalse(columns[column].null_ok, column)  # NOT NULL again, defaults filled
        old = step_1.get_model("carbon", "CarbonEntry")
        self.assertEqual(old.objects.get(pk=self.entry.pk).confidence_level, "medium")
        step_2 = _migration("0048_retire_columns_from_model")
        step_2.refuse_if_a_value_is_held(step_1, None)  # defaults only: runs

        old.objects.filter(pk=self.entry.pk).update(verification_notes="USDA verified fuel consumption data")
        with self.assertRaisesMessage(RuntimeError, "{'verification_notes': 1}"):
            step_2.refuse_if_a_value_is_held(step_1, None)

    def test_both_migrations_freeze_the_same_list(self):
        step_2 = _migration("0048_retire_columns_from_model")
        step_3 = _migration("0049_drop_retired_columns_from_table")
        self.assertEqual({c: empty for c, (empty, _) in step_2.RETIRED.items()}, RETIRED_CARBON_ENTRY_COLUMNS)
        self.assertEqual(set(step_3.RETIRED), set(RETIRED_CARBON_ENTRY_COLUMNS))


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
