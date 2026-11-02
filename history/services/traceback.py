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

FROM A HARVEST LOT
------------------
The inspector also points at product IN STORAGE, not yet sold, and asks for the records behind
it. `trace_pick` starts there: the same hop builders (`_pick_rows`, `_season_row`, `_input_chain`,
`_balance_row`) minus the sale, plus where the pick went (the live sales that name it), so the lot
reads both directions. Every rule above holds there too.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from certifications.services.audit_trail_exhibit import _fmt_qty, _lot_balance, fmt_total
from history.services import supplier_certificates
from history.services.record_receipts import RECEIPT_KIND, receipt_files
from history.services.supplier_certificates import purchase_date_of

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
    "pick_without_lot_code": "{input}: harvest pick with no lot code.",
    "season_without_lot_id": "The season has no lot ID recorded.",
    "input_without_supplier": "{input}: no supplier recorded.",
    "input_without_invoice": "{input}: no purchase invoice number recorded.",
    "input_without_lot": "{input}: no supplier lot number recorded.",
    "input_without_document": "{input}: no purchase receipt file attached.",
    "supplier_certificate_missing": (
        "{input}: recorded as certified organic, with no supplier organic certificate on file that covers the purchase."
    ),
}


def gap_sentence(gap: dict, inputs: list, picks: list = ()) -> str:
    """One gap as the packet prints it, naming the record it is about.

    A pick gap names the pick (date, block, quantity): a sale can name several picks, and two
    without a lot code printed as identical lines nobody could act on (review of back #193).
    """
    if gap.get("hop") == "picks":
        row = next((p for p in picks if p.get("id") == gap.get("ref")), None) or {}
        bits = [row.get("date", ""), f"block {row['block']}" if row.get("block") else "", row.get("quantity", "")]
        name = " · ".join(x for x in bits if x) or "A harvest pick"
    else:
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


def _receipt(ev, season) -> list:
    """The record's receipt file, only when it belongs to the season's own farm.

    The FK is not trusted: the create path checks only the company (the season is resolved after
    validation), so a multi-farm company could link another farm's file. Shown here, it would put
    that farm's document on this trace and hide the missing-receipt gap (review of back #191).
    """
    doc = ev.receipt_document
    farm = season.parcel.establishment_id if season.parcel else None
    return [_doc(doc, "receipt")] if doc is not None and farm is not None and doc.establishment_id == farm else []


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
                # A purchase receipt filed on the record is a receipt; anything else filed there (a
                # lab report, a photo) is shown, but as an attachment (record_receipts.RECEIPT_KIND).
                row["documents"].append(_doc(d, "receipt" if d.source_kind == RECEIPT_KIND else "attachment"))


def _seed_is_purchase(ev) -> bool:
    """Whether a planting record names a seed or stock PURCHASE, so a receipt can exist for it.

    A seed row is listed when any purchase identifier is recorded, a lot or a status alone
    included. A receipt is asked for only when the record names an invoice or a supplier and the
    seed is not farm-saved: a gap the grower can never close is noise, and noise teaches growers
    to read past the gaps that matter.
    """
    return supplier_certificates.is_seed_purchase(ev)


def _attach_receipts(inputs) -> None:
    """Add the receipts a record holds through its multi-parcel group (`record_receipts`).

    `_receipt` and `_attach_event_documents` already put the record's own files on its row. A
    receipt filed on ANOTHER record of the same application (one purchase logged on several
    parcels) is this record's receipt too; it is added here with `filed_on`, the parcels whose
    records it was filed on, so the page says where it lives. A constant number of queries for the
    whole chain.
    """
    from history.models import ChemicalEvent, ProductionEvent, SoilManagementEvent

    ids = {kind: [r["event_id"] for r in inputs if r["kind"] == kind] for kind in ("chemical", "amendment", "seed")}
    events = [
        *(ChemicalEvent.objects.filter(pk__in=ids["chemical"]).only("pk") if ids["chemical"] else []),
        *(SoilManagementEvent.objects.filter(pk__in=ids["amendment"]).only("pk") if ids["amendment"] else []),
        *(ProductionEvent.objects.filter(pk__in=ids["seed"]).only("pk", "type") if ids["seed"] else []),
    ]
    if not events:
        return
    files = receipt_files(events)
    for row in inputs:
        if row["kind"] not in ids:
            continue
        key = (_KIND_EVENT_TYPE[row["kind"]], row["event_id"])
        for d in files.get(key, []):
            if all(x["id"] != d.pk for x in row["documents"]):
                row["documents"].append(dict(_doc(d, "receipt"), filed_on=list(files.shared_from.get(key, ()))))


