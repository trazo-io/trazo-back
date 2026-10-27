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
    """{"agent": "WSDA", "refs": {question_key: [{"form", "items"}, ...]}} for one module of this
    plan, or None when the plan's agent has no register here (no caption is better than a wrong one).
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
    return {
        "agent": (known.short_name or known.name) if known else agent.name,
        "refs": {
            key[len(prefix) :]: [dict(ref, items=list(ref["items"])) for ref in refs]
            for key, refs in by_question.items()
            if key.startswith(prefix)
        },
    }
