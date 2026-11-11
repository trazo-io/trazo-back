"""Retire UserImpactSummary from the state, step 1 of 2.

The signed-in consumer dashboard stored one row per shopper, refreshed at most hourly. Besides
counts derivable from the shopper's scans, a row carried `total_carbon_offset_kg` (the scanned
seasons' emissions labelled as an offset), `miles_driving_offset`, `trees_equivalent`,
`sustainable_farms_found`, `better_choices_made` and seeded points, levels and achievements. Since
#367 (2026-11-10) the dashboard counts live and nothing reads or writes a row.
`clear_impact_summaries` then emptied the table in production with a copy of every column of each
row on its DataOperationLog row: dry run 2, applied 2, dry run 0, on 2026-11-11.

The table cannot go yet. `migrate` runs on the new container while the previous ones still serve,
and their delete collector reads this table when it deletes a user (the model is a one-to-one to
User with CASCADE). So:

1. refuse to run if the table holds a row. The command that empties it with a copy of each row is
   deleted alongside this migration; on a database that still holds rows (a stale staging copy, a
   restored snapshot), run it from the code before 0256: #367's merge commit ff15233b. Do not
   DELETE by hand: that keeps no copy;
2. drop the foreign key from this table to users_user. With the model gone, Django no longer knows
   the table references it, and a constraint it cannot see makes `TRUNCATE` of users_user fail
   (every TransactionTestCase flush);
3. remove the model from the state only. The table and the content type stay.

Step 2 (0257) drops the table. Reversing this one restores the foreign key and puts the model back
in the state over the table still there. The rows come back only through the DataOperationLog
report, with the command from ff15233b; this migration does not restore data.
"""

from django.db import migrations

TABLE = "history_userimpactsummary"

#: (column, referenced table, Django's constraint name) of the one foreign key, as history 0016
#: created it. The forward step finds it by table instead of by name; the reverse puts it back.
OUTWARD_FOREIGN_KEY = ("user_id", "users_user", "history_userimpactsummary_user_id_2990807d_fk_users_user_id")


def rows_held(cursor):
    cursor.execute(f'SELECT count(*) FROM "{TABLE}"')
    return cursor.fetchone()[0]


def outward_foreign_keys(cursor):
    """Names of the foreign keys from the retired table to any other table."""
    cursor.execute(
        "SELECT c.conname FROM pg_constraint c WHERE c.contype = 'f' AND c.conrelid::regclass::text = %s "
        "AND c.confrelid::regclass::text <> %s ORDER BY 1",
        [TABLE, TABLE],
    )
    return [name for (name,) in cursor.fetchall()]


#: Adding or dropping a foreign key locks users_user too: every login. Fail after 5 s instead of
#: queueing every read behind a long transaction; the deploy can be retried. Set inside both
#: directions, because a reverse runs the operations backwards.
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def drop_outward_foreign_keys(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(LOCK_TIMEOUT)
        for constraint in outward_foreign_keys(cursor):
            cursor.execute(f'ALTER TABLE "{TABLE}" DROP CONSTRAINT "{constraint}"')


def restore_outward_foreign_keys(apps, schema_editor):
    column, target, constraint = OUTWARD_FOREIGN_KEY
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(LOCK_TIMEOUT)
        cursor.execute(
            f'ALTER TABLE "{TABLE}" ADD CONSTRAINT "{constraint}" FOREIGN KEY ("{column}") '
            f'REFERENCES "{target}" ("id") DEFERRABLE INITIALLY DEFERRED'
        )


def refuse_if_a_row_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        held = rows_held(cursor)
    if held:
        raise RuntimeError(
            f"history 0256: {TABLE} holds {held} rows; nothing was changed. Empty it with a copy of "
            "each row first: from a checkout of commit ff15233b (#367, the code before this migration, "
            "where the command still exists), run `manage.py clear_impact_summaries --report <path> "
            "--apply` against this database. Do not DELETE by hand: that keeps no copy."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0255_drop_shopper_tables"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.RunPython(drop_outward_foreign_keys, restore_outward_foreign_keys),
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="UserImpactSummary")],
            database_operations=[],
        ),
    ]
