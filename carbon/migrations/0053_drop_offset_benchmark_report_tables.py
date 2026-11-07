"""Drop carbon_carbonauditlog.report_id and the five retired tables, step 2 of 2.

Migration 0052 (#342) took CarbonOffsetProject, CarbonOffsetPurchase, CarbonOffsetCertificate,
CarbonBenchmark, CarbonReport and CarbonAuditLog.report out of the model state and dropped the
foreign keys from those tables to live ones. Every container serving now runs that state: nothing
reads the tables, and audit-log INSERTs no longer name `report_id`. The census after 0052
(2026-11-07, `after-0052`) was `ok` with each table and the column retired empty.

1. `refuse_if_a_row_exists` refuses if any of the five tables holds a row or any audit-log row
   names a report. The deploy then fails and nothing changes.
2. `lock_timeout`: fail after 5 s instead of queueing behind a long transaction, in both
   directions. `carbon_carbonauditlog` is written on every activity edit.
3. `DROP COLUMN report_id` first: it carries the only foreign key from a live table into the set.
   Then `DROP TABLE` without `CASCADE`, children before parents (certificate -> purchase ->
   project). Anything else that depends on one of them, a view or a foreign key nobody knows
   about, makes the migration fail instead of disappearing with it.

Reversing recreates the tables, empty, from the models as they stood before 0052, drops the
foreign keys `create_model` gives them to live tables (0052 left none), and puts `report_id` back:
nullable, with its index and its foreign key under their original names. 0052's own reverse then
puts the models back in the state and restores those foreign keys.
"""

from django.db import migrations
from django.db.migrations.loader import MigrationLoader

#: Frozen, in drop order: each table after every table that references it.
TABLES = (
    "carbon_carbonoffsetcertificate",
    "carbon_carbonoffsetpurchase",
    "carbon_carbonoffsetproject",
    "carbon_carbonbenchmark",
    "carbon_carbonreport",
)

MODELS = ("CarbonBenchmark", "CarbonReport", "CarbonOffsetProject", "CarbonOffsetPurchase", "CarbonOffsetCertificate")
BEFORE_RETIREMENT = ("carbon", "0051_drop_retired_satellite_tables")

AUDIT_TABLE = "carbon_carbonauditlog"
REPORT_ID_INDEX = "carbon_carbonauditlog_report_id_153b054b"
REPORT_ID_FOREIGN_KEY = "carbon_carbonauditlo_report_id_153b054b_fk_carbon_ca"


def _present(cursor):
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        [list(TABLES)],
    )
    return {row[0] for row in cursor.fetchall()}


def _has_report_id(cursor):
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s AND column_name = 'report_id'",
        [AUDIT_TABLE],
    )
    return cursor.fetchone() is not None


def rows_held(cursor):
    held = {}
    present = _present(cursor)
    for table in TABLES:
        if table not in present:
            continue
        cursor.execute(f'SELECT count(*) FROM "{table}"')
        count = cursor.fetchone()[0]
        if count:
            held[table] = count
    if _has_report_id(cursor):
        cursor.execute(f'SELECT count(*) FROM "{AUDIT_TABLE}" WHERE "report_id" IS NOT NULL')
        count = cursor.fetchone()[0]
        if count:
            held[f"{AUDIT_TABLE}.report_id"] = count
    return held


def refuse_if_a_row_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        held = rows_held(cursor)
    if held:
        raise RuntimeError(
            f"carbon 0053: retired tables hold rows {held}; nothing was dropped. Nothing in the code "
            "writes them: find out what did before dropping them."
        )


#: Fail after 5 s instead of queueing behind a long transaction. Set inside the reverse step too:
#: a reverse runs the operations backwards, so the forward `RunSQL` below comes after it, and the
#: step adds and drops foreign keys that lock users_user, history_history, company_establishment
#: and carbon_carbonauditlog. (Reviews of #325 and #327.)
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def recreate_as_0052_left_them(apps, schema_editor):
    schema_editor.execute(LOCK_TIMEOUT)
    old = MigrationLoader(schema_editor.connection).project_state(BEFORE_RETIREMENT).apps
    for name in MODELS:  # parents before children
        schema_editor.create_model(old.get_model("carbon", name))
    # `create_model` queues each foreign key to run when the migration ends. Run them now, so the
    # ones to live tables exist to be dropped: 0052 left none.
    for sql in schema_editor.deferred_sql:
        schema_editor.execute(sql)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.conrelid::regclass::text, c.conname FROM pg_constraint c "
            "WHERE c.contype = 'f' AND c.conrelid::regclass::text = ANY(%s) "
            "AND NOT (c.confrelid::regclass::text = ANY(%s))",
            [list(TABLES), list(TABLES)],
        )
        for table, constraint in cursor.fetchall():
            cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{constraint}"')
        # `report_id` as 0052 left it: nullable, indexed, a deferred foreign key into the report table.
        cursor.execute(f'ALTER TABLE "{AUDIT_TABLE}" ADD COLUMN "report_id" bigint NULL')
        cursor.execute(f'CREATE INDEX "{REPORT_ID_INDEX}" ON "{AUDIT_TABLE}" ("report_id")')
        cursor.execute(
            f'ALTER TABLE "{AUDIT_TABLE}" ADD CONSTRAINT "{REPORT_ID_FOREIGN_KEY}" FOREIGN KEY ("report_id") '
            'REFERENCES "carbon_carbonreport" ("id") DEFERRABLE INITIALLY DEFERRED'
        )


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0052_retire_offset_benchmark_report_models"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.RunSQL(LOCK_TIMEOUT, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(migrations.RunPython.noop, recreate_as_0052_left_them),
        migrations.RunSQL(f'ALTER TABLE "{AUDIT_TABLE}" DROP COLUMN "report_id";', reverse_sql=migrations.RunSQL.noop),
        *[migrations.RunSQL(f'DROP TABLE "{table}";', reverse_sql=migrations.RunSQL.noop) for table in TABLES],
    ]
