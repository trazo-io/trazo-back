"""
The CCOF *Recordkeeping Checklist for Organic Growers*, item by item, against the packet.

Source: ccof.org, "Recordkeeping-checklist-for-Growers-3.pdf" — one page, eight checkboxes.
Audited 2026-08-16. Items 2, 3, 4 and 5 were already covered past what the checklist asks;
these tests pin the four that were not, so a later refactor cannot quietly undo them:

  item 1 — receipts for "fertilizer, compost, soil amendments, planting mixes". Chemical
           inputs had supplier / date / invoice / quantity / lot; amendments had none, so the
           mass-balance section built its "Inputs Purchased" table from ChemicalEvent alone and
           printed an unclearable "[REVIEW] Mass balance cannot be reconciled" for any operation
           whose main input is compost.
  item 2 — "what you plant, when you planted it, and WHERE it was planted". The planting table
           had no Block column, although the harvest table (fixed 2026-08-15) does.
  item 6 — "what you sent, where you sent it, when you sent it, and what you received as the
           outcome". Only *where* existed; the outcome was inferred shrinkage, not a record.
  item 7 — "what you sell, how much you sell, who you sold it to, and how much money you
           received". The first three were thorough; there was no amount column anywhere.

Every assertion reads the RENDERED flowables, not the model — a field that exists and does not
print is the failure mode this file exists to catch.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from reportlab.platypus import Table

from company.models import Company, Establishment
from history.models import History, ProductionEvent, SalesRecord, SoilManagementEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product


def _text(elements):
    """Every Paragraph string in a section, joined."""
    return " ".join(getattr(el, "text", "") or "" for el in elements)


def _table_cells(elements):
    """Every cell's text across every Table in a section.

    Cells are Paragraphs (so ReportLab word-wraps them), which is why this reaches into
    `.text` rather than comparing strings directly.
    """
    out = []
    for el in elements:
        if isinstance(el, Table):
            for row in el._cellvalues:
                for cell in row:
                    out.append(getattr(cell, "text", "") or str(cell))
    return out


class CCOFChecklistBase(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Checklist Co")
        self.establishment = Establishment.objects.create(name="Checklist Farm", company=self.company)
        self.parcel = Parcel.objects.create(name="Home Block", establishment=self.establishment, area=20.0)
        self.product = Product.objects.create(name="Walnut")
        self.production = History.objects.create(
            name="Walnut 2026",
            parcel=self.parcel,
            product=self.product,
            start_date=timezone.now() - timedelta(days=200),
        )

    def _service(self):
        return AuditExportService(self.production, certification_type="organic")


class Item1AmendmentPurchaseTests(CCOFChecklistBase):
    """'Keep records of all the … input materials (fertilizer, compost, soil amendments,
    planting mixes, etc.) you use … Receipts for purchases.'"""

    def _amendment(self, **kw):
        defaults = dict(
            history=self.production,
            date=timezone.now(),
            description="Compost application",
            type="OM",
            amendment_type="compost",
            amendment_product_name="Bu's Blend Compost",
        )
        defaults.update(kw)
        return SoilManagementEvent.objects.create(**defaults)

    def test_supplier_and_invoice_print_in_the_soil_section(self):
        self._amendment(
            amendment_supplier_name="Central Valley Compost Supply",
            amendment_purchase_date=timezone.now().date(),
            amendment_purchase_invoice="INV-20614",
            amendment_lot_number="LOT-CVC-8841",
            amendment_quantity_purchased=12,
            amendment_quantity_purchased_unit="tons",
        )
        cells = _table_cells(self._service()._build_soil_section())
        self.assertIn("Central Valley Compost Supply", cells)
        self.assertIn("INV-20614", cells)
        self.assertIn("LOT-CVC-8841", cells)

    def test_no_purchase_prints_no_subtable(self):
        """On-farm compost is not a purchase; an empty row would invent a gap."""
        self._amendment()
        self.assertNotIn(
            "Amendment Supplier",
            _text(self._service()._build_soil_section()),
        )

    def test_amendment_purchase_reaches_the_mass_balance(self):
        """The point of the whole fix: a compost-only operation can clear the [REVIEW] flag."""
        self._amendment(
            amendment_supplier_name="Central Valley Compost Supply",
            amendment_purchase_invoice="INV-20614",
            amendment_quantity_purchased=12,
            amendment_quantity_purchased_unit="tons",
        )
        elements = self._service()._build_mass_balance_section()
        self.assertNotIn("Mass balance cannot be reconciled", _text(elements))
        self.assertIn("Central Valley Compost Supply", _table_cells(elements))

    def test_no_purchases_anywhere_still_flags_review(self):
        """The flag must still fire when there is genuinely nothing to reconcile."""
        self._amendment()
        self.assertIn(
            "Mass balance cannot be reconciled",
            _text(self._service()._build_mass_balance_section()),
        )


