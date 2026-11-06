"""Five carbon satellite models retired in two steps: carbon migrations 0050 and 0051.

SustainabilityBadge, MicroOffset, GreenPoints, RegionalEmissionFactor and CarbonIntelligence: no
route, no writer, 0 rows in production. 0050 (#325) took them out of the state, dropped the foreign
keys from their tables to live ones and left the tables, because containers on the previous model
still read them when they deleted a production, an establishment or a user. 0051 drops the tables.

These tests hold the end state (no model, no table), each step's refusal to run over a row and its
5 s lock budget, the chain reversing step by step, and the census compare accepting a retired table
leaving only when it was empty.
"""

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from common.services import census

MODELS = ("CarbonIntelligence", "GreenPoints", "MicroOffset", "RegionalEmissionFactor", "SustainabilityBadge")
BEFORE = "0049_drop_retired_columns_from_table"
STEP_1 = "0050_retire_satellite_models"
STEP_2 = "0051_drop_retired_satellite_tables"


def _migration(name):
    return importlib.import_module(f"carbon.migrations.{name}")


def _tables():
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def _migrate_carbon_to(name):
    executor = MigrationExecutor(connection)
    executor.migrate([("carbon", name)] if name else executor.loader.graph.leaf_nodes())


class _Rollback(Exception):
    pass


class TheModelsAndTablesAreGoneTests(TestCase):
    def test_no_model_is_left_in_the_registry(self):
        for name in MODELS:
            with self.assertRaises(LookupError, msg=name):
                apps.get_model("carbon", name)

    def test_no_table_is_left(self):
        self.assertIn("carbon_carbonentry", _tables())  # the guard read the real catalogue
        self.assertEqual(set(_migration(STEP_2).TABLES) & _tables(), set())

    def test_both_steps_freeze_the_same_tables(self):
        self.assertEqual(set(_migration(STEP_1).TABLES), set(_migration(STEP_2).TABLES))

    def test_the_census_declares_every_retired_table(self):
        retired = {f"carbon.{name}" for name in MODELS} | {
            "carbon.SustainabilityBadge_establishments",
            "carbon.SustainabilityBadge_productions",
        }
        self.assertEqual(census.RETIRED_TABLES, retired)


class TheChainTests(TransactionTestCase):
    """Migrates the test database back step by step and forward again.

    `TransactionTestCase`: migrating cannot happen inside a test transaction.
    """

    def tearDown(self):
        with connection.cursor() as cursor:
            for table in _migration(STEP_2).TABLES:
                if table in _tables():
                    cursor.execute(f'DELETE FROM "{table}"')  # a row would stop the way forward
        _migrate_carbon_to(None)
        super().tearDown()

    def _insert_a_badge(self):
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "carbon_sustainabilitybadge" (name, description, criteria, minimum_score, '
                "is_automatic, usda_factors_used, created_at, updated_at) "
                "VALUES ('Gold Tier', '', '{}', 90, true, true, now(), now())"
            )

    def test_back_to_step_1_the_tables_return_empty_with_no_foreign_key_to_a_live_table(self):
        _migrate_carbon_to(STEP_1)
        step_1, step_2 = _migration(STEP_1), _migration(STEP_2)
        self.assertTrue(set(step_2.TABLES) <= _tables())
        with connection.cursor() as cursor:
            self.assertEqual(step_2.rows_held(cursor), {})
            self.assertEqual(step_1.outward_foreign_keys(cursor), [])

        editor = SimpleNamespace(connection=connection)
        step_2.refuse_if_a_row_exists(None, editor)  # empty: runs
        self._insert_a_badge()
        with self.assertRaisesMessage(RuntimeError, "{'carbon_sustainabilitybadge': 1}"):
            step_2.refuse_if_a_row_exists(None, editor)
        with self.assertRaisesMessage(RuntimeError, "{'carbon_sustainabilitybadge': 1}"):
            step_1.refuse_if_a_row_exists(None, editor)

    def test_step_1s_foreign_key_steps_wait_at_most_5_seconds_for_a_lock(self):
        """They lock users_user and history_history too: never queue every login behind them."""
        _migrate_carbon_to(STEP_1)
        step_1 = _migration(STEP_1)
        editor = SimpleNamespace(connection=connection)
        for step in (step_1.restore_outward_foreign_keys, step_1.drop_outward_foreign_keys):
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = 0")
                        step(None, editor)
                        cursor.execute("SHOW lock_timeout")
                        self.assertEqual(cursor.fetchone()[0], "5s", step.__name__)
                    raise _Rollback  # leave the database as step 1 left it
            except _Rollback:
                pass

    def test_back_before_step_1_the_models_and_foreign_keys_return(self):
        _migrate_carbon_to(BEFORE)
        state = MigrationExecutor(connection).loader.project_state(("carbon", BEFORE))
        for name in MODELS:
            self.assertEqual(state.apps.get_model("carbon", name).objects.count(), 0, name)  # real table
        step_1 = _migration(STEP_1)
        with connection.cursor() as cursor:
            restored = step_1.outward_foreign_keys(cursor)
        self.assertEqual(sorted(restored), sorted((table, name) for table, _, _, name in step_1.OUTWARD_FOREIGN_KEYS))


class CensusAcrossTheRetirementTests(TransactionTestCase):
    """`TransactionTestCase`: the census opens its own read-only snapshot transaction."""

    def setUp(self):
        self.now = census.take_census(label="after-satellites")

    def _before(self, label, count):
        before = {**self.now, "tables": dict(self.now["tables"])}
        before["tables"][label] = {"table": "x", "columns": ["id"], "pk": "id", "count": count, "rows": {}}
        return before

    def test_a_retired_table_that_was_empty_is_a_note(self):
        result = census.compare(self._before("carbon.GreenPoints", 0), self.now)
        self.assertTrue(result["ok"], result["losses"])
        self.assertIn("table carbon.GreenPoints retired, empty before", result["notes"])

    def test_a_retired_table_that_held_rows_is_a_loss(self):
        result = census.compare(self._before("carbon.GreenPoints", 3), self.now)
        self.assertFalse(result["ok"])
        self.assertIn("retired table carbon.GreenPoints is missing while it held 3 rows", result["losses"])

    def test_an_undeclared_table_is_a_loss_even_when_empty(self):
        result = census.compare(self._before("carbon.NotRetired", 0), self.now)
        self.assertIn("table carbon.NotRetired is missing", result["losses"])
