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

from dataclasses import dataclass, replace
from typing import Optional

from certifications.services.national_list_citations import citation_paragraphs, citation_with_uses
from certifications.services.registry_identifiers import wsda_identifier_label


@dataclass(frozen=True)
class PlanMaterial:
    """One row the operator has put on the plan."""

    name: str
    source: str  # "National List" | NONSYNTHETIC_SOURCE | "OMRI" | "WSDA"
    identifier: str = ""
    manufacturer: str = ""
    # Why the operator uses it, and whether they use it TODAY. Both are asked per-row by CCOF,
    # by WSDA AGR 2196, and by the Common OSP's Materials List attachment — and both exist only
    # on the operator-authored source (`PlanMaterialEntry`). A catalog listing says a product is
    # allowed; it cannot say this operation uses it. Empty on the three catalog sources, and
    # that is the honest state rather than a gap to paper over: nobody has said it yet.
    reason: str = ""
    status: str = ""  # PlanMaterialEntry.STATUS_PLANNED | STATUS_IN_USE | "" (not stated)
    #: Which section of the certifier's materials form the operator filed the row under
    #: (`PlanMaterialEntry.CATEGORY_CHOICES`: fertilizer_amendment | pest_disease_weed |
    #: production_aid | post_harvest | other). Operator rows only; a catalog row says what a
    #: product IS, not what this operation uses it for, so it carries "".
    category: str = ""
    # § 205.602 substances are PROHIBITED in organic crop production and live in the same National
    # List catalogue as the § 205.601 allowed ones. The write path refuses to attach one
    # (`add_approved_input`, 2026-08-28), but a row that predates that guard — or one added through
    # the ORM by a seeder or a shell — would otherwise print here as an ordinary input on the plan.
    # Defence in depth: the reading of the list refuses to render it as ordinary.
    prohibited: bool = False
    #: The use the rule allows for a § 205.602 row it prohibits otherwise ((c) calcium chloride,
    #: (e) potassium chloride, (h) sodium nitrate), in the rule's words as the catalogue stores
    #: them; "" for every other row. NOT `prohibited`: the plan may carry the material, and the
    #: certifier checks the recorded use against this text (2026-11-06; until then every one of
    #: the three printed "PROHIBITED ... remove from this plan").
    condition: str = ""
    #: The plan's own G4.0 answer to a calcium chloride condition: the physiological disorder the operation
    #: states it treats, set only when G4.0 also says the material is applied as a foliar spray. "" otherwise.
    #: It moves the line from a question for the operation to a statement of where the answer is; it does
    #: not say the use meets the rule.
    condition_answered: str = ""
    #: Edition date on which OMRI's published list stopped carrying this product, as ISO text;
    #: "" while it is still listed. OMRI listings lapse: 6 of the 9,230 products on the
    #: 2026-09-05 edition were gone from the 2026-09-26 one, all six returning HTTP 404 at
    #: their own certificate URL. Re-seeding never noticed, because `update_or_create` only
    #: touches rows the new file contains, so a withdrawn product kept printing here as an
    #: ordinary OMRI listing: a third-party claim nobody held any more.
    #:
    #: NOT `prohibited`. A lapsed listing means OMRI no longer vouches for the product, not
    #: that the substance is barred under § 205.602; the material may still be perfectly
    #: allowed. The row also stays ON the plan: the operator did approve it, and dropping it
    #: would empty their § 205.201(a)(2) materials list. What lapses is the claim, not the record.
    delisted_on: str = ""
    #: Primary key of the row this came from, in its own table, so a caller that has to WRITE
    #: back to it (the Materials List editor) does not have to re-find it by name. Paired with
    #: `source`, which says which table.
    source_id: object = None
    #: The agent's review as the operator recorded it (`PlanMaterialEntry.agent_review_statement`),
    #: "" when none is. Operator rows only: a catalog listing is never an agent's approval.
    agent_review: str = ""
    #: `PlanMaterialEntry.pk` when the operator has a row of their own for this product, whatever
    #: `source` ends up saying. Kept separate from `source_id` because a folded row is filed
    #: under the CATALOG it is listed on — that is where a certifier looks for it — while the
    #: thing a caller has to write back to is still the entry.
    entry_id: object = None
    #: `PlanMaterialEntry.label_document_id`: the label or container photo the operator filed for
    #: this product, None when none is. Operator rows only.
    label_document_id: object = None
    #: The National List paragraphs alone, "§ 205.601(e)(6), (i)(6)", for the app, which shows the
    #: reference beside the row. `identifier` carries the use the rule lists each under, in the
    #: rule's English, for the certifier's packet; the app is read in Spanish too.
    listing_ref: str = ""
    #: CCOF §F/§G, on a `facility_pest` row only: the National List type (or `not_national_list`), where in
    #: the facility it is used, and whether it is applied by fumigation or fogging (None: not stated).
    facility_material_type: str = ""
    where_used: str = ""
    applied_by_fumigation: Optional[bool] = None
    #: OTCO C11's OTHER review agency, as the operator records it: "<agency>, <reference>". Operator
    #: rows only, and never on an OMRI or WSDA row (the serializer refuses it there).
    other_review: str = ""
    #: True when the operator's row for a National List or nonsynthetic substance carries the
    #: substance's own name: the answers are about the substance, and the product applied is still
    #: unnamed. Until 2026-11-16 any operator row suppressed "brand and formulation not stated", so
    #: stating only a use for "Lime sulfur" made the line read as if its brand had been given.
    brand_unstated: bool = False

    @property
    def review_position(self) -> str:
        """Which box of OTCO C11's review-agency cell this row's own record fills: "omri", "wsda" or
        "other". A lapsed OMRI listing is no longer OMRI's review."""
        if self.source == "OMRI" and not self.delisted_on:
            return "omri"
        if self.source == "WSDA":
            return "wsda"
        return "other"

    def review_notes(self) -> list[str]:
        """The [REVIEW] and restricted-use sentences `display` appends, one per line."""
        notes = []
        if self.prohibited:
            notes.append("[REVIEW] PROHIBITED in organic production — remove from this plan")
        elif self.condition and self.condition_answered:
            notes.append(
                f"restricted use: {self.condition} The restriction is answered in G4.0: applied as a foliar "
                f"spray, disorder stated as {self.condition_answered}."
            )
        elif self.condition:
            notes.append(f"[REVIEW] restricted use: {self.condition}")
        if self.delisted_on:
            notes.append(
                f"[REVIEW] no longer on the OMRI list as of {self.delisted_on}; "
                "confirm the product's status with your certifier"
            )
        return notes

    @property
    def names_a_substance_only(self) -> bool:
        """A National List or nonsynthetic substance with no product named for it."""
        named_substance = self.source in ("National List", NONSYNTHETIC_SOURCE)
        return named_substance and (self.entry_id is None or self.brand_unstated) and not self.prohibited

    @property
    def needs_label(self) -> bool:
        """OTCO C11 11.1: "Labels or photos of container are attached for each product that is not
        OMRI or WSDA listed." A National List substance is not an OMRI or WSDA listing, and an OMRI
        listing that has lapsed no longer is one."""
        listed = self.source in ("OMRI", "WSDA") and not self.delisted_on
        return not listed and not self.prohibited

    def display(self, stated_absences: bool = False) -> str:
        """The ONE author of a material's line: name — manufacturer — identifier.

        `stated_absences=True` is the certifier-facing form (module PDF, plan snapshot): every
        column CCOF ORGB41 §A/§B, WSDA AGR 2196 and OTCO C11 ask for on EVERY row is either
        filled or stated as missing — "manufacturer not stated", "reason for use not stated",
        and for a bare National List substance "brand and formulation not stated" (the row
        names a substance, not the product applied). Until 2026-09-09 a missing cell was a
        silent omission, indistinguishable on paper from a row that never needed it, on the
        one artifact OTCO says it "cannot review and will not approve" without a manufacturer.
        The default stays compact for the editor and the narrative.
        """
        bits = [self.name]
        if stated_absences and self.names_a_substance_only:
            bits.append("brand and formulation not stated")
        if self.manufacturer:
            bits.append(self.manufacturer)
        elif stated_absences:
            bits.append("manufacturer not stated")
        if self.identifier:
            bits.append(self.identifier)
        if stated_absences:
            # "reason for use: …", the column's own name: "for {reason}" printed "for Holds soil pH down"
            # whenever the operator began the reason with a capital (packet review, 2026-10-31).
            bits.append(f"reason for use: {self.reason}" if self.reason else "reason for use not stated")
            # In use or intended for use is a column on CCOF ORGB41's list instructions, USDA's
            # Materials List and OTCO C11 ("in use or intended for use"); the row stated neither
            # until 2026-11-04 (reviewer reads).
            bits.append(_STATUS_WORDS.get(self.status, "use not stated"))
            if self.agent_review:
                bits.append(self.agent_review)
        line = " — ".join(bits)
        for note in self.review_notes():
            line += f" {note}"
        return line