class Item2PlantingLocationTests(CCOFChecklistBase):
    """'Keep records of what you plant, when you planted it, and where it was planted.'"""

    def test_planting_table_names_the_block(self):
        ProductionEvent.objects.create(
            history=self.production,
            date=timezone.now() - timedelta(days=190),
            description="Replanted 40 Hass",
            type="PL",
            variety="Hass",
            block_id="Block 7",
            seeds_source="commercial",
        )
        self.assertIn("Block 7", _table_cells(self._service()._build_seed_stock_section()))


class Item6HandlerRoundTripTests(CCOFChecklistBase):
    """'Keep records of what you sent, where you sent it, when you sent it, and what you
    received as the outcome.'"""

    def _harvest(self, **kw):
        defaults = dict(
            history=self.production,
            date=timezone.now() - timedelta(days=20),
            description="First pick",
            type="HA",
            harvest_lot_code="WAL-B7-20260928",
        )
        defaults.update(kw)
        return ProductionEvent.objects.create(**defaults)

    def test_sent_and_returned_quantities_print(self):
        self._harvest(
            harvest_destination="handler",
            sent_to_handler_date=(timezone.now() - timedelta(days=18)).date(),
            quantity_sent_to_handler=42000,
            handler_quantity_unit="lbs",
            quantity_returned_from_handler=13400,
            handler_return_unit="lbs",
            handler_document_reference="PACKOUT-2026-114",
        )
        elements = self._service()._build_post_harvest_section()
        cells = _table_cells(elements)
        self.assertIn("42,000.00 lbs", cells)
        self.assertIn("13,400.00 lbs", cells)
        self.assertIn("PACKOUT-2026-114", cells)
        self.assertIn("WAL-B7-20260928", cells)

    def test_load_sent_with_nothing_back_is_flagged_for_review(self):
        self._harvest(
            harvest_destination="handler",
            sent_to_handler_date=(timezone.now() - timedelta(days=18)).date(),
            quantity_sent_to_handler=42000,
            handler_quantity_unit="lbs",
        )
        text = _text(self._service()._build_post_harvest_section())
        self.assertIn("[REVIEW]", text)
        self.assertIn("no returned quantity recorded", text)

    def test_field_run_sale_prints_no_handler_table(self):
        self._harvest(harvest_destination="sold_direct")
        self.assertNotIn(
            "Crop Sent for Off-Farm Handling",
            _text(self._service()._build_post_harvest_section()),
        )

    def test_shipment_with_no_handler_named_is_flagged(self):
        """Crop left for handling and nobody recorded WHO handled it — the certificate
        cannot travel with the lot, and that is a specific answerable gap, not a reminder."""
        self._harvest(
            harvest_destination="handler",
            sent_to_handler_date=(timezone.now() - timedelta(days=18)).date(),
            quantity_sent_to_handler=42000,
            handler_quantity_unit="lbs",
            quantity_returned_from_handler=13400,
            handler_return_unit="lbs",
        )
        text = _text(self._service()._build_post_harvest_section())
        self.assertIn("no handler is recorded for this production", text)

    def test_the_farms_own_cooler_is_not_named_as_an_off_farm_handler(self):
        """The warning must not assert that the operation shipped to its own building.

        🔴 2026-08-21 — the named list was built from `storage_location` FIRST, so on an
        operation that cools and packs its own fruit the packet read "this lot was sent for
        off-farm handling to Farm cooler". A finding that is false on its face is discounted
        by the reviewer, and the underlying § 205.272 gap — a real off-farm handler with no
        certificate on file — goes unfixed with it.
        """
        from history.models import ProductionEvent

        h = self._harvest(
            harvest_destination="handler",
            sent_to_handler_date=(timezone.now() - timedelta(days=18)).date(),
            quantity_sent_to_handler=42000,
            handler_quantity_unit="lbs",
        )
        ProductionEvent.objects.create(
            history=self.production,
            type="PH",
            date=timezone.now() - timedelta(days=17),
            description="Forced-air cooling",
            storage_location="Farm cooler, 34F",
        )
        ProductionEvent.objects.create(
            history=self.production,
            type="TP",
            date=timezone.now() - timedelta(days=16),
            description="Reefer to the packer",
            transport_destination_address="Willamette Valley Fruit, Salem OR",
        )
        text = _text(self._service()._build_post_harvest_section())
        self.assertIn("Willamette Valley Fruit", text)
        self.assertNotIn("off-farm handling to Farm cooler", text)
        self.assertNotIn("sent for off-farm handling to Farm cooler, 34F", text)

    def test_handler_is_an_offered_destination(self):
        """Without this option a grower records the huller as a BUYER, which puts a non-sale
        into the § 205.307 itemized sales table and breaks the mass balance."""
        self.assertIn("handler", dict(ProductionEvent._meta.get_field("harvest_destination").choices))


