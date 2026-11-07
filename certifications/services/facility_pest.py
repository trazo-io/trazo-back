"""Pest control materials used in handling and storage facilities: CCOF Materials Application §F and §G.

§F: "Table, by National List material type — Ammonium carbonate, Boric acid, Botanical pesticides, Carbon
dioxide, Diatomaceous earth, Nitrogen gas, Nonsynthetic bait/lure/repellent, Pheromones, Pyrethrum/pyrethrins,
Sticky traps, Vitamin D3 — each with Used?, Where Used, and Applied by fumigation/fogging? (Yes/No)."
§G: "List any pest control material used in a post-harvest handling or crop-storage facility that does not
fit a §F National List type ... Non-National List Material, Where Used, Applied by fumigation/fogging?"

The rows are the operator's own materials-list entries filed under `facility_pest`. § 205.271(d) allows a
synthetic not on the National List only when the handler and the certifying agent agree on the substance,
method and contact prevention, so a §G row prints the agent's review as the operator recorded it, and a
[REVIEW] when none is recorded. G9.0's `material_tier` answer is read against the same rows.
"""

from __future__ import annotations

from dataclasses import dataclass

NOT_NATIONAL_LIST = "not_national_list"


@dataclass(frozen=True)
class FacilityTypeRow:
    label: str
    products: tuple
    where_used: tuple
    fumigation: str  # "Yes" | "No" | "not stated" | "" (type not used)

    @property
    def used(self) -> bool:
        return bool(self.products)


def facility_entries(osp):
    return list(osp.plan_material_entries.filter(category="facility_pest").order_by("product_name", "pk"))


def _fumigation_word(values) -> str:
    stated = {v for v in values if v is not None}
    if not values:
        return ""
    if True in stated:
        return "Yes"
    if stated == {False} and None not in values:
        return "No"
    return "not stated"


def section_f(entries) -> list[FacilityTypeRow]:
    """One row per National List type CCOF lists, in its order, whether used or not."""
    from certifications.models import PlanMaterialEntry

    out = []
    for value, label in PlanMaterialEntry.FACILITY_MATERIAL_TYPE_CHOICES:
        if value == NOT_NATIONAL_LIST:
            continue
        mine = [e for e in entries if e.facility_material_type == value]
        out.append(
            FacilityTypeRow(
                label=label,
                products=tuple(e.product_name for e in mine),
                where_used=tuple(e.where_used for e in mine if (e.where_used or "").strip()),
                fumigation=_fumigation_word([e.applied_by_fumigation for e in mine]),
            )
        )
    return out


def section_g(entries) -> list:
    return [e for e in entries if e.facility_material_type == NOT_NATIONAL_LIST]


def untyped(entries) -> list:
    return [e for e in entries if not e.facility_material_type]


def agreement_recorded(entry) -> bool:
    from certifications.models import PlanMaterialEntry

    return entry.agent_review == PlanMaterialEntry.REVIEW_APPROVED


def entry_review_lines(entries) -> list[str]:
    """[REVIEW]s the rows raise by themselves."""
    lines = []
    for e in section_g(entries):
        if not agreement_recorded(e):
            lines.append(
                f"[REVIEW] {e.product_name} is not a National List type and no agreement with the certifying agent "
                "is recorded for it; § 205.271(d) allows such a material only when the handler and the agent agree on "
                "the substance, the method and how contact with the product is prevented."
            )
    for e in untyped(entries):
        lines.append(
            f"[REVIEW] {e.product_name} is filed as facility pest control without its National List type, so it "
            "cannot be placed on the §F table or the §G list."
        )
    return lines


def tier_review_lines(tier, entries) -> list[str]:
    """[REVIEW]s for G9.0's material answer read against the materials list."""
    if not tier:
        return []
    lines = []
    if tier in ("national_list", "synthetic_approved") and not entries:
        lines.append(
            "[REVIEW] The plan says pest control materials are used in its structures, and its materials list holds "
            "none filed under pest control in handling and storage facilities."
        )
    if tier == "none" and entries:
        names = ", ".join(e.product_name for e in entries)
        lines.append(
            f"[REVIEW] The plan says no pest control material is used in its structures, and its materials list "
            f"holds these under facility pest control: {names}."
        )
    if tier == "national_list" and section_g(entries):
        names = ", ".join(e.product_name for e in section_g(entries))
        lines.append(
            f"[REVIEW] The plan says only National List materials are used in its structures, and its materials "
            f"list holds materials that are not a National List type: {names} (§ 205.271(d))."
        )
    return lines
