"""Drop `SoilManagementEvent.carbon_sequestration_potential` from the table, step 3 of 3.

Migration 0266 (#493) took the field out of the model while the column stayed, nullable, so no
container that can still be serving names it: the containers this deploy replaces run the 0266
model. In production the census `before-soil-retire` (2026-11-18) counted 0 rows holding a value,
and step 1's clear changed 0 rows.

1. `refuse_if_a_value_is_held` reads the table directly (the model no longer has the field) and
   refuses to run if any row holds anything but NULL. The deploy then fails and nothing changes.
2. `lock_timeout`: `ALTER TABLE` takes an exclusive lock, and waiting behind a long transaction
   would stall every soil event read behind it. It fails after 5 s instead, and the deploy can be
   retried.
3. `DROP COLUMN` without `CASCADE`: an object built on this column that nothing here knows about
   (a view) makes the migration fail instead of disappearing with it.

There is no state operation: the model state lost the field in 0266. Reversing adds the column
back nullable and empty, as 0266 left it.
"""

from django.db import migrations

TABLE = "history_soilmanagementevent"

#: Column -> SQL type, as information_schema reports it after 0266. Frozen: same names as
#: history/retired_columns.py.
RETIRED = {
    "carbon_sequestration_potential": "numeric(10, 3)",
}


def held_values(cursor):
    """Column -> rows holding anything but NULL, for the columns still in the table."""
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        [TABLE],
    )
    present = {row[0] for row in cursor.fetchall()}
    held = {}
    for column in RETIRED:
        if column not in present:
            continue
        cursor.execute(f'SELECT count(*) FROM "{TABLE}" WHERE "{column}" IS NOT NULL')
        count = cursor.fetchone()[0]
        if count:
            held[column] = count
    return held


def refuse_if_a_value_is_held(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        held = held_values(cursor)
    if held:
        raise RuntimeError(
            f"history 0267: rows hold a value in retired columns {held}; nothing was dropped. Nothing has "
            "written them since #483: find the writer before clearing them."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0266_retire_soil_sequestration_from_model"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_value_is_held, migrations.RunPython.noop),
        migrations.RunSQL("SET LOCAL lock_timeout = '5s';", reverse_sql=migrations.RunSQL.noop),
        *[
            migrations.RunSQL(
                f'ALTER TABLE "{TABLE}" DROP COLUMN "{column}";',
                reverse_sql=f'ALTER TABLE "{TABLE}" ADD COLUMN "{column}" {sql_type} NULL;',
            )
            for column, sql_type in RETIRED.items()
        ],
    ]
