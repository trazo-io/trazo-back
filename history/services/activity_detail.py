"""
Narrative detail for activity rows (WS-4 auto-narrative).

One place that decides which structured values a feed row carries for the
frontend narrative composer (config/events/narrative.ts) — and, later, for
dossier row summaries. Values only, never prose: the frontend owns wording
and localization, so backend English never leaks into an es-419 UI.

Keys are emitted only when the value is present — the composer treats every
key as optional.
"""

from __future__ import annotations

from decimal import Decimal

from history.taxonomy import BY_SLUG

# Codes are defined once, in history/taxonomy.py.
PRODUCTION_EVENT = BY_SLUG["production"].code
CHEMICAL_EVENT = BY_SLUG["chemical"].code


def narrative_detail(event_type: int, event) -> dict:
    """Small, type-aware dict of narrative-relevant values for one event row."""
    detail: dict = {}

    if event_type == CHEMICAL_EVENT:
        _put(detail, "commercial_name", getattr(event, "commercial_name", None))
        _put(detail, "applied_scope", getattr(event, "applied_scope", None))
        _put(detail, "applied_scope_detail", getattr(event, "applied_scope_detail", None))

    elif event_type == PRODUCTION_EVENT:
        subtype = getattr(event, "type", None)
        if subtype == "HA":
            qty = getattr(event, "yield_quantity", None)
            if qty is not None:
                # "4200.00" reads as machine output; strip insignificant zeros
                detail["yield_quantity"] = format(Decimal(qty).normalize(), "f")
                _put(detail, "yield_unit", getattr(event, "yield_unit", None))
            _put(detail, "amount_determination", getattr(event, "amount_determination", None))
            _put(detail, "harvest_destination", getattr(event, "harvest_destination", None))
        elif subtype == "EM":
            _put(detail, "cleaning_method", getattr(event, "cleaning_method", None))

    return detail


def _put(detail: dict, key: str, value) -> None:
    if value not in (None, ""):
        detail[key] = value
