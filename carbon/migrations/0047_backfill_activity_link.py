"""Link each CarbonEntry to the activity its writer's text names (schema remodel plan, CarbonEntry slice).

Historical models and `.update()` only: no save(), no signal, no `auto_now`, and no CarbonEntry is
created or deleted (a seal's second layer counts them per season). Only rows with no link are
touched, so it can run again.

A row is linked only when, frozen here as in carbon/event_link.py:
- its text has the writer's shape and names ONE event (description "Auto-calculated from
  <Class>(ID=<id>) event:", or before 2026-02-12 the registry id "REG-<Class>-<id>"), and the
  description and registry id do not name different events or classes;
- that event exists and belongs to the entry's production;
- no user created or edited the entry through the API (a CarbonAuditLog create/update row with a
  user): the API lets a user write both texts, so they prove nothing.
Everything else stays unlinked, and an identity is never invented: an Activity holds no legacy
pk, so a deleted event's tombstone cannot be found from the text. The census counts what is left.
"""

import re

from django.db import migrations
from django.db.models import Exists, OuterRef, Q

AUTO_DESCRIPTION = re.compile(r"^Auto-calculated from ([A-Z][A-Za-z]+Event)\(ID=(\d+)\) event:")
LEGACY_DESCRIPTION = re.compile(r"^Auto-calculated from ([A-Z][A-Za-z]+Event) event:")
REGISTRY_ID = re.compile(r"^REG-([A-Z][A-Za-z]+Event)-(\d+)$")

EVENT_MODELS = (
    "WeatherEvent",
    "ProductionEvent",
    "ChemicalEvent",
    "GeneralEvent",
    "EquipmentEvent",
    "SoilManagementEvent",
    "PestManagementEvent",
    "BusinessEvent",
)


def named_event(description, registry_id):
    described = AUTO_DESCRIPTION.match(description or "")
    registered = REGISTRY_ID.match(registry_id or "")
    if described:
        named = (described.group(1), int(described.group(2)))
        if registered and (registered.group(1), int(registered.group(2))) != named:
            return None
        return named
    if registered:
        legacy = LEGACY_DESCRIPTION.match(description or "")
        if legacy and legacy.group(1) != registered.group(1):
            return None
        return registered.group(1), int(registered.group(2))
    return None


def backfill(apps, schema_editor):
    CarbonEntry = apps.get_model("carbon", "CarbonEntry")
    CarbonAuditLog = apps.get_model("carbon", "CarbonAuditLog")
    total = CarbonEntry.objects.count()

    touched = Exists(
        CarbonAuditLog.objects.filter(carbon_entry=OuterRef("pk"), action__in=("create", "update"), user__isnull=False)
    )
    rows = (
        CarbonEntry.objects.filter(activity__isnull=True)
        .filter(Q(description__startswith="Auto-calculated from ") | Q(registry_verification_id__startswith="REG-"))
        .annotate(touched=touched)
        .values_list("pk", "production_id", "description", "registry_verification_id", "touched")
    )
    wanted = {}
    for pk, production_id, description, registry_id, is_touched in rows:
        named = named_event(description, registry_id)
        if named is None or named[0] not in EVENT_MODELS or is_touched:
            continue
        wanted.setdefault(named[0], []).append((pk, named[1], production_id))

    for name, items in wanted.items():
        Event = apps.get_model("history", name)
        events = {
            pk: (activity_id, history_id)
            for pk, activity_id, history_id in Event.objects.filter(pk__in=[e for _, e, _ in items]).values_list(
                "pk", "activity_id", "history_id"
            )
        }
        for pk, event_pk, production_id in items:
            found = events.get(event_pk)
            if found is not None and found[0] is not None and found[1] == production_id:
                CarbonEntry.objects.filter(pk=pk, activity__isnull=True).update(activity_id=found[0])

    assert CarbonEntry.objects.count() == total, "the backfill must not create or delete a CarbonEntry"


def unlink(apps, schema_editor):
    apps.get_model("carbon", "CarbonEntry").objects.update(activity=None)


class Migration(migrations.Migration):
    dependencies = [("carbon", "0046_activity_link")]

    operations = [migrations.RunPython(backfill, unlink)]
