"""
Guided OSP module definitions — the frozen schema.

## What this is

Each Common-OSP-style module (G3.0 Seeds, G4.0 Rotation & Soil, ...) is defined as a tree of
frozen dataclasses in one Python file under `certifications/osp_modules/`. Python is the single
source of truth: the server must validate required-if-visible questions and completion (a
certifier-bound artifact cannot trust the client), and the per-module PDFs are ReportLab — both
need these definitions. The frontend receives them serialized as JSON from the
`module-definitions` endpoint and renders the wizard from that payload; it never carries its own
copy of question content.

This is the same regulatory-content class as `common_osp_records.RecordType` and
`common_osp_workbooks.Workbook`: frozen dataclasses, real CFR citations required on the module,
and no entry added merely because a competitor has a screen for it.

## Content rules (hard)

- Education text and question labels are AUTHORED for Trazo from the primary sources (eCFR
  7 CFR part 205, the USDA Common OSP template structure, NOP handbook). Never copied from any
  competitor's rendering. Structure and topic order may follow the public Common OSP; wording is
  ours.
- Every module carries `nop_cites` (e.g. "§ 205.204"). Citations are authored constants used
  for rendering only — nothing here resolves National List citations by matching (the no-fuzzy
  red line lives in `national_list_aliases.py` and applies to this file too).
- All user-visible text is a TextMap carrying BOTH locales: {"en": ..., "es": ...}. Module
  content deliberately does NOT go through the react-intl catalogs — 15+ modules of long-form
  prose would bloat both 5,500-line catalog files and split one module's content across three
  files. PDFs render EN (certifier-facing, consistent with every existing PDF).

## Answers are the operator's, never Trazo's

Definitions may declare a `prefill` source so the UI can SUGGEST an answer derived from the
farm's own records ("Suggested from 14 logged spray events"). A suggestion is rendered with an
explicit Accept/Dismiss and is written into `module_responses` only by the operator's accept —
the same suggested-vs-confirmed split as `common_osp_records.confirm()`. Nothing in this package
writes answers.

## Deviation from the design memo, documented

The memo sketched a ConditionGroup with any_of/all_of composition. Shipped v1 uses a plain
tuple of Conditions with AND semantics (`visible_when=(c1, c2)` means c1 AND c2): every
branching rule observed in the Common OSP / CCOF forms is driven by a single answer, OR
composition had no real use case, and a smaller contract keeps the backend and frontend
evaluators trivially provable against the shared golden fixture. If OR is ever needed, add a
new dataclass rather than overloading this one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

# A TextMap is {"en": str, "es": str}. Both keys are REQUIRED on every user-visible
# string — the i18n-parity rule applies to module content exactly as it does to
# catalog keys, and the registry test suite enforces it.
TextMap = Mapping[str, str]

LOCALES = ("en", "es")


def text(en: str, es: str) -> dict:
    """Build a TextMap. Positional to keep module files compact."""
    return {"en": en, "es": es}


# ---------------------------------------------------------------------------
# Branching
# ---------------------------------------------------------------------------

CONDITION_OPS = ("eq", "ne", "includes", "includes_any", "one_of", "not_includes", "truthy", "falsy")


@dataclass(frozen=True)
class Condition:
    """One branching predicate against a previously-answered question.

    Semantics (mirrored exactly by `src/config/osp/conditionEval.ts`; the two are kept
    honest by the golden fixture exported via `manage.py export_osp_module_fixture`):

      eq / ne            — answer == value / answer != value
      includes           — value in answer (answer is a checkbox_group list)
      one_of             — scalar answer is one of value (a list); false when
                           unanswered — the radio counterpart of includes_any
      includes_any       — any of value (a list) in answer; the POSITIVE trigger op —
                           false while unanswered, so conditional pages stay hidden
                           until the trigger question is actually answered
      not_includes       — value not in answer; deliberately TRUE while unanswered
                           (use for carve-outs on already-visible content, never as a
                           page trigger — an unanswered farmer would see the page)
      truthy / falsy     — bool(answer) with None/[]/"" all falsy

    A tuple of Conditions is AND — all must pass. Questions whose `visible_when` fails
    are hidden AND exempt from `required` (required-if-visible).
    """

    question: str
    op: str
    value: Any = None


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

# Kinds the wizard runner knows how to render. "info" renders education text with no
# input. "upload" renders a file-drop; in v1 (pre-WS-3 storage wiring) uploads are
# collected but not required-validated — completion validation skips them, documented
# in `conditions.missing_required`.
QUESTION_KINDS = (
    "radio",
    "checkbox_group",
    "boolean",
    "text",
    "textarea",
    "date",
    "select",
    "info",
    "upload",
)


@dataclass(frozen=True)
class Option:
    """One choice in a radio / checkbox_group / select question.

    `exclusive=True` marks a none-of-the-above style option ("None used",
    "Not applicable...") that the UI unchecks the others for. The evaluator treats an
    exclusive selection as the only value present.
    """

    value: str
    label: TextMap
    exclusive: bool = False
    #: Kept only so an answer given before the option was replaced still reads as it was given
    #: (stored plans, regenerated PDFs of submitted ones). Never offered for a new answer, and an
    #: answer made only of retired options counts as unanswered until the operator confirms one of
    #: the current options: the replacement asks something the old option never did.
    retired: bool = False
    #: An English sentence printed as a [REVIEW] line under the answer when this option is chosen:
    #: what the certifier should look at, never a verdict. For answers the operator gives honestly
    #: but cannot vouch for ("believed, not yet confirmed in writing").
    review: str = ""
    #: The key of an `upload` question in the same module that this option says holds a file
    #: ("SOP attached"). When chosen and no file is filed to that question, the module PDF prints
    #: a [REVIEW] line instead of letting the answer claim an attachment that is not there.
    requires_upload: str = ""
    #: A key of `common_osp_records.ANSWER_EVIDENCE`. When chosen, the module PDF prints how many
    #: records of that kind are logged in Trazo under the answer ("2 cleaning records for harvest
    #: bins or totes logged"), or that none are. A count, never a verdict on the records.
    evidence: str = ""


@dataclass(frozen=True)
class Prefill:
    """Declares that this question's answer can be SUGGESTED from farm records.

    `source` is a registered resolver key (resolved server-side at module GET time into
    {value, basis, count}); it is never resolved client-side and never auto-written.
    """

    source: str


@dataclass(frozen=True)
class CompileRule:
    """How an answered question contributes to the six § 205.201(a) narratives.

    `template` is an EN sentence with `{answer}` interpolated by the WS-2.3 compiler
    (deterministic template-fill — no generation). `section_key` overrides the module's
    `default_section_key` when a single module feeds two sections (e.g. G5.0 practices
    → (a)(1) but its monitoring questions → (a)(3)).
    """

    template: str
    section_key: Optional[str] = None
    # For a boolean whose template states the Yes reading ("The operator states that no fertilizer is
    # used ({answer})"): the sentence a No compiles to. Without it a No printed the Yes statement with
    # "(No)" after it, a statement the operator never made (production specimen packet, 2026-10-29).
    template_false: Optional[str] = None


@dataclass(frozen=True)
class Question:
    key: str
    kind: str
    label: TextMap
    # Inline definition/coaching shown under the label (the 'Mark "with treatment"
    # if...' pattern) — optional.
    coaching: Optional[TextMap] = None
    options: tuple = ()
    # Enforced only when visible — see Condition docstring.
    required: bool = True
    visible_when: tuple = ()
    # Citation string rendered next to the question (e.g. "§ 205.204(a)(1)").
    nop_cite: Optional[str] = None
    prefill: Optional[Prefill] = None
    compiles_to: Optional[CompileRule] = None
    # Binding to a real model field for the per-parcel module (Appendix A §f) —
    # answers for bound questions are routed through ParcelSerializer, not stored in
    # module_responses.
    parcel_field: Optional[str] = None
    # Binding to an `Establishment` column for a farm-wide module. Unlike `parcel_field`
    # the answer IS still stored in `module_responses` (the OSP is the record a certifier
    # reads); the column is kept in step by a WRITE-THROUGH in `OSPViewSet.module_detail`
    # so a regulated fact has ONE editor.
    #
    # 🔴 2026-08-21 (F25) — `Establishment.has_split_operation` (a farm-profile checkbox)
    # and this module's `split_operation` answer recorded the same § 205.201(a)(5) fact
    # with nothing binding them, so a farm that answered "yes, we sell the buffer rows
    # conventional" in the OSP still filed a packet whose § 205.272 row read
    # "Split Operation: No" — followed by a REVIEW telling the operator the two statements
    # in their own packet disagree. The export was taught to prefer the OSP answer, which
    # removed the contradiction from the document; this binding removes the divergence at
    # the source. The column stays because the packet, the "declares split but files no
    # separation plan" check and `seed_osp_template` all read it.
    establishment_field: Optional[str] = None
    # Embeds an existing panel as this question's body. v1 embeds:
    #   "s11_record_types" — the Common OSP § 11 registry panel (G8.0)
    #   "approved_inputs"  — the ApprovedInputs flow (Materials Application, later)
    embed: Optional[str] = None
    #: This question is the operator vouching for the contents of an embed rendered above it
    #: (the embed's name). It cannot be answered affirmatively while that embed is empty —
    #: see certifications/services/attestation_gates.py for why that is a server rule and not
    #: a UI courtesy.
    attests_embed: Optional[str] = None
    placeholder: Optional[TextMap] = None
    max_length: Optional[int] = None
    #: A question REPLACED by others that ask more (the `Option.retired` idea, for a whole question). It is shown
    #: only while it holds an answer, so a plan that answered it keeps reading it as given and printing it, and
    #: no plan is asked it anew. G5.0's untyped practice lists, retired 2026.11.22 for four lists by pest type.
    retired: bool = False


@dataclass(frozen=True)
class ModulePage:
    """One wizard step — one lettered sub-section of the source form."""

    key: str
    title: Optional[TextMap] = None
    # Plain-language regulation summaries shown above the questions ("► ..." blocks).
    education: tuple = ()
    questions: tuple = ()
    visible_when: tuple = ()


@dataclass(frozen=True)
class Module:
    key: str
    # Display code from the Common OSP taxonomy ("G3.0"). Empty for non-coded modules
    # (Certification Contract, Materials Application).
    code: str
    title: TextMap
    # Citation strings for the header card, e.g. ("§ 205.2", "§ 205.204", "§ 205.105").
    nop_cites: tuple
    education: tuple = ()
    # Whether the module offers the top-level "Not applicable — reviewed and does not
    # apply" attestation. When the operator sets it, question validation is skipped and
    # the compiler emits one attested N/A line. The attestation is stamped (who/when)
    # in module_responses — it is an explicit operator statement, never a default.
    allows_not_applicable: bool = True
    na_label: Optional[TextMap] = None
    pages: tuple = ()
    # One of certifications.models.OSP_SECTION_KEYS — where this module's compiled
    # narrative lands by default.
    default_section_key: str = "practices_procedures"
    repeat_per_parcel: bool = False


# ---------------------------------------------------------------------------
# Validation (called by the registry test suite for every module)
# ---------------------------------------------------------------------------


def _check_textmap(value, where: str, errors: list) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        errors.append(f"{where}: TextMap must be a mapping, got {type(value).__name__}")
        return
    for locale in LOCALES:
        if not (value.get(locale) or "").strip():
            errors.append(f"{where}: missing '{locale}' text")


def validate_module(module: Module, section_keys: tuple) -> list:
    """Return a list of definition errors (empty = valid).

    Enforced invariants:
      - module has code-or-title, at least one citation, and a real section key
      - question keys are unique within the module
      - every visible_when references a question DEFINED EARLIER in the module
        (branching can only look backwards — matches the wizard's page order)
      - every citation string looks like a § 205.x citation
      - choice questions have options; non-choice questions have none
      - every TextMap carries both locales
      - compile targets are real section keys
    """
    errors: list = []
    where = f"module '{module.key}'"

    if not module.nop_cites:
        errors.append(f"{where}: at least one NOP citation required")
    for cite in module.nop_cites:
        if "205." not in cite or "§" not in cite:
            errors.append(f"{where}: citation '{cite}' must be a '§ 205.x' string")
    if module.default_section_key not in section_keys:
        errors.append(f"{where}: default_section_key '{module.default_section_key}' not in OSP_SECTION_KEYS")
    _check_textmap(module.title, f"{where} title", errors)
    if module.allows_not_applicable and module.na_label is not None:
        _check_textmap(module.na_label, f"{where} na_label", errors)
    for block in module.education:
        _check_textmap(block, f"{where} education", errors)

    seen_keys: list = []
    for page in module.pages:
        pwhere = f"{where} page '{page.key}'"
        _check_textmap(page.title, f"{pwhere} title", errors)
        for block in page.education:
            _check_textmap(block, f"{pwhere} education", errors)
        for cond in page.visible_when:
            if cond.op not in CONDITION_OPS:
                errors.append(f"{pwhere}: unknown condition op '{cond.op}'")
            if cond.question not in seen_keys:
                errors.append(f"{pwhere}: visible_when references undefined/later question '{cond.question}'")
            if cond.op in ("eq", "ne", "includes", "not_includes") and cond.value is None:
                errors.append(f"{pwhere}: op '{cond.op}' requires a value")
            if cond.op == "includes_any" and not isinstance(cond.value, (list, tuple)):
                errors.append(f"{pwhere}: op 'includes_any' requires a list value")
            if cond.op == "one_of" and not isinstance(cond.value, (list, tuple)):
                errors.append(f"{pwhere}: op 'one_of' requires a list value")
        for q in page.questions:
            qwhere = f"{pwhere} question '{q.key}'"
            if q.key in seen_keys:
                errors.append(f"{qwhere}: duplicate question key")
            if q.kind not in QUESTION_KINDS:
                errors.append(f"{qwhere}: unknown kind '{q.kind}'")
            _check_textmap(q.label, f"{qwhere} label", errors)
            _check_textmap(q.coaching, f"{qwhere} coaching", errors)
            _check_textmap(q.placeholder, f"{qwhere} placeholder", errors)
            if q.kind in ("radio", "checkbox_group", "select"):
                if not q.options:
                    errors.append(f"{qwhere}: choice question needs options")
            elif q.options:
                errors.append(f"{qwhere}: kind '{q.kind}' must not carry options")
            option_values = [o.value for o in q.options]
            if len(option_values) != len(set(option_values)):
                errors.append(f"{qwhere}: duplicate option values")
            for o in q.options:
                _check_textmap(o.label, f"{qwhere} option '{o.value}'", errors)
            for cond in q.visible_when:
                if cond.op not in CONDITION_OPS:
                    errors.append(f"{qwhere}: unknown condition op '{cond.op}'")
                if cond.question not in seen_keys:
                    errors.append(f"{qwhere}: visible_when references undefined/later question '{cond.question}'")
                if cond.op in ("eq", "ne", "includes", "not_includes") and cond.value is None:
                    errors.append(f"{qwhere}: op '{cond.op}' requires a value")
                if cond.op == "includes_any" and not isinstance(cond.value, (list, tuple)):
                    errors.append(f"{qwhere}: op 'includes_any' requires a list value")
                if cond.op == "one_of" and not isinstance(cond.value, (list, tuple)):
                    errors.append(f"{qwhere}: op 'one_of' requires a list value")
            if q.compiles_to and q.compiles_to.section_key and q.compiles_to.section_key not in section_keys:
                errors.append(f"{qwhere}: compiles_to section '{q.compiles_to.section_key}' not in OSP_SECTION_KEYS")
            if q.kind == "info" and q.required:
                errors.append(f"{qwhere}: info questions must be required=False")
            seen_keys.append(q.key)

    # An option's `requires_upload` must name an upload question of this module, or the PDF's
    # check would look for a file under a requirement nothing can ever be filed to.
    uploads = {q.key for page in module.pages for q in page.questions if q.kind == "upload"}
    for page in module.pages:
        for q in page.questions:
            for o in q.options:
                if o.requires_upload and o.requires_upload not in uploads:
                    errors.append(
                        f"{where} question '{q.key}' option '{o.value}': requires_upload "
                        f"'{o.requires_upload}' is not an upload question of this module"
                    )

    if not seen_keys and not module.allows_not_applicable:
        errors.append(f"{where}: no questions and no N/A attestation — module can never complete")
    return errors


# ---------------------------------------------------------------------------
# Serialization (what the module-definitions endpoint returns)
# ---------------------------------------------------------------------------


def _serialize_condition(c: Condition) -> dict:
    return {"question": c.question, "op": c.op, "value": c.value}


def _serialize_option(o: Option) -> dict:
    out = {"value": o.value, "label": dict(o.label), "exclusive": o.exclusive}
    # Only when set, so the payload of every option that was never retired stays as it was.
    if o.retired:
        out["retired"] = True
    return out


def _serialize_question(q: Question) -> dict:
    return {
        "key": q.key,
        "kind": q.kind,
        "label": dict(q.label),
        "coaching": dict(q.coaching) if q.coaching else None,
        "options": [_serialize_option(o) for o in q.options],
        "required": q.required,
        "visible_when": [_serialize_condition(c) for c in q.visible_when],
        "nop_cite": q.nop_cite,
        "prefill": {"source": q.prefill.source} if q.prefill else None,
        "parcel_field": q.parcel_field,
        "establishment_field": q.establishment_field,
        "embed": q.embed,
        "placeholder": dict(q.placeholder) if q.placeholder else None,
        "max_length": q.max_length,
        # Only when set, so the payload of every question never retired stays as it was.
        **({"retired": True} if q.retired else {}),
    }


def serialize_module(m: Module) -> dict:
    return {
        "key": m.key,
        "code": m.code,
        "title": dict(m.title),
        "nop_cites": list(m.nop_cites),
        "education": [dict(b) for b in m.education],
        "allows_not_applicable": m.allows_not_applicable,
        "na_label": dict(m.na_label) if m.na_label else None,
        "default_section_key": m.default_section_key,
        "repeat_per_parcel": m.repeat_per_parcel,
        "pages": [
            {
                "key": p.key,
                "title": dict(p.title) if p.title else None,
                "education": [dict(b) for b in p.education],
                "visible_when": [_serialize_condition(c) for c in p.visible_when],
                "questions": [_serialize_question(q) for q in p.questions],
            }
            for p in m.pages
        ],
    }
