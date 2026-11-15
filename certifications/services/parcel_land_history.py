"""Land-history evidence for the Parcel Application page — what § 205.202(b) asks a reviewer to see.

WHY THIS MODULE EXISTS (2026-09-09)
-----------------------------------
Three certifiers ask the same things on the parcel form, and the packet answered them in the
wrong place or not at all:

* **The certificate.** CCOF Parcel Application §G, OTCO C2 2.4-2 and WSDA AGR 2264 ref 6 all accept
  the operation's current certificate as the land-history evidence for a parcel that is already
  certified. The certificate printed on the packet COVER only; the parcel's own page read like a
  first-time applicant's.
* **The prior-manager table.** CCOF §F6, OTCO 2.5-1/2.5-5 and WSDA AGR 2262 ask WHO managed the
  land during the 36 months, WHEN, and the last prohibited application under each. Every fact was
  captured on `LandownerAffidavit` and printed in the per-production audit dossier — a separate
  download — while the parcel page said "2 landowner affidavit(s) on file." Same defect class as
  the 2026-08-20 sweep: fixed on one surface, absent on the one the certifier actually asks it on.
* **The 36-month accounting.** Nothing showed that the operator's tenure plus the affidavit periods
  account for every day of the window. A signer who managed one of the three years read as
  covering all three.
* **Materials by name and date.** WSDA AGR 2264 ref 13 and OTCO 2.4-8/2.4-9 want each material and
  its application date for operator-typed years. `substance_applications` held them; the page never
  read it.

Everything here is pure derivation from records. It decides nothing: `coverage()` names gaps, it
does not rule on eligibility (that is the certifying agent's call — see `transition_verdict`).
Absences are stated as absences, never rendered as an affirmative — the rule
`attestation_absence_is_not_denial` and `LandownerAffidavit.no_materials_applied` already follow.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: § 205.202(b): no prohibited substance applied for three years before harvest.
WINDOW_MONTHS = 36

CURRENT_MANAGER = "current manager"
PRIOR_MANAGER = "prior manager"

#: The declared-materials states a reviewer reads on the table. Mirrors the audit dossier's
#: wording so the two artifacts agree about the same affidavit.
DECLARED_NONE = "None applied (declared)"
DECLARED_NOT_ANSWERED = "Not answered"
DECLARED_APPLIED_NONE_LISTED = '"No materials applied" answered No; no materials listed'


# ---------------------------------------------------------------------------
# The certificate of record, on the parcel's own page
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CertificateLine:
    """The operation's certificate, as ONE record stated it (see `operation_certificate`)."""

    number: str = ""
    agent: str = ""
    effective: Optional[date] = None
    expiry: Optional[date] = None
    document_url: str = ""
    source: str = ""

    @property
    def on_file(self) -> bool:
        return bool(self.number)


def certificate_line(establishment) -> CertificateLine:
    """Number and agent from `certificate_of_record`; dates and document only when the same
    `Certification` row supplied the number — never assembled from two records."""
    from certifications.services.operation_certificate import certificate_of_record

    cert = certificate_of_record(establishment.id)
    if not cert.number:
        return CertificateLine()
    effective = expiry = None
    url = ""
    if cert.source == "certification":
        try:
            from certifications.constants import NOP_CERTIFICATION_TYPES
            from certifications.models import Certification

            # Same order `operation_certificate` used to pick the number: active before inactive,
            # newest effective date first — so the dates belong to the row that supplied the number.
            rows = sorted(
                Certification.objects.filter(
                    establishment_id=establishment.id, certification_type__in=NOP_CERTIFICATION_TYPES
                ),
                key=lambda c: (c.is_active, c.effective_date or date.min),
                reverse=True,
            )
            row = next((r for r in rows if (r.certification_number or "").strip() == cert.number), None)
        except Exception:  # noqa: BLE001 — a lookup failure must never take the parcel page down
            logger.exception("Certificate row for %s could not be read", establishment.id)
            row = None
        if row is not None:
            effective, expiry, url = row.effective_date, row.expiry_date, (row.document_url or "").strip()
    return CertificateLine(
        number=cert.number, agent=cert.agent, effective=effective, expiry=expiry, document_url=url, source=cert.source
    )


