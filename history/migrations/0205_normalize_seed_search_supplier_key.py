"""Rewrite NOP 5029 seed-search rows onto the canonical ``supplier_name`` key.

🔴 2026-08-15. The planting form wrote each commercial-availability search row as
``{supplier, date_contacted, result}`` while the certifier packet reads ``supplier_name``
and ``notes``. The serializer validated only the row COUNT, so the save succeeded and the
grower saw no error — and the NOP 5029 table in their audit export printed:

    Supplier Contacted | Date | Result                | Notes
    —                  | —    | Not available organic | —

Under 7 CFR 205.204(a)(1) the identity of the suppliers contacted is the evidence for the
exemption, so an empty column is worse than an absent table.

This backfills every stored row. It is deliberately additive — ``supplier`` is copied to
``supplier_name`` and then removed, and any other key on the row is left untouched — so a
row that was already correct (every row written by the demo seeder) is not disturbed.
"""

from django.db import migrations

ROW_KEYS = ("supplier_name", "date_contacted", "result", "notes")


def _normalize(rows):
    """Return (normalized_rows, changed)."""
    if not isinstance(rows, list):
        return rows, False
    changed = False
    out = []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        new_row = dict(row)
        legacy = new_row.pop("supplier", None)
        if legacy is not None:
            changed = True
            if not str(new_row.get("supplier_name") or "").strip() and str(legacy or "").strip():
                new_row["supplier_name"] = legacy
        for key in ROW_KEYS:
            if key not in new_row:
                new_row[key] = ""
                changed = True
        out.append(new_row)
    return out, changed


def forwards(apps, schema_editor):
    ProductionEvent = apps.get_model("history", "ProductionEvent")
    updated = 0
    # Filter in Python, not with .exclude(seed_search_attempts=[]).
    #
    # A JSONField exclude() is not a reliable "has content" test in this codebase — an
    # earlier incident had .exclude() on a JSONField return ZERO rows — and a migration that
    # silently skips the records it was written to repair is worse than no migration at all.
    # The table is small enough that a full scan costs nothing.
    for event in ProductionEvent.objects.only("id", "seed_search_attempts").iterator():
        if not event.seed_search_attempts:
            continue
        rows, changed = _normalize(event.seed_search_attempts)
        if changed:
            event.seed_search_attempts = rows
            event.save(update_fields=["seed_search_attempts"])
            updated += 1
    if updated:
        print(f"  normalized seed_search_attempts on {updated} production event(s)")


def backwards(apps, schema_editor):
    """Intentionally a no-op.

    Reversing would mean renaming ``supplier_name`` back to ``supplier`` and thereby
    re-blanking the certifier packet's supplier column. The forward state is a superset of
    the old one, so leaving it in place is safe for any earlier code path.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0204_salesrecord_transport_notes_and_unit_choices"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
