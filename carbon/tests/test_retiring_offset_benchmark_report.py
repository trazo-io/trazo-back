"""The offset marketplace, the benchmark and the report models, retired in carbon 0052 (step 1 of 2).

0052 takes CarbonOffsetProject, CarbonOffsetPurchase, CarbonOffsetCertificate, CarbonBenchmark,
CarbonReport and CarbonAuditLog.report out of the model state, drops the three foreign keys from
those tables to live ones, and refuses to run over a row. The tables and `report_id` stay until
step 2, because the previous containers still read them during the rollout.

The census lets a table or a column disappear only when it was declared retiring AND the census
taken before counted nothing in it. The declarations shipped one deploy earlier (#341), keyed by
database column: for a foreign key the column (`report_id`) is not the field name (`report`).

These tests hold the end state of step 1, both refusals, the 5 s lock budget in both directions,
the chain reversing, and the census compare across the retirement.
"""

import copy
import importlib
from types import SimpleNamespace

from django.apps import apps
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from carbon.models import CarbonAuditLog
from common.services import census
from company.models import Company, Establishment

AUDIT = "carbon.CarbonAuditLog"
MODELS = ("CarbonBenchmark", "CarbonOffsetCertificate", "CarbonOffsetProject", "CarbonOffsetPurchase", "CarbonReport")
BEFORE = "0051_drop_retired_satellite_tables"
STEP_1 = "0052_retire_offset_benchmark_report_models"


def _step_1():
    return importlib.import_module(f"carbon.migrations.{STEP_1}")


def _tables():
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def _columns(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


def _migrate_carbon_to(name):
    executor = MigrationExecutor(connection)
    executor.migrate([("carbon", name)] if name else executor.loader.graph.leaf_nodes())


class _Rollback(Exception):
    pass


class TheModelsAreGoneTests(TestCase):
    def test_no_model_is_left_in_the_registry(self):
        for name in MODELS:
            with self.assertRaises(LookupError, msg=name):
                apps.get_model("carbon", name)

    def test_the_audit_log_has_no_report_field_but_keeps_the_column(self):
        self.assertNotIn("report", {f.name for f in CarbonAuditLog._meta.get_fields()})
        self.assertIn("report_id", _columns("carbon_carbonauditlog"))  # step 2 drops it

    def test_the_tables_are_still_there_for_the_previous_containers(self):
        self.assertTrue(set(_step_1().TABLES) <= _tables())

    def test_the_census_declares_every_retiring_table(self):
        self.assertTrue({f"carbon.{name}" for name in MODELS} <= census.RETIRED_TABLES)

    def test_an_audit_row_is_still_written_without_report(self):
        CarbonAuditLog.objects.create(action="create", details="an event edit")
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM "carbon_carbonauditlog" WHERE "report_id" IS NULL')
            self.assertEqual(cursor.fetchone()[0], 1)


class TheChainTests(TransactionTestCase):
    """Migrates the test database back and forward. `TransactionTestCase`: migrating cannot run
    inside a test transaction."""

    def tearDown(self):
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM "carbon_carbonauditlog" WHERE "report_id" IS NOT NULL')
            for table in _step_1().TABLES:
                cursor.execute(f'DELETE FROM "{table}"')  # a row would stop the way forward
        _migrate_carbon_to(None)
        super().tearDown()

    def _insert_a_report(self):
        """Through the model as it stood before 0052, so every column gets its default."""
        establishment = Establishment.objects.create(name="Report Farm", company=Company.objects.create(name="R"))
        old = MigrationExecutor(connection).loader.project_state(("carbon", BEFORE)).apps
        return old.get_model("carbon", "CarbonReport").objects.create(establishment_id=establishment.pk).pk

    def test_step_1_left_no_foreign_key_to_a_live_table(self):
        with connection.cursor() as cursor:
            self.assertEqual(_step_1().outward_foreign_keys(cursor), [])

    def test_the_guard_refuses_a_row_in_a_retiring_table(self):
        step_1, editor = _step_1(), SimpleNamespace(connection=connection)
        step_1.refuse_if_a_row_exists(None, editor)  # empty: runs
        self._insert_a_report()
        with self.assertRaisesMessage(RuntimeError, "{'carbon_carbonreport': 1}"):
            step_1.refuse_if_a_row_exists(None, editor)

    def test_the_guard_refuses_an_audit_row_naming_a_report(self):
        step_1, editor = _step_1(), SimpleNamespace(connection=connection)
        report = self._insert_a_report()
        old = MigrationExecutor(connection).loader.project_state(("carbon", BEFORE)).apps
        old.get_model("carbon", "CarbonAuditLog").objects.create(report_id=report, action="create", details="")
        with self.assertRaisesMessage(RuntimeError, "'carbon_carbonauditlog.report_id': 1"):
            step_1.refuse_if_a_row_exists(None, editor)

    def test_both_foreign_key_steps_wait_at_most_5_seconds_for_a_lock(self):
        """They lock users_user, company_establishment and history_history too."""
        step_1, editor = _step_1(), SimpleNamespace(connection=connection)
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
        audit = state.apps.get_model("carbon", "CarbonAuditLog")
        self.assertIn("report", {f.name for f in audit._meta.get_fields()})
        step_1 = _step_1()
        with connection.cursor() as cursor:
            restored = step_1.outward_foreign_keys(cursor)
        self.assertEqual(sorted(restored), sorted((table, name) for table, _, _, name in step_1.OUTWARD_FOREIGN_KEYS))


def _with_report_id(snapshot, counted):
    """`snapshot` as the census before 0052 read it: `report_id` still a model column, counted."""
    before = copy.deepcopy(snapshot)
    table = before["tables"][AUDIT]
    filler = "0" * census.CELL_HASH_CHARS
    for key, row in table["rows"].items():
        table["rows"][key] = row + filler
    table["columns"] = table["columns"] + ["report_id"]
    if counted is not None:
        before["domain"]["retiring_columns"][AUDIT] = {"report_id": counted}
    for name in MODELS:
        before["tables"][f"carbon.{name}"] = {"table": "x", "columns": ["id"], "pk": "id", "count": 0, "rows": {}}
    return before


class CensusAcrossTheRetirementTests(TransactionTestCase):
    """`TransactionTestCase`: the census opens its own read-only snapshot transaction."""

    def setUp(self):
        CarbonAuditLog.objects.create(action="create", details="an event edit")
        self.now = census.take_census(label="after-0052")

    def test_report_id_is_no_longer_counted_once_the_field_is_gone(self):
        self.assertEqual(census._retiring_column_facts()[AUDIT], {})

    def test_the_retirement_counted_empty_is_notes_only(self):
        result = census.compare(_with_report_id(self.now, 0), self.now)
        self.assertTrue(result["ok"], result["losses"])
        self.assertIn(
            f"{AUDIT}: retired columns dropped, every row held the empty value before: ['report_id']",
            result["notes"],
        )
        for name in MODELS:
            self.assertIn(f"table carbon.{name} retired, empty before", result["notes"])

    def test_report_id_dropped_while_a_row_named_a_report_is_a_loss(self):
        result = census.compare(_with_report_id(self.now, 1), self.now)
        self.assertIn(
            f"{AUDIT}: retired columns dropped while rows still held a value {{'report_id': 1}}", result["losses"]
        )

    def test_without_the_declaration_the_drop_is_a_loss(self):
        """What a before-census on the code before #341 would have said."""
        result = census.compare(_with_report_id(self.now, None), self.now)
        self.assertIn(f"{AUDIT}: columns dropped ['report_id']", result["losses"])