def _norm(value) -> str:
    return " ".join(str(value or "").split()).strip().lower()


#: `PlanMaterial.source` for a catalogue row that is NOT a National List entry — a nonsynthetic
#: substance (spinosad, Bt, d-limonene) allowed without any listing. Its own heading, because a
#: row printed under "National List" is read as a listing by anyone who sees it there.
NONSYNTHETIC_SOURCE = "Nonsynthetic, no National List entry"

#: `PlanMaterial.source` -> the `PlanMaterialEntry` FK that would prove the entry IS that
#: catalog row. Used to decide whether an entry may inherit the catalog's registration number:
#: a shared NAME is not a listing, and taking the identifier on a name match alone would let an
#: operator-entered row print someone else's OMRI number.
_CATALOG_FK_BY_SOURCE = {
    "National List": "national_list_substance_id",
    NONSYNTHETIC_SOURCE: "national_list_substance_id",
    "OMRI": "omri_product_id",
    "WSDA": "wsda_material_id",
}


def _fold(row: PlanMaterial, entry_names: set, folded: dict, entry_by_link: Optional[dict] = None) -> bool:
    """Set the catalog row aside for its entry to inherit from. True when it was folded.

    An entry claims a catalog row by NAME, or by its own foreign key to that exact row: "Rex Lime
    Sulfur" linked to the National List's "Lime sulfur" is that listing, and printing the substance
    again beside it, as "brand and formulation not stated, reason for use not stated", put a phantom
    material on the certifier's list (packet review, 2026-10-31). A shared name alone never links.
    """
    key = _norm(row.name)
    if key not in entry_names:
        key = (entry_by_link or {}).get((_LINK_SOURCE.get(row.source, row.source), row.source_id))
        if key is None:
            return False
    folded.setdefault(key, []).append(row)
    return True


