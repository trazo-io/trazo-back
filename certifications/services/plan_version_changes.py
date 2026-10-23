"""
Which sections of the plan changed between two versions, read from the versions themselves.

Oregon Tilth's OSP Update Form Step 4 asks the operation to "list updated OSP sections and attach"
them. The § 205.406(a)(2) additions and deletions on the annual update cannot answer that: the
annual-update card stores them as the operator's free-text lines, so there is no section to read.
The two plan versions the update moved between can. `osp_fork.fork_plan` copies every answer, the
three catalogue lists and the operator's materials rows into the new version, so anything that
differs between them is a change the operator made to the new version.

What counts as a change:

  * a module's answers: the VALUE of each answer and the module's not-applicable election. Each
    stored answer also carries the time it was written (`at`), and re-saving the same value moves
    it, so comparing whole answer dicts would report a section the operator only re-saved.
    Status, completion stamps and definition version are bookkeeping and are not compared.
  * the materials list: the approved National List / OMRI / WSDA entries and the operator's own
    `PlanMaterialEntry` rows, compared by content. The rows are copied on fork, so their ids and
    `created_by` always differ and say nothing about the plan.

What it does not see: land. Parcels belong to the establishment, not to a plan version, so a
parcel added this year is in both versions' packets. `parcels_begun_since` is the separate,
operator-stated reading of that.

This is a comparison of stored answers. It does not review a change or judge whether one needs
the agent's approval.
"""

from __future__ import annotations

from datetime import date

#: The module whose content includes the catalogue lists and `PlanMaterialEntry` rows.
MATERIALS_MODULE_KEY = "materials_application"

#: `PlanMaterialEntry` fields that are the operator's statement about a material. `id`, `osp`,
#: `created_by` and timestamps change on every fork and are left out.
_MATERIAL_ENTRY_FIELDS = (
    "product_name",
    "manufacturer",
    "category",
    "reason_for_use",
    "status",
    "listing_basis",
    "omri_product_id",
    "wsda_material_id",
    "national_list_substance_id",
    "certifier_letter_reference",
    "notes",
)


def _module_content(osp, key: str) -> tuple:
    """(not-applicable election, {question: value}) for one module, with write times removed."""
    module = ((osp.module_responses or {}).get("modules") or {}).get(key) or {}
    answers = {}
    for question, answer in (module.get("answers") or {}).items():
        value = answer.get("value") if isinstance(answer, dict) else answer
        # An answer cleared back to empty is the same plan as one never given.
        if value in (None, "", [], {}):
            continue
        answers[question] = value
    return bool(module.get("not_applicable")), answers


def _materials_content(osp) -> tuple:
    entries = sorted(
        tuple("" if value is None else str(value).strip() for value in row)
        for row in osp.plan_material_entries.values_list(*_MATERIAL_ENTRY_FIELDS)
    )
    return (
        sorted(osp.approved_national_list_substances.values_list("pk", flat=True)),
        sorted(osp.approved_omri_products.values_list("pk", flat=True)),
        sorted(osp.approved_wsda_materials.values_list("pk", flat=True)),
        entries,
    )


def changed_module_keys(prior, new) -> list[str]:
    """Keys of the modules whose content differs between `prior` and `new`, in packet order."""
    from certifications.osp_modules import MODULE_REGISTRY

    materials_changed = _materials_content(prior) != _materials_content(new)
    changed = []
    for module in MODULE_REGISTRY:
        if _module_content(prior, module.key) != _module_content(new, module.key) or (
            module.key == MATERIALS_MODULE_KEY and materials_changed
        ):
            changed.append(module.key)
    return changed


def plan_reference_date(osp) -> tuple[date | None, str]:
    """(the date a plan version counts from, how the plan states it): submitted, else effective."""
    if osp.submitted_at is not None:
        return osp.submitted_at.date(), "submitted"
    if osp.effective_date is not None:
        return osp.effective_date, "effective"
    return None, ""


def parcels_begun_since(establishment, since: date) -> tuple[list, list]:
    """(parcels whose stated management start is on or after `since`, parcels that state none).

    `date_began_managing` is the operator's own answer (the CCOF land-history affidavit date). A
    parcel without one is reported as not stated, never as not new.
    """
    parcels = list(establishment.parcels.order_by("name", "id"))
    begun = [p for p in parcels if p.date_began_managing is not None and p.date_began_managing >= since]
    unstated = [p for p in parcels if p.date_began_managing is None]
    return begun, unstated
