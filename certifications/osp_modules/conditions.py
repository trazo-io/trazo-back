"""
Condition evaluation + completion validation for guided OSP modules.

This evaluator has an exact twin in `trazo-app/src/config/osp/conditionEval.ts`. The two are
kept honest by a golden fixture (`manage.py export_osp_module_fixture` writes the serialized
registry plus answers→visible-questions cases; both test suites assert against it). Change
semantics here and the fixture test on the other side fails — that is the point.

Visibility is transitive (2026-11-03): a condition on a question that is itself hidden fails, so a
child never outlives its parent and no child repeats its ancestors' conditions. See `_visibility`.

Answers shape (the `module_responses` entry this validates against, Appendix A §a):

    answers = {"<question_key>": {"value": <json>, "at": "<iso>"}, ...}

Bare values are tolerated (`answers[k] = <json>`) so callers can validate hypothetical answer
sets (the fixture does) without building envelopes.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .schema import Condition, Module, ModulePage, Question


def answer_value(answers: dict, question_key: str) -> Any:
    """Extract the raw value for a question, tolerating both envelope and bare shapes."""
    entry = (answers or {}).get(question_key)
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


def _is_falsy(value: Any) -> bool:
    # None, "", [], {}, False all count as falsy; 0 does too (no numeric answers where
    # zero-vs-unanswered is meaningful exist in the registry — validation enforces that
    # by construction: numeric inputs are kind "text").
    return not value


def evaluate(cond: Condition, answers: dict) -> bool:
    value = answer_value(answers, cond.question)
    if cond.op == "eq":
        return value == cond.value
    if cond.op == "ne":
        return value != cond.value
    if cond.op == "includes":
        return isinstance(value, (list, tuple)) and cond.value in value
    if cond.op == "includes_any":
        return isinstance(value, (list, tuple)) and any(v in value for v in cond.value)
    if cond.op == "one_of":
        # Scalar counterpart of includes_any: unanswered (None) is NOT one of anything.
        return value is not None and value in cond.value
    if cond.op == "not_includes":
        # A missing/unanswered list does NOT include the value — deliberately True.
        return not (isinstance(value, (list, tuple)) and cond.value in value)
    if cond.op == "truthy":
        return not _is_falsy(value)
    if cond.op == "falsy":
        return _is_falsy(value)
    raise ValueError(f"Unknown condition op: {cond.op}")


def conditions_pass(conds: Iterable[Condition], answers: dict) -> bool:
    """AND semantics — an empty tuple always passes."""
    return all(evaluate(c, answers) for c in conds)


def _visibility(module: Module, answers: dict) -> tuple[list, list]:
    """(visible pages, [(page, question)] visible), with visibility TRANSITIVE.

    A condition on a question that is itself hidden fails, whatever that question still holds. So a
    child is shown only when its own conditions pass and every question they read is shown, through
    every ancestor and the ancestor's page. Until 2026-11-03 each condition read the stored answer
    alone: a grower who said "we do not irrigate" after answering the irrigation questions was still
    asked the children of those stale answers, could not complete the module, and the stale answers
    printed in the plan. Authors repeated every ancestor's conditions on each child to work around
    it, and 27 chains had missed one.

    One pass in definition order is enough: `validate_module` requires every condition to read a
    question defined EARLIER, so a trigger's visibility is always known before it is read.
    """
    shown: dict = {}

    def passes(conds) -> bool:
        return all(shown.get(c.question, True) and evaluate(c, answers) for c in conds)

    pages, questions = [], []
    for page in module.pages:
        page_shown = passes(page.visible_when)
        if page_shown:
            pages.append(page)
        for q in page.questions:
            # A retired question shows only while it still holds an answer (`Question.retired`).
            held = not q.retired or is_answered(effective_value(q, answer_value(answers, q.key)))
            shown[q.key] = page_shown and passes(q.visible_when) and held
            if shown[q.key]:
                questions.append((page, q))
    return pages, questions


def visible_pages(module: Module, answers: dict) -> list:
    return _visibility(module, answers)[0]


def visible_questions(module: Module, answers: dict) -> list:
    """[(page, question)] for every question currently visible, in wizard order."""
    return _visibility(module, answers)[1]


# Question kinds that completion validation skips in v1:
#   info    — renders text, collects nothing
#   upload  — file storage lands with WS-3 (Documents); until then an upload
#             requirement would be unsatisfiable through the API. Deliberate,
#             documented gap — revisit when file_document() exists.
_UNVALIDATED_KINDS = ("info", "upload")


def _answered(q: Question, value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    if isinstance(value, bool):
        # booleans are an explicit yes/no — False is an answer (same distinction
        # common_osp_records._has_content draws for *evidence*, inverted here:
        # this is the operator answering, not Trazo observing).
        return True
    return True


def retired_values(q: Optional[Question]) -> set:
    return {o.value for o in q.options if o.retired} if q is not None else set()


def effective_value(q: Optional[Question], value: Any) -> Any:
    """The stored value with retired options removed: what counts as the operator's CURRENT answer.

    A retired option is kept so an old answer still reads as it was given, but the option that
    replaced it asks something the old one never did. CCOF's contract asks for markets exported to
    "directly or indirectly"; the old "Neither: all product is sold within the United States" was
    never an answer to the indirect half. So an answer made only of retired options is no answer
    until the operator picks a current one (OSP alignment audit 2026-10, T17).
    """
    retired = retired_values(q)
    if not retired or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [v for v in value if v not in retired]
    return None if value in retired else value


def retired_additions(module: Module, incoming: dict, stored: dict) -> dict:
    """{question_key: [retired values]} that an incoming save ADDS to what is stored.

    A retired option is never a new answer. Re-sending the stored value unchanged is accepted, so
    an old client that posts the whole answer set back does not break an unrelated save.
    """
    by_key = {q.key: q for page in module.pages for q in page.questions}
    out = {}
    for key in incoming or {}:
        retired = retired_values(by_key.get(key))
        if not retired:
            continue
        new = answer_value(incoming, key)
        old = answer_value(stored or {}, key)
        new_set = set(new) if isinstance(new, (list, tuple)) else {new}
        old_set = set(old) if isinstance(old, (list, tuple)) else {old}
        added = sorted(v for v in new_set & retired if v not in old_set)
        if added:
            out[key] = added
    return out


def is_answered(value: Any) -> bool:
    """Whether a stored value is an answer at all (the same test completion validation uses)."""
    return _answered(None, value)


def missing_required(module: Module, answers: dict, not_applicable: bool = False) -> list:
    """Question keys that block completion.

    A module attested Not-Applicable validates empty — the attestation replaces the
    questionnaire (and the compiler will emit one attested N/A line for it).
    Required-ness applies only to VISIBLE questions (required-if-visible).
    """
    if not_applicable and module.allows_not_applicable:
        return []
    missing = []
    for _page, q in visible_questions(module, answers):
        if not q.required or q.kind in _UNVALIDATED_KINDS:
            continue
        if q.parcel_field:
            # Bound questions are validated against live model state by the parcel
            # save path (Appendix A §f), not against module answers.
            continue
        if not _answered(q, effective_value(q, answer_value(answers, q.key))):
            missing.append(q.key)
    return missing


def validate_answer_keys(module: Module, answers: dict) -> list:
    """Answer keys that don't exist in the module definition (client drift guard)."""
    known = {q.key for page in module.pages for q in page.questions}
    return sorted(k for k in (answers or {}) if k not in known)


