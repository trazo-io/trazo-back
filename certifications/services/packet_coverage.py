"""
What the renewal packet covers — and, just as importantly, what it does not.

A certifying agent's own Guide routes an operation to forms by activity, so a reviewer opening
this packet already knows which forms a crop operation owes. An absence they have to discover for
themselves reads as an omission; a stated one reads as a scope decision. This page is the
difference, and it is the cheapest thing in the whole conformance effort: the facts already exist
in the conformance register (`documentation/compliance/certifiers/<certifier>/`), which CI checks
against the shipped module registry.

## Whose form numbers this page speaks

🔴 2026-09-07 — the operation's OWN certifier's, resolved from its records, where the register
carries that agent. Until now the page was hardcoded to CCOF: a 16-row Python dict mapped NOPB
document ids to packet filenames, and `COVERAGE_PAGE_CERTIFIER = "ccof"` was a module constant.

That dict was a hand-maintained duplicate of data the register already holds and CI already
guards. A WSDA-certified operation — the primary market — received a packet indexed entirely to
another agent's paperwork, under a disclaimer inviting it to translate the numbering itself.

The register makes the mapping derivable instead. Each form file carries its `document_id`
(`AGR 2264`, `NOPB49`) and the `trazo_module` whose content answers it, and the packet's own
filename rule (`generate_osp_packet`) turns a module key into the file the ZIP contains. So this
page now walks the forms of whichever agent certified this operation. Registering a third agent
becomes a folder, not a code change.

## What this page may and may not say

It is written for the certifying agent, not for us. So:

  * it maps that agent's form codes to the files in this packet, because that is how a reviewer
    navigates;
  * it names the forms Trazo does not generate, with the reason, so the operation knows what to
    file separately;
  * it states who authored what — Trazo drafts from the operation's own records, the producer is
    the author of the plan under § 205.201(a), and every compliance determination is the agent's.

It does NOT carry the register's internal severities or engineering gap notes. "P0 — the packet
asserts something untrue" is a sentence about our backlog, not about this farm's plan.

Three rules keep the "not generated" list from making false statements, and each exists because
the register's raw shape would otherwise produce one:

  DRAFT      A form whose `register_status` is `draft` has not been analysed. Its empty
             `trazo_module` means "nobody has decided yet", NOT "Trazo does not cover this" —
             WSDA's §F Weed Management is a draft entry, and the packet plainly answers weed
             management inside G5.0. Draft forms are counted, never listed as absent.
  UMBRELLA   A form with no section code sharing its `document_id` with coded sections IS those
             sections. WSDA AGR 2121 "Crop Producer Organic System Plan" is the whole OSP; the
             packet is what it asks for, section by section. Listing it as not generated would be
             the most wrong sentence on the page.
  PRESENT    Anything the packet actually contains is filtered out of the exclusions, however its
             scope entry reads — a page that tells a certifier a document is absent while it sits
             in the same ZIP is exactly the kind of false statement this work exists to remove.

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

#: The numbering a packet falls back to when the operation's certifying agent is unknown or is not
#: in the register. CCOF's Common OSP is the closest thing to a shared vocabulary — it was
#: co-authored as the industry's common template — so a reviewer at an unregistered agent can still
#: navigate it. The page SAYS it is doing this; it never lets the reader assume the numbering is
#: their own.
FALLBACK_CERTIFIER = "ccof"

#: Forms the packet generates that the register carries no form file for, keyed
#: (certifier, document_id) -> (label, module key).
#:
#: Two entries, both the same real distinction rather than an oversight: CCOF NOPB48 is described in
#: `ccof/scope.yaml` as a deliberate decision — Trazo ships an N/A-attestable stub so a crop grower
#: can record that wild-crop harvesting does not apply, while the full form (designated area,
#: 36-month site history, harvest sustainability) is not built. The stub PDF is in the ZIP, so the
#: exclusions list must not call it absent; the register has no form file, so nothing else knows
#: its number. Keeping the exception visible here beats burying it in a 16-row location table.
_UNREGISTERED_PACKET_FORMS = {
    ("ccof", "NOPB48"): ("W2.0 Wild Crop Harvesting", "w2_0_wild_crop"),
    # Same decision, OTCO's number: W1 is excluded in otco/scope.yaml while the W2.0 stub ships.
    ("otco", "W1"): ("W1 Wild Crop Harvest", "w2_0_wild_crop"),
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


@dataclass(frozen=True)
class PacketAgent:
    """The certifying agent a plan is for, as one record stated it."""

    #: The agent as the record spells it; "" when no record names one.
    name: str = ""
    #: `certifying_agents` slug when the name is a known agent, else None. A slug is not a register:
    #: OCI has a slug and no form register, and `packet_certifier` is what tells the two apart.
    slug: str | None = None
    #: "plan" (the plan's own answer), "certificate" (the certificate of record), "records" (any
    #: other record that names an agent) or "" (none does).
    source: str = ""


def packet_agent(osp) -> PacketAgent:
    """The certifying agent THIS plan is for, and which record said so.

    🔴 2026-09-10 — the plan's own answer comes first. The picker asks for it at plan start and on
    the plan page, and it is the only place a first-year applicant, who holds no certificate yet,
    can name an agent at all. It wins over the certificate of record because the two answer
    different questions: the certificate says who certified the operation, the plan says who
    reviews this packet. They differ exactly when an operation moves to a new agent, and then the
    plan is the right one to number by. The cover still prints the certificate the operation holds.

    With no plan answer, the certificate of record decides, as it has since 2026-09-07, so the
    coverage page and the cover cannot name two agents drawn from two records by accident. Only
    when it names none does the wider scan run.

    A plan answer that is no known agent resolves to no slug. It does NOT fall through to the
    certificate: the operator said who reviews this plan, and the packet says it does not carry
    that agent's numbering rather than borrowing another record's.
    """
    from certifications.certifying_agents import agent_for_name
    from certifications.services.operation_certificate import agent_names, certificate_of_record

    def _slug(name):
        agent = agent_for_name(name)
        return agent.slug if agent else None

    stated = (getattr(osp, "certifier_name", "") or "").strip()
    if stated:
        return PacketAgent(stated, _slug(stated), "plan")

    establishment_id = osp.establishment_id
    certificate = certificate_of_record(establishment_id)
    if certificate.agent:
        return PacketAgent(certificate.agent, _slug(certificate.agent), "certificate")

    names = agent_names(establishment_id)
    for name in names:
        slug = _slug(name)
        if slug:
            return PacketAgent(name, slug, "records")
    return PacketAgent(names[0], None, "records") if names else PacketAgent()


def resolve_certifier(osp) -> str | None:
    """The slug of the agent that reviews THIS plan, or None when it is no agent Trazo knows.

    A slug is the agent's key in `certifications.certifying_agents`; where Trazo holds a form
    register for the agent it is also the register folder. Which record supplies the name is
    `packet_agent`'s decision, so every page of one packet speaks for the same agent.
    """
    return packet_agent(osp).slug


def registered_certifiers() -> set[str]:
    """Slugs of the agents whose form numbering the packet can speak. Empty if the register is unreadable."""
    try:
        from certifications.services.certifier_register import certifiers

        return set(certifiers())
    except Exception:  # noqa: BLE001
        logger.exception("Certifier register could not be listed")
        return set()


def packet_certifier(osp) -> tuple[str, bool]:
    """(register folder this packet's coverage page speaks, whether it is the operation's own)."""
    slug = resolve_certifier(osp)
    if slug and slug in registered_certifiers():
        return slug, True
    return FALLBACK_CERTIFIER, False


def _module_location(module_key: str) -> str:
    """Where a module's content lands in the ZIP.

    Mirrors `generate_osp_packet`'s own filename rule so the two cannot drift — a coverage page
    naming a file the ZIP does not contain is worse than no coverage page.
    `test_packet_coverage_speaks_the_agents_numbers.py` asserts, in both directions, that every
    location this returns is a real entry in the ZIP and that every module PDF in the ZIP is named
    on the page.
    """
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

    if module_key == PARCEL_APPLICATION.key:
        return "parcels/parcel-application-<parcel>.pdf (one per parcel)"
    module = MODULES_BY_KEY.get(module_key)
    if module is None:
        return ""
    return f"modules/{(module.code or module.key).replace('.', '_')}.pdf"


def _module_label(module_key: str) -> str:
    """How a module names itself when no form of this agent claims it."""
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

    module = MODULES_BY_KEY.get(module_key)
    if module is None and module_key == PARCEL_APPLICATION.key:
        module = PARCEL_APPLICATION
    if module is None:
        return module_key
    title = module.title.get("en", module_key) if isinstance(module.title, dict) else str(module.title)
    return f"{module.code} {title}".strip() if module.code else title


def _packet_module_keys() -> list[str]:
    """Every module the packet writes a PDF for, in packet order."""
    from certifications.osp_modules import MODULE_REGISTRY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

    return [m.key for m in MODULE_REGISTRY] + [PARCEL_APPLICATION.key]


def _is_umbrella(form, by_document_id) -> bool:
    """A section-less form whose document id is carried by coded sections IS those sections."""
    if form.code:
        return False
    return any(other.code for other in by_document_id.get(form.document_id, ()) if other is not form)


def _classify(forms) -> tuple[list, list]:
    """Split a certifier's forms into [(form, [locations])] generated, and [(form, why)] not.

    Lists of pairs, not dicts: `Form` is a mutable dataclass and therefore unhashable, so keying
    by it raises `TypeError: unhashable type: 'Form'` the moment the register loads.

    🔴 One pass, two consumers. `coverage_rows` and `unreviewed_form_count` each carried their own
    copy of the DRAFT and UMBRELLA rules, and the first version of the count applied neither — so
    a page that had just listed twenty WSDA forms by name closed with "20 further WSDA forms have
    not yet been compared". Two readings of one rule set is exactly how that sentence happens, so
    there is now only one.
    """
    by_document_id: dict[str, list] = {}
    for form in forms:
        by_document_id.setdefault(form.document_id, []).append(form)

    generated: list = []
    unlisted: list = []
    for form in forms:
        # A form's own document first: the packet documents that answer it where no module does
        # (the agent's renewal application -> the update pages), or that ARE the agent's form
        # (OTCO FACT-04 -> its workbook, which this page used to skip for the parcel PDFs). The
        # loader has already refused any name this agent's ZIP does not write.
        locations: list[str] = list(form.packet_documents)
        for key in form.trazo_modules:
            location = _module_location(key)
            if location and location not in locations:
                locations.append(location)
        if locations:
            generated.append((form, locations))
        elif form.register_status == "complete" and not _is_umbrella(form, by_document_id):
            unlisted.append((form, "absent"))
        elif not _is_umbrella(form, by_document_id):
            # A draft entry with nothing mapped: neither covered nor absent, because nobody has
            # decided. Counted on the page, never named either way.
            unlisted.append((form, "unreviewed"))
    return generated, unlisted


def _load_forms(certifier: str):
    """(forms, loaded?) — the register is a docs tree, and a packet must build without it."""
    try:
        from certifications.services.certifier_register import load_forms

        return load_forms(certifier), True
    except Exception:  # noqa: BLE001
        logger.exception("%s register could not be loaded; packet coverage page will be reduced", certifier)
        return [], False


def _unlisted_draft_forms(certifier: str) -> list:
    forms, _loaded = _load_forms(certifier)
    _generated, unlisted = _classify(forms)
    return [form for form, why in unlisted if why == "unreviewed"]


def coverage_rows(certifier: str = FALLBACK_CERTIFIER) -> list[CoverageRow]:
    """Every form of `certifier` this packet produces, plus registered forms it does not.

    Derived from the register: each form's `trazo_module` says which module answers it, and
    `_module_location` says where that module lands in the ZIP. Packet modules no form of this
    agent claims are listed too, without a form number — the packet contains them either way, and
    a coverage page that omits a file the reviewer is holding is its own kind of wrong.
    """
    # NOT a bare return on failure. The register is a docs tree; the packet's own contents are
    # code. When the tree cannot be read, every module still falls through to the unclaimed loop
    # below and is listed by filename with no form number — the reviewer keeps the wayfinding and
    # simply loses the agent's numbering, which the renderer then says out loud. Returning [] here
    # would throw away a list we can always compute, and that is the one behaviour the pre-refactor
    # version got right that a naive rewrite drops.
    forms, register_loaded = _load_forms(certifier)
    generated, unlisted = _classify(forms)

    rows: list[CoverageRow] = []
    claimed: set[str] = set()

    for form, locations in generated:
        claimed.update(key for key in form.trazo_modules if _module_location(key))
        rows.append(
            CoverageRow(
                form=form.label,
                document_id=form.document_id,
                location="; ".join(locations),
                generated=True,
            )
        )
    for form, why in unlisted:
        if why == "absent":
            rows.append(CoverageRow(form=form.label, document_id=form.document_id, location="", generated=False))

    # Gated on the register having loaded. This map fills a GAP IN the register — a form the
    # packet generates that has no form file yet — so it has no standing when the register itself
    # is unreadable. Ungated it left exactly one numbered row among twenty unnumbered ones, and
    # the page then announced it was numbering against CCOF while showing a single number.
    if register_loaded:
        for (slug, document_id), (label, module_key) in _UNREGISTERED_PACKET_FORMS.items():
            if slug != certifier:
                continue
            location = _module_location(module_key)
            if location:
                claimed.add(module_key)
                rows.append(CoverageRow(form=label, document_id=document_id, location=location, generated=True))

    for key in _packet_module_keys():
        if key in claimed:
            continue
        location = _module_location(key)
        if not location:
            continue
        rows.append(CoverageRow(form=_module_label(key), document_id="", location=location, generated=True))

    return sorted(rows, key=lambda r: (not r.generated, r.form))


def unreviewed_form_count(certifier: str = FALLBACK_CERTIFIER) -> int:
    """Forms of this agent that appear in NEITHER list on the coverage page.

    A draft register entry is not by itself unreviewed enough to hide: 20 of WSDA's 24 forms are
    drafts, and most of them already carry a `trazo_module`, so they are listed above as generated
    with the file that answers them. What a reader has to be told about is the residue — a draft
    entry with no module yet, which the DRAFT rule keeps out of "not generated" because nobody has
    decided whether Trazo covers it.

    Counting every draft instead printed "20 further WSDA forms have not yet been compared" on a
    page that had just listed 20 of them by name. Umbrella rows are excluded for the same reason
    they are excluded above: they are the sections, and the sections are listed.
    """
    return sum(1 for form in _unlisted_draft_forms(certifier))


def exclusion_rows(certifier: str = FALLBACK_CERTIFIER) -> list[ExclusionRow]:
    """Forms Trazo neither registers NOR generates, with the stated reason.

    Anything the packet actually contains is filtered out here, however its scope entry reads —
    see the PRESENT rule in this module's docstring.

    🔴 2026-09-06 — this read `load_scope()` with no argument, which returns EVERY registered
    agent's scope file. Once WSDA was registered (2026-08-28), a CCOF packet's coverage page
    listed WSDA's AGR 2180 / 2523 / 2524 among the forms "this packet does not cover" — three
    documents CCOF has never heard of, on a page written to tell a CCOF reviewer what is missing.
    """
    try:
        from certifications.services.certifier_register import load_scope

        present = {row.document_id for row in coverage_rows(certifier) if row.generated and row.document_id}
        return [
            ExclusionRow(
                form=entry.form,
                document_id=entry.document_id,
                reason=entry.reason,
                is_gap=entry.disposition == "gap",
            )
            for entry in load_scope(certifier)
            if entry.document_id not in present
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
