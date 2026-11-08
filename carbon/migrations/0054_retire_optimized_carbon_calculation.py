"""Retire OptimizedCarbonCalculation and drop its table, in one step.

`calculate-event-carbon/` wrote one row per uncached call: a performance log carrying the result's
self-assigned 0-100 `efficiency_score`, the retired score concept. Nothing ever read a row. #347
removed the only writer and added `clear_optimized_carbon_calculations`, which emptied the table
in production (with every row's copy on its DataOperationLog row) before this migration.

One step instead of 0050/0051's two, because nothing can reach the table during the rollout: no
foreign key points to or from it, so no delete collector reads it, and since #347 no code path in
the previous containers queries it (no view, serializer, admin, task or command).

1. `refuse_if_a_row_exists` refuses if the table holds a row. The deploy then fails and nothing
   changes. The command that empties it with a copy of each row is deleted alongside this
   migration, so on a database that still holds rows (a stale staging copy, a restored snapshot)
   run it from the code before 0054: #347's merge commit c109495a (review of #350).
2. `lock_timeout`: fail after 5 s instead of queueing behind a long transaction, both directions.
3. The model leaves the state, and the table goes with a plain `DROP TABLE`, without the `CASCADE`
   that Django's own DeleteModel would issue: anything else depending on it, a view or a foreign
   key nobody knows about, fails the migration instead of disappearing with it.

Reversing recreates the table, empty, from the model as it stood before (indexes included). The
rows themselves come back only through the DataOperationLog report, and only with code that still
has the model; this migration does not restore data.
"""

from django.db import migrations
from django.db.migrations.loader import MigrationLoader

TABLE = "carbon_optimized_calculations"
BEFORE = ("carbon", "0053_drop_offset_benchmark_report_tables")

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def _present(cursor):
    cursor.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = %s",
        [TABLE],
    )
    return cursor.fetchone() is not None


def rows_held(cursor):
    if not _present(cursor):
        return 0
    cursor.execute(f'SELECT count(*) FROM "{TABLE}"')
    return cursor.fetchone()[0]


def refuse_if_a_row_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        held = rows_held(cursor)
    if held:
        raise RuntimeError(
            f"carbon 0054: {TABLE} holds {held} rows; nothing was dropped. Empty it with a copy of "
            "each row first: from a checkout of commit c109495a (#347, the code before this migration, "
            "where the command still exists), run `manage.py clear_optimized_carbon_calculations "
            "--report <path> --apply` against this database. Do not DELETE by hand: that keeps no copy."
        )


def drop_table(apps, schema_editor):
    schema_editor.execute(LOCK_TIMEOUT)
    schema_editor.execute(f'DROP TABLE "{TABLE}"')


def recreate_table(apps, schema_editor):
    schema_editor.execute(LOCK_TIMEOUT)
    old = MigrationLoader(schema_editor.connection).project_state(BEFORE).apps
    schema_editor.create_model(old.get_model("carbon", "OptimizedCarbonCalculation"))


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0053_drop_offset_benchmark_report_tables"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="OptimizedCarbonCalculation")],
            database_operations=[migrations.RunPython(drop_table, recreate_table)],
        ),
    ]