class Item7SalesAmountTests(CCOFChecklistBase):
    """'Keep track of what you sell, how much you sell, who you sold it to, and how much money
    you received.'"""

    def _sale(self, **kw):
        defaults = dict(
            production=self.production,
            sale_date=timezone.now().date(),
            buyer_name="Sunrise Packing",
            quantity=13400,
            quantity_unit="lb",
        )
        defaults.update(kw)
        return SalesRecord.objects.create(**defaults)

    def test_amount_prints_in_the_itemized_sales_table(self):
        self._sale(sale_amount=48240)
        cells = _table_cells(self._service()._build_mass_balance_section())
        self.assertIn("$48,240.00", cells)

    def test_recorded_zero_is_not_hidden(self):
        """A donation or a rejected load taken at no charge is a FACT, not a blank."""
        self._sale(sale_amount=0)
        self.assertIn("$0.00", _table_cells(self._service()._build_mass_balance_section()))

    def test_total_only_prints_when_every_sale_is_priced(self):
        """A total over a partly-filled column understates sales — and the CDFA $5,000
        registration threshold turns on that number."""
        self._sale(sale_amount=48240)
        self._sale(buyer_name="Second Buyer", quantity=2000)
        text = _text(self._service()._build_mass_balance_section())
        self.assertNotIn("Total Sales Recorded", text)
        self.assertIn("1 of 2 sales have no amount recorded", text)

    def test_total_prints_when_all_are_priced(self):
        self._sale(sale_amount=48240)
        self._sale(buyer_name="Second Buyer", quantity=2000, sale_amount=7200)
        self.assertIn(
            "$55,440.00",
            _text(self._service()._build_mass_balance_section()),
        )


class AttachedDocumentsSectionTests(CCOFChecklistBase):
    """Four of the eight checklist items are satisfied by a DOCUMENT. The packet referenced
    `GeneratedDocument` zero times, so a scanned receipt was filed where no certifier looks."""

    def test_empty_shelf_states_what_is_expected(self):
        text = _text(self._service()._build_attached_documents_section())
        self.assertIn("No documents have been uploaded", text)
        self.assertIn("handler", text)

    def test_uploaded_document_is_indexed_with_its_production(self):
        from django.core.files.base import ContentFile

        from documents.services.filing import file_document

        file_document(
            establishment=self.establishment,
            source="upload",
            folder="uploads",
            title="Compost receipt March 2026",
            filename="receipt.pdf",
            content=ContentFile(b"%PDF-1.4 fake").read(),
            history=self.production,
        )
        cells = _table_cells(self._service()._build_attached_documents_section())
        self.assertIn("Compost receipt March 2026", cells)
        self.assertIn("Walnut 2026", cells)

    def test_document_filed_against_one_record_names_that_record(self):
        """Pilot rehearsal 2026-10, finding 4: tracing the May 15 spray to its invoice needs the
        index row to name the RECORD, not only the season."""
        from documents.services.filing import file_document
        from history.models import ChemicalEvent

        spray = ChemicalEvent.objects.create(
            history=self.production,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            name="Entrust SC, codling moth",
            description="",
            date=timezone.now() - timedelta(days=150),
        )
        file_document(
            establishment=self.establishment,
            source="upload",
            folder="activity_attachments",
            title="Supplier invoice ASTRA-INV-2605-01",
            filename="invoice.pdf",
            content=b"%PDF-1.4 fake",
            history=self.production,
            event_type=2,
            event_id=spray.pk,
        )
        cells = _table_cells(self._service()._build_attached_documents_section())
        self.assertIn("Supplier invoice ASTRA-INV-2605-01", cells)
        linked = [c for c in cells if c.startswith("Walnut 2026")]
        self.assertEqual(len(linked), 1, cells)
        self.assertIn("record: Entrust SC, codling moth", linked[0])

    def test_generated_artifacts_are_not_listed(self):
        """A packet listing previous copies of itself is noise, not evidence."""
        from django.core.files.base import ContentFile

        from documents.services.filing import file_document

        file_document(
            establishment=self.establishment,
            source="dossier",
            folder="exports",
            title="Audit dossier 2026-08-16",
            filename="dossier.pdf",
            content=ContentFile(b"%PDF-1.4 fake").read(),
            history=self.production,
        )
        self.assertNotIn(
            "Audit dossier 2026-08-16",
            _table_cells(self._service()._build_attached_documents_section()),
        )


