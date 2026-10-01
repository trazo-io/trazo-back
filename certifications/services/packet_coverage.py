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
    #: False for a registered form only some operations owe (WSDA's mushroom section). The page
    #: qualifies those, instead of telling every grower to file them.
    required_of_every_grower: bool = True


#: The location of the one-per-parcel application, as this module states it for every operation.
#: The packet's coverage page substitutes the operation's own parcels.
PARCEL_APPLICATION_LOCATION = "parcels/parcel-application-<parcel>.pdf (one per parcel)"


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
        return PARCEL_APPLICATION_LOCATION
    module = MODULES_BY_KEY.get(module_key)
    if module is None:
        return ""
    return f"modules/{module_file_stem(module)}.pdf"


#: Packet filenames that do not follow the module's code or key.
#:
#: `certification_contract` is an operation profile: three questions and an optional upload of
#: the contract the operation signed. Shipped as `certification_contract.pdf` beside a coverage
#: line reading "CCOF Certification Contract (NOPB06)", it read as the six-page agreement itself
#: (OSP alignment audit 2026-10, T16). The module KEY stays, because stored answers are keyed by it.
_MODULE_FILE_STEMS = {"certification_contract": "operation_profile"}


def module_file_stem(module) -> str:
    """The ONE filename rule for a module's packet PDF. The ZIP writer and this page both call it."""
    return _MODULE_FILE_STEMS.get(module.key) or (module.code or module.key).replace(".", "_")


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
            rows.append(
                CoverageRow(
                    form=form.label,
                    document_id=form.document_id,
                    location="",
                    generated=False,
                    required_of_every_grower=bool(form.required_of_every_grower),
                )
            )

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


@dataclass(frozen=True)
class FormCoverage:
    """One registered form the packet speaks to, with what THIS plan actually answers on it."""

    form: str
    document_id: str
    location: str
    #: "answered"          every in-scope question is closed (see packet_answers.CLOSED_STATES)
    #: "in_part"           the packet carries content for it, and some questions are still open
    #: "filed_with_agent"  the operation files it with the agent; the packet only supports it
    standing: str
    #: The open REQUIRED rows, in register order. Empty for an answered form.
    open_rows: tuple = ()
    #: Open rows the form itself prints as optional. Listed beside the form whatever its standing,
    #: so an answered form never reads as complete while optional items are blank.
    optional_open_rows: tuple = ()
    requires_signature: bool = False
    accepted_format: str = ""
    #: The form is answered by the renewal pages (02/03) rather than a module.
    via_renewal_pages: bool = False


def form_coverage(osp, certifier: str) -> list[FormCoverage]:
    """Every form of `certifier` the packet carries content for, judged against this plan's answers.

    🔴 2026-09-30 (OSP alignment audit, T15/T16/T20). `coverage_rows` answers "which file carries
    this form", and the page printed that as "Forms generated in this packet". A mapping is not an
    answer: an operation that had answered nothing got a page listing every form as generated. This
    reads the answers. A form is `answered` only when every in-scope question on it is closed, and
    a form the operation files with its agent is never `answered` at all, whatever is filed in Trazo.
    """
    from certifications.services.packet_answers import form_answer_states, form_is_answered

    forms, _loaded = _load_forms(certifier)
    generated, _unlisted = _classify(forms)
    states = form_answer_states(osp, [form for form, _locations in generated])
    out: list[FormCoverage] = []
    for form, locations in generated:
        rows = states[id(form)]
        if form.filed_with_agent:
            standing = "filed_with_agent"
        elif form_is_answered(rows):
            standing = "answered"
        else:
            standing = "in_part"
        out.append(
            FormCoverage(
                form=form.label,
                document_id=form.document_id,
                location="; ".join(locations),
                standing=standing,
                open_rows=tuple(row for row in rows if row.is_open and not row.optional),
                optional_open_rows=tuple(row for row in rows if row.is_open and row.optional),
                requires_signature=form.requires_signature,
                accepted_format=form.accepted_format,
                via_renewal_pages="02-annual-update.pdf" in form.packet_documents,
            )
        )
    return sorted(out, key=lambda f: f.form)


