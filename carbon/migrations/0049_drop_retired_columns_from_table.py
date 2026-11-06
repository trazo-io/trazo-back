"""Drop the 16 retired CarbonEntry columns from the table (carbon/retired_columns.py), step 3 of 3.

Migration 0048 (#320) took them out of the model and let them take NULL, so no container that can
still be serving names them: the containers this deploy replaces run the 0048 model. The census
across #320 (`after-carbon-model`, 2026-11-06) compared clean against `before-carbon-drop`, which
counted 0 rows holding a value in every one of them.

1. `refuse_if_a_value_is_held` reads the table directly (the model no longer has the fields) and
   refuses to run if any row holds anything but NULL or the old default. The deploy then fails
   and nothing changes.
2. `lock_timeout`: `ALTER TABLE` takes an exclusive lock, and waiting behind a long transaction
   would stall every CarbonEntry read behind it. It fails after 5 s instead, and the deploy can be
   retried.
3. `DROP COLUMN` without `CASCADE`: an object built on one of these columns that nothing here knows
   about (a view) makes the migration fail instead of disappearing with it.

There is no state operation: the model state lost the fields in 0048. Reversing adds the columns
back nullable and empty, as 0048 left them; 0048's own reverse then fills the defaults and restores
NOT NULL. The values cleared in step 1 come back only from that run's `DataOperationLog` report.
"""

from django.db import migrations

#: Column -> (SQL type, the SQL literal of the default it held). Frozen: same names as
#: carbon/retired_columns.py, types as information_schema reports them after 0048.
RETIRED = {
    "iot_device_id": ("varchar(100)", "''"),
    "external_verification_id": ("varchar(100)", "''"),
    "gps_coordinates": ("jsonb", "'{}'::jsonb"),
    "verification_notes": ("text", "''"),
    "baseline_scenario": ("jsonb", "'{}'::jsonb"),
    "detected_patterns": ("jsonb", "'{}'::jsonb"),
    "financial_analysis": ("jsonb", "'{}'::jsonb"),
    "methodology_id": ("varchar(100)", "''"),
    "monitoring_plan": ("jsonb", "'{}'::jsonb"),
    "registry_name": ("varchar(100)", "''"),
    "registry_submission_id": ("varchar(100)", "''"),
    "verification_report_url": ("varchar(200)", "''"),
    "explanation_text": ("text", "''"),
    "confidence_level": ("varchar(10)", "'medium'"),
    "improvement_potential": ("double precision", "0.0"),
    "benchmark_comparison": ("jsonb", "'{}'::jsonb"),
}


def held_values(cursor):
    """Column -> rows holding anything but NULL or the default, for the columns still in the table."""
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'carbon_carbonentry'"
    )
    present = {row[0] for row in cursor.fetchall()}
    held = {}
    for column, (_, empty) in RETIRED.items():
        if column not in present:
            continue
        cursor.execute(
            f'SELECT count(*) FROM "carbon_carbonentry" WHERE "{column}" IS NOT NULL AND "{column}" <> {empty}'
        )
        count = cursor.fetchone()[0]
        if count:
            held[column] = count
    return held


def refuse_if_a_value_is_held(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        held = held_values(cursor)
    if held:
        raise RuntimeError(
            f"carbon 0049: rows hold a value in retired columns {held}; nothing was dropped. Nothing has "
            "written them since #318: find the writer before clearing them."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0048_retire_columns_from_model"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_value_is_held, migrations.RunPython.noop),
        migrations.RunSQL("SET LOCAL lock_timeout = '5s';", reverse_sql=migrations.RunSQL.noop),
        *[
            migrations.RunSQL(
                f'ALTER TABLE "carbon_carbonentry" DROP COLUMN "{column}";',
                reverse_sql=f'ALTER TABLE "carbon_carbonentry" ADD COLUMN "{column}" {sql_type} NULL;',
            )
            for column, (sql_type, _) in RETIRED.items()
        ],
    ]
