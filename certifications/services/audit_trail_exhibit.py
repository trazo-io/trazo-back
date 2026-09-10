"""
Audit trail exhibit — § 205.103(b)(2) trace-back, as a document the packet carries.

WHY THIS EXISTS
---------------
Two certifier forms ask for the same thing in two shapes, and until 2026-09-09 the product
answered neither while its own coaching said it did:

  * CCOF G8.0 B1 — "Attach a sample audit trail showing how you plan to meet the audit trail
    requirements: highlight the linking elements showing how documents connect in sequence; show
    how you identify the organic status".
  * Oregon Tilth C12 Q6 — "Complete the table below (Name of Document · Activity the document
    describes · Linking element to next and previous document in chain) or attach a separate
    diagram", then "attach sample documents".

G8.0's `audit_trail_exhibit` upload coached "Trazo can generate this exhibit from your records …
Generate it from the Documents page" — and no generator existed in either repo. The register
recorded that as a P1 on both certifiers. This module is that generator.

TWO HALVES, TWO RULES
---------------------
Part A — the DOCUMENT TABLE. One row per record type, but ONLY the record types the operator has
CONFIRMED in G8.0 §A (`common_osp_records.confirm`). The producer is the author of the plan
(§ 205.201(a)); a table that listed every record type Trazo can see would be the auto-attestation
this codebase has already shipped once and undone. What Trazo adds to a confirmed row is a FACT
about its own record shapes — which field links a harvest record to the lot, a sale to the
harvest — never a claim about the operator's filing cabinet. A record type Trazo cannot hold
(`external_by_design`: weigh tickets, delivery slips, the operator's own "other") prints with its
linking cell left for the operator: the document is theirs, so is the link.

Part B — the SAMPLE TRAIL. One real lot, chosen mechanically (the most recently finished season
that has at least one live sale), walked from the lot identifier through harvest, storage and
sale with the linking element named at every step. Nothing is invented: every line is a dated
record the operation logged, and where a link is missing the exhibit says so — a production with
no lot identifier is reported with the same blocker the lot-tag generator refuses on, never as
"LOT —". When no finished season has a sale yet, the exhibit states that absence rather than
fabricating a chain from an open season.

Voided sales are excluded (`SalesRecord.objects.live()`): a trace that ended at a sale which did
not happen would be a false statement to a certifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Trazo's own record shapes: which field carries the § 205.103(b)(2) linkage for each record
#: type the product HOLDS. Keys are `common_osp_records` record-type keys. A record type absent
#: here is either external-by-design (the operator's own document) or has no single linking
#: field — both print the linking cell for the operator to complete.
LINKING_ELEMENTS: dict = {
    "planting_records": (
        "Planting a crop on a parcel for a season",
        "Parcel name and season (History) — links forward to every activity record on the season",
    ),
    "harvest_records": (
        "Harvesting the crop",
        "Lot ID (History.lot_id) + harvest date + parcel — links back to the season and forward to storage and sales",
    ),
    "pest_management": (
        "Pest management practices and applications",
        "Parcel + application date on the event — links to the season and to the materials list",
    ),
    "disease_management": (
        "Disease management practices and applications",
        "Parcel + application date on the event — links to the season and to the materials list",
    ),
    "weeding": ("Weed control", "Parcel + date on the event — links to the season"),
    "cultivation": ("Cultivation", "Parcel + date on the event — links to the season"),
    "tillage": ("Tillage", "Parcel + date on the event — links to the season"),
    "mulching": ("Mulching", "Parcel + date on the event — links to the season"),
    "input_material_application": (
        "Applying a fertilizer, amendment or other input",
        "Parcel + date + product name — links to the season and to the plan's materials list",
    ),
    "input_material_usage": (
        "Quantity of an input used",
        "Product name + date + parcel on the application event — links to purchase records by product",
    ),
    "compost_production": (
        "Producing compost on the operation",
        "Compost batch on the soil-management event (date, temperatures, turnings) — links to the application event that spreads it",
    ),
    "shared_equipment_cleaning": (
        "Cleaning equipment used on both organic and non-organic crops",
        "Equipment name + date on the production event — links to the next organic use of that equipment",
    ),
    "rotation_records": ("Crop rotation on a parcel", "Parcel + year in the field history — links seasons in sequence"),
    "storage_records": (
        "Storing harvested crop",
        "Storage location on the harvest record + Lot ID — links harvest to sale",
    ),
    "post_harvest_production": (
        "Post-harvest handling (washing, sorting, packing)",
        "Lot ID + date on the post-harvest event — links harvest to sale",
    ),
    "invoices": (
        "Selling the crop",
        "Invoice number + Lot ID + buyer on the sales record — links back to the harvest records it draws from",
    ),
    "bill_of_lading": (
        "Shipping the crop to the buyer",
        "Bill of lading number on the sales record + Lot ID — links the shipment to the sale",
    ),
    "purchase_records": (
        "Buying inputs, seed or planting stock",
        "Product name + purchase date — links forward to the application event that uses it",
    ),
    "purchase_receipts": (
        "Receipt for a purchased input",
        "Product name + purchase date — links forward to the application event that uses it",
    ),
    "purchase_receipts_invoices": (
        "Receipt or invoice for a purchased input",
        "Product name + purchase date — links forward to the application event that uses it",
    ),
    "purchase_orders": ("Ordering an input", "Product name + order date — links to the purchase receipt"),
    "organic_certificates": (
        "Certificate of a supplier or handler traded with",
        "Operation name + certificate number on the supplier or facility record — links to purchases from or shipments to that operation",
    ),
    "supplier_verification_records": (
        "Verifying a supplier's organic status",
        "Supplier name + certificate reference on the supplier record — links to purchases from that supplier",
    ),
    "monitoring_records": (
        "Monitoring practice effectiveness",
        "Parcel + date on the observation event — links to the season",
    ),
    "clean_out_records": (
        "Cleaning out equipment or storage",
        "Equipment or location + date — links to the next organic use",
    ),
    "drift_prevention_records": (
        "Preventing drift",
        "Parcel + date — links to the buffer rows on the Parcel Application",
    ),
    "buffer_separation_records": (
        "Harvesting and selling buffer crop separately",
        "Parcel buffer row + harvest date + disposition — links the buffer harvest to its non-organic sale",
    ),
    "non_gmo_seed_verification": (
        "Verifying seed is not GMO",
        "Seed product name + supplier — links to the planting record",
    ),
    "untreated_seed_verification": (
        "Verifying seed is untreated",
        "Seed product name + supplier — links to the planting record",
    ),
    "seed_search_commercial_availability": (
        "Searching for organic seed or stock",
        "Variety + search date + suppliers contacted — links to the planting record that used the non-organic seed",
    ),
    "input_material_information": (
        "Label, SDS or listing for an input",
        "Product name + manufacturer — links to the materials list row and the application events",
    ),
    "restricted_input_use_records": (
        "Using a restricted input within its annotation",
        "Product name + date + the restriction met, on the application event — links to the materials list",
    ),
    "natural_resources_condition": (
        "Condition of soil and water",
        "Parcel + date on the observation or test — links to the season",
    ),
}

OPERATOR_COMPLETES = "(the operator's own document — state the linking element)"


@dataclass(frozen=True)
class DocumentRow:
    name: str
    activity: str
    linking_element: Optional[str]  # None = left for the operator


@dataclass
class SampleTrail:
    season_name: str
    crop: str
    parcel: str
    lot_id: Optional[str]
    lot_blocker: str
    harvests: list = field(default_factory=list)  # dicts: date, quantity, unit, storage, block
    storage_locations: list = field(default_factory=list)
    sales: list = field(
        default_factory=list
    )  # dicts: date, buyer, quantity, unit, invoice, bol, organic_on_invoice, label_category


def document_table(establishment, osp) -> list[DocumentRow]:
    """Part A — one row per CONFIRMED record type, in registry order."""
    from certifications.services.common_osp_records import derive_record_types

    rows = []
    for rt in derive_record_types(establishment, osp):
        if not rt["confirmed"]:
            continue
        name = rt["custom_label"] or rt["label"]
        known = LINKING_ELEMENTS.get(rt["key"])
        if known and not rt["external_by_design"]:
            rows.append(DocumentRow(name=name, activity=known[0], linking_element=known[1]))
        else:
            rows.append(DocumentRow(name=name, activity=name, linking_element=None))
    return rows


def _fmt_qty(quantity, unit) -> str:
    """'13400 lb', '2.5 t' — the recorded number without Decimal's trailing zeros, never rounded."""
    if quantity is None:
        return ""
    text = str(quantity)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text} {unit or ''}".strip()