#: `PlanMaterial.source` -> the key `entry_by_link` files an entry's foreign key under.
_LINK_SOURCE = {NONSYNTHETIC_SOURCE: "National List"}


#: A material's use, in the words its line prints. No " — " in any: `display` joins on it.
_STATUS_WORDS = {"in_use": "in use", "planned": "intended for use", "discontinued": "no longer used"}


def _fold_into_entry(entry, catalog_rows: list, linked_conditions: Optional[dict] = None) -> PlanMaterial:
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
    delisted_on = ""
    listing_ref = ""
    brand_unstated = False
    # The substance's own condition, whether the entry claimed the listing by name or by its
    # foreign key: the rule restricts the substance, whatever the product is called.
    condition = (linked_conditions or {}).get(getattr(entry, "national_list_substance_id", None), "")
    for row in catalog_rows:
        if not manufacturer and row.manufacturer:
            manufacturer = row.manufacturer
        if row.condition and not condition:
            condition = row.condition
        fk = _CATALOG_FK_BY_SOURCE.get(row.source)
        if not fk or getattr(entry, fk, None) != row.source_id:
            continue
        # The entry IS this listing, by its own foreign key. So the row keeps the catalog's
        # heading — a reviewer looks for a listed product under the registry that lists it, and
        # filing it under "Operator-entered" because the grower typed a reason next to it would
        # move it out from under the heading where it belongs.
        source, source_id = row.source, row.source_id
        # A nonsynthetic substance has no listing to cite, and its row says so by its heading. The
        # entry's own `listing_statement` ("National List substance", from the basis the attach gives
        # it) would print a listing the substance does not have.
        if row.identifier or row.source == NONSYNTHETIC_SOURCE:
            identifier = row.identifier
            listing_ref = row.listing_ref
        if row.source in ("National List", NONSYNTHETIC_SOURCE) and _norm(entry.product_name) == _norm(row.name):
            brand_unstated = True
        # A lapse travels with the listing it belongs to. OMRI rows do not reach here (a
        # delisted one is held back from the fold above), but promoting `source` and
        # `identifier` without this would make any future folding source assert a listing its
        # own registry had withdrawn.
        if row.delisted_on:
            delisted_on = row.delisted_on
    return PlanMaterial(
        name=entry.product_name,
        source=source,
        identifier=identifier,
        manufacturer=manufacturer,
        reason=entry.reason_for_use or "",
        status=entry.status or "",
        category=entry.category or "",
        facility_material_type=getattr(entry, "facility_material_type", "") or "",
        where_used=getattr(entry, "where_used", "") or "",
        applied_by_fumigation=getattr(entry, "applied_by_fumigation", None),
        source_id=source_id,
        entry_id=entry.pk,
        delisted_on=delisted_on,
        agent_review=entry.agent_review_statement,
        label_document_id=entry.label_document_id,
        listing_ref=listing_ref,
        condition=condition,
        other_review=_other_review(entry),
        brand_unstated=brand_unstated,
    )


def _other_review(entry) -> str:
    agency = (getattr(entry, "other_review_agency", "") or "").strip()
    reference = (getattr(entry, "other_review_reference", "") or "").strip()
    if not agency:
        return f"agency not named, {reference}" if reference else ""
    return f"{agency}, {reference}" if reference else agency


