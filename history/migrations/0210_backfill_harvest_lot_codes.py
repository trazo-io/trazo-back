"""Give every existing harvest pass a lot code.

7 CFR 205.103(b)(2) requires records "traceable back to the last certified operation", and
USDA's Guide for Organic Crop Producers is explicit that growers with multiple fields of the
same crop "will need to assign lot numbers to the crops harvested from different fields" — a
lot links "products to the fields of origin and the year or date".

Until 0209 the only lot identifier lived on History, i.e. per SEASON, so a multi-pick orchard
could not say which pick went to which buyer. This backfills the new per-pass code for records
already on file, using the same crop+block+date shape `suggest_harvest_lot_code()` offers new
records.

Deliberately conservative:
  * only HA events, only where the code is empty — an operator value is never overwritten;
  * skipped where the inputs would produce a meaningless code (no crop AND no block), because
    a lot code built from a date alone collides across blocks, which is the exact failure the
    code exists to prevent. Those rows keep the production-level trace and are reported.
"""

from django.db import migrations


def _token(value: str, length: int) -> str:
    return "".join(ch for ch in (value or "") if ch.isalnum())[:length].upper()


def _suggest(event, product_name: str) -> str | None:
    """Mirror of ProductionEvent.suggest_harvest_lot_code for the historical model.

    Migrations get a frozen model without custom methods, so the logic is repeated rather
    than imported — importing the live model here would silently change behaviour the next
    time that method is edited.

    Every token is stripped to alphanumerics: a product named "QA " otherwise yields the code
    `QA -BLOCKCEA-20251011`, i.e. a space inside an identifier that gets typed onto a bin tag
    and matched against a sales record. The same-day ordinal suffix is applied by the caller,
    which is the only place that can see the other picks.
    """
    if not event.date:
        return None
    what = _token(product_name, 3) or _token(event.variety, 3)
    where = _token(event.block_id, 8)
    if not what and not where:
        return None
    return "-".join(part for part in (what, where, event.date.strftime("%Y%m%d")) if part)


def forwards(apps, schema_editor):
    ProductionEvent = apps.get_model("history", "ProductionEvent")

    filled = 0
    skipped = 0
    # Same crop + same block + same DAY is a real pattern (a morning pick and an afternoon
    # pick). Minting one code for both would defeat the point, so the second pass on a day
    # gets -2, the third -3, ordered by id so the codes are stable across re-runs.
    used = set(
        ProductionEvent.objects.filter(type="HA")
        .exclude(harvest_lot_code__isnull=True)
        .exclude(harvest_lot_code="")
        .values_list("harvest_lot_code", flat=True)
    )
    for event in (
        ProductionEvent.objects.filter(type="HA")
        .select_related("history", "history__product")
        .order_by("id")
        .iterator()
    ):
        if event.harvest_lot_code:
            continue
        product = getattr(getattr(event, "history", None), "product", None)
        code = _suggest(event, getattr(product, "name", "") or "")
        if not code:
            skipped += 1
            continue
        base, n = code, 1
        while code in used:
            n += 1
            code = f"{base}-{n}"
        used.add(code)
        event.harvest_lot_code = code
        event.save(update_fields=["harvest_lot_code"])
        filled += 1

    if filled or skipped:
        print(f"  harvest lot codes: {filled} assigned, {skipped} skipped (no crop and no block)")


def backwards(apps, schema_editor):
    """No-op. 0209 drops the column if the schema is reversed; clearing values here would
    destroy operator-entered codes that happen to match the generated shape."""


class Migration(migrations.Migration):

    dependencies = [
        ("history", "0209_harvest_lot_identity"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