def unreviewed_form_count(certifier: str = FALLBACK_CERTIFIER) -> int:
    """Forms of this agent that appear in NEITHER list on the coverage page.

    A draft register entry is not by itself unreviewed enough to hide: when WSDA was being
    registered most of its forms were drafts that already carried a `trazo_module`, so they were
    listed above with the file that answers them. (Every registered form is `complete` as of
    2026-09-30, so this counts zero today; it stays for the next agent registered a form at a
    time.) What a reader has to be told about is the residue: a draft entry with no module yet,
    which the DRAFT rule keeps out of "not generated" because nobody has decided whether Trazo
    covers it.

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


def outstanding_modules(osp, *, with_codes: bool = True) -> list[str]:
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
            # A fallback packet names sections without the G-numbers, which are one agent's numbering.
            label = f"{module.code} " if module.code and with_codes else ""
            pending.append(f"{label}{module.title.get('en', module.key)}".strip())
    return pending


# ---------------------------------------------------------------------------
# Renewal routing (OSP alignment audit T20, Phase 3)
# ---------------------------------------------------------------------------

#: The order a renewing operation meets its agent's renewal forms in.
_RENEWAL_ROLE_ORDER = ("annual_renewal", "site_update", "crop_update", "fee")

#: Register verdict, in the words the renewal supplement prints beside each official row. These
#: say where the answer is, never that the agent's form is complete.
_ROUTING_WORDS = {
    "covered": "in this packet",
    "partial": "in part in this packet",
    "not_covered": "not in this packet; answer it on the form",
    "out_of_scope": "the operation's own election on the form",
}


@dataclass(frozen=True)
class RoutingRow:
    ref: str
    asks: str
    #: One of `_ROUTING_WORDS`' values, or the plan's own open state for a row that cites a
    #: question this plan has not answered.
    standing: str
    where: str = ""
    optional: bool = False


@dataclass(frozen=True)
class RenewalForm:
    title: str
    document_id: str
    revision: str
    role: str
    url: str = ""
    accepted_format: str = ""
    requires_signature: bool = False
    #: Empty for a form the agent does not publish (it is named, with the reason, and no rows).
    rows: tuple = ()
    reason: str = ""


def renewal_routing(osp) -> tuple[str, list[RenewalForm]]:
    """(agent name, the agent's renewal forms with a row-by-row crosswalk), for the 02s supplement.

    Only for an agent whose register this packet speaks (`packet_certifier` own). A fallback
    packet gets nothing here: borrowing CCOF's renewal forms for an OCI operation would send it
    to the wrong agent's paperwork (the T23 rule).
    """
    from certifications.services.packet_answers import form_answer_states

    agent, own = packet_certifier(osp)
    if not own:
        return "", []
    forms, _loaded = _load_forms(agent)
    renewal_forms = [form for form in forms if form.renewal_role]
    states = form_answer_states(osp, renewal_forms)
    out: list[RenewalForm] = []
    for form in renewal_forms:
        plan_state = {row.ref: row for row in states[id(form)]}
        rows = []
        for item in form.items:
            if item.kind != "question":
                continue
            standing = _ROUTING_WORDS.get(item.status, item.status)
            row_state = plan_state.get(item.ref)
            if (
                item.questions
                and row_state is not None
                and row_state.state
                in (
                    "unanswered",
                    "unresolved",
                    "unconfirmed",
                )
            ):
                standing = f"not yet answered in this plan ({row_state.state})"
            where = item.prints if item.status in ("covered", "partial") and item.prints != "—" else ""
            rows.append(RoutingRow(item.ref, item.asks, standing, where, item.optional))
        out.append(
            RenewalForm(
                title=form.title,
                document_id=form.document_id,
                revision=form.revision,
                role=form.renewal_role,
                url=form.url,
                accepted_format=form.accepted_format,
                requires_signature=form.requires_signature,
                rows=tuple(rows),
            )
        )
    try:
        from certifications.services.certifier_register import load_scope

        for entry in load_scope(agent):
            if entry.renewal_role:
                out.append(
                    RenewalForm(
                        title=entry.form,
                        document_id=entry.document_id,
                        revision="",
                        role=entry.renewal_role,
                        reason=entry.reason,
                    )
                )
    except Exception:  # noqa: BLE001 — a packet must build without the docs tree
        logger.exception("%s scope could not be loaded for renewal routing", agent)
    out.sort(key=lambda f: (_RENEWAL_ROLE_ORDER.index(f.role), f.title))
    return packet_agent(osp).name or agent.upper(), out
