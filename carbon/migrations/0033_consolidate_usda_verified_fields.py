# Migration: Consolidate usda_verified fields
#
# CarbonEntry & CarbonSource: DROP usda_verified (usda_factors_based already exists)
# 6 other models: RENAME usda_verified -> usda_factors_used
#
# Why: "usda_verified" implies independent USDA verification (FTC 16 CFR 260.6 risk).
# The field actually means "used standard EPA/USDA emission factors" (automatic).

from django.db import migrations, models


def copy_usda_verified_to_factors_based(apps, schema_editor):
    """Copy usda_verified=True into usda_factors_based=True before dropping column."""
    CarbonEntry = apps.get_model("carbon", "CarbonEntry")
    CarbonSource = apps.get_model("carbon", "CarbonSource")

    entry_count = CarbonEntry.objects.filter(usda_verified=True, usda_factors_based=False).update(
        usda_factors_based=True
    )
    print(f"  Migrated {entry_count} CarbonEntry records: usda_verified -> usda_factors_based")

    source_count = CarbonSource.objects.filter(usda_verified=True, usda_factors_based=False).update(
        usda_factors_based=True
    )
    print(f"  Migrated {source_count} CarbonSource records: usda_verified -> usda_factors_based")


def reverse_copy(apps, schema_editor):
    """Reverse: populate re-added usda_verified from usda_factors_based."""
    CarbonEntry = apps.get_model("carbon", "CarbonEntry")
    CarbonSource = apps.get_model("carbon", "CarbonSource")

    CarbonEntry.objects.filter(usda_factors_based=True).update(usda_verified=True)
    CarbonSource.objects.filter(usda_factors_based=True).update(usda_verified=True)


class Migration(migrations.Migration):

    dependencies = [
        ("carbon", "0032_add_event_template_display_fields"),
    ]

    operations = [
        # ── Step 1: Data migration ──────────────────────────────────────
        migrations.RunPython(
            copy_usda_verified_to_factors_based,
            reverse_copy,
        ),
        # ── Step 2: Remove indexes referencing usda_verified on CarbonEntry/CarbonSource ──
        migrations.RemoveIndex(
            model_name="carbonentry",
            name="carbon_carb_usda_ve_60ecf3_idx",
        ),
        # Note: carbon_production_usda_idx was already removed by migration 0032
        migrations.RemoveIndex(
            model_name="carbonsource",
            name="carbon_carb_usda_ve_35ffb1_idx",
        ),
        # Also remove the single-field usda_factors_based index (from 0014),
        # replaced by composite (production, usda_factors_based) in Step 4.
        migrations.RemoveIndex(
            model_name="carbonentry",
            name="carbon_carb_usda_fa_d3807e_idx",
        ),
        # ── Step 3: Drop usda_verified from CarbonEntry & CarbonSource ──
        migrations.RemoveField(
            model_name="carbonentry",
            name="usda_verified",
        ),
        migrations.RemoveField(
            model_name="carbonsource",
            name="usda_verified",
        ),
        # ── Step 4: Add replacement composite index ──
        migrations.AddIndex(
            model_name="carbonentry",
            index=models.Index(
                fields=["production", "usda_factors_based"],
                name="carbon_production_factors_idx",
                condition=models.Q(("production__isnull", False)),
            ),
        ),
        # ── Step 5: CarbonBenchmark — remove index, rename field, add index ──
        migrations.RemoveIndex(
            model_name="carbonbenchmark",
            name="carbon_carb_usda_ve_b88ee0_idx",
        ),
        migrations.RenameField(
            model_name="carbonbenchmark",
            old_name="usda_verified",
            new_name="usda_factors_used",
        ),
        migrations.AddIndex(
            model_name="carbonbenchmark",
            index=models.Index(
                fields=["usda_factors_used"],
                name="carbon_carb_usda_fa_bench_idx",
            ),
        ),
        # ── Step 6: CarbonReport — remove index, rename field, add index ──
        migrations.RemoveIndex(
            model_name="carbonreport",
            name="carbon_carb_usda_ve_ff76a3_idx",
        ),
        migrations.RenameField(
            model_name="carbonreport",
            old_name="usda_verified",
            new_name="usda_factors_used",
        ),
        migrations.AddIndex(
            model_name="carbonreport",
            index=models.Index(
                fields=["usda_factors_used"],
                name="carbon_carb_usda_fa_report_idx",
            ),
        ),
        # ── Step 7: SustainabilityBadge — remove index, rename field, add index ──
        migrations.RemoveIndex(
            model_name="sustainabilitybadge",
            name="carbon_sust_usda_ve_925ceb_idx",
        ),
        migrations.RenameField(
            model_name="sustainabilitybadge",
            old_name="usda_verified",
            new_name="usda_factors_used",
        ),
        migrations.AddIndex(
            model_name="sustainabilitybadge",
            index=models.Index(
                fields=["usda_factors_used"],
                name="carbon_sust_usda_fa_badge_idx",
            ),
        ),
        # ── Step 8: RegionalEmissionFactor — remove index, rename field, add index ──
        migrations.RemoveIndex(
            model_name="regionalemissionfactor",
            name="carbon_regi_usda_ve_badc80_idx",
        ),
        migrations.RenameField(
            model_name="regionalemissionfactor",
            old_name="usda_verified",
            new_name="usda_factors_used",
        ),
        migrations.AddIndex(
            model_name="regionalemissionfactor",
            index=models.Index(
                fields=["usda_factors_used"],
                name="carbon_regi_usda_fa_factor_idx",
            ),
        ),
        # ── Step 9: CropType & CarbonOffsetAction — rename only (no indexes) ──
        migrations.RenameField(
            model_name="croptype",
            old_name="usda_verified",
            new_name="usda_factors_used",
        ),
        migrations.RenameField(
            model_name="carbonoffsetaction",
            old_name="usda_verified",
            new_name="usda_factors_used",
        ),
        # ── Step 10: Update help_text after rename ──
        migrations.AlterField(
            model_name="regionalemissionfactor",
            name="usda_factors_used",
            field=models.BooleanField(default=False, help_text="Whether this factor uses USDA data"),
        ),
        # ── Step 11: Raw SQL index from migration 0002 ──
        migrations.RunSQL(
            "DROP INDEX IF EXISTS idx_carbon_benchmark_crop_year;",
            "CREATE INDEX IF NOT EXISTS idx_carbon_benchmark_crop_year "
            "ON carbon_carbonbenchmark(crop_type, year, usda_verified);",
        ),
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS idx_carbon_benchmark_crop_year "
            "ON carbon_carbonbenchmark(crop_type, year, usda_factors_used);",
            "DROP INDEX IF EXISTS idx_carbon_benchmark_crop_year;",
        ),
    ]
