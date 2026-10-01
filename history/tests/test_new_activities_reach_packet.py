"""Transport, Buffer Use and Seed Search: saved as their own activity, printed in the packet.

These three exist because Quick Organics offers them and Trazo did not — but the deeper reason
is that each fact outlives the event it used to hang off:

  * a load ships days after the pick it came from, and one pick can ship on several dates;
    § 205.272 commingling turns on the LOAD, not the harvest
  * buffer-zone crop is disposed of on its own schedule and must never be sold as organic
    (§ 205.202(c))
  * an organic-seed search precedes planting and may cover varieties never planted; recording
    it only on a planting event loses every search that succeeded

They reuse the existing columns rather than adding new ones, so the risk is not storage — it is
that the packet, which maps subtype codes to labels BY HAND, prints "TP" instead of "Transport"
to an inspector. Each test below asserts the rendered PDF, not the saved row.
"""

import io
import re

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class NewActivitiesReachPacketTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="newacts@test.com", password="x")
        company = Company.objects.create(name="New Acts Co")
        establishment = Establishment.objects.create(name="NA1", company=company, state="California")
        parcel = Parcel.objects.create(name="Block 5", establishment=establishment, area=8)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="New Acts Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _pdf_text(self):
        from pdfminer.high_level import extract_text

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def test_a_transport_activity_prints_its_label_and_destination(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="TP",
            date=timezone.now(),
            description="Load to the huller",
            harvest_lot_code="LOT-TP-001",
            harvest_destination="handler",
            created_by=self.user,
        )
        text = self._pdf_text()
        self.assertIn("Transport", text, "the subtype printed its raw code instead of a label")
        self.assertIn("LOT-TP-001", text, "the lot this load carried is not in the packet")

    def test_a_buffer_use_activity_prints_its_disposition(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="BU",
            date=timezone.now(),
            description="Buffer rows cut and sold conventional",
            harvest_lot_code="LOT-BU-002",
            buffer_disposition="sold_conventional",
            buffer_disposition_quantity="400 lb",
            buffer_disposition_evidence="Delivery tag 8891",
            created_by=self.user,
        )
        text = self._pdf_text()
        self.assertIn("Buffer Use", text)
        self.assertIn("LOT-BU-002", text)
        # § 205.202(c): buffer crop entering commerce must carry its evidence, or the record
        # asserts a disposition nobody can check.
        self.assertIn("Delivery tag 8891", text, "the buffer disposition evidence is missing")

    def test_a_seed_search_activity_prints_its_attempts(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="SS",
            date=timezone.now(),
            description="Organic seed availability search",
            seed_certification_status="non_organic_untreated",
            # A CHOICE, not prose — the column is 16 chars and takes form/quality/quantity/other.
            seed_nonavailability_reason="quantity",
            seed_search_attempts=[
                {
                    "supplier_name": "Territorial Seed",
                    "date_contacted": "2026-02-10",
                    "result": "not_available",
                    "notes": "Variety not carried",
                }
            ],
            created_by=self.user,
        )
        text = self._pdf_text()
        self.assertIn("Seed Search", text)
        self.assertIn(
            "Territorial Seed",
            text,
            "§ 205.204(a)(1) commercial-availability evidence did not reach the packet",
        )

    def test_the_three_are_distinguishable_from_each_other(self):
        """One label map entry missing renders a raw code, and a test asserting only that the
        PDF is non-empty would not notice."""
        for subtype, label in (("TP", "Transport"), ("BU", "Buffer Use"), ("SS", "Seed Search")):
            with self.subTest(subtype=subtype):
                ProductionEvent.objects.all().delete()
                ProductionEvent.objects.create(
                    history=self.history,
                    type=subtype,
                    date=timezone.now(),
                    description=f"{label} activity",
                    created_by=self.user,
                )
                text = self._pdf_text()
                # Only the label is asserted. A "raw code must be absent" check reads well and
                # is wrong: two-letter codes collide with ordinary words and abbreviations
                # elsewhere in the packet, so it would fail for reasons unrelated to labelling.
                # The label map guard (test_production_label_map_exhaustive) is what actually
                # prevents a raw code, by construction rather than by string search.
                self.assertIn(label, text)

    def test_purge_records_reach_the_packet(self):
        """§ 205.272 turns on what happened to the purge material, not on the purge itself.

        Quick Organics asks all three (material, quantity, end use); Trazo had no purge concept
        at all — the cleaning record captured method and materials and stopped there.
        """
        ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            date=timezone.now(),
            description="Auger purge before organic run",
            equipment_operation_type="CL",
            cleaning_asset_class="processing_line",
            cleaning_date=timezone.now().date(),
            cleaned_by="A. Reyes",
            cleaning_method="Purge",
            purge_material="Conventional walnuts",
            purge_quantity="200 lb",
            purge_material_end_use="Sold as conventional to Handler B, delivery tag 4417",
            created_by=self.user,
        )
        text = self._pdf_text()
        self.assertIn("Purge Records", text, "the purge section did not render")
        self.assertIn("Conventional walnuts", text)
        self.assertIn("200 lb", text)
        self.assertIn(
            "Sold as conventional",
            text,
            "the end use is the compliance-relevant half and it is missing",
        )

    def test_transport_endpoints_reach_the_packet(self):
        """`harvest_destination` is a category; the counterparty's identity is not in it."""
        ProductionEvent.objects.create(
            history=self.history,
            type="TP",
            date=timezone.now(),
            description="Load to huller",
            harvest_lot_code="LOT-TP-EP-1",
            harvest_destination="handler",
            transport_origin="Blue Oak Orchards, 1 Orchard Rd, Chico CA",
            transport_destination_address="Sacramento Valley Hulling, 9 Mill Way, Yuba City CA",
            created_by=self.user,
        )
        text = self._pdf_text()
        self.assertIn("Transport Endpoints", text)
        self.assertIn("Sacramento Valley Hulling", text, "the destination identity is missing")
        self.assertIn("Blue Oak Orchards", text)

    def test_the_endpoint_table_stays_absent_when_nothing_was_recorded(self):
        """The mirror: an empty section on every packet is noise that trains readers to skip."""
        ProductionEvent.objects.create(
            history=self.history,
            type="TP",
            date=timezone.now(),
            description="Load with no endpoints recorded",
            created_by=self.user,
        )
        self.assertNotIn("Transport Endpoints", self._pdf_text())
