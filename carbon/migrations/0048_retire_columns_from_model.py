"""Retire the 16 dead CarbonEntry columns from the model (carbon/retired_columns.py), step 2 of 3.

Step 1 (#318) stopped every writer, and `clear_retired_carbon_columns --apply` reset each value to
its default in production; the values it cleared are kept in that run's `DataOperationLog` report.
The census taken before this migration (`before-carbon-drop`) counted 0 rows holding a value in
every one of these columns.

The columns cannot leave the TABLE yet. `migrate` runs when the new container boots, while the
previous containers still serve, and their model still names all 16 columns in every CarbonEntry
INSERT and UPDATE (event saves write CarbonEntry from signals). So this migration:

1. refuses to run if any row holds a value in a retired column (the deploy then fails and the old
   containers keep serving): the census gate, enforced where the drop happens;
2. drops the 5 model indexes on them and the raw `idx_carbonentry_confidence` index from 0028,
   which nothing in the model state knows about;
3. removes the 16 fields from the model state only, and in the database lets each column take
   NULL, since the new code's INSERTs no longer name them and none has a database default.

Step 3, a later migration once this is live, drops the columns from the table.

Reversing it puts the fields back in the model, fills any NULL a new row left with the default and
restores NOT NULL and the indexes. The cleared values come back only from the step 1 report.
"""

from django.db import migrations

#: Column -> (the default it held, the SQL literal for that default). Same list as
#: carbon/retired_columns.py, frozen here: a migration must not change when that module does.
RETIRED = {
    "iot_device_id": ("", "''"),
    "external_verification_id": ("", "''"),
    "gps_coordinates": ({}, "'{}'::jsonb"),
    "verification_notes": ("", "''"),
    "baseline_scenario": ({}, "'{}'::jsonb"),
    "detected_patterns": ({}, "'{}'::jsonb"),
    "financial_analysis": ({}, "'{}'::jsonb"),
    "methodology_id": ("", "''"),
    "monitoring_plan": ({}, "'{}'::jsonb"),
    "registry_name": ("", "''"),
    "registry_submission_id": ("", "''"),
    "verification_report_url": ("", "''"),
    "explanation_text": ("", "''"),
    "confidence_level": ("medium", "'medium'"),
    "improvement_potential": (0.0, "0.0"),
    "benchmark_comparison": ({}, "'{}'::jsonb"),
}

MODEL_INDEXES = {
    "carbon_carb_iot_dev_35c2c3_idx": "iot_device_id",
    "carbon_carb_externa_724efd_idx": "external_verification_id",
    "carbon_carb_methodo_a7bb9e_idx": "methodology_id",
    "carbon_carb_registr_57bff4_idx": "registry_name",
    "carbon_carb_confide_f4d0b0_idx": "confidence_level",
}


def refuse_if_a_value_is_held(apps, schema_editor):
    CarbonEntry = apps.get_model("carbon", "CarbonEntry")
    held = {}
    for column, (empty, _) in RETIRED.items():
        count = CarbonEntry.objects.exclude(**{column: empty}).count()
        if count:
            held[column] = count
    if held:
        raise RuntimeError(
            f"carbon 0048: rows still hold a value in retired columns {held}. Run "
            "`clear_retired_carbon_columns --apply` from the #318 release first; nothing was changed."
        )


def _nullable(column, literal):
    return migrations.RunSQL(
        f'ALTER TABLE "carbon_carbonentry" ALTER COLUMN "{column}" DROP NOT NULL;',
        # `SET CONSTRAINTS ALL IMMEDIATE`: the FKs are deferred, so the UPDATE would leave trigger
        # events pending and Postgres refuses the ALTER that follows in the same transaction
        # (found by the reverse test with step 3, back #320's follow-up). Reverse only.
        reverse_sql=(
            "SET CONSTRAINTS ALL IMMEDIATE;"
            f'UPDATE "carbon_carbonentry" SET "{column}" = {literal} WHERE "{column}" IS NULL;'
            f'ALTER TABLE "carbon_carbonentry" ALTER COLUMN "{column}" SET NOT NULL;'
        ),
    )


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0047_backfill_activity_link"),
    ]

    operations = [
        migrations.RunPython(refuse_if_a_value_is_held, migrations.RunPython.noop),
        *[migrations.RemoveIndex(model_name="carbonentry", name=name) for name in MODEL_INDEXES],
        migrations.RunSQL(
            "DROP INDEX IF EXISTS idx_carbonentry_confidence;",
            reverse_sql=(
                "CREATE INDEX IF NOT EXISTS idx_carbonentry_confidence ON carbon_carbonentry(confidence_level);"
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.RemoveField(model_name="carbonentry", name=column) for column in RETIRED],
            database_operations=[_nullable(column, literal) for column, (_, literal) in RETIRED.items()],
        ),
    ]
