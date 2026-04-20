"""
NOP 7 CFR 205.202 — Organic Transition Status (Sprint 2.2).

Computes the earliest date a parcel becomes eligible to harvest crops marketable as
USDA Organic. Per 7 CFR 205.202(b), land must have had no prohibited substances applied
for the 36 months immediately preceding harvest of the first organic crop.

Two evidence sources, in priority order:
  1. ParcelCropHistory.date_last_prohibited (farmer-declared, retroactive history)
  2. ChemicalEvent records on Histories tied to this parcel where the chemical is NOT
     organic-approved (live recordkeeping data).

The latest of (1) and (2) sets the transition clock. transition_complete = latest + 36 months.

Returns a structured payload usable by the API endpoint, frontend transition card, and
audit export field-history section.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from django.utils import timezone

from dateutil.relativedelta import relativedelta

# 7 CFR 205.202(b): "no prohibited substance...applied for a period of 3 years
# immediately preceding harvest." We use calendar months (relativedelta) so the
# clock matches certifier expectations exactly, not a 30-day approximation.
TRANSITION_MONTHS = 36
ORGANIC_OK_VALUES = {"omri_listed", "usda_nop_approved", "organic_equivalent"}


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

    # Source 2: ChemicalEvent records on this parcel where organic_approved is NOT in
    # the allow-list (i.e., synthetic/conventional). Includes blank organic_approved
    # since "not classified" defaults to non-organic.
    chemical_qs = ChemicalEvent.objects.filter(
        history__parcel=parcel,
    ).exclude(organic_approved__in=ORGANIC_OK_VALUES)
    for ev in chemical_qs:
        if not ev.date:
            continue
        findings.append(
            ProhibitedFinding(
                source="ChemicalEvent",
                date_observed=ev.date.date() if hasattr(ev.date, "date") else ev.date,
                description=(
                    f"{ev.commercial_name or ev.get_chemical_subtype_display() or 'Chemical'}"
                    f" — organic_approved: {ev.organic_approved or 'unclassified'}"
                ),
                record_id=ev.pk,
            )
        )

    findings.sort(key=lambda f: f.date_observed, reverse=True)

    today = timezone.now().date()

    if not findings:
        # No evidence of prohibited substances — eligible by absence of contrary evidence.
        # Inspector can still demand affidavits per 7 CFR 205.202(b).
        return TransitionStatus(
            parcel_id=parcel.pk,
            parcel_name=parcel.name,
            is_eligible=True,
            transition_complete_date=None,
            days_remaining=0,
            last_prohibited_date=None,
            findings=[],
            note=(
                "No prohibited substance applications recorded. Field history affidavits "
                "may still be required by the certifier per 7 CFR 205.202(b)."
            ),
        )

    last_prohibited = findings[0].date_observed
    transition_complete = last_prohibited + relativedelta(months=TRANSITION_MONTHS)
    days_remaining = max(0, (transition_complete - today).days)
    is_eligible = today >= transition_complete

    return TransitionStatus(
        parcel_id=parcel.pk,
        parcel_name=parcel.name,
        is_eligible=is_eligible,
        transition_complete_date=transition_complete,
        days_remaining=days_remaining,
        last_prohibited_date=last_prohibited,
        findings=findings,
        note=(
            "Eligible for organic harvest."
            if is_eligible
            else f"{days_remaining} day(s) remaining in 36-month transition (7 CFR 205.202)."
        ),
    )
