"""The record types this plan's own activities require, and where each one stands.

WHY THIS MODULE EXISTS
----------------------
OSP alignment audit 2026-10, T17-F1 (CCOF G8.0 A1). CCOF asks whether the operation maintains ALL
the records needed to verify compliance "based on the activities described in your OSP". Trazo's
attestation covered "the records confirmed above" and its gate refused only an EMPTY list, so one
confirmed record type let an operation that applies inputs, harvests and composts attest to its
records with no input-application record anywhere in the plan.

A record type is REQUIRED when an answer in the plan says the activity behind it happens. Each
trigger cites the answer, so the requirement is the operator's own statement played back, never a
guess about the farm. Each required type is in exactly one state:

    confirmed       the operator confirmed it in the § 11 list
    not_confirmed   required, and not confirmed
    not_kept        the operator says the operation does not keep it (with a reason). Not a way
                    out: a required record that is not kept is a missing record, and says so.
    unresolved      the answer that would decide whether it is required has not been given, so it
                    stays open (the rule for every conditional requirement in this audit)

The attestation can be "Yes" only when every required type is `confirmed`.

The triggers are deliberately few and each is a direct reading of one answer. A record type with no
trigger here is not "not required"; it is simply not derived from the plan, and the § 11 list still
offers it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

CONFIRMED = "confirmed"
NOT_CONFIRMED = "not_confirmed"
NOT_KEPT = "not_kept"
UNRESOLVED = "unresolved"

#: States that leave a required record missing for the attestation.
MISSING_STATES = (NOT_CONFIRMED, NOT_KEPT, UNRESOLVED)


@dataclass(frozen=True)
class Trigger:
    module: str
    question: str
    #: value -> True (activity happens), False (it does not). An unanswered question is unresolved.
    test: Callable
    #: How the requirement reads back to the operator, from their own answer.
    because: str


#: record type key -> the answers that make it required (any one firing is enough).
TRIGGERS: dict[str, tuple[Trigger, ...]] = {
    "input_material_application": (
        Trigger(
            "materials_application",
            "no_materials_used",
            lambda v: v is False,
            "the materials list says input materials are used",
        ),
    ),
    "pest_management": (
        Trigger(
            "g5_0_pest",
            "applies_pest_weed_disease_inputs",
            lambda v: v is True,
            "the pest section says pest, weed or disease inputs are applied",
        ),
    ),
    "harvest_records": (
        Trigger(
            "g6_1_harvest_transport",
            "who_harvests",
            # A crop sold standing in the field is harvested by the buyer, who keeps the records.
            lambda v: bool(set(v if isinstance(v, (list, tuple)) else [v]) - {None, "", "sold_standing"}),
            "the harvest section names who harvests",
        ),
    ),
    "compost_production": (
        Trigger(
            "g4_1_compost_manure",
            "compost_method",
            lambda v: bool(v),
            "the compost section describes compost made on the operation",
        ),
    ),
    "clean_out_records": (
        Trigger(
            "g6_2_storage",
            "storage_shared_with_nonorganic",
            lambda v: v is True,
            "the storage section says storage is shared with non-organic product",
        ),
    ),
    "supplier_verification_records": (
        Trigger(
            "g6_5_sales_soe",
            "sales_soe_supplier_verification",
            lambda v: v == "yes",
            "the sales section says supplier organic status is verified",
        ),
    ),
    "seed_search_commercial_availability": (
        Trigger(
            "g3_0_seeds",
            "ca_search_before_use",
            lambda v: v == "documented_search",
            "the seeds section says non-organic seed follows a documented search",
        ),
    ),
}


@dataclass(frozen=True)
class RequiredRecord:
    key: str
    label: str
    state: str
    because: str = ""
    reason: str = ""

    @property
    def missing(self) -> bool:
        return self.state in MISSING_STATES


def _trigger_value(osp, trigger: Trigger):
    """(answered, value, not_applicable) for one trigger on this plan.

    Visibility decides first, the same way the coverage page does (`packet_answers.question_state`):
    a trigger question hidden by an ANSWERED condition does not apply (a farm that makes no compost
    is never asked its compost method), so it requires nothing; one hidden by an unanswered
    condition, or simply unanswered, leaves the requirement unresolved.
    """
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.conditions import answer_value, effective_value
    from certifications.services.packet_answers import _question_and_page, question_state

    modules = (osp.module_responses or {}).get("modules") if isinstance(osp.module_responses, dict) else None
    entry = (modules or {}).get(trigger.module) if isinstance(modules, dict) else None
    # A stored entry that is not a dict (a malformed write) reads as unanswered, never as a crash:
    # this runs inside the packet build (review of back #84).
    entry = entry if isinstance(entry, dict) else {}
    module = MODULES_BY_KEY.get(trigger.module)
    if module is None:
        return False, None, False
    answers = entry.get("answers") if isinstance(entry.get("answers"), dict) else {}
    na_attested = bool(entry.get("not_applicable")) and bool(entry.get("na_attestation"))
    state, _detail = question_state(module, trigger.question, answers, na_attested=na_attested, section_uploads=0)
    if state == "not_applicable":
        return True, None, True
    if state != "answered":
        return False, None, False
    _page, question = _question_and_page(module, trigger.question)
    return True, effective_value(question, answer_value(answers, trigger.question)), False


def required_records(osp) -> list[RequiredRecord]:
    """Every record type the plan's answers require or leave undecided, with its state.

    Types no trigger fires for, and whose triggers are all answered, are not listed.
    """
    from certifications.services.common_osp_records import RECORD_TYPES_BY_KEY, _confirmations

    confirmations = _confirmations(osp)
    out: list[RequiredRecord] = []
    for key, triggers in TRIGGERS.items():
        record_type = RECORD_TYPES_BY_KEY.get(key)
        if record_type is None:
            continue
        fired, unanswered = [], []
        for trigger in triggers:
            answered, value, module_na = _trigger_value(osp, trigger)
            if module_na:
                continue
            if not answered:
                unanswered.append(trigger)
            elif trigger.test(value):
                fired.append(trigger)
        entry = confirmations.get(key)
        entry = entry if isinstance(entry, dict) else {}
        if fired:
            because = fired[0].because
            if entry.get("confirmed"):
                state = CONFIRMED
            elif entry.get("not_kept"):
                state = NOT_KEPT
            else:
                state = NOT_CONFIRMED
            out.append(RequiredRecord(key, record_type.label, state, because, entry.get("reason") or ""))
        elif unanswered:
            if entry.get("confirmed"):
                # Confirmed anyway: whether the plan requires it does not matter to the attestation.
                continue
            question = unanswered[0]
            out.append(
                RequiredRecord(
                    key,
                    record_type.label,
                    UNRESOLVED,
                    f"{question.module}.{question.question} is not answered yet",
                )
            )
    return out


def missing_required(osp) -> list[RequiredRecord]:
    return [r for r in required_records(osp) if r.missing]


def describe_missing(records: list[RequiredRecord]) -> str:
    """ "Input/material application (not confirmed); Compost production records (not kept: ...)" """
    words = {NOT_CONFIRMED: "not confirmed", NOT_KEPT: "not kept", UNRESOLVED: "not yet decided"}
    parts = []
    for r in records:
        tail = words.get(r.state, r.state)
        if r.state == NOT_KEPT and r.reason:
            tail = f"not kept: {r.reason}"
        parts.append(f"{r.label} ({tail})")
    return "; ".join(parts)
