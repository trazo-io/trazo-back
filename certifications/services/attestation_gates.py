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

## Why the materials list is gated on reconciliation, not emptiness

(2026-11-04.) The materials "listed" statements are gated, but on a different fact: not that the list
is empty, but that the records name products the list does not hold, by name or by a current
identity decision (`plan_materials.unmatched_logged_materials`, the one reading the materials page
prints from). The CCOF, WSDA and OTCO reviewer reads all found the same page printing "Yes" to
"every input material I use is entered in this list" beside "11 logged product names are not
confirmed". The emptiness argument below still holds: a grower who applies nothing logs nothing,
so nothing is unmatched and "Yes" stands.

## Why the materials list is not an emptiness gate

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
    """Is the § 11 list empty as the PACKET would print it?

    Reads the confirmations off the plan rather than deriving evidence: this runs on every G8.0
    write, on completion, on the reported module status and inside the PDF, and `EvidenceBundle`
    loads every production on the operation with six prefetched event relations to answer a
    question that never looks at a single event.

    ⚠️ The intersection with `RECORD_TYPES_BY_KEY` is load-bearing, not tidiness. A confirmation
    for a key that has since left the registry is still sitting in `sections`, and the renderer
    iterates the REGISTRY — so counting raw confirmations would let an attestation through while
    the generated page under it printed nothing at all, which is the precise defect this gate
    exists to prevent.
    """
    from certifications.services.common_osp_records import RECORD_TYPES_BY_KEY, _confirmations

    confirmations = _confirmations(osp)
    return not any(
        isinstance(entry, dict) and entry.get("confirmed")
        for key, entry in confirmations.items()
        if key in RECORD_TYPES_BY_KEY
    )


def _s11_missing_required(osp):
    """Required record types (from the plan's own answers) that are not confirmed, or ""."""
    from certifications.services.required_records import describe_missing, missing_required

    missing = missing_required(osp)
    return describe_missing(missing) if missing else ""


#: embed name -> (missing(osp) -> "" or the missing items named, message template). Checked after
#: emptiness: a list can be non-empty and still leave out a record the plan's activities require.
_EMBED_COMPLETENESS: dict[str, tuple[Callable, str]] = {
    "s11_record_types": (
        _s11_missing_required,
        (
            "Your plan's own answers require records that are not confirmed in the list above: "
            "{missing}. Confirm each one you keep, or answer No: this statement covers every record "
            "your activities require (CCOF G8.0 A1)."
        ),
    )
}

_EMBED_EMPTINESS["s11_record_types"] = (
    _s11_is_empty,
    (
        "Confirm at least one record type in the list above first. This answer is your statement "
        "to your certifier about the records you keep, and right now the list is empty — the "
        "generated plan would show an attestation with nothing under it."
    ),
)


#: Materials Application statements that the records can contradict: the question, and the product
#: names it covers (None = every logged product).
_RECONCILED_STATEMENTS = {
    "materials_list_complete": None,
    "fertilizers_listed": "fertilizers_listed",
    "pest_disease_weed_listed": "pest_disease_weed_listed",
    "post_harvest_contact_listed": "post_harvest_contact_listed",
}

RECONCILIATION_MESSAGE = (
    "The records name {count} product(s) this list does not hold: {names}. Add each one to the list, "
    "or tie it to a listed product under Logged names not on the plan, before answering Yes."
)


def unlisted_products(question_key: str, osp) -> list[str]:
    """Logged products a Materials Application "listed" statement would leave out, for this plan."""
    from certifications.services.osp_prefill import logged_category_names
    from certifications.services.plan_materials import _norm, unmatched_logged_materials

    unmatched = unmatched_logged_materials(osp)
    category = _RECONCILED_STATEMENTS.get(question_key)
    if category is None:
        return unmatched
    names = {_norm(n) for n in logged_category_names(osp.establishment, category)}
    return [n for n in unmatched if _norm(n) in names]


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
                    continue
                completeness = _EMBED_COMPLETENESS.get(embed)
                if completeness is not None:
                    missing_of, template = completeness
                    missing = missing_of(osp)
                    if missing:
                        blocked[question.key] = template.format(missing=missing)
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
    if getattr(module, "key", "") == "materials_application":
        for question_key in _RECONCILED_STATEMENTS:
            if answer_value(answers, question_key) is not True:
                continue
            try:
                unlisted = unlisted_products(question_key, osp)
            except Exception:  # noqa: BLE001 (fail open, logged, as above)
                logger.exception("Materials reconciliation could not run for OSP %s", getattr(osp, "pk", None))
                continue
            if unlisted:
                shown = ", ".join(unlisted[:8]) + (f", and {len(unlisted) - 8} more" if len(unlisted) > 8 else "")
                blocked[question_key] = RECONCILIATION_MESSAGE.format(count=len(unlisted), names=shown)
    return blocked
