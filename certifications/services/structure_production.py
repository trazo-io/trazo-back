"""What the plan and the records say about production G3.1 asks about, set against a G3.1 marked not applicable.

CCOF G3.1 (Container & Greenhouse/Shadehouse Production) is asked of every operation; its "None of these" is the
module's not-applicable attestation. Five facts elsewhere can disagree with it: the plan's own G3.0 (seedlings the
operation grows itself), G3.0b (planting stock sold as organic) and G4.0 (a container production system), a parcel
flagged for container production, and a production recorded as indoor. Each prints as a [REVIEW] line under the
attestation. Nothing is answered for the operator: a container parcel can be potted nursery stock or a container
crop, and which one is the operator's statement.
"""

from __future__ import annotations


def _answer(osp, module_key, question_key):
    from certifications.osp_modules.conditions import answer_value

    entry = ((osp.module_responses or {}).get("modules") or {}).get(module_key) or {}
    if entry.get("not_applicable"):
        return None
    return answer_value(entry.get("answers") or {}, question_key)


def na_contradictions(osp) -> list[str]:
    """[REVIEW] lines for a G3.1 marked not applicable, one per fact that says otherwise. Empty when none do."""
    lines = []
    seedlings = _answer(osp, "g3_0_seeds", "seedlings_used") or []
    if isinstance(seedlings, list) and "own_organic" in seedlings:
        lines.append(
            "[REVIEW] G3.1 is marked not applicable, but G3.0 states the operation grows its own organic seedlings. "
            "CCOF G3.1 A1 lists annual seedlings."
        )
    if _answer(osp, "g3_2_planting_stock", "stock_sold_as_organic") == "sold_organic_stock":
        lines.append(
            "[REVIEW] G3.1 is marked not applicable, but G3.0b states the operation sells planting stock as organic. "
            "CCOF G3.1 A1 lists planting stock or nursery production in pots."
        )
    systems = _answer(osp, "g4_0_rotation_soil", "system_type") or []
    if isinstance(systems, list) and "container" in systems:
        lines.append("[REVIEW] G3.1 is marked not applicable, but G4.0 names a container production system.")
    if osp.establishment_id:
        parcels = list(
            osp.establishment.parcels.filter(container_production=True).order_by("name").values_list("name", flat=True)
        )
        if parcels:
            lines.append(
                "[REVIEW] G3.1 is marked not applicable, but these parcels are recorded as container or greenhouse "
                f"production: {', '.join(parcels)}."
            )
        from history.models import History

        indoor = History.objects.filter(parcel__establishment_id=osp.establishment_id, is_outdoor=False).count()
        if indoor:
            lines.append(
                "[REVIEW] G3.1 is marked not applicable, but "
                f"{indoor} production{'s are' if indoor != 1 else ' is'} recorded as indoor."
            )
    return lines
