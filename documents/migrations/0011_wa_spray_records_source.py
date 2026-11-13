from django.db import migrations, models


class Migration(migrations.Migration):
    """A choices-only change: the Washington pesticide application record export files under its own
    source, so the Documents page never labels it a California PUR. No column changes."""

    dependencies = [
        ("documents", "0010_backfill_activity_link"),
    ]

    operations = [
        migrations.AlterField(
            model_name="generateddocument",
            name="source",
            field=models.CharField(
                choices=[
                    ("osp_snapshot", "OSP submission snapshot"),
                    ("module_pdf", "OSP module PDF"),
                    ("packet", "OSP packet ZIP"),
                    ("workbook", "Common OSP workbook"),
                    ("dossier", "Audit dossier"),
                    ("operation_dossier", "Operation audit dossier"),
                    ("pur", "California PUR export"),
                    ("lot_tag", "Lot tag sheet"),
                    ("upload", "Upload"),
                    ("import_preview", "Record import preview"),
                    ("annual_update", "Annual update filing"),
                    ("wa_spray_records", "Washington pesticide application records"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
