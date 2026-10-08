"""What a parcel stated as currently certified needs, branch by branch, and what is on file for it.

WHY THIS MODULE EXISTS
----------------------
OSP alignment audit 2026-10, T21-F1, found by the Calapooia specimen (Phase 3 S6). A parcel the
operation stated was currently certified printed "the operation's own period ... is not covered:
the operator has made no declaration for it", while the same page said that declaration is not
asked of a certified parcel. The 36-month accounting demanded a statement the form skips.

The fix is not to treat "currently certified" as the missing declaration. Each certifying agent's
own form routes a certified parcel somewhere specific, and the parcel page now follows that route
and reports what the route asks for:

* CCOF Parcel Application (NOPB49) F2 "Yes, skip to section G": G asks for (1) a copy of the
  current certificate listing this parcel and (2) verification of no lapse in organic management
  (written confirmation from the current certifier, an Affidavit of Land History covering the
  period, and the like). F4 to F8, the declaration among them, are not asked.
* WSDA: a Site Application (AGR 2264) is filed for an initial application, new sites or added
  acreage, or a transfer of a certified site. An existing certified site of this operation renews on
  the Organic Site Update (AGR 2516); for a transfer, 2264 item 6a asks for a copy of the previous
  grower's certificate and a Previous Land Use Declaration (AGR 2262) signed by the previous manager.
* OTCO C2 is filed with a new application or to add acreage and is not updated; currently certified
  acreage is updated on FACT-04. For a parcel coming from another operation C2 still asks for the
  land history (2.4) and signed affirmations from every party that managed it (2.5), and between two
  OTCO-certified operations OTCO's Land Transfer Form applies instead.
* Any other agent: its own form decides. Trazo reports what is on file and claims no requirement,
  and no exemption either: the 36-month accounting prints in full.

WHICH ROUTE: "CURRENTLY CERTIFIED" IS NOT "ALREADY ON THIS AGENT'S CERTIFICATE" (run 3, R3-04/05/06)
----------------------------------------------------------------------------------------------
A parcel is existing acreage under the selected agent only when the operator reports both that the
certificate is this operation's (the operation name blank, or one of its names) and that the agent
named for it IS the selected agent (`certifying_agents.agent_for_name`, exact, never fuzzy). Another
known agent makes the parcel new to the selected one. No agent named, or a name Trazo does not
recognise, leaves the route UNRESOLVED: nothing is treated as not asked, and a review item says why.
Every packet renderer assesses through `assess_for_plan` with the packet's own plan, so the summary,
the detail, the land-history accounting, the attachments and page 04 cannot disagree.

THE RULES THIS MODULE KEEPS
---------------------------
* Availability, never acceptance. "Attached" means a file is in Trazo (and, in a packet, in the
  ZIP); whether it lists this parcel or satisfies the agent is the agent's determination. Nothing
  here says "verified", "36 months" accounted or "eligible".
* An unsupported checkbox is a statement, not evidence. `no_lapse_attested` prints as what the
  operator said; it never fills the continuity item. The operation's certificate of record is
  context; it is not a copy of a certificate that identifies this parcel.
* Conflicting records stay visible as review items: a dated input recorded as not organic-approved,
  or a land-history year marked conventional, inside a period stated as certified.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

logger = logging.getLogger(__name__)

#: `GeneratedDocument.linked_section` for the two per-parcel uploads this branch asks for.
CERTIFICATE_SECTION = "parcel_application_certificate"
CONTINUITY_SECTION = "parcel_application_continuity"

# Branches
EXISTING_SITE = "existing_site"
FROM_OTHER_OPERATION = "from_other_operation"

# Item states. The UI maps each to a message; the PDF to a sentence. Both read this list.
REPORTED = "reported"
ATTACHED = "attached"
NOT_IN_PACKET = "not_in_packet"  # a file is in Trazo but the packet could not carry it
REFERENCED = "referenced"
MISSING = "missing"
NOT_ASKED = "not_asked"
STATED_YES = "stated_yes"
STATED_NO = "stated_no"
UNANSWERED = "unanswered"

STATES = (REPORTED, ATTACHED, NOT_IN_PACKET, REFERENCED, MISSING, NOT_ASKED, STATED_YES, STATED_NO, UNANSWERED)

# Item keys
CERTIFICATION = "certification"
CERTIFICATE = "certificate"
CONTINUITY = "continuity"
NO_LAPSE_STATEMENT = "no_lapse_statement"
DECLARATION = "declaration"
PRIOR_MANAGER = "prior_manager"

#: Spelled out (not the names above) because the frontend reads this tuple to check every item has words.
ITEMS = ("certification", "certificate", "continuity", "no_lapse_statement", "declaration", "prior_manager")
assert ITEMS == (CERTIFICATION, CERTIFICATE, CONTINUITY, NO_LAPSE_STATEMENT, DECLARATION, PRIOR_MANAGER)

#: Route codes, one per agent branch. The UI names each in the operator's language.
ROUTES = (
    "ccof_g",
    "ccof_crop_update",
    "wsda_existing_site",
    "wsda_transfer",
    "wsda_new_site",
    "otco_existing_site",
    "otco_transfer",
    "otco_new_acreage",
    "unresolved",
    "agent_form",
)

#: Agents whose parcel forms Trazo reads. Any other agent gets `agent_form`.
ROUTED_AGENTS = ("ccof", "wsda", "otco")

ROUTE_TEXT = {
    "ccof_g": (
        "CCOF Parcel Application (NOPB49) F2: a currently certified parcel skips to section G, which asks "
        "for (1) a copy of the current organic certificate listing this parcel and (2) verification of no "
        "lapse in organic management. F3 to F8, including the date of last prohibited material, are not asked."
    ),
    "ccof_crop_update": (
        "CCOF: the parcel is reported as already on this operation's CCOF certification. The Parcel "
        "Application (NOPB49) is for a new parcel; crops on a parcel already on file change on the Crop "
        "Update (NOPB88). NOPB49's land-history sections are not asked of this parcel."
    ),
    "wsda_existing_site": (
        "WSDA: a Site Application (AGR 2264) is filed for an initial application, a new site or added acreage, "
        "or a transfer of a certified site. An existing certified site of this operation is updated on the "
        "Organic Site Update (AGR 2516), so 2264's land-history items are not asked of it."
    ),
    "wsda_transfer": (
        "WSDA AGR 2264 item 6a, transfer of a certified site: a copy of the previous grower's certificate and a "
        "Previous Land Use Declaration (AGR 2262) completed and signed by the previous manager."
    ),
    "wsda_new_site": (
        "WSDA: the parcel is reported as certified by another agent, so for WSDA it is a new site and a "
        "Site Application (AGR 2264) is filed for it, land-history items included. Whether another agent's "
        "certificate satisfies any of them is WSDA's determination."
    ),
    "otco_existing_site": (
        "OTCO C2 is filed with a new application or to add acreage and is not updated; currently certified "
        "acreage is updated on FACT-04. C2's land-history items are not asked again for this parcel."
    ),
    "otco_transfer": (
        "OTCO C2 2.1-7a/7b: the parcel comes from another certified operation. C2 still asks for the land "
        "history (2.4) and signed affirmations from every party that managed the parcel in the past 36 months "
        "(2.5). Between two OTCO-certified operations, with the field inspected in the last 12 months, OTCO's "
        "Land Transfer Form applies instead."
    ),
    "otco_new_acreage": (
        "OTCO: the parcel is reported as certified by another agent, so for OTCO it is added acreage and C2 "
        "is filed for it. C2 2.4 accepts a current certificate with evidence of continuous organic management "
        "in place of the land-history table; 2.5 asks for the affirmations it names."
    ),
    "unresolved": (
        "Trazo cannot tell which of this agent's routes applies. The parcel is stated currently certified, "
        "but the certifying agent named for it is not one Trazo recognises, or none is named, so whether it "
        "is already on this operation's certification with this agent is not determined. Nothing is treated "
        "as not asked: the land-history accounting is shown in full."
    ),
    "agent_form": (
        "Trazo does not assess this certifying agent's land-history requirements, and no agent-specific "
        "exemption is determined. The 36-month accounting is shown in full; the items below are what is on "
        "file in Trazo."
    ),
}


@dataclass(frozen=True)
class Item:
    key: str
    state: str
    #: The sentence the PDF prints. The UI builds its own from key, state and the fields below.
    text: str
    path: str = ""
    reference: str = ""
    #: True when this route's form asks for it. Shown items that are not asked are context only.
    asked: bool = True
    #: True when the route's form accepts this item in place of another answer (OTCO C2 2.4). Shown,
    #: never counted as outstanding.
    alternative: bool = False

    def _replace_alternative(self, alternative: bool) -> "Item":
        from dataclasses import replace

        return replace(self, alternative=alternative) if alternative else self


#: Review kinds. Each carries a short `detail` (the record named); the UI words it per kind.
REVIEW_KINDS = (
    "prohibited_input",
    "unknown_input",
    "conventional_year",
    "no_lapse_answered_no",
    "operation_name_not_on_file",
    "certifier_not_recognised",
)

#: Printed where the 36-month accounting would be, on a route that does not ask for it. The wizard
#: payload carries the same sentence so the two surfaces say the same thing (review of back #86).
COVERAGE_NOT_ASKED_TEXT = (
    "The parcel is stated currently certified. On this route the certifying agent's form does not ask "
    "for the 36-month accounting; what it asks for is listed with the certification answers."
)


@dataclass(frozen=True)
class ReviewItem:
    kind: str
    detail: str
    text: str


@dataclass
class Assessment:
    agent: Optional[str]
    branch: str
    route: str
    items: List[Item] = field(default_factory=list)
    review: List[ReviewItem] = field(default_factory=list)
    #: Whether this route asks for the 36-month accounting: True, False (not asked on this route), or
    #: None (not determined: an unresolved route, or an agent Trazo does not assess). Only False replaces
    #: the accounting with `COVERAGE_NOT_ASKED_TEXT`.
    land_history_asked: Optional[bool] = None
    #: The plan whose agent this was assessed for, so a reader knows which route it shows.
    plan_version: Optional[int] = None

    @property
    def missing(self) -> List[str]:
        return [i.key for i in self.items if i.asked and i.state == MISSING]


def is_certified(parcel) -> bool:
    return (getattr(parcel, "application_answers", None) or {}).get("currently_certified") == "yes"


def _normalise(name: str) -> str:
    """Formatting only: case, spacing, punctuation and "&". Never legal suffixes or other words.

    "Branch Farms, L.L.C." matches "Branch Farms LLC"; "Valley Orchards Inc" does NOT match
    "Valley Orchards LLC" (two companies). Anything this does not match is treated as another
    operation and named as a review item, never guessed (review of back #86).
    """
    value = (name or "").lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", value)


def _own_names(establishment) -> set:
    names = {getattr(establishment, "name", ""), getattr(getattr(establishment, "company", None), "name", "")}
    try:
        from certifications.models import Certification

        names.update(
            Certification.objects.filter(establishment_id=establishment.pk).values_list(
                "usda_operation_name", flat=True
            )
        )
    except Exception:  # noqa: BLE001 — the branch must still render without this lookup
        logger.exception("Operation names could not be read for establishment %s", getattr(establishment, "pk", None))
    return {_normalise(n) for n in names if n and _normalise(n)}


def branch_for(parcel) -> str:
    """The question asks for the operation name "if not this operation": blank means this one."""
    stated = ((parcel.application_answers or {}).get("certified_operation_name") or "").strip()
    if not stated or _normalise(stated) in _own_names(parcel.establishment):
        return EXISTING_SITE
    return FROM_OTHER_OPERATION


def stated_agent(parcel) -> Optional[str]:
    """The registered agent slug the operator named as certifying this parcel, or None (none named, or a
    name Trazo does not recognise). Exact after normalisation, never fuzzy."""
    name = ((parcel.application_answers or {}).get("prior_certifier_name") or "").strip()
    if not name:
        return None
    from certifications.certifying_agents import agent_for_name

    agent = agent_for_name(name)
    return agent.slug if agent else None


def route_for(parcel, agent: Optional[str]) -> str:
    """The route the selected agent's own form takes for this certified parcel."""
    if agent not in ROUTED_AGENTS:
        return "agent_form"
    branch = branch_for(parcel)
    named = stated_agent(parcel)
    if agent == "ccof":
        # NOPB49 applies to any parcel new to the operation's CCOF file; a parcel from another operation
        # is new to this one whoever certified it.
        if branch == FROM_OTHER_OPERATION or (named is not None and named != "ccof"):
            return "ccof_g"
        return "ccof_crop_update" if named == "ccof" else "unresolved"
    if agent == "otco":
        # C2 2.1-7a/7b: a parcel from another certified operation, whichever agent certified it.
        if branch == FROM_OTHER_OPERATION:
            return "otco_transfer"
        if named is None:
            return "unresolved"
        return "otco_existing_site" if named == "otco" else "otco_new_acreage"
    # WSDA: 2264 6a's transfer is between WSDA-certified operations.
    if named is None:
        return "unresolved"
    if named != "wsda":
        return "wsda_new_site"
    return "wsda_existing_site" if branch == EXISTING_SITE else "wsda_transfer"


def plan_for_parcel(parcel):
    """The plan the operator is working on: the newest one not withdrawn. Outside a packet there is no
    plan in hand, so the wizard assesses for this one and says so (`plan_version`)."""
    try:
        from certifications.models import OrganicSystemPlan

        return (
            OrganicSystemPlan.objects.filter(establishment_id=parcel.establishment_id)
            .exclude(status="withdrawn")
            .order_by("-version_number")
            .first()
        )
    except Exception:  # noqa: BLE001
        logger.exception("Plan could not be resolved for parcel %s", getattr(parcel, "pk", None))
        return None


def agent_for_plan(osp) -> Optional[str]:
    """The registered agent slug a plan's packet speaks for, or None. The ONE resolver both the packet
    and the wizard use, so they can only differ by the plan they are about."""
    if osp is None:
        return None
    try:
        from certifications.services.packet_coverage import packet_certifier

        slug, own = packet_certifier(osp)
        return slug if own else None
    except Exception:  # noqa: BLE001
        logger.exception("Agent could not be resolved for plan %s", getattr(osp, "pk", None))
        return None


def agent_for_parcel(parcel) -> Optional[str]:
    return agent_for_plan(plan_for_parcel(parcel))


def assess_for_plan(parcel, osp, today: Optional[date] = None) -> Optional["Assessment"]:
    """THE assessment for a packet: the packet's plan, its agent and its version. Every packet renderer
    calls this, never `assess_for_wizard`, which reads the newest plan in the database and so answered
    for a different plan than the one being exported (run 3, R3-05)."""
    return assess(parcel, agent_for_plan(osp), today=today, plan_version=getattr(osp, "version_number", None))


def assess_for_wizard(parcel) -> Optional["Assessment"]:
    """The assessment outside a packet: for the plan the operator is working on, naming its version."""
    osp = plan_for_parcel(parcel)
    return assess(parcel, agent_for_plan(osp), plan_version=getattr(osp, "version_number", None))


def _documents(parcel, section):
    try:
        return list(parcel.documents.filter(linked_section=section).order_by("-created_at"))
    except Exception:  # noqa: BLE001 — a document lookup must never take the page down
        logger.exception("Documents could not be read for parcel %s", getattr(parcel, "pk", None))
        return []


def document_path(doc, folder: str) -> str:
    name = doc.file.name if doc.file else ""
    ext = ("." + name.rsplit(".", 1)[-1]) if "." in name else ""
    return f"parcels/{folder}/{doc.pk}-{(doc.title or folder).replace('/', '-')[:60]}{ext}"


def _manifest_state(source_id: str, path: str):
    """(state, path, detail) for any file the packet may carry, keyed as the manifest keys it."""
    try:
        from certifications.services.packet_attachments import ATTACHED as MANIFEST_ATTACHED
        from certifications.services.packet_attachments import current_manifest

        manifest = current_manifest()
    except Exception:  # noqa: BLE001
        manifest = None
    if manifest is not None:
        entry = next((e for e in manifest.entries if e.source_id == source_id), None)
        if entry is not None and entry.state != MANIFEST_ATTACHED:
            return NOT_IN_PACKET, entry.zip_path, entry.detail
        if entry is not None:
            return ATTACHED, entry.zip_path, ""
    return ATTACHED, path, ""


def _file_state(doc, folder: str):
    """(state, path, detail). In a packet build the manifest decides; elsewhere the file's presence."""
    return _manifest_state(f"doc:{doc.pk}", document_path(doc, folder))


def _upload_item(parcel, key, section, folder, reference_key, what, asked) -> Item:
    answers = parcel.application_answers or {}
    docs = _documents(parcel, section)
    if docs:
        state, path, detail = _file_state(docs[0], folder)
        if state == ATTACHED:
            return Item(key, ATTACHED, f"{what}: attached at {path}.", path=path, asked=asked)
        return Item(key, NOT_IN_PACKET, f"{what}: uploaded to Trazo but not in this packet ({detail}).", asked=asked)
    reference = (answers.get(reference_key) or "").strip()
    if reference:
        return Item(
            key,
            REFERENCED,
            f"{what}: referenced separately by the operator: {reference}",
            reference=reference,
            asked=asked,
        )
    return Item(key, MISSING, f"{what}: none attached or referenced.", asked=asked)


def _continuity_item(parcel, asked: bool, today: Optional[date] = None) -> Item:
    what = "Verification of no lapse in organic management"
    item = _upload_item(parcel, CONTINUITY, CONTINUITY_SECTION, "continuity", "continuity_reference", what, asked)
    if item.state != MISSING:
        return item
    # CCOF G(2) names "a completed Affidavit of Land History covering the period". Only a signed one
    # whose stated period covers the whole 36-month window counts (review of back #86); one that does
    # not is named, and the item stays missing.
    from certifications.services.parcel_land_history import WINDOW_MONTHS, _months_back, affidavit_attachment_name

    today = today or date.today()
    window_start = _months_back(today, WINDOW_MONTHS)
    short = []
    for aff in parcel.landowner_affidavits.all():
        name = affidavit_attachment_name(aff)
        if not name:
            continue
        start, end = aff.management_period_start, aff.management_period_end
        period = " to ".join(d.isoformat() if d else "not stated" for d in (start, end))
        if not (start and start <= window_start and (end is None or end >= today)):
            short.append(period)
            continue
        state, path, detail = _manifest_state(f"affidavit:{aff.pk}", f"parcels/affidavits/{name}")
        if state != ATTACHED:
            return Item(
                CONTINUITY,
                NOT_IN_PACKET,
                f"{what}: a signed Affidavit of Land History is in Trazo but not in this packet ({detail}).",
                asked=asked,
            )
        return Item(
            CONTINUITY,
            ATTACHED,
            f"{what}: a signed Affidavit of Land History is attached at {path} (period as the signer stated it: "
            f"{period}).",
            path=path,
            asked=asked,
        )
    if short:
        return Item(
            CONTINUITY,
            MISSING,
            f"{what}: none attached or referenced. Signed affidavit(s) on file state a period that does not cover "
            f"{window_start.isoformat()} to {today.isoformat()}: " + "; ".join(short) + ".",
            asked=asked,
        )
    return item


def _no_lapse_item(parcel) -> Item:
    value = (parcel.application_answers or {}).get("no_lapse_attested")
    if value is True:
        return Item(
            NO_LAPSE_STATEMENT,
            STATED_YES,
            "The operator states there has been no lapse in organic management. This is the operator's "
            "statement; it is not the verification listed above.",
            asked=False,
        )
    if value is False:
        return Item(
            NO_LAPSE_STATEMENT,
            STATED_NO,
            "The operator answered No to the statement that there has been no lapse in organic management.",
            asked=False,
        )
    return Item(NO_LAPSE_STATEMENT, UNANSWERED, "The operator has not answered the no-lapse statement.", asked=False)


def _certification_item(parcel, branch) -> Item:
    answers = parcel.application_answers or {}
    certifier = (answers.get("prior_certifier_name") or "").strip()
    operation = (answers.get("certified_operation_name") or "").strip()
    site = (answers.get("prior_certificate_site_number") or "").strip()
    bits = ["The operator reports this parcel as currently certified organic"]
    bits.append(f"by {certifier}" if certifier else "(certifying agent not named)")
    if branch == FROM_OTHER_OPERATION:
        bits.append(f"under another operation, {operation}")
    else:
        bits.append("on this operation's certificate")
    if site:
        bits.append(f"site or parcel number {site}")
    return Item(CERTIFICATION, REPORTED, ", ".join(bits) + ".", reference=certifier, asked=True)


def _prior_manager_item(parcel, document_name: str) -> Item:
    """Every prior party signs (OTCO 2.5 "each", AGR 2262 per previous manager): one signed row out of
    three is not the item (review of back #86)."""
    from certifications.services.parcel_land_history import affidavit_attachment_name

    rows = list(parcel.landowner_affidavits.all())
    if not rows:
        return Item(PRIOR_MANAGER, MISSING, f"{document_name}: none on file.")
    unsigned = [a.previous_manager_name or "unnamed" for a in rows if not affidavit_attachment_name(a)]
    if unsigned:
        return Item(
            PRIOR_MANAGER,
            MISSING,
            f"{document_name}: {len(rows) - len(unsigned)} of {len(rows)} signed; no signed document from "
            + ", ".join(unsigned)
            + ".",
        )
    paths = []
    for aff in rows:
        state, path, detail = _manifest_state(
            f"affidavit:{aff.pk}", f"parcels/affidavits/{affidavit_attachment_name(aff)}"
        )
        if state != ATTACHED:
            return Item(
                PRIOR_MANAGER,
                NOT_IN_PACKET,
                f"{document_name}: {aff.previous_manager_name or 'a signer'}'s signed document is in Trazo but not "
                f"in this packet ({detail}).",
            )
        paths.append(path)
    return Item(
        PRIOR_MANAGER,
        ATTACHED,
        f"{document_name}: all {len(rows)} signed, attached at " + ", ".join(paths) + ".",
        path=paths[0],
    )


def _declaration_item(route, land_history_asked: Optional[bool]) -> Item:
    if land_history_asked is False:
        text = "The date-of-last-prohibited-material declaration is not asked on this branch."
    elif land_history_asked is True:
        text = (
            "Trazo does not ask the date-of-last-prohibited-material declaration of a parcel stated currently "
            "certified. On this route the agent's form asks for the land history, so the accounting below shows "
            "what covers each period."
        )
    else:
        text = (
            "Trazo does not ask the date-of-last-prohibited-material declaration of a parcel stated currently "
            "certified. Whether the certifying agent asks it of this parcel is not determined."
        )
    return Item(DECLARATION, NOT_ASKED, text, asked=False)


def _review(parcel, today: Optional[date], route: str = "") -> List[ReviewItem]:
    """Records that conflict with a period stated as certified. Shown, never reconciled."""
    from certifications.services.parcel_land_history import WINDOW_MONTHS, _months_back
    from product.services.input_evidence import NOT_CONFIRMED, PROHIBITED, UNKNOWN, describe, parcel_inputs

    today = today or date.today()
    start = _months_back(today, WINDOW_MONTHS)
    out = []
    try:
        for record in parcel_inputs(parcel):
            if record.day < start or record.day > today:
                continue
            if record.status == PROHIBITED:
                out.append(
                    ReviewItem(
                        "prohibited_input",
                        describe(record),
                        f"[REVIEW] {describe(record)}, inside a period stated as certified. Both are shown; "
                        "the records are not reconciled here.",
                    )
                )
            elif record.status == NOT_CONFIRMED:
                out.append(
                    ReviewItem(
                        "unconfirmed_input",
                        describe(record),
                        f"[REVIEW] {describe(record)}. Confirm the basis with the certifying agent.",
                    )
                )
            elif record.status == UNKNOWN:
                out.append(
                    ReviewItem(
                        "unknown_input",
                        describe(record),
                        f"[REVIEW] {describe(record)}. Its organic status is not recorded.",
                    )
                )
        for row in parcel.crop_history.all():
            method = (getattr(row, "production_method", "") or "").lower()
            if method == "conventional" and row.year >= start.year:
                out.append(
                    ReviewItem(
                        "conventional_year",
                        str(row.year),
                        f"[REVIEW] The land history for {row.year} records conventional production on this parcel, "
                        "inside a period stated as certified.",
                    )
                )
    except Exception:  # noqa: BLE001 — a review lookup must never take the page down
        logger.exception("Certified-branch review items could not be read for parcel %s", getattr(parcel, "pk", None))
    named = ((parcel.application_answers or {}).get("prior_certifier_name") or "").strip()
    if route == "unresolved":
        out.append(
            ReviewItem(
                "certifier_not_recognised",
                named,
                (
                    f"[REVIEW] The certifying agent named for this parcel, {named}, is not one Trazo recognises, "
                    if named
                    else "[REVIEW] No certifying agent is named for this parcel, "
                )
                + "so whether it is already on this operation's certification with this packet's agent is not "
                "determined.",
            )
        )
    stated = ((parcel.application_answers or {}).get("certified_operation_name") or "").strip()
    if stated and branch_for(parcel) == FROM_OTHER_OPERATION:
        out.append(
            ReviewItem(
                "operation_name_not_on_file",
                stated,
                f"[REVIEW] The operation named on that certificate, {stated}, is not one of this operation's "
                "names on file, so the parcel is read as coming from another operation. If it is this "
                "operation's own certificate, leave that answer blank.",
            )
        )
    if (parcel.application_answers or {}).get("no_lapse_attested") is False:
        out.append(
            ReviewItem(
                "no_lapse_answered_no",
                "",
                "[REVIEW] The parcel is stated currently certified and the no-lapse statement is answered No.",
            )
        )
    return out


def assess(
    parcel, agent: Optional[str] = None, today: Optional[date] = None, plan_version: Optional[int] = None
) -> Optional[Assessment]:
    """The certified branch for `parcel`, or None when the parcel is not stated currently certified."""
    if not is_certified(parcel):
        return None
    branch = branch_for(parcel)
    route = route_for(parcel, agent)

    def certificate(what, asked, alternative=False):
        return _upload_item(
            parcel, CERTIFICATE, CERTIFICATE_SECTION, "certificates", "certificate_reference", what, asked
        )._replace_alternative(alternative)

    items = [_certification_item(parcel, branch)]
    land_history_asked: Optional[bool] = None
    if route == "ccof_g":
        items.append(certificate("Copy of the current organic certificate listing this parcel", True))
        items.append(_continuity_item(parcel, asked=True, today=today))
        land_history_asked = False
    elif route in ("ccof_crop_update", "wsda_existing_site", "otco_existing_site"):
        items.append(certificate("Copy of the current organic certificate", False))
        land_history_asked = False
    elif route == "wsda_transfer":
        items.append(certificate("Copy of the previous grower's certificate", True))
        items.append(
            _prior_manager_item(parcel, "Previous Land Use Declaration (AGR 2262) signed by the previous manager")
        )
        land_history_asked = True
    elif route == "otco_transfer":
        items.append(_prior_manager_item(parcel, "Signed affirmation from each prior party (C2 2.5)"))
        land_history_asked = True
    elif route == "otco_new_acreage":
        items.append(certificate("Copy of the current organic certificate (accepted by C2 2.4)", False, True))
        items.append(_continuity_item(parcel, asked=False, today=today)._replace_alternative(True))
        land_history_asked = True
    elif route == "wsda_new_site":
        items.append(certificate("Copy of the current organic certificate", False))
        items.append(_continuity_item(parcel, asked=False, today=today))
        if branch == FROM_OTHER_OPERATION:
            # Land another operation managed: AGR 2262 is signed by the previous manager whatever agent
            # certified it (review of back #90).
            items.append(
                _prior_manager_item(parcel, "Previous Land Use Declaration (AGR 2262) signed by the previous manager")
            )
        land_history_asked = True
    else:  # unresolved, agent_form
        items.append(certificate("Copy of the current organic certificate", False))
        items.append(_continuity_item(parcel, asked=False, today=today))
    items.append(_no_lapse_item(parcel))
    items.append(_declaration_item(route, land_history_asked))
    return Assessment(
        agent=agent,
        branch=branch,
        route=route,
        items=items,
        review=_review(parcel, today, route),
        land_history_asked=land_history_asked,
        plan_version=plan_version,
    )


#: The parcel form each routed agent's register carries, by register `document_id`.
PARCEL_FORMS = {"ccof": "NOPB49", "wsda": "AGR 2264", "otco": "C2"}

#: (route, register document_id) -> (how, refs, reason). "not_filed": no row of the form is asked for
#: this parcel; "skipped": only `refs` are not asked. Reasons are printed on page 04 as written.
ROUTE_FORMS = {
    ("ccof_crop_update", "NOPB49"): (
        "not_filed",
        frozenset(),
        "NOPB49 is for a new parcel; a parcel already on the operation's CCOF file changes on the Crop Update "
        "(NOPB88)",
    ),
    ("ccof_g", "NOPB49"): (
        "skipped",
        frozenset({"F3", "F4", "F5", "F6", "F7", "F7a", "F8", "F8a"}),
        "F2 Yes: a currently certified parcel skips to section G",
    ),
    ("wsda_existing_site", "AGR 2264"): (
        "not_filed",
        frozenset(),
        "AGR 2264 is not filed for an existing certified site; it is updated on the Organic Site Update (AGR 2516)",
    ),
    ("wsda_existing_site", "AGR 2262"): (
        "not_filed",
        frozenset(),
        "AGR 2262 goes with a Site Application for a new site or a transfer, not with an existing certified site",
    ),
    ("otco_existing_site", "C2"): (
        "not_filed",
        frozenset(),
        "C2 is not refiled for currently certified acreage; that acreage is updated on FACT-04",
    ),
}

APPLIES = "applies"
NOT_ON_ROUTE = "not_on_route"
ROUTE_UNRESOLVED = "route_unresolved"

# Recordkeeping review S9 (F-15): this read "the route is not determined (certifying agent not
# recognised, or none named)" and was printed once per question per parcel (42-54 times on the
# specimen), as if about the addressed agent. It names the answer that decides the route.
UNRESOLVED_REASON = (
    "the route is not determined: the parcel's prior certifying agent is not named, or not recognised, "
    "on its Parcel Application (section F)"
)


def form_on_route(assessment: Optional[Assessment], document_id: str, ref: str) -> tuple:
    """(APPLIES | NOT_ON_ROUTE | ROUTE_UNRESOLVED, reason) for one register row of one parcel's form.

    Page 04 calls this per parcel with the same assessment the parcel pages print, so a row the route
    skips is never listed as still open, and an undetermined route is never listed as skipped.
    """
    if assessment is None:
        return APPLIES, ""
    if assessment.route == "unresolved" and document_id == PARCEL_FORMS.get(assessment.agent or ""):
        return ROUTE_UNRESOLVED, UNRESOLVED_REASON
    rule = ROUTE_FORMS.get((assessment.route, document_id))
    if rule is None:
        return APPLIES, ""
    how, refs, reason = rule
    if how == "not_filed" or ref in refs:
        return NOT_ON_ROUTE, reason
    return APPLIES, ""


def lines(assessment: Assessment) -> List[str]:
    """What the parcel page prints, in order."""
    out = [ROUTE_TEXT[assessment.route]]
    for item in assessment.items:
        if item.asked or item.state in (REPORTED, NOT_ASKED, STATED_YES, STATED_NO, UNANSWERED):
            prefix = ""
        elif item.alternative:
            prefix = "(Accepted by the form in place of the land-history table; shown, not counted as outstanding.) "
        elif assessment.land_history_asked is None:
            # Unresolved or an agent Trazo does not assess: whether the item is asked is not known, so
            # it is never "not asked" (run 4, R4-01).
            prefix = "(Whether this is asked is not determined on this route; shown for reference.) "
        else:
            prefix = "(Not asked on this branch; shown for reference.) "
        out.append(prefix + item.text)
    out.append(
        "These lines report what is on file in Trazo. Whether a document satisfies the certifying agent "
        "is the agent's determination."
    )
    out.extend(r.text for r in assessment.review)
    return out


#: Printed in the parcel summary when the route, and so the evidence it asks for, is not determined.
ROUTE_UNDETERMINED_SUMMARY = {
    "unresolved": "certified route unresolved, so the evidence this agent asks for is not determined",
    "agent_form": "this agent's own form sets the evidence it asks for; Trazo does not assess it",
}


def to_json(assessment: Optional[Assessment]) -> Optional[dict]:
    if assessment is None:
        return None
    return {
        "agent": assessment.agent,
        "branch": assessment.branch,
        "route": assessment.route,
        "land_history_asked": assessment.land_history_asked,
        "plan_version": assessment.plan_version,
        "items": [
            {
                "key": i.key,
                "state": i.state,
                "asked": i.asked,
                "alternative": i.alternative,
                "path": i.path,
                "reference": i.reference,
            }
            for i in assessment.items
        ],
        "review": [{"kind": r.kind, "detail": r.detail} for r in assessment.review],
        "missing": assessment.missing,
    }
