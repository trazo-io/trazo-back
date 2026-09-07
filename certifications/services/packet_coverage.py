"""
What the renewal packet covers — and, just as importantly, what it does not.

CCOF's *Guide to Grower OSP Forms* (NOPB50) routes an operation to forms by activity, so a reviewer
opening this packet already knows which forms a crop operation owes. An absence they have to
discover for themselves reads as an omission; a stated one reads as a scope decision. This page is
the difference, and it is the cheapest thing in the whole conformance effort: the facts already
exist in the conformance register (`documentation/compliance/ccof/`), which CI checks against the
shipped module registry.

## What this page may and may not say

It is written for the certifying agent, not for us. So:

  * it maps CCOF's form codes to the files in this packet, because that is how a reviewer navigates;
  * it names the forms Trazo does not generate, with the reason, so the operation knows what to
    file separately;
  * it states who authored what — Trazo drafts from the operation's own records, the producer is
    the author of the plan under § 205.201(a), and every compliance determination is the agent's.

It does NOT carry the register's internal severities or engineering gap notes. "P0 — the packet
asserts something untrue" is a sentence about our backlog, not about this farm's plan.

## Degradation

The register is a documentation tree read at runtime. If it cannot be loaded, this page still
renders the authorship statement and the packet's own contents — a packet must never fail to
generate because a docs file moved. `coverage_rows()` returning an empty list is that state, and
the renderer says so rather than implying full coverage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: CCOF document id -> (form title, where it lands in this packet).
#:
#: Keyed by document id because that is the stable identifier on CCOF's own paper (the G-code is
#: absent from three of the forms). This map — not the conformance register — is the truth about
#: what the ZIP contains: W2.0 has a module and rides in every packet even though it has no
#: register entry yet, and an earlier version of this page listed it under "forms Trazo does not
#: generate" while the packet contained it. Registered and generated are different axes.
_PACKET_LOCATION = {
    "NOPB49": ("Parcel Application", "parcels/parcel-application-<parcel>.pdf (one per parcel)"),
    "NOPB41": ("Grower Materials Application (OSP Materials List)", "modules/materials_application.pdf"),
    "NOPB47": ("G3.0 Seeds & Planting Stock", "modules/G3_0.pdf"),
    "NOPB45": ("G4.0 Rotation & Soil Management", "modules/G4_0.pdf"),
    "NOPB44": ("G4.1 Compost and Manure", "modules/G4_1.pdf"),
    "NOPB43": ("G4.2 Natural Resources", "modules/G4_2.pdf"),
    "NOPB42": ("G5.0 Pest Management", "modules/G5_0.pdf"),
    "NOPB40": ("G6.0 Production", "modules/G6_0.pdf"),
    "NOPB39": ("G6.1 Harvest & Transport", "modules/G6_1.pdf"),
    "NOPB38": ("G6.2 Storage", "modules/G6_2.pdf"),
    "NOPB36": ("G6.4 Simple On-Farm Post Harvest Handling", "modules/G6_4.pdf"),
    "NOPB35": ("G6.5 Sourcing Products and Direct Marketing", "modules/G6_5.pdf"),
    "NOPB34": ("G7.0 Labeling", "modules/G7_0.pdf"),
    "NOPB33": ("G8.0 Record Keeping", "modules/G8_0.pdf"),
    "NOPB06": ("CCOF Certification Contract", "modules/certification_contract.pdf"),
    "NOPB48": ("W2.0 Wild Crop Harvesting", "modules/W2_0.pdf"),
}


@dataclass(frozen=True)
class CoverageRow:
    form: str
    document_id: str
    location: str
    generated: bool


@dataclass(frozen=True)
class ExclusionRow:
    form: str
    document_id: str
    reason: str
    is_gap: bool


#: Whose form codes this page speaks. `_PACKET_LOCATION` maps CCOF document ids, and the page's
#: whole premise is that a reviewer navigates by their OWN form codes — so it is CCOF's scope this
#: page states, not every registered agent's. Generalising the page to a second agent means keying
#: `_PACKET_LOCATION` by certifier too; until then, naming the assumption beats inheriting it.
COVERAGE_PAGE_CERTIFIER = "ccof"


def coverage_rows() -> list[CoverageRow]:
    """Every CCOF form this packet produces, plus registered forms it does not.

    Built from `_PACKET_LOCATION` (what the ZIP contains) unioned with the conformance register
    (what we have compared ourselves against), so a form can never be described as absent while the
    packet carries it.
    """
    try:
        from certifications.services.certifier_register import load_forms

        # 🔴 2026-09-07 — this called `load_forms()` with no argument, so it returned EVERY
        # registered certifier's forms while the page below files them all under CCOF's
        # headings. Once WSDA was registered, five AGR forms (2121 Crop Producer OSP, 2196
        # Input Material List, 2262 Previous Land Use, 2264 Site Application, 2516 Site
        # Update) printed under "Compared against, but not generated — file CCOF's own form".
        # Telling an operation to file a Washington State form with CCOF is worse than saying
        # nothing. `COVERAGE_PAGE_CERTIFIER` is the scope this page has always documented, and
        # `exclusion_rows()` below already honoured it — only this half did not.
        registered = {form.document_id: form.label for form in load_forms(COVERAGE_PAGE_CERTIFIER)}
    except Exception:  # noqa: BLE001
        logger.exception("CCOF register could not be loaded; packet coverage page will be reduced")
        registered = {}

    rows = [
        CoverageRow(
            form=registered.get(doc_id) or title,
            document_id=doc_id,
            location=location,
            generated=True,
        )
        for doc_id, (title, location) in _PACKET_LOCATION.items()
    ]
    rows += [
        CoverageRow(form=label, document_id=doc_id, location="", generated=False)
        for doc_id, label in registered.items()
        if doc_id not in _PACKET_LOCATION
    ]
    return sorted(rows, key=lambda r: (not r.generated, r.form))


def exclusion_rows(certifier: str = COVERAGE_PAGE_CERTIFIER) -> list[ExclusionRow]:
    """Forms Trazo neither registers NOR generates, with the stated reason.

    Anything the packet actually contains is filtered out here, however its scope entry reads —
    a page that tells a certifier a document is absent while it sits in the same ZIP is exactly the
    kind of false statement this work exists to remove.

    🔴 2026-09-06 — this read `load_scope()` with no argument, which returns EVERY registered
    agent's scope file. Once WSDA was registered (2026-08-28), a CCOF packet's coverage page
    listed WSDA's AGR 2180 / 2523 / 2524 among the forms "this packet does not cover" — three
    documents CCOF has never heard of, on a page written to tell a CCOF reviewer what is missing.
    """
    try:
        from certifications.services.certifier_register import load_scope

        return [
            ExclusionRow(
                form=entry.form,
                document_id=entry.document_id,
                reason=entry.reason,
                is_gap=entry.disposition == "gap",
            )
            for entry in load_scope(certifier)
            if entry.document_id not in _PACKET_LOCATION
        ]
    except Exception:  # noqa: BLE001
        logger.exception("%s scope file could not be loaded; packet coverage page will be reduced", certifier)
        return []


def outstanding_modules(osp) -> list[str]:
    """Modules of THIS plan that are neither complete nor attested Not Applicable.

    The operator's own to-do, in the packet, because a reviewer finding it first is worse. Uses the
    same current-questionnaire rule the module list uses, so a module completed against older
    content — or holding an attestation over an empty list — is reported honestly here too.
    """
    from certifications.osp_modules import MODULE_REGISTRY
    from certifications.osp_modules.conditions import missing_required
    from certifications.services.attestation_gates import blocked_attestations

    responses = (osp.module_responses or {}).get("modules", {}) or {}
    pending: list[str] = []
    for module in MODULE_REGISTRY:
        entry = responses.get(module.key) or {}
        if entry.get("not_applicable"):
            continue
        answers = entry.get("answers") or {}
        complete = bool(entry.get("completed_at")) and not missing_required(module, answers)
        if complete and blocked_attestations(module, answers, osp):
            complete = False
        if not complete:
            label = f"{module.code} " if module.code else ""
            pending.append(f"{label}{module.title.get('en', module.key)}".strip())
    return pending
