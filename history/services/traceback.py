"""
Traceback from one sale: the inspector's § 205.103(b)(2) exercise, run by the operation first.

WHY THIS EXISTS
---------------
At every annual inspection the inspector picks a lot off a sales document (an invoice or a bill of
lading) and walks it backward: sale -> harvest pick -> season and parcel -> the inputs applied.
Every hop must carry an identifier the next record also carries; the usual failure is a hop where
no record holds both (a "lot-number gap"). Trazo already stores each link (the sale's
`harvest_events`, the pick's `harvest_lot_code`, the inputs' supplier / invoice / lot), but nothing
walked them from an identifier: `certifications.services.audit_trail_exhibit.sample_trail` picks a
season by itself, reads only `History.lot_id`, and stops before the inputs.

RULES
-----
* Anchored on a SALE, because that is where the inspector starts. A voided sale is never a start:
  callers pass `SalesRecord.objects.live()` rows only, and the balance counts live sales only.
* Gaps are CODES (`{hop, code, field, ref}`), never prose and never a verdict. There is no pass /
  fail, no count of gaps as a grade, no percentage: the operator fixes the named field.
* An input with no classification reads `not_classified`. Absence of a listing is not evidence of
  a prohibited input (the inverse error `claim_authority` exists to prevent).
* A sale with no linked pick is the lot-number gap at its true location. The season's picks are
  still listed, marked unlinked, so the operator can see which pick the sale should name.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from certifications.services.audit_trail_exhibit import _fmt_qty, _lot_balance, fmt_total

#: `claim_authority` labels -> stable codes the frontend translates. The labels are consumer
#: copy; a code keeps the producer surface from re-printing them in English.
_LISTING_CODES = {
    "LABEL_INPUT_OMRI_LISTED": "omri_listed",
    "LABEL_INPUT_WSDA_LISTED": "wsda_listed",
    "LABEL_INPUT_NATIONAL_LIST": "national_list_allowed",
    "LABEL_INPUT_NATIONAL_LIST_CONDITIONAL": "national_list_conditional",
    "LABEL_INPUT_NATIONAL_LIST_PROHIBITED": "national_list_prohibited",
    "LABEL_INPUT_GROWER_REPORTED": "recorded_by_farm",
    "LABEL_INPUT_UNCLASSIFIED": "not_classified",
}


#: Each gap code in the certifier's words, for the packet (English, like every packet page). A
#: statement of what the records do not hold, never a verdict: whether a missing receipt matters
#: is the certifier's call. `{input}` names the record.
GAP_PROSE = {
    "no_sale_document": "The sale records no invoice number and no bill of lading number.",
    "label_category_not_recorded": "The sale is identified as organic on the invoice but its labeling category is not recorded.",
    "sale_without_document": "No invoice, bill of lading or pack-out file is attached to the sale; its numbers are recorded as text only.",
    "sale_not_linked_to_pick": "The sale does not name the harvest pick it came from.",
    "pick_without_lot_code": "A harvest pick has no lot code.",
    "season_without_lot_id": "The season has no lot ID recorded.",
    "input_without_supplier": "{input}: no supplier recorded.",
    "input_without_invoice": "{input}: no purchase invoice number recorded.",
    "input_without_lot": "{input}: no supplier lot number recorded.",
    "input_without_document": "{input}: no purchase receipt file attached.",
}


def gap_sentence(gap: dict, inputs: list) -> str:
    """One gap as the packet prints it, naming the input it is about."""
    row = next((r for r in inputs if r["kind"] == gap.get("kind") and r["event_id"] == gap.get("ref")), None)
    name = " ".join(x for x in ((row or {}).get("date", ""), (row or {}).get("product", "")) if x) or "An input"
    return GAP_PROSE.get(gap["code"], gap["code"]).format(input=name)


@dataclass
class Gap:
    hop: str  # sale | picks | season | inputs
    code: str
    field: str = ""
    ref: Optional[int] = None  # the record the operator opens to fix it
    kind: str = ""  # which table `ref` is in, for an input: chemical | amendment | beneficial | seed


@dataclass
class Traceback:
    sale: dict
    picks_linked: bool
    picks: list = field(default_factory=list)
    season: dict = field(default_factory=dict)
    inputs: list = field(default_factory=list)
    balance: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _s(value) -> str:
    return (value or "").strip() if isinstance(value, str) or value is None else str(value)


def _iso(value) -> str:
    if value is None:
        return ""
    return value.date().isoformat() if hasattr(value, "date") and callable(value.date) else value.isoformat()


def _listing_code(chemical_event) -> str:
    from history.services import claim_authority

    label = claim_authority.may_claim_input_listing(chemical_event).safe_label
    for const, code in _LISTING_CODES.items():
        if getattr(claim_authority, const) == label:
            return code
    return "not_classified"


def _recorded_basis_code(value) -> str:
    """Seed / amendment / beneficial carry only the operator's own statement, never a listing."""
    from history.services.claim_resolver import ORGANIC_APPROVED_VALUES

    value = _s(value)
    if not value or value == "unknown":
        return "not_classified"
    return "recorded_by_farm" if value in ORGANIC_APPROVED_VALUES else "recorded_other"


