"""Build a production's season plan from a crop-template selection.

A season plan is a list of SUGGESTED practices. It is not a set of records, and this
module is the only thing that turns a template selection into rows. See
``history.models.ProductionPlanItem`` for why that distinction is load-bearing.

⛔ Nothing here may create a ``CommonEvent`` subclass, and nothing here may put a VALUE on a
plan item. The operator authors records (7 CFR 205.201(a)); the plan only says WHICH practice
the crop usually needs and roughly WHEN. See ``ProductionPlanItem`` for why carrying the
catalogue's field values was removed before it shipped.

The build is SERVER-AUTHORITATIVE: the client sends which catalogue suggestions the
operator ticked, by id, and every value on the resulting row is read from the catalogue.
Nothing about a plan item is client-supplied, so there is no mass-assignment surface and
no way for a payload to invent a practice that is not in the catalogue.
"""

import logging
import re
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

#: Month name -> ordinal. Matched against a template's prose window
#: ("December - February", "Late March", "March-April").
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

#: Production methods under which a prohibited synthetic input must never be SUGGESTED.
#: Mirrors ORGANIC_PRODUCTION_METHODS in QuickStartProduction.tsx — but this copy is the
#: one that decides, because a rule enforced only in the browser is not enforced.
ORGANIC_PRODUCTION_METHODS = frozenset({"organic", "regenerative", "biodynamic"})


def parse_window_month(timing: Optional[str]) -> Optional[int]:
    """First month named in a template's prose window, or None.

    Returns a MONTH, never a day. A month is a property of an agronomic window; a day
    would be an invented fact about an activity that has not happened. The frontend's old
    ``calculateEventDate`` returned the 15th of this month — that is the bug this replaces.
    """
    if not timing:
        return None
    text = str(timing)

    # Matched CASE-SENSITIVELY on the capitalised name, with word boundaries.
    #
    # "May" is also an ordinary English word, and so are "March" and "August". A bare
    # `find()` over a lowercased string read the "may" in "Post-harvest; may extend into
    # November" as the month of May — a window seven months off, and nothing downstream
    # could flag it, because a month is a plausible month. Requiring the capital is the
    # signal that actually separates the two, and it is how every value in the catalogue is
    # written ("December - February", "May - August", "Late March").
    #
    # Degrades honestly: a lowercase "december" yields None, i.e. "no month known", which
    # only costs ordering and the upcoming-practices view. `planned_window` still carries
    # the operator-visible text either way. A WRONG month would not degrade honestly.
    #
    # Scanned by position so "December - February" yields December, not whichever month
    # happens to come first in dict order.
    best: Optional[int] = None
    best_at = len(text) + 1
    for name, ordinal in _MONTHS.items():
        match = re.search(rf"\b{name.capitalize()}\b", text)
        if match and match.start() < best_at:
            best, best_at = ordinal, match.start()
    return best


def is_prohibited_suggestion(backend_fields: Dict[str, Any], production_method: Optional[str]) -> bool:
    """True when this catalogue entry must not be suggested to this operation.

    A synthetic herbicide on a certified-organic farm is a § 205.105 disqualification if it
    is ever performed, so Trazo does not put it on the plan. The operator can still log one
    by hand if they really applied it — the record is theirs to author either way.
    """
    method = str(production_method or "").lower()
    if method not in ORGANIC_PRODUCTION_METHODS:
        return False
    approval = str(backend_fields.get("organic_approved") or "").lower()
    subtype = str(backend_fields.get("chemical_subtype") or "").lower()
    return approval == "not_organic" or "synthetic" in subtype


def build_plan_items(history, template_id: Any, selected_ids: Iterable[Any]) -> List[Any]:
    """Persist the operator's ticked suggestions as this production's season plan.

    ``selected_ids`` are ``carbon.EventTemplate`` primary keys. Items are scoped to
    ``template_id`` so a payload cannot pull suggestions out of an unrelated crop's
    catalogue, and prohibited inputs are dropped server-side.

    Returns the created ``ProductionPlanItem`` rows.
    """
    from carbon.models import EventTemplate
    from history.models import ProductionPlanItem

    wanted = {value for value in (_as_int(raw) for raw in selected_ids or []) if value is not None}
    if not wanted:
        return []

    # FAIL CLOSED. An earlier version applied the production_template filter only when
    # `template_id` parsed, so a payload that simply omitted it — or sent garbage — pulled
    # arbitrary EventTemplate rows out of the whole catalogue by id. Suggestions must come
    # from the template the operator actually picked, or from nowhere.
    template_pk = _as_int(template_id)
    if template_pk is None:
        logger.warning(
            "Refusing to build a season plan for history %s: no usable template_id (%r)",
            getattr(history, "id", None),
            template_id,
        )
        return []

    queryset = EventTemplate.objects.filter(id__in=wanted, production_template_id=template_pk)

    rows: List[ProductionPlanItem] = []
    for index, template in enumerate(queryset.order_by("order_sequence", "id")):
        backend_fields = template.backend_event_fields or {}

        if is_prohibited_suggestion(backend_fields, history.production_method):
            logger.info(
                "Dropped prohibited suggestion %r from the season plan for history %s (%s operation)",
                template.name,
                history.id,
                history.production_method,
            )
            continue

        rows.append(
            ProductionPlanItem(
                history=history,
                source_template=template,
                source_template_version=getattr(template, "content_version", None),
                name=(template.name or "")[:150],
                description=(template.description or "")[:2000],
                event_type=template.backend_event_type,
                event_subtype=str(backend_fields.get("type") or "")[:20],
                planned_window=str(template.timing or "")[:100],
                planned_month=parse_window_month(template.timing),
                order_sequence=(template.order_sequence if template.order_sequence is not None else index),
            )
        )

    if rows:
        ProductionPlanItem.objects.bulk_create(rows)
    return rows


def plan_completeness(history) -> Dict[str, int]:
    """The counts the producer surfaces read.

    Completeness, not volume: "you planned 12 activities, you have logged 9" is a
    recordkeeping fact about this season. A raw event count is not.
    """
    from history.models import ProductionPlanItem

    counts = {"total": 0, "logged": 0, "pending": 0, "skipped": 0}
    for status in ProductionPlanItem.objects.filter(history=history).values_list("status", flat=True):
        counts["total"] += 1
        if status in counts:
            counts[status] += 1
    return counts


def _as_int(value: Any) -> Optional[int]:
    """Best-effort int, tolerating the frontend's stringly-typed ids."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
