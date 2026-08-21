"""The one resolver for an operation's § 205.201(a)(5) / § 205.272 split declaration.

Three states, never two: **yes / no / never answered.** Collapsing "never answered" into
"no" is how a document ends up ratifying a regulatory conclusion nobody drew — § 205.272(a)
binds any operation producing both organic and non-organic product, so the packet reports
the declaration, it does not make one.

🔴 2026-08-21 (F25) — the fact had two editors: `Establishment.has_split_operation` (a
farm-profile switch) and OSP module G6.0's `split_operation` answer, with nothing binding
them. A farm that answered "yes, we sell the buffer rows conventional" in the OSP still
filed a packet whose § 205.272 row read "Split Operation: No", followed by a REVIEW telling
the operator that the two statements in their own packet disagreed. The OSP now OWNS the
fact and writes through to the column (`certifications/osp_modules/bindings.py`); this
module is the single place that says what the resolution order is, so the audit export and
the farm profile can never disagree about it either.
"""

from __future__ import annotations

from typing import Optional

# The three states the UI and the packet both render. Strings, not a bool-or-None, because
# this crosses the API boundary and `null` in JSON reads as "the backend forgot".
DECLARED_YES = "yes"
DECLARED_NO = "no"
UNANSWERED = "unanswered"


def osp_split_operation_answer(establishment) -> Optional[bool]:
    """The operator's own G6.0 answer, or None if the question was never answered.

    Reads the ACTIVE plan first and falls back to the newest of any status, so a farm whose
    only plan is still a draft is read from the draft rather than reported as silent.
    """
    try:
        from certifications.models import OrganicSystemPlan

        osp = (
            OrganicSystemPlan.objects.filter(establishment=establishment, status="active")
            .order_by("-version_number")
            .first()
            or OrganicSystemPlan.objects.filter(establishment=establishment).order_by("-version_number").first()
        )
        if osp is None:
            return None
        entry = ((osp.module_responses or {}).get("modules", {}) or {}).get("g6_0_production") or {}
        answer = (entry.get("answers") or {}).get("split_operation")
        if isinstance(answer, dict):  # stored enveloped as {"value", "at"}
            answer = answer.get("value")
        return answer if isinstance(answer, bool) else None
    except Exception:  # noqa: BLE001 — a cross-check must never take down the packet or the profile
        return None


def split_operation_declaration(establishment) -> str:
    """`"yes"` / `"no"` / `"unanswered"` — what this operation has actually declared.

    Resolution order:
      1. The OSP G6.0 answer when it exists. It is the § 205.201 plan of record and, since
         the binding, the only editor.
      2. A `True` column with no OSP answer — a declaration made under the pre-binding
         farm-profile switch. It is a real operator statement and is not thrown away.
      3. Everything else is UNANSWERED. A `False` column with no OSP answer is the model
         DEFAULT, not a statement: reporting it as "no" is exactly the manufactured
         declaration this module exists to prevent.
    """
    answer = osp_split_operation_answer(establishment)
    if answer is True:
        return DECLARED_YES
    if answer is False:
        return DECLARED_NO
    return DECLARED_YES if establishment.has_split_operation else UNANSWERED
