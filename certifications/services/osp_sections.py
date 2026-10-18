"""
Which § 205.201(a) narratives count as having text, in one place.

Three surfaces answer "how many of the six sections have text?" and they must give the same
number:

    the submit gate          `OrganicSystemPlanViewSet.submit` refuses a blank, brief or padded
                             section
    the OSP page             "{n} of 6 narrative sections have text", which also holds (a)(2)
                             back while the inputs registry and the narrative disagree
    the onboarding checklist ticks "has text in all six sections" and shows the same count

Until 2026-10-17 the checklist read `section_completion`, which counts any non-blank narrative.
One character in each of the six ticked the item while the OSP page said "0 of 6" and submit
refused the plan. `section_completion` keeps its old meaning for its other readers; the count a
person sees comes from here.
"""

from certifications.models import OSP_SECTION_KEYS


def sections_missing_text(osp):
    """Section keys that are blank, under the material floor, or padded. The submit gate's rule."""
    from history.services.audit_export_service import OSP_NARRATIVE_MATERIAL_FLOOR, looks_like_padding

    missing = []
    for key in OSP_SECTION_KEYS:
        section = (osp.sections or {}).get(key, {}) or {}
        narrative = (section.get("narrative") or "").strip()
        if len(narrative) < OSP_NARRATIVE_MATERIAL_FLOOR or looks_like_padding(narrative):
            missing.append(key)
    return missing


def registry_sync_diff(osp):
    """Inputs registry against the (a)(2) narrative, as the PDF snapshot reports it."""
    from certifications.services.plan_materials import plan_materials
    from history.services.audit_export_service import (
        OSP_NARRATIVE_MATERIAL_FLOOR,
        REGISTRY_THIN_THRESHOLD,
        _compute_registry_sync_diff,
    )

    sections = osp.sections or {}
    narrative = (sections.get("inputs_list") or {}).get("narrative", "") or ""
    diff = _compute_registry_sync_diff(
        inputs_narrative=narrative,
        plan_rows=plan_materials(osp),
    )
    narrative_len = len(narrative.strip())
    missing_from_narrative = [e for e in diff["registry_entries"] if not e["in_narrative"]]
    # Derive the same REVIEW condition the PDF surfaces so the frontend banner
    # can show an identical message and farmers don't get mixed signals.
    has_warning = bool(missing_from_narrative) or (
        narrative_len >= OSP_NARRATIVE_MATERIAL_FLOOR and diff["registry_total"] < REGISTRY_THIN_THRESHOLD
    )
    return {
        "registry_total": diff["registry_total"],
        "narrative_char_count": narrative_len,
        "entries_not_in_narrative": [{"source": e["source"], "name": e["name"]} for e in missing_from_narrative],
        "has_warning": has_warning,
    }


def sections_with_text(osp, diff=None):
    """How many of the six have text, counted the way the OSP page counts them.

    The submit gate's rule, plus (a)(2) held back while `registry_sync_diff` warns. Pass `diff`
    when the caller already computed it.
    """
    missing = set(sections_missing_text(osp))
    if "inputs_list" not in missing:
        if diff is None:
            diff = registry_sync_diff(osp)
        if diff["has_warning"]:
            missing.add("inputs_list")
    return len(OSP_SECTION_KEYS) - len(missing)