def _seed_basis_code(status) -> str:
    """Seed status is its own vocabulary, not the organic_approved one: only certified organic seed
    is a recorded organic basis. Non-organic (treated or not) and transitional are recorded, and
    say so, never as "allowed"; whether untreated non-organic seed was permitted is a § 205.204
    commercial-availability question for the certifier, not something this page can decide."""
    status = _s(status)
    if not status:
        return "not_classified"
    return "recorded_by_farm" if status == "certified_organic" else "recorded_other"


#: Which event table each input kind lives in, as `GeneratedDocument.event_type` addresses it
#: (history.constants.EVENT_TYPE_TO_MODEL). A harvest pick is a ProductionEvent too.
_KIND_EVENT_TYPE = {"chemical": 2, "amendment": 5, "beneficial": 6, "seed": 1, "pick": 1}


def _doc(document, kind) -> dict:
    """A file the operation holds, by id: the page opens it through the farm's own documents
    route, which checks the caller's company. No storage URL leaves the server here."""
    return dict(id=document.pk, title=_s(document.title), kind=_s(kind))


def _attach_event_documents(establishment_id, rows_by_kind) -> None:
    """Add the files filed against each record (`GeneratedDocument.event_type/event_id`), in ONE
    query for the whole chain, scoped to the season's farm. `rows_by_kind` maps an input kind (or
    "pick") to its rows; each row gains its files under `documents`."""
    from django.db.models import Q

    from documents.models import GeneratedDocument

    wanted = Q()
    index = {}
    for kind, rows in rows_by_kind.items():
        event_type = _KIND_EVENT_TYPE[kind]
        for r in rows:
            index.setdefault((event_type, r.get("event_id", r.get("id"))), []).append(r)
        if rows:
            wanted |= Q(event_type=event_type, event_id__in=[r.get("event_id", r.get("id")) for r in rows])
    if not index or establishment_id is None:
        return
    docs = GeneratedDocument.objects.filter(wanted, establishment_id=establishment_id).order_by("created_at", "pk")
    for d in docs:
        for row in index.get((d.event_type, d.event_id), []):
            if all(x["id"] != d.pk for x in row["documents"]):
                row["documents"].append(_doc(d, "attachment"))