class NewFieldsNeverReachConsumersTests(CCOFChecklistBase):
    """The wire, not the registry.

    Every field this audit added is commercial data: who a farm buys from, what it paid, what
    a packer sent back. The frontend registry deliberately gives none of them a `consumer_card`
    surface — but a registry surface is a RENDERING decision, and the public payload is built
    by a hand-written allow-list in `PublicHistorySerializer.get_events()`. Three consumer
    leaks in this codebase (2026-08-03, -06, -09) all shipped with the display layer correct,
    so this asserts on the serialized bytes an anonymous scanner receives.
    """

    def _public_payload(self):
        from rest_framework.test import APIRequestFactory

        from history.serializers import PublicHistorySerializer

        request = APIRequestFactory().get("/")
        request.user = None
        return PublicHistorySerializer(
            self.production,
            context={"request": request, "force_public_view": True},
        ).data

    def test_amendment_purchase_fields_are_absent(self):
        SoilManagementEvent.objects.create(
            history=self.production,
            date=timezone.now(),
            description="Compost application",
            type="OM",
            amendment_type="compost",
            amendment_supplier_name="Central Valley Compost Supply",
            amendment_purchase_date=timezone.now().date(),
            amendment_purchase_invoice="INV-20614",
            amendment_quantity_purchased=12,
            amendment_quantity_purchased_unit="tons",
            amendment_lot_number="LOT-CVC-8841",
        )
        payload = self._public_payload()
        wire = str(payload)
        for leaked in ("Central Valley Compost Supply", "INV-20614", "LOT-CVC-8841"):
            self.assertNotIn(leaked, wire, f"{leaked!r} reached the anonymous consumer payload")
        for event in payload.get("events") or []:
            for key in (
                "amendment_supplier_name",
                "amendment_purchase_date",
                "amendment_purchase_invoice",
                "amendment_quantity_purchased",
                "amendment_lot_number",
            ):
                self.assertNotIn(key, event, f"{key!r} reached the anonymous consumer payload")

    def test_handler_round_trip_fields_are_absent(self):
        ProductionEvent.objects.create(
            history=self.production,
            date=timezone.now() - timedelta(days=20),
            description="First pick",
            type="HA",
            harvest_destination="handler",
            sent_to_handler_date=(timezone.now() - timedelta(days=18)).date(),
            quantity_sent_to_handler=42000,
            handler_quantity_unit="lbs",
            quantity_returned_from_handler=13400,
            handler_return_unit="lbs",
            handler_document_reference="PACKOUT-2026-114",
        )
        payload = self._public_payload()
        # Assert on KEYS, not on a substring of the whole payload: a bare "42000" matches the
        # timestamp inside the QR filename, which would have made this test pass for the wrong
        # reason on a day the clock cooperated.
        for event in payload.get("events") or []:
            for key in (
                "sent_to_handler_date",
                "quantity_sent_to_handler",
                "quantity_returned_from_handler",
                "handler_quantity_unit",
                "handler_return_unit",
                "handler_document_reference",
            ):
                self.assertNotIn(key, event, f"{key!r} reached the anonymous consumer payload")
        self.assertNotIn("PACKOUT-2026-114", str(payload))

    def test_sale_amount_is_absent(self):
        SalesRecord.objects.create(
            production=self.production,
            sale_date=timezone.now().date(),
            buyer_name="Sunrise Packing",
            quantity=13400,
            quantity_unit="lb",
            sale_amount=48240,
        )
        # Same reason as above: assert on the buyer's name and on the absence of any sales
        # block, not on a bare number that could match a timestamp.
        payload = self._public_payload()
        self.assertNotIn("Sunrise Packing", str(payload))
        self.assertNotIn("sale_amount", str(payload))
        self.assertNotIn("sales_records", payload)
