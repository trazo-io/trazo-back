"""Give every existing event row its Activity (schema remodel plan, Phase 2).

Historical models and `.update()` only: no `save()`, so no signal fires. A real save would
recalculate carbon, write audit-log entries and run the retention hooks for every event in the
database. The kind codes are frozen here, as a migration must not read code that can change later
(they equal history/taxonomy.py, which pins them in its own test).

Separate from 0250 on purpose: on Postgres, updating rows and then altering the same tables in one
transaction fails with "pending trigger events" when deferred constraints are involved.
"""

from django.db import migrations

KIND_CODES = (
    ("WeatherEvent", 0),
    ("ProductionEvent", 1),
    ("ChemicalEvent", 2),
    ("GeneralEvent", 3),
    ("EquipmentEvent", 4),
    ("SoilManagementEvent", 5),
    ("PestManagementEvent", 6),
    ("BusinessEvent", 7),
)
BATCH = 500


def backfill(apps, schema_editor):
    Activity = apps.get_model("history", "Activity")
    for model_name, code in KIND_CODES:
        Model = apps.get_model("history", model_name)
        pending = list(Model.objects.filter(activity__isnull=True).order_by("pk").values_list("pk", flat=True))
        for start in range(0, len(pending), BATCH):
            pks = pending[start : start + BATCH]
            created = Activity.objects.bulk_create([Activity(kind=code) for _ in pks])
            for pk, activity in zip(pks, created):
                Model.objects.filter(pk=pk, activity__isnull=True).update(activity_id=activity.pk)


def unlink(apps, schema_editor):
    """Reverse: detach and drop the backfilled identities (0250's reverse drops the table)."""
    for model_name, _code in KIND_CODES:
        apps.get_model("history", model_name).objects.update(activity=None)
    apps.get_model("history", "Activity").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("history", "0250_activity_identity")]

    operations = [migrations.RunPython(backfill, unlink)]
