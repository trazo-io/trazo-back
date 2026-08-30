"""
One reading of "the materials on this plan", and an honest account of where it disagrees with the
logged applications.

The defect this replaces, found on the pilot farm 2026-08-27: a single renewal packet carried FOUR
renderings of the operation's materials and they did not agree.

    modules/materials_application.pdf   7 rows — the renderer read two of the three registries and
                                        silently dropped the WSDA-listed products, under a heading
                                        that said "OMRI / WSDA"
    01-narrative-snapshot.pdf           9 rows — all three registries
    the per-lot audit export            9 rows, plus a table declaring a product "Listed — not on
                                        OSP" that its own drift section had cleared
    workbooks/materials_list.xlsx      10 rows — derived from logged application events instead

Exact-name overlap between the registry and the workbook was ONE row. Beneath all of it the module
prints five attestations that every material in use is "entered in this list".

Two different questions were being answered by surfaces that looked like the same list:

    what the operator has PUT ON THE PLAN     the three registries (National List / OMRI / WSDA)
    what the records show was APPLIED         distinct product names on chemical and soil events

Both are legitimate — CCOF's own form asks for the first, and the USDA workbook is built from the
second — so the fix is not to make one of them win. It is to compute them together, state which
logged products could not be matched to a plan entry, and stop leaving the reader to notice.

## Why matching is deliberately conservative

A logged product is a BRAND ("Rex Lime Sulfur", "Tiger 90CR elemental sulfur"); a National List row
is a SUBSTANCE ("Lime sulfur", "Elemental sulfur"). Fuzzy-matching those would quietly mark a
material as covered when nobody decided that it was — the same class of invention this codebase
keeps removing. So matching is exact-ish (case- and whitespace-insensitive, nothing more) and the
unmatched list is reported as *unmatched*, never as *unapproved*: the wording has to leave room for
a brand that is genuinely covered by a substance entry.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanMaterial:
    """One row the operator has put on the plan."""

    name: str
    source: str  # "National List" | "OMRI" | "WSDA"
    identifier: str = ""
    manufacturer: str = ""
    # § 205.602 substances are PROHIBITED in organic crop production and live in the same National
    # List catalogue as the § 205.601 allowed ones. The write path refuses to attach one
    # (`add_approved_input`, 2026-08-28), but a row that predates that guard — or one added through
    # the ORM by a seeder or a shell — would otherwise print here as an ordinary input on the plan.
    # Defence in depth: the reading of the list refuses to render it as ordinary.
    prohibited: bool = False

    def display(self) -> str:
        bits = [self.name]
        if self.manufacturer:
            bits.append(self.manufacturer)
        if self.identifier:
            bits.append(self.identifier)
        line = " — ".join(bits)
        if self.prohibited:
            line += " [REVIEW] PROHIBITED in organic production — remove from this plan"
        return line


def _norm(value) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def plan_materials(osp) -> list[PlanMaterial]:
    """Every material on the plan, across ALL THREE registries.

    Reading two of the three is the bug this function exists to make impossible to repeat: any
    caller that wants "the plan's materials" gets all of them or none.
    """
    rows: list[PlanMaterial] = []

    for sub in osp.approved_national_list_substances.all():
        rows.append(
            PlanMaterial(
                name=getattr(sub, "substance_name", "") or str(sub),
                source="National List",
                identifier=getattr(sub, "cfr_section", "") or "",
                prohibited=(getattr(sub, "status", "") or "").lower() == "prohibited",
            )
        )
    for prod in osp.approved_omri_products.all():
        rows.append(
            PlanMaterial(
                name=getattr(prod, "product_name", "") or str(prod),
                source="OMRI",
                identifier=getattr(prod, "omri_id", "") or "",
                manufacturer=getattr(prod, "manufacturer", "") or "",
            )
        )
    # Operator-authored rows — the fourth source, and the one CCOF's own prompt asks for
    # (compost, manure, gypsum, limestone) that no catalog can supply. Its `listing_statement`
    # says exactly what the basis supports and never more: an unlisted material renders as
    # "operator-entered; no third-party listing on file", never as listed or approved.
    for entry in osp.plan_material_entries.all():
        rows.append(
            PlanMaterial(
                name=entry.product_name,
                source="Operator-entered",
                identifier=entry.listing_statement,
                manufacturer=entry.manufacturer,
            )
        )
    for mat in osp.approved_wsda_materials.all():
        rows.append(
            PlanMaterial(
                name=getattr(mat, "brand_name", "") or str(mat),
                source="WSDA",
                identifier=getattr(mat, "wsda_id", "") or "",
                manufacturer=getattr(mat, "manufacturer", "") or "",
            )
        )
    return rows


def logged_material_names(establishment) -> list[str]:
    """Distinct product names the records show were applied.

    Calls the Materials List workbook's own row builder rather than repeating its query, so the
    reconciliation and the workbook cannot disagree about what "the logged materials" are. An
    earlier version of this function reimplemented the query and claimed in its docstring that the
    two could not drift — which was the same shape of untrue statement this whole module exists to
    remove, made about my own code.
    """
    from certifications.services.common_osp_workbooks import _material_rows

    names: list[str] = []
    seen: set[str] = set()
    for kind, event in _material_rows(establishment):
        raw = event.commercial_name if kind == "chemical" else event.amendment_product_name
        name = (raw or "").strip()
        if name and _norm(name) not in seen:
            seen.add(_norm(name))
            names.append(name)
    return names


def unmatched_logged_materials(osp) -> list[str]:
    """Logged product names with no exact match on the plan.

    UNMATCHED, not unapproved. A brand legitimately covered by a National List substance entry
    lands here too, and saying otherwise would invent a compliance finding out of a naming
    difference.
    """
    on_plan = {_norm(row.name) for row in plan_materials(osp)}
    return [name for name in logged_material_names(osp.establishment) if _norm(name) not in on_plan]
