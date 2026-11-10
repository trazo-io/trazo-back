"""Five shopper models retired in two steps: history 0254 and 0255.

UserFavorite, UserProductComparison, UserShoppingGoal, UserShoppingInsight and
UserLocalRecommendation: no screen read or wrote them, and production held 0 rows in all seven
tables on 2026-11-09. Their routes went with them, and two of those routes were tenancy findings:
`compare_products` served an unpublished season's farm, location and carbon to any UUID holder,
and `toggle_favorite` turned integer production ids into public UUIDs.
UserLocalRecommendation carried `carbon_score`, a stored 0-100 grade, the last exemption in
`carbon/tests/test_no_score_in_any_carbon_payload.py`.

0254 (#360) took the models out of the state, dropped the foreign keys from their tables to live
ones and left the tables, because containers on the previous code still read them when they deleted
a user, a production or an establishment. 0255 drops the seven tables. These tests hold the end
state, each step's refusal to run over a row and its 5 s lock budget, the chain reversing step by
step, the routes staying gone and the census accepting a retired table leaving only when it was
empty.
"""

import importlib
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import Resolver404, resolve

from common.services import census

MODELS = (
    "UserFavorite",
    "UserLocalRecommendation",
    "UserProductComparison",
    "UserShoppingGoal",
    "UserShoppingInsight",
)
BEFORE = "0253_backfill_activity_link"
STEP_1 = "0254_retire_shopper_models"
STEP_2 = "0255_drop_shopper_tables"

#: path -> what it served. Each one must stay unrouted.
RETIRED_ROUTES = {
    "/api/consumer/favorites/": "UserFavoriteViewSet list/create",
    "/api/consumer/favorites/1/": "UserFavoriteViewSet detail",
    "/api/consumer/favorites/toggle_favorite/": (
        "toggle_favorite: took any integer production id, published or not, and the list then "
        "returned its public UUID, farm name, location and carbon"
    ),
    "/api/consumer/goals/": "UserShoppingGoalViewSet list/create",
    "/api/consumer/goals/1/": "UserShoppingGoalViewSet detail",
    "/api/consumer/dashboard/compare_products/": (
        "compare_products: filtered public_id__in with no published check, so an unpublished "
        "season's farm name, location, carbon and certifications reached any UUID holder"
    ),
}


def _migration(name):
    return importlib.import_module(f"history.migrations.{name}")


def _tables():
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def _migrate_history_to(name):
    executor = MigrationExecutor(connection)
    executor.migrate([("history", name)] if name else executor.loader.graph.leaf_nodes())


class _Rollback(Exception):
    pass


class TheRoutesStayRetiredTests(SimpleTestCase):
    def test_the_dashboard_that_stays_still_resolves(self):
        """The probe below would pass vacuously if the whole consumer router were gone."""
        self.assertEqual(
            resolve("/api/consumer/dashboard/impact_dashboard/").url_name, "consumer-dashboard-impact-dashboard"
        )

    def test_no_retired_route_resolves(self):
        for path, why in RETIRED_ROUTES.items():
            with self.subTest(path=path), self.assertRaises(Resolver404, msg=f"{path} is routed again: {why}"):
                resolve(path)


class TheModelsAndTablesAreGoneTests(TestCase):
    def test_no_model_is_left_in_the_registry(self):
        for name in MODELS:
            with self.assertRaises(LookupError, msg=name):
                apps.get_model("history", name)

    def test_the_impact_summary_stays(self):
        """The signed-in consumer dashboard reads it; it is not part of this retirement."""
        self.assertEqual(apps.get_model("history", "UserImpactSummary")._meta.db_table, "history_userimpactsummary")

    def test_no_table_is_left(self):
        self.assertIn("history_userimpactsummary", _tables())  # the check read the real catalogue
        self.assertEqual(set(_migration(STEP_2).TABLES) & _tables(), set())

    def test_both_steps_freeze_the_same_tables(self):
        self.assertEqual(set(_migration(STEP_1).TABLES), set(_migration(STEP_2).TABLES))

    def test_the_census_declares_every_retired_table(self):
        retired = {f"history.{name}" for name in MODELS} | {
            "history.UserLocalRecommendation_recommended_products",
            "history.UserProductComparison_products",
        }
        self.assertTrue(retired <= census.RETIRED_TABLES, retired - census.RETIRED_TABLES)
        self.assertNotIn("history.UserImpactSummary", census.RETIRED_TABLES)


