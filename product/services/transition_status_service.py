"""
NOP 7 CFR 205.202 — Organic Transition Status (Sprint 2.2).

Computes the earliest date a parcel becomes eligible to harvest crops marketable as
USDA Organic. Per 7 CFR 205.202(b), land must have had no prohibited substances applied
for the 36 months immediately preceding harvest of the first organic crop.

Three evidence sources:
  1. ParcelCropHistory.date_last_prohibited (farmer-declared, retroactive history)
  2. ChemicalEvent records on Histories tied to this parcel where the chemical is NOT
     organic-approved (live recordkeeping data).
  3. LandownerAffidavit.last_prohibited_date — the signed statement covering the years before
     this operation kept records here, and the document CCOF's Parcel Application §G asks for.

The latest of (1), (2) and (3) sets the transition clock. transition_complete = latest + 36 months.

Returns a structured payload usable by the API endpoint, frontend transition card, and
audit export field-history section.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from django.utils import timezone

from dateutil.relativedelta import relativedelta

from common.field_registry import ORGANIC_APPROVED_OK_VALUES, ORGANIC_PROHIBITED_VALUES

# 7 CFR 205.202(b): "no prohibited substance...applied for a period of 3 years
# immediately preceding harvest." We use calendar months (relativedelta) so the
# clock matches certifier expectations exactly, not a 30-day approximation.
TRANSITION_MONTHS = 36

# Re-exported for backward compatibility with existing importers. The list itself
# now lives beside the enum it is derived from — see the comment there for why a
# local copy was a defect and not a convenience.
ORGANIC_OK_VALUES = ORGANIC_APPROVED_OK_VALUES


@dataclass
class ProhibitedFinding:
    source: str  # "ParcelCropHistory" or "ChemicalEvent"
    date_observed: date
    description: str
    record_id: Optional[int] = None


@dataclass
class TransitionStatus:
    parcel_id: int
    parcel_name: str
    is_eligible: bool
    transition_complete_date: Optional[date]
    days_remaining: Optional[int]
    last_prohibited_date: Optional[date]
    findings: List[ProhibitedFinding] = field(default_factory=list)
    # Applications whose organic status was never recorded. These do NOT date the
    # transition clock — missing data is not evidence of a prohibited substance —
    # but they are reported so an inspector knows the basis is incomplete.
    unclassified: List[ProhibitedFinding] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "parcel_id": self.parcel_id,
            "parcel_name": self.parcel_name,
            "is_eligible": self.is_eligible,
            "transition_complete_date": (
                self.transition_complete_date.isoformat() if self.transition_complete_date else None
            ),
            "days_remaining": self.days_remaining,
            "last_prohibited_date": (self.last_prohibited_date.isoformat() if self.last_prohibited_date else None),
            "findings": [
                {
                    "source": f.source,
                    "date": f.date_observed.isoformat(),
                    "description": f.description,
                    "record_id": f.record_id,
                }
                for f in self.findings
            ],
            "unclassified": [
                {
                    "source": f.source,
                    "date": f.date_observed.isoformat(),
                    "description": f.description,
                    "record_id": f.record_id,
                }
                for f in self.unclassified
            ],
            "note": self.note,
        }


def compute_transition_status(parcel) -> TransitionStatus:
    """Compute the parcel's organic transition status as of today."""
    from history.models import ChemicalEvent
    from product.models import ParcelCropHistory

    findings: List[ProhibitedFinding] = []

    # Source 1: ParcelCropHistory date_last_prohibited
    crop_history_qs = ParcelCropHistory.objects.filter(parcel=parcel, date_last_prohibited__isnull=False).order_by(
        "-date_last_prohibited"
    )
    for entry in crop_history_qs:
        findings.append(
            ProhibitedFinding(
                source="ParcelCropHistory",
                date_observed=entry.date_last_prohibited,
                description=(
                    f"Year {entry.year}, crop: {entry.crop_grown}. "
                    f"Substances: {entry.substances_applied or 'unspecified'}"
                ),
                record_id=entry.pk,
            )
        )

    # Source 2: ChemicalEvent records on this parcel that AFFIRMATIVELY state a
    # prohibited substance was applied.
    #
    # This used to be `.exclude(organic_approved__in=ORGANIC_OK_VALUES)` — every
    # value that was not on the allow-list reset the 36-month clock. Two ways that
    # produced false findings on the certifier's copy:
    #
    #   1. The allow-list was incomplete. An OMRI-listed copper fungicide stored as
    #      "organic" fell through and dated the transition — see field_registry.
    #   2. Blank / NULL fell through too, so a field the farmer simply never filled
    #      became a positive finding of prohibited-substance use with a three-year
    #      consequence. 94 of 234 chemical events carry no status.
    #
    # Now only ORGANIC_PROHIBITED_VALUES move the clock. Unclassified events are
    # collected separately and reported, because "we don't know" is a real gap an
    # inspector should see — it just isn't the same statement as "a prohibited
    # substance was applied here".
    unclassified: List[ProhibitedFinding] = []
    for ev in ChemicalEvent.objects.filter(history__parcel=parcel):
        if not ev.date:
            continue
        status = (ev.organic_approved or "").strip().lower()
        observed = ev.date.date() if hasattr(ev.date, "date") else ev.date
        label = ev.commercial_name or ev.get_chemical_subtype_display() or "Chemical"
        if status in ORGANIC_PROHIBITED_VALUES:
            findings.append(
                ProhibitedFinding(
                    source="ChemicalEvent",
                    date_observed=observed,
                    description=f"{label} — organic_approved: {status}",
                    record_id=ev.pk,
                )
            )
        elif status not in ORGANIC_APPROVED_OK_VALUES:
            unclassified.append(
                ProhibitedFinding(
                    source="ChemicalEvent(unclassified)",
                    date_observed=observed,
                    description=f"{label} — organic status not recorded",
                    record_id=ev.pk,
                )
            )

    # Source 3: the signed landowner affidavit — the ONLY source for the years before this
    # operation kept records in Trazo, and the document CCOF's Parcel Application §G asks for by
    # name. Omitting it let the packet print "Eligible" beside an affidavit whose signer had dated
    # a prohibited application: the two facts sat in one PDF, contradicting each other, because
    # only one of them reached the clock.
    #
    # A NULL date is not a finding — on this model it is the signed attestation that none were
    # ever applied (see the field's help_text), which is the opposite of missing data.
    from certifications.models import LandownerAffidavit

    for aff in LandownerAffidavit.objects.filter(parcel=parcel, last_prohibited_date__isnull=False):
        findings.append(
            ProhibitedFinding(
                source="LandownerAffidavit",
                date_observed=aff.last_prohibited_date,
                description=(
                    f"Signed affidavit for {parcel.name}: prohibited substance applied "
                    f"{aff.last_prohibited_date.isoformat()}"
                ),
                record_id=aff.pk,
            )
        )

    findings.sort(key=lambda f: f.date_observed, reverse=True)
    unclassified.sort(key=lambda f: f.date_observed, reverse=True)

    today = timezone.now().date()

    # Never let an unrecorded status read as a clean result. It does not date the
    # clock, but the inspector must be told the basis is incomplete.
    unclassified_note = ""
    if unclassified:
        # Name them. "2 applications are unclassified" tells the grower there is work but
        # not WHICH work, and an inspector cannot check an unnamed record — the same reason
        # the packet stopped truncating values. Capped so a parcel with a hundred blanks
        # does not swallow the paragraph, and the cap announces itself.
        _shown = unclassified[:5]
        # rsplit, not split: the description is f"{label} — organic status not recorded", and a
        # product legitimately named with an em dash ("Kocide 3000-O — copper") would lose half
        # its name to a left split.
        _named = "; ".join(f"{f.description.rsplit(' — ', 1)[0]} ({f.date_observed})" for f in _shown)
        _rest = len(unclassified) - len(_shown)
        if _rest > 0:
            _named += f"; and {_rest} more"
        unclassified_note = (
            f" {len(unclassified)} chemical application(s) on this parcel have no organic "
            f"status recorded ({_named}); the transition "
            f"date cannot be confirmed until they are classified."
        )

    if not findings:
        # No evidence of prohibited substances — eligible by absence of contrary evidence.
        # Inspector can still demand affidavits per 7 CFR 205.202(b).
        return TransitionStatus(
            parcel_id=parcel.pk,
            parcel_name=parcel.name,
            is_eligible=not unclassified,
            transition_complete_date=None,
            days_remaining=0,
            last_prohibited_date=None,
            findings=[],
            unclassified=unclassified,
            note=(
                "No prohibited substance applications recorded. Field history affidavits "
                "may still be required by the certifier per 7 CFR 205.202(b)."
            )
            + unclassified_note,
        )

    last_prohibited = findings[0].date_observed
    transition_complete = last_prohibited + relativedelta(months=TRANSITION_MONTHS)
    days_remaining = max(0, (transition_complete - today).days)
    is_eligible = today >= transition_complete

    return TransitionStatus(
        parcel_id=parcel.pk,
        parcel_name=parcel.name,
        is_eligible=is_eligible and not unclassified,
        transition_complete_date=transition_complete,
        days_remaining=days_remaining,
        last_prohibited_date=last_prohibited,
        findings=findings,
        unclassified=unclassified,
        note=(
            "Eligible for organic harvest."
            if is_eligible
            else f"{days_remaining} day(s) remaining in 36-month transition (7 CFR 205.202)."
        )
        + unclassified_note,
    )


