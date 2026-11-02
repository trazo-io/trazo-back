"""Annual update: its Documents copy and its supporting documents (§ 205.406(a)(1)).

Schema only. No revision filed before this gets a `filed_document`: a copy appearing on the farm's
shelf that nobody filed is the class documents/models.py forbids. No revision gets supporting
documents either, so every existing signature keeps its hash (`signed_content` hashes the list
only when it is not empty).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("certifications", "0061_biodiversity_monitoring_multichoice"),
        ("documents", "0008_annual_update_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="ospannualupdate",
            name="filed_document",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="annual_update_filing",
                to="documents.generateddocument",
            ),
        ),
        migrations.CreateModel(
            name="OSPAnnualUpdateSupportingDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "annual_update",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="supporting_links",
                        to="certifications.ospannualupdate",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="annual_update_links",
                        to="documents.generateddocument",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AddField(
            model_name="ospannualupdate",
            name="supporting_documents",
            field=models.ManyToManyField(
                blank=True,
                related_name="annual_updates_supported",
                through="certifications.OSPAnnualUpdateSupportingDocument",
                to="documents.generateddocument",
            ),
        ),
        migrations.AddConstraint(
            model_name="ospannualupdatesupportingdocument",
            constraint=models.UniqueConstraint(
                fields=("annual_update", "document"), name="unique_annual_update_supporting_doc"
            ),
        ),
    ]
