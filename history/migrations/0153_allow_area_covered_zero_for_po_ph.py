# Allow area_covered=0 for Pollination (PO) and Post-Harvest Processing (PH)
# in addition to Equipment Maintenance (EM). These subtypes are facility/
# equipment-based rather than field-based, so a zero area is legitimate.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0152_nop_seed_traceability"),
    ]

    operations = [
        # Drop the EM-only constraint from migration 0135
        migrations.RunSQL(
            "ALTER TABLE history_productionevent DROP CONSTRAINT IF EXISTS chk_area_covered_valid;",
            reverse_sql="""
            ALTER TABLE history_productionevent ADD CONSTRAINT chk_area_covered_valid
            CHECK (area_covered IS NULL OR area_covered > 0 OR (area_covered = 0 AND type = 'EM'));
            """,
        ),
        # New constraint: allow zero for EM, PO, PH
        migrations.RunSQL(
            """
            ALTER TABLE history_productionevent ADD CONSTRAINT chk_area_covered_valid
            CHECK (
                area_covered IS NULL
                OR area_covered > 0
                OR (area_covered = 0 AND type IN ('EM', 'PO', 'PH'))
            );
            """,
            reverse_sql="ALTER TABLE history_productionevent DROP CONSTRAINT IF EXISTS chk_area_covered_valid;",
        ),
    ]