def sample_trail(establishment) -> Optional[SampleTrail]:
    """Part B — the most recently finished season with at least one live sale, or None."""
    from history.models import History, ProductionEvent, SalesRecord
    from history.services.claim_authority import may_label_container

    season = (
        History.objects.filter(
            parcel__establishment=establishment,
            finish_date__isnull=False,
            sales_records__in=SalesRecord.objects.live(),
        )
        .select_related("product", "crop_type", "parcel")
        .order_by("-finish_date")
        .distinct()
        .first()
    )
    if season is None:
        return None

    decision = may_label_container(season)
    crop = getattr(season.product, "name", None) or getattr(season.crop_type, "name", None) or ""
    trail = SampleTrail(
        season_name=season.name or "",
        crop=crop,
        parcel=season.parcel.name if season.parcel else "",
        lot_id=decision.lot_id if decision.may_print else None,
        lot_blocker="" if decision.may_print else decision.blocker,
    )
    for ev in ProductionEvent.objects.filter(history=season, type=ProductionEvent.HARVESTING).order_by("date"):
        trail.harvests.append(
            {
                "date": ev.date.date().isoformat() if ev.date else "",
                "quantity": _fmt_qty(ev.yield_quantity, ev.yield_unit),
                "storage": (ev.storage_location or "").strip(),
                "block": (ev.block_id or "").strip(),
            }
        )
    trail.storage_locations = sorted({h["storage"] for h in trail.harvests if h["storage"]})
    for sale in SalesRecord.objects.live().filter(production=season).order_by("sale_date", "pk"):
        trail.sales.append(
            {
                "date": sale.sale_date.isoformat() if sale.sale_date else "",
                "buyer": sale.buyer_name,
                "quantity": _fmt_qty(sale.quantity, sale.quantity_unit),
                "invoice": sale.invoice_number or "",
                "bol": sale.bill_of_lading or "",
                "organic_on_invoice": bool(sale.organic_on_invoice),
                "label_category": (sale.get_organic_label_category_display() if sale.organic_label_category else ""),
            }
        )
    return trail
