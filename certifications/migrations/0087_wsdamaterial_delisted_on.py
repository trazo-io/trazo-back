from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("certifications", "0086_wsda_list_annotations")]

    operations = [
        migrations.AddField(
            model_name="wsdamaterial",
            name="delisted_on",
            field=models.DateField(
                blank=True,
                db_index=True,
                null=True,
                help_text=(
                    "Edition date of the first WSDA list Trazo loaded that no longer carried this product. "
                    "NULL means it was on the most recently seeded edition. A value here does NOT mean the "
                    "product is prohibited, only that WSDA no longer lists it, so Trazo may not state a WSDA "
                    "listing for it (overall review 2026-11, OV-MT-C04; mirrors OMRIProduct.delisted_on)."
                ),
            ),
        ),
    ]
