"""Where the operation's own certifying agent asks each plan question: the wizard's caption.

The questions are the same for every operation and gated by its own answers, never by its agent
(one answer fills WSDA's, CCOF's and Oregon Tilth's forms alike). What the agent changes is where
the grower will meet the question again: "WSDA asks this in K Storage (AGR 2121), item 3a". That
line is read from the same register the packet's coverage page and question index read, so the
wizard and the packet cannot name different items.

Only the agent's own register is used. An agent Trazo holds no register for (OCI, WFCF, an unknown
name) gets no caption: a borrowed agent's item numbers would send the grower to the wrong form.
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

#: Rows that do not tie a question to an item the agent asks: an out-of-scope row cites none, and a
#: not-covered row says no Trazo question answers it.
_UNCITED_STATUSES = ("out_of_scope", "not_covered")


def _form_name(form) -> str:
    """The form as the packet names it: "K Storage (AGR 2121)", "G6.2 Storage (ORGB38)", "C8 Crop
    Labeling & Sales" (OTCO's document id is its code, so it is not repeated)."""
    label = form.label
    document_id = form.document_id
    if document_id and document_id not in (form.code, form.title, label):
        return f"{label} ({document_id})"
    return label


@lru_cache(maxsize=None)
def refs_by_question(certifier: str) -> dict[str, tuple[dict, ...]]:
    """{"module.question": ({"form": name, "items": (ref, ...)}, ...)} for one agent's register.

    Cached per agent: the register is a docs tree read from disk, and it changes only with a deploy.
    """
    from certifications.services.certifier_register import load_forms

    grouped: dict[str, dict[str, list[str]]] = {}
    for form in load_forms(certifier):
        if not form.served:
            continue
        name = _form_name(form)
        for item in form.items:
            if item.kind != "question" or item.status in _UNCITED_STATUSES:
                continue
            for key in item.questions:
                items = grouped.setdefault(key, {}).setdefault(name, [])
                if item.ref not in items:
                    items.append(item.ref)
    return {
        key: tuple({"form": name, "items": tuple(items)} for name, items in forms.items())
        for key, forms in grouped.items()
    }


def agent_question_refs(osp, module_key: str) -> dict | None:
    """{"agent": "WSDA", "refs": {question_key: [{"form", "items"}, ...]}, "asked": [key, ...]} for
    one module of this plan, or None when the plan's agent has no register here (no caption is
    better than a wrong one).
    """
    from certifications.certifying_agents import AGENTS
    from certifications.services.packet_coverage import packet_agent, registered_certifiers

    agent = packet_agent(osp)
    if not agent.slug or agent.slug not in registered_certifiers():
        return None
    try:
        by_question = refs_by_question(agent.slug)
    except Exception:  # noqa: BLE001 - a wizard page must load without the docs tree
        logger.exception("%s register could not be read for question captions", agent.slug)
        return None
    known = next((a for a in AGENTS if a.slug == agent.slug), None)
    prefix = f"{module_key}."
    asks = agent_asks(osp)
    return {
        "agent": (known.short_name or known.name) if known else agent.name,
        "refs": {
            key[len(prefix) :]: [dict(ref, items=list(ref["items"])) for ref in refs]
            for key, refs in by_question.items()
            if key.startswith(prefix)
        },
        # The questions a row of this agent asks and applies to this plan; the wizard flags the
        # blank ones that are showing (`blank_asked_questions` is the server's copy of that rule).
        "asked": sorted(asks[1].get(module_key, ())) if asks else [],
    }


# ---------------------------------------------------------------------------
# Blank questions the agent asks
# ---------------------------------------------------------------------------
#
# A question Trazo marks optional is optional to Trazo: the plan reads true without it. It is not
# optional to an agent whose form asks it. Left blank, it printed "Not answered (optional)" and
# the wizard said nothing, so the grower learned it was asked only when the agent wrote back.
# These are the blank ones the plan's own agent asks: flagged softly, never blocking completion
# (the agent decides what it needs, not Trazo).
#
# Only rows that tie the answer to an item the agent asks count: `covered` or `partial`, not
# printed optional by the form, and applying to this plan. A row whose `applies_when` trigger is
# unanswered is left out; its trigger is the open question, and is flagged if the agent asks it.

