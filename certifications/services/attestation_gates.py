"""
Attestations that cannot be true while the thing they attest to is empty.

Some OSP questions are not questions about the farm — they are the operator vouching for a LIST
rendered above them. CCOF G8.0 section A is the archetype: the form prints the record types an
organic crop operation keeps, and the signature line says "I maintain the records above." Trazo
renders that list as an embed (the Common OSP § 11 registry) and the attestation as a boolean
underneath it.

The defect this module exists to prevent, found 2026-08-27 on the pilot farm: the embed is an
`info` question, and `info` is skipped by completion validation, so the module reported
"Completed · 3 of 3 required" while its generated PDF printed

    No record types have been confirmed in the Common OSP § 11 registry yet.
    Do you maintain the records confirmed above, keep them for at least 5 years, and make them
    available at inspection?  Yes

— an attestation to an empty list, in a document a certifier reads, over the operator's name.

## Why this is a registry and not `if module_key == ...`

The same shape will recur every time an embed carries content an attestation vouches for. Declaring
it on the question (`attests_embed="s11_record_types"`) keeps the rule next to the sentence it
governs, and this module holds the one thing a question cannot know: whether that embed has
anything in it for THIS plan.

## Why the materials list is deliberately NOT here

`materials_application.materials_list_complete` ("every input material I use or plan to use is
entered in this list") sits over the approved-inputs panel and looks like the same shape. It is not.
An operation that applies nothing has an empty materials list and the attestation is then vacuously
TRUE — refusing it would force a no-spray grower to lie or leave the module incomplete. That
attestation has a different defect (the packet renders four disagreeing lists beneath it) and a
different fix: reconciliation, not an emptiness gate.

An operation that maintains NO records, by contrast, cannot be certified at all, so an empty § 11
list never means "correctly empty" — it means the operator has not ticked yet.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# embed name -> (is_empty(osp) -> bool, message shown to the operator)
_EMBED_EMPTINESS: dict[str, tuple[Callable, str]] = {}


def _s11_is_empty(osp) -> bool:
    from certifications.services.common_osp_records import derive_record_types

    rows = derive_record_types(osp.establishment, osp=osp)
    return not any(row.get("confirmed") for row in rows)


_EMBED_EMPTINESS["s11_record_types"] = (
    _s11_is_empty,
    (
        "Confirm at least one record type in the list above first. This answer is your statement "
        "to your certifier about the records you keep, and right now the list is empty — the "
        "generated plan would show an attestation with nothing under it."
    ),
)


def blocked_attestations(module, answers: dict, osp) -> dict[str, str]:
    """{question_key: message} for attestations answered affirmatively over an empty embed.

    Only affirmative answers are blocked. "No" over an empty list is a coherent statement, and an
    unanswered question is already handled by required-field validation.
    """
    # Answers arrive in TWO shapes: bare values on the write path (straight from the request) and
    # enveloped `{"value": ..., "at": ...}` once stored. `answer_value` is the accessor that already
    # exists for exactly this, and reading `answers.get(key)` directly is how the first version of
    # this gate passed silently at completion time — the envelope is a dict, and a dict is not True.
    from certifications.osp_modules.conditions import answer_value

    blocked: dict[str, str] = {}
    if osp is None:
        return blocked

    for page in module.pages:
        for question in page.questions:
            embed = getattr(question, "attests_embed", None)
            if not embed or answer_value(answers, question.key) is not True:
                continue
            checker = _EMBED_EMPTINESS.get(embed)
            if checker is None:
                continue
            is_empty, message = checker
            try:
                if is_empty(osp):
                    blocked[question.key] = message
            except Exception:  # noqa: BLE001
                # Fail OPEN, but never silently. Failing closed would block an operator from
                # saving anything because of an unrelated bug in the emptiness check; failing
                # open lets one attestation through. Both are bad, and the deciding factor is
                # that a silent pass is undetectable while a logged one is not.
                logger.exception(
                    "CCOF attestation gate could not evaluate embed %r for OSP %s; allowing the "
                    "answer through. An attestation may now stand over an empty list.",
                    embed,
                    getattr(osp, "pk", None),
                )
                continue
    return blocked