def _attach_supplier_certificates(establishment_id, inputs) -> None:
    """Put each seed row's supplier certificate on it (`supplier_certificates.resolve`).

    `supplier_certificate` is None on rows of other kinds. On a seed row it says which register
    supplier the record's text resolves to, if any, and the certificate copy that covered the
    purchase. Two queries for the whole chain.
    """
    queries = {}
    for i, row in enumerate(inputs):
        query = row.pop("_supplier_query", None)
        row.setdefault("certificate_expected", False)
        row["supplier_certificate"] = None
        if row["kind"] == "seed" and query is not None:
            queries[i] = query
    for i, evidence in supplier_certificates.resolve(establishment_id, queries).items():
        inputs[i]["supplier_certificate"] = evidence


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
                documents=_receipt(ev, season),
                receipt_expected=True,
                # The label PHI as the operation recorded it; `trace_sale` sets the days to the
                # next pick beside it.
                # `format(..., "f")`: a bare `normalize()` prints a 10-day PHI as "1E+1".
                phi_days=format(ev.phi_days.normalize(), "f") if ev.phi_days is not None else "",
                # Mating-disruption dispensers hang in the canopy and touch no fruit: no PHI.
                dispensers=ev.application_method_structured == "hand_dispenser",
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
                documents=_receipt(ev, season),
                receipt_expected=True,
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
                receipt_expected=False,
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
                receipt_expected=_seed_is_purchase(ev),
                # Read by `_attach_supplier_certificates`, which removes it.
                _supplier_query=(ev.seed_supplier_name, purchase_date_of(ev)),
                certificate_expected=supplier_certificates.certificate_expected(ev),
            )
        )
    rows.sort(key=lambda r: (r["date"], r["kind"], r["event_id"]))
    return rows


#: Past this many matches the search says `truncated` rather than dropping rows silently.
MATCH_CAP = 20


