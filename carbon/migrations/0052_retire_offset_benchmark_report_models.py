"""Retire the offset marketplace, the benchmark and the report models from the state, step 1 of 2.

CarbonOffsetProject, CarbonOffsetPurchase and CarbonOffsetCertificate (the pre-pivot offset
marketplace: projects labelled "VCS", purchases, PDF certificates), CarbonBenchmark (an industry
average Trazo computed about itself) and CarbonReport (snapshots that carried a 0-100 carbon
score). Every route, view, serializer, service and seeder that read or wrote them is gone (#329,
#332, #333, #337, #338). On 2026-11-07 production held 0 rows in all five tables and 0 audit-log
rows pointing at a report.

The tables cannot go yet. `migrate` runs on the new container while the previous ones still serve,
and their delete collector reads CarbonReport and CarbonOffsetPurchase when it deletes an
establishment, a production or a user; their CarbonAuditLog model still names `report_id`. So:

1. refuse to run if any of the five tables holds a row, or any audit-log row names a report;
2. drop the three foreign keys from these tables to live ones (users, establishments,
   productions). With the models gone, Django no longer knows the tables reference them, and a
   constraint it cannot see makes `TRUNCATE` of the live table fail (every TransactionTestCase
   flush). The foreign key from carbon_carbonauditlog.report_id INTO carbon_carbonreport stays:
   it points from a live table into a retiring one, which TRUNCATE does not mind, and step 2 drops
   it with the column;
3. remove the five models and CarbonAuditLog.report from the state only. The tables, the
   report_id column (nullable, NULL in every row) and the content types stay.

Step 2 drops `carbon_carbonauditlog.report_id` and the five tables. Reversing this one restores
the foreign keys and puts the models back in the state over the tables still there.
"""

from django.db import migrations

#: Frozen: the five tables this step retires.
TABLES = (
    "carbon_carbonbenchmark",
    "carbon_carbonoffsetcertificate",
    "carbon_carbonoffsetproject",
    "carbon_carbonoffsetpurchase",
    "carbon_carbonreport",
)


def rows_held(cursor):
    held = {}
    for table in TABLES:
        cursor.execute(f'SELECT count(*) FROM "{table}"')
        count = cursor.fetchone()[0]
        if count:
            held[table] = count
    cursor.execute('SELECT count(*) FROM "carbon_carbonauditlog" WHERE "report_id" IS NOT NULL')
    count = cursor.fetchone()[0]
    if count:
        held["carbon_carbonauditlog.report_id"] = count
    return held


#: (table, column, referenced table, Django's constraint name) for every foreign key from a retired
#: table to a live one, as migrations up to 0051 created them. The forward step finds the
#: constraints by table instead of by name; the reverse puts these back.
OUTWARD_FOREIGN_KEYS = (
    (
        "carbon_carbonoffsetpurchase",
        "user_id",
        "users_user",
        "carbon_carbonoffsetpurchase_user_id_685bbb79_fk_users_user_id",
    ),
    (
        "carbon_carbonreport",
        "establishment_id",
        "company_establishment",
        "carbon_carbonreport_establishment_id_165fc440_fk_company_e",
    ),
    (
        "carbon_carbonreport",
        "production_id",
        "history_history",
        "carbon_carbonreport_production_id_85c1e2e2_fk_history_h",
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
#: behind a long transaction; the deploy can be retried. Set inside both directions, because a
#: reverse runs the operations backwards (reviews of #325 and #327).
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
            f"carbon 0052: retired tables hold rows {held}; nothing was changed. Nothing in the code "
            "writes them: find out what did before retiring them."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0051_drop_retired_satellite_tables"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_row_exists, migrations.RunPython.noop),
        migrations.RunPython(drop_outward_foreign_keys, restore_outward_foreign_keys),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="CarbonBenchmark",
                ),
                migrations.RemoveField(
                    model_name="carbonoffsetpurchase",
                    name="project",
                ),
                migrations.RemoveField(
                    model_name="carbonoffsetpurchase",
                    name="user",
                ),
                migrations.RemoveField(
                    model_name="carbonreport",
                    name="establishment",
                ),
                migrations.RemoveField(
                    model_name="carbonreport",
                    name="production",
                ),
                migrations.RemoveField(
                    model_name="carbonauditlog",
                    name="report",
                ),
                migrations.DeleteModel(
                    name="CarbonOffsetCertificate",
                ),
                migrations.DeleteModel(
                    name="CarbonOffsetProject",
                ),
                migrations.DeleteModel(
                    name="CarbonOffsetPurchase",
                ),
                migrations.DeleteModel(
                    name="CarbonReport",
                ),
            ],
            database_operations=[],
        ),
    ]
