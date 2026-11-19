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
    # 2026-11-04 (CCOF, WSDA and OTCO reviewer reads): "recorded as organic-approved" read as the
    # certifier's approval, which no input record holds. `describe` names the basis the operator
    # recorded instead; this is the fallback for a basis it does not know.
    ALLOWED: "logged by the operator as allowed",
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
    #: The record carries the listing its basis names (`listing_on_file`). Only a chemical
    #: application can hold one; an amendment's "OMRI listed" is always the operator's word alone.
    listing_on_file: bool = False


#: The listing each pick names, as the field on the record that holds it.
_LISTING_FIELD = {"omri_listed": "omri_product_id", "wsda_listed": "wsda_material_id"}


def listing_on_file(event, basis=None) -> bool:
    """Whether the record carries the listing its "OMRI listed" or "WSDA listed" pick names.

    One rule for every page of a packet. The Input Log's Organic Status cell has read it since
    2026-08-20; the land history printed the bare pick until 2026-11-16 (OV-MT-C08), so two pages
    of one packet disagreed about the same spray.

    The catalogue must be the one the pick names. The pick and the attached listing are two
    controls, and a product such as a fish fertilizer sits on both lists, so "OMRI listed" with
    only a WSDA row attached printed plain beside an OMRI verification table reading "OMRI ID: —"
    (review of back #460). Any other basis (a seal, a certifier's review) names no catalogue, so
    there is no listing for it to carry: False. Until back #500 either listing counted for it, and
    the Input Log printed a seal with an OMRI row attached as a bare label, as if a listing showed
    the seal or the certifier's review.
    """
    basis = (basis if basis is not None else getattr(event, "organic_approved", None)) or ""
    field = _LISTING_FIELD.get(str(basis).strip())
    return bool(field and getattr(event, field, None))


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
                listing_on_file(ev),
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
    from history.models import Production

    inputs = inputs if inputs is not None else parcel_inputs(parcel)
    out: List[SeasonSpan] = []
    for season in Production.objects.filter(parcel=parcel).order_by("start_date", "pk"):
        start, end = _day(season.start_date), _day(season.finish_date)
        count = sum(1 for r in inputs if r.season_id == season.pk)
        out.append(SeasonSpan(season.name or "Season", start, end, count))
    return out


#: The basis an operator can record for an allowed input, in the words the land history prints.
#: "Reviewed by my certifier" is the operator's statement that it was, never Trazo's finding.
_ALLOWED_BASIS_WORDS = {
    "omri_listed": "OMRI listed",
    "wsda_listed": "WSDA listed",
    "nop_seal_on_label": "NOP seal on the label",
    "usda_nop_approved": "NOP seal on the label",
    "certifier_approved": "reviewed by the certifier, per the operator",
    "organic_equivalent": "the operator's own assessment",
    "yes": "no basis named",
    "organic": "no basis named",
}


#: Picks that name a listing Trazo can look for on the record. A seal on the label or a
#: certifier's review is not a listing, and the line already attributes those to the operator.
_LISTING_BASIS = frozenset({"omri_listed", "wsda_listed"})


def describe(record: InputRecord) -> str:
    words = STATUS_WORDS[record.status]
    if record.status == ALLOWED and record.raw_status in _ALLOWED_BASIS_WORDS:
        basis = _ALLOWED_BASIS_WORDS[record.raw_status]
        if record.raw_status in _LISTING_BASIS and not record.listing_on_file:
            # The Input Log's words for the same pick, so the two pages read alike.
            basis = f"{basis} (no listing on file)"
        words = f"{words}: {basis}"
    return f"{record.day.isoformat()} · {record.product} · {record.kind} · {words}"
