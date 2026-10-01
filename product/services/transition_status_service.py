"""
NOP 7 CFR 205.202 — Organic Transition Status (Sprint 2.2).

Computes the earliest date a parcel becomes eligible to harvest crops marketable as
USDA Organic. Per 7 CFR 205.202(b), land must have had no prohibited substances applied
for the 36 months immediately preceding harvest of the first organic crop.

Three evidence sources:
  1. ParcelCropHistory.date_last_prohibited (farmer-declared, retroactive history)
  2. Dated input events on Histories tied to this parcel (chemical applications, soil
     amendments, beneficial releases) recorded as NOT organic-approved. Until 2026-10-01 only
     chemical events were read (OSP alignment audit T21); see product/services/input_evidence.py.
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

from common.field_registry import ORGANIC_APPROVED_OK_VALUES

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

    # Source 2: dated input events on this parcel that AFFIRMATIVELY state a prohibited input.
    #
    # This used to be `.exclude(organic_approved__in=ORGANIC_OK_VALUES)` on chemical events only:
    # every value off the allow-list reset the 36-month clock, blanks included, so a field never
    # filled became a finding with a three-year consequence. Only a prohibited status moves the
    # clock. An unknown status is collected apart and named, because "we don't know" is a real gap
    # an inspector should see, but it is not "a prohibited substance was applied here".
    #
    # Since 2026-10-01 soil amendments and beneficial releases are read too (audit T21). An unknown
    # input older than the 36-month window cannot bear on it and is not listed.
    from product.services.input_evidence import PROHIBITED, UNKNOWN, parcel_inputs

    window_start = timezone.now().date() - relativedelta(months=TRANSITION_MONTHS)
    unclassified: List[ProhibitedFinding] = []
    for record in parcel_inputs(parcel):
        if record.status == PROHIBITED:
            findings.append(
                ProhibitedFinding(
                    source=record.source,
                    date_observed=record.day,
                    description=f"{record.product} ({record.kind}) — organic status: {record.raw_status}",
                    record_id=record.record_id,
                )
            )
        elif record.status == UNKNOWN and record.day >= window_start:
            unclassified.append(
                ProhibitedFinding(
                    source=f"{record.source}(unclassified)",
                    date_observed=record.day,
                    description=f"{record.product} ({record.kind}) — organic status not recorded",
                    record_id=record.record_id,
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
            f" {len(unclassified)} input application(s) on this parcel inside the 36-month window "
            f"have no organic status recorded ({_named}); the transition "
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
        # 2026-09-09 — read "Eligible for organic harvest." when the clock had run out. That is the
        # self-assigned eligibility call `transition_verdict` exists to prevent, and the two printed
        # side by side on the parcel page: "Not established — no field history on file" over
        # "Eligible for organic harvest." (an affidavit dated the clock; no field history existed).
        # The note states the arithmetic; the determination is the certifying agent's.
        note=(
            (
                f"36 months have elapsed since the last recorded prohibited application "
                f"({last_prohibited.isoformat()}); § 205.202(b) eligibility is the certifying agent's determination."
            )
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

    unknown = _unknown_clause(status)
    if status.unclassified:
        # An input of unknown status inside the window blocks every clean statement, and is never
        # read as prohibited either: with a prohibited one on record the clock runs from it "at
        # the earliest", because any of the unknown ones could be later. Before 2026-10-01 a clock
        # that had run out printed "In transition — 0 days remaining" here.
        if status.last_prohibited_date is not None and (status.days_remaining or 0) > 0:
            return (
                f"In transition — {status.days_remaining} days remaining (eligible "
                f"{status.transition_complete_date}) at the earliest{unknown} (§ 205.202(b))"
            )
        if status.last_prohibited_date is not None:
            # The clock from the last recorded prohibited application has run out, and that date
            # IS fixed; what cannot be said is that nothing prohibited came after it (review of
            # back #83: this said "no start date can be fixed" beside a printed start date).
            return (
                f"Not established from records in Trazo — 36 months have elapsed since the last recorded "
                f"prohibited application ({status.last_prohibited_date.isoformat()}), but "
                + _unknown_clause(
                    status, tail="so the record cannot show that nothing prohibited was applied since"
                ).removeprefix(" — ")
                + " (§ 205.202(b))"
            )
        return f"Not established from records in Trazo{unknown} (§ 205.202(b))"
    if status.is_eligible and not has_field_history:
        return "Not established — no field history on file (§ 205.202(b))"
    if status.is_eligible:
        # 🔴 2026-09-30 (OSP alignment audit, T21). This returned the bare word "Eligible", printed
        # beside "none recorded" and an unanswered land declaration: the absence of a record read
        # as a determination. The records support one fact, so the line states that fact. What the
        # operator declares is a separate line (operator_statement_lines) and never derived from it.
        return (
            "No prohibited substance on record in Trazo for the last 36 months; eligibility under "
            "§ 205.202(b) is the certifying agent's determination"
        )
    if status.last_prohibited_date is None:
        return "Not established from records in Trazo (§ 205.202(b))"
    return f"In transition — {status.days_remaining} days remaining (eligible {status.transition_complete_date})"


def _unknown_clause(status: TransitionStatus, tail: str = "so no start date can be fixed") -> str:
    """ " — N input(s) of unknown status inside the window: A (date); B (date)", or ""."""
    if not status.unclassified:
        return ""
    shown = status.unclassified[:5]
    named = "; ".join(f"{f.description.rsplit(' — ', 1)[0]}, {f.date_observed.isoformat()}" for f in shown)
    rest = len(status.unclassified) - len(shown)
    if rest > 0:
        named += f"; and {rest} more"
    return (
        f" — {len(status.unclassified)} input(s) on this parcel inside the 36-month window have no "
        f"organic status recorded ({named}), {tail}"
    )


#: `currently_certified` answers as the operator's own statement. Printed as a statement, never as
#: evidence about prohibited inputs.
_CERTIFICATION_STATEMENT = {
    "yes": "The operation states this parcel is currently certified organic (Parcel Application F).",
    "previously": "The operation states this parcel was certified before and is not certified now (Parcel Application F).",
    "no": "The operation states this parcel has never been certified organic (Parcel Application F).",
}


def operator_statement_lines(parcel) -> list[str]:
    """What the operator has said about this parcel's land, each statement on its own line.

    Two statements, kept apart on purpose:

      * certification status (`currently_certified`): a statement about the parcel's certificate;
      * the tenure declaration (`dlpm_none_within_tenure`): a statement that no prohibited
        material was applied since the operator began managing it.

    🔴 2026-09-30 (audit T21). The packet printed "Certified organic, as the operation states in F
    below; no prohibited substance is on record" when certification status was "yes", which read
    as a declaration about inputs that nobody made. The declaration is not even ASKED of a
    currently certified parcel (its `visible_when`), so this says it was not asked rather than
    inferring it. The declaration states are distinct: declared, answered No (a declined declaration,
    never read as "one was applied"), not declared, and not yet asked.
    """
    from certifications.osp_modules.conditions import answer_value

    answers = parcel.application_answers or {}
    lines: list[str] = []
    certified = answer_value(answers, "currently_certified")
    if certified in _CERTIFICATION_STATEMENT:
        lines.append(_CERTIFICATION_STATEMENT[certified])
    else:
        lines.append("The operation has not stated this parcel's certification status (Parcel Application F).")

    since = parcel.date_began_managing.isoformat() if parcel.date_began_managing else "the operator began managing it"
    declared = answer_value(answers, "dlpm_none_within_tenure")
    if declared is True:
        lines.append(f"The operator declares no prohibited material has been applied since {since}.")
    elif declared is False:
        # "No" to "no prohibited material has been applied" is a declined declaration, not a
        # statement that one WAS applied (the rule parcel_land_history.current_manager_row keeps).
        # State the answer; the dated records say what was applied, if anything does.
        lines.append(
            f"The operator answered No to the declaration that no prohibited material has been applied "
            f"since {since} (Parcel Application F)."
        )
    elif certified == "yes":
        lines.append(
            "The prohibited-materials declaration is not asked of a parcel the operation states is "
            "currently certified."
        )
    elif certified not in _CERTIFICATION_STATEMENT:
        # The declaration is shown only after certification status is answered "no" or
        # "previously" (its visible_when), so nobody has been asked it yet.
        lines.append(
            "The prohibited-materials declaration follows the certification-status answer, which has not " "been given."
        )
    else:
        lines.append("The operator has not declared whether a prohibited material was applied (Parcel Application F).")

    # WSDA AGR 2264 ref 13's N/A, a separate statement from the one above (audit T17-F2). Three
    # states; No is a declined statement, never "an input was applied".
    no_inputs = answer_value(answers, "no_inputs_within_tenure")
    if no_inputs is True:
        lines.append(f"The operator states no input materials of any kind have been applied since {since}.")
        if parcel.date_began_managing:
            from product.services.input_evidence import describe, parcel_inputs

            inside = [r for r in parcel_inputs(parcel) if r.day >= parcel.date_began_managing]
            if inside:
                lines.append(
                    f"[REVIEW] {len(inside)} dated input record(s) on this parcel fall inside that period "
                    f"(first: {describe(inside[0])}). The statement and the records disagree."
                )
    elif no_inputs is False:
        lines.append(
            f"The operator answered No to the statement that no input materials have been applied since {since}."
        )
    else:
        lines.append("The operator has not stated whether any input materials were applied (Parcel Application).")
    return lines