def option_values(q: Question) -> set:
    return {o.value for o in q.options}


def invalid_choice_answers(module: Module, answers: dict) -> dict:
    """{question_key: bad_value} for choice answers not in the defined options."""
    bad = {}
    by_key = {q.key: q for page in module.pages for q in page.questions}
    for key, entry in (answers or {}).items():
        q = by_key.get(key)
        if q is None or q.kind not in ("radio", "select", "checkbox_group"):
            continue
        value = answer_value(answers, key)
        if value is None:
            continue
        allowed = option_values(q)
        if q.kind in ("radio", "select"):
            # `value not in allowed` is a set membership test, so an unhashable value —
            # a client sending a LIST to a single-choice question, which is exactly what a
            # checkbox_group→radio content change produces on an old client — raised
            # TypeError here and surfaced as a 500 on the module save. Malformed input is
            # a validation failure, not a server error: report it like any other bad choice.
            # Found 2026-08-21 writing the Calapooia Bend OSP.
            if isinstance(value, (list, tuple, dict, set)) or value not in allowed:
                bad[key] = value
        else:
            if not isinstance(value, (list, tuple)):
                bad[key] = value
            else:
                unknown = [v for v in value if v not in allowed]
                if unknown:
                    bad[key] = unknown
    return bad


def invalid_typed_answers(module: Module, answers: dict) -> dict:
    """{question_key: reason} for answers whose JSON type contradicts the question kind.

    Load-bearing for the compiler: a boolean question answered with the STRING "no"
    is truthy and would compile "…: Yes." into a certifier-bound narrative. Types are
    enforced at the write boundary so the compiler can trust its inputs.
    """
    bad = {}
    by_key = {q.key: q for page in module.pages for q in page.questions}
    for key in answers or {}:
        q = by_key.get(key)
        if q is None:
            continue
        value = answer_value(answers, key)
        if value is None:
            continue
        if q.kind == "boolean" and not isinstance(value, bool):
            bad[key] = f"Expected true/false, got {type(value).__name__}"
        elif q.kind == "date" and not isinstance(value, str):
            bad[key] = f"Expected an ISO date string, got {type(value).__name__}"
        elif q.kind in ("text", "textarea") and not isinstance(value, (str, int, float)):
            bad[key] = f"Expected a string, got {type(value).__name__}"
    return bad


def exclusive_conflicts(module: Module, answers: dict) -> dict:
    """{question_key: exclusive_value} where a none-of-the-above option is combined
    with other selections ("None used" + "Organic, untreated" would compile a
    self-contradictory sentence). The UI unchecks the others; the server refuses."""
    conflicts = {}
    by_key = {q.key: q for page in module.pages for q in page.questions}
    for key in answers or {}:
        q = by_key.get(key)
        if q is None or q.kind != "checkbox_group":
            continue
        value = answer_value(answers, key)
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            continue
        exclusive_values = {o.value for o in q.options if o.exclusive}
        chosen_exclusive = [v for v in value if v in exclusive_values]
        if chosen_exclusive:
            conflicts[key] = chosen_exclusive[0]
    return conflicts


def progress(module: Module, answers: dict, not_applicable: bool = False) -> dict:
    """Answered/required counts for the module list page."""
    if not_applicable and module.allows_not_applicable:
        return {"answered": 0, "required": 0, "missing": []}
    required_keys = [
        q.key
        for _p, q in visible_questions(module, answers)
        if q.required and q.kind not in _UNVALIDATED_KINDS and not q.parcel_field
    ]
    missing = missing_required(module, answers, not_applicable=not_applicable)
    return {
        "answered": len(required_keys) - len(missing),
        "required": len(required_keys),
        "missing": missing,
    }
