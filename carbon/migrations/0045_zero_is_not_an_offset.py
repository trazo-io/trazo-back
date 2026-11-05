"""A zero carbon result is an emission of zero, not an offset (2026-11-05).

`create_carbon_entry_from_event` stored `type="offset"` for every result that was not positive,
so a zero (an answer: the activity emitted nothing, carbon-methodology.md) was counted as an offset
by every summary. The writer now stores "offset" only for a negative result; this relabels the
rows already written.

Only `type` changes: `amount`, `co2e_amount` and the row count are untouched, so the totals a
season shows and the blockchain layer-2 hash inputs (Sum of co2e_amount, Count) do not move.

Reversible exactly: before this migration no zero was ever stored as "emission", so the reverse
predicate selects the same rows.
"""

from django.db import migrations


def relabel(apps, schema_editor):
    CarbonEntry = apps.get_model("carbon", "CarbonEntry")
    CarbonEntry.objects.filter(type="offset", co2e_amount=0).update(type="emission")


def restore(apps, schema_editor):
    CarbonEntry = apps.get_model("carbon", "CarbonEntry")
    CarbonEntry.objects.filter(type="emission", co2e_amount=0).update(type="offset")


class Migration(migrations.Migration):
    dependencies = [("carbon", "0044_remove_iot_and_automation")]

    operations = [migrations.RunPython(relabel, restore)]