# ---------------------------------------------------------------------------
# Who managed the land, and when
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManagerRow:
    """One line of the prior-controller table every certifier asks for."""

    name: str
    role: str
    period_start: Optional[date]
    #: None means "to present" for the current manager, "not recorded" for a prior one.
    period_end: Optional[date]
    last_prohibited: Optional[date]
    declared: str
    signed: Optional[date] = None
    #: Path inside the packet ZIP where the signed document rides, or "" when there is none.
    attachment: str = ""
    landowner: str = ""
    legal_description: str = ""
    #: A declaration of "none applied" over rows or records that name an application.
    contradiction: bool = False
    #: The prior manager's `LandownerAffidavit`, for the signer and site lines under the table.
    affidavit: object = None


def _safe(text: str, limit: int = 60) -> str:
    return (text or "").replace("/", "-").strip()[:limit]


def affidavit_attachment_name(affidavit) -> str:
    """Filename of the signed affidavit as it appears under `parcels/affidavits/`, or ""."""
    doc = getattr(affidavit, "signed_document", None)
    name = getattr(doc, "name", "") or ""
    if not name:
        return ""
    ext = ("." + name.rsplit(".", 1)[-1]) if "." in name else ""
    return f"{affidavit.pk}-{_safe(affidavit.previous_manager_name) or 'affidavit'}{ext}"


def _rows_naming_an_input(affidavit) -> list:
    return [
        row
        for row in (affidavit.yearly_history or [])
        if isinstance(row, dict)
        and any(str(row.get(k) or "").strip() for k in ("inputs", "manufacturer", "date_applied"))
    ]


def _declared(affidavit) -> Tuple[str, bool]:
    """(what the signer declared about materials, whether it contradicts their own table).

    Same four states as the audit dossier. An empty table is NOT a declaration of none —
    `declared_no_materials_applied()` is the only path to that wording.
    """
    naming = _rows_naming_an_input(affidavit)
    if affidavit.declared_no_materials_applied() and naming:
        return f"CONTRADICTION — declared none, {len(naming)} application(s) listed", True
    if affidavit.declared_no_materials_applied():
        return DECLARED_NONE, False
    if affidavit.yearly_history:
        return f"{len(affidavit.yearly_history)} year(s) listed", False
    if affidavit.no_materials_applied is False:
        # An explicit No to "no materials applied" is an answer, not a blank. It is printed as the answer
        # it is, never turned into a statement that materials were applied.
        return DECLARED_APPLIED_NONE_LISTED, False
    return DECLARED_NOT_ANSWERED, False


def operation_affidavits(parcel) -> list:
    """The operation's own signed-for-its-own-period affidavits (OTCO C2 2.5, CCOF ORGB49 §G), newest signed
    first. `.all()` then a filter in Python, so a caller's prefetch of `landowner_affidavits` is used."""
    manager = getattr(parcel, "landowner_affidavits", None)
    if manager is None:
        # Callers pass light stand-ins for a parcel (tests, previews); one without affidavits has none.
        return []
    own = [a for a in manager.all() if getattr(a, "signer_role", "") == "this_operation"]
    return sorted(own, key=lambda a: (a.previous_manager_signed_date or date.min, a.pk), reverse=True)


def prior_manager_rows(parcel) -> List[ManagerRow]:
    """One row per previous manager's `LandownerAffidavit` on the parcel, oldest management period first. The
    operation's own affidavit is not a prior party's and rides on the current manager's row."""
    rows: List[ManagerRow] = []
    for aff in parcel.landowner_affidavits.all():
        if getattr(aff, "signer_role", "prior_manager") == "this_operation":
            continue
        declared, contradiction = _declared(aff)
        rows.append(
            ManagerRow(
                name=aff.previous_manager_name or "—",
                role=PRIOR_MANAGER,
                period_start=aff.management_period_start,
                period_end=aff.management_period_end,
                last_prohibited=aff.last_prohibited_date,
                declared=declared,
                signed=aff.previous_manager_signed_date,
                attachment=(
                    f"parcels/affidavits/{affidavit_attachment_name(aff)}" if affidavit_attachment_name(aff) else ""
                ),
                landowner=aff.landowner_name or "",
                legal_description=aff.parcel_legal_description or "",
                contradiction=contradiction,
                affidavit=aff,
            )
        )
    rows.sort(key=lambda r: (r.period_start or date.min, r.name))
    return rows


