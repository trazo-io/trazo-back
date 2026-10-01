from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("certifications", "0044_annual_update_revisions_backfill")]

    operations = [
        migrations.AddConstraint(
            model_name="ospannualupdate",
            constraint=models.UniqueConstraint(
                fields=("establishment", "reporting_year", "revision_number"), name="unique_annual_update_revision"
            ),
        ),
        migrations.AddConstraint(
            model_name="ospannualupdate",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("submitted_at__isnull", False), ("superseded_at__isnull", True), ("withdrawn_at__isnull", True)
                ),
                fields=("establishment", "reporting_year"),
                name="one_current_filed_annual_update_per_year",
            ),
        ),
    ]
