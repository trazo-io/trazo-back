"""Drop the seven tables of the five retired shopper models, step 2 of 2.

Migration 0254 (#360) took UserFavorite, UserProductComparison, UserShoppingGoal,
UserShoppingInsight and UserLocalRecommendation out of the model state and dropped the foreign keys
from their tables to live ones. Every container serving now runs that state: nothing reads the
tables. After 0254 (2026-11-10, `after-shopper-0254`) the census was `ok`, each table retired
empty, and the seven tables held 0 rows with no foreign key to a live table.

1. `refuse_if_a_row_exists` refuses if any of the seven tables holds a row. The deploy then fails
   and nothing changes.
2. `lock_timeout`: fail after 5 s instead of queueing behind a long transaction, in both
   directions.
3. `DROP TABLE` without `CASCADE`, each many-to-many table before the table it references.
   Anything else that depends on one of them, a view or a foreign key nobody knows about, makes
   the migration fail instead of disappearing with it.

Reversing recreates the tables, empty, from the models as they stood before 0254, drops the
foreign keys `create_model` gives them to live tables and rebuilds the two indexes history 0017
created in raw SQL, so they stand as 0254 left them. 0254's own
reverse then restores those foreign keys and puts the models back in the state.
"""

from django.db import migrations
from django.db.migrations.loader import MigrationLoader

#: Frozen, in drop order: each table after every table that references it.
TABLES = (
    "history_userlocalrecommendation_recommended_products",
    "history_userlocalrecommendation",
    "history_userproductcomparison_products",
    "history_userproductcomparison",
    "history_userfavorite",
    "history_usershoppinggoal",
    "history_usershoppinginsight",
)

MODELS = (
    "UserFavorite",
    "UserLocalRecommendation",
    "UserProductComparison",
    "UserShoppingGoal",
    "UserShoppingInsight",
)
BEFORE_RETIREMENT = ("history", "0253_backfill_activity_link")

#: (index, table, columns) for the two indexes history 0017 created in raw SQL. They are not in the
#: model state, so `create_model` does not rebuild them; the reverse does.
RAW_INDEXES = (
    ("history_userfavorite_user_production_idx", "history_userfavorite", ("user_id", "production_id")),
    (
        "history_userlocalrecommendation_user_establishment_idx",
        "history_userlocalrecommendation",
        ("user_id", "establishment_id"),
    ),
)


def _present(cursor):
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        [list(TABLES)],
    )
    return {row[0] for row in cursor.fetchall()}


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
    return held


def refuse_if_a_row_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        held = rows_held(cursor)
    if held:
        raise RuntimeError(
            f"history 0255: retired tables hold rows {held}; nothing was dropped. Nothing in the code "
            "writes them: find out what did before dropping them."
        )


#: Fail after 5 s instead of queueing behind a long transaction. Set inside the reverse step too:
#: a reverse runs the operations backwards, so the forward `RunSQL` below comes after it, and the
#: reverse adds and drops foreign keys that lock users_user, history_history and
#: company_establishment.
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def recreate_as_0254_left_them(apps, schema_editor):
    schema_editor.execute(LOCK_TIMEOUT)
    old = MigrationLoader(schema_editor.connection).project_state(BEFORE_RETIREMENT).apps
    for name in MODELS:  # each one creates its many-to-many table too
        schema_editor.create_model(old.get_model("history", name))
    # `create_model` queues each foreign key to run when the migration ends. Run them now, so the
    # ones to live tables exist to be dropped: 0254 left none.
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
        for index, table, columns in RAW_INDEXES:  # the tables are empty: no CONCURRENTLY needed
            quoted = ", ".join(f'"{column}"' for column in columns)
            cursor.execute(f'CREATE INDEX "{index}" ON "{table}" ({quoted})')


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0254_retire_shopper_models"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.RunSQL(LOCK_TIMEOUT, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(migrations.RunPython.noop, recreate_as_0254_left_them),
        *[migrations.RunSQL(f'DROP TABLE "{table}";', reverse_sql=migrations.RunSQL.noop) for table in TABLES],
    ]
