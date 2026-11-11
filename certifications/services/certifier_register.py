"""
Loader and validator for the certifier conformance registers.

The register (`documentation/compliance/certifiers/<certifier>/`) is the source of truth for any
statement Trazo makes about alignment with a certifying agent's own OSP forms: one YAML file per
form, one row per numbered question, table column or checkbox group on that form.

One folder per certifier, all the same shape — `forms/`, `scope.yaml`, `unmapped/`. CCOF and WSDA
are overlays of the same federal content (7 CFR 205.201), so a second certifier is registered as a
DELTA against the first: rows that ask the same obligation cite the same Trazo questions, and only
what a certifier asks differently, or additionally, is fresh analysis. Two independent full audits
of one product will disagree about it — that is not a hypothetical, it is what the
cited-vs-unmapped guard was written to catch after two passes described the same nine questions
contradictorily.

It is data rather than prose for one reason: prose about a questionnaire goes stale the first time
the questionnaire changes, and nothing tells you. Everything here exists so that
`test_ccof_conformance_register.py` can fail when the register and `MODULE_REGISTRY` disagree — in
BOTH directions:

  forward   every `module_key.question_key` the register cites must exist today. Catches a
            register row pointing at a question that was renamed or deleted.
  reverse   every question of a module whose form is marked `register_status: complete` must be
            cited by the register or listed in `unmapped/<module_key>.yaml` with a reason. Catches
            a question added to a mapped module without anyone deciding what CCOF asks about it.

`form.trazo_module` takes one module key or a list. A list is how a form claims content Trazo
splits differently from CCOF — G6.2 Storage, for instance, answers its facility-pest questions out
of the separate G9.0 module.

`form.packet_documents` names top-level packet documents (`PACKET_DOCUMENTS`) that answer a form
no module does — a renewal application answered by the annual-update and change-notification
pages. It is the third state the coverage page needs besides "answered by a module" and "absent".

Reverse coverage is deliberately scoped to *complete* forms so the register can be built one form
at a time without the guard failing the build meanwhile.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# certifications/services/certifier_register.py -> services -> certifications -> trazo-back
#
# ⚠️ This was `parents[3]`, i.e. the directory ABOVE this repository, with the comment
# "certifications -> trazo-back -> repo root". There is no such root: ~/dev/trazo is an
# ordinary folder, not a git repository, and it is not part of the Docker build context
# either (Dockerfile is WORKDIR /app + COPY . .). So in production `parents[3]` resolved to
# "/" and REGISTER_DIR pointed at /documentation/compliance/certifiers, which does not exist.
#
# The register was therefore ABSENT from every built image. It failed silently rather than
# loudly — `certifiers()` returns [] on a missing directory, and the packet's coverage page
# is designed to degrade instead of crash — so the certifier packet has been shipping without
# the section that names the forms Trazo does NOT generate. The honesty section is the one
# that goes missing.
#
# Found 2026-09-07 by the first CI run this repository ever completed: the same absence made
# `test_the_page_names_the_forms_trazo_does_not_generate` fail on a runner while passing on a
# laptop, where ~/dev/trazo/documentation happened to sit beside the checkout.
#
# The register is a RUNTIME FIXTURE read by application code, not documentation. It now lives
# inside this repository, so it is versioned with the code that reads it and is present in the
# image. `.dockerignore` excludes *.md but not *.yaml, so the form definitions are copied.
REGISTER_DIR = Path(__file__).resolve().parents[2] / "documentation" / "compliance" / "certifiers"


def certifiers() -> list[str]:
    """Certifier keys, alphabetical.

    A certifier counts as registered once it has at least one form file — an empty `forms/`
    directory is the normal state while a new certifier is being built out, and it must not break
    the guards or the generated statement for the certifiers already registered.
    """
    if not REGISTER_DIR.is_dir():
        return []
    return sorted(p.name for p in REGISTER_DIR.iterdir() if any((p / "forms").glob("*.yaml")))


def forms_dir(certifier: str) -> Path:
    return REGISTER_DIR / certifier / "forms"


def unmapped_dir(certifier: str) -> Path:
    return REGISTER_DIR / certifier / "unmapped"


def scope_path(certifier: str) -> Path:
    return REGISTER_DIR / certifier / "scope.yaml"


STATUSES = ("covered", "partial", "not_covered", "out_of_scope")
#: What a row IS, before what Trazo does about it (OSP alignment audit 2026-10, T26):
#:   question        an official item the operation answers. The only kind that carries a status.
#:   instruction     official text that asks nothing (an explanation, an agreement term executed by
#:                   a signature row elsewhere on the form)
#:   interpretation  not on the form at all: a reading Trazo adds, kept for its gap analysis
#: Only questions count toward whether a form is answered, and the source inventory guarantees
#: every official question has its own `question` row, so the other two kinds cannot stand in for
#: one.
ROW_KINDS = ("question", "instruction", "interpretation")
#: Why an official question is nobody's business in this packet. Closed on purpose: a requirement
#: that applies to SOME operations is not out of scope, it is conditional, and says so with
#: `applies_when` (evaluated against the plan's answers) or stays open as `not_covered`.
#: `agent_agreement` is the row that executes the agent's own agreement (a signature, "I accept the
#: above terms"): the operation gives it to the agent on the agent's form, and no packet gives it for
#: them. The terms it executes are `instruction` rows.
SCOPE_BASES = (
    "payment_data",
    "agent_administration",
    "optional_marketing",
    "not_an_operation_obligation",
    "agent_agreement",
)
#: Condition ops `applies_when` may use, the same ones a module's `visible_when` uses.
_APPLIES_WHEN_OPS = ("eq", "ne", "includes", "includes_any", "one_of", "not_includes", "truthy", "falsy")
SEVERITIES = ("P0", "P1", "P2", "P3")
REGISTER_STATUSES = ("complete", "draft")
#: How an agent accepts a form the operation files with it (`form.accepted_format`):
#:   agent_form                                the agent's own document, completed and returned
#:   agent_web_form                            the agent's online form
#:   alternative_records_with_required_fields  the agent accepts the operation's own records in
#:                                             place of the form, provided every field it asks is there
ACCEPTED_FORMATS = ("agent_form", "agent_web_form", "alternative_records_with_required_fields")
#: What part of an agent's renewal a form is (`form.renewal_role`), for routing the renewal
#: supplement (02s) to the agent's own forms (OSP alignment audit T20, Phase 3):
#:   annual_renewal  the agent's renewal application or contract, filed every year
#:   site_update     changes to sites or parcels on the certified profile
#:   crop_update     changes to the crops and acreage on the certified profile
#:   fee             the renewal fee calculation and payment
RENEWAL_ROLES = ("annual_renewal", "site_update", "crop_update", "fee")
DISPOSITIONS = ("decision", "gap")

# Rows that are not `covered` owe the reader a statement of what is missing; anything short of
# `out_of_scope` also owes a fix, because "we know and we are not doing it" is a decision that
# belongs in `reason`, not an empty column.
_REQUIRED_WHEN = {
    "partial": ("severity", "gap", "fix"),
    "not_covered": ("severity", "gap", "fix"),
    "out_of_scope": ("reason",),
}

# `code` is deliberately NOT required: the Parcel Application, the Grower Materials Application and
# the Certification Contract carry no G-number on CCOF's own paper, and forcing a placeholder into
# the field would print a code in the statement that a reviewer cannot look up.
_FORM_REQUIRED = ("title", "document_id", "revision", "url", "retrieved", "register_status")

#: The packet's top-level documents, by the exact name `generate_osp_packet` writes into the ZIP.
#: A form names these in `packet_documents` when a packet document, not an OSP module, answers it.
#: Validated at load so a renamed document fails the build instead of printing a filename the
#: reviewer cannot find; `test_packet_documents_match_the_zip` pins this tuple to the ZIP itself.
PACKET_DOCUMENTS = (
    "00-cover.pdf",
    "01-organic-system-plan.pdf",
    "02-annual-update.pdf",
    "02s-renewal-status-and-routing.pdf",
    "03-change-notifications.pdf",
    "04-coverage-and-scope.pdf",
    "05-audit-trail-exhibit.pdf",
    # Built last: the agent-ordered question index, citing the pages of everything above (T24).
    "06-question-index.pdf",
)


def _packet_documents(meta: dict, where: str, certifier: str = "") -> tuple[str, ...]:
    """`form.packet_documents`, refused when it names a file this agent's packet does not write.

    Two kinds of name are accepted: a top-level document (`PACKET_DOCUMENTS`), and
    `workbooks/<file>` for a sheet this agent's packet carries — an agent-neutral USDA sheet, or
    the agent's own (OTCO FACT-04). A sheet another agent owns never ships in this agent's ZIP.
    """
    names = _as_tuple(meta.get("packet_documents"))
    unknown = [name for name in names if name not in PACKET_DOCUMENTS and not _ships_workbook(name, certifier)]
    if unknown:
        raise ValueError(f"{where}: packet_documents names no packet document: {', '.join(unknown)}")
    return names


def _ships_workbook(name: str, certifier: str) -> bool:
    """True when `name` is `workbooks/<file>` for a sheet every packet of `certifier` carries."""
    if not name.startswith("workbooks/"):
        return False
    # Imported here: the register is read by code that never builds a workbook, and the packet
    # module is heavy. `_workbook_filename` is the ONE author of the ZIP entry name.
    from certifications.services.common_osp_workbooks import WORKBOOKS
    from certifications.services.osp_module_pdf import _workbook_filename

    return any(
        name == f"workbooks/{_workbook_filename(spec)}" and (not spec.agents or certifier in spec.agents)
        for spec in WORKBOOKS
    )


@dataclass
class Item:
    ref: str
    asks: str
    status: str
    severity: str | None = None
    gap: str | None = None
    fix: str | None = None
    reason: str | None = None
    #: Where the answer to this form question lives in Trazo.
    questions: tuple[str, ...] = ()
    #: Existing Trazo answers that INDICATE this form applies — not where it is answered. A form
    #: Trazo cannot answer at all still has triggers, and conflating the two made one question read
    #: as both `covered` (by the form that answers it) and `not_covered` (by the form it triggers).
    triggered_by: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    prints: str = ""
    #: Where the answer is, in the words a certifier reads on the renewal supplement (02s): packet
    #: file names and the label printed there. `prints` is the register's own note and is never
    #: printed; it may carry placeholders and in-app detail.
    where: str = ""
    root_cause: str = ""
    kind: str = "question"
    #: The form itself prints this item as optional. Set only where the source inventory says so.
    optional: bool = False
    #: Required on `out_of_scope`: one of SCOPE_BASES.
    scope_basis: str = ""
    #: `((module.question, op, value), ...)`. The item applies only when every condition holds.
    #: Evaluated like a module's `visible_when`: a failing condition on an ANSWERED trigger closes
    #: the row as not applicable with that answer as evidence; on an unanswered one it is open.
    applies_when: tuple = ()

    @property
    def is_gap(self) -> bool:
        return self.kind == "question" and self.status in ("partial", "not_covered")


@dataclass
class Form:
    path: Path
    code: str
    title: str
    document_id: str
    revision: str
    url: str
    retrieved: datetime.date | str
    pdf: str = ""
    nop_cites: tuple[str, ...] = ()
    guide_trigger: str = ""
    required_of_every_grower: bool = False
    trazo_modules: tuple[str, ...] = ()
    #: Packet documents that answer this form when no OSP module does. OTCO's OSP Update Form and
    #: WSDA AGR 2516 are answered by 02-annual-update.pdf and 03-change-notifications.pdf, which
    #: print `OSPAnnualUpdate` and `OSPChangeNotification` — models, not a module. Without this
    #: the only honest status for such a form was `draft`, and the coverage page told an OTCO
    #: reviewer that the agent's own renewal application "has not yet been compared".
    packet_documents: tuple[str, ...] = ()
    #: The operation files this form with the agent through the agent's own process (a contract,
    #: a renewal application). A packet can support it; it never completes or replaces it, so the
    #: coverage page lists it apart from the forms the packet answers (audit 2026-10, T16 and T20).
    filed_with_agent: bool = False
    #: The form carries a signature the operation gives the agent. Set only where the form says so.
    requires_signature: bool = False
    #: One of ACCEPTED_FORMATS, or "" when nobody has read what the agent accepts.
    accepted_format: str = ""
    #: Where `requires_signature` / `accepted_format` come from: the form section or instruction
    #: that says so. Required whenever either is set, so neither is ever a guess.
    format_source: str = ""
    #: One of RENEWAL_ROLES when the form is part of the agent's renewal; "" otherwise.
    renewal_role: str = ""
    #: Set when the agent sends this form to the operation with its renewal and the copy it sends is
    #: not the one on its website: the agent's own words, with who said it and when. The routing page
    #: then names no edition, since the edition transcribed here is not the one the operation fills.
    sent_with_renewal: str = ""
    #: Set when the agent has asked Trazo not to reproduce the form (`not_reproduced: {basis,
    #: decided}`): the agent's own words, with who said it and when. The items stay in the register
    #: as the record of the edition that was read, but nothing the operation or the agent reads
    #: prints them or links the file: 02s names the form with the reason and no rows, and the copy
    #: sheet gives one row sending the operation to the copy the agent sent (WSDA AGR 2521,
    #: overall review 2026-11, OV-PK-W01).
    not_reproduced_basis: str = ""
    not_reproduced_decided: datetime.date | str = ""
    #: Set when the form exists only for a kind of operation Trazo has decided not to serve
    #: (mushrooms, wild harvest). A business decision, so it lives on the FORM with its reason and
    #: date, never on the questions: their statuses stay what they are, and the day the decision
    #: is reversed the work is already listed. The statement counts these forms apart.
    not_served_basis: str = ""
    not_served_decided: datetime.date | str = ""
    register_status: str = "complete"
    #: sha256 of the agent's file this form was transcribed from. Matches its source inventory
    #: (`<agent>/inventory/<stem>.yaml`), which lists the form's official items as the document
    #: prints them; see certifications/services/form_inventory.py.
    source_sha256: str = ""
    certifier: str = ""
    items: list[Item] = field(default_factory=list)

    @property
    def served(self) -> bool:
        return not self.not_served_basis

    @property
    def reproduced(self) -> bool:
        return not self.not_reproduced_basis

    @property
    def label(self) -> str:
        return f"{self.code} {self.title}".strip() if self.code else self.title


def _as_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _not_served_meta(meta: dict, where: str) -> dict:
    """`not_served: {basis, decided}`, validated: both or nothing, and never on a form every
    grower files (Trazo cannot decline to serve the operation it is for)."""
    raw = meta.get("not_served")
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not str(raw.get("basis") or "").strip() or not raw.get("decided"):
        raise ValueError(f"{where}: not_served needs a basis and the date it was decided")
    if meta.get("required_of_every_grower"):
        raise ValueError(f"{where}: a form every grower files cannot be marked not_served")
    return {"not_served_basis": " ".join(str(raw["basis"]).split()), "not_served_decided": raw.get("decided")}


def _not_reproduced_meta(meta: dict, where: str) -> dict:
    """`not_reproduced: {basis, decided}`, validated: both or nothing, and only on a form the
    operation files with the agent. A form the packet answers is answered by printing its items, so
    it cannot also be one whose items are never printed."""
    raw = meta.get("not_reproduced")
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not str(raw.get("basis") or "").strip() or not raw.get("decided"):
        raise ValueError(f"{where}: not_reproduced needs a basis and the date it was decided")
    if not meta.get("filed_with_agent"):
        raise ValueError(f"{where}: not_reproduced describes a form filed with the agent")
    return {
        "not_reproduced_basis": " ".join(str(raw["basis"]).split()),
        "not_reproduced_decided": raw.get("decided"),
    }


def _filing_meta(meta: dict, where: str) -> dict:
    """`filed_with_agent`, `requires_signature`, `accepted_format`, `format_source`, validated.

    A signature or a format claim printed on a certifier-facing page has to come from the form,
    so either one without a `format_source` is refused rather than defaulted.
    """
    accepted_format = str(meta.get("accepted_format") or "")
    if accepted_format and accepted_format not in ACCEPTED_FORMATS:
        raise ValueError(f"{where}: accepted_format must be one of {ACCEPTED_FORMATS}")
    requires_signature = bool(meta.get("requires_signature"))
    format_source = str(meta.get("format_source") or "").strip()
    if (requires_signature or accepted_format) and not format_source:
        raise ValueError(f"{where}: requires_signature / accepted_format need a `format_source`")
    filed_with_agent = bool(meta.get("filed_with_agent"))
    if (requires_signature or accepted_format) and not filed_with_agent:
        raise ValueError(f"{where}: signature and format metadata describe a form filed with the agent")
    renewal_role = str(meta.get("renewal_role") or "")
    if renewal_role and renewal_role not in RENEWAL_ROLES:
        raise ValueError(f"{where}: renewal_role must be one of {RENEWAL_ROLES}")
    if renewal_role and not filed_with_agent:
        # A renewal form is the agent's paperwork. Routing a reader to it while the coverage page
        # lists it as answered by the packet would say two different things about one form.
        raise ValueError(f"{where}: a renewal_role form is filed with the agent")
    sent_with_renewal = " ".join(str(meta.get("sent_with_renewal") or "").split())
    if sent_with_renewal and not renewal_role:
        raise ValueError(f"{where}: sent_with_renewal describes a form in the agent's renewal")
    return {
        "filed_with_agent": filed_with_agent,
        "requires_signature": requires_signature,
        "accepted_format": accepted_format,
        "format_source": format_source,
        "renewal_role": renewal_role,
        "sent_with_renewal": sent_with_renewal,
    }


def _applies_when(raw, where: str) -> tuple:
    """`applies_when:` as ((module.question, op, value), ...), refused when malformed."""
    if not raw:
        return ()
    out = []
    for cond in raw:
        question = str((cond or {}).get("question") or "")
        op = str((cond or {}).get("op") or "")
        if "." not in question or op not in _APPLIES_WHEN_OPS:
            raise ValueError(f"{where}: applies_when needs `question: module.key` and an op from {_APPLIES_WHEN_OPS}")
        if question.startswith("parcel_application."):
            # Answered once per parcel, so no single answer can decide a form-level requirement.
            raise ValueError(f"{where}: applies_when cannot read a per-parcel question ({question})")
        out.append((question, op, cond.get("value")))
    return tuple(out)


def load_forms(certifier: str | None = None) -> list[Form]:
    """Parse every form file for one certifier, or for all of them.

    Raises ValueError with a path-prefixed message on a schema fault.
    """
    if certifier is None:
        out: list[Form] = []
        for key in certifiers():
            out.extend(load_forms(key))
        if not out:
            raise ValueError(f"No certifier register holds any form file: {REGISTER_DIR}")
        return out

    directory = forms_dir(certifier)
    if not directory.is_dir():
        raise ValueError(f"Certifier register directory is missing: {directory}")

    forms: list[Form] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        meta = raw.get("form") or {}
        where = path.name

        missing = [k for k in _FORM_REQUIRED if not meta.get(k)]
        if missing:
            raise ValueError(f"{where}: form is missing required key(s): {', '.join(missing)}")

        # No default. `complete` claims every question of the mapped modules is accounted for, and
        # a file that merely FORGOT the field would make that claim silently — which is exactly
        # what happened while WSDA was being registered.
        register_status = meta.get("register_status")
        if register_status not in REGISTER_STATUSES:
            raise ValueError(f"{where}: register_status must be one of {REGISTER_STATUSES}")

        items: list[Item] = []
        seen_refs: set[str] = set()
        for raw_item in raw.get("items") or []:
            ref = str(raw_item.get("ref", "")).strip()
            if not ref:
                raise ValueError(f"{where}: an item has no `ref`")
            if ref in seen_refs:
                raise ValueError(f"{where}: duplicate item ref {ref!r}")
            seen_refs.add(ref)

            kind = str(raw_item.get("kind") or "question")
            if kind not in ROW_KINDS:
                raise ValueError(f"{where} [{ref}]: kind must be one of {ROW_KINDS}, got {kind!r}")
            status = raw_item.get("status")
            if kind != "question":
                # An instruction or an interpretation is not answered by anyone, so a status on it
                # would be a verdict about nothing, and would be counted as one.
                if status is not None:
                    raise ValueError(f"{where} [{ref}]: a {kind} row carries no status")
                if kind == "interpretation" and not str(raw_item.get("reason") or "").strip():
                    raise ValueError(f"{where} [{ref}]: an interpretation row needs a `reason`: why it is here")
                status = ""
            elif status not in STATUSES:
                raise ValueError(f"{where} [{ref}]: status must be one of {STATUSES}, got {status!r}")
            scope_basis = str(raw_item.get("scope_basis") or "")
            if status == "out_of_scope" and scope_basis not in SCOPE_BASES:
                raise ValueError(
                    f"{where} [{ref}]: out_of_scope needs a `scope_basis` from {SCOPE_BASES}; a requirement "
                    "that applies to some operations is conditional (`applies_when`), not out of scope"
                )
            if scope_basis and status != "out_of_scope":
                raise ValueError(f"{where} [{ref}]: scope_basis belongs on an out_of_scope row only")
            applies_when = _applies_when(raw_item.get("applies_when"), f"{where} [{ref}]")
            if applies_when and status == "out_of_scope":
                raise ValueError(f"{where} [{ref}]: a conditional row is not out of scope; drop one of the two")

            for key in _REQUIRED_WHEN.get(status, ()):
                if not raw_item.get(key):
                    raise ValueError(f"{where} [{ref}]: status {status!r} requires `{key}`")

            # One defect usually breaks several CCOF questions: the materials list that cannot hold
            # compost fails three questions on two forms. Without a shared root cause the register
            # reads as seventeen problems when it is ten, and a burn-down built from it would
            # mis-count the work. Required on blockers only — that is where the count gets quoted.
            if raw_item.get("status") != "covered" and raw_item.get("severity") == "P0":
                if not str(raw_item.get("root_cause") or "").strip():
                    raise ValueError(
                        f"{where} [{ref}]: a P0 row needs a `root_cause` slug so blockers that share "
                        "one defect are counted once"
                    )

            severity = raw_item.get("severity")
            if severity is not None and severity not in SEVERITIES:
                raise ValueError(f"{where} [{ref}]: severity must be one of {SEVERITIES}")
            if status == "covered" and severity:
                raise ValueError(f"{where} [{ref}]: a covered row must not carry a severity")

            if not str(raw_item.get("asks", "")).strip():
                raise ValueError(f"{where} [{ref}]: `asks` must state what the CCOF form asks")

            trazo = raw_item.get("trazo") or {}
            items.append(
                Item(
                    ref=ref,
                    asks=str(raw_item["asks"]).strip(),
                    status=status,
                    severity=severity,
                    gap=raw_item.get("gap"),
                    fix=raw_item.get("fix"),
                    reason=raw_item.get("reason"),
                    questions=_as_tuple(trazo.get("questions")),
                    triggered_by=_as_tuple(trazo.get("triggered_by")),
                    models=_as_tuple(trazo.get("models")),
                    prints=str(trazo.get("prints") or ""),
                    where=str(trazo.get("where") or "").strip(),
                    root_cause=str(raw_item.get("root_cause") or ""),
                    kind=kind,
                    optional=bool(raw_item.get("optional")),
                    scope_basis=scope_basis,
                    applies_when=applies_when,
                )
            )

        if not items:
            raise ValueError(f"{where}: form has no items")

        forms.append(
            Form(
                path=path,
                code=str(meta.get("code") or ""),
                title=str(meta["title"]),
                document_id=str(meta["document_id"]),
                revision=str(meta["revision"]),
                url=str(meta["url"]),
                retrieved=meta["retrieved"],
                pdf=str(meta.get("pdf") or ""),
                nop_cites=_as_tuple(meta.get("nop_cites")),
                guide_trigger=str(meta.get("guide_trigger") or ""),
                required_of_every_grower=bool(meta.get("required_of_every_grower")),
                trazo_modules=_as_tuple(meta.get("trazo_module")),
                packet_documents=_packet_documents(meta, where, certifier),
                **_filing_meta(meta, where),
                **_not_reproduced_meta(meta, where),
                **_not_served_meta(meta, where),
                register_status=register_status,
                source_sha256=str(meta.get("source_sha256") or ""),
                certifier=certifier,
                items=items,
            )
        )

    if not forms:
        raise ValueError(f"Certifier register holds no form files: {directory}")
    return forms


def load_unmapped(certifier: str | None = None) -> dict[str, str]:
    """`module_key.question_key` -> reason it has no CCOF counterpart.

    One file per module (`unmapped/<module_key>.yaml`) so that work on different CCOF forms never
    edits the same file.
    """
    if certifier is None:
        merged: dict[str, str] = {}
        for key in certifiers():
            merged.update(load_unmapped(key))
        return merged

    directory = unmapped_dir(certifier)
    if not directory.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text()) or {}
        for key, reason in (raw.get("questions") or {}).items():
            if not str(reason or "").strip():
                raise ValueError(f"{path.name}: {key} needs a reason, not an empty value")
            if not str(key).startswith(f"{path.stem}."):
                raise ValueError(
                    f"{path.name}: {key} belongs in {str(key).split('.')[0]}.yaml — "
                    "one file per module keeps parallel edits from colliding"
                )
            out[str(key)] = str(reason).strip()
    return out


def live_modules() -> tuple:
    """Every OSP module a farm actually answers.

    `MODULE_REGISTRY` is the farm-wide list; the Parcel Application is deliberately NOT in it
    because it is answered once per parcel and is served by its own branch of the module endpoint.
    Leaving it out here would exempt the largest CCOF form from every guard below — which is what
    happened on the first pass, and the register's 36 Parcel Application rows carried no validated
    citation at all until this was fixed.
    """
    from certifications.osp_modules import MODULE_REGISTRY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

    return tuple(MODULE_REGISTRY) + (PARCEL_APPLICATION,)


def live_question_keys() -> set[str]:
    """Every `module_key.question_key` a farm can answer, farm-wide and per-parcel."""
    return {
        f"{module.key}.{question.key}"
        for module in live_modules()
        for page in module.pages
        for question in page.questions
    }


def cited_question_keys(forms: list[Form]) -> set[str]:
    """Questions the register says ANSWER a form question — the reverse-coverage sense."""
    # A Trazo interpretation is not a form question, so citing a question there decides nothing
    # about what the agent asks; the question still needs a real row or an `unmapped/` reason.
    return {key for form in forms for item in form.items if item.kind != "interpretation" for key in item.questions}


def referenced_question_keys(forms: list[Form]) -> set[str]:
    """Every question key the register names, answering or triggering.

    Both must exist in the live registry; only `questions` counts as coverage.
    """
    return (
        cited_question_keys(forms)
        | {key for form in forms for item in form.items for key in item.triggered_by}
        | {cond[0] for form in forms for item in form.items for cond in item.applies_when}
    )


def summarize(forms: list[Form]) -> dict:
    """Counts for the generated statement. No ratio that reads as a self-assigned grade."""
    by_status = {status: 0 for status in STATUSES}
    by_severity = {severity: 0 for severity in SEVERITIES}
    by_kind = {kind: 0 for kind in ROW_KINDS}
    for form in forms:
        for item in form.items:
            by_kind[item.kind] += 1
            if item.kind != "question":
                continue
            by_status[item.status] += 1
            if item.severity:
                by_severity[item.severity] += 1
    draft_forms = [f for f in forms if f.register_status != "complete"]
    # 🔴 2026-09-07 — "41 forms, 472 questions, ZERO blockers" read as one uniformly reviewed
    # body of work. 20 of the 41 are DRAFT entries whose own per-form banner says "treat
    # absences as unreviewed, not as gaps", and reverse coverage does not run on them at all.
    # Publishing the total without the split states more review than happened, so the split is
    # DERIVED here and printed beside it rather than left to whoever quotes the number.
    return {
        "forms": len(forms),
        "items": sum(len(f.items) for f in forms),
        # Statuses count official questions only; instructions and interpretations are listed apart.
        "by_kind": by_kind,
        "by_status": by_status,
        "by_severity": by_severity,
        "complete_forms": sum(1 for f in forms if f.register_status == "complete"),
        "draft_forms": len(draft_forms),
        "draft_items": sum(len(f.items) for f in draft_forms),
    }


#: Prose shapes that are about OUR backlog, not about this operation's plan. Each one was
#: found printed on a real `04-coverage-and-scope.pdf`, not imagined.
_INTERNAL_PHRASES = (
    "not built",
    "no follow-up",
    "unrepresented",
    "no trigger",
    "not yet built",
    "no representation",
    "open product decision",
    "would become a",
    "trazo has no",
)

#: How each registered agent's own name and form identifiers look. A certifier's coverage page
#: must not carry ANOTHER agent's — `certifier` already scopes the ROWS, this scopes the PROSE
#: inside them.
#:
#: ⛔ Derived, never hand-listed per certifier. The first version of this was
#: `{"ccof": ("AGR 2", "WSDA"), "wsda": ("NOPB", "CCOF")}`, which gives a THIRD certifier an
#: empty tuple and therefore no check at all — the same "knows about two of three" off-by-one
#: that keeps recurring here. `test_every_registered_certifier_declares_its_markers` fails when
#: a new agent is registered without adding its row, so the gap is loud instead of silent.
_CERTIFIER_MARKERS = {
    "ccof": ("CCOF", "ORGB", "NOPB"),
    "wsda": ("WSDA", "AGR 2"),
    # OTCO codes its sections C2…C14 — too short to be a safe marker, so the agent's names are the
    # markers. "FACT-04" is the one coded form whose token is distinctive enough to add.
    "otco": ("OTCO", "Oregon Tilth", "FACT-04"),
}


def foreign_markers(certifier: str) -> tuple[str, ...]:
    """Identifiers belonging to some OTHER agent than `certifier`."""
    own = set(_CERTIFIER_MARKERS.get(certifier, ()))
    every = {marker for markers in _CERTIFIER_MARKERS.values() for marker in markers}
    return tuple(sorted(every - own))


def _reject_internal_language(certifier: str, form: str, reason: str) -> None:
    """Raise unless `reason` is prose a certifying agent may read as-is."""
    where = f"{certifier}/scope.yaml [{form}]"
    if "`" in reason:
        raise ValueError(
            f"{where}: `reason` is printed to the certifier — a backtick-quoted identifier is "
            f"ours, not theirs. Put it in `note`."
        )
    lowered = reason.lower()
    for phrase in _INTERNAL_PHRASES:
        if phrase in lowered:
            raise ValueError(
                f"{where}: `reason` reads as our backlog ({phrase!r}), not as this operation's "
                f"scope. State what the operation does about the form; put the debt in `note`."
            )
    for marker in foreign_markers(certifier):
        if marker.lower() in lowered:
            raise ValueError(
                f"{where}: `reason` names another certifying agent or its forms ({marker!r}). "
                f"This prose is printed on {certifier.upper()}'s own coverage page. Put the "
                f"cross-reference in `note`."
            )


@dataclass
class ScopeEntry:
    """A certifier's form Trazo does not register, and why.

    `decision` and `gap` are kept apart deliberately: a decision is an answer, a gap is a debt. A
    file that let them blur would be the thing it exists to prevent — an absence presented as a
    choice.

    `certifier` is load-bearing, not bookkeeping: the renewal packet's coverage page is addressed
    to ONE agent, and `load_scope()` with no argument returns every registered agent's entries.
    Without this field the page had no way to tell them apart, so a CCOF packet listed WSDA's
    AGR 2180/2523/2524 among the forms "this packet does not cover".

    🔴 2026-09-07 — `reason` IS CERTIFIER-FACING PROSE. `osp_module_pdf` renders it verbatim onto
    `04-coverage-and-scope.pdf`, so a reason written as a backlog note is published to the agent:
    the CCOF page carried "Not built and not triggered: `G7.0`'s `buyer_label` option has no
    follow-up", and the WSDA page carried CCOF's own form numbers plus "which IS a real
    grower-side trigger and remains unrepresented in Trazo". The per-row certifier scoping was
    fixed on 2026-09-06; the leak survived inside the prose the rows carry.

    `note` is the internal half and is NEVER rendered. Backlog language, our own question keys,
    another agent's form identifiers and anything phrased as a debt belong there.
    """

    form: str
    disposition: str
    reason: str
    document_id: str = ""
    triggered_from: str = ""
    certifier: str = ""
    note: str = ""  # internal only — never printed to a certifier
    #: One of RENEWAL_ROLES when the excluded form is part of the agent's renewal, so the renewal
    #: supplement can name it even though it has no register file (WSDA's renewal application is
    #: not published as a blank form).
    renewal_role: str = ""


def load_scope(certifier: str | None = None) -> list[ScopeEntry]:
    if certifier is None:
        out: list[ScopeEntry] = []
        for key in certifiers():
            out.extend(load_scope(key))
        return out

    path = scope_path(certifier)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    entries: list[ScopeEntry] = []
    for item in raw.get("forms") or []:
        form = str(item.get("form", "")).strip()
        if not form:
            raise ValueError(f"{certifier}/scope.yaml: an entry has no `form`")
        disposition = item.get("disposition")
        if disposition not in DISPOSITIONS:
            raise ValueError(f"{certifier}/scope.yaml [{form}]: disposition must be one of {DISPOSITIONS}")
        reason = str(item.get("reason", "")).strip()
        if not reason:
            raise ValueError(f"{certifier}/scope.yaml [{form}]: an excluded form needs a stated reason")
        # 🔴 2026-09-07 — `reason` is published verbatim to the certifying agent, so the
        # sanitising happens HERE, at the source, not in the renderer. A claim filtered by its
        # reader is still on the wire, and the packet test's five-term denylist ("P0", "P1",
        # "blocker", "root_cause", "not_covered") matched none of what actually leaked: a
        # backtick-quoted Trazo question key, our own backlog phrasing, and — on the WSDA page —
        # CCOF's form numbers. Internal detail goes in `note`, which nothing renders.
        _reject_internal_language(certifier, form, reason)
        renewal_role = str(item.get("renewal_role") or "")
        if renewal_role and renewal_role not in RENEWAL_ROLES:
            raise ValueError(f"{certifier}/scope.yaml [{form}]: renewal_role must be one of {RENEWAL_ROLES}")
        if disposition == "gap" and not str(item.get("triggered_from", "")).strip():
            raise ValueError(
                f"{certifier}/scope.yaml [{form}]: a gap must say where it is triggered from, "
                "otherwise it cannot be prioritised against anything"
            )
        entries.append(
            ScopeEntry(
                form=form,
                disposition=disposition,
                reason=reason,
                document_id=str(item.get("document_id") or ""),
                triggered_from=str(item.get("triggered_from") or ""),
                certifier=certifier,
                note=str(item.get("note") or "").strip(),
                renewal_role=renewal_role,
            )
        )
    return entries


@dataclass
class PublishedForm:
    """A form the certifying agent publishes, as read from the agent's own page."""

    document_id: str
    form: str
    revision: str = ""
    certifier: str = ""


