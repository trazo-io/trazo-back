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
* Any other agent: its own form decides. Trazo reports what is on file and claims no requirement.

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
    "wsda_existing_site",
    "wsda_transfer",
    "otco_existing_site",
    "otco_transfer",
    "agent_form",
)

ROUTE_TEXT = {
    "ccof_g": (
        "CCOF Parcel Application (NOPB49) F2: a currently certified parcel skips to section G, which asks "
        "for (1) a copy of the current organic certificate listing this parcel and (2) verification of no "
        "lapse in organic management. F4 to F8, including the date of last prohibited material, are not asked."
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
    "agent_form": (
        "This packet does not carry the certifying agent's own parcel form. What that agent asks of a "
        "currently certified parcel is set by its form; the items below are what is on file in Trazo."
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


#: Review kinds. Each carries a short `detail` (the record named); the UI words it per kind.
REVIEW_KINDS = ("prohibited_input", "unknown_input", "conventional_year", "no_lapse_answered_no")


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
    #: Whether the 36-month accounting (`parcel_land_history.coverage`) is what this route asks for.
    land_history_asked: bool = False

    @property
    def missing(self) -> List[str]:
        return [i.key for i in self.items if i.asked and i.state == MISSING]


def is_certified(parcel) -> bool:
    return (getattr(parcel, "application_answers", None) or {}).get("currently_certified") == "yes"


def _normalise(name: str) -> str:
    value = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    words = [w for w in value.split() if w not in {"llc", "inc", "co", "corp", "ltd", "the", "company"}]
    return " ".join(words)


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


def agent_for_parcel(parcel) -> Optional[str]:
    """The agent slug the parcel's packet speaks for: the newest plan's agent, else the certificate's."""
    try:
        from certifications.models import OrganicSystemPlan
        from certifications.services.packet_coverage import packet_agent, registered_certifiers

        osp = (
            OrganicSystemPlan.objects.filter(establishment_id=parcel.establishment_id)
            .exclude(status="withdrawn")
            .order_by("-version_number")
            .first()
        )
        if osp is None:
            return None
        slug = packet_agent(osp).slug
        return slug if slug in registered_certifiers() else None
    except Exception:  # noqa: BLE001
        logger.exception("Agent could not be resolved for parcel %s", getattr(parcel, "pk", None))
        return None


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


def _file_state(doc, folder: str):
    """(state, path, detail). In a packet build the manifest decides; elsewhere the file's presence."""
    path = document_path(doc, folder)
    try:
        from certifications.services.packet_attachments import ATTACHED as MANIFEST_ATTACHED
        from certifications.services.packet_attachments import current_manifest

        manifest = current_manifest()
    except Exception:  # noqa: BLE001
        manifest = None
    if manifest is not None:
        entry = next((e for e in manifest.entries if e.source_id == f"doc:{doc.pk}"), None)
        if entry is not None and entry.state != MANIFEST_ATTACHED:
            return NOT_IN_PACKET, entry.zip_path, entry.detail
        if entry is not None:
            return ATTACHED, entry.zip_path, ""
    return ATTACHED, path, ""


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


def _continuity_item(parcel, asked: bool) -> Item:
    what = "Verification of no lapse in organic management"
    item = _upload_item(parcel, CONTINUITY, CONTINUITY_SECTION, "continuity", "continuity_reference", what, asked)
    if item.state != MISSING:
        return item
    # CCOF G(2) names "a completed Affidavit of Land History covering the period" as one form of it.
    from certifications.services.parcel_land_history import affidavit_attachment_name

    for aff in parcel.landowner_affidavits.all():
        name = affidavit_attachment_name(aff)
        if name:
            period = " to ".join(
                d.isoformat() if d else "not stated" for d in (aff.management_period_start, aff.management_period_end)
            )
            path = f"parcels/affidavits/{name}"
            return Item(
                CONTINUITY,
                ATTACHED,
                f"{what}: a signed Affidavit of Land History is attached at {path} (period as the signer "
                f"stated it: {period}).",
                path=path,
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
    rows = list(parcel.landowner_affidavits.all())
    signed = [a for a in rows if getattr(a, "signed_document", None)]
    from certifications.services.parcel_land_history import affidavit_attachment_name

    if signed:
        path = f"parcels/affidavits/{affidavit_attachment_name(signed[0])}"
        return Item(PRIOR_MANAGER, ATTACHED, f"{document_name}: signed document attached at {path}.", path=path)
    if rows:
        return Item(
            PRIOR_MANAGER,
            MISSING,
            f"{document_name}: {len(rows)} affidavit record(s) in Trazo, none with a signed document attached.",
        )
    return Item(PRIOR_MANAGER, MISSING, f"{document_name}: none on file.")


def _declaration_item(route) -> Item:
    if route == "agent_form":
        text = (
            "The date-of-last-prohibited-material declaration is not asked by Trazo of a parcel stated "
            "currently certified; whether the certifying agent asks it is set by its own form."
        )
    else:
        text = "The date-of-last-prohibited-material declaration is not asked on this branch."
    return Item(DECLARATION, NOT_ASKED, text, asked=False)


def _review(parcel, today: Optional[date]) -> List[ReviewItem]:
    """Records that conflict with a period stated as certified. Shown, never reconciled."""
    from certifications.services.parcel_land_history import WINDOW_MONTHS, _months_back
    from product.services.input_evidence import PROHIBITED, UNKNOWN, describe, parcel_inputs

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
    if (parcel.application_answers or {}).get("no_lapse_attested") is False:
        out.append(
            ReviewItem(
                "no_lapse_answered_no",
                "",
                "[REVIEW] The parcel is stated currently certified and the no-lapse statement is answered No.",
            )
        )
    return out


def assess(parcel, agent: Optional[str] = None, today: Optional[date] = None) -> Optional[Assessment]:
    """The certified branch for `parcel`, or None when the parcel is not stated currently certified."""
    if not is_certified(parcel):
        return None
    branch = branch_for(parcel)
    if agent == "ccof":
        route = "ccof_g"
    elif agent in ("wsda", "otco"):
        route = f"{agent}_{'existing_site' if branch == EXISTING_SITE else 'transfer'}"
    else:
        route = "agent_form"

    items = [_certification_item(parcel, branch)]
    land_history_asked = False
    if route == "ccof_g":
        items.append(
            _upload_item(
                parcel,
                CERTIFICATE,
                CERTIFICATE_SECTION,
                "certificates",
                "certificate_reference",
                "Copy of the current organic certificate listing this parcel",
                asked=True,
            )
        )
        items.append(_continuity_item(parcel, asked=True))
    elif route in ("wsda_existing_site", "otco_existing_site"):
        items.append(
            _upload_item(
                parcel,
                CERTIFICATE,
                CERTIFICATE_SECTION,
                "certificates",
                "certificate_reference",
                "Copy of the current organic certificate",
                asked=False,
            )
        )
    elif route == "wsda_transfer":
        items.append(
            _upload_item(
                parcel,
                CERTIFICATE,
                CERTIFICATE_SECTION,
                "certificates",
                "certificate_reference",
                "Copy of the previous grower's certificate",
                asked=True,
            )
        )
        items.append(
            _prior_manager_item(parcel, "Previous Land Use Declaration (AGR 2262) signed by the previous manager")
        )
        land_history_asked = True
    elif route == "otco_transfer":
        items.append(_prior_manager_item(parcel, "Signed affirmation from each prior party (C2 2.5)"))
        land_history_asked = True
    else:
        items.append(
            _upload_item(
                parcel,
                CERTIFICATE,
                CERTIFICATE_SECTION,
                "certificates",
                "certificate_reference",
                "Copy of the current organic certificate",
                asked=False,
            )
        )
        items.append(_continuity_item(parcel, asked=False))
    items.append(_no_lapse_item(parcel))
    items.append(_declaration_item(route))
    return Assessment(
        agent=agent,
        branch=branch,
        route=route,
        items=items,
        review=_review(parcel, today),
        land_history_asked=land_history_asked,
    )


def lines(assessment: Assessment) -> List[str]:
    """What the parcel page prints, in order."""
    out = [ROUTE_TEXT[assessment.route]]
    for item in assessment.items:
        prefix = (
            ""
            if item.asked or item.state in (REPORTED, NOT_ASKED, STATED_YES, STATED_NO, UNANSWERED)
            else "(Not asked on this branch; shown for reference.) "
        )
        out.append(prefix + item.text)
    out.append(
        "These lines report what is on file in Trazo. Whether a document satisfies the certifying agent "
        "is the agent's determination."
    )
    out.extend(r.text for r in assessment.review)
    return out


def to_json(assessment: Optional[Assessment]) -> Optional[dict]:
    if assessment is None:
        return None
    return {
        "agent": assessment.agent,
        "branch": assessment.branch,
        "route": assessment.route,
        "land_history_asked": assessment.land_history_asked,
        "items": [
            {
                "key": i.key,
                "state": i.state,
                "asked": i.asked,
                "path": i.path,
                "reference": i.reference,
            }
            for i in assessment.items
        ],
        "review": [{"kind": r.kind, "detail": r.detail} for r in assessment.review],
        "missing": assessment.missing,
    }