def _input_rows(season) -> list:
    """Every input applied in the season, oldest first, with its purchase identifiers."""
    from history.models import PestManagementEvent, ProductionEvent

    rows = []
    # One query for the listing evidence `may_claim_input_listing` reads, not two per spray.
    chemical = season.history_chemicalevent_events.select_related(
        "omri_product", "wsda_material", "national_list_substance", "receipt_document"
    )
    for ev in chemical:
        rows.append(
            dict(
                kind="chemical",
                event_id=ev.id,
                event_type=ev.type or "",
                date=_iso(ev.date),
                product=_s(ev.commercial_name),
                block=_s(ev.block_id),
                supplier=_s(ev.supplier_name),
                invoice=_s(ev.purchase_invoice),
                lot=_s(ev.chemical_lot_number),
                listing=_listing_code(ev),
                documents=[_doc(ev.receipt_document, "receipt")] if ev.receipt_document_id else [],
            )
        )
    for ev in season.history_soilmanagementevent_events.select_related("receipt_document"):
        product = _s(ev.amendment_product_name) or _s(ev.amendment_type)
        if not (product or _s(ev.amendment_supplier_name) or _s(ev.amendment_lot_number)):
            continue  # a soil test or tillage pass, not an input
        rows.append(
            dict(
                kind="amendment",
                event_id=ev.id,
                event_type=ev.type or "",
                date=_iso(ev.date),
                product=product,
                block=_s(ev.block_id),
                supplier=_s(ev.amendment_supplier_name),
                invoice=_s(ev.amendment_purchase_invoice),
                lot=_s(ev.amendment_lot_number),
                listing=_recorded_basis_code(ev.amendment_organic_approved),
                documents=[_doc(ev.receipt_document, "receipt")] if ev.receipt_document_id else [],
            )
        )
    for ev in season.history_pestmanagementevent_events.filter(type=PestManagementEvent.BENEFICIAL_RELEASE):
        rows.append(
            dict(
                kind="beneficial",
                event_id=ev.id,
                event_type=ev.type or "",
                date=_iso(ev.date),
                product=_s(ev.beneficial_species),
                block=_s(ev.block_id),
                supplier=_s(ev.beneficial_supplier),
                # No invoice field exists for a release; the supplier + lot are the link.
                invoice=None,
                lot=_s(ev.beneficial_lot_number),
                listing=_recorded_basis_code(ev.beneficial_organic_approved),
                documents=[],
            )
        )
    # Planting AND transplanting stock (§ 205.204). A planting that records no seed purchase at
    # all is left out: farm-saved seed or stock carried from a prior year has no supplier to
    # name, and listing it would print three gaps the operation cannot close.
    plantings = season.history_productionevent_events.filter(
        type__in=(ProductionEvent.PLANTING, ProductionEvent.TRANSPLANTING)
    )
    for ev in plantings:
        if not any(
            _s(v)
            for v in (ev.seed_supplier_name, ev.seed_purchase_invoice, ev.seed_lot_number, ev.seed_certification_status)
        ):
            continue
        rows.append(
            dict(
                kind="seed",
                event_id=ev.id,
                event_type=ev.type or "",
                date=_iso(ev.date),
                product=_s(ev.variety),
                block=_s(ev.block_id),
                supplier=_s(ev.seed_supplier_name),
                invoice=_s(ev.seed_purchase_invoice),
                lot=_s(ev.seed_lot_number),
                listing=_seed_basis_code(ev.seed_certification_status),
                documents=[],
            )
        )
    rows.sort(key=lambda r: (r["date"], r["kind"], r["event_id"]))
    return rows


