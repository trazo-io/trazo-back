"""Two answers a reviewer read as contradicted elsewhere in the same packet, with nothing saying so.

Found by the blind re-grade of 2026-11-19 (three graders, each given only an agent's forms and two generated
packets; audit note documentation/audits/OVERALL-REVIEW-2026-11/regrade-2026-11-19 in the workspace repo):

  G6.2 marked not applicable ("product is never stored; it is sold and shipped directly from the field") while
  G6.1 says the crop goes to cold storage before the buyer, or a facility on file stores it. CCOF G6.2 A1 asks
  whether the operation owns the crop in off-farm storage; with the section attested away it is never answered.

  The certification history (CCOF contract D4, OTCO O1 D-1A) says no other agency certifies the operation today,
  or that the agency the plan is filed with does, while the certificate on file, or parcels recorded as certified
  under this operation, name another agent. A plan whose agent changes keeps answers given against the old one.

Each fact prints as a [REVIEW] line beside the answer it contradicts. Nothing is answered for the operator: which
statement is true is theirs to say.
"""

from __future__ import annotations


def _module_answers(osp, module_key) -> dict | None:
    entry = ((osp.module_responses or {}).get("modules") or {}).get(module_key) or {}
    if entry.get("not_applicable"):
        return None
    return entry.get("answers") or {}


def _listed(names) -> str:
    """Names joined into the end of a sentence: one full stop, even after "Co." or "Inc."."""
    return ", ".join(names).rstrip(".") + "."


def _answer(osp, module_key, question_key):
    from certifications.osp_modules.conditions import answer_value

    answers = _module_answers(osp, module_key)
    if answers is None:
        return None
    return answer_value(answers, question_key)


# ---------------------------------------------------------------------------------------------------------------
# G6.2 attested not applicable
# ---------------------------------------------------------------------------------------------------------------

#: `PostHarvestFacility.role` values that hold the crop.
STORING_ROLES = ("storage", "both")


def storage_na_contradictions(osp) -> list[str]:
    """[REVIEW] lines for a G6.2 marked not applicable, one per fact that says the crop is stored. Empty when none do.

    A facility that stores the crop counts only while the operation still owns it: G6.1's "ownership of the crop
    transfers" says the handler holds its own crop, which is not this operation's storage."""
    lines = []
    first_stop = _answer(osp, "g6_1_harvest_transport", "first_stop_before_buyer") or []
    if isinstance(first_stop, list) and "cold_storage" in first_stop:
        lines.append(
            "[REVIEW] G6.2 is marked not applicable, but G6.1 states the crop goes to cold storage before the buyer."
        )
    if _answer(osp, "g6_1_harvest_transport", "handled_by_another_operation") == "yes_ownership_transfers":
        return lines
    if osp.establishment_id:
        from certifications.models import PostHarvestFacility

        names = list(
            PostHarvestFacility.objects.filter(establishment_id=osp.establishment_id, role__in=STORING_ROLES)
            .order_by("name")
            .values_list("name", flat=True)
        )
        if names:
            lines.append(
                "[REVIEW] G6.2 is marked not applicable, but these facilities on file store the crop: "
                f"{_listed(names)}"
            )
    return lines


# ---------------------------------------------------------------------------------------------------------------
# Certification history
# ---------------------------------------------------------------------------------------------------------------


def _parcels_certified_by_another_agent(osp, plan_slug: str) -> dict[str, list[str]]:
    """{agent name: [parcel names]} for parcels stated currently certified under THIS operation by a registered agent
    other than the plan's. A parcel certified under another operation, or naming no agent Trazo knows, is left out:
    neither says who certifies this operation."""
    from certifications.certifying_agents import AGENTS
    from certifications.services.certified_parcel_branch import EXISTING_SITE, branch_for, is_certified, stated_agent

    names_by_slug = {a.slug: a.name for a in AGENTS}
    out: dict[str, list[str]] = {}
    if not osp.establishment_id:
        return out
    for parcel in osp.establishment.parcels.order_by("name"):
        if not is_certified(parcel) or branch_for(parcel) != EXISTING_SITE:
            continue
        slug = stated_agent(parcel)
        if slug and slug != plan_slug:
            out.setdefault(names_by_slug.get(slug, slug), []).append(parcel.name)
    return out


def history_answer_lines(osp, question_key: str, value) -> list[str]:
    """[REVIEW] lines under one certification-history answer that the certificate on file or the parcels contradict."""
    if question_key not in (
        "history_ever_certified",
        "history_certified_by_this_agency",
        "history_certified_elsewhere_now",
    ):
        return []
    from certifications.services.operation_certificate import certificate_from_another_agent
    from certifications.services.packet_coverage import packet_agent

    agent = packet_agent(osp)
    if not agent.slug:
        return []
    other = certificate_from_another_agent(osp)
    other_agent = other.certificate.agent if other is not None and other.confirmed else ""
    parcels = _parcels_certified_by_another_agent(osp, agent.slug)
    lines = []
    if question_key == "history_ever_certified" and value is False and (other_agent or parcels):
        lines.append(
            "[REVIEW] The plan states the operation has never been certified, but "
            + (
                f"the certificate on file was issued by {other_agent}"
                if other_agent
                else "parcels are recorded as certified"
            )
            + "."
        )
    if question_key == "history_certified_by_this_agency" and value is True and other_agent:
        lines.append(
            f"[REVIEW] The plan states {agent.name} certifies the operation today, but the certificate on file was "
            f"issued by {other_agent}."
        )
    if question_key == "history_certified_elsewhere_now" and value is False:
        if other_agent:
            lines.append(
                "[REVIEW] The plan states no other agency certifies the operation today, but the certificate on file "
                f"was issued by {other_agent}."
            )
        for name, parcel_names in parcels.items():
            lines.append(
                "[REVIEW] The plan states no other agency certifies the operation today, but these parcels are "
                f"recorded as certified by {name}: {_listed(parcel_names)}"
            )
    return lines
