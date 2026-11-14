"""Backfill FieldNoteConfirmation.activity from the pair it sits next to (schema remodel plan, slice B).

FieldNoteConfirmation is append-only: its own save() refuses any change but voiding, and its manager
refuses bulk updates. A migration's historical model carries neither, so `.update()` here writes the
one derived column and nothing else; no value the confirmation recorded is touched, and no save() or
signal runs. A pair whose event no longer exists stays unlinked: the census counts those orphans, and
an identity is never invented for them. Kind codes are frozen here (they equal history/taxonomy.py,
which pins them in its own test).
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


def backfill(apps, schema_editor):
    Confirmation = apps.get_model("fieldnotes", "FieldNoteConfirmation")
    by_type = defaultdict(list)
    for pk, code, event_id in Confirmation.objects.filter(activity__isnull=True).values_list(
        "pk", "event_type", "event_id"
    ):
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
                Confirmation.objects.filter(pk=pk).update(activity_id=activity_id)


def unlink(apps, schema_editor):
    apps.get_model("fieldnotes", "FieldNoteConfirmation").objects.update(activity=None)


class Migration(migrations.Migration):
    dependencies = [("fieldnotes", "0008_confirmation_activity_link")]

    operations = [migrations.RunPython(backfill, unlink)]
