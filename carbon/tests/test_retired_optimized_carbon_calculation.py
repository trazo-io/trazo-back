"""OptimizedCarbonCalculation, the score log, retired in one step: carbon 0054.

A performance log of `calculate-event-carbon/` results, each row carrying the self-assigned 0-100
`efficiency_score`; nothing ever read it. #347 removed the writer and emptied the table through
`clear_optimized_carbon_calculations` (each row's copy on its DataOperationLog row). 0054 takes the
model out of the state and drops the table in the same migration: no foreign key touches it and no
code path in the previous containers queries it, so nothing reads the table during the rollout.

These tests hold the end state, the refusal to run over a row, the 5 s lock budget in both
directions, and the migration reversing to an empty table with its indexes.
"""

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from common.services import census

BEFORE = "0053_drop_offset_benchmark_report_tables"
STEP = "0054_retire_optimized_carbon_calculation"


def _migration():
    return importlib.import_module(f"carbon.migrations.{STEP}")


def _tables():
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def _migrate_carbon_to(name):
    executor = MigrationExecutor(connection)
    executor.migrate([("carbon", name)] if name else executor.loader.graph.leaf_nodes())


class _Rollback(Exception):
    pass


class TheModelAndTableAreGoneTests(TestCase):
    def test_no_model_is_left_in_the_registry(self):
        with self.assertRaises(LookupError):
            apps.get_model("carbon", "OptimizedCarbonCalculation")

    def test_no_table_is_left(self):
        self.assertIn("carbon_carbonentry", _tables())  # read the real catalogue
        self.assertNotIn(_migration().TABLE, _tables())

    def test_the_census_declares_it_retired(self):
        self.assertIn("carbon.OptimizedCarbonCalculation", census.RETIRED_TABLES)


class TheChainTests(TransactionTestCase):
    """Migrates back and forward. `TransactionTestCase`: migrating cannot run inside a test
    transaction."""

    def tearDown(self):
        with connection.cursor() as cursor:
            if _migration().TABLE in _tables():
                cursor.execute(f'DELETE FROM "{_migration().TABLE}"')  # a row would stop the way forward
        _migrate_carbon_to(None)
        super().tearDown()

    def test_back_one_step_the_table_returns_empty_with_its_indexes(self):
        _migrate_carbon_to(BEFORE)
        table = _migration().TABLE
        self.assertIn(table, _tables())
        with connection.cursor() as cursor:
            self.assertEqual(_migration().rows_held(cursor), 0)
            indexes = connection.introspection.get_constraints(cursor, table)
        indexed = {tuple(c["columns"]) for c in indexes.values() if c["index"]}
        self.assertIn(("event_type", "efficiency_score"), indexed)
        self.assertIn(("created_at",), indexed)

    def test_the_guard_refuses_a_row(self):
        _migrate_carbon_to(BEFORE)
        step, editor = _migration(), SimpleNamespace(connection=connection)
        step.refuse_if_a_row_exists(None, editor)  # empty: runs
        old = MigrationExecutor(connection).loader.project_state(("carbon", BEFORE)).apps
        old.get_model("carbon", "OptimizedCarbonCalculation").objects.create(
            production_id="api_calc_1",
            event_type="chemical",
            co2e_total=1,
            efficiency_score=70.0,
            calculation_method="optimized_v2",
            calculation_time_ms=5,
        )
        with self.assertRaisesMessage(RuntimeError, "holds 1 rows"):
            step.refuse_if_a_row_exists(None, editor)

    def test_both_directions_wait_at_most_5_seconds_for_a_lock(self):
        step = _migration()
        _migrate_carbon_to(BEFORE)  # the table exists: drop_table has something to drop
        for name, fn in (("drop_table", step.drop_table), ("recreate_table", step.recreate_table)):
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = 0")
                    with connection.schema_editor(atomic=False) as editor:
                        if name == "recreate_table":
                            step.drop_table(None, editor)  # recreate needs it gone first
                            with connection.cursor() as cursor:
                                cursor.execute("SET LOCAL lock_timeout = 0")
                        fn(None, editor)
                    with connection.cursor() as cursor:
                        cursor.execute("SHOW lock_timeout")
                        self.assertEqual(cursor.fetchone()[0], "5s", name)
                    raise _Rollback  # leave the database as it was
            except _Rollback:
                pass
