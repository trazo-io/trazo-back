"""Which crops each off-farm handler or storage facility takes, read from the production records.

CCOF G6.1 C2 asks the finished products per handler, CCOF G6.2 A2 the crops stored per storage
facility, and OTCO C7 7.7-2 the products or crops per storage facility. A production (`History`)
already names the facilities its crop went to (`post_harvest_facilities`), so the crop per facility
is read from those links, never typed: an operator cannot list a crop the records do not show.
What the records cannot say (product detail, packaging form) is the facility's `products_detail`.
"""

from __future__ import annotations


def _crop_name(production) -> str:
    """The crop as the audit-trail exhibit and the product-list workbook name it: the product, else the
    crop type. One packet must name one season one way (review of #272)."""
    return getattr(production.product, "name", None) or getattr(production.crop_type, "name", None) or ""


def _year(production):
    when = production.finish_date or production.start_date
    return when.year if when else None


def _group(productions) -> list[tuple[str, list[int]]]:
    crops: dict[str, set] = {}
    for production in productions:
        name = _crop_name(production)
        if not name:
            continue
        year = _year(production)
        crops.setdefault(name, set())
        if year:
            crops[name].add(year)
    return [(name, sorted(years)) for name, years in sorted(crops.items(), key=lambda kv: kv[0].casefold())]


def crops_for(facility) -> list[tuple[str, list[int]]]:
    """[(crop, [season years])] for one facility, from the productions of its own farm linked to it."""
    productions = facility.productions.filter(parcel__establishment_id=facility.establishment_id).select_related(
        "crop_type", "product"
    )
    return _group(productions)


def crops_by_facility(establishment) -> dict[int, list[tuple[str, list[int]]]]:
    """{facility id: [(crop, [years])]} for every facility of the farm, in one query."""
    from history.models import History

    through = History.post_harvest_facilities.through
    links = through.objects.filter(
        postharvestfacility__establishment=establishment, history__parcel__establishment=establishment
    ).values_list("postharvestfacility_id", "history_id")
    by_facility: dict[int, set] = {}
    for facility_id, history_id in links:
        by_facility.setdefault(facility_id, set()).add(history_id)
    ids = {h for hs in by_facility.values() for h in hs}
    productions = {p.pk: p for p in History.objects.filter(pk__in=ids).select_related("crop_type", "product")}
    return {fid: _group(productions[h] for h in hs if h in productions) for fid, hs in by_facility.items()}


def crops_sentence(crops) -> str:
    """ "Blueberries (2025, 2026); Garlic (2026)" """
    return "; ".join(f"{name} ({', '.join(str(y) for y in years)})" if years else name for name, years in crops)
