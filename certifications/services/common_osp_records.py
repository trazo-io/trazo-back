"""
Common OSP § 11 "Records Maintained" — evidence derivation, NOT attestation.

## What this is

USDA AMS published the **Common Organic System Plan** (template files dated 2026-05-26; NOP
announcement 2026-07-07), developed by Quick Organics, Wolf & Associates and the Accredited
Certifiers Association. Its Section 11 — *Record Keeping and Traceability (§ 205.103)* — asks the
operation to check which record types it maintains, in four groups. Those checkbox lists are the
closest thing the industry has to an authoritative taxonomy of "every record an organic crop farm
keeps," which is why this module is keyed to them verbatim rather than to any competitor's UI.

Adoption of the Common OSP is **optional** — the AMS page says the NOP "strongly encourages"
certifiers to adopt it, not that anyone must. Nothing here assumes a given certifier uses it; the
same evidence answers the equivalent question on any certifier's own form.

## The hard rule: evidence is not an answer

§ 205.201(a) makes the **producer** the author of the organic system plan. A checkbox on § 11 is
the operator's assertion that their operation *maintains* a record type — an attestation to their
certifier. Trazo can observe that events exist in its own database. It cannot observe what is in
the farmer's filing cabinet, and it must never convert "we found 14 spray events" into "the
operator asserts they maintain input-application records."

So this module produces, per record type, exactly one of:

    EVIDENCED_IN_TRAZO      — Trazo holds records of this type (with a count and a basis string)
    NOT_EVIDENCED_IN_TRAZO  — Trazo holds none; the operation may still maintain them on paper

and never a boolean answer. The § 11 checkbox itself is set only by an explicit operator
confirmation (`confirm()` below), which stamps who confirmed it and when. An unconfirmed record
type renders as a *suggestion* in the UI and is excluded from any generated form output.

This is the same failure class the project has already shipped once and undone: a Smart Setup
template fabricated a backdated record attributed to the farmer by name (see the 2026-08-02 NOP
finalization QA), and a self-assigned grade was served as though externally verified. An
auto-ticked § 11 is that mistake with a regulator on the other end of it.

## Discipline for adding entries

Every record type carries the verbatim label from a REAL certifier form and a real CFR citation.
No entry may be added because a competitor has a screen for it. If Trazo cannot see evidence for a
record type, it stays in the registry as permanently NOT_EVIDENCED_IN_TRAZO — that is honest and
useful (the operator still ticks it if they keep weigh tickets in a drawer), and it is how the
operator learns which parts of their recordkeeping live outside this tool.

Two sources, marked in the registry: the Common OSP § 11 list, and a short block at the end
sourced from **WSDA AGR 2121-O** (Recordkeeping, R 02/25) question 2. WSDA names 17 record types
for balancing crops harvested against crops sold — bin ticket stubs, harvest pick sheets, pool
closings, CSA and farmers-market records among them — and the Common OSP list carries none of
them. Because only CONFIRMED rows print, a closed list does not merely omit a row: it makes that
record type undeclarable, and the certifier reads the silence. Every list that ends in "Other:"
is telling you the same thing, which is why `other_records` exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from certifications.services.restricted_materials import TISSUE_MATRICES

# Same emptiness rule the PUR export and per-event completeness registry already use:
# None, "", and whitespace-only all count as missing.
from common.field_registry import ORGANIC_UNRESOLVED_VALUES
from history.services.record_completeness import _present

logger = logging.getLogger(__name__)


def _has_content(value) -> bool:
    """Does this field actually record something?

    `_present()` alone is WRONG here. It was written for the chemical-event required-field
    registry, where every field is a string or a number, so it returns True for anything that
    is not None and not blank text. Applied to the field types this module reads, that produced
    fabricated evidence on real data:

      - `History.organic_on_invoice` is a `BooleanField(default=False)`. Every production
        defaults to False, so `_present(False)` → True reported "13 invoice records logged" on a
        farm where **zero** productions had it set.
      - `seed_search_attempts` and `water_test_results` are JSONFields that default to `[]`.
        `_present([])` → True reported "9 documented seed searches logged" where all nine were
        empty lists.

    Both would have put a fabricated count in front of a farmer as the basis for ticking a § 11
    checkbox — the auto-attestation failure this module exists to prevent, arriving through the
    evidence rather than through the checkbox.

    A False boolean is an explicit "no", not a record. An empty container is not a record either.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) > 0
    return _present(value)


EVIDENCED = "evidenced_in_trazo"
NOT_EVIDENCED = "not_evidenced_in_trazo"
# A record type whose evidence check itself failed. Deliberately NOT folded into
# NOT_EVIDENCED: "we could not look" and "we looked and found nothing" are different
# statements, and only one of them is safe to show a certifier. A swallowed AttributeError
# once rendered a farm holding 4 organic certificates as holding none.
UNKNOWN = "evidence_check_failed"

# Where operator confirmations live inside OrganicSystemPlan.sections. § 11 is a recordkeeping
# question, so it belongs under the (a)(4) section rather than in a new table — the JSONB is
# already versioned and auditlog-registered.
OSP_SECTION_KEY = "recordkeeping_description"
# Purchase and certificate records cite § 205.103(b)(2) — records that "span the time of purchase
# or acquisition ... and be traceable back to the last certified operation". They cited (b)(1),
# "adapted to the particular business", which says nothing about purchases (eCFR, 2026-09-11).
CONFIRMATIONS_KEY = "common_osp_records"


@dataclass(frozen=True)
class RecordType:
    """One § 11 checkbox.

    `label` is verbatim from OSP_Crop_WildCrop_V1.docx — do not reword it. The generated form and
    the certifier's own form must read identically, and a paraphrase is how a form stops matching.
    """

    key: str
    label: str
    group: str
    cfr_cite: str
    # (bundle) -> (count, basis) ; count == 0 means NOT_EVIDENCED_IN_TRAZO.
    evidence: Callable
    # Set when Trazo structurally cannot see this record type. Renders as an explicit
    # "maintained outside Trazo" hint rather than looking like a gap in the farm's records.
    external_by_design: bool = False
    # The operator names this one themselves. Both source forms end their record-type lists
    # with an "Other:" line, and a CLOSED list silently makes the un-listed record type
    # undeclarable — see the "Rows sourced from WSDA AGR 2121-O" note in the module docstring.
    # A free-text row may only be confirmed together with a label (enforced in `confirm()`).
    free_text: bool = False