def _condition(substance) -> str:
    """The stored condition of a § 205.602 row the rule allows for a stated use, else "".

    The typed `is_conditionally_permitted` decides, never whether the note has text: a
    § 205.105 rationale note grants nothing (`NationalListSubstance.annotation_kind`)."""
    if substance is None or not getattr(substance, "is_conditionally_permitted", False):
        return ""
    return (getattr(substance, "restriction_notes", "") or "").strip()


def plan_materials(osp) -> list[PlanMaterial]:
    """Every material on the plan, across ALL FOUR sources.

    Reading a subset is the bug this function exists to make impossible to repeat: any caller
    that wants "the plan's materials" gets all of them or none.

    ⚠️ FOUR, not three. The three catalog registries (National List / OMRI / WSDA) plus the
    operator-entered `plan_material_entries` that shipped 2026-08-28 — the CCOF ORGB41 §A case
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
    entry_by_link: dict = {}
    for e in entries:
        for source, attr in (
            ("National List", "national_list_substance_id"),
            ("OMRI", "omri_product_id"),
            ("WSDA", "wsda_material_id"),
        ):
            if getattr(e, attr, None) is not None:
                entry_by_link.setdefault((source, getattr(e, attr)), _norm(e.product_name))
    folded: dict = {}
    #: The label each operator entry holds, by the key `_fold` files entries under. A row held back
    #: from the fold (a lapsed OMRI listing, a prohibited substance) still prints beside its entry,
    #: so it states the same label rather than "none on file" for a product whose label is on file
    #: (review of back #292).
    label_by_key = {_norm(e.product_name): e.label_document_id for e in entries if e.label_document_id}

    def _entry_label(row: PlanMaterial):
        key = _norm(row.name)
        if key not in entry_names:
            key = entry_by_link.get((_LINK_SOURCE.get(row.source, row.source), row.source_id))
        return label_by_key.get(key)

    national_list: list[PlanMaterial] = []
    omri: list[PlanMaterial] = []
    wsda: list[PlanMaterial] = []

    for sub in osp.approved_national_list_substances.all():
        name = getattr(sub, "substance_name", "") or str(sub)
        listed = getattr(sub, "is_national_list_entry", True)
        row = PlanMaterial(
            name=name,
            source="National List" if listed else NONSYNTHETIC_SOURCE,
            # Where the rule lists the substance, to the paragraph and with the use it is listed
            # for: "§ 205.601(e)(6) insecticide, (i)(6) crop disease control". A bare "§ 205.601"
            # left the reviewer to find the paragraph (WSDA reviewer read, 2026-11-04), and the
            # catalogue's one stored letter was wrong for a substance listed under several. A row
            # the citation table does not name keeps the section alone. A nonsynthetic row has no
            # section to print.
            identifier=(
                (citation_with_uses(sub) or f"§ {sub.cfr_section}")
                if listed and getattr(sub, "cfr_section", "")
                else ""
            ),
            listing_ref=(citation_paragraphs(sub) if listed and getattr(sub, "cfr_section", "") else ""),
            prohibited=(getattr(sub, "status", "") or "").lower() == "prohibited"
            and not getattr(sub, "is_conditionally_permitted", False),
            condition=_condition(sub),
            source_id=sub.pk,
        )
        # ⛔ A PROHIBITED substance is never folded away. The § 205.602 marker lives on this row
        # and on no other, so an operator row that happens to share its name would hide the one
        # line telling a reviewer to take the material off the plan. Printing it twice is the
        # lesser failure by a wide margin.
        if row.prohibited or not _fold(row, entry_names, folded, entry_by_link):
            national_list.append(replace(row, label_document_id=_entry_label(row)))

    for prod in osp.approved_omri_products.all():
        # OMRI's own published code (company letters + number) — real, and it deep-links
        # to a live certificate at omri.org/mfg/<letters>/certificate/<number>. Labelled
        # so the reader knows which registry the string belongs to.
        omri_id = getattr(prod, "omri_id", "") or ""
        name = getattr(prod, "product_name", "") or str(prod)
        delisted = getattr(prod, "delisted_on", None)
        row = PlanMaterial(
            name=name,
            source="OMRI",
            identifier=f"OMRI #{omri_id}" if omri_id else "",
            manufacturer=getattr(prod, "manufacturer", "") or "",
            source_id=prod.pk,
            delisted_on=delisted.isoformat() if delisted else "",
        )
        # A WITHDRAWN listing is never folded away, for the same reason a prohibited substance
        # is not. `_fold_into_entry` promotes this row's `source` and `identifier` onto the
        # operator's entry, so folding would print "OMRI #<id>" on a merged row while dropping
        # the one line saying OMRI no longer lists it: the exact claim this flag exists to
        # stop, reassembled. Reachable in practice, because `_listing_basis_for` links an
        # operator entry to an approved OMRI product by normalized name, which is the fold
        # condition. Printing the product twice is the lesser failure.
        if row.delisted_on or not _fold(row, entry_names, folded, entry_by_link):
            omri.append(replace(row, label_document_id=_entry_label(row)))

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
        if not _fold(row, entry_names, folded, entry_by_link):
            wsda.append(row)

    # Operator-authored rows — the fourth source, and the one CCOF's own prompt asks for
    # (compost, manure, gypsum, limestone) that no catalog can supply. Its `listing_statement`
    # says exactly what the basis supports and never more: an unlisted material renders as
    # "no third-party listing on file", never as listed or approved.
    # The condition of every conditional row an entry links by its own foreign key, in ONE query
    # and only when an entry links one: reading `entry.national_list_substance` per row is a query
    # per entry, and the viewset's prefetch of the entries does not cover the substance.
    linked_ids = {e.national_list_substance_id for e in entries if getattr(e, "national_list_substance_id", None)}
    linked_conditions: dict = {}
    if linked_ids:
        from certifications.models import NationalListSubstance

        linked_conditions = {
            sub.pk: _condition(sub)
            for sub in NationalListSubstance.objects.filter(
                pk__in=linked_ids, annotation_kind=NationalListSubstance.ANNOTATION_CONDITION
            )
            if _condition(sub)
        }
    operator = [
        _fold_into_entry(entry, folded.get(_norm(entry.product_name), []), linked_conditions) for entry in entries
    ]

    return _with_g4_answers(osp, national_list + omri + operator + wsda)


#: The words of § 205.602(c)'s condition that G4.0's calcium chloride questions ask about.
_CALCIUM_CONDITION_WORDS = "calcium uptake"


def _with_g4_answers(osp, rows: list) -> list:
    """Mark a calcium chloride row whose restriction the plan's own G4.0 answers address.

    G4.0 asks whether calcium chloride is applied as a foliar spray (`calcium_chloride_foliar`) and which
    physiological disorder it treats (`calcium_chloride_disorder`), the two halves of § 205.602(c). With both
    answered the row stops being an open question; a missing or negative answer leaves it a review line.
    """
    if not any(r.condition and _CALCIUM_CONDITION_WORDS in r.condition.lower() for r in rows):
        return rows
    from certifications.osp_modules.conditions import answer_value

    answers = ((osp.module_responses or {}).get("modules") or {}).get("g4_0_rotation_soil", {}).get("answers") or {}
    disorder = answer_value(answers, "calcium_chloride_disorder")
    disorder = " ".join(disorder.split()).rstrip(".") if isinstance(disorder, str) else ""
    if not (
        answer_value(answers, "applies_calcium_chloride") is True
        and answer_value(answers, "calcium_chloride_foliar") is True
        and disorder
    ):
        return rows
    # G4.0 asks about field use; its own coaching calls a post-harvest calcium chloride dip handling.
    # A row the operator filed under post-harvest keeps its review line.
    return [
        (
            replace(r, condition_answered=disorder)
            if r.condition and _CALCIUM_CONDITION_WORDS in r.condition.lower() and r.category != "post_harvest"
            else r
        )
        for r in rows
    ]


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
    """Logged product names that THIS plan's materials list does not hold.

    Read from the Materials List workbook's own rows for `osp`: a logged row with no plan row is a
    name with no exact match on the plan and no current identity decision folding it into a listed
    product (`_apply_identity_decisions` merges those and drops the logged row). It is the one
    reading of "not on the plan": the materials page and each Materials Application category line
    print from it (review of back #279).

    Until 2026-11-04 the rows were built for the establishment's CURRENT plan (`_current_osp`, the
    active one) and only then compared with `osp` by name. On a draft that drops a product the
    active plan lists, a logged name the operator had tied to that product was folded away by the
    active plan's list and never reported for the draft, which does not hold it.

    UNMATCHED, not unapproved. A brand legitimately covered by a National List substance entry
    lands here too until the operator ties the two, and saying otherwise would invent a compliance
    finding out of a naming difference.
    """
    from certifications.services.common_osp_workbooks import _material_rows

    names: list[str] = []
    seen: set[str] = set()
    for row in _material_rows(osp.establishment, osp=osp):
        if row.event is None or row.plan is not None:
            continue
        name = (row.name or "").strip()
        if name and _norm(name) not in seen:
            seen.add(_norm(name))
            names.append(name)
    return names


#: The agents whose materials form asks for a label or container photo of an unlisted product.
#: OTCO C11 11.1 does; CCOF's Materials Application and WSDA AGR 2196 do not (read 2026-11-04).
LABEL_ASKING_AGENTS = frozenset({"otco"})


def labels_asked_for(osp) -> bool:
    from certifications.services.packet_coverage import packet_agent

    return (packet_agent(osp).slug or "") in LABEL_ASKING_AGENTS


# ---------------------------------------------------------------------------
# OTCO C11 Crop Materials List: the four columns, from the same rows
# ---------------------------------------------------------------------------

#: Agents whose materials form is OTCO's C11 table (rev. 2023/09/14, source hash checked 2026-11-16):
#: Full Product Name, Full Manufacturer Name, Third Party Review Agency (OMRI / WSDA / OTHER) and
#: Intended Use, one row per product. For their plans the module page prints the list in those columns.
C11_TABLE_AGENTS = frozenset({"otco"})


def c11_table_asked(osp) -> bool:
    from certifications.services.packet_coverage import packet_agent

    return (packet_agent(osp).slug or "") in C11_TABLE_AGENTS


#: C11's Intended Use is a category word ("Fertility, Pest Control, Post-Harvest Sanitation"), which is
#: `PlanMaterialEntry.category`'s granularity. Words of their own: the category's picker labels name
#: CCOF's sections, which have no place on another agent's page.
C11_USE_WORDS = {
    "fertilizer_amendment": "Fertility and soil amendment",
    "pest_disease_weed": "Pest, disease or weed control",
    "production_aid": "Production aid (seed treatment, growing media, adjuvant)",
    "post_harvest": "Post-harvest (wash water, sanitation)",
    "facility_pest": "Pest control in facilities",
    "other": "Other",
}


def c11_product_cell(row: PlanMaterial) -> list[str]:
    lines = [row.name]
    if row.names_a_substance_only:
        lines.append("brand and formulation not stated")
    return lines


def c11_review_cell(row: PlanMaterial) -> list[str]:
    """OMRI, WSDA or Other, from the row's own record, and what that record is.

    The OMRI and WSDA boxes are the catalog listing the operator attached (Trazo resolved the name;
    the operator confirmed it), never a review Trazo made. Other is the agency the operator names.
    A row with neither says so rather than ticking a box nobody ticked.
    """
    position = row.review_position
    if position == "omri":
        return ["OMRI", row.identifier or "OMRI listed"]
    if position == "wsda":
        return ["WSDA", row.identifier or "WSDA Brand Name Material List"]
    lines = [f"Other: {row.other_review}" if row.other_review else "No review agency named"]
    if row.source == "National List":
        lines.append(f"National List substance, {row.identifier}" if row.identifier else "National List substance")
    elif row.source == NONSYNTHETIC_SOURCE:
        lines.append("nonsynthetic, no National List entry")
    elif row.source == "OMRI":
        lines.append(f"OMRI listing lapsed as of {row.delisted_on}")
    elif row.identifier:
        lines.append(row.identifier)
    return lines


def c11_use_cell(row: PlanMaterial) -> list[str]:
    return [
        C11_USE_WORDS.get(row.category, "use category not stated"),
        f"reason for use: {row.reason}" if row.reason else "reason for use not stated",
        _STATUS_WORDS.get(row.status, "use not stated"),
    ]


def materials_changes_since_filing(osp) -> Optional[dict]:
    """What was added to and taken off the materials list since the plan was last filed.

    OTCO C11's second mode ("The products identified below are to be added to my current Materials
    List") and CCOF's materials list update both ask for the additions apart from the standing list.
    The window opens at the newest filing in the plan's lineage (this version's own, else the version
    it continues) and runs to now; a plan never filed has no additions, only its list. Read from the
    append-only change log, catalog and operator-entered alike. Net per material: a product added and
    then taken off again inside the window is neither.
    """
    from certifications.models import ApprovedInputChangeLog

    lineage, filed, cursor = [], None, osp
    while cursor is not None and cursor.pk not in lineage:
        lineage.append(cursor.pk)
        if filed is None and cursor.submitted_at:
            filed = cursor.submitted_at
        cursor = cursor.previous_version
    if filed is None:
        return None
    first: dict = {}
    last: dict = {}
    for log in ApprovedInputChangeLog.objects.filter(osp_id__in=lineage, changed_at__gt=filed).order_by(
        "changed_at", "pk"
    ):
        key = _norm(log.target_name_at_change)
        first.setdefault(key, log)
        last[key] = log
    # Net both ways: added then taken off is neither, and taken off then put back (a product already on
    # the filed list) is neither too (review of back #457).
    added = [
        (log.target_name_at_change, log.changed_at.date().isoformat())
        for key, log in last.items()
        if log.action == ApprovedInputChangeLog.ACTION_ADDED
        and first[key].action != ApprovedInputChangeLog.ACTION_REMOVED
    ]
    removed = [
        (log.target_name_at_change, log.changed_at.date().isoformat())
        for key, log in last.items()
        if log.action == ApprovedInputChangeLog.ACTION_REMOVED
        and first[key].action != ApprovedInputChangeLog.ACTION_ADDED
    ]
    return {"since": filed.date().isoformat(), "added": added, "removed": removed}


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

    entries = {
        entry.pk: entry
        for entry in osp.plan_material_entries.select_related("label_document", "omri_product", "wsda_material")
    }
    labels_asked = labels_asked_for(osp)
    rows = []
    for row in _material_rows(osp.establishment, osp=osp):
        in_use, intended = _material_use(row)
        plan = row.plan
        entry = entries.get(getattr(plan, "entry_id", None))
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
                "listing": getattr(plan, "listing_ref", "") or getattr(plan, "identifier", "") or "",
                "entry_id": getattr(plan, "entry_id", None),
                # The operator's own row's answers, "" until there is one (a catalog-only material
                # gets a row the first time one is answered).
                "category": getattr(entry, "category", "") or "",
                "agent_review": getattr(entry, "agent_review", "") or "",
                "agent_review_date": entry.agent_review_date.isoformat() if entry and entry.agent_review_date else "",
                "agent_review_reference": getattr(entry, "agent_review_reference", "") or "",
                "agent_review_use": getattr(entry, "agent_review_use", "") or "",
                "agent_review_statement": getattr(entry, "agent_review_statement", "") or "",
                "label_document": getattr(entry, "label_document_id", None),
                # CCOF §F/§G, answered on a facility pest row.
                "facility_material_type": getattr(entry, "facility_material_type", "") or "",
                "where_used": getattr(entry, "where_used", "") or "",
                "applied_by_fumigation": getattr(entry, "applied_by_fumigation", None),
                "label_document_title": entry.label_document.title if entry and entry.label_document_id else "",
                # OTCO C11's review agency: which box the row's own record fills, and the Other agency
                # the operator names when it is neither OMRI nor WSDA.
                "review_position": _review_position(plan, entry),
                "other_review_agency": getattr(entry, "other_review_agency", "") or "",
                "other_review_reference": getattr(entry, "other_review_reference", "") or "",
                # Only an OTCO plan asks for the label; the editor offers the upload on every row.
                "needs_label": labels_asked and (plan is None or plan.needs_label),
            }
        )
    return rows


def _review_position(plan, entry) -> str:
    """The row's review box for the editor. The entry's own listing decides when it has one, by the same
    rule the serializer refuses an Other agency on (`PlanMaterialEntry.listing_review_position`), so the
    editor never offers an agency the server would refuse, nor hides one from a lapsed listing."""
    if entry is not None and entry.listing_basis in ("omri", "wsda"):
        return entry.listing_review_position
    return plan.review_position if plan is not None else "other"


# ---------------------------------------------------------------------------
# "No materials used" — a statement, checked against what the records show
# ---------------------------------------------------------------------------

#: Category "none used" statements on the Materials Application, and the logged ChemicalEvent
#: types that would contradict each. Post-harvest contact materials and crop production aids are
#: checked separately below: a sanitizer's record is a ProductionEvent of type PH naming a
#: `sanitizer_name`, and a production aid is a seed treatment on a planting record or a tank-mix
#: partner on an application record, neither of which a ChemicalEvent type classifies.
NONE_USED_CATEGORIES = {
    "fertilizers_none_used": (("FE",), "fertilizer or soil amendment"),
    "pest_disease_weed_none_used": (("PE", "HE", "FU"), "pest, disease or weed-control"),
}


def logged_post_harvest_sanitizers(establishment) -> list[str]:
    """Distinct wash-water sanitizer names on the operation's post-harvest processing records."""
    from history.models import ProductionEvent

    names = (
        ProductionEvent.objects.filter(history__parcel__establishment=establishment, type="PH")
        .exclude(sanitizer_name__isnull=True)
        .exclude(sanitizer_name="")
        .values_list("sanitizer_name", flat=True)
    )
    return sorted({(n or "").strip() for n in names if (n or "").strip()})