def published_inventory_path(certifier: str) -> Path:
    return REGISTER_DIR / certifier / "published_inventory.yaml"


def load_published_inventory(certifier: str | None = None) -> list[PublishedForm]:
    """What the agent publishes — the outside edge the register is measured against.

    🔴 2026-09-07. `forms/` says what we registered and `scope.yaml` says what we deliberately
    did not, and NOTHING said what the agent actually publishes — so a form could be in neither
    and no guard could tell. Seven were, including AGR 2519, which five register rows quote by
    name as the attachment WSDA demands.

    Returns [] when a certifier has no inventory file yet, so registering a new agent is not
    blocked on transcribing its whole catalogue first; `certifiers_missing_inventory()` is what
    keeps that from being permanent.
    """
    if certifier is None:
        out: list[PublishedForm] = []
        for key in certifiers():
            out.extend(load_published_inventory(key))
        return out

    path = published_inventory_path(certifier)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or {}
    entries = []
    for item in raw.get("forms") or []:
        document_id = str(item.get("document_id", "")).strip()
        form = str(item.get("form", "")).strip()
        if not document_id or not form:
            raise ValueError(f"{certifier}/published_inventory.yaml: every entry needs `document_id` and `form`")
        entries.append(
            PublishedForm(
                document_id=document_id,
                form=form,
                revision=str(item.get("revision") or ""),
                certifier=certifier,
            )
        )
    return entries


