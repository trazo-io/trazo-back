"""The offset marketplace, the benchmark and the report models, retired in two steps: carbon 0052 and 0053.

0052 (#342) took CarbonOffsetProject, CarbonOffsetPurchase, CarbonOffsetCertificate,
CarbonBenchmark, CarbonReport and CarbonAuditLog.report out of the model state, dropped the three
foreign keys from those tables to live ones, and refused to run over a row. The tables and
`report_id` stayed, because the previous containers still read them during the rollout. 0053 drops
`report_id`, then the five tables.

The census lets a table or a column disappear only when it was declared retiring AND the census
taken before counted nothing in it. The declarations shipped one deploy earlier (#341), keyed by
database column: for a foreign key the column (`report_id`) is not the field name (`report`).

These tests hold the end state, each step's refusal to run over a row and its 5 s lock budget,
the chain reversing step by step, and the census compare across the retirement.
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
STEP_2 = "0053_drop_offset_benchmark_report_tables"


def _migration(name):
    return importlib.import_module(f"carbon.migrations.{name}")


def _tables():
    with connection.cursor() as cursor:
        return set(connection.introspection.table_names(cursor))


def _columns(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


def _constraints(table):
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, table)


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
        self.assertIn("carbon_carbonentry", _tables())  # the check read the real catalogue
        self.assertEqual(set(_migration(STEP_2).TABLES) & _tables(), set())

    def test_the_audit_log_has_no_report_field_and_no_column(self):
        self.assertNotIn("report", {f.name for f in CarbonAuditLog._meta.get_fields()})
        columns = _columns("carbon_carbonauditlog")
        self.assertIn("carbon_entry_id", columns)  # read the real table
        self.assertNotIn("report_id", columns)

    def test_both_steps_freeze_the_same_tables(self):
        self.assertEqual(set(_migration(STEP_1).TABLES), set(_migration(STEP_2).TABLES))

    def test_the_census_declares_every_retired_table(self):
        self.assertTrue({f"carbon.{name}" for name in MODELS} <= census.RETIRED_TABLES)


class TheChainTests(TransactionTestCase):
    """Migrates the test database back step by step and forward again. `TransactionTestCase`:
    migrating cannot happen inside a test transaction."""

    def tearDown(self):
        with connection.cursor() as cursor:
            if "report_id" in _columns("carbon_carbonauditlog"):
                cursor.execute('DELETE FROM "carbon_carbonauditlog" WHERE "report_id" IS NOT NULL')
            for table in _migration(STEP_2).TABLES:
                if table in _tables():
                    cursor.execute(f'DELETE FROM "{table}"')  # a row would stop the way forward
        _migrate_carbon_to(None)
        super().tearDown()

    def _insert_a_report(self):
        """Through the model as it stood before 0052, so every column gets its default."""
        establishment = Establishment.objects.create(name="Report Farm", company=Company.objects.create(name="R"))
        old = MigrationExecutor(connection).loader.project_state(("carbon", BEFORE)).apps
        return old.get_model("carbon", "CarbonReport").objects.create(establishment_id=establishment.pk).pk

    def test_back_to_step_1_the_tables_and_report_id_return_as_step_1_left_them(self):
        _migrate_carbon_to(STEP_1)
        step_1, step_2 = _migration(STEP_1), _migration(STEP_2)
        self.assertTrue(set(step_2.TABLES) <= _tables())
        self.assertIn("report_id", _columns("carbon_carbonauditlog"))
        constraints = _constraints("carbon_carbonauditlog")
        self.assertEqual(constraints[step_2.REPORT_ID_FOREIGN_KEY]["foreign_key"], ("carbon_carbonreport", "id"))
        self.assertEqual(constraints[step_2.REPORT_ID_INDEX]["columns"], ["report_id"])
        with connection.cursor() as cursor:
            self.assertEqual(step_2.rows_held(cursor), {})
            self.assertEqual(step_1.outward_foreign_keys(cursor), [])

    def test_both_guards_refuse_a_row_and_an_audit_row_naming_a_report(self):
        _migrate_carbon_to(STEP_1)
        step_1, step_2 = _migration(STEP_1), _migration(STEP_2)
        editor = SimpleNamespace(connection=connection)
        step_2.refuse_if_a_row_exists(None, editor)  # empty: runs
        report = self._insert_a_report()
        old = MigrationExecutor(connection).loader.project_state(("carbon", BEFORE)).apps
        old.get_model("carbon", "CarbonAuditLog").objects.create(report_id=report, action="create", details="")
        for step in (step_1, step_2):
            with self.assertRaisesMessage(RuntimeError, "'carbon_carbonreport': 1", msg=step.__name__):
                step.refuse_if_a_row_exists(None, editor)
            with self.assertRaisesMessage(RuntimeError, "'carbon_carbonauditlog.report_id': 1", msg=step.__name__):
                step.refuse_if_a_row_exists(None, editor)

    def test_step_1s_foreign_key_steps_wait_at_most_5_seconds_for_a_lock(self):
        """They lock users_user, company_establishment and history_history too."""
        _migrate_carbon_to(STEP_1)
        step_1, editor = _migration(STEP_1), SimpleNamespace(connection=connection)
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

    def test_step_2s_reverse_waits_at_most_5_seconds_for_a_lock(self):
        """It adds and drops foreign keys on live tables and alters carbon_carbonauditlog."""
        step_2 = _migration(STEP_2)
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = 0")
                with connection.schema_editor(atomic=False) as editor:
                    step_2.recreate_as_0052_left_them(None, editor)
                with connection.cursor() as cursor:
                    cursor.execute("SHOW lock_timeout")
                    self.assertEqual(cursor.fetchone()[0], "5s")
                raise _Rollback  # leave the tables dropped
        except _Rollback:
            pass

    def test_back_before_step_1_the_models_and_foreign_keys_return(self):
        _migrate_carbon_to(BEFORE)
        state = MigrationExecutor(connection).loader.project_state(("carbon", BEFORE))
        for name in MODELS:
            self.assertEqual(state.apps.get_model("carbon", name).objects.count(), 0, name)  # real table
        audit = state.apps.get_model("carbon", "CarbonAuditLog")
        self.assertIn("report", {f.name for f in audit._meta.get_fields()})
        self.assertEqual(audit.objects.filter(report__isnull=False).count(), 0)  # the column is real
        step_1 = _migration(STEP_1)
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
        self.now = census.take_census(label="after-0053")

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
