"""
Three-step migration to add public_id UUID field to History model.
Step 1: Add nullable field without unique constraint.
Step 2: Populate existing rows with unique UUIDs.
Step 3: Set NOT NULL and add unique constraint.
"""

import uuid

from django.db import migrations, models


def populate_history_public_ids(apps, schema_editor):
    """Generate unique UUIDs for all existing History records."""
    History = apps.get_model("history", "History")
    for history in History.objects.all():
        history.public_id = uuid.uuid4()
        history.save(update_fields=["public_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0135_allow_area_covered_zero_for_em"),
    ]

    operations = [
        # Step 1: Add nullable field (no unique constraint yet)
        migrations.AddField(
            model_name="history",
            name="public_id",
            field=models.UUIDField(null=True),
        ),
        # Step 2: Populate existing rows
        migrations.RunPython(populate_history_public_ids, migrations.RunPython.noop),
        # Step 3: Set NOT NULL, unique, db_index, and default
        migrations.AlterField(
            model_name="history",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True),
        ),
    ]