def certifiers_missing_inventory() -> list[str]:
    """Registered agents with no `published_inventory.yaml` — the guard cannot see their edge."""
    return [key for key in certifiers() if not published_inventory_path(key).exists()]


def unaccounted_published_forms(certifier: str) -> list[PublishedForm]:
    """Published forms that are in neither `forms/` nor `scope.yaml` — the silent holes.

    Matched on `document_id`, which is the agent's own identifier and the only token that is
    stable across our renamings of a form's title.
    """
    registered = {f.document_id.strip() for f in load_forms(certifier) if f.document_id}
    excluded = {e.document_id.strip() for e in load_scope(certifier) if e.document_id}
    accounted = registered | excluded
    return [f for f in load_published_inventory(certifier) if f.document_id.strip() not in accounted]


def blockers_by_root_cause(forms: list[Form]) -> dict[str, list[tuple[Form, Item]]]:
    """P0 rows grouped by the defect behind them — the burn-down view.

    The count that matters is DEFECTS, not rows: fixing the materials-list model closes four rows
    across two certifiers at once. Do not hard-code either number here — an earlier version of this
    docstring said "seventeen rows across ten defects" and was still saying it after two rounds of
    fixes and a second certifier. `summarize()` derives both.
    """
    grouped: dict[str, list[tuple[Form, Item]]] = {}
    for form in forms:
        for item in form.items:
            if item.severity == "P0":
                grouped.setdefault(item.root_cause or item.ref, []).append((form, item))
    return dict(sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])))