def search_sales(sales, q: str = "", random: bool = False) -> dict:
    """The sale(s) an inspector's document number points at, from an already-SCOPED queryset.

    Shared by the operation's own page and the certifier review link: each caller decides WHICH
    sales are in scope (the caller's companies; the link's farm and window), this decides how a
    number matches. `q` is matched exactly (trimmed, case-insensitive) against the invoice, the
    bill of lading, a harvest pick's lot code, the packer's receipt or weigh ticket on a pick, the
    season's lot ID, and an input's lot number or purchase invoice. None is unique, so every match
    is returned and nobody picks for the reader. A pick code or packer receipt also finds the sales
    of the pick's season that name NO pick (the commonest gap); a sale that names another pick
    already says where it came from. An input's lot or invoice finds every sale of each season it
    was applied in: the supplier-recall question ("where did the crop from that compost go?"),
    answered wide on purpose, since a recall list that leaves a sale out is the failure that
    matters. `random` returns one live sale from the last 12 months.
    """
    from datetime import timedelta

    from django.utils import timezone

    if random:
        sale = sales.filter(sale_date__gte=timezone.now().date() - timedelta(days=365)).order_by("?").first()
        matches = [(sale, "random")] if sale else []
    else:
        matched_on = {}
        # Order matters: a sale that names the pick keeps that label over the season fallback.
        for label, lookup in (
            ("invoice", {"invoice_number__iexact": q}),
            ("bill_of_lading", {"bill_of_lading__iexact": q}),
            ("pick_lot_code", {"harvest_events__harvest_lot_code__iexact": q}),
            (
                "pick_lot_code_season",
                {
                    "production__history_productionevent_events__harvest_lot_code__iexact": q,
                    "production__history_productionevent_events__type": "HA",
                    "harvest_events__isnull": True,
                },
            ),
            ("handler_document", {"harvest_events__handler_document_reference__iexact": q}),
            (
                "handler_document_season",
                {
                    "production__history_productionevent_events__handler_document_reference__iexact": q,
                    "production__history_productionevent_events__type": "HA",
                    "harvest_events__isnull": True,
                },
            ),
            ("season_lot_id", {"production__lot_id__iexact": q}),
            # One lookup per record type, not one OR across them: an OR over four reverse
            # relations joins them all at once and multiplies the rows before `distinct()`.
            ("input_lot", {"production__history_chemicalevent_events__chemical_lot_number__iexact": q}),
            ("input_lot", {"production__history_soilmanagementevent_events__amendment_lot_number__iexact": q}),
            ("input_lot", {"production__history_pestmanagementevent_events__beneficial_lot_number__iexact": q}),
            ("input_lot", {"production__history_productionevent_events__seed_lot_number__iexact": q}),
            ("input_invoice", {"production__history_chemicalevent_events__purchase_invoice__iexact": q}),
            (
                "input_invoice",
                {"production__history_soilmanagementevent_events__amendment_purchase_invoice__iexact": q},
            ),
            ("input_invoice", {"production__history_productionevent_events__seed_purchase_invoice__iexact": q}),
        ):
            for sale in sales.filter(**lookup).distinct():
                matched_on.setdefault(sale.pk, (sale, label))
        matches = sorted(matched_on.values(), key=lambda m: (m[0].sale_date, m[0].pk), reverse=True)
    return {
        "results": [
            {
                "sale_id": sale.pk,
                "date": sale.sale_date,
                "buyer": sale.buyer_name,
                "invoice": sale.invoice_number,
                # A lot or input search reads as a recall list: who got how much.
                "quantity": _fmt_qty(sale.quantity, sale.quantity_unit),
                "crop": getattr(sale.production.product, "name", "") or "",
                "parcel": sale.production.parcel.name if sale.production.parcel else "",
                "season": sale.production.name or "",
                "matched_on": label,
            }
            for sale, label in matches[:MATCH_CAP]
        ],
        "truncated": len(matches) > MATCH_CAP,
    }


def _set_days_to_pick(row: dict, pick_rows: list) -> None:
    """Days from a spray to the first pick in this trace on or after it, beside the recorded PHI.

    The question a buyer's residue finding or an export MRL check starts with. Arithmetic on the
    operation's own dates, never a verdict on the label: `inside_phi` only says the pick came
    sooner than the PHI the operation itself recorded. A pick on another block does not count
    when both records name a block. Only sprays carry a PHI; other inputs get None, and so does a
    fertilizer or a set of pheromone dispensers with no PHI recorded, where "no PHI recorded" would
    read as a missing record.
    """
    no_phi_applies = row["kind"] == "chemical" and (row["event_type"] == "FE" or row["dispensers"])
    if row["kind"] != "chemical" or not row["date"] or (no_phi_applies and not row["phi_days"]):
        row.update(days_to_pick=None, inside_phi=False)
        return
    applied = date.fromisoformat(row["date"])
    waits = [
        (date.fromisoformat(p["date"]) - applied).days
        for p in pick_rows
        if p["date"] >= row["date"] and not (row["block"] and p["block"] and p["block"] != row["block"])
    ]
    days = min(waits) if waits else None
    phi = Decimal(row["phi_days"]) if row["phi_days"] else None
    row.update(days_to_pick=days, inside_phi=days is not None and phi is not None and days < phi)


