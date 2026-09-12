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
from decimal import Decimal
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
        # "Lot ID", not "Lot ID (History.lot_id)": a model field name printed to a certifier.
        "Lot ID on the season record + harvest date + parcel — links back to the season and forward to storage "
        "and sales",
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

#: Documents Trazo does not hold whose link to the rest of the trail is nevertheless standard, so
#: the page can state it instead of printing an unanswered prompt. The document stays the
#: operator's; the row says so. Other external record types (weigh tickets, the operator's own
#: forms) still get OPERATOR_COMPLETES, because their link is the operator's own scheme.
EXTERNAL_LINKING_ELEMENTS = {
    "settlement_statements": (
        "The handler's final statement for the crop delivered",
        "Invoice number + Lot ID on the sales record — the statement settles that invoice (held by the "
        "operation, outside Trazo)",
    ),
    "contracts": (
        "The terms the crop is sold under",
        "Buyer + crop year on the sales record — the contract behind those sales (held by the operation, "
        "outside Trazo)",
    ),
}


@dataclass(frozen=True)
class DocumentRow:
    name: str
    activity: str
    linking_element: Optional[str]  # None = left for the operator


@dataclass(frozen=True)
class LotBalance:
    """Harvested minus sold for the traced lot, in one unit — or the reason it cannot be stated.

    🔴 2026-09-10 (OTCO desk read) — Part B listed the lot's harvests and its sales and never
    subtracted. The cooler received more fresh fruit than was sold fresh and the page did not say
    so, while the subtraction is the inspector's whole trace-back. Units are folded only through
    the audit export's own unambiguous synonyms ("lbs" is "lb"); anything else is not summed,
    because a total across bins and pounds is a confident fabricated number.
    """

    harvested: Optional[Decimal] = None
    sold: Optional[Decimal] = None
    #: The handler's pack-out, when EVERY harvest record carries one in the balance's unit. It is
    #: what explains the gap between harvest and sale on a packed crop: the sale is the packed-out
    #: fruit, and the difference is the handler's culls and shrink. Without it the page asked the
    #: operator to explain a gap the records already explained (WSDA specimen read, 2026-09-11).
    packed_out: Optional[Decimal] = None
    #: The § 205.202(c) buffer crop, kept OUT of the organic sums above. It is harvested from the
    #: same block and sold to someone else as conventional, so netting it into the organic lot
    #: makes both numbers wrong; stating it beside them is the evidence a reviewer asks for.
    buffer_harvested: Optional[Decimal] = None
    buffer_sold: Optional[Decimal] = None
    buffer_sale_count: int = 0
    unit: str = ""
    harvest_count: int = 0
    sale_count: int = 0
    #: Why no balance is stated; empty when one is.
    not_computed: str = ""

    @property
    def difference(self) -> Optional[Decimal]:
        if self.not_computed or self.harvested is None or self.sold is None:
            return None
        return self.harvested - self.sold


def fmt_total(value, unit) -> str:
    """'114,240 lb' — thousands separated, no trailing zeros, never rounded."""
    text = format(Decimal(str(value)).normalize(), ",f")
    return f"{text} {unit or ''}".strip()