def cross_certifier_conflicts(forms: list[Form]) -> dict[str, dict[str, list[str]]]:
    """Trazo questions two certifiers describe incompatibly.

    CCOF and WSDA overlay the same federal content, so most of their questions ask the same
    obligation of the same Trazo question. `covered` for one certifier and `not_covered` for
    another is therefore a contradiction about the product, not a difference between the forms:
    either the fact is capturable and printable or it is not.

    `partial` alongside `covered` is NOT a conflict — one certifier legitimately asks for more
    depth than another, and flattening that would push people to overstate the weaker one.

    Returns {question_key: {status: [where it is claimed]}} for the conflicting questions only.
    """
    seen: dict[str, dict[str, list[str]]] = {}
    for form in forms:
        for item in form.items:
            for key in item.questions:
                where = f"{form.certifier}:{form.code or form.title} {item.ref}"
                seen.setdefault(key, {}).setdefault(item.status, []).append(where)

    return {key: statuses for key, statuses in seen.items() if "covered" in statuses and "not_covered" in statuses}


def question_keys_hidden_in_models(forms: list[Form]) -> list[str]:
    """`trazo.models` entries that are really `module_key.question_key` citations.

    `models` is free text and `cited_question_keys()` reads only `questions`, so a real question
    key parked in `models` is validated by nothing and counts toward no coverage. THIRTEEN rows
    did exactly that when this guard first ran — an adversarial re-read had spotted three, which
    is the usual relationship between reading and checking. Several carried a parenthetical
    explaining why the key was not in `questions`: they were dodging the cited-vs-unmapped guard,
    which at the time compared the two ACROSS certifiers and so called a legitimate WSDA citation
    a contradiction. That guard is scoped per certifier now, which removes the reason to hide
    anything; this closes the hiding place.

    Found 2026-08-28: `broken_model_references()` skips any ref containing a space, and every one
    of these carried its excuse inline. Each comma-separated segment is checked, because the rows
    that did this joined two keys in one string.
    """
    live = live_question_keys()
    hidden: list[str] = []
    for form in forms:
        for item in form.items:
            for raw in item.models:
                for segment in raw.split("(")[0].split(","):
                    candidate = segment.strip().rstrip(".")
                    if candidate in live and candidate not in item.questions:
                        hidden.append(f"{form.certifier}:{form.code or form.document_id} {item.ref} -> {candidate}")
    return hidden


