"""Five carbon satellite models retired from the model state (carbon migration 0050), step 1 of 2.

SustainabilityBadge, MicroOffset, GreenPoints, RegionalEmissionFactor and CarbonIntelligence: no
route, no writer, 0 rows in production. Step 1 takes them out of the state but leaves the tables,
because containers on the previous model read them whenever they delete a production, an
establishment or a user. These tests hold that state: the models are gone, the tables are still
there and empty with no foreign key to a live table, the migration refuses to run over a row, it
reverses (foreign keys included), and the census compare accepts a retired table leaving only when
it was empty.
"""

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from common.services import census

MODELS = ("CarbonIntelligence", "GreenPoints", "MicroOffset", "RegionalEmissionFactor", "SustainabilityBadge")
STEP_1 = "0050_retire_satellite_models"


def _migration():
    return importlib.import_module(f"carbon.migrations.{STEP_1}")


def _tables():
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


class TheModelsAreGoneTests(TestCase):
    def test_no_model_is_left_in_the_registry(self):
        for name in MODELS:
            with self.assertRaises(LookupError, msg=name):
                apps.get_model("carbon", name)

    def test_the_tables_stay_until_step_2_and_are_empty(self):
        migration = _migration()
        self.assertTrue(set(migration.TABLES) <= _tables())
        with connection.cursor() as cursor:
            self.assertEqual(migration.rows_held(cursor), {})

    def test_no_foreign_key_points_from_them_to_a_live_table(self):
        """One Django cannot see makes TRUNCATE of the live table fail: every TransactionTestCase."""
        with connection.cursor() as cursor:
            self.assertEqual(_migration().outward_foreign_keys(cursor), [])
            cursor.execute(
                "SELECT count(*) FROM pg_constraint WHERE contype = 'f' "
                "AND conrelid::regclass::text = 'carbon_sustainabilitybadge_productions'"
            )
            self.assertEqual(cursor.fetchone()[0], 1)  # the one to the badge table stays

    def test_the_census_declares_every_retired_table(self):
        retired = {f"carbon.{name}" for name in MODELS} | {
            "carbon.SustainabilityBadge_establishments",
            "carbon.SustainabilityBadge_productions",
        }
        self.assertEqual(census.RETIRED_TABLES, retired)

    def test_the_migration_refuses_to_run_over_a_row(self):
        migration = _migration()
        editor = SimpleNamespace(connection=connection)
        migration.refuse_if_a_row_exists(None, editor)  # empty: runs

        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "carbon_sustainabilitybadge" (name, description, criteria, minimum_score, '
                "is_automatic, usda_factors_used, created_at, updated_at) "
                "VALUES ('Gold Tier', '', '{}', 90, true, true, now(), now())"
            )
        with self.assertRaisesMessage(RuntimeError, "{'carbon_sustainabilitybadge': 1}"):
            migration.refuse_if_a_row_exists(None, editor)


class TheMigrationReversesTests(TransactionTestCase):
    """`TransactionTestCase`: migrating the test database cannot happen inside a test transaction."""

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_the_models_come_back_over_the_tables_still_there(self):
        MigrationExecutor(connection).migrate([("carbon", "0049_drop_retired_columns_from_table")])
        state = MigrationExecutor(connection).loader.project_state(("carbon", "0049_drop_retired_columns_from_table"))
        for name in MODELS:
            model = state.apps.get_model("carbon", name)
            self.assertEqual(model.objects.count(), 0, name)  # the state reads the real table
        migration = _migration()
        with connection.cursor() as cursor:
            restored = migration.outward_foreign_keys(cursor)
        self.assertEqual(
            sorted(restored), sorted((table, name) for table, _, _, name in migration.OUTWARD_FOREIGN_KEYS)
        )


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
