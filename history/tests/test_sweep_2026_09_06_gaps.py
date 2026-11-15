"""
Gaps found by the 2026-09-06 per-activity end-to-end sweep (one record per wizard tile on the
demo farm, read back through the API, the detail modal, the buyer card and the season audit PDF).
Each test here pins one of the packet/serializer fixes so it cannot silently reopen.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import GeneralEvent, Production, ProductionEvent, SoilManagementEvent
from history.serializers import ProductionEventSerializer, UpdateProductionEventSerializer
from history.services.audit_export_service import AuditExportService
from history.tests.test_pdf_field_coverage import flowable_text
from product.models import Parcel, Product
from users.models import User


class SweepGapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sweep@test.com", password="x")
        company = Company.objects.create(name="Sweep Farm")
        self.establishment = Establishment.objects.create(name="Home", company=company, state="OR")
        self.parcel = Parcel.objects.create(name="Upper Terrace", establishment=self.establishment, area=6.0)
        product = Product.objects.create(name="Onions")
        self.now = timezone.now()
        self.production = Production.objects.create(
            name="Onions 2026",
            start_date=self.now - timedelta(days=120),
            product=product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_a_seed_search_that_ended_in_a_purchase_prints_the_purchase(self):
        """The SS form collects supplier / purchase date / invoice / lot / treatment; the
        traceability table iterated PL rows only, so all five were silently absent."""
        ProductionEvent.objects.create(
            history=self.production,
            type="SS",
            date=self.now - timedelta(days=100),
            description="Organic seed search, three suppliers contacted",
            variety="Walla Walla",
            seeds_source="purchased",
            seed_certification_status="certified_organic",
            seed_supplier_name="High Mowing Organic Seeds",
            seed_purchase_date=(self.now - timedelta(days=99)).date(),
            seed_purchase_invoice="HM-44812",
            seed_lot_number="LOT-WW-26",
            seed_treatment="none",
        )
        text = flowable_text(
            AuditExportService(self.production, certification_type="organic")._build_seed_stock_section()
        )
        for token in ("High Mowing Organic Seeds", "HM-44812", "LOT-WW-26"):
            self.assertIn(token, text)

    def test_the_cleaning_event_a_pass_links_to_is_readable_not_a_bare_id(self):
        cleaning = ProductionEvent.objects.create(
            history=self.production,
            type="EM",
            date=self.now - timedelta(days=3),
            description="Sprayer cleanout",
            name="Sprayer cleanout before organic block",
            equipment_operation_type="CL",
        )
        pass_event = ProductionEvent.objects.create(
            history=self.production,
            type="CU",
            date=self.now - timedelta(days=2),
            description="Cultivation",
            equipment_cleaning_event=cleaning,
        )
        expected = f"{cleaning.date.strftime('%Y-%m-%d')} · Sprayer cleanout before organic block"
        self.assertEqual(ProductionEventSerializer(pass_event).data["equipment_cleaning_event_label"], expected)
        self.assertEqual(UpdateProductionEventSerializer(pass_event).data["equipment_cleaning_event_label"], expected)
        self.assertIsNone(ProductionEventSerializer(cleaning).data["equipment_cleaning_event_label"])

    def test_operation_dossier_signoffs_cover_every_production_named(self):
        """The operation dossier builds the attestation section once, from a service bound to
        one production; `scope_productions` is how it names the rest."""
        other_parcel = Parcel.objects.create(name="River Block", establishment=self.establishment, area=3.0)
        other = Production.objects.create(
            name="Carrots 2026",
            start_date=self.now - timedelta(days=90),
            product=Product.objects.create(name="Carrots"),
            parcel=other_parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        ProductionEvent.objects.create(
            history=self.production,
            type="IR",
            date=self.now - timedelta(days=5),
            description="Drip set",
            reviewed=True,
            reviewer_name="Laurel Brandt",
            review_date=self.now.date(),
        )
        ProductionEvent.objects.create(
            history=other,
            type="CU",
            date=self.now - timedelta(days=4),
            description="Cultivation pass",
            reviewed=True,
            reviewer_name="Sam Okafor",
            review_date=self.now.date(),
        )
        svc = AuditExportService(self.production, certification_type="organic")
        alone = flowable_text(svc._build_supervisor_signoff_subtable())
        self.assertIn("Laurel Brandt", alone)
        self.assertNotIn("Sam Okafor", alone, "a season export prints its own sign-offs only")

        svc.scope_productions = [self.production, other]
        both = flowable_text(svc._build_supervisor_signoff_subtable())
        self.assertIn("Laurel Brandt", both)
        self.assertIn("Sam Okafor", both)
        self.assertIn("Carrots 2026", both, "with several productions the row says which season it belongs to")

    def test_operation_dossier_contamination_incidents_cover_every_production_named(self):
        other_parcel = Parcel.objects.create(name="River Block", establishment=self.establishment, area=3.0)
        other = Production.objects.create(
            name="Carrots 2026",
            start_date=self.now - timedelta(days=90),
            product=Product.objects.create(name="Carrots"),
            parcel=other_parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            lot_id="CAR-26-RB",
        )
        GeneralEvent.objects.create(
            history=other,
            date=self.now - timedelta(days=20),
            description="Drift from the neighbour's aerial pass",
            activity_type="maintenance",
            is_contamination_incident=True,
            contamination_source="spray_drift",
            corrective_action_taken="Flagged rows 1-4, notified certifier",
        )
        svc = AuditExportService(self.production, certification_type="organic")
        alone = flowable_text(svc._build_soe_compliance_section())
        self.assertNotIn("Flagged rows 1-4", alone)
        svc.scope_productions = [self.production, other]
        both = flowable_text(svc._build_soe_compliance_section())
        self.assertIn("Flagged rows 1-4", both, "an incident on another season must reach the operation dossier")
        self.assertIn("CAR-26-RB", both, "lot status is reported across the scope, not for one season")

    def test_soil_amendment_row_names_its_block(self):
        SoilManagementEvent.objects.create(
            history=self.production,
            type="OM",
            date=self.now - timedelta(days=10),
            description="Compost spread",
            amendment_type="compost",
            area_covered=2.5,
            area_unit="acres",
            block_id="UT-7",
        )
        text = flowable_text(AuditExportService(self.production, certification_type="organic")._build_soil_section())
        self.assertIn("Blk UT-7", text)

    def test_transport_prints_its_work_order(self):
        ProductionEvent.objects.create(
            history=self.production,
            type="TP",
            date=self.now - timedelta(days=2),
            description="Load to cold storage",
            transport_origin="Upper Terrace",
            transport_destination_address="Marion Bend Fruit Co., Salem",
            harvest_contract_number="WO-2026-118",
        )
        text = flowable_text(
            AuditExportService(self.production, certification_type="organic")._build_production_events()
        )
        self.assertIn("WO-2026-118", text)
