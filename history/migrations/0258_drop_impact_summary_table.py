"""Drop history_userimpactsummary, step 2 of 2 retiring UserImpactSummary.

Migration 0256 (#370) took UserImpactSummary out of the model state and dropped the table's
foreign key to users_user. Every container serving now runs that state: nothing reads the table.
`clear_impact_summaries` (#367) emptied it in production first, each row's copy on its
DataOperationLog row.

1. `refuse_if_a_row_exists` refuses if the table holds a row. The deploy then fails and nothing
   changes.
2. `lock_timeout`: fail after 5 s instead of queueing behind a long transaction, in both
   directions.
3. `DROP TABLE` without `CASCADE`: anything else that depends on it, a view or a foreign key
   nobody knows about, makes the migration fail instead of disappearing with it.

Reversing recreates the table, empty, from the model as it stood before 0256 and drops the foreign
key `create_model` gives it to users_user, so it stands as 0256 left it. 0256's own reverse then
restores that foreign key under its 0016 name and puts the model back in the state. The rows come
back only through the DataOperationLog report, with the command from #367's merge commit ff15233b.
"""

from django.db import migrations
from django.db.migrations.loader import MigrationLoader

TABLE = "history_userimpactsummary"
BEFORE_RETIREMENT = ("history", "0255_drop_shopper_tables")


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
            f"history 0258: {TABLE} holds {held} rows; nothing was dropped. Nothing in the code writes "
            "it: find out what did before dropping it."
        )


#: Fail after 5 s instead of queueing behind a long transaction. Set inside the reverse step too:
#: a reverse runs the operations backwards, so the forward `RunSQL` below comes after it, and the
#: reverse adds and drops a foreign key that locks users_user.
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def recreate_as_0256_left_it(apps, schema_editor):
    schema_editor.execute(LOCK_TIMEOUT)
    old = MigrationLoader(schema_editor.connection).project_state(BEFORE_RETIREMENT).apps
    schema_editor.create_model(old.get_model("history", "UserImpactSummary"))
    # `create_model` queues the foreign key to run when the migration ends. Run it now, so it
    # exists to be dropped: 0256 left none.
    for sql in schema_editor.deferred_sql:
        schema_editor.execute(sql)
    schema_editor.deferred_sql = []
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE contype = 'f' AND conrelid::regclass::text = %s",
            [TABLE],
        )
        for (constraint,) in cursor.fetchall():
            cursor.execute(f'ALTER TABLE "{TABLE}" DROP CONSTRAINT "{constraint}"')


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0257_manure_interval_choices_read_as_a_floor"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.RunSQL(LOCK_TIMEOUT, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(migrations.RunPython.noop, recreate_as_0256_left_it),
        migrations.RunSQL(f'DROP TABLE "{TABLE}";', reverse_sql=migrations.RunSQL.noop),
    ]
