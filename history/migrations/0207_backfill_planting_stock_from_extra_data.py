"""Promote rootstock / plant count / spacing out of ``extra_data`` into their new columns.

Until 0206 these three facts had no field, so every writer that had them — the demo seeders,
the COG Pro importer, the AI templates — parked them in ``extra_data`` under whatever key it
happened to use. ``rootstock`` was even on the consumer extra_data allow-list, so a shopper
could be shown a rootstock the grower had no way to enter.

This moves what already exists onto the columns the form, the registry and the certifier
packet now read. Deliberately non-destructive: the original ``extra_data`` keys are LEFT IN
PLACE. They are what a prior deploy would read if this release were rolled back, they cost
nothing, and rewriting a JSON blob to save a few bytes is not worth the risk of dropping a
key some other consumer still reads.

Only fills a column that is currently empty — an operator-entered value always wins.
"""

from django.db import migrations

#: extra_data keys seen in real data, in preference order. `planting_rate` is COG Pro's
#: spacing column ("27 ft x 22 ft"); their SECOND Planting Rate column carries density and is
#: imported as `planting_rate_2`.
ROOTSTOCK_KEYS = ("rootstock",)
COUNT_KEYS = ("trees_planted", "trees_replanted", "plants_planted", "plant_count")
SPACING_KEYS = ("planting_rate", "spacing_m", "row_spacing", "plant_spacing", "planting_rate_2")

SEED_SOURCED_SUBTYPES = ("PL", "TR")


def _first(extra, keys):
    """First non-empty value among `keys`, looking one level into the importer payloads.

    The COG Pro importer nests everything it read under `extra_data["cogpro_import"]`, so a
    top-level-only lookup would miss exactly the migrated growers this backfill exists for —
    their spacing lives at `extra_data["cogpro_import"]["planting_rate"]` ("27 ft x 22 ft").
    """
    sources = [extra]
    for container in ("cogpro_import", "custom_fields"):
        nested = extra.get(container)
        if isinstance(nested, dict):
            sources.append(nested)
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value not in (None, "", [], {}):
                return value
    return None


def forwards(apps, schema_editor):
    ProductionEvent = apps.get_model("history", "ProductionEvent")
    filled = 0

    # Filter in Python, not with .exclude() on the JSONField — a JSONField exclude() has
    # returned zero rows in this codebase before, and a backfill that silently skips its
    # targets is worse than one that never ran.
    for event in ProductionEvent.objects.filter(type__in=SEED_SOURCED_SUBTYPES).iterator():
        extra = event.extra_data
        if not isinstance(extra, dict) or not extra:
            continue

        updates = []

        if not event.rootstock:
            value = _first(extra, ROOTSTOCK_KEYS)
            if value:
                event.rootstock = str(value)[:120]
                updates.append("rootstock")

        if event.plants_established is None:
            value = _first(extra, COUNT_KEYS)
            if value is not None:
                try:
                    count = int(str(value).strip())
                except (TypeError, ValueError):
                    count = None
                # PositiveIntegerField — a negative or zero count is not a plant count.
                if count and count > 0:
                    event.plants_established = count
                    updates.append("plants_established")

        if not event.plant_spacing:
            value = _first(extra, SPACING_KEYS)
            if value:
                event.plant_spacing = str(value)[:60]
                updates.append("plant_spacing")

        if updates:
            event.save(update_fields=updates)
            filled += 1

    if filled:
        print(f"  backfilled planting-stock fields on {filled} event(s)")


def backwards(apps, schema_editor):
    """No-op. The source keys were never removed from extra_data, so nothing is lost by
    leaving the columns populated; 0206 drops them anyway if the schema is reversed."""


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0206_planting_stock_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
