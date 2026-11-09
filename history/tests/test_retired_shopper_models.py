"""Five shopper models retired in two steps: history 0254, then a drop of the tables.

UserFavorite, UserProductComparison, UserShoppingGoal, UserShoppingInsight and
UserLocalRecommendation: no screen read or wrote them, and production held 0 rows in all seven
tables on 2026-11-09. Their routes went with them, and two of those routes were tenancy findings:
`compare_products` served an unpublished season's farm, location and carbon to any UUID holder,
and `toggle_favorite` turned integer production ids into public UUIDs.
UserLocalRecommendation carried `carbon_score`, a stored 0-100 grade, the last exemption in
`carbon/tests/test_no_score_in_any_carbon_payload.py`.

0254 takes the models out of the state, drops the foreign keys from their tables to live ones and
leaves the tables, because containers on the previous code still read them when they delete a user,
a production or an establishment. These tests hold that state, the refusal to run over a row, the
5 s lock budget, the step reversing, the routes staying gone and the census accepting a retired
table leaving only when it was empty.
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


class TheModelsAreGoneTablesStayTests(TestCase):
    def test_no_model_is_left_in_the_registry(self):
        for name in MODELS:
            with self.assertRaises(LookupError, msg=name):
                apps.get_model("history", name)

    def test_the_impact_summary_stays(self):
        """The signed-in consumer dashboard reads it; it is not part of this retirement."""
        self.assertEqual(apps.get_model("history", "UserImpactSummary")._meta.db_table, "history_userimpactsummary")

    def test_the_tables_are_still_there_with_no_foreign_key_to_a_live_table(self):
        step_1 = _migration(STEP_1)
        self.assertTrue(set(step_1.TABLES) <= _tables(), set(step_1.TABLES) - _tables())
        with connection.cursor() as cursor:
            self.assertEqual(step_1.outward_foreign_keys(cursor), [])
            self.assertEqual(step_1.rows_held(cursor), {})

    def test_the_census_declares_every_retired_table(self):
        retired = {f"history.{name}" for name in MODELS} | {
            "history.UserLocalRecommendation_recommended_products",
            "history.UserProductComparison_products",
        }
        self.assertTrue(retired <= census.RETIRED_TABLES, retired - census.RETIRED_TABLES)
        self.assertNotIn("history.UserImpactSummary", census.RETIRED_TABLES)


class TheStepTests(TransactionTestCase):
    """Migrates the test database back before 0254 and forward again.

    `TransactionTestCase`: migrating cannot happen inside a test transaction.
    """

    def tearDown(self):
        with connection.cursor() as cursor:
            for table in _migration(STEP_1).TABLES:
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

    def test_the_step_refuses_to_run_over_a_row(self):
        step_1 = _migration(STEP_1)
        editor = SimpleNamespace(connection=connection)
        step_1.refuse_if_a_row_exists(None, editor)  # empty: runs
        self._insert_a_goal()
        with self.assertRaisesMessage(RuntimeError, "{'history_usershoppinggoal': 1}"):
            step_1.refuse_if_a_row_exists(None, editor)

    def test_the_foreign_key_steps_wait_at_most_5_seconds_for_a_lock(self):
        """They lock users_user and history_history too: never queue every login behind them."""
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
                    raise _Rollback  # leave the database as 0254 left it
            except _Rollback:
                pass

    def test_back_before_the_step_the_models_and_foreign_keys_return(self):
        _migrate_history_to(BEFORE)
        state = MigrationExecutor(connection).loader.project_state(("history", BEFORE))
        for name in MODELS:
            self.assertEqual(state.apps.get_model("history", name).objects.count(), 0, name)  # real table
        step_1 = _migration(STEP_1)
        with connection.cursor() as cursor:
            restored = step_1.outward_foreign_keys(cursor)
        self.assertEqual(sorted(restored), sorted((table, name) for table, _, _, name in step_1.OUTWARD_FOREIGN_KEYS))


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
