"""
Backfill expected_harvest and production_method from existing data.

- expected_harvest: Copy finish_date for productions that haven't actually finished
  (published=False means they're still in progress, so finish_date was being used
  as expected_harvest).
- production_method: Copy from extra_data['production_method'] where it exists.
"""

from django.db import migrations, models


def backfill(apps, schema_editor):
    History = apps.get_model("history", "History")

    # Backfill expected_harvest from finish_date for unpublished (in-progress) productions
    # Published productions have a real finish_date, so don't touch those.
    History.objects.filter(
        published=False,
        finish_date__isnull=False,
        expected_harvest__isnull=True,
    ).update(expected_harvest=models.F("finish_date"))

    # Backfill production_method from extra_data
    for history in History.objects.filter(
        extra_data__has_key="production_method",
        production_method__isnull=True,
    ).only("id", "extra_data"):
        pm = history.extra_data.get("production_method")
        if pm:
            History.objects.filter(id=history.id).update(production_method=pm)


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0142_add_expected_harvest_and_production_method"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
