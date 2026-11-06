"""Retire five carbon satellite models from the model state, step 1 of 2.

SustainabilityBadge (a self-assigned sustainability label), MicroOffset (a shopper offset
micro-purchase), GreenPoints (a shopper gamification score), RegionalEmissionFactor ("regional USDA
factors" nothing filled or read) and CarbonIntelligence ("AI insights" and a 0-100 confidence about
one production, nothing wrote it). Their routes were retired in 2026-09; the census of 2026-11-06
(`after-carbon-model`) counted 0 rows in every one of their tables.

The tables cannot go yet. `migrate` runs on the new container while the previous ones still serve,
and when one of those deletes a production, an establishment or a user, Django's delete collector
reads MicroOffset, CarbonIntelligence, GreenPoints and the badge M2M tables. So this migration:

1. refuses to run if any of the seven tables (with the badge M2M tables) holds a row;
2. drops the foreign keys from these tables to live ones (users, productions, establishments).
   With the models gone, Django no longer knows the tables reference them, and a constraint it
   cannot see makes `TRUNCATE` of the live table fail (every TransactionTestCase flush, `flush`
   in development). The previous containers only read these tables, and they hold no row;
3. removes the models from the state only. The tables, their columns and their content types stay.

Step 2, a later migration once this is live, drops the tables. Reversing this one puts the models
back in the state over the tables still there.
"""

from django.db import migrations

#: Frozen: the seven tables this step retires, models and the badge M2M tables together.
TABLES = (
    "carbon_greenpoints",
    "carbon_intelligence",
    "carbon_microoffset",
    "carbon_regional_emission_factor",
    "carbon_sustainabilitybadge",
    "carbon_sustainabilitybadge_establishments",
    "carbon_sustainabilitybadge_productions",
)


def rows_held(cursor):
    held = {}
    for table in TABLES:
        cursor.execute(f'SELECT count(*) FROM "{table}"')
        count = cursor.fetchone()[0]
        if count:
            held[table] = count
    return held


#: (table, column, referenced table, Django's constraint name) for every foreign key that points from
#: a retired table to a live one, as migrations up to 0049 created them. The forward step finds the
#: constraints by table instead of by name; the reverse puts these back.
OUTWARD_FOREIGN_KEYS = (
    ("carbon_greenpoints", "user_id", "users_user", "carbon_greenpoints_user_id_8175318e_fk_users_user_id"),
    (
        "carbon_intelligence",
        "production_id",
        "history_history",
        "carbon_intelligence_production_id_15bedd98_fk_history_h",
    ),
    (
        "carbon_microoffset",
        "production_id",
        "history_history",
        "carbon_microoffset_production_id_f5244f09_fk_history_history_id",
    ),
    ("carbon_microoffset", "user_id", "users_user", "carbon_microoffset_user_id_f2f212f5_fk_users_user_id"),
    (
        "carbon_regional_emission_factor",
        "created_by_id",
        "users_user",
        "carbon_regional_emis_created_by_id_9d1a20a1_fk_users_use",
    ),
    (
        "carbon_sustainabilitybadge_establishments",
        "establishment_id",
        "company_establishment",
        "carbon_sustainabilit_establishment_id_47b798ca_fk_company_e",
    ),
    (
        "carbon_sustainabilitybadge_productions",
        "history_id",
        "history_history",
        "carbon_sustainabilit_history_id_8eebedb4_fk_history_h",
    ),
)


def outward_foreign_keys(cursor):
    """(table, constraint) for each foreign key from a retired table to a table outside the set."""
    cursor.execute(
        "SELECT c.conrelid::regclass::text, c.conname FROM pg_constraint c "
        "WHERE c.contype = 'f' AND c.conrelid::regclass::text = ANY(%s) "
        "AND NOT (c.confrelid::regclass::text = ANY(%s)) ORDER BY 1, 2",
        [list(TABLES), list(TABLES)],
    )
    return cursor.fetchall()


#: Adding or dropping a foreign key locks the referenced table too (users_user, history_history,
#: company_establishment: logins and every page). Fail after 5 s instead of queueing every read
#: behind a long transaction; the deploy can be retried. Same reasoning as 0049. (Review of #325.)
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def drop_outward_foreign_keys(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(LOCK_TIMEOUT)
        for table, constraint in outward_foreign_keys(cursor):
            cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{constraint}"')


def restore_outward_foreign_keys(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(LOCK_TIMEOUT)
        for table, column, target, constraint in OUTWARD_FOREIGN_KEYS:
            cursor.execute(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{constraint}" FOREIGN KEY ("{column}") '
                f'REFERENCES "{target}" ("id") DEFERRABLE INITIALLY DEFERRED'
            )


def refuse_if_a_row_exists(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        held = rows_held(cursor)
    if held:
        raise RuntimeError(
            f"carbon 0050: retired tables hold rows {held}; nothing was changed. Nothing in the code "
            "writes them: find out what did before retiring them."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0049_drop_retired_columns_from_table"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.RunPython(drop_outward_foreign_keys, restore_outward_foreign_keys),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="greenpoints",
                    name="user",
                ),
                migrations.RemoveField(
                    model_name="microoffset",
                    name="production",
                ),
                migrations.RemoveField(
                    model_name="microoffset",
                    name="user",
                ),
                migrations.AlterUniqueTogether(
                    name="regionalemissionfactor",
                    unique_together=None,
                ),
                migrations.RemoveField(
                    model_name="regionalemissionfactor",
                    name="created_by",
                ),
                migrations.RemoveField(
                    model_name="sustainabilitybadge",
                    name="establishments",
                ),
                migrations.RemoveField(
                    model_name="sustainabilitybadge",
                    name="productions",
                ),
                migrations.DeleteModel(
                    name="CarbonIntelligence",
                ),
                migrations.DeleteModel(
                    name="GreenPoints",
                ),
                migrations.DeleteModel(
                    name="MicroOffset",
                ),
                migrations.DeleteModel(
                    name="RegionalEmissionFactor",
                ),
                migrations.DeleteModel(
                    name="SustainabilityBadge",
                ),
            ],
            database_operations=[],
        ),
    ]
