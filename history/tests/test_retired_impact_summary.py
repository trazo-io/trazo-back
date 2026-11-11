"""UserImpactSummary retired in two steps: history 0256, then 0258.

The signed-in consumer dashboard stored one row per shopper carrying the scanned seasons'
emissions labelled as an offset, miles and trees equivalents, points, a level and achievements.
#367 made the dashboard count live and added `clear_impact_summaries`, which emptied the table in
production with a copy of each row on its DataOperationLog row (2 rows, 2026-11-11).

0256 took the model out of the state, dropped the table's foreign key to users_user and left the
table, because containers on the previous code still read it when they deleted a user. 0258 drops
the table (0257 is an unrelated label migration that took #371's colliding 0256 number). These
tests hold the end state, each step's refusal to run over a row and its 5 s lock budget, and the
chain reversing step by step to the table, model and foreign key history 0016 created.
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
STEP_2 = "0258_drop_impact_summary_table"


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

    def test_no_table_is_left(self):
        self.assertIn("history_history", _tables())  # the check read the real catalogue
        self.assertNotIn(_migration(STEP_2).TABLE, _tables())

    def test_both_steps_name_the_same_table(self):
        self.assertEqual(_migration(STEP_1).TABLE, _migration(STEP_2).TABLE)

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

    def test_back_to_step_1_the_table_returns_empty_with_no_foreign_key(self):
        _migrate_history_to(STEP_1)
        step_2 = _migration(STEP_2)
        self.assertIn(step_2.TABLE, _tables())
        self.assertEqual(_foreign_keys(step_2.TABLE), [])
        with connection.cursor() as cursor:
            self.assertEqual(step_2.rows_held(cursor), 0)
            constraints = connection.introspection.get_constraints(cursor, step_2.TABLE)
        self.assertEqual(  # the primary key and the one-to-one's unique constraint, as 0016 made them
            {name: (c["columns"], c["primary_key"], c["unique"]) for name, c in constraints.items()},
            {
                "history_userimpactsummary_pkey": (["id"], True, True),
                "history_userimpactsummary_user_id_key": (["user_id"], False, True),
            },
        )

    def test_back_before_step_1_the_model_and_its_foreign_key_return(self):
        _migrate_history_to(BEFORE)
        step = _migration(STEP_1)
        self.assertEqual(self._old_model().objects.count(), 0)  # the state reads the real table
        column, target, name = step.OUTWARD_FOREIGN_KEY
        self.assertEqual(
            _foreign_keys(step.TABLE),
            [(name, f"FOREIGN KEY ({column}) REFERENCES {target}(id) DEFERRABLE INITIALLY DEFERRED")],
        )

    def test_both_guards_refuse_a_row(self):
        _migrate_history_to(BEFORE)
        editor = SimpleNamespace(connection=connection)
        steps = (_migration(STEP_1), _migration(STEP_2))
        for step in steps:
            step.refuse_if_a_row_exists(None, editor)  # empty: runs
        user = get_user_model().objects.create_user(email="stored@example.com", password="x")
        self._old_model().objects.create(user_id=user.pk, total_carbon_offset_kg=12.5)
        for step in steps:
            with self.assertRaisesMessage(RuntimeError, "history_userimpactsummary holds 1 rows", msg=step.__name__):
                step.refuse_if_a_row_exists(None, editor)

    def test_step_1s_foreign_key_steps_wait_at_most_5_seconds_for_a_lock(self):
        """They lock users_user too: never queue every login behind them."""
        _migrate_history_to(STEP_1)
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

    def test_step_2s_reverse_waits_at_most_5_seconds_for_a_lock(self):
        """It adds and drops a foreign key to users_user."""
        step_2 = _migration(STEP_2)
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = 0")
                with connection.schema_editor(atomic=False) as editor:
                    step_2.recreate_as_0256_left_it(None, editor)
                with connection.cursor() as cursor:
                    cursor.execute("SHOW lock_timeout")
                    self.assertEqual(cursor.fetchone()[0], "5s")
                raise _Rollback  # leave the table dropped
        except _Rollback:
            pass
