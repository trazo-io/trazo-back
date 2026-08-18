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

Every record type carries the verbatim USDA label and a real CFR citation. No entry may be added
because a competitor has a screen for it. If Trazo cannot see evidence for a record type, it stays
in the registry as permanently NOT_EVIDENCED_IN_TRAZO — that is honest and useful (the operator
still ticks it if they keep weigh tickets in a drawer), and it is how the operator learns which
parts of their recordkeeping live outside this tool.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

# Same emptiness rule the PUR export and per-event completeness registry already use:
# None, "", and whitespace-only all count as missing.
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


# --------------------------------------------------------------------------------------
# Evidence bundle — every queryset read once, then counted many times.
# --------------------------------------------------------------------------------------


class EvidenceBundle:
    """Events + productions for one establishment, optionally windowed.

    Mirrors `OperationAuditExportService._productions()` windowing semantics (a production counts
    if it was active during the window) so the § 11 evidence and the certifier dossier never
    disagree about which season they are describing.
    """

    def __init__(self, establishment, start_date=None, end_date=None):
        from django.db.models import Q

        from history.models import History

        self.establishment = establishment
        self.start_date = start_date
        self.end_date = end_date

        qs = History.objects.filter(parcel__establishment=establishment)
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
        self.sales = [s for p in self.productions for s in p.sales_records.all()]
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
        evidence=lambda b: _count(b.pest + b.chem("PE"), "pest management record"),
    ),
    RecordType(
        key="cultivation",
        label="Cultivation",
        group=GROUP_CROP,
        cfr_cite="7 CFR 205.206(a)(1)",
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
            "input application",
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
        cfr_cite="7 CFR 205.206(a)(6)",
        # Trazo has no dedicated mulching subtype. MO ("Mowing / Orchard-Floor") covers mowing,
        # mulching and floor management together, so an MO event is evidence of floor work but
        # NOT proof that mulch was applied — the basis string says so rather than overstating.
        evidence=lambda b: (
            len(b.prod("MO")),
            (
                f"{len(b.prod('MO'))} orchard-floor / mowing event(s) logged — confirm whether these include mulching"
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
        evidence=lambda b: _count(
            b.chem("FU") + b.with_field(b.pest, "pest_species"),
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
        evidence=lambda b: _count(b.chemical, "input usage record"),
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
            b.with_field(b.chemical, "omri_product", "national_list_substance", "organic_approved"),
            "input record checked against an approved-materials list",
            "input records checked against approved-materials lists",
        ),
    ),
    RecordType(
        key="purchase_receipts_invoices",
        label="Purchase receipts / invoices",
        group=GROUP_INPUTS,
        cfr_cite="7 CFR 205.103(b)(1)",
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
        cfr_cite="7 CFR 205.103(b)(1)",
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
        cfr_cite="7 CFR 205.103(b)(1)",
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
        cfr_cite="7 CFR 205.103(b)(1)",
        evidence=lambda b: _count(
            b.with_field(b.chemical, "purchase_invoice") + b.with_field(b.soil, "amendment_purchase_invoice"),
            "input purchase receipt",
        ),
    ),
]


RECORD_TYPES_BY_KEY = {rt.key: rt for rt in COMMON_OSP_RECORD_TYPES}


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
          "suggested": bool,            # evidence exists AND the operator has not confirmed yet
          "confirmed": bool,            # the operator's own assertion — the only thing that
                                        # may be rendered as a ticked § 11 checkbox
          "confirmed_at", "confirmed_by",
        }

    `suggested` and `confirmed` are deliberately separate fields. A caller that renders
    `suggested` as a tick has reintroduced the auto-attestation bug this module exists to
    prevent — see the module docstring.
    """
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
                "suggested": bool(count) and not confirmed,
                "confirmed": confirmed,
                "confirmed_at": conf.get("confirmed_at"),
                "confirmed_by": conf.get("confirmed_by"),
            }
        )
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
        "external_by_design": sum(1 for r in rows if r["external_by_design"]),
        # Surfaced so a broken evidence check is visible instead of quietly reading as "none".
        "evidence_check_failed": sum(1 for r in rows if r["status"] == UNKNOWN),
    }


def confirm(osp, keys, user=None, confirmed=True) -> dict:
    """Record the OPERATOR's assertion for the given record-type keys.

    This is the only path by which a § 11 checkbox becomes an answer. Callers must invoke it
    from an authenticated, operator-facing action — never from a signal, a seeder, an import, or
    any automated derivation.

    Unknown keys are ignored rather than raising: the registry may add entries between a client
    fetching the list and posting confirmations back.
    """
    from django.utils import timezone

    if osp is None:
        raise ValueError("An OrganicSystemPlan is required to record § 11 confirmations.")

    sections = dict(osp.sections or {})
    section = dict(sections.get(OSP_SECTION_KEY) or {})
    current = dict(section.get(CONFIRMATIONS_KEY) or {})

    stamp = timezone.now().isoformat()
    for key in keys:
        if key not in RECORD_TYPES_BY_KEY:
            continue
        if confirmed:
            current[key] = {
                "confirmed": True,
                "confirmed_at": stamp,
                "confirmed_by": getattr(user, "id", None),
            }
        else:
            current.pop(key, None)

    section[CONFIRMATIONS_KEY] = current
    sections[OSP_SECTION_KEY] = section
    osp.sections = sections
    osp.save(update_fields=["sections", "updated_at"])
    return current