# --------------------------------------------------------------------------------------
# Evidence bundle — every queryset read once, then counted many times.
# --------------------------------------------------------------------------------------


class EvidenceBundle:
    """Events + productions for one establishment, optionally windowed.

    Mirrors `OperationAuditExportService._productions()` windowing semantics (a production counts
    if it was active during the window) so the § 11 evidence and the certifier dossier never
    disagree about which season they are describing.
    """

    def __init__(self, establishment, start_date=None, end_date=None, osp=None):
        from django.db.models import Q

        from history.models import Production

        self.establishment = establishment
        # The plan the evidence is read for, when there is one: a suggestion that compares the
        # records with the plan's own lists (the materials rows) has nothing to compare without it.
        self.osp = osp
        self.start_date = start_date
        self.end_date = end_date

        qs = Production.objects.filter(parcel__establishment=establishment)
        if start_date:
            qs = qs.filter(Q(finish_date__gte=start_date) | Q(finish_date__isnull=True))
        if end_date:
            qs = qs.filter(start_date__lte=end_date)
        qs = qs.prefetch_related(
            "history_chemicalevent_events",
            "history_productionevent_events",
            "history_soilmanagementevent_events",
            "history_pestmanagementevent_events",
            "history_generalevent_events",
            "history_businessevent_events",
            "sales_records",
        )

        self.productions = list(qs)
        # Parcel-level evidence (buffer_zones etc.) is not windowed — a documented buffer
        # is a standing fact about the land, not an event inside the season.
        self.parcels = list(establishment.parcels.all())
        # `.live()`: a VOIDED sale is kept on the record but retracted by the operation, so it
        # is not evidence that an invoice or bill of lading exists for a shipment that happened.
        self.sales = [s for p in self.productions for s in p.sales_records.live()]
        self.chemical = [e for p in self.productions for e in p.history_chemicalevent_events.all()]
        self.production_events = [e for p in self.productions for e in p.history_productionevent_events.all()]
        self.soil = [e for p in self.productions for e in p.history_soilmanagementevent_events.all()]
        self.pest = [e for p in self.productions for e in p.history_pestmanagementevent_events.all()]
        self.general = [e for p in self.productions for e in p.history_generalevent_events.all()]
        self.business = [e for p in self.productions for e in p.history_businessevent_events.all()]

    # -- small helpers used by the registry ---------------------------------------------

    def prod(self, *types):
        return [e for e in self.production_events if e.type in types]

    def chem(self, *types):
        return [e for e in self.chemical if e.type in types]

    def soils(self, *types):
        return [e for e in self.soil if e.type in types]

    def pests(self, *types):
        return [e for e in self.pest if e.type in types]

    def with_field(self, events, *field_names):
        """Events where at least one of the named fields carries a value."""
        return [e for e in events if any(_has_content(getattr(e, f, None)) for f in field_names)]

    def chem_purpose(self, *purposes):
        """Chemical applications whose operator-chosen PURPOSE is one of `purposes`.

        `ChemicalEvent.application_purpose` is the only field in the model that carries a
        disease/pest/weed intent chosen by the operator. Reading it is how a purpose-scoped
        record type stays a purpose-scoped record type instead of drifting into "any event
        that happens to name a species".
        """
        return [e for e in self.chemical if getattr(e, "application_purpose", None) in purposes]

    @staticmethod
    def dedupe(events):
        """Distinct events, first occurrence wins.

        Two evidence filters may legitimately select the same row (a fungicide is both an
        `FU` subtype and an application whose purpose is disease management). Counting it
        twice inflates the basis string a farmer reads before ticking a § 11 box.
        """
        seen = set()
        out = []
        for e in events:
            marker = (type(e).__name__, getattr(e, "pk", None) or id(e))
            if marker in seen:
                continue
            seen.add(marker)
            out.append(e)
        return out

    def cleanouts(self, *asset_classes):
        """Equipment cleanouts of the named asset classes, by the same rule as `clean_out_records`:
        an `EM` activity that records a cleaning date or method. `cleaning_asset_class` says WHAT
        was cleaned (harvest bins, a transport vehicle)."""
        return [
            e
            for e in self.with_field(self.prod("EM"), "cleaning_date", "cleaning_method")
            if getattr(e, "cleaning_asset_class", None) in asset_classes
        ]

    def clean_transport_sales(self, *methods):
        """Live sales that record how the transport unit was kept clean: `clean_transport_method`
        (affidavit / inspected / dedicated) or the USDA affidavit's cleaning method. With `methods`,
        only those `clean_transport_method` values. Blank is "not documented", never "no"."""
        if methods:
            return [s for s in self.sales if getattr(s, "clean_transport_method", "") in methods]
        return self.with_field(self.sales, "clean_transport_method", "transport_cleaning_method")

    def legacy_transport_affidavits(self):
        """Productions whose clean-transport record is the legacy single-shipment affidavit flag.

        That flag and `SalesRecord.clean_transport_method` are the same fact from two editors, so a
        production counts here only while none of its live shipments documents clean transport,
        the rule the audit export applies (`audit_export_service`, "describe the SAME fact").
        """
        documented = {getattr(s, "production_id", None) for s in self.clean_transport_sales()}
        return [
            p
            for p in self.productions
            if getattr(p, "pk", None) not in documented
            and (
                getattr(p, "transport_affidavit_on_file", False)
                # A FieldFile is truthy only when a file is stored; an empty one is an object,
                # which `_has_content` would read as present.
                or bool(getattr(p, "transport_affidavit_document", None))
            )
        ]

    def business_extra(self, *keys):
        """Sale/Delivery BusinessEvents carrying at least one of the given extra_data keys.

        `bill_of_lading` / `purchase_order` / `invoice_number` are stored in
        `BusinessEvent.extra_data` (see `_solana_verde_finished_events.py`), and are deliberately
        stripped from every anonymous consumer payload by
        `EXTRA_DATA_SENSITIVE_SUBSTRINGS` — reading them here is certifier-side only.
        """
        out = []
        for e in self.business:
            data = e.extra_data or {}
            if any(_has_content(data.get(k)) for k in keys):
                out.append(e)
        return out


