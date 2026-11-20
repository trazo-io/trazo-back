"""The retired SoilManagementEvent columns (history/retired_columns.py), retired in three deploys.

#483 stopped every reader and writer and cleared the values through a logged data operation;
0266 (#493) took the field out of the model while the column stayed in the table, because
containers on the #483 model still named it while the new one migrated; 0267 drops the column.
These tests hold the end state (no field, no column), each migration's refusal to run over a held
value, the chain reversing step by step, a correction naming the column being refused, and the
census compare refusing a column that leaves while it held a value.
"""

import importlib
import json
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from common.services import census
from company.models import Company, Establishment
from history.amendments import AmendmentError, amendable_fields, apply_amendment
from history.constants import SOIL_MANAGEMENT_EVENT_TYPE
from history.models import EventAmendment, Production, SoilManagementEvent
from history.retired_columns import RETIRED_SOIL_EVENT_COLUMNS
from product.models import Parcel

LABEL = "history.SoilManagementEvent"
TABLE = "history_soilmanagementevent"
STEP_2 = "0266_retire_soil_sequestration_from_model"
STEP_3 = "0267_drop_soil_sequestration_column"
BEFORE_STEP_2 = "0265_production_permissions_take_over_history"


class _FarmMixin:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(email="retire-soil@example.com", password="pw-for-tests")
        company = Company.objects.create(name="Retire Soil Co")
        establishment = Establishment.objects.create(name="Retire Soil Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=establishment, area=1)
        self.season = Production.objects.create(parcel=parcel, name="2026", start_date=timezone.now())
        self.event = SoilManagementEvent.objects.create(
            history=self.season, type="CC", date=timezone.now(), description="Ryegrass"
        )


def _table_columns():
    with connection.cursor() as cursor:
        return {c.name: c for c in connection.introspection.get_table_description(cursor, TABLE)}


class TheFieldIsGoneTests(_FarmMixin, TestCase):
    def test_no_retired_column_is_left_in_the_model(self):
        fields = {f.name for f in SoilManagementEvent._meta.get_fields()}
        self.assertIn("soil_ph", fields)  # the model was read
        self.assertEqual(fields & set(RETIRED_SOIL_EVENT_COLUMNS), set())

    def test_no_retired_column_is_left_in_the_table(self):
        columns = _table_columns()
        self.assertIn("soil_ph", columns)  # the guard read the real table
        self.assertEqual(set(columns) & set(RETIRED_SOIL_EVENT_COLUMNS), set())


class NoCorrectionWritesItBackTests(_FarmMixin, TestCase):
    def test_a_retired_column_is_not_offered_for_correction(self):
        names = {f.name for f in amendable_fields(SoilManagementEvent)}
        self.assertIn("soil_ph", names)  # the list was read
        self.assertEqual(names & set(RETIRED_SOIL_EVENT_COLUMNS), set())

    def test_a_correction_naming_it_is_refused(self):
        with self.assertRaisesMessage(AmendmentError, "is not a field that can be corrected"):
            apply_amendment(
                event=self.event,
                event_type=SOIL_MANAGEMENT_EVENT_TYPE,
                field_name="carbon_sequestration_potential",
                new_value="50",
                reason="typo",
                user=self.user,
            )
        self.assertFalse(EventAmendment.objects.exists())


def _migration(name):
    return importlib.import_module(f"history.migrations.{name}")


def _migrate_history_to(name):
    """Migrate the test database's history app to `name` and return that state's apps."""
    executor = MigrationExecutor(connection)
    target = [("history", name)] if name else executor.loader.graph.leaf_nodes()
    executor.migrate(target)
    return MigrationExecutor(connection).loader.project_state(target).apps


class TheMigrationChainTests(_FarmMixin, TransactionTestCase):
    """Each step refuses a held value, and the chain reverses step by step.

    `TransactionTestCase`: migrating the test database cannot happen inside a test transaction.
    """

    def tearDown(self):
        present = set(_table_columns()) & set(RETIRED_SOIL_EVENT_COLUMNS)
        with connection.cursor() as cursor:  # a held value would stop the way back
            for column in present:
                cursor.execute(f'UPDATE "{TABLE}" SET "{column}" = NULL')
        _migrate_history_to(None)
        super().tearDown()

    def test_0267_refuses_a_held_value_and_reverses_to_a_nullable_column(self):
        _migrate_history_to(STEP_2)
        columns = _table_columns()
        for column in RETIRED_SOIL_EVENT_COLUMNS:
            self.assertTrue(columns[column].null_ok, column)  # back as 0266 left it
        step_3 = _migration(STEP_3)
        editor = SimpleNamespace(connection=connection)
        step_3.refuse_if_a_value_is_held(None, editor)  # NULL everywhere: runs

        with connection.cursor() as cursor:
            cursor.execute(
                f'UPDATE "{TABLE}" SET "carbon_sequestration_potential" = 1.2 WHERE id = %s', [self.event.pk]
            )
        with self.assertRaisesMessage(RuntimeError, "{'carbon_sequestration_potential': 1}"):
            step_3.refuse_if_a_value_is_held(None, editor)

    def test_0266_refuses_a_held_value_and_reverses_to_the_step_1_model(self):
        before = _migrate_history_to(BEFORE_STEP_2)
        old = before.get_model("history", "SoilManagementEvent")
        self.assertIsNone(old.objects.get(pk=self.event.pk).carbon_sequestration_potential)
        step_2 = _migration(STEP_2)
        step_2.refuse_if_a_value_is_held(before, None)  # NULL everywhere: runs

        old.objects.filter(pk=self.event.pk).update(carbon_sequestration_potential="1.200")
        with self.assertRaisesMessage(RuntimeError, "{'carbon_sequestration_potential': 1}"):
            step_2.refuse_if_a_value_is_held(before, None)

    def test_both_migrations_freeze_the_same_list(self):
        self.assertEqual(set(_migration(STEP_2).RETIRED), set(RETIRED_SOIL_EVENT_COLUMNS))
        self.assertEqual(set(_migration(STEP_3).RETIRED), set(RETIRED_SOIL_EVENT_COLUMNS))


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


class CensusAcrossTheRetirementTests(_FarmMixin, TransactionTestCase):
    """`TransactionTestCase`: the census opens its own read-only snapshot transaction."""

    def setUp(self):
        super().setUp()
        self.now = census.take_census(label="after-0267")

    def test_the_census_counts_nothing_once_the_field_is_gone(self):
        self.assertEqual(census._retiring_column_facts()[LABEL], {})
        self.assertEqual(self.now["domain"]["retiring_columns"][LABEL], {})

    def test_a_retirement_counted_empty_before_is_a_note(self):
        before = _with_columns(self.now, ["carbon_sequestration_potential"], {"carbon_sequestration_potential": 0})
        result = census.compare(before, self.now)
        self.assertTrue(result["ok"], result["losses"])
        self.assertTrue(any("retired columns dropped" in note for note in result["notes"]))

    def test_a_retirement_while_a_row_held_a_value_is_a_loss(self):
        before = _with_columns(self.now, ["carbon_sequestration_potential"], {"carbon_sequestration_potential": 1})
        result = census.compare(before, self.now)
        self.assertFalse(result["ok"])
        self.assertIn(
            f"{LABEL}: retired columns dropped while rows still held a value {{'carbon_sequestration_potential': 1}}",
            result["losses"],
        )
