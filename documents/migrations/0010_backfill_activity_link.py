"""Backfill GeneratedDocument.activity from the loose pair it sits next to (schema remodel plan, Phase 2).

Historical models and `.update()` only, so no save() or signal runs. A pair whose event no longer
exists stays unlinked: the census counts those orphans, and an identity is never invented for them.
The kind codes are frozen here (they equal history/taxonomy.py, which pins them in its own test).
"""

from collections import defaultdict

from django.db import migrations

EVENT_MODELS = {
    0: "WeatherEvent",
    1: "ProductionEvent",
    2: "ChemicalEvent",
    3: "GeneralEvent",
    4: "EquipmentEvent",
    5: "SoilManagementEvent",
    6: "PestManagementEvent",
    7: "BusinessEvent",
}

#: (app, model, type field, id field, identity field)
LINKS = (("documents", "GeneratedDocument", "event_type", "event_id", "activity"),)


def backfill(apps, schema_editor):
    for app_label, model_name, type_field, id_field, fk_field in LINKS:
        Model = apps.get_model(app_label, model_name)
        rows = (
            Model.objects.filter(**{f"{fk_field}__isnull": True})
            .exclude(**{f"{type_field}__isnull": True})
            .exclude(**{f"{id_field}__isnull": True})
            .values_list("pk", type_field, id_field)
        )
        by_type = defaultdict(list)
        for pk, code, event_id in rows:
            by_type[code].append((pk, event_id))
        for code, items in by_type.items():
            name = EVENT_MODELS.get(code)
            if name is None:
                continue
            Event = apps.get_model("history", name)
            identity = dict(Event.objects.filter(pk__in=[e for _, e in items]).values_list("pk", "activity_id"))
            for pk, event_id in items:
                activity_id = identity.get(event_id)
                if activity_id is not None:
                    Model.objects.filter(pk=pk).update(**{f"{fk_field}_id": activity_id})


def unlink(apps, schema_editor):
    for app_label, model_name, _type, _id, fk_field in LINKS:
        apps.get_model(app_label, model_name).objects.update(**{fk_field: None})


class Migration(migrations.Migration):
    dependencies = [("documents", "0009_activity_link"), ("history", "0251_backfill_activity_identity")]

    operations = [migrations.RunPython(backfill, unlink)]