def _count(items, basis_singular, basis_plural=None, verb="logged"):
    n = len(items)
    if n == 0:
        return 0, ""
    word = basis_singular if n == 1 else (basis_plural or basis_singular + "s")
    return n, f"{n} {word} {verb}".strip()


# --------------------------------------------------------------------------------------
# The registry — verbatim § 11 labels, in the form's own order.
# --------------------------------------------------------------------------------------

GROUP_CROP = "What types of records do you maintain for organic crop production?"
GROUP_INPUTS = "What types of input and materials records do you maintain?"
GROUP_GENERAL = "What types of general production and management records do you maintain?"
GROUP_SALES = "What types of purchase, sales, and transport records do you maintain?"


COMMON_OSP_RECORD_TYPES: list[RecordType] = [
    # -- A. Organic crop production records — § 205.103(b)(2) ---------------------------
    RecordType(
        key="planting_records",
        label="Planting records",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.103(b)(2)",
        # TR (transplanting) is a planting activity for § 205.204 purposes — the seedling still
        # enters the field and still needs organic-status documentation.
        evidence=lambda b: _count(b.prod("PL", "TR"), "planting event"),
    ),
    RecordType(
        key="harvest_records",
        label="Harvest records",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.103(b)(2)",
        evidence=lambda b: _count(b.prod("HA"), "harvest event"),
    ),
    RecordType(
        key="pest_management",
        label="Pest management",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.206",
        # Both halves of § 205.206: the non-chemical tiers (scouting, beneficials, cultural
        # controls) and the substance applications that § 205.206(e) allows only after them.
        evidence=lambda b: _count(
            b.pest + b.chem("PE"),
            "pest-management event or pesticide spray",
            "pest-management events and pesticide sprays",
        ),
    ),
    RecordType(
        key="cultivation",
        label="Cultivation",
        group=GROUP_CROP,
        # Mechanical weed cultivation (the CU production subtype): § 205.206(c)(4). It cited
        # (a)(1), which is crop rotation and nutrient management, until 2026-11-17.
        cfr_cite="7 CFR 205.206(c)(4)",
        evidence=lambda b: _count(b.prod("CU"), "cultivation event"),
    ),
    RecordType(
        key="tillage",
        label="Tillage",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.203(a)",
        evidence=lambda b: _count(b.soils("TI"), "tillage event"),
    ),
    RecordType(
        key="input_material_application",
        label="Input/material application",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.103(b)(2)",
        # Every ChemicalEvent is an input application; soil amendments are applications too.
        evidence=lambda b: _count(
            b.chemical + b.with_field(b.soils("OM", "PA"), "amendment_product_name", "amendment_type"),
            # Says what it adds up, so it reconciles on sight with the plan's "Chemical / spray
            # records" count a few pages earlier (sprays there, sprays plus amendments here).
            "spray or soil-amendment application",
            "spray and soil-amendment applications",
        ),
    ),
    RecordType(
        key="weeding",
        label="Weeding",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.206(a)",
        # Mechanical (cultivation, mowing) and the herbicide route.
        evidence=lambda b: _count(b.prod("CU", "MO") + b.chem("HE"), "weed management event"),
    ),
    RecordType(
        key="mulching",
        label="Mulching",
        group=GROUP_CROP,
        # (c)(1) biodegradable mulch, (c)(6) plastic or synthetic mulch removed at season end.
        # Was "205.206(a)(6)", a paragraph that does not exist (2026-11 citation review).
        cfr_cite="7 CFR 205.206(c)(1) and (c)(6)",
        # Trazo has no dedicated mulching subtype. MO ("Mowing / Orchard-Floor") covers mowing,
        # mulching and floor management together, so an MO event is evidence of floor work but
        # NOT proof that mulch was applied — the basis string says so rather than overstating.
        evidence=lambda b: (
            len(b.prod("MO")),
            (
                f"{len(b.prod('MO'))} orchard-floor / mowing event{'' if len(b.prod('MO')) == 1 else 's'} logged — "
                "confirm whether these include mulching"
                if b.prod("MO")
                else ""
            ),
        ),
    ),
    RecordType(
        key="disease_management",
        label="Disease management",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.206",
        # 🔴 2026-09-06 — was `b.chem("FU") + b.with_field(b.pest, "pest_species")`.
        #
        # `pest_species` is a CORE field on every PestManagementEvent subtype (config/events/
        # pestEvent.ts renders it for SC/TM/BR/PI/TA/IP/CU alike), so it names the codling moth
        # a scout counted just as readily as a disease. Counting it here presented the farm's
        # entire insect-scouting programme as disease-management evidence: the pilot orchard
        # read "159 pest management records" and "153 disease management records" — the same
        # rows, twice, and the second number is not what it says it is.
        #
        # An operator ticks the § 11 box on the strength of that number. Fabricating it is the
        # same failure this module's docstring exists to prevent, arriving through the evidence
        # instead of through the checkbox — exactly like the `_present([])` and
        # `_present(False)` bugs above.
        #
        # `ChemicalEvent.application_purpose` ("disease_management") is the real, operator-chosen
        # signal and is used instead. PestManagementEvent has NO disease axis — no subtype, no
        # field — so pest events are not counted here at all. A farm whose disease work is all
        # non-chemical (sanitation pruning, resistant varieties) shows no evidence and ticks the
        # box from its own knowledge, which is the honest state.
        evidence=lambda b: _count(
            b.dedupe(b.chem("FU") + b.chem_purpose("disease_management")),
            "disease management record",
        ),
    ),
    RecordType(
        key="compost_production",
        label="Compost production records",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.203(c)(2)",
        evidence=lambda b: _count(b.soils("CO"), "compost production record"),
    ),
    RecordType(
        key="shared_equipment_cleaning",
        label="Shared equipment cleaning log",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.272(a)",
        evidence=lambda b: _count(
            b.with_field(b.prod("EM"), "cleaning_date", "cleaning_method", "cleaning_materials_used"),
            "equipment cleaning log entry",
            "equipment cleaning log entries",
        ),
    ),
    # -- B. Input and materials records -------------------------------------------------
    RecordType(
        key="non_gmo_seed_verification",
        label="Non-GMO seed verification",
        group=GROUP_INPUTS,
        cfr_cite="7 CFR 205.105(e)",
        evidence=lambda b: _count(
            b.with_field(b.prod("PL", "TR"), "seed_certification_status"),
            "seed record with certification status",
            "seed records with certification status",
        ),
    ),
    RecordType(
        key="input_material_usage",
        label="Input/material usage records",
        group=GROUP_INPUTS,
        cfr_cite="7 CFR 205.103(b)(2)",
        evidence=lambda b: _count(b.chemical, "spray record"),
    ),
    RecordType(
        key="untreated_seed_verification",
        label="Untreated seed verification",
        group=GROUP_INPUTS,
        cfr_cite="7 CFR 205.204(a)",
        evidence=lambda b: _count(
            b.with_field(b.prod("PL", "TR"), "seed_treatment"),
            "seed treatment record",
        ),
    ),
    RecordType(
        key="input_material_information",
        label="Input/material information (labels, SDS, etc.)",
        group=GROUP_INPUTS,
        cfr_cite="7 CFR 205.201(a)(2)",
        # Photos on a chemical event are how a label gets captured in Trazo today.
        evidence=lambda b: _count(
            [e for e in b.chemical if getattr(e, "album", None) and e.album.images.exists()],
            "input record with a label/document photo",
            "input records with label/document photos",
        ),
    ),
    RecordType(
        key="seed_search_commercial_availability",
        label="Seed search/Commercial availability",
        group=GROUP_INPUTS,
        cfr_cite="7 CFR 205.204(a)(1)",
        evidence=lambda b: _count(
            b.with_field(b.prod("PL", "TR"), "seed_search_attempts"),
            "documented seed search",
            "documented seed searches",
        ),
    ),
    RecordType(
        key="restricted_input_use_records",
        label=("Input use records verify all restricted inputs are used in accordance with their " "use restriction"),
        group=GROUP_INPUTS,
        cfr_cite="7 CFR 205.601",
        # Evidence = inputs matched against an approved-materials source (OMRI / National List)
        # or carrying an explicit organic-approval determination.
        evidence=lambda b: _count(
            # A confirmed classification only (Phase 5 slice 1); a guess checks nothing. A basis the
            # grower marked "Not yet confirmed" checks nothing either (review of back #125).
            [
                e
                for e in b.chemical
                if b.with_field([e], "omri_product", "confirmed_national_list_substance")
                or (
                    _has_content(getattr(e, "organic_approved", None))
                    and str(e.organic_approved).strip() not in ORGANIC_UNRESOLVED_VALUES
                )
            ],
            "input record checked against an approved-materials list",
            "input records checked against approved-materials lists",
        ),
    ),
    RecordType(
        key="purchase_receipts_invoices",
        label="Purchase receipts / invoices",
        group=GROUP_INPUTS,
        cfr_cite="7 CFR 205.103(b)(2)",
        # Amendments count as inputs here (2026-08-16). CCOF's grower checklist names
        # "fertilizer, compost, soil amendments, planting mixes" in one line and asks for
        # receipts; reading only ChemicalEvent told a compost-fed orchard it kept no input
        # purchase records at all.
        evidence=lambda b: _count(
            b.with_field(b.chemical, "purchase_invoice", "purchase_date", "supplier_name")
            + b.with_field(
                b.soil,
                "amendment_purchase_invoice",
                "amendment_purchase_date",
                "amendment_supplier_name",
            ),
            "input purchase record",
        ),
    ),
    # -- C. General production and management records -----------------------------------
    RecordType(
        key="monitoring_records",
        label="Monitoring records",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.201(a)(3)",
        evidence=lambda b: _count(b.pests("SC", "TM", "PI", "TA"), "monitoring record"),
    ),
    RecordType(
        key="clean_out_records",
        label="Clean out records",
        # § 205.272 is the HANDLING standard. A producer cleaning shared equipment between a
        # conventional buffer row and an organic block is doing it under § 205.201(a)(5), the
        # management practices and physical barriers the plan must describe (eCFR, 2026-09-12).
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.272(b)",
        evidence=lambda b: _count(
            b.with_field(b.prod("EM"), "cleaning_date", "cleaning_method"),
            "clean-out record",
        ),
    ),
    RecordType(
        # Label from the teardown's § 11 summary — verify verbatim against
        # OSP_Crop_WildCrop_V1.docx before GA (same rule as every label here).
        key="rotation_records",
        label="Crop rotation records",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.205",
        evidence=lambda b: _count(
            b.with_field(b.prod("PL", "TR"), "variety"),
            "planting record carrying crop identity for rotation history",
            "planting records carrying crop identity for rotation history",
        ),
    ),
    RecordType(
        key="drift_prevention_records",
        label="Drift prevention records",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.202(c)",
        evidence=lambda b: _count(
            [p for p in b.parcels if p.buffer_zones],
            "parcel with documented buffer/adjoining-land records",
            "parcels with documented buffer/adjoining-land records",
        ),
    ),
    RecordType(
        key="buffer_separation_records",
        label="Buffer harvest and sales separation records",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.202(c)",
        evidence=lambda b: _count(
            b.with_field(b.prod("HA"), "buffer_disposition"),
            "harvest record stating buffer-row disposition",
            "harvest records stating buffer-row disposition",
        ),
    ),
    RecordType(
        key="supplier_verification_records",
        label="Supplier and sourcing verification records",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)",
        evidence=lambda b: _count(
            b.with_field(b.chem(), "supplier_name") + b.with_field(b.soil, "amendment_supplier_name"),
            "input record naming its supplier",
            "input records naming their supplier",
        ),
    ),
    RecordType(
        key="storage_records",
        label="Storage records",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.272(a)",
        # `storage_location` on harvest/post-harvest events is the storage EVIDENCE signal;
        # the G6.2 Storage module (WS-2.7) collects the practice narrative separately.
        evidence=lambda b: _count(
            b.with_field(b.prod("HA", "PH"), "storage_location"),
            "harvest/post-harvest record naming a storage location",
            "harvest/post-harvest records naming a storage location",
        ),
    ),
    RecordType(
        key="inventory_records",
        label="Inventory records",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.103(b)(3)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="post_harvest_production",
        label="Post-harvest production records",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.270",
        evidence=lambda b: _count(b.prod("PH"), "post-harvest record"),
    ),
    RecordType(
        key="natural_resources_condition",
        label="Condition of natural resources, including soil and water quality",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.200",
        evidence=lambda b: _count(
            b.soils("ST", "LA") + b.with_field(b.production_events, "water_test_date", "water_test_results"),
            "soil or water condition record",
        ),
    ),
    # -- D. Purchase, sales, and transport records ---------------------------------------
    RecordType(
        key="organic_certificates",
        label="Organic certificates",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        # ⚠️ The reverse accessor is `structured_certifications`, NOT `certifications` —
        # `Establishment.certifications` is an unrelated TEXT field, so the obvious spelling
        # returns a string and blows up at `.all()`. Caught by a smoke test against real data;
        # the swallowed exception had rendered a farm with 4 certificates as having none.
        evidence=lambda b: _count(
            list(b.establishment.structured_certifications.all()),
            "organic certificate",
            "organic certificates",
            verb="on file",
        ),
    ),
    RecordType(
        key="weigh_tickets",
        label="Weigh tickets",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="bill_of_lading",
        label="Bill of Lading",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        # Two sources: legacy BusinessEvent extra_data + the per-shipment field on
        # SalesRecord rows (2026-08 transport block).
        evidence=lambda b: _count(
            b.business_extra("bill_of_lading") + b.with_field(b.sales, "bill_of_lading"),
            "sale record carrying a bill of lading",
            "sale records carrying a bill of lading",
        ),
    ),
    RecordType(
        key="delivery_slips",
        label="Delivery slips",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="packing_slips",
        label="Packing slips",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="purchase_records",
        label="Purchase records",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        evidence=lambda b: _count(
            b.with_field(b.chemical, "supplier_name", "purchase_date")
            + b.with_field(b.soil, "amendment_supplier_name", "amendment_purchase_date")
            + b.with_field(b.prod("PL", "TR"), "seed_supplier_name", "seed_purchase_date"),
            "purchase record",
        ),
    ),
    RecordType(
        key="invoices",
        label="Invoices",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        # 🔴 2026-08-16: `b.sales` was consulted exactly once in this whole registry, for
        # `bill_of_lading` — so an operation that recorded every sale WITH its invoice number
        # through the current sales editor was told it held no invoice records, and the § 11
        # checkbox arrived unsuggested. The legacy BusinessEvent extra_data path and the
        # production-level `organic_on_invoice` flag stay as fallbacks for pre-SalesRecord data.
        evidence=lambda b: _count(
            b.with_field(b.sales, "invoice_number")
            + b.business_extra("invoice_number")
            + [p for p in b.productions if _has_content(p.organic_on_invoice)],
            "invoice record",
        ),
    ),
    RecordType(
        key="settlement_statements",
        label="Settlement statements",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="contracts",
        label="Contracts",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="purchase_receipts",
        label="Purchase receipts",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        evidence=lambda b: _count(
            b.with_field(b.chemical, "purchase_invoice") + b.with_field(b.soil, "amendment_purchase_invoice"),
            "input purchase receipt",
        ),
    ),
    # -- E. Rows sourced from WSDA AGR 2121-O, not from the Common OSP --------------------
    # Provenance differs from every row above and is stated here rather than inferred: these
    # labels come from WSDA's Recordkeeping form (AGR 2121-O R 02/25) question 2, which names
    # 17 record types for balancing crops harvested against crops sold. The Common OSP § 11
    # list does not carry them, so on the closed 38-row registry a Washington grower could not
    # DECLARE a record type their own certifier's form asks about by name — and only confirmed
    # rows print, so the answer simply went missing. Same discipline as the rows above: verbatim
    # label from the source form, a real citation, honest evidence.
    RecordType(
        key="purchase_orders",
        label="Purchase orders",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        # Stored in BusinessEvent.extra_data by the sale/delivery editor, alongside the
        # bill-of-lading and invoice keys the rows above already read.
        evidence=lambda b: _count(
            b.business_extra("purchase_order"),
            "sale record carrying a purchase order",
            "sale records carrying purchase orders",
        ),
    ),
    RecordType(
        key="bin_ticket_stubs",
        label="Bin ticket stubs / load tickets",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="harvest_pick_sheets",
        label="Harvest pick sheets",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="pool_closings",
        label="Pool closings",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        # A handler's pool statement is issued to the grower months after delivery; it is the
        # settlement document for most California tree-nut tonnage and nothing about it passes
        # through Trazo.
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="csa_records",
        label="CSA records",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        # Trazo has no member/share ledger and `SalesRecord` carries no channel field, so a CSA
        # season is invisible here even when every box went out. Deriving it from buyer names
        # would be a guess printed to a certifier.
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="farmers_market_records",
        label="Farmers market records",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="packaging_records",
        label="Packaging log / packaging reports",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.272(b)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    # -- F. Rows sourced from OTCO C12 (Crop Record Keeping), not from the Common OSP -------
    RecordType(
        # C12 12.1 lists it as its own checkbox; CCOF G8.0 and WSDA AGR 2121-O name no
        # clean-transport record type. Before this row the operator could declare it only by
        # typing it into `other_records`, with no count beside it.
        key="clean_transport_records",
        label="Clean truck affidavits and/or other clean transport records",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.272(a)",
        evidence=lambda b: _count(
            b.clean_transport_sales() + b.legacy_transport_affidavits(),
            "shipment recording how the transport unit was kept clean",
            "shipments recording how the transport unit was kept clean",
            verb="",
        ),
    ),
    RecordType(
        # C12 12.1's own checkbox. Trazo knows which off-farm handlers touch the crop, but not the
        # documents exchanged with them (packout reports, custody transfers), and a sale's free-text
        # destination is never matched to a facility by name.
        key="copacker_transaction_records",
        label="Documentation of transactions with co-packers",
        group=GROUP_SALES,
        cfr_cite="7 CFR 205.103(b)(2)",
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
    RecordType(
        key="other_records",
        label="Other records maintained (describe)",
        group=GROUP_GENERAL,
        cfr_cite="7 CFR 205.103(b)(2)",
        # The "Other:" line both source forms end on. Nothing derives it — the operator names
        # the record type and that name is what prints, so this row is never suggested.
        free_text=True,
        external_by_design=True,
        evidence=lambda b: (0, ""),
    ),
]


RECORD_TYPES_BY_KEY = {rt.key: rt for rt in COMMON_OSP_RECORD_TYPES}


@dataclass(frozen=True)
class AnswerEvidence:
    """Records of one kind, counted under a module answer that names them (`Option.evidence`)."""

    #: (bundle) -> the records
    items: Callable
    singular: str
    plural: str
    verb: str = "logged"

    def sentence(self, bundle) -> str:
        n = len(self.items(bundle))
        what = self.singular if n == 1 else self.plural
        verb = f" {self.verb}" if self.verb else ""
        if n:
            return f"In Trazo: {n} {what}{verb}."
        return f"In Trazo: no {self.plural}{verb}. Records kept outside Trazo are not counted here."


#: Counts printed under a module answer that names a kind of record. They come from the same bundle
#: and the same rules as the section 11 rows, so a module page and the records list never disagree.
#: A count is what is logged in Trazo, never a statement that the records are complete or adequate.
ANSWER_EVIDENCE = {
    "harvest_bin_cleanouts": AnswerEvidence(
        lambda b: b.cleanouts("harvest_bins"),
        "cleaning record for harvest bins or totes",
        "cleaning records for harvest bins or totes",
    ),
    "transport_vehicle_cleanouts": AnswerEvidence(
        lambda b: b.cleanouts("transport_vehicle"),
        "cleaning record for a transport vehicle or trailer",
        "cleaning records for transport vehicles or trailers",
    ),
    "clean_transport_affidavits": AnswerEvidence(
        lambda b: b.clean_transport_sales("affidavit") + b.legacy_transport_affidavits(),
        "shipment recorded with a clean-transport affidavit on file",
        "shipments recorded with a clean-transport affidavit on file",
        verb="",
    ),
    # The same rule as the `storage_records` row: a harvest or post-harvest activity naming where the
    # lot went.
    "storage_location_entries": AnswerEvidence(
        lambda b: b.with_field(b.prod("HA", "PH"), "storage_location"),
        "harvest or post-harvest record naming a storage location",
        "harvest or post-harvest records naming a storage location",
        verb="",
    ),
    "field_equipment_cleanouts": AnswerEvidence(
        lambda b: b.cleanouts("equipment"),
        "cleaning record for field or harvest equipment",
        "cleaning records for field or harvest equipment",
    ),
    # CCOF G4.0 B2: "Test results must be available at inspection." A soil test record, or a lab
    # analysis of soil; leaf, petiole and hull analyses are the tissue tests.
    "soil_test_records": AnswerEvidence(
        lambda b: b.soils("ST") + [e for e in b.soils("LA") if getattr(e, "sample_matrix", None) == "soil"],
        "soil test record",
        "soil test records",
    ),
    # Hull is a tissue too: hull sampling at harvest is the almond boron test (the same set as
    # `restricted_materials.TISSUE_MATRICES`; review of back #348).
    "tissue_test_records": AnswerEvidence(
        lambda b: [e for e in b.soils("LA") if getattr(e, "sample_matrix", None) in TISSUE_MATRICES],
        "leaf, petiole or hull analysis",
        "leaf, petiole or hull analyses",
    ),
    "storage_area_cleanouts": AnswerEvidence(
        lambda b: b.cleanouts("storage"),
        "cleaning record for a storage area or cooler",
        "cleaning records for storage areas or coolers",
    ),
}


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------


def _confirmations(osp) -> dict:
    if osp is None:
        return {}
    sections = osp.sections or {}
    section = sections.get(OSP_SECTION_KEY) or {}
    return section.get(CONFIRMATIONS_KEY) or {}


def derive_record_types(establishment, osp=None, start_date=None, end_date=None) -> list[dict]:
    """Evidence + confirmation state for every § 11 record type.

    Returns one dict per record type::

        {
          "key", "label", "group", "cfr_cite",
          "status": evidenced_in_trazo | not_evidenced_in_trazo,
          "count": int,
          "basis": str,                 # "" when nothing was found
          "external_by_design": bool,   # Trazo structurally cannot see this record type
          "free_text": bool,            # the operator names this row themselves
          "custom_label": str | None,   # what they named it; None until confirmed
          "suggested": bool,            # evidence exists AND the operator has not confirmed yet
          "confirmed": bool,            # the operator's own assertion — the only thing that
                                        # may be rendered as a ticked § 11 checkbox
          "confirmed_at", "confirmed_by",
        }

    `suggested` and `confirmed` are deliberately separate fields. A caller that renders
    `suggested` as a tick has reintroduced the auto-attestation bug this module exists to
    prevent — see the module docstring.
    """
    from certifications.services.audit_trail_exhibit import operator_states_link

    bundle = EvidenceBundle(establishment, start_date=start_date, end_date=end_date)
    confirmations = _confirmations(osp)

    rows = []
    for rt in COMMON_OSP_RECORD_TYPES:
        failed = False
        try:
            count, basis = rt.evidence(bundle)
        except Exception as exc:  # noqa: BLE001 — one bad record type must not break the section
            logger.exception("Common OSP §11 evidence check failed for %r", rt.key)
            count, basis, failed = 0, f"Evidence check failed: {exc.__class__.__name__}", True

        conf = confirmations.get(rt.key) or {}
        confirmed = bool(conf.get("confirmed"))

        rows.append(
            {
                "key": rt.key,
                "label": rt.label,
                "group": rt.group,
                "cfr_cite": rt.cfr_cite,
                "status": UNKNOWN if failed else (EVIDENCED if count else NOT_EVIDENCED),
                "count": count,
                "basis": basis,
                "external_by_design": rt.external_by_design,
                "free_text": rt.free_text,
                "custom_label": conf.get("label") or None,
                # How this record links to the next and previous one, in the operator's words; only
                # asked of a record type whose link Trazo cannot state (OTCO C12 12.2-6).
                "operator_states_link": operator_states_link(rt.key, rt.external_by_design),
                "linking_element": conf.get("linking") or "",
                # A free-text row is never suggested — nothing derives it, and `count` is
                # always 0 — but state it rather than leaving it to the arithmetic.
                "suggested": (not rt.free_text) and bool(count) and not confirmed,
                "confirmed": confirmed,
                "confirmed_at": conf.get("confirmed_at"),
                "confirmed_by": conf.get("confirmed_by"),
                # Set when this answer came across from an earlier plan version and no human
                # has re-stated it since. The row is still confirmed — it is the FRESHNESS that
                # is in question, and a certifier reading a renewal needs to see which.
                "carried_from_version": conf.get("carried_from_version"),
                # The operator's statement that this record is NOT kept, with the reason.
                "not_kept": bool(conf.get("not_kept")),
                "not_kept_reason": conf.get("reason") or "",
                # Whether this plan's own answers require it (OSP alignment audit T17-F1); set
                # below from `required_records`, so the panel can mark it.
                "required": False,
                "required_state": "",
                "required_because": "",
            }
        )
    if osp is not None:
        try:
            from certifications.services.required_records import required_records

            by_key = {r.key: r for r in required_records(osp)}
        except Exception:  # noqa: BLE001 — the list renders without the marks rather than not at all
            logger.exception("Required record types could not be derived for OSP %s", getattr(osp, "pk", None))
            by_key = {}
        for row in rows:
            record = by_key.get(row["key"])
            if record is not None:
                row["required"] = True
                row["required_state"] = record.state
                row["required_because"] = record.because
    return rows


def summarize(rows: list[dict]) -> dict:
    """Counts for a card header. No score, no grade, no percentage-complete verdict.

    Deliberately omits any ratio that could read as a self-assigned completeness grade — the
    same reason the transparency score was removed from every outward-facing surface.
    """
    return {
        "total": len(rows),
        "evidenced": sum(1 for r in rows if r["status"] == EVIDENCED),
        "confirmed": sum(1 for r in rows if r["confirmed"]),
        "awaiting_confirmation": sum(1 for r in rows if r["suggested"]),
        # Confirmed on an earlier plan and not re-stated since. Counted separately from
        # `confirmed` rather than deducted from it: they ARE confirmed answers, and the
        # question a renewal raises about them is when, not whether.
        "carried_forward": sum(1 for r in rows if r.get("carried_from_version")),
        "external_by_design": sum(1 for r in rows if r["external_by_design"]),
        # Surfaced so a broken evidence check is visible instead of quietly reading as "none".
        "evidence_check_failed": sum(1 for r in rows if r["status"] == UNKNOWN),
    }


def mark_carried_forward(sections, from_version: int) -> dict:
    """A deep copy of `sections` whose § 11 confirmations are marked as carried, not made.

    🔴 2026-09-07 — `OSPViewSet.new_version` clones `sections` verbatim, so every § 11 tick an
    operator made in v1 arrived in v2 already confirmed, still stamped with v1's `confirmed_at`
    and `confirmed_by`, and neither the panel nor the PDF showed that date. The next year's
    packet therefore presented a year-old attestation as this year's, in the one document where
    § 205.406(a)(1) makes currency the entire question.

    Wiping the ticks would be the wrong fix — the operator DID make those statements, and
    re-ticking forty boxes a year is friction that buys no information (the same reasoning that
    made cloning the materials registry correct). What must not survive the clone is the
    IMPLICATION OF FRESHNESS. So the answer carries and `carried_from_version` records that it
    came from an earlier plan; the row reads "carried from plan v1" until the operator either
    re-ticks it or attests, on the § 205.406 annual update, that the recordkeeping section is
    unchanged — which is that same statement, dated this year, in the filing that exists to
    carry it.

    Pure and total: takes the source's sections, returns a new dict, mutates nothing. The caller
    hands the result to `objects.create()`. `sections=source.sections` also passed the SAME dict
    object to the clone, so a later in-memory edit of one plan's sections reached the other.
    """
    from copy import deepcopy

    out = deepcopy(sections or {})
    section = out.get(OSP_SECTION_KEY)
    if not isinstance(section, dict):
        return out
    confirmations = section.get(CONFIRMATIONS_KEY)
    if not isinstance(confirmations, dict):
        return out

    for entry in confirmations.values():
        if isinstance(entry, dict) and entry.get("confirmed"):
            # An entry already carried through v1 -> v2 keeps its ORIGINAL origin on the way to
            # v3. "Carried from v2" would date the staleness to the clone rather than to the
            # last time a human actually looked at it.
            entry.setdefault("carried_from_version", from_version)
    return out


def reaffirm_carried(osp, user=None) -> int:
    """Re-date every carried § 11 confirmation as a statement made NOW. Returns the count.

    Called when the operator attests on their § 205.406(a)(1) annual update that the
    recordkeeping section is unchanged since the prior plan. That attestation IS the
    re-affirmation — it is dated, it is theirs, and it is the filing the regulation provides for
    exactly this — so there is no second control to click and no new record to keep.

    ⛔ NOT a "confirm all". Every row this touches is already confirmed BY THIS OPERATION; it
    re-stamps existing statements and can never create one. A row the operator has not confirmed
    is untouched, and a plan with nothing carried is a no-op.
    """
    from django.utils import timezone

    if osp is None:
        return 0
    sections = dict(osp.sections or {})
    section = dict(sections.get(OSP_SECTION_KEY) or {})
    confirmations = dict(section.get(CONFIRMATIONS_KEY) or {})

    stamp = timezone.now().isoformat()
    touched = 0
    for key, entry in list(confirmations.items()):
        # BOTH conditions. `carried_from_version` is only ever written onto a confirmed entry
        # today, so the `confirmed` half looks redundant — but the promise in this docstring is
        # that the function cannot create a statement, and a promise that holds only because of
        # an invariant in another module is one line away from being false.
        if not isinstance(entry, dict) or not entry.get("confirmed") or not entry.get("carried_from_version"):
            continue
        updated = dict(entry)
        updated.pop("carried_from_version", None)
        updated["confirmed_at"] = stamp
        updated["confirmed_by"] = getattr(user, "id", None)
        confirmations[key] = updated
        touched += 1

    if not touched:
        return 0

    section[CONFIRMATIONS_KEY] = confirmations
    sections[OSP_SECTION_KEY] = section
    osp.sections = sections
    osp.save(update_fields=["sections", "updated_at"])
    return touched


#: Longest an operator-authored "Other" record-type name may be. It is a label on a certifier's
#: form line, not a narrative — the description of what the records CONTAIN belongs in the module's
#: recordkeeping narrative, which has room for it.
FREE_TEXT_LABEL_MAX = 200


def confirm(osp, keys, user=None, confirmed=True, label=None) -> dict:
    """Record the OPERATOR's assertion for the given record-type keys.

    This is the only path by which a § 11 checkbox becomes an answer. Callers must invoke it
    from an authenticated, operator-facing action — never from a signal, a seeder, an import, or
    any automated derivation.

    `label` names a `free_text=True` row ("Other records maintained"). It is REQUIRED to confirm
    one and rejected on any other row: an unnamed "Other ✓" on a certifier's form is a tick with
    no statement under it — the same empty-attestation shape `attestation_gates` refuses one
    level up. Confirming a free-text row again with a new label renames it.

    Unknown keys are ignored rather than raising: the registry may add entries between a client
    fetching the list and posting confirmations back.
    """
    from django.utils import timezone

    if osp is None:
        raise ValueError("An OrganicSystemPlan is required to record § 11 confirmations.")

    label = (label or "").strip()
    if label:
        if len(label) > FREE_TEXT_LABEL_MAX:
            raise ValueError(f"A record-type label may be at most {FREE_TEXT_LABEL_MAX} characters.")
        named = [k for k in keys if k in RECORD_TYPES_BY_KEY and RECORD_TYPES_BY_KEY[k].free_text]
        if len(named) != 1 or len(keys) != 1:
            raise ValueError("A label applies to exactly one free-text record type, on its own.")
    elif confirmed:
        unnamed = [k for k in keys if k in RECORD_TYPES_BY_KEY and RECORD_TYPES_BY_KEY[k].free_text]
        if unnamed:
            raise ValueError(f"Name the record type before confirming it: {', '.join(sorted(unnamed))}.")

    sections = dict(osp.sections or {})
    section = dict(sections.get(OSP_SECTION_KEY) or {})
    current = dict(section.get(CONFIRMATIONS_KEY) or {})

    stamp = timezone.now().isoformat()
    for key in keys:
        if key not in RECORD_TYPES_BY_KEY:
            continue
        if confirmed:
            entry = {
                "confirmed": True,
                "confirmed_at": stamp,
                "confirmed_by": getattr(user, "id", None),
            }
            if RECORD_TYPES_BY_KEY[key].free_text:
                entry["label"] = label
            # A re-confirmation (a renamed "Other" row) keeps the link the operator stated for it.
            previous = current.get(key)
            if isinstance(previous, dict) and previous.get("confirmed") and previous.get("linking"):
                entry["linking"] = previous["linking"]
            current[key] = entry
        else:
            current.pop(key, None)

    section[CONFIRMATIONS_KEY] = current
    sections[OSP_SECTION_KEY] = section
    osp.sections = sections
    osp.save(update_fields=["sections", "updated_at"])
    return current


#: Longest linking element an operator may state: one cell of the exhibit's Part A table.
LINKING_ELEMENT_MAX = 300


def set_linking_element(osp, key, text, user=None) -> dict:
    """Record how a confirmed record type links to the next and previous document, in the operator's
    words (OTCO C12 12.2-6: "Linking element to next and previous document in chain").

    Only for a record type whose link Trazo cannot state from its own record shapes
    (`audit_trail_exhibit.operator_states_link`): a weigh ticket, a delivery slip, the operation's
    own form. Only on a CONFIRMED row: a link for a record the operation has not said it keeps would
    print a chain nobody vouched for. Empty text clears it. Operator-only, like `confirm()`.
    """
    from certifications.services.audit_trail_exhibit import operator_states_link

    if osp is None:
        raise ValueError("An OrganicSystemPlan is required to record a linking element.")
    rt = RECORD_TYPES_BY_KEY.get(key)
    if rt is None:
        raise ValueError(f"Unknown record type: {key}")
    if not operator_states_link(key, rt.external_by_design):
        raise ValueError("Trazo states this record's linking element from its own records; there is none to add.")
    text = (text or "").strip()
    if len(text) > LINKING_ELEMENT_MAX:
        raise ValueError(f"A linking element may be at most {LINKING_ELEMENT_MAX} characters.")
    sections = dict(osp.sections or {})
    section = dict(sections.get(OSP_SECTION_KEY) or {})
    current = dict(section.get(CONFIRMATIONS_KEY) or {})
    entry = current.get(key)
    if not (isinstance(entry, dict) and entry.get("confirmed")):
        raise ValueError("Confirm that the operation keeps this record before stating how it links.")
    entry = dict(entry)
    if text:
        entry["linking"] = text
        entry["linking_by"] = getattr(user, "id", None)
    else:
        entry.pop("linking", None)
        entry.pop("linking_by", None)
    current[key] = entry
    section[CONFIRMATIONS_KEY] = current
    sections[OSP_SECTION_KEY] = section
    osp.sections = sections
    osp.save(update_fields=["sections", "updated_at"])
    return current


def mark_not_kept(osp, key, reason, user=None) -> dict:
    """Record the operator's statement that the operation does NOT keep this record type.

    The counterpart of `confirm()`, and as operator-only. It exists so a required record the
    operation does not keep reads as exactly that in the packet (with the operator's reason),
    rather than as an unticked box. It never satisfies the records attestation: a required record
    that is not kept is a missing record (`required_records`, OSP alignment audit T17-F1).
    """
    from django.utils import timezone

    if osp is None:
        raise ValueError("An OrganicSystemPlan is required to record § 11 statements.")
    if key not in RECORD_TYPES_BY_KEY:
        raise ValueError(f"Unknown record type: {key}")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("Say why this record type is not kept.")
    sections = dict(osp.sections or {})
    section = dict(sections.get(OSP_SECTION_KEY) or {})
    current = dict(section.get(CONFIRMATIONS_KEY) or {})
    current[key] = {
        "confirmed": False,
        "not_kept": True,
        "reason": reason[:300],
        "stated_at": timezone.now().isoformat(),
        "stated_by": getattr(user, "id", None),
    }
    section[CONFIRMATIONS_KEY] = current
    sections[OSP_SECTION_KEY] = section
    osp.sections = sections
    osp.save(update_fields=["sections", "updated_at"])
    return current
