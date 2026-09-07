"""
One reading of "the materials on this plan", and an honest account of where it disagrees with the
logged applications.

The defect this replaces, found on the pilot farm 2026-08-27: a single renewal packet carried FOUR
renderings of the operation's materials and they did not agree.

    modules/materials_application.pdf   7 rows — the renderer read two of the three registries and
                                        silently dropped the WSDA-listed products, under a heading
                                        that said "OMRI / WSDA"
    01-organic-system-plan.pdf           9 rows — all three registries
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

from certifications.services.registry_identifiers import wsda_identifier_label


@dataclass(frozen=True)
class PlanMaterial:
    """One row the operator has put on the plan."""

    name: str
    source: str  # "National List" | "OMRI" | "WSDA"
    identifier: str = ""
    manufacturer: str = ""
    # Why the operator uses it, and whether they use it TODAY. Both are asked per-row by CCOF,
    # by WSDA AGR 2196, and by the Common OSP's Materials List attachment — and both exist only
    # on the operator-authored source (`PlanMaterialEntry`). A catalog listing says a product is
    # allowed; it cannot say this operation uses it. Empty on the three catalog sources, and
    # that is the honest state rather than a gap to paper over: nobody has said it yet.
    reason: str = ""
    status: str = ""  # PlanMaterialEntry.STATUS_PLANNED | STATUS_IN_USE | "" (not stated)
    # § 205.602 substances are PROHIBITED in organic crop production and live in the same National
    # List catalogue as the § 205.601 allowed ones. The write path refuses to attach one
    # (`add_approved_input`, 2026-08-28), but a row that predates that guard — or one added through
    # the ORM by a seeder or a shell — would otherwise print here as an ordinary input on the plan.
    # Defence in depth: the reading of the list refuses to render it as ordinary.
    prohibited: bool = False
    #: Primary key of the row this came from, in its own table, so a caller that has to WRITE
    #: back to it (the Materials List editor) does not have to re-find it by name. Paired with
    #: `source`, which says which table.
    source_id: object = None
    #: `PlanMaterialEntry.pk` when the operator has a row of their own for this product, whatever
    #: `source` ends up saying. Kept separate from `source_id` because a folded row is filed
    #: under the CATALOG it is listed on — that is where a certifier looks for it — while the
    #: thing a caller has to write back to is still the entry.
    entry_id: object = None

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


#: `PlanMaterial.source` -> the `PlanMaterialEntry` FK that would prove the entry IS that
#: catalog row. Used to decide whether an entry may inherit the catalog's registration number:
#: a shared NAME is not a listing, and taking the identifier on a name match alone would let an
#: operator-entered row print someone else's OMRI number.
_CATALOG_FK_BY_SOURCE = {
    "National List": "national_list_substance_id",
    "OMRI": "omri_product_id",
    "WSDA": "wsda_material_id",
}


def _fold(row: PlanMaterial, entry_names: set, folded: dict) -> bool:
    """Set the catalog row aside for its entry to inherit from. True when it was folded."""
    key = _norm(row.name)
    if key not in entry_names:
        return False
    folded.setdefault(key, []).append(row)
    return True


def _fold_into_entry(entry, catalog_rows: list) -> PlanMaterial:
    """One printed row for a product the operator has ALSO attached from a catalog.

    The operator's answers win — they are the only ones on offer. What the entry inherits is
    strictly what only the catalog row holds:

      manufacturer  taken when the entry has none. A blank maker on a Materials List is a cell
                    the certifier asks about, and the catalog knows it.
      identifier    taken ONLY when the entry's own FK points at that exact catalog row. Its
                    `listing_statement` already says "OMRI listed"; the number is the half a
                    reviewer can look up. Matching on the NAME alone here would print a
                    registration onto a row whose basis is "no third-party listing" — the claim
                    inflation `PlanMaterialEntry` exists to prevent, arrived at sideways.
    """
    manufacturer = entry.manufacturer
    identifier = entry.listing_statement
    source, source_id = "Operator-entered", entry.pk
    for row in catalog_rows:
        if not manufacturer and row.manufacturer:
            manufacturer = row.manufacturer
        fk = _CATALOG_FK_BY_SOURCE.get(row.source)
        if not fk or getattr(entry, fk, None) != row.source_id:
            continue
        # The entry IS this listing, by its own foreign key. So the row keeps the catalog's
        # heading — a reviewer looks for a listed product under the registry that lists it, and
        # filing it under "Operator-entered" because the grower typed a reason next to it would
        # move it out from under the heading where it belongs.
        source, source_id = row.source, row.source_id
        if row.identifier:
            identifier = row.identifier
    return PlanMaterial(
        name=entry.product_name,
        source=source,
        identifier=identifier,
        manufacturer=manufacturer,
        reason=entry.reason_for_use or "",
        status=entry.status or "",
        source_id=source_id,
        entry_id=entry.pk,
    )


def plan_materials(osp) -> list[PlanMaterial]:
    """Every material on the plan, across ALL FOUR sources.

    Reading a subset is the bug this function exists to make impossible to repeat: any caller
    that wants "the plan's materials" gets all of them or none.

    ⚠️ FOUR, not three. The three catalog registries (National List / OMRI / WSDA) plus the
    operator-entered `plan_material_entries` that shipped 2026-08-28 — the CCOF NOPB41 §A case
    (compost, manure, gypsum, limestone) no catalog can supply. This docstring said "ALL THREE"
    for ten days after the fourth source existed, which is precisely the kind of stale lead-in
    that lets the next reader write another two-of-N renderer in good faith.
    """
    # ⚠️ EVERY catalog source is read before the entries are emitted, not just the ones that
    # happen to come first. The entries used to sit third of four, so a WSDA attachment — read
    # fourth — was folded AFTER its entry had already been built, and the entry inherited
    # nothing: exactly the identifier-and-manufacturer loss this fold exists to prevent, still
    # live for one of the three registries. Two passes, so source ORDER cannot decide
    # correctness.
    entries = list(osp.plan_material_entries.all())
    entry_names = {_norm(e.product_name) for e in entries}
    folded: dict = {}

    national_list: list[PlanMaterial] = []
    omri: list[PlanMaterial] = []
    wsda: list[PlanMaterial] = []

    for sub in osp.approved_national_list_substances.all():
        name = getattr(sub, "substance_name", "") or str(sub)
        row = PlanMaterial(
            name=name,
            source="National List",
            identifier=getattr(sub, "cfr_section", "") or "",
            prohibited=(getattr(sub, "status", "") or "").lower() == "prohibited",
            source_id=sub.pk,
        )
        # ⛔ A PROHIBITED substance is never folded away. The § 205.602 marker lives on this row
        # and on no other, so an operator row that happens to share its name would hide the one
        # line telling a reviewer to take the material off the plan. Printing it twice is the
        # lesser failure by a wide margin.
        if row.prohibited or not _fold(row, entry_names, folded):
            national_list.append(row)

    for prod in osp.approved_omri_products.all():
        # OMRI's own published code (company letters + number) — real, and it deep-links
        # to a live certificate at omri.org/mfg/<letters>/certificate/<number>. Labelled
        # so the reader knows which registry the string belongs to.
        omri_id = getattr(prod, "omri_id", "") or ""
        name = getattr(prod, "product_name", "") or str(prod)
        row = PlanMaterial(
            name=name,
            source="OMRI",
            identifier=f"OMRI #{omri_id}" if omri_id else "",
            manufacturer=getattr(prod, "manufacturer", "") or "",
            source_id=prod.pk,
        )
        if not _fold(row, entry_names, folded):
            omri.append(row)

    for mat in osp.approved_wsda_materials.all():
        # A real WSDA Product # is a bare integer; the seeded `WSDA-REG-…` strings are
        # Trazo inventions and print as nothing at all rather than as a registration a
        # certifier can look up and will not find. `str(mat)` is deliberately NOT the
        # name fallback here — WSDAMaterial.__str__ embeds that same identifier.
        name = getattr(mat, "brand_name", "") or ""
        row = PlanMaterial(
            name=name,
            source="WSDA",
            identifier=wsda_identifier_label(getattr(mat, "wsda_id", "")),
            manufacturer=getattr(mat, "manufacturer", "") or "",
            source_id=mat.pk,
        )
        if not _fold(row, entry_names, folded):
            wsda.append(row)

    # Operator-authored rows — the fourth source, and the one CCOF's own prompt asks for
    # (compost, manure, gypsum, limestone) that no catalog can supply. Its `listing_statement`
    # says exactly what the basis supports and never more: an unlisted material renders as
    # "no third-party listing on file", never as listed or approved.
    operator = [_fold_into_entry(entry, folded.get(_norm(entry.product_name), [])) for entry in entries]

    return national_list + omri + operator + wsda


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
    for row in _material_rows(establishment):
        # 🔴 2026-09-07: this loop still unpacked `_material_rows` as a 2-tuple of
        # `(kind, event)` after it began yielding `MaterialRow` dataclasses, so EVERY call
        # raised `TypeError: cannot unpack non-iterable MaterialRow object`. The readiness
        # check swallowed it and silently stopped reporting logged-but-unplanned materials;
        # `generate_osp_packet` did not, and the renewal packet could not be built at all.
        #
        # Read the row's own `name` rather than reaching back through `event` for the
        # per-model column: the row builder already resolved which column that is, and
        # duplicating the choice here is what let the two drift in the first place.
        #
        # `kind == "plan"` rows carry no event — declared on the plan, never applied. This
        # function answers what the RECORDS show was applied, so they are not its names;
        # including them would make every declared material match itself and empty the
        # unmatched list, which is the finding the plan exists to surface.
        if row.event is None:
            continue
        name = (row.name or "").strip()
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


def materials_list_rows(osp) -> list[dict]:
    """The Materials List exactly as the attachment renders it, plus what it takes to finish it.

    ONE reading, shared with the workbook: the row set comes from `_material_rows` and every
    displayed cell from that workbook's own column helpers. The editor and the generated
    attachment therefore cannot disagree about what is blank — which is the whole point, because
    the editor exists to fill the attachment's blanks and an editor that showed a different set
    of them would be worse than none.

    `entry_id` is the row's handle for writing: present when the operator already has a row of
    their own for this product, None when the answer would create one. `source` says where the
    product came from, because the three cases read differently to a certifier — declared on the
    plan, found in the records, or both.
    """
    from certifications.services.common_osp_workbooks import (
        _material_manufacturer,
        _material_reason,
        _material_rows,
        _material_use,
    )

    rows = []
    for row in _material_rows(osp.establishment, osp=osp):
        in_use, intended = _material_use(row)
        plan = row.plan
        rows.append(
            {
                "name": row.name,
                "manufacturer": _material_manufacturer(row) or "",
                "reason": _material_reason(row) or "",
                "status": getattr(plan, "status", "") or "",
                "in_use": in_use is not None,
                "intended_for_use": intended is not None,
                # "both" is not decoration: a material the records show was applied but which is
                # NOT on the plan is the finding `unmatched_logged_materials` reports, and the
                # operator answering here is how they resolve it.
                "source": (
                    "both"
                    if (row.event is not None and plan is not None)
                    else ("plan" if plan is not None else "records")
                ),
                "listing": getattr(plan, "identifier", "") or "",
                "entry_id": getattr(plan, "entry_id", None),
            }
        )
    return rows
