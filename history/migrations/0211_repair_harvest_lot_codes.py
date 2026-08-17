"""Repair lot codes that 0210 generated before its two defects were found.

0210 shipped with a generator that had already run against real records here. Two defects
showed up only when the output was read back:

  * `QA -BLOCKCEA-20251011` — the crop token was sliced off the product name without
    stripping non-alphanumerics, so a product named "QA " put a SPACE inside an identifier.
    A lot code is typed onto a bin tag and matched against a sales record; a space in it is
    a transcription error waiting to happen.
  * two picks from one block on one day were both given `AVO-BLOCKCEA-20251007`. A morning
    pick and an afternoon pick are a normal pattern, and a lot code shared by two lots
    identifies neither — which is the whole failure 7 CFR 205.103(b)(2) traceability needs
    the code to prevent.

0210 was corrected too, so a fresh database never produces these. This migration exists for
databases where 0210 had already applied.

Only touches codes matching the GENERATED shape. An operator-entered code is left exactly as
typed even if it contains a space or duplicates another — their lot scheme is their own, and
silently rewriting an identifier that is already printed on physical bin tags would be worse
than the inconsistency.
"""

import re

from django.db import migrations

# The shape 0210 emits: TOKEN[-BLOCK]-YYYYMMDD, optionally with an ordinal suffix.
GENERATED_SHAPE = re.compile(r"^[A-Z0-9 ]{1,3}(?:-[A-Z0-9]{1,8})?-\d{8}(?:-\d+)?$")


def _token(value: str, length: int) -> str:
    return "".join(ch for ch in (value or "") if ch.isalnum())[:length].upper()


def _suggest(event, product_name: str):
    if not event.date:
        return None
    what = _token(product_name, 3) or _token(event.variety, 3)
    where = _token(event.block_id, 8)
    if not what and not where:
        return None
    return "-".join(part for part in (what, where, event.date.strftime("%Y%m%d")) if part)


def forwards(apps, schema_editor):
    ProductionEvent = apps.get_model("history", "ProductionEvent")

    events = list(
        ProductionEvent.objects.filter(type="HA")
        .exclude(harvest_lot_code__isnull=True)
        .exclude(harvest_lot_code="")
        .select_related("history", "history__product")
        .order_by("id")
    )

    # Codes we must not collide with: anything operator-shaped stays reserved.
    reserved = {ev.harvest_lot_code for ev in events if not GENERATED_SHAPE.match(ev.harvest_lot_code or "")}

    repaired = 0
    for event in events:
        current = event.harvest_lot_code or ""
        if not GENERATED_SHAPE.match(current):
            continue
        product = getattr(getattr(event, "history", None), "product", None)
        code = _suggest(event, getattr(product, "name", "") or "")
        if not code:
            continue
        base, n = code, 1
        while code in reserved:
            n += 1
            code = f"{base}-{n}"
        reserved.add(code)
        if code != current:
            event.harvest_lot_code = code
            event.save(update_fields=["harvest_lot_code"])
            repaired += 1

    if repaired:
        print(f"  harvest lot codes: {repaired} repaired (space in token / same-day duplicate)")


def backwards(apps, schema_editor):
    """No-op. Reinstating a duplicate or space-bearing code has no value."""


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0210_backfill_harvest_lot_codes"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
