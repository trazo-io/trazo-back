# Allow area_covered=0 for Equipment Maintenance (EM) production events

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0134_add_harvest_quality_grain_moisture_certificate_number"),
    ]

    operations = [
        # Drop old constraint that requires area_covered > 0
        migrations.RunSQL(
            "ALTER TABLE history_productionevent DROP CONSTRAINT IF EXISTS chk_area_covered_valid;",
            reverse_sql="""
            ALTER TABLE history_productionevent ADD CONSTRAINT chk_area_covered_valid
            CHECK (area_covered IS NULL OR area_covered > 0);
            """,
        ),
        # Add new constraint: area_covered > 0 OR (area_covered >= 0 AND type = 'EM')
        migrations.RunSQL(
            """
            ALTER TABLE history_productionevent ADD CONSTRAINT chk_area_covered_valid
            CHECK (area_covered IS NULL OR area_covered > 0 OR (area_covered = 0 AND type = 'EM'));
            """,
            reverse_sql="ALTER TABLE history_productionevent DROP CONSTRAINT IF EXISTS chk_area_covered_valid;",
        ),
    ]
