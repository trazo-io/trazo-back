"""A zero carbon result is an emission of zero, not an offset (2026-11-05).

`create_carbon_entry_from_event` stored `type="offset"` for every result that was not positive,
so a zero (an answer: the activity emitted nothing, carbon-methodology.md) was counted as an offset
by every summary. The writer now stores "offset" only for a negative result; this relabels the
rows already written.

Only `type` changes, and only on rows whose `amount` AND `co2e_amount` are both 0, so no total a
season shows moves (they sum `amount`, `co2e_amount` or `effective_amount`, all 0 on these rows)
and neither do the blockchain layer-2 hash inputs (Sum of co2e_amount, Count).

Reversible exactly: before this migration no zero was ever stored as "emission", so the reverse
predicate selects the same rows.
"""

from django.db import migrations


def relabel(apps, schema_editor):
    CarbonEntry = apps.get_model("carbon", "CarbonEntry")
    # `amount=0` as well: a user-created offset (the offset endpoints) sets `amount` and leaves
    # `co2e_amount` at its default of 0, so `co2e_amount=0` alone would relabel REAL offsets
    # (review of back #308). The event writer sets `amount=abs(co2e)`, so its zero rows have both.
    CarbonEntry.objects.filter(type="offset", co2e_amount=0, amount=0).update(type="emission")


def restore(apps, schema_editor):
    CarbonEntry = apps.get_model("carbon", "CarbonEntry")
    CarbonEntry.objects.filter(type="emission", co2e_amount=0, amount=0).update(type="offset")


class Migration(migrations.Migration):
    dependencies = [("carbon", "0044_remove_iot_and_automation")]

    operations = [migrations.RunPython(relabel, restore)]
