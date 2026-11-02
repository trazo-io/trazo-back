from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("documents", "0007_import_preview_source"),
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
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
