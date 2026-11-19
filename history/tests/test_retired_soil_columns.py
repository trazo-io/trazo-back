"""The retired SoilManagementEvent columns (history/retired_columns.py), retired in three deploys.

#483 stopped every reader and writer and cleared the values through a logged data operation;
0266 takes the field out of the model while the column stays in the table, because containers on
the #483 model still name it while the new one migrates; step 3 drops the column. These tests hold
the step 2 state (no field; the column still there and nullable, so new rows save), 0266's refusal
to run over a held value, a correction naming the column being refused, and the census compare
refusing a column that leaves while it held a value.
"""

import importlib
import json

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

    def test_the_column_stays_in_the_table_and_takes_null(self):
        """Until step 3: containers on the #483 model still name it in their INSERTs."""
        columns = _table_columns()
        self.assertIn("soil_ph", columns)  # the guard read the real table
        for column in RETIRED_SOIL_EVENT_COLUMNS:
            self.assertTrue(columns[column].null_ok, column)

    def test_a_new_row_saves_and_leaves_it_null(self):
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT "carbon_sequestration_potential" FROM "{TABLE}" WHERE id = %s', [self.event.pk])
            self.assertEqual(cursor.fetchone(), (None,))


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


class TheMigrationGuardTests(_FarmMixin, TestCase):
    """0266 changes no table, so the state before it reads the real table as it is now."""

    def setUp(self):
        super().setUp()
        self.step_2 = importlib.import_module(f"history.migrations.{STEP_2}")
        self.before = MigrationExecutor(connection).loader.project_state(("history", BEFORE_STEP_2)).apps

    def test_it_runs_when_no_row_holds_a_value(self):
        self.step_2.refuse_if_a_value_is_held(self.before, None)

    def test_it_refuses_a_held_value(self):
        old = self.before.get_model("history", "SoilManagementEvent")
        old.objects.filter(pk=self.event.pk).update(carbon_sequestration_potential="1.200")
        with self.assertRaisesMessage(RuntimeError, "{'carbon_sequestration_potential': 1}"):
            self.step_2.refuse_if_a_value_is_held(self.before, None)

    def test_the_migration_freezes_the_same_list(self):
        self.assertEqual(set(self.step_2.RETIRED), set(RETIRED_SOIL_EVENT_COLUMNS))


def _with_columns(snapshot, columns, counted):
    """`snapshot` as a census would have read it while `columns` were still in the model.

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
        self.now = census.take_census(label="after-0266")

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
