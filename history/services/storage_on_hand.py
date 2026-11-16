"""
Recorded harvested minus recorded sold, per storage location, for one season.

WHY THIS EXISTS
---------------
At inspection the inspector points at product IN STORAGE ("what is in cooler 3, and which records
are behind it?"). Every harvest pick carries `storage_location`, and every sale names the picks it
drew from (`SalesRecord.harvest_events`), but nothing put the two together per location.

RULES
-----
* The figure is RECORDED harvested minus RECORDED sold, never "inventory": nobody counted the
  cooler, and shrink, culls and repacks have no record here. The screen labels it so.
* Each location is summed by the season balance's own machinery
  (`certifications.services.audit_trail_exhibit._lot_balance`), so units fold and refuse exactly
  as they do on the trace and the exhibit: different units are never added, a record with no
  quantity or no unit stops the sum, and the reason is stated as a code instead of a number.
* A sale is subtracted from a location only when EVERY pick it names was stored there. A sale
  that names picks in several locations is listed as unallocated, with the locations named: the
  records do not say how the load split, and inventing a split is a fabricated number. A sale that
  names no pick is unallocated too. Neither is subtracted from any location, and the screen says so.
* A pick with a blank `storage_location` is its own "location not recorded" bucket, never merged
  into a named one.
* Voided sales never count (`SalesRecord.objects.live()`).
"""

from __future__ import annotations

from certifications.services.audit_trail_exhibit import _fmt_qty, _lot_balance, fmt_total

#: The bucket key for picks whose storage location is blank.
NOT_RECORDED = ""


def location_key(value) -> str:
    """The location as written, trimmed and with runs of spaces collapsed. Nothing else is
    folded: "Cooler 3" and "Cooler 3B" are different rooms, and only the operator can say two
    spellings are one place."""
    return " ".join((value or "").split())


def _location_row(location: str, picks: list, sales: list) -> dict:
    balance = _lot_balance(picks, sales)
    code = balance.not_computed_code
    units = list(balance.units_seen)
    # `_lot_balance` sums records that ALL carry no unit (one unit: blank). A number with no unit
    # is not a quantity anybody can check against a cooler, so it is not stated here.
    if not code and not balance.unit:
        code, units = "unit_not_recorded", [""]
    elif "" in units:
        code = "unit_not_recorded"
    computed = not code
    diff = balance.difference if computed else None
    return dict(
        location=location,
        location_recorded=location != NOT_RECORDED,
        pick_count=len(picks),
        sale_count=len(sales),
        harvested=fmt_total(balance.harvested, balance.unit) if computed and balance.harvested is not None else "",
        packed_out=fmt_total(balance.packed_out, balance.unit) if computed and balance.packed_out is not None else "",
        sold=fmt_total(balance.sold, balance.unit) if computed and balance.sold is not None else "",
        difference=fmt_total(diff, balance.unit) if diff is not None else "",
        not_computed=not computed,
        not_computed_code=code,
        units=units,
        # As on the season balance: a sale not invoiced as organic is inside "sold" (it left the
        # cooler), and only a sale of the buffer crop is counted apart (overall review 2026-11,
        # OV-FJ-C24: counting every unmarked sale apart kept sold fruit "on hand").
        sold_not_organic_count=balance.sold_not_organic_count,
        sold_not_organic=(
            fmt_total(balance.sold_not_organic, balance.unit)
            if computed and balance.sold_not_organic is not None and balance.unit
            else ""
        ),
        buffer_sale_count=balance.buffer_sale_count,
        buffer_sold=(
            fmt_total(balance.buffer_sold, balance.unit)
            if computed and balance.buffer_sold is not None and balance.unit
            else ""
        ),
    )


def _sale_row(sale, reason: str, locations) -> dict:
    return dict(
        sale_id=sale.pk,
        date=sale.sale_date.isoformat() if sale.sale_date else "",
        buyer=(sale.buyer_name or "").strip(),
        quantity=_fmt_qty(sale.quantity, sale.quantity_unit),
        invoice=(sale.invoice_number or "").strip(),
        reason=reason,  # names_no_pick | several_locations
        locations=sorted(locations),
    )


def on_hand_by_location(season) -> dict:
    """One row per storage location the season's picks went into, plus the sales no location
    can claim. Two queries."""
    from history.models import ProductionEvent, SalesRecord

    picks = list(ProductionEvent.objects.filter(history=season, type=ProductionEvent.HARVESTING).order_by("date", "pk"))
    sales = list(
        SalesRecord.objects.live()
        .filter(production=season)
        .prefetch_related("harvest_events")
        .order_by("sale_date", "pk")
    )

    picks_at: dict[str, list] = {}
    for ev in picks:
        picks_at.setdefault(location_key(ev.storage_location), []).append(ev)

    sales_at: dict[str, list] = {}
    unallocated = []
    for sale in sales:
        named = list(sale.harvest_events.all())
        locations = {location_key(ev.storage_location) for ev in named}
        if not named:
            unallocated.append(_sale_row(sale, "names_no_pick", ()))
        elif len(locations) > 1:
            unallocated.append(_sale_row(sale, "several_locations", locations))
        else:
            sales_at.setdefault(locations.pop(), []).append(sale)

    # Named locations alphabetically, the "not recorded" bucket last.
    order = sorted(set(picks_at) | set(sales_at), key=lambda k: (k == NOT_RECORDED, k.lower(), k))
    return dict(
        locations=[_location_row(k, picks_at.get(k, []), sales_at.get(k, [])) for k in order],
        unallocated_sales=unallocated,
        season_open=season.finish_date is None,
    )