def post_harvest_listing_review(osp) -> list[str]:
    """A wash-water sanitizer on the records, set against a plan that lists none under § 205.605.

    🔴 2026-09-10 (OTCO desk read) — the flume sanitizer printed as "Peracetic acid — § 205.601".
    § 205.601(a) lists sanitizers for crop production; sanitizers for post-harvest wash and rinse
    water are listed at § 205.605(b) (eCFR, Title 7 issue of 2026-09-04: peracetic acid "for use
    in wash and/or rinse water according to FDA limitations"). This names the mismatch and never
    rules on it — which listing covers a product is the operator's statement and the certifier's
    call. Silent when the plan already carries a § 205.605 substance, or when the operator has
    filed post-harvest rows of their own, whose listing basis prints on each row.
    """
    logged = logged_post_harvest_sanitizers(osp.establishment)
    if not logged:
        return []
    substances = list(osp.approved_national_list_substances.all())
    if any(s.cfr_section == "205.605" for s in substances):
        return []
    if osp.plan_material_entries.filter(category="post_harvest").exists():
        return []
    shown = ", ".join(logged)
    crop_only = sorted(s.substance_name for s in substances if s.cfr_section == "205.601" and s.category == "sanitizer")
    if crop_only:
        return [
            f"[REVIEW] The post-harvest records log a wash-water sanitizer ({shown}). Sanitizers for "
            "post-harvest wash and rinse water are listed at § 205.605(b); this plan lists "
            f"{', '.join(crop_only)} only under § 205.601, which covers crop production. Confirm the "
            "listing that covers each product."
        ]
    return [
        f"[REVIEW] The post-harvest records log a wash-water sanitizer ({shown}), and this plan lists no "
        "§ 205.605 substance. Sanitizers for post-harvest wash and rinse water are listed at "
        "§ 205.605(b); add the entry that covers each product."
    ]