class TheChainTests(TransactionTestCase):
    """Migrates the test database back step by step and forward again.

    `TransactionTestCase`: migrating cannot happen inside a test transaction.
    """

    def tearDown(self):
        with connection.cursor() as cursor:
            for table in _migration(STEP_2).TABLES:
                if table in _tables():
                    cursor.execute(f'DELETE FROM "{table}"')  # a row would stop the way forward
        _migrate_history_to(None)
        super().tearDown()

    def _insert_a_goal(self):
        user = get_user_model().objects.create_user(email="goal@example.com", password="x")
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "history_usershoppinggoal" (user_id, goal_type, title, description, target_value, '
                "current_value, unit, start_date, target_date, status, created_at, updated_at) VALUES "
                "(%s, 'scan_products', 'Scan 10', '', 10, 0, 'products', now(), now(), 'active', now(), now())",
                [user.pk],
            )

    def test_back_to_step_1_the_tables_return_as_step_1_left_them(self):
        _migrate_history_to(STEP_1)
        step_1, step_2 = _migration(STEP_1), _migration(STEP_2)
        self.assertTrue(set(step_2.TABLES) <= _tables(), set(step_2.TABLES) - _tables())
        with connection.cursor() as cursor:
            self.assertEqual(step_2.rows_held(cursor), {})
            self.assertEqual(step_1.outward_foreign_keys(cursor), [])
            cursor.execute(
                "SELECT c.conrelid::regclass::text, c.confrelid::regclass::text FROM pg_constraint c "
                "WHERE c.contype = 'f' AND c.conrelid::regclass::text = ANY(%s) ORDER BY 1",
                [list(step_2.TABLES)],
            )
            internal = cursor.fetchall()
        self.assertEqual(  # the two foreign keys 0254 kept, between the retired tables themselves
            internal,
            [
                (
                    "history_userlocalrecommendation_recommended_products",
                    "history_userlocalrecommendation",
                ),
                (
                    "history_userproductcomparison_products",
                    "history_userproductcomparison",
                ),
            ],
        )
        for index, table, columns in step_2.RAW_INDEXES:  # history 0017's, outside the model state
            with connection.cursor() as cursor:
                constraints = connection.introspection.get_constraints(cursor, table)
            self.assertIn(index, constraints, table)
            self.assertEqual(constraints[index]["columns"], list(columns), index)

    def test_both_guards_refuse_a_row(self):
        _migrate_history_to(STEP_1)
        editor = SimpleNamespace(connection=connection)
        steps = (_migration(STEP_1), _migration(STEP_2))
        for step in steps:
            step.refuse_if_a_row_exists(None, editor)  # empty: runs
        self._insert_a_goal()
        for step in steps:
            with self.assertRaisesMessage(RuntimeError, "{'history_usershoppinggoal': 1}", msg=step.__name__):
                step.refuse_if_a_row_exists(None, editor)

    def test_step_1s_foreign_key_steps_wait_at_most_5_seconds_for_a_lock(self):
        """They lock users_user and history_history too: never queue every login behind them."""
        _migrate_history_to(STEP_1)
        step_1 = _migration(STEP_1)
        editor = SimpleNamespace(connection=connection)
        for step in (
            step_1.restore_outward_foreign_keys,
            step_1.drop_outward_foreign_keys,
        ):
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

    def test_step_2s_reverse_waits_at_most_5_seconds_for_a_lock(self):
        """It adds and drops foreign keys to users_user, history_history and company_establishment."""
        step_2 = _migration(STEP_2)
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = 0")
                with connection.schema_editor(atomic=False) as editor:
                    step_2.recreate_as_0254_left_them(None, editor)
                with connection.cursor() as cursor:
                    cursor.execute("SHOW lock_timeout")
                    self.assertEqual(cursor.fetchone()[0], "5s")
                raise _Rollback  # leave the tables dropped
        except _Rollback:
            pass

    def test_back_before_step_1_the_models_and_foreign_keys_return(self):
        _migrate_history_to(BEFORE)
        state = MigrationExecutor(connection).loader.project_state(("history", BEFORE))
        for name in MODELS:
            self.assertEqual(state.apps.get_model("history", name).objects.count(), 0, name)  # real table
        step_1 = _migration(STEP_1)
        with connection.cursor() as cursor:
            restored = step_1.outward_foreign_keys(cursor)
        self.assertEqual(
            sorted(restored),
            sorted((table, name) for table, _, _, name in step_1.OUTWARD_FOREIGN_KEYS),
        )


class CensusAcrossTheRetirementTests(TransactionTestCase):
    """`TransactionTestCase`: the census opens its own read-only snapshot transaction."""

    def setUp(self):
        self.now = census.take_census(label="after-shopper-models")

    def _before(self, label, count):
        before = {**self.now, "tables": dict(self.now["tables"])}
        before["tables"][label] = {"table": "x", "columns": ["id"], "pk": "id", "count": count, "rows": {}}
        return before

    def test_a_retired_table_that_was_empty_is_a_note(self):
        result = census.compare(self._before("history.UserFavorite", 0), self.now)
        self.assertTrue(result["ok"], result["losses"])
        self.assertIn("table history.UserFavorite retired, empty before", result["notes"])

    def test_a_retired_table_that_held_rows_is_a_loss(self):
        result = census.compare(self._before("history.UserShoppingGoal", 2), self.now)
        self.assertFalse(result["ok"])
        self.assertIn("retired table history.UserShoppingGoal is missing while it held 2 rows", result["losses"])