def broken_model_references(forms: list[Form]) -> list[str]:
    """`trazo.models` entries that name a Django field or property which does not exist.

    Unlike `trazo.questions`, this field is free text — it has to be, because a location is
    sometimes a service module, a frontend component or a workbook rather than a model attribute.
    That freedom let fabricated names in: seven register rows cited cleanout fields on
    `history.EquipmentEvent`, which records equipment name, type, fuel and hours and has no
    cleaning fields at all. The fields were real, on `history.ProductionEvent` — so the rows
    described the product from the wrong model, under the defect that tops the roadmap.

    Only strict `app.Model.field` / `app.models.Model.field` refs are checked. Anything with a
    space, a slash or fewer than three segments is prose or a non-Django location and is skipped
    rather than guessed at; a trailing "(note)" is stripped first. Properties count as fields —
    `PostHarvestFacility.cert_is_current` is a computed tri-state, not a column.
    """
    from django.apps import apps

    broken: list[str] = []
    for form in forms:
        for item in form.items:
            for raw in item.models:
                ref = raw.split("(")[0].strip().rstrip(".")
                if " " in ref or "/" in ref:
                    continue
                parts = [p for p in ref.split(".") if p != "models"]
                if len(parts) != 3 or not parts[1][:1].isupper():
                    continue
                app_label, model_name, attr = parts
                try:
                    model = apps.get_model(app_label, model_name)
                except Exception:  # noqa: BLE001 — an unknown app/model is not necessarily ours
                    continue
                names = {f.name for f in model._meta.get_fields()}
                names |= {getattr(f, "attname", "") for f in model._meta.get_fields()}
                if attr not in names and not hasattr(model, attr):
                    broken.append(f"{form.certifier}:{form.code or form.document_id} {item.ref} -> {ref}")
    return broken
