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


def _plan_of_record(establishment):
    """The ACTIVE plan first, else the newest of any status (a draft-only farm reads its draft)."""
    from certifications.models import OrganicSystemPlan

    return (
        OrganicSystemPlan.objects.filter(establishment=establishment, status="active")
        .order_by("-version_number")
        .first()
        or OrganicSystemPlan.objects.filter(establishment=establishment).order_by("-version_number").first()
    )


def _module_answer(osp, module_key, question_key):
    entry = ((osp.module_responses or {}).get("modules", {}) or {}).get(module_key) or {}
    answer = (entry.get("answers") or {}).get(question_key)
    if isinstance(answer, dict):  # stored enveloped as {"value", "at"}
        answer = answer.get("value")
    return answer


def osp_split_operation_answer(establishment) -> Optional[bool]:
    """The operator's own G6.0 answer, or None if the question was never answered.

    Reads the ACTIVE plan first and falls back to the newest of any status, so a farm whose
    only plan is still a draft is read from the draft rather than reported as silent.
    """
    try:
        osp = _plan_of_record(establishment)
        if osp is None:
            return None
        answer = _module_answer(osp, "g6_0_production", "split_operation")
        return answer if isinstance(answer, bool) else None
    except Exception:  # noqa: BLE001 — a cross-check must never take down the packet or the profile
        return None


# G2.0 (fraud prevention) asks which risk areas describe the operation, and one option is
# "We produce or sell both organic and nonorganic product". That is the same fact G6.0's
# split_operation answers, asked a second time. Pilot rehearsal 2026-10-17: the packet's G2.0
# page said "both organic and nonorganic" while the audit export, reading only G6.0 (unanswered)
# and the default-False column, printed "Operator declares a wholly organic operation". The
# export now reads both answers and states a disagreement instead of picking one.
G2_SPLIT_PRODUCTION_OPTION = "split_production"


def g2_split_production_label() -> str:
    """The G2.0 option's own English label, read from the module definition (one author)."""
    from certifications.osp_modules.g2_0_fraud_prevention import G2_0_FRAUD_PREVENTION

    for page in G2_0_FRAUD_PREVENTION.pages:
        for question in page.questions:
            for option in getattr(question, "options", None) or ():
                if option.value == G2_SPLIT_PRODUCTION_OPTION:
                    return option.label["en"]
    return "We produce or sell both organic and nonorganic product"


def g2_lists_split_production(establishment) -> bool:
    """True when the plan's G2.0 risk areas include organic AND nonorganic product."""
    try:
        osp = _plan_of_record(establishment)
        if osp is None:
            return False
        answer = _module_answer(osp, "g2_0_fraud_prevention", "fraud_risk_areas")
        if isinstance(answer, str):
            answer = [answer]
        return isinstance(answer, (list, tuple)) and G2_SPLIT_PRODUCTION_OPTION in answer
    except Exception:  # noqa: BLE001 (a cross-check must never take down the packet)
        return False


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