def current_manager_row(parcel, answers: Optional[dict] = None) -> ManagerRow:
    """The operation itself — OTCO 2.5-4's "current landowner/manager requesting certification".

    The last-prohibited date is the transition service's, from all of its sources. The declaration
    is the operator's `dlpm_none_within_tenure` answer; True over a dated prohibited application
    inside the tenure is flagged, not hidden — the answer is theirs and stays visible.
    """
    answers = answers or {}
    last_prohibited = None
    try:
        from product.services.transition_status_service import compute_transition_status

        last_prohibited = compute_transition_status(parcel).last_prohibited_date
    except Exception:  # noqa: BLE001
        logger.exception("Transition status for parcel %s could not be computed", getattr(parcel, "pk", None))

    attested = answers.get("dlpm_none_within_tenure")
    if isinstance(attested, dict):
        attested = attested.get("value")
    began = parcel.date_began_managing
    contradiction = bool(attested is True and last_prohibited and began and last_prohibited >= began)
    if attested is True:
        declared = "None applied since tenure began (declared)"
    elif attested is False:
        # "No" to the statement "no prohibited material has been applied" is a negated boolean and
        # cannot be read as an affirmative that one WAS applied — the dated records say that, if
        # anything does. Print the declaration as not made; never invert it into a claim.
        declared = "Declaration not made (answered No)"
    elif _stated_certified(answers):
        # The declaration is not asked of a parcel stated currently certified, so "not answered" read
        # as a blank the operator left (production specimen packet, 2026-10-29).
        declared = "Not asked: parcel stated certified"
    else:
        declared = DECLARED_NOT_ANSWERED
    # OTCO C2 2.5: the current manager signs too. Its signed affidavit, when on file, fills the row's Signed and
    # Attachment columns and its statements print under the table like a prior manager's.
    own = operation_affidavits(parcel)
    signed_own = next((a for a in own if affidavit_attachment_name(a)), None)
    chosen = signed_own or (own[0] if own else None)
    return ManagerRow(
        name=parcel.establishment.name,
        role=CURRENT_MANAGER,
        period_start=began,
        period_end=None,
        last_prohibited=last_prohibited,
        declared=declared,
        signed=chosen.previous_manager_signed_date if chosen is not None else None,
        attachment=(
            f"parcels/affidavits/{affidavit_attachment_name(chosen)}"
            if chosen is not None and affidavit_attachment_name(chosen)
            else ""
        ),
        contradiction=contradiction,
        affidavit=chosen,
    )


def _stated_certified(answers) -> bool:
    value = answers.get("currently_certified")
    if isinstance(value, dict):
        value = value.get("value")
    return value == "yes"


# ---------------------------------------------------------------------------
# Does tenure + affidavits account for the whole window?
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Coverage:
    """What the records account for inside the 36-month window. Never an eligibility ruling."""

    window_start: date
    window_end: date
    #: None when the window cannot be assessed (no tenure start recorded).
    complete: Optional[bool]
    gaps: Tuple[Tuple[date, date], ...] = ()
    #: Affidavits that carry no management period and so cannot be placed in the window.
    unplaced: int = 0
    text: str = ""