def trace_sale(sale) -> Traceback:
    """Walk one live sale back to its picks, its season and the season's inputs."""
    from history.models import ProductionEvent, SalesRecord

    season = sale.production
    gaps: list[Gap] = []

    invoice, bol = _s(sale.invoice_number), _s(sale.bill_of_lading)
    if not (invoice or bol):
        gaps.append(Gap("sale", "no_sale_document", "invoice_number", sale.pk))
    if sale.organic_on_invoice and not sale.organic_label_category:
        gaps.append(Gap("sale", "label_category_not_recorded", "organic_label_category", sale.pk))
    # The invoice, bill of lading or pack-out FILE behind the numbers above. Without one the packet
    # prints the numbers as text only (the sales row already says so), and the inspector asks to
    # see the paper. Same farm only, whatever the FK says.
    sale_docs = [
        _doc(d, d.source_kind or "other")
        for d in sale.source_documents.filter(establishment_id=season.parcel.establishment_id).order_by(
            "created_at", "pk"
        )
    ]
    if not sale_docs:
        gaps.append(Gap("sale", "sale_without_document", "source_documents", sale.pk))
    sale_row = dict(
        id=sale.pk,
        documents=sale_docs,
        date=_iso(sale.sale_date),
        buyer=_s(sale.buyer_name),
        quantity=_fmt_qty(sale.quantity, sale.quantity_unit),
        invoice=invoice,
        bol=bol,
        organic_on_invoice=bool(sale.organic_on_invoice),
        label_category=sale.organic_label_category or "",
    )

    linked = list(sale.harvest_events.order_by("date", "pk"))
    picks = linked or list(
        ProductionEvent.objects.filter(history=season, type=ProductionEvent.HARVESTING).order_by("date", "pk")
    )
    if not linked:
        gaps.append(Gap("picks", "sale_not_linked_to_pick", "harvest_events", sale.pk))
    pick_rows = []
    for ev in picks:
        lot = _s(ev.harvest_lot_code)
        if not lot:
            gaps.append(Gap("picks", "pick_without_lot_code", "harvest_lot_code", ev.pk))
        pick_rows.append(
            dict(
                id=ev.pk,
                lot_code=lot,
                date=_iso(ev.date),
                block=_s(ev.block_id),
                quantity=_fmt_qty(ev.yield_quantity, ev.yield_unit),
                storage=_s(ev.storage_location),
                destination=_s(ev.harvest_destination),
                sent_to_handler_date=_iso(ev.sent_to_handler_date),
                quantity_sent_to_handler=_fmt_qty(ev.quantity_sent_to_handler, ev.handler_quantity_unit),
                quantity_returned_from_handler=_fmt_qty(
                    ev.quantity_returned_from_handler, ev.handler_return_unit or ev.yield_unit
                ),
                handler_document=_s(ev.handler_document_reference),
                # A bin receipt or weigh ticket filed on the pick. Shown, not required: many loads
                # go out under the packer's receipt, which is the sale's document.
                documents=[],
            )
        )

    # The same precondition `claim_authority.may_label_container` refuses a container tag on
    # (§ 205.307(a)(2)): no lot ID on the season, nothing on the box links back to it.
    if not _s(season.lot_id):
        gaps.append(Gap("season", "season_without_lot_id", "lot_id", None))
    season_row = dict(
        # The internal id the Documents filing dialog selects a season by (owner-only payload).
        id=season.pk,
        public_id=str(season.public_id),
        name=_s(season.name),
        crop=_s(getattr(season.product, "name", None)) or _s(getattr(season.crop_type, "name", None)),
        parcel=season.parcel.name if season.parcel else "",
        parcel_id=season.parcel_id,
        establishment_id=season.parcel.establishment_id if season.parcel else None,
        # The page builds file links on the company-scoped documents route; it must not depend on
        # which company the app happens to have loaded (a direct link loads none: MEASURED, the
        # first browser run built `/companies//establishments/...`).
        company_id=season.parcel.establishment.company_id if season.parcel else None,
        lot_id=_s(season.lot_id),
    )

    pick_blocks = {r["block"] for r in pick_rows if r["block"]}
    inputs = _input_rows(season)
    _attach_event_documents(
        season.parcel.establishment_id if season.parcel else None,
        {
            "pick": pick_rows,
            **{
                kind: [r for r in inputs if r["kind"] == kind]
                for kind in ("chemical", "amendment", "beneficial", "seed")
            },
        },
    )
    for row in inputs:
        # Shown, never hidden: whether a neighbouring block's spray reached this pick is the
        # operator's call, and the inspector will ask either way.
        row["other_block"] = bool(pick_blocks and row["block"] and row["block"] not in pick_blocks)
        for fld in ("supplier", "invoice", "lot"):
            if row[fld] == "":  # None = the record type has no such field
                gaps.append(Gap("inputs", f"input_without_{fld}", fld, row["event_id"], row["kind"]))
        # The purchase receipt behind the invoice number. Only for the two record types that carry
        # a receipt field; a beneficial release or a seed lot can still show a filed attachment.
        if row["kind"] in ("chemical", "amendment") and not row["documents"]:
            gaps.append(Gap("inputs", "input_without_document", "receipt_document", row["event_id"], row["kind"]))

    all_harvests = list(ProductionEvent.objects.filter(history=season, type=ProductionEvent.HARVESTING))
    balance = _lot_balance(all_harvests, list(SalesRecord.objects.live().filter(production=season)))
    diff = balance.difference
    balance_row = dict(
        harvested=fmt_total(balance.harvested, balance.unit) if balance.harvested is not None else "",
        sold=fmt_total(balance.sold, balance.unit) if balance.sold is not None else "",
        packed_out=fmt_total(balance.packed_out, balance.unit) if balance.packed_out is not None else "",
        difference=fmt_total(diff, balance.unit) if diff is not None else "",
        # The reason is English certifier prose (the exhibit prints it); the screen says only that
        # the two sides cannot be summed and lists the records, which name why.
        not_computed=bool(balance.not_computed),
        # Sales NOT identified as organic on the invoice are counted apart by `_lot_balance` (a
        # buffer-row crop sold conventional). Dropping them made "sold" read short, with a
        # confident difference and no sign anything was left out; the exhibit prints them beside
        # the balance, and so does this.
        sold_not_organic_count=balance.buffer_sale_count,
        sold_not_organic=(
            fmt_total(balance.buffer_sold, balance.unit) if balance.buffer_sold is not None and balance.unit else ""
        ),
    )

    return Traceback(
        sale=sale_row,
        picks_linked=bool(linked),
        picks=pick_rows,
        season=season_row,
        inputs=inputs,
        balance=balance_row,
        gaps=[asdict(g) for g in gaps],
    )