def none_used_contradictions(osp, answers: dict) -> list[str]:
    """Statements that no materials are used, set against the plan and the logged applications.

    Returns one "[REVIEW] …" sentence per contradiction. The statement is the operator's and
    stays on the page; this names the records that disagree so a reviewer sees both — never a
    silent drop of either side (CCOF ORGB41 Header C, OTCO C11 Hdr-2).
    """
    from certifications.osp_modules.conditions import answer_value

    out: list[str] = []
    if answer_value(answers, "no_materials_used") is True:
        on_plan = plan_materials(osp)
        logged = logged_material_names(osp.establishment)
        if on_plan or logged:
            bits = []
            if on_plan:
                bits.append(f"{len(on_plan)} material(s) are on this plan's list")
            if logged:
                shown = ", ".join(logged[:6]) + (f", and {len(logged) - 6} more" if len(logged) > 6 else "")
                bits.append(f"{len(logged)} product(s) appear in the logged applications ({shown})")
            out.append(
                "[REVIEW] The plan states that no input materials or substances are used, but "
                + " and ".join(bits)
                + ". Both are shown; the records are not reconciled here."
            )

    from history.models import ChemicalEvent

    for key, (types, label) in NONE_USED_CATEGORIES.items():
        if answer_value(answers, key) is not True:
            continue
        events = ChemicalEvent.objects.filter(history__parcel__establishment=osp.establishment, type__in=types)
        count = events.count()
        if not count:
            continue
        named = sorted({(e.commercial_name or "").strip() for e in events if (e.commercial_name or "").strip()})
        shown = ", ".join(named[:6]) + (f", and {len(named) - 6} more" if len(named) > 6 else "")
        out.append(
            f"[REVIEW] The plan states that no {label} materials are used, but {count} {label} "
            f"application(s) are logged"
            + (f" ({shown})" if shown else "")
            + ". Both are shown; the records are not reconciled here."
        )

    if answer_value(answers, "crop_production_aids_none_used") is True:
        from certifications.services.osp_prefill import logged_category_names

        aids = logged_category_names(osp.establishment, "crop_production_aids_listed")
        listed = sorted(
            {
                (e.product_name or "").strip()
                for e in osp.plan_material_entries.filter(category="production_aid")
                if (e.product_name or "").strip()
            }
        )
        if aids or listed:
            bits = []
            if listed:
                bits.append(f"this plan's own list holds {len(listed)} ({', '.join(listed[:6])})")
            if aids:
                shown = ", ".join(aids[:6]) + (f", and {len(aids) - 6} more" if len(aids) > 6 else "")
                bits.append(
                    f"the records name {len(aids)} ({shown}) as a seed treatment on a planting or a tank-mix "
                    "partner or adjuvant on an application"
                )
            out.append(
                "[REVIEW] The plan states that no seed treatments, growing media or adjuvants are used, but "
                + " and ".join(bits)
                + ". Both are shown; the records are not reconciled here."
            )

    if answer_value(answers, "post_harvest_contact_none_used") is True:
        sanitizers = logged_post_harvest_sanitizers(osp.establishment)
        if sanitizers:
            shown = ", ".join(sanitizers[:6]) + (f", and {len(sanitizers) - 6} more" if len(sanitizers) > 6 else "")
            out.append(
                "[REVIEW] The plan states that no post-harvest contact materials are used, but the "
                f"post-harvest processing records name a wash-water sanitizer ({shown}). Both are shown; "
                "the records are not reconciled here."
            )
    return out
