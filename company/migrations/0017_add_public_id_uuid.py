"""
Three-step migration to add public_id UUID field to Establishment model.
Step 1: Add nullable field without unique constraint.
Step 2: Populate existing rows with unique UUIDs.
Step 3: Set NOT NULL and add unique constraint.
"""

import uuid

from django.db import migrations, models


def populate_establishment_public_ids(apps, schema_editor):
    """Generate unique UUIDs for all existing Establishment records."""
    Establishment = apps.get_model("company", "Establishment")
    for establishment in Establishment.objects.all():
        establishment.public_id = uuid.uuid4()
        establishment.save(update_fields=["public_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0016_remove_company_company_name_search_idx_and_more"),
    ]

    operations = [
        # Step 1: Add nullable field (no unique constraint yet)
        migrations.AddField(
            model_name="establishment",
            name="public_id",
            field=models.UUIDField(null=True),
        ),
        # Step 2: Populate existing rows
        migrations.RunPython(populate_establishment_public_ids, migrations.RunPython.noop),
        # Step 3: Set NOT NULL, unique, db_index, and default
        migrations.AlterField(
            model_name="establishment",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True),
        ),
    ]
