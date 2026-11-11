"""UserImpactSummary retired in two steps: history 0256, then 0257.

The signed-in consumer dashboard stored one row per shopper carrying the scanned seasons'
emissions labelled as an offset, miles and trees equivalents, points, a level and achievements.
#367 made the dashboard count live and added `clear_impact_summaries`, which emptied the table in
production with a copy of each row on its DataOperationLog row (2 rows, 2026-11-11).

0256 takes the model out of the state, drops the table's foreign key to users_user and leaves the
table, because containers on the previous code still read it when they delete a user. These tests
hold that end state, the step's refusal to run over a row, its 5 s lock budget, and the step
reversing to the model and foreign key history 0016 created.
"""

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import resolve

from common.services import census

BEFORE = "0255_drop_shopper_tables"
STEP_1 = "0256_retire_impact_summary"


def _migration(name):
    return importlib.import_module(f"history.migrations.{name}")


def _tables():
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def _migrate_history_to(name):
    executor = MigrationExecutor(connection)
    executor.migrate([("history", name)] if name else executor.loader.graph.leaf_nodes())


def _foreign_keys(table):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE contype = 'f' AND conrelid::regclass::text = %s ORDER BY 1",
            [table],
        )
        return cursor.fetchall()


class _Rollback(Exception):
    pass


class TheDashboardStillResolvesTests(SimpleTestCase):
    def test_the_dashboard_that_read_it_is_still_routed(self):
        self.assertEqual(
            resolve("/api/consumer/dashboard/impact_dashboard/").url_name, "consumer-dashboard-impact-dashboard"
        )


class TheModelIsGoneTests(TestCase):
    def test_no_model_is_left_in_the_registry(self):
        with self.assertRaises(LookupError):
            apps.get_model("history", "UserImpactSummary")
        self.assertFalse(hasattr(get_user_model(), "impact_summary"))

    def test_the_table_stays_with_no_foreign_key_until_step_2(self):
        table = _migration(STEP_1).TABLE
        self.assertIn(table, _tables())
        self.assertEqual(_foreign_keys(table), [])
        with connection.cursor() as cursor:
            self.assertEqual(_migration(STEP_1).rows_held(cursor), 0)

    def test_the_census_declares_it_retired(self):
        self.assertIn("history.UserImpactSummary", census.RETIRED_TABLES)


class TheChainTests(TransactionTestCase):
    """Migrates the test database back and forward again.

    `TransactionTestCase`: migrating cannot happen inside a test transaction.
    """

    def tearDown(self):
        with connection.cursor() as cursor:
            if _migration(STEP_1).TABLE in _tables():
                cursor.execute(f'DELETE FROM "{_migration(STEP_1).TABLE}"')  # a row would stop the way forward
        _migrate_history_to(None)
        super().tearDown()

    def _old_model(self):
        state = MigrationExecutor(connection).loader.project_state(("history", BEFORE))
        return state.apps.get_model("history", "UserImpactSummary")

    def test_back_one_step_the_model_and_its_foreign_key_return(self):
        _migrate_history_to(BEFORE)
        step = _migration(STEP_1)
        self.assertEqual(self._old_model().objects.count(), 0)  # the state reads the real table
        column, target, name = step.OUTWARD_FOREIGN_KEY
        self.assertEqual(
            _foreign_keys(step.TABLE),
            [(name, f"FOREIGN KEY ({column}) REFERENCES {target}(id) DEFERRABLE INITIALLY DEFERRED")],
        )

    def test_the_guard_refuses_a_row(self):
        _migrate_history_to(BEFORE)
        step, editor = _migration(STEP_1), SimpleNamespace(connection=connection)
        step.refuse_if_a_row_exists(None, editor)  # empty: runs
        user = get_user_model().objects.create_user(email="stored@example.com", password="x")
        self._old_model().objects.create(user_id=user.pk, total_carbon_offset_kg=12.5)
        with self.assertRaisesMessage(RuntimeError, "history_userimpactsummary holds 1 rows"):
            step.refuse_if_a_row_exists(None, editor)

    def test_both_foreign_key_steps_wait_at_most_5_seconds_for_a_lock(self):
        """They lock users_user too: never queue every login behind them."""
        step = _migration(STEP_1)
        editor = SimpleNamespace(connection=connection)
        for fn in (step.restore_outward_foreign_keys, step.drop_outward_foreign_keys):
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = 0")
                        fn(None, editor)
                        cursor.execute("SHOW lock_timeout")
                        self.assertEqual(cursor.fetchone()[0], "5s", fn.__name__)
                    raise _Rollback  # leave the database as step 1 left it
            except _Rollback:
                pass