def _months_back(day: date, months: int) -> date:
    year = day.year - months // 12
    month = day.month - months % 12
    if month <= 0:
        month += 12
        year -= 1
    # Clamp the day for short months (Feb 29 → Feb 28).
    for d in (day.day, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    return date(year, month, 1)  # pragma: no cover — 28 always exists


ONE_DAY = timedelta(days=1)


def _merge(intervals: Sequence[Tuple[date, date]]) -> List[Tuple[date, date]]:
    """Merge inclusive date ranges; a range starting the day after another ends is contiguous."""
    merged: List[Tuple[date, date]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + ONE_DAY:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def tenure_declaration(parcel) -> str:
    """Which operator statement covers the operator's own period, or "" when none does.

    Only an explicit statement covers it (OSP alignment audit T21): the no-prohibited-material
    declaration or the no-inputs-at-all statement, answered Yes. Tenure alone is not one, and
    neither is a logged season: a season with no input events shows that none was RECORDED.
    """
    from certifications.osp_modules.conditions import answer_value

    answers = getattr(parcel, "application_answers", None) or {}
    if answer_value(answers, "no_inputs_within_tenure") is True:
        return "no input materials of any kind (declared)"
    if answer_value(answers, "dlpm_none_within_tenure") is True:
        return "no prohibited material (declared)"
    # The operation's own signed affidavit for its period (OTCO C2 2.5, CCOF ORGB49 §G) is a statement too, and
    # only once the signed copy is on file (a row typed in Trazo is not a signature) and only when the period it
    # states covers the operation's own part of the window: one stating six months must not read as covering
    # all of it (review of back PR 396).
    if any(_own_affidavit_covers(a, parcel) for a in operation_affidavits(parcel)):
        return "its own signed affidavit (attached)"
    return ""


def _own_affidavit_covers(affidavit, parcel, today: Optional[date] = None) -> bool:
    """Signed copy on file, and a stated period from the start of the operation's part of the window (its tenure
    start, or the window start if earlier) through today."""
    if not affidavit_attachment_name(affidavit):
        return False
    began = getattr(parcel, "date_began_managing", None)
    start, end = affidavit.management_period_start, affidavit.management_period_end
    if not (began and start):
        return False
    today = today or date.today()
    own_from = max(began, _months_back(today, WINDOW_MONTHS))
    return start <= own_from and (end is None or end >= today)


def _verification_of_no_lapse(parcel, assessment) -> str:
    """ "no lapse in organic management (verification attached at <path>)", or "" when none is attached.

    Read from the route assessment the page prints, never from the document store alone (review of
    back #251): a route that does not list the verification (a transfer) ships no such file, so a
    stored one would be cited at a path the packet does not contain. And only on the operation's own
    certificate: a verification about another operation's tenure does not cover this one's period.
    """
    from certifications.services import certified_parcel_branch as cpb

    if assessment is None or assessment.branch != cpb.EXISTING_SITE:
        return ""
    item = next((i for i in assessment.items if i.key == cpb.CONTINUITY), None)
    if item is None or item.state != cpb.ATTACHED:
        return ""
    return f"no lapse in organic management (verification attached at {item.path})"


def coverage(parcel, prior: Sequence[ManagerRow], today: Optional[date] = None, assessment=None) -> Coverage:
    """Account for the 36-month window from explicit statements: the operator's declaration for its
    own period, and each prior manager's affidavit for theirs.

    The CCOF "N/A — my operation has had control for the past three years" case is derived from
    `date_began_managing`, never assumed. Gaps are named as date ranges so a reviewer sees exactly
    which days no one has attested for.

    2026-10-01 (audit T21): the operator's own period used to count as accounted for by tenure
    alone, so a parcel nobody had declared anything about read "every day of the window is
    accounted for". It now counts only with a declaration (`tenure_declaration`). Seasons logged
    in Trazo never count; they print beside this as supporting record (`season_evidence_lines`).
    """
    today = today or date.today()
    window_start = _months_back(today, WINDOW_MONTHS)
    began = parcel.date_began_managing
    if not began:
        return Coverage(
            window_start,
            today,
            complete=None,
            text=(
                "Tenure start is not recorded, so the 36-month window "
                f"({window_start.isoformat()} to {today.isoformat()}) cannot be accounted for on this page."
            ),
        )
    declared = tenure_declaration(parcel)
    answers = getattr(parcel, "application_answers", None) or {}
    certified = answers.get("currently_certified") == "yes"
    if not declared and certified and answers.get("no_lapse_attested") is not False:
        # A currently certified parcel is not asked the declaration; what accounts for its period is
        # the verification of no lapse its agent's form asks for (CCOF G(2), OTCO C2 2.4). Only an
        # attached one counts: a reference or the operator's own no-lapse answer is not evidence.
        if assessment is None:
            from certifications.services.certified_parcel_branch import assess_for_wizard

            assessment = assess_for_wizard(parcel)
        declared = _verification_of_no_lapse(parcel, assessment)
    if declared:
        own = f"the operation from {began.isoformat()}, {declared}"
    elif certified:
        # T21-F1: the declaration is not asked of a parcel stated currently certified, so its absence
        # is not "the operator has made no declaration". The period is still not covered by one.
        own = (
            f"the operation's own period from {began.isoformat()} is not covered by a declaration "
            "(the declaration is not asked of a parcel stated currently certified)"
        )
    else:
        own = f"the operation's own period from {began.isoformat()} is not covered: the operator has made no declaration for it"
    if began <= window_start and declared:
        return Coverage(
            window_start,
            today,
            complete=True,
            text=(
                f"The operation has had control of this parcel for the full 36 months "
                f"(since {began.isoformat()}), {declared}; no prior-manager affidavit is required for this window."
            ),
        )

    intervals: List[Tuple[date, date]] = [(began, today)] if declared else []
    unplaced = 0
    for row in prior:
        if row.period_start:
            end = row.period_end or began
            # A period whose end precedes its start is a data error; count the start day only
            # rather than letting a reversed range corrupt the merge.
            intervals.append((row.period_start, max(end, row.period_start)))
        else:
            unplaced += 1
    # Inclusive day arithmetic: `cursor` is the last day accounted for, so a gap runs from the
    # day after it to the day before the next range begins.
    gaps: List[Tuple[date, date]] = []
    cursor = window_start - ONE_DAY
    for start, end in _merge(intervals):
        if end <= cursor:
            continue
        if start > cursor + ONE_DAY:
            gaps.append((cursor + ONE_DAY, min(start - ONE_DAY, today)))
        cursor = max(cursor, end)
        if cursor >= today:
            break
    if cursor < today:
        gaps.append((cursor + ONE_DAY, today))

    bits = [
        f"Window {window_start.isoformat()} to {today.isoformat()}: {own}"
        + (
            f"; {len(prior) - unplaced} prior-manager affidavit(s) with a stated period"
            if prior
            else "; no prior-manager affidavit on file"
        )
    ]
    if unplaced:
        bits.append(f"{unplaced} affidavit(s) carry no management period and cannot be placed in the window")
    if gaps:
        bits.append("[REVIEW] not accounted for: " + ", ".join(f"{a.isoformat()} to {b.isoformat()}" for a, b in gaps))
    else:
        bits.append("Every day of the window is accounted for")
    return Coverage(
        window_start, today, complete=not gaps, gaps=tuple(gaps), unplaced=unplaced, text=". ".join(bits) + "."
    )


def season_evidence_lines(parcel, today: Optional[date] = None) -> List[str]:
    """Seasons logged in Trazo on this parcel inside the window: supporting record, never coverage.

    Each with its exact span. A season with no end date says so, and one that only partly overlaps
    the window prints the dates it actually spans; none of them closes a gap in `coverage`.
    """
    from product.services.input_evidence import season_spans

    today = today or date.today()
    window_start = _months_back(today, WINDOW_MONTHS)
    lines = []
    for span in season_spans(parcel):
        if span.start and span.start > today:
            continue
        if span.end and span.end < window_start:
            continue
        start = span.start.isoformat() if span.start else "start not recorded"
        end = span.end.isoformat() if span.end else "in progress"
        inputs = (
            f"{span.inputs} dated input record{'' if span.inputs == 1 else 's'}"
            if span.inputs
            else "no input recorded in Trazo (not a statement that none was applied)"
        )
        lines.append(f"{span.name}: {start} to {end}, {inputs}")
    return lines


# ---------------------------------------------------------------------------
# Materials by name and date, for the typed land-history years
# ---------------------------------------------------------------------------


def structured_substances(row) -> List[Tuple[str, str, str]]:
    """(material, manufacturer, application_dates) for a recorded `LandHistoryRow`, else []."""
    recorded = getattr(row, "recorded", None)
    entries = getattr(recorded, "substance_applications", None) or []
    out: List[Tuple[str, str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        material = str(entry.get("material") or "").strip()
        if not material:
            continue
        out.append(
            (material, str(entry.get("manufacturer") or "").strip(), str(entry.get("application_dates") or "").strip())
        )
    return out


def fmt_period_edge(day: Optional[date], *, present_when_none: bool = False) -> str:
    """YYYY-MM, or "present" / "not recorded" when there is no date.

    CCOF's table heads the column "MM/YY", but every other date on the parcel page is ISO
    (2026-08-07), and a "07/26" printed beside them reads as July 26th as easily as July 2026
    — verified on a rendered page, not guessed. Year-month keeps the month granularity the form
    asks for and cannot be misread; a reviewer at any of the three agents reads it unaided.
    """
    if day is None:
        return "present" if present_when_none else "not recorded"
    return f"{day.year:04d}-{day.month:02d}"


# ---------------------------------------------------------------------------
# The same facts for the wizard — so the operator sees what the packet will print
# ---------------------------------------------------------------------------


def _iso(day: Optional[date]) -> Optional[str]:
    return day.isoformat() if day else None


def _row_json(row: ManagerRow) -> dict:
    return {
        "name": row.name,
        "role": row.role,
        "period_start": _iso(row.period_start),
        "period_end": _iso(row.period_end),
        "last_prohibited": _iso(row.last_prohibited),
        "declared": row.declared,
        "signed": _iso(row.signed),
        "attached": bool(row.attachment),
        "contradiction": row.contradiction,
    }


def land_history_summary(parcel, answers: Optional[dict] = None) -> dict:
    """JSON-able mirror of what the parcel page prints: certificate, managers, 36-month accounting.

    Served on the Parcel Application GET so the wizard's certificate card and manager card show
    the operator the exact facts the certifier will read, before the PDF is generated. One source
    (`certificate_line`, `current_manager_row`, `prior_manager_rows`, `coverage`) for both surfaces.
    """
    from certifications.services import certified_parcel_branch as cpb

    answers = answers if answers is not None else (parcel.application_answers or {})
    line = certificate_line(parcel.establishment)
    prior = prior_manager_rows(parcel)
    certified = cpb.assess_for_wizard(parcel)
    account = coverage(parcel, prior, assessment=certified)
    coverage_not_asked = certified is not None and certified.land_history_asked is False
    return {
        # T21-F1: the same assessment the parcel PDF prints, so the wizard and the page agree.
        "certified_branch": cpb.to_json(certified),
        "certificate": (
            {
                "number": line.number,
                "agent": line.agent,
                "effective": _iso(line.effective),
                "expiry": _iso(line.expiry),
                "document_url": line.document_url,
            }
            if line.on_file
            else None
        ),
        "current_manager": _row_json(current_manager_row(parcel, answers)),
        "prior_managers": [_row_json(r) for r in prior],
        # T21-F1: on a route that does not ask for the accounting, the wizard gets what the PDF prints
        # in its place, never the gap list (review of back #86).
        "coverage": {
            "window_start": account.window_start.isoformat(),
            "window_end": account.window_end.isoformat(),
            "complete": None if coverage_not_asked else account.complete,
            "gaps": [] if coverage_not_asked else [[a.isoformat(), b.isoformat()] for a, b in account.gaps],
            "unplaced": account.unplaced,
            "text": cpb.COVERAGE_NOT_ASKED_TEXT if coverage_not_asked else account.text,
            "not_asked": coverage_not_asked,
        },
    }


# ---------------------------------------------------------------------------
# What each signer stated (CCOF ORGB49 Affidavit A-D; WSDA AGR 2262 refs 1-8 and the attestation)
# ---------------------------------------------------------------------------

#: CCOF ORGB49 Affidavit D's "Type" column, in the words its own heading lists.
AFFIDAVIT_MATERIAL_TYPES = {
    "fertilizer": "Fertilizer",
    "pest_disease_control": "Pest or disease control",
    "herbicide": "Herbicide",
    "compost_manure": "Compost or manure",
    "seed_treatment": "Seed treatment",
    "adjuvant": "Adjuvant",
    "other": "Other",
}

#: The signer's materials table as the parcel page prints it (CCOF Affidavit D; WSDA AGR 2262 refs 7 and 8).
AFFIDAVIT_ROW_COLUMNS = ("Year", "Use", "Months", "Acres", "Material", "Manufacturer", "Applied", "Type")


def _month(value) -> str:
    text = str(value or "").strip()
    return f"{text[5:7]}/{text[:4]}" if len(text) == 7 and text[4] == "-" else text


def affidavit_row_cells(affidavit) -> list:
    """One list of cell texts per typed row of the signer's table, "" where the signer left it blank."""
    from product.services.land_history import format_acres

    out = []
    for row in affidavit.yearly_history or []:
        if not isinstance(row, dict):
            continue
        start, end = _month(row.get("period_from")), _month(row.get("period_to"))
        months = f"{start} to {end}" if start and end and start != end else (start or end)
        try:
            acres = format_acres(row["acres"]) if row.get("acres") not in (None, "") else ""
        except Exception:  # noqa: BLE001 — a malformed stored value prints as typed, never sinks the page
            acres = str(row.get("acres"))
        out.append(
            [
                str(row.get("year") or ""),
                str(row.get("land_use") or ""),
                months,
                acres,
                str(row.get("inputs") or ""),
                str(row.get("manufacturer") or ""),
                str(row.get("date_applied") or ""),
                AFFIDAVIT_MATERIAL_TYPES.get(row.get("material_type") or "", ""),
            ]
        )
    return out


def affidavit_signer_lines(affidavit) -> list[str]:
    """What the signer stated beside the table: why they know the parcel, who they are, the site as they name
    it, their last inspection, what stays with them, and treated seed in their period. A blank says nothing;
    only a stated Yes to treated seed is a review line."""
    from product.services.land_history import format_acres

    lines = []
    basis = dict(affidavit.SIGNER_BASIS_CHOICES).get(affidavit.signer_basis)
    if affidavit.signer_basis == "other":
        lines.append(f"Knows the parcel's history through: {affidavit.signer_basis_other or 'other (not described)'}.")
    elif basis:
        lines.append(f"Knows the parcel's history because they {basis[0].lower() + basis[1:]}.")
    name = (affidavit.previous_manager_name or "").strip()
    who = [x for x in (affidavit.signer_title, affidavit.signer_company) if x]
    contact = [x for x in (affidavit.signer_email, affidavit.previous_manager_phone) if x]
    if name and (who or contact):
        # The name leads only when something else was stated: a name alone is the row's own label.
        lines.append("Signer: " + "; ".join([", ".join([name, *who])] + contact).rstrip(".") + ".")
    else:
        # Contact details never stand in for a name: with none stored they are labelled as contact.
        if who:
            lines.append("Signer: " + ", ".join(who).rstrip(".") + ".")
        if contact:
            lines.append("Signer's contact: " + "; ".join(contact).rstrip(".") + ".")
    if affidavit.field_name:
        lines.append(f"Site as the signer names it: {affidavit.field_name}.")
    if affidavit.field_acres:
        lines.append(f"Site acreage stated by the signer: {format_acres(affidavit.field_acres)} acres.")
    if affidavit.last_inspection_date:
        lines.append(f"Signer's last organic inspection of the site: {affidavit.last_inspection_date.isoformat()}.")
    if affidavit.portion_remains == "yes":
        acres = (
            f"{format_acres(affidavit.acres_remaining)} acres"
            if affidavit.acres_remaining is not None
            else "acreage not stated"
        )
        lines.append(f"A portion of the site remains on the signer's certificate: {acres}.")
    elif affidavit.portion_remains == "no":
        lines.append("The whole site leaves the signer's certificate.")
    if affidavit.treated_seed_planted == "yes":
        lines.append(
            "[REVIEW] Treated seed was planted during the signer's management: "
            + (affidavit.treated_seed_detail or "no treatment brand or planting date given")
            + "."
        )
    elif affidavit.treated_seed_planted == "no":
        lines.append("No treated seed was planted during the signer's management (stated).")
    return lines
