"""Drop the seven tables of the five retired carbon satellite models, step 2 of 2.

Migration 0050 (#325) took SustainabilityBadge, MicroOffset, GreenPoints, RegionalEmissionFactor and
CarbonIntelligence out of the model state, dropped the foreign keys from their tables to live ones,
and refused to run over a row. Every container serving now runs that state, so nothing reads these
tables any more, not even the delete collector.

1. `refuse_if_a_row_exists` refuses to run if any of the seven tables holds a row. The deploy then
   fails and nothing changes.
2. `lock_timeout`: fail after 5 s instead of queueing behind a long transaction.
3. `DROP TABLE` without `CASCADE`, the two badge M2M tables first (their foreign keys to the badge
   table are the only ones left). Anything else that depends on one of them, a view or a foreign
   key nobody knows about, makes the migration fail instead of disappearing with it.

Reversing recreates the tables, empty, from the models as they stood before 0050, and drops the
foreign keys `create_model` gives them to live tables, so the database matches what 0050 left.
0050's own reverse then puts the models back in the state and restores those foreign keys.
"""

from django.db import migrations
from django.db.migrations.loader import MigrationLoader

#: Frozen, in drop order: the badge M2M tables reference the badge table.
TABLES = (
    "carbon_sustainabilitybadge_establishments",
    "carbon_sustainabilitybadge_productions",
    "carbon_sustainabilitybadge",
    "carbon_microoffset",
    "carbon_greenpoints",
    "carbon_intelligence",
    "carbon_regional_emission_factor",
)

MODELS = ("SustainabilityBadge", "MicroOffset", "GreenPoints", "CarbonIntelligence", "RegionalEmissionFactor")
BEFORE_RETIREMENT = ("carbon", "0049_drop_retired_columns_from_table")


def _present(cursor):
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
        [list(TABLES)],
    )
    return {row[0] for row in cursor.fetchall()}


def rows_held(cursor):
    held = {}
    for table in TABLES:
        if table not in _present(cursor):
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
            f"carbon 0051: retired tables hold rows {held}; nothing was dropped. Nothing in the code "
            "writes them: find out what did before dropping them."
        )


def recreate_tables_as_0050_left_them(apps, schema_editor):
    old = MigrationLoader(schema_editor.connection).project_state(BEFORE_RETIREMENT).apps
    for name in MODELS:
        schema_editor.create_model(old.get_model("carbon", name))
    # `create_model` queues each foreign key to run when the migration ends. Run them now, so the
    # ones to live tables exist to be dropped: 0050 left none.
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


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0050_retire_satellite_models"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.RunSQL("SET LOCAL lock_timeout = '5s';", reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(migrations.RunPython.noop, recreate_tables_as_0050_left_them),
        *[migrations.RunSQL(f'DROP TABLE "{table}";', reverse_sql=migrations.RunSQL.noop) for table in TABLES],
    ]
