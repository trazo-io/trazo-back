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


def storage_na_contradictions(osp) -> list[str]:
    """[REVIEW] lines for a G6.2 marked not applicable, one per fact that says the crop is stored. Empty when none do.

    A facility another operation runs counts only while this operation still owns the crop: G6.1's "ownership of the
    crop transfers" says that handler holds its own crop. The operation's own store counts either way (review of back
    #508). A facility stores by `agent_form_sheet.facility_stores`, the rule the WSDA sheet uses. G6.1's cold storage
    is asked as a stop BEFORE the buyer, so a transfer of ownership to a handler does not move it out of the
    operation's hands; that line prints either way."""
    lines = []
    first_stop = _answer(osp, "g6_1_harvest_transport", "first_stop_before_buyer") or []
    if isinstance(first_stop, list) and "cold_storage" in first_stop:
        lines.append(
            "[REVIEW] G6.2 is marked not applicable, but G6.1 states the crop goes to cold storage before the buyer."
        )
    transfers = _answer(osp, "g6_1_harvest_transport", "handled_by_another_operation") == "yes_ownership_transfers"
    if osp.establishment_id:
        from certifications.models import PostHarvestFacility
        from certifications.services.agent_form_sheet import facility_stores

        names = [
            facility.name
            for facility in PostHarvestFacility.objects.filter(establishment_id=osp.establishment_id).order_by("name")
            if facility_stores(facility) and not (transfers and facility.operated_by != "this_operation")
        ]
        if names:
            lines.append(
                "[REVIEW] G6.2 is marked not applicable, but these facilities on file store the crop: "
                f"{_listed(names)}"
            )
    return lines


# ---------------------------------------------------------------------------------------------------------------
# Certification history
# ---------------------------------------------------------------------------------------------------------------


def _parcels_certified_under_this_operation(osp) -> list[str]:
    """Names of parcels stated currently certified under THIS operation, by any agent or none named."""
    from certifications.services.certified_parcel_branch import EXISTING_SITE, branch_for, is_certified

    if not osp.establishment_id:
        return []
    return [
        parcel.name
        for parcel in osp.establishment.parcels.order_by("name")
        if is_certified(parcel) and branch_for(parcel) == EXISTING_SITE
    ]


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
            # The operator's own words when the registry has no name for the slug, never the bare slug.
            name = names_by_slug.get(slug) or (parcel.application_answers or {}).get("prior_certifier_name") or slug
            out.setdefault(name, []).append(parcel.name)
    return out


def history_answer_lines(osp, question_key: str, value) -> list[str]:
    """[REVIEW] lines under one certification-history answer that the certificate on file or the parcels contradict."""
    if question_key not in (
        "history_ever_certified",
        "history_certified_by_this_agency",
        "history_certified_elsewhere_now",
    ):
        return []
    from certifications.services.operation_certificate import certificate_from_another_agent, certificate_of_record
    from certifications.services.packet_coverage import packet_agent

    if question_key == "history_ever_certified":
        # Agent-agnostic: any certificate on file, or any parcel stated certified under this operation, says it has
        # been certified, whoever the plan is filed with (review of back #508).
        if value is not False:
            return []
        held = certificate_of_record(osp.establishment_id) if osp.establishment_id else None
        certified = _parcels_certified_under_this_operation(osp)
        lines = []
        if held is not None and held.number:
            named = f", issued by {held.agent}" if held.agent else ""
            lines.append(
                f"[REVIEW] The plan states the operation has never been certified, but certificate {held.number}"
                f"{named} is on file."
            )
        if certified:
            lines.append(
                "[REVIEW] The plan states the operation has never been certified, but these parcels are recorded as "
                f"certified: {_listed(certified)}"
            )
        return lines

    agent = packet_agent(osp)
    if not agent.slug:
        return []
    # Only an answer that can be contradicted pays for the lookups (review of back #508).
    if question_key == "history_certified_by_this_agency":
        # Dual certification is a true answer: with another agency stated, the other certificate is expected.
        if value is not True or _answer(osp, "certification_contract", "history_certified_elsewhere_now") is True:
            return []
    elif value is not False:
        return []
    other = certificate_from_another_agent(osp)
    other_agent = other.certificate.agent if other is not None and other.confirmed else ""
    lines = []
    if question_key == "history_certified_by_this_agency" and other_agent:
        lines.append(
            f"[REVIEW] The plan states {agent.name} certifies the operation today, but the certificate on file was "
            f"issued by {other_agent}."
        )
    if question_key == "history_certified_elsewhere_now":
        if other_agent:
            lines.append(
                "[REVIEW] The plan states no other agency certifies the operation today, but the certificate on file "
                f"was issued by {other_agent}."
            )
        for name, parcel_names in _parcels_certified_by_another_agent(osp, agent.slug).items():
            lines.append(
                "[REVIEW] The plan states no other agency certifies the operation today, but these parcels are "
                f"recorded as certified by {name}: {_listed(parcel_names)}"
            )
    return lines
