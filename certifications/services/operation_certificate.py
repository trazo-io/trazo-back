"""The operation's certificate of record — number and issuing agent, from ONE record.

WHY THIS MODULE EXISTS
----------------------
🔴 2026-09-07. A certificate number and the agent that issued it are a single fact, and the
renewal packet had begun assembling them from two places.

`Certification` (the farm profile's certification list) and `OrganicSystemPlan.approval_*` (what
the activation gate requires before a plan may go active) both carry a number and an agent name.
The cover read the first and, when that came up short, filled in the missing half from the second
— field by field, independently. So an operation with a `Certification` row carrying a number but
no agent, plus a WSDA-approved plan, printed:

    Certificate: CCOF-2026-1234 — Washington State Department of Agriculture

A certificate number attributed to an agent that did not issue it, on the document that agent
reads. Worse than the blank it was written to replace.

The rule this module exists to hold: **the first record that carries a number supplies both
halves, or the agent half stays empty.** Never two records, never field-by-field.

It also settles a second disagreement. `packet_coverage.resolve_certifier` decides which
certifier's form numbering document 04 speaks; it scanned the OSP lineage first while the cover
preferred `Certification`. Two documents in one ZIP could therefore name two different certifying
agents. Both now start from the same record here, so the packet tells one story.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OperationCertificate:
    """A certificate as one record stated it. `agent` may be empty; the pair is never mixed."""

    number: str = ""
    agent: str = ""
    #: "certification" (farm profile row) or "osp" (the activation gate), for logging and tests.
    source: str = ""


def _clean(value) -> str:
    return (value or "").strip()


def _certification_candidates(establishment_id) -> list[tuple[str, str]]:
    """(number, agent) from the farm profile's NOP certificates, most authoritative first.

    Active before inactive, newest effective date first. Without the active filter a revoked or
    expired certificate with a later effective date would print as the operation's certificate.
    `is_active` is a property (it reads today's date), so the sort runs in Python over the handful
    of rows an operation has.
    """
    from certifications.constants import NOP_CERTIFICATION_TYPES
    from certifications.models import Certification

    rows = sorted(
        Certification.objects.filter(
            establishment_id=establishment_id,
            certification_type__in=NOP_CERTIFICATION_TYPES,
        ),
        key=lambda c: (c.is_active, c.effective_date or date.min),
        reverse=True,
    )
    return [(_clean(row.certification_number), _clean(row.certifier_name)) for row in rows]


def _osp_candidates(establishment_id) -> list[tuple[str, str]]:
    """(number, agent) from the activation gate, newest plan version first.

    A renewal draft must be able to name the certificate that approved the PRIOR version — that is
    the certificate the operation actually holds while the new version is still a draft.
    """
    from certifications.models import OrganicSystemPlan

    return [
        (_clean(number), _clean(agent))
        for number, agent in OrganicSystemPlan.objects.filter(establishment_id=establishment_id)
        .order_by("-version_number")
        .values_list("approval_certificate_number", "approval_certifier_name")
    ]


def certificate_of_record(establishment_id) -> OperationCertificate:
    """The certificate this operation holds: the first record carrying a NUMBER, with its own agent.

    Returns an empty certificate rather than raising — a packet must never fail to generate over
    this, and a blank line reads as absence, which is true.
    """
    try:
        sources = (
            ("certification", _certification_candidates(establishment_id)),
            ("osp", _osp_candidates(establishment_id)),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not read the certificate of record for establishment %s", establishment_id)
        return OperationCertificate()

    for source, candidates in sources:
        for number, agent in candidates:
            if number:
                return OperationCertificate(number=number, agent=agent, source=source)
    return OperationCertificate()


def agent_names(establishment_id) -> list[str]:
    """Every certifying-agent name on the operation's records, most authoritative first.

    Used ONLY when the certificate of record names no agent. While it does name one, that name is
    the operation's answer and nothing else may contradict it — see this module's docstring.
    """
    try:
        pairs = _certification_candidates(establishment_id) + _osp_candidates(establishment_id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not read certifying-agent names for establishment %s", establishment_id)
        return []
    return [agent for _number, agent in pairs if agent]


def certificate_from_another_agent(osp) -> OperationCertificate | None:
    """The certificate of record when an agent OTHER than the one this plan names issued it, else None.

    `packet_coverage.packet_agent` numbers the packet by the plan's own answer and the cover prints
    the certificate the operation holds. The two differ exactly when an operation moves to a new
    agent, and until 2026-11-04 nothing in the packet said so: the CCOF, WSDA and OTCO reviewer
    reads found one agent's certificate on the cover under another agent's renewal routing, with
    02s pointing the new agent's Cert No and Client ID rows at it.

    None when there is no certificate number, when it names no agent, when the plan names no agent
    Trazo knows, or when both are the same agent. An issuing agent Trazo does not know is not the
    plan's agent, so it counts as another.
    """
    from certifications.certifying_agents import agent_for_name
    from certifications.services.packet_coverage import packet_agent

    certificate = certificate_of_record(osp.establishment_id)
    if not certificate.number or not certificate.agent:
        return None
    plan_slug = packet_agent(osp).slug
    if not plan_slug:
        return None
    held = agent_for_name(certificate.agent)
    if held is not None and held.slug == plan_slug:
        return None
    return certificate