def _lot_balance(all_harvest_events, all_sales) -> LotBalance:
    """Sum each side only when every record carries a quantity and all share one unit.

    The organic lot is what balances: a harvest whose § 205.202(c) disposition put the buffer crop
    into someone else's hands, and a sale not invoiced as organic, are counted apart. Netted in,
    they made the organic harvest look bigger than the fruit that could be sold as organic.
    """
    from history.services.audit_export_service import AuditExportService

    canonical = AuditExportService._canonical_unit
    buffer_events = [ev for ev in all_harvest_events if ev.buffer_disposition_entered_commerce()]
    harvest_events = [ev for ev in all_harvest_events if ev not in buffer_events]
    buffer_sales = [s for s in all_sales if not s.organic_on_invoice]
    sales = [s for s in all_sales if s.organic_on_invoice]
    buffer_harvested = (
        sum((Decimal(str(ev.yield_quantity)) for ev in buffer_events if ev.yield_quantity is not None), Decimal(0))
        or None
    )
    buffer_sold = sum((Decimal(str(s.quantity)) for s in buffer_sales if s.quantity is not None), Decimal(0)) or None
    buffer = dict(buffer_harvested=buffer_harvested, buffer_sold=buffer_sold, buffer_sale_count=len(buffer_sales))
    if not harvest_events:
        return LotBalance(sale_count=len(sales), not_computed="no harvest record is on file for this season", **buffer)
    missing = [ev for ev in harvest_events if ev.yield_quantity is None]
    if missing:
        return LotBalance(
            not_computed=f"{len(missing)} of {len(harvest_events)} harvest record(s) carry no quantity", **buffer
        )
    missing = [sale for sale in sales if sale.quantity is None]
    if missing:
        return LotBalance(not_computed=f"{len(missing)} of {len(sales)} sale(s) carry no quantity", **buffer)
    units = {canonical(ev.yield_unit) for ev in harvest_events} | {canonical(s.quantity_unit) for s in sales}
    if len(units) != 1:
        shown = ", ".join(sorted(u or "no unit" for u in units))
        return LotBalance(not_computed=f"the records use more than one unit ({shown})", **buffer)
    unit = units.pop()
    packed = [ev.quantity_returned_from_handler for ev in harvest_events]
    packed_units = {canonical(ev.handler_return_unit or ev.yield_unit) for ev in harvest_events}
    packed_out = (
        sum((Decimal(str(q)) for q in packed), Decimal(0))
        if all(q is not None for q in packed) and packed_units == {unit}
        else None
    )
    return LotBalance(
        harvested=sum((Decimal(str(ev.yield_quantity)) for ev in harvest_events), Decimal(0)),
        sold=sum((Decimal(str(s.quantity)) for s in sales), Decimal(0)),
        packed_out=packed_out,
        unit=unit,
        harvest_count=len(harvest_events),
        sale_count=len(sales),
        **buffer,
    )


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
    balance: Optional[LotBalance] = None


def document_table(establishment, osp) -> list[DocumentRow]:
    """Part A — one row per CONFIRMED record type, in registry order."""
    from certifications.services.common_osp_records import derive_record_types

    rows = []
    for rt in derive_record_types(establishment, osp):
        if not rt["confirmed"]:
            continue
        name = rt["custom_label"] or rt["label"]
        known = LINKING_ELEMENTS.get(rt["key"])
        external = EXTERNAL_LINKING_ELEMENTS.get(rt["key"])
        if known and not rt["external_by_design"]:
            rows.append(DocumentRow(name=name, activity=known[0], linking_element=known[1]))
        elif external and rt["external_by_design"]:
            rows.append(DocumentRow(name=name, activity=external[0], linking_element=external[1]))
        else:
            rows.append(DocumentRow(name=name, activity=name, linking_element=None))
    return rows


def _fmt_qty(quantity, unit) -> str:
    """'13,400 lb', '2.5 t' — thousands separated, trailing zeros dropped, never rounded.

    The same number formatting as the balance line below it: the trail printed "558000 lbs" two
    lines above "971,100 lb" (WSDA specimen read, 2026-09-11). The unit is folded through the
    audit export's unambiguous synonyms only ("lbs" is "lb"), exactly as the balance folds it.
    """
    if quantity is None:
        return ""
    from history.services.audit_export_service import AuditExportService

    return fmt_total(quantity, AuditExportService._canonical_unit(unit) or unit)


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
    harvest_events = list(
        ProductionEvent.objects.filter(history=season, type=ProductionEvent.HARVESTING).order_by("date")
    )
    for ev in harvest_events:
        trail.harvests.append(
            {
                "date": ev.date.date().isoformat() if ev.date else "",
                "quantity": _fmt_qty(ev.yield_quantity, ev.yield_unit),
                "storage": (ev.storage_location or "").strip(),
                "block": (ev.block_id or "").strip(),
            }
        )
    trail.storage_locations = sorted({h["storage"] for h in trail.harvests if h["storage"]})
    sales = list(SalesRecord.objects.live().filter(production=season).order_by("sale_date", "pk"))
    trail.balance = _lot_balance(harvest_events, sales)
    for sale in sales:
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