def transition_verdict(status: TransitionStatus, *, has_field_history: Optional[bool] = None) -> str:
    """The § 205.202(b) line a certifier reads, in ONE place.

    `is_eligible` is reached "by absence of contrary evidence" — the service only sees rows that
    carry a `date_last_prohibited`, so a parcel with three documented clean years and a parcel with
    no records at all both come back with `findings == []`. Printing the favourable verdict for the
    second is a self-assigned eligibility call in a document the certifier reads, and eligibility is
    the certifying agent's determination, not ours.

    This function exists because that correction was made once, in the per-production audit export,
    and the OSP packet's parcel page went on printing "Eligible for organic harvest: Yes" from the
    same status object — the "fixed on the audited surface, alive on its sibling" failure this
    codebase keeps meeting. Two callers, one sentence. Add a third caller here, not a fourth copy.

    Pass `has_field_history` when it is already known; otherwise it is queried.
    """
    if has_field_history is None:
        from product.models import ParcelCropHistory

        has_field_history = ParcelCropHistory.objects.filter(parcel_id=status.parcel_id).exists()

    if status.is_eligible and not has_field_history:
        return "Not established — no field history on file (§ 205.202(b))"
    if status.is_eligible:
        return "Eligible"
    if status.last_prohibited_date is None:
        # Not "In transition": `is_eligible` is False here for the opposite reason to the one that
        # phrasing implies. Nothing prohibited is on record, so there is no clock at all; what
        # blocks the determination is an application whose organic status was never classified.
        blocked_by = ""
        if status.unclassified:
            blocked_by = (
                f" — {len(status.unclassified)} application(s) on this parcel have no organic "
                "status recorded, so no start date can be fixed"
            )
        return f"Not established from records in Trazo{blocked_by} (§ 205.202(b))"
    return f"In transition — {status.days_remaining} days remaining (eligible {status.transition_complete_date})"
