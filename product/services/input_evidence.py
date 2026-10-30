"""Every dated input on a parcel, in one of three evidence classes, and the seasons around them.

WHY THIS MODULE EXISTS
----------------------
OSP alignment audit 2026-10, T21 and T17-F2. The § 205.202(b) clock read chemical events only, so
a soil amendment or a beneficial release recorded as not organic-approved never moved it, and the
parcel page could not print the dated inputs WSDA AGR 2264 ref 13 asks for beside the typed land
history.

The three classes, kept apart on purpose:

    prohibited  the record says the input is not organic-approved. Dated; it starts the clock.
    allowed     the record gives an organic-approved basis.
    unknown     no status, or one Trazo does not recognise. It is NEVER read as prohibited (it
                starts no clock and prints no "last prohibited" date) and NEVER read as allowed
                (while one sits inside the window, no clean statement can be made).

A season is not evidence of what was NOT applied. A season with no input events shows that none
was recorded in Trazo, not that none was used, so `season_spans` is printed as supporting record
and never fills a gap in the 36-month accounting (`parcel_land_history.coverage`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from common.field_registry import ORGANIC_APPROVED_OK_VALUES, ORGANIC_PROHIBITED_VALUES, ORGANIC_UNRESOLVED_VALUES

PROHIBITED = "prohibited"
ALLOWED = "allowed"
UNKNOWN = "unknown"
#: The grower answered "Not yet confirmed" (R8-08): a recorded answer whose basis is still owed,
#: NOT a blank. Recordkeeping review S4 (F-08, 2026-10-07): it was classed UNKNOWN and so read
#: everywhere as "organic status not recorded", and one such input unset a certified parcel's
#: transition statement. It is named for what it is and never moves or blocks the clock.
NOT_CONFIRMED = "not_confirmed"

#: The words a certifier reads for each class. Statements about the RECORD, never verdicts.
STATUS_WORDS = {
    PROHIBITED: "recorded as not organic-approved",
    ALLOWED: "recorded as organic-approved",
    UNKNOWN: "organic status not recorded",
    NOT_CONFIRMED: "organic basis recorded as not yet confirmed",
}


@dataclass(frozen=True)
class InputRecord:
    day: date
    product: str
    kind: str  # chemical application | soil amendment | beneficial release
    status: str  # PROHIBITED | ALLOWED | UNKNOWN | NOT_CONFIRMED
    raw_status: str
    source: str  # ChemicalEvent | SoilManagementEvent | PestManagementEvent
    record_id: int
    season_id: Optional[int] = None


@dataclass(frozen=True)
class SeasonSpan:
    name: str
    start: Optional[date]
    end: Optional[date]
    inputs: int


#: `ChemicalEvent.type` -> the kind word printed beside the product.
_CHEMICAL_KIND = {
    "FE": "fertilizer application",
    "PE": "pesticide application",
    "FU": "fungicide application",
    "HE": "herbicide application",
}


def classify(raw: Optional[str], *, beneficial: bool = False) -> str:
    value = (raw or "").strip().lower()
    if beneficial:
        # The release record's own scale: yes / no / unknown.
        if value == "yes":
            return ALLOWED
        if value == "no":
            return PROHIBITED
        return UNKNOWN
    if value in ORGANIC_PROHIBITED_VALUES:
        return PROHIBITED
    if value in ORGANIC_APPROVED_OK_VALUES:
        return ALLOWED
    if value in ORGANIC_UNRESOLVED_VALUES:
        return NOT_CONFIRMED
    return UNKNOWN


def _day(value) -> Optional[date]:
    if value is None:
        return None
    return value.date() if hasattr(value, "date") else value


def parcel_inputs(parcel) -> List[InputRecord]:
    """Every DATED input event on seasons tied to this parcel, oldest first."""
    from history.models import ChemicalEvent, PestManagementEvent, SoilManagementEvent

    out: List[InputRecord] = []
    for ev in ChemicalEvent.objects.filter(history__parcel=parcel):
        day = _day(ev.date)
        if day is None:
            continue
        out.append(
            InputRecord(
                day,
                ev.commercial_name or ev.get_chemical_subtype_display() or "Chemical",
                # By the event's own type: "chemical application" beside feather meal and fish
                # emulsion read as a red flag to an organic reviewer (production specimen packet, 2026-10-29).
                _CHEMICAL_KIND.get(ev.type, "input application"),
                classify(ev.organic_approved),
                (ev.organic_approved or "").strip(),
                "ChemicalEvent",
                ev.pk,
                ev.history_id,
            )
        )
    for ev in SoilManagementEvent.objects.filter(history__parcel=parcel):
        day = _day(ev.date)
        # A soil TEST is not an input. Only an amendment the record names is.
        if day is None or not ((ev.amendment_type or "").strip() or (ev.amendment_product_name or "").strip()):
            continue
        out.append(
            InputRecord(
                day,
                ev.amendment_product_name or ev.amendment_type or "Soil amendment",
                "soil amendment",
                classify(ev.amendment_organic_approved),
                (ev.amendment_organic_approved or "").strip(),
                "SoilManagementEvent",
                ev.pk,
                ev.history_id,
            )
        )
    for ev in PestManagementEvent.objects.filter(history__parcel=parcel):
        day = _day(ev.date)
        # Scouting and trap counts are not inputs. A released organism is.
        if day is None or not (ev.beneficial_species or "").strip():
            continue
        out.append(
            InputRecord(
                day,
                ev.beneficial_species,
                "beneficial release",
                classify(ev.beneficial_organic_approved, beneficial=True),
                (ev.beneficial_organic_approved or "").strip(),
                "PestManagementEvent",
                ev.pk,
                ev.history_id,
            )
        )
    out.sort(key=lambda r: (r.day, r.source, r.record_id))
    return out


def season_spans(parcel, inputs: Optional[List[InputRecord]] = None) -> List[SeasonSpan]:
    """The seasons logged on this parcel, with their exact span and how many dated inputs they hold."""
    from history.models import History

    inputs = inputs if inputs is not None else parcel_inputs(parcel)
    out: List[SeasonSpan] = []
    for season in History.objects.filter(parcel=parcel).order_by("start_date", "pk"):
        start, end = _day(season.start_date), _day(season.finish_date)
        count = sum(1 for r in inputs if r.season_id == season.pk)
        out.append(SeasonSpan(season.name or "Season", start, end, count))
    return out


def describe(record: InputRecord) -> str:
    return f"{record.day.isoformat()} · {record.product} · {record.kind} · {STATUS_WORDS[record.status]}"
