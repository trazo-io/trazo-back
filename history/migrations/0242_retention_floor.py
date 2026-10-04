"""Run 7 (R7-10): move each finished production's `retention_until` forward to its floor.

The floor is the later of finish + 5 years and the newest covered record's creation + 5 years.
Forward-only: a stored date is never shortened. Events carry no creation stamp of their own; this
migration uses their date and the sales and amendment `created_at`, and the runtime hook
(`history.retention.extend_retention`) adds the audit-log creation times from now on.
"""

from django.db import migrations
from django.db.models import Max

EVENT_MODELS = (
    "ProductionEvent",
    "ChemicalEvent",
    "WeatherEvent",
    "GeneralEvent",
    "EquipmentEvent",
    "SoilManagementEvent",
    "PestManagementEvent",
    "BusinessEvent",
)


def _plus_five(day):
    try:
        return day.replace(year=day.year + 5)
    except ValueError:
        return day.replace(year=day.year + 5, month=3, day=1)


def forward(apps, schema_editor):
    History = apps.get_model("history", "History")
    SalesRecord = apps.get_model("history", "SalesRecord")
    EventAmendment = apps.get_model("history", "EventAmendment")
    events = [apps.get_model("history", name) for name in EVENT_MODELS]
    for history in History.objects.filter(finish_date__isnull=False).iterator():
        stamps = [history.finish_date, history.created_at]
        stamps.append(SalesRecord.objects.filter(production_id=history.pk).aggregate(m=Max("created_at"))["m"])
        stamps.append(EventAmendment.objects.filter(history_id=history.pk).aggregate(m=Max("created_at"))["m"])
        for model in events:
            stamps.append(model.objects.filter(history_id=history.pk).aggregate(m=Max("date"))["m"])
        days = [s.date() if hasattr(s, "date") else s for s in stamps if s is not None]
        floor = _plus_five(max(days))
        if history.retention_until is None or floor > history.retention_until:
            History.objects.filter(pk=history.pk).update(retention_until=floor)


class Migration(migrations.Migration):
    dependencies = [("history", "0241_rinse_step_help_text")]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