def _pick_row(ev) -> dict:
    """One harvest pick as every trace prints it, whichever end the trace starts from."""
    return dict(
        id=ev.pk,
        lot_code=_s(ev.harvest_lot_code),
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


def _pick_rows(picks, gaps: list) -> list:
    rows = []
    for ev in picks:
        row = _pick_row(ev)
        if not row["lot_code"]:
            gaps.append(Gap("picks", "pick_without_lot_code", "harvest_lot_code", ev.pk))
        rows.append(row)
    return rows


def _season_row(season, gaps: list) -> dict:
    # The same precondition `claim_authority.may_label_container` refuses a container tag on
    # (§ 205.307(a)(2)): no lot ID on the season, nothing on the box links back to it.
    if not _s(season.lot_id):
        gaps.append(Gap("season", "season_without_lot_id", "lot_id", None))
    return dict(
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


def _input_chain(season, pick_rows: list, gaps: list) -> list:
    """The season's inputs with their files, receipts and supplier certificates, each missing
    identifier named as a gap. Also files the picks' own documents (one query for the chain).
    Days to pick are counted against `pick_rows`: the picks THIS trace walks through."""
    farm = season.parcel.establishment_id if season.parcel else None
    pick_blocks = {r["block"] for r in pick_rows if r["block"]}
    inputs = _input_rows(season)
    _attach_event_documents(
        farm,
        {
            "pick": pick_rows,
            **{
                kind: [r for r in inputs if r["kind"] == kind]
                for kind in ("chemical", "amendment", "beneficial", "seed")
            },
        },
    )
    _attach_receipts(inputs)
    _attach_supplier_certificates(farm, inputs)
    for row in inputs:
        _set_days_to_pick(row, pick_rows)
        # Shown, never hidden: whether a neighbouring block's spray reached this pick is the
        # operator's call, and the inspector will ask either way.
        row["other_block"] = bool(pick_blocks and row["block"] and row["block"] not in pick_blocks)
        for fld in ("supplier", "invoice", "lot"):
            if row[fld] == "":  # None = the record type has no such field
                gaps.append(Gap("inputs", f"input_without_{fld}", fld, row["event_id"], row["kind"]))
        # The purchase receipt behind the invoice number: sprays, amendments and seed or stock
        # purchases (`receipt_expected`; a farm-saved or lot-only planting asks for none). A
        # beneficial release can still show a filed attachment.
        if row["receipt_expected"] and not any(d["kind"] == "receipt" for d in row["documents"]):
            gaps.append(Gap("inputs", "input_without_document", "receipt_document", row["event_id"], row["kind"]))
        # A certified organic seed or stock purchase is a claim; the supplier's certificate is its
        # evidence. Only a copy covering the purchase date closes this (`supplier_certificates`).
        evidence = row["supplier_certificate"]
        if row["certificate_expected"] and (evidence is None or evidence["status"] != supplier_certificates.COVERING):
            gaps.append(Gap("inputs", "supplier_certificate_missing", "supplier", row["event_id"], row["kind"]))
    return inputs


def _balance_row(season) -> dict:
    """The season's harvested minus sold (`_lot_balance`), live sales only."""
    from history.models import ProductionEvent, SalesRecord

    all_harvests = list(ProductionEvent.objects.filter(history=season, type=ProductionEvent.HARVESTING))
    balance = _lot_balance(all_harvests, list(SalesRecord.objects.live().filter(production=season)))
    diff = balance.difference
    return dict(
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
        # Sales are recorded while the season is still being picked. Until it is finished these
        # are the picks and sales on file so far, and "harvested minus sold" is product not yet
        # sold as much as anything missing, so the screen says the season is open.
        season_open=season.finish_date is None,
    )


def trace_sale(sale) -> Traceback:
    """Walk one live sale back to its picks, its season and the season's inputs."""
    from history.models import ProductionEvent

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
    sale_docs = (
        [
            _doc(d, d.source_kind or "other")
            for d in sale.source_documents.filter(establishment_id=season.parcel.establishment_id).order_by(
                "created_at", "pk"
            )
        ]
        if season.parcel
        else []
    )
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
    pick_rows = _pick_rows(picks, gaps)
    season_row = _season_row(season, gaps)
    inputs = _input_chain(season, pick_rows, gaps)

    return Traceback(
        sale=sale_row,
        picks_linked=bool(linked),
        picks=pick_rows,
        season=season_row,
        inputs=inputs,
        balance=_balance_row(season),
        gaps=[asdict(g) for g in gaps],
    )


@dataclass
class LotTraceback:
    """The same chain anchored on one harvest pick: product in storage, not yet (or not all) sold.

    `picks` holds the one anchored pick, so a screen renders it with the sale trace's own pick
    card. `sales` reads the lot forward (the live sales that name the pick); the season and inputs
    read it backward, exactly as from a sale.
    """

    anchor: str
    picks: list
    sales: list = field(default_factory=list)
    sales_naming_no_pick: list = field(default_factory=list)
    season: dict = field(default_factory=dict)
    inputs: list = field(default_factory=list)
    balance: dict = field(default_factory=dict)
    gaps: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _forward_sale_row(sale) -> dict:
    return dict(
        sale_id=sale.pk,
        date=_iso(sale.sale_date),
        buyer=_s(sale.buyer_name),
        quantity=_fmt_qty(sale.quantity, sale.quantity_unit),
        invoice=_s(sale.invoice_number),
        bol=_s(sale.bill_of_lading),
        organic_on_invoice=bool(sale.organic_on_invoice),
        # How many picks the sale names in all: a load that combines this pick with others says
        # so, and the screen does not read the sale's whole quantity as this pick's.
        picks_named=len(sale.harvest_events.all()),
    )


def trace_pick(pick) -> LotTraceback:
    """Walk one harvest pick back to its season and inputs, and forward to the sales that name it.

    Same hops and gap codes as `trace_sale` minus the sale. A pick that no sale names is not a gap:
    product in storage is the reason this entry point exists. The season's live sales that name NO
    pick are listed beside it (`sales_naming_no_pick`), the way `trace_sale` lists a season's picks
    for an unlinked sale: one of them may be where this pick went, and only the operator knows.
    Sales are read from the pick's own season only (the sale serializer refuses a pick from another
    production; this does not trust that alone). Voided sales never appear.
    """
    from history.models import SalesRecord

    season = pick.history
    gaps: list[Gap] = []
    pick_rows = _pick_rows([pick], gaps)
    season_row = _season_row(season, gaps)
    inputs = _input_chain(season, pick_rows, gaps)

    live = SalesRecord.objects.live().filter(production=season).prefetch_related("harvest_events")
    named = live.filter(harvest_events=pick).distinct().order_by("sale_date", "pk")
    unlinked = live.filter(harvest_events__isnull=True).order_by("sale_date", "pk")

    return LotTraceback(
        anchor="pick",
        picks=pick_rows,
        sales=[_forward_sale_row(s) for s in named],
        sales_naming_no_pick=[_forward_sale_row(s) for s in unlinked],
        season=season_row,
        inputs=inputs,
        balance=_balance_row(season),
        gaps=[asdict(g) for g in gaps],
    )


def search_picks(picks, q: str) -> dict:
    """The harvest pick(s) a number read off a bin tag, a pallet or a packer's receipt points at.

    `picks` is an already-SCOPED queryset of harvest events (the caller's companies; a certifier
    link's farm and window). `q` is matched exactly (trimmed, case-insensitive) against the pick's
    lot code, the packer's receipt or weigh ticket on it, and the season's lot ID (which finds every
    pick of that season). None is unique, so every match is returned and nobody picks for the
    reader; past `MATCH_CAP`, `truncated` says so.
    """
    matched_on = {}
    for label, lookup in (
        ("pick_lot_code", {"harvest_lot_code__iexact": q}),
        ("handler_document", {"handler_document_reference__iexact": q}),
        ("season_lot_id", {"history__lot_id__iexact": q}),
    ):
        for ev in picks.filter(**lookup).select_related("history__product", "history__parcel").distinct():
            matched_on.setdefault(ev.pk, (ev, label))
    matches = sorted(matched_on.values(), key=lambda m: (m[0].date, m[0].pk), reverse=True)
    return {
        "results": [
            {
                "pick_id": ev.pk,
                "date": _iso(ev.date),
                "lot_code": _s(ev.harvest_lot_code),
                "block": _s(ev.block_id),
                "quantity": _fmt_qty(ev.yield_quantity, ev.yield_unit),
                "storage": _s(ev.storage_location),
                "crop": getattr(ev.history.product, "name", "") or "",
                "parcel": ev.history.parcel.name if ev.history.parcel else "",
                "season": ev.history.name or "",
                "matched_on": label,
            }
            for ev, label in matches[:MATCH_CAP]
        ],
        "truncated": len(matches) > MATCH_CAP,
    }
