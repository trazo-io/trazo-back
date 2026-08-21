"""Establishment-field bindings — what a farm-wide OSP answer writes through to.

`Question.establishment_field` declares that an answer also OWNS a column on
`Establishment`. Unlike `parcel_field` (where the column IS the storage and the answer
never lands in `module_responses`), a bound farm-wide answer is stored in BOTH places:
the OSP because that is the record a certifier reads, and the column because the audit
export, the readiness checks and `seed_osp_template` already read it. The write-through
below is what stops the two from drifting.

🔴 2026-08-21 (F25) — before this existed, `Establishment.has_split_operation` (a
farm-profile checkbox) and G6.0's `split_operation` answer were two editors of one
§ 205.201(a)(5) fact. A farm that answered "yes, we sell the buffer rows conventional"
in the OSP wizard filed a packet whose § 205.272 row said "Split Operation: No", with a
REVIEW underneath telling the operator that the two statements in their own packet
disagreed — about a question they had already answered in the place the regulation
cares about.

Deliberately NOT a generic model-field writer: the only writable columns are the ones a
module definition names, so the allowlist is the content itself and a request body can
never reach a column no question binds.
"""

from __future__ import annotations

from typing import Optional


def _coerce(kind: str, value) -> object:
    """Answer value → column value, by question kind.

    A deleted answer (`None`) clears the column rather than leaving the last statement
    standing: an operator who removes their answer has withdrawn the declaration, and a
    stale `True` here would print a declaration the plan no longer makes.
    """
    if kind == "boolean":
        return bool(value) if value is not None else False
    return "" if value is None else str(value)


def is_unchanged(current, incoming) -> bool:
    """Whether writing `incoming` over `current` would change anything an inspector reads.

    `None` and `""` are the same emptiness on a `null=True, blank=True` text column, and the
    two are chosen by whoever wrote the row rather than by the operator. Comparing them
    naively makes every "clear this answer" save write a column that was already empty — a
    real row in the § 205.400(f)(1) audit log recording that nothing happened, which is worse
    than noise in a document whose whole job is to be readable.
    """
    if current in (None, "") and incoming in (None, ""):
        return True
    return current == incoming


def establishment_writes(module, incoming: dict) -> dict:
    """`{column: value}` for the questions in `incoming` that bind an Establishment column.

    Only keys present in THIS request are returned. Recomputing every bound column from
    the whole stored answer set instead would clobber a column with a default whenever an
    unrelated question in the same module is saved.
    """
    if not incoming:
        return {}
    bound: dict = {}
    for page in module.pages:
        for q in page.questions:
            field: Optional[str] = getattr(q, "establishment_field", None)
            if field and q.key in incoming:
                bound[field] = _coerce(q.kind, incoming[q.key])
    return bound


def bound_establishment_fields(module) -> dict:
    """`{question_key: column}` for every bound question on `module` — for tests and admin."""
    return {
        q.key: q.establishment_field
        for page in module.pages
        for q in page.questions
        if getattr(q, "establishment_field", None)
    }
