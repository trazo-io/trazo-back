"""
Whether THIS plan answers each question on a certifying agent's form.

The conformance register says where Trazo would answer a form question (`questions:` on each
item). That is a mapping, not an answer. The coverage page used to list a form as "generated" the
moment a module mapped to it, without reading one answer, so an operation that had filled in
nothing received a page telling its certifier that every form was in the packet (OSP alignment
audit 2026-10, T15). This module reads the operator's answers for each register item and says
what the packet can honestly claim about it.

The states are evidence states, not a grade. They are never totalled into a ratio or a
percentage; the page names the questions that are still open.

    answered                   every cited question is answered, and the register row is `covered`
    not_applicable             the question is hidden, and every trigger that hides it is answered
                               (the evidence is kept), or the module carries a recorded N/A
                               attestation
    partial                    every cited question is answered, but the register row itself is
                               `partial`: Trazo collects only part of what the form asks
    not_collected              the register row is `not_covered`: Trazo has nowhere to record it
    unanswered                 a visible cited question has no answer
    unresolved                 a cited question is hidden only because a question that decides
                               whether it applies has not been answered, so nobody has said it
                               does not apply
    attachment_missing         the form asks for a file and none is uploaded to that section
    attachment_not_identified  files are uploaded to that section, but none is linked to THIS
                               requirement (uploads are linked by section, not by question), and
                               none of them rides in the packet
    not_assessed               the register row names no answering question (models or printed
                               output only), so nothing here can say it is answered
    unknown_reference          the register cites a question that does not exist today

Only `answered` and `not_applicable` close a row. Everything else is open.
"""

from __future__ import annotations

from dataclasses import dataclass

#: States that close a register row. Anything else is listed as open on the coverage page.
CLOSED_STATES = frozenset({"answered", "not_applicable"})

#: Worst state wins when a row cites several questions (or one question across several parcels).
_SEVERITY = (
    "unknown_reference",
    "attachment_missing",
    "attachment_not_identified",
    "unresolved",
    "unanswered",
    "not_assessed",
    "answered",
    "not_applicable",
)


@dataclass(frozen=True)
class RowState:
    ref: str
    state: str
    #: Evidence for the state: the trigger answers that make a question not apply, or the
    #: requirement an attachment is missing for. Plain text, safe to print.
    detail: str = ""

    @property
    def is_open(self) -> bool:
        return self.state not in CLOSED_STATES


def _worst(states: list[tuple[str, str]]) -> tuple[str, str]:
    """(state, detail) with the highest severity; ties keep the first detail."""
    order = {s: i for i, s in enumerate(_SEVERITY)}
    return min(states, key=lambda pair: order.get(pair[0], 0))


def _question_and_page(module, question_key):
    for page in module.pages:
        for question in page.questions:
            if question.key == question_key:
                return page, question
    return None, None


def question_state(module, question_key: str, answers: dict, *, na_attested: bool, section_uploads: int):
    """(state, detail) for one question of one module against one set of answers."""
    from certifications.osp_modules.conditions import answer_value, conditions_pass, is_answered

    page, question = _question_and_page(module, question_key)
    if question is None:
        return "unknown_reference", question_key
    if na_attested and module.allows_not_applicable:
        return "not_applicable", "the operation attested this section does not apply"
    if question.kind == "info":
        return "not_assessed", ""

    conditions = tuple(page.visible_when) + tuple(question.visible_when)
    visible = conditions_pass(conditions, answers)
    # A trigger is the question a condition reads. Its answer is the evidence that decides
    # whether the question applies, so an unanswered trigger decides nothing.
    open_triggers = [c.question for c in conditions if not is_answered(answer_value(answers, c.question))]

    if not visible:
        if open_triggers:
            return "unresolved", ", ".join(sorted(set(open_triggers)))
        evidence = "; ".join(f"{c.question} = {answer_value(answers, c.question)!r}" for c in conditions)
        return "not_applicable", evidence

    if question.kind == "upload":
        label = question.label.get("en", question_key) if isinstance(question.label, dict) else str(question.label)
        return ("attachment_not_identified" if section_uploads else "attachment_missing"), label

    if is_answered(answer_value(answers, question_key)):
        return "answered", ""
    return "unanswered", ""


class _Answers:
    """The operator's answers for one plan, read once per coverage page."""

    def __init__(self, osp):
        from certifications.osp_modules import MODULES_BY_KEY
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

        self.osp = osp
        self.modules = dict(MODULES_BY_KEY)
        self.modules[PARCEL_APPLICATION.key] = PARCEL_APPLICATION
        self.parcel_key = PARCEL_APPLICATION.key
        self.responses = (osp.module_responses or {}).get("modules", {}) or {}
        self._uploads: dict[str, int] | None = None
        self._parcels: list | None = None

    def uploads(self, module_key: str) -> int:
        if self._uploads is None:
            from django.db.models import Count

            from documents.models import GeneratedDocument

            rows = (
                GeneratedDocument.objects.filter(establishment_id=self.osp.establishment_id, source="upload")
                .exclude(linked_section="")
                .values("linked_section")
                .annotate(n=Count("id"))
            )
            self._uploads = {row["linked_section"]: row["n"] for row in rows}
        return self._uploads.get(module_key, 0)

    def parcels(self) -> list:
        if self._parcels is None:
            from product.services.parcel_application_status import parcel_application_values

            parcels = self.osp.establishment.parcels.order_by("id")
            self._parcels = [(parcel.name, parcel_application_values(parcel)) for parcel in parcels]
        return self._parcels

    def state_of(self, cited_key: str) -> tuple[str, str]:
        module_key, _, question_key = cited_key.partition(".")
        module = self.modules.get(module_key)
        if module is None or not question_key:
            return "unknown_reference", cited_key
        if module_key == self.parcel_key:
            parcels = self.parcels()
            if not parcels:
                return "unanswered", "no parcel is recorded"
            return _worst(
                [
                    question_state(module, question_key, values, na_attested=False, section_uploads=0)
                    for _name, values in parcels
                ]
            )
        entry = self.responses.get(module_key) or {}
        # A module N/A closes its questions only with the attestation that says who made it.
        na_attested = bool(entry.get("not_applicable")) and bool(entry.get("na_attestation"))
        return question_state(
            module,
            question_key,
            entry.get("answers") or {},
            na_attested=na_attested,
            section_uploads=self.uploads(module_key),
        )


def row_answer_state(answers: _Answers, item) -> RowState | None:
    """The state of one register item for this plan. None for an out-of-scope row."""
    if item.status == "out_of_scope":
        return None
    if item.status == "not_covered":
        return RowState(item.ref, "not_collected")
    if not item.questions:
        return RowState(item.ref, "not_assessed")
    state, detail = _worst([answers.state_of(key) for key in item.questions])
    if state == "answered" and item.status != "covered":
        return RowState(item.ref, "partial")
    return RowState(item.ref, state, detail)


def form_answer_states(osp, forms) -> dict:
    """{id(form): [RowState, ...]} for every form, in-scope rows only, in register order."""
    answers = _Answers(osp)
    out: dict = {}
    for form in forms:
        states = [row_answer_state(answers, item) for item in form.items]
        out[id(form)] = [s for s in states if s is not None]
    return out


def form_is_answered(states: list[RowState]) -> bool:
    """True only when at least one row was checked and every in-scope row is closed.

    A form whose rows are all `not_assessed` or out of scope has been checked against nothing,
    and "answered" would be a claim with no evidence under it. `not_assessed` is an open state, so
    only the empty case needs its own line.
    """
    if not states:
        return False
    return all(not s.is_open for s in states)
