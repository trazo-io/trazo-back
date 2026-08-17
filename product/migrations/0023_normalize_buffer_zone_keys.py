"""Normalize Parcel.buffer_zones onto the single canonical vocabulary.

Rows written before 2026-08-09 carry whichever spelling their writer happened to own:
the Parcel page wrote `adjacent_organic` / `crop_in_buffer` / `buffer_width_m`, the OSP
Parcel Application wizard wrote `adjacent_is_organic` / `crop_grown_in_buffer` /
`buffer_width_ft` / `prohibited_use_last_date`. Both are now aliases of one shape owned by
product.services.buffer_zones.

The one judgement call: a legacy `adjacent_organic: False` is ambiguous — the old serializer
stamped `False` onto every row whether or not the operator answered, so it cannot be read as
an affirmative "the neighbour is not certified". It is migrated to `None` (unanswered) rather
than asserting something the operator never said. A legacy `True` was only ever set by a
farmer ticking the box, so it is preserved. Same reasoning for `neighbor_notified`.

That reasoning applies ONLY to the legacy spellings. `adjacent_is_organic` is written solely
by the Parcel Application wizard, and only when a farmer touches the checkbox, so a `False`
there is a real answer and is preserved.
"""

from django.db import migrations


def _forwards(apps, schema_editor):
    from product.services.buffer_zones import BufferZoneError, drop_stamped_booleans, normalize_buffer_rows

    Parcel = apps.get_model("product", "Parcel")
    # Deliberately NOT `.exclude(buffer_zones=None)` — exclude() against a JSONField drops
    # rows in ways that are easy to get wrong, and the row count here is small. Filter in
    # Python where the semantics are obvious.
    for parcel in Parcel.objects.all().iterator():
        rows = parcel.buffer_zones
        if not rows or not isinstance(rows, list):
            continue
        if not all(isinstance(row, dict) for row in rows):
            # Leave a structurally malformed blob completely alone. Normalizing the dict rows
            # and dropping the rest would silently delete a boundary record, which is the
            # failure this migration exists to undo.
            continue
        prepared = [drop_stamped_booleans(row) for row in rows]
        try:
            normalized = normalize_buffer_rows(prepared)
        except BufferZoneError:
            # A row too malformed to normalize (e.g. missing direction) is left untouched
            # rather than silently dropped — a human should see it.
            continue
        if normalized != rows:
            parcel.buffer_zones = normalized
            parcel.save(update_fields=["buffer_zones"])


def _noop(apps, schema_editor):
    """Canonical rows remain readable by every current reader; nothing to undo."""


class Migration(migrations.Migration):
    dependencies = [
        ("product", "0022_parcelcrophistory_cover_crop"),
    ]

    operations = [
        migrations.RunPython(_forwards, _noop),
    ]