#: Kinds that hold no typed answer: an info panel collects nothing, and an upload is answered by a
#: linked file the coverage page already reads (`attachment_missing`).
_NO_TYPED_ANSWER = ("info", "upload")


def _blank_reads_as_no(module) -> frozenset[str]:
    """Questions some condition of the module reads with `falsy`.

    The plan already treats their blank as No ("No fertilizers used" left unticked shows the
    fertilizer list), so a blank there is an answer, and flagging it would nag a grower who listed
    their materials.
    """
    keys = set()
    for page in module.pages:
        for cond in page.visible_when:
            if cond.op == "falsy":
                keys.add(cond.question)
        for question in page.questions:
            for cond in question.visible_when:
                if cond.op == "falsy":
                    keys.add(cond.question)
    return frozenset(keys)


@lru_cache(maxsize=None)
def _asking_rows(certifier: str) -> tuple:
    """((document id, item), ...): the rows of one agent's served forms that tie an answer to an item
    the agent asks and the form does not print optional. Cached like `refs_by_question`."""
    from certifications.services.certifier_register import load_forms

    return tuple(
        (form.document_id or "", item)
        for form in load_forms(certifier)
        if form.served
        for item in form.items
        if item.kind == "question" and item.status in ("covered", "partial") and not item.optional
    )


def agent_asks(osp) -> tuple[str, dict[str, frozenset[str]]] | None:
    """(agent name, {module key: question keys}) the plan's own agent asks on a row that applies.

    None for an agent Trazo holds no register for. Farm-wide modules only: a parcel's questions
    are answered on its own page.
    """
    from certifications.certifying_agents import AGENTS
    from certifications.services.packet_answers import _Answers, _applies
    from certifications.services.packet_coverage import packet_agent, registered_certifiers

    agent = packet_agent(osp)
    if not agent.slug or agent.slug not in registered_certifiers():
        return None
    try:
        rows = _asking_rows(agent.slug)
    except Exception:  # noqa: BLE001 - a wizard page must load without the docs tree
        logger.exception("%s register could not be read for blank-question flags", agent.slug)
        return None
    from certifications.services.certified_parcel_branch import PARCEL_FORMS, ROUTE_FORMS

    answers = _Answers(osp)
    # Only a parcel form can be off a parcel's route; asking the route of every other form would
    # assess each parcel once per module PDF of a packet build for nothing.
    routed = {document_id for _route, document_id in ROUTE_FORMS} | set(PARCEL_FORMS.values())
    asked: dict[str, set[str]] = {}
    for document_id, item in rows:
        if item.applies_when and _applies(answers, item) is not None:
            continue
        if document_id in routed and answers.row_off_route(document_id, item.ref) is not None:
            continue
        for key in item.questions:
            module_key, _, question_key = key.partition(".")
            if module_key in answers.modules and module_key != answers.parcel_key:
                asked.setdefault(module_key, set()).add(question_key)
    known = next((a for a in AGENTS if a.slug == agent.slug), None)
    name = (known.short_name or known.name) if known else agent.name
    return name, {key: frozenset(keys) for key, keys in asked.items()}


def blank_asked_questions(module, entry: dict, asked: frozenset[str]) -> list[str]:
    """Keys of this module's questions that are showing, blank, not required by Trazo, and asked.

    Required ones are left out: the wizard already refuses to complete without them, and one
    question flagged twice reads as two problems.
    """
    from certifications.osp_modules.conditions import answer_value, is_answered, visible_questions

    if not asked or (entry.get("not_applicable") and module.allows_not_applicable):
        return []
    answers = entry.get("answers") or {}
    reads_as_no = _blank_reads_as_no(module)
    return [
        question.key
        for _page, question in visible_questions(module, answers)
        if question.key in asked
        and not question.required
        and question.kind not in _NO_TYPED_ANSWER
        and not question.parcel_field
        and question.key not in reads_as_no
        and not is_answered(answer_value(answers, question.key))
    ]


def asks_sentence(agent: str, refs) -> str:
    """ "WSDA asks this in K Storage (AGR 2121), item 3a." The wizard caption's English wording
    (`osp.wizard.agentAsks`), so the plan and the wizard say it the same way."""
    forms = "; ".join(
        f"{ref['form']}, {'item' if len(ref['items']) == 1 else 'items'} {', '.join(ref['items'])}" for ref in refs
    )
    return f"{agent} asks this in {forms}."
