"""
Tests for the California Pesticide Use Report (PUR / DPR-PML-017C) export.

Covers: fertilizer exclusion, DPR box mapping from F20 fields, per-row
completeness flags, month filtering, fumigation FFM requirement, and CSV shape.
"""

from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.pur_export_service import PURExportService
from product.models import Parcel, Product
from users.models import User


class PURExportServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pur@test.com", password="x")
        self.company = Company.objects.create(name="Salinas Citrus Co")
        self.establishment = Establishment.objects.create(
            name="Block 7",
            company=self.company,
            address="123 Grove Rd",
            city="Fresno",
            state="CA",
            zip_code="93701",
        )
        self.parcel = Parcel.objects.create(name="North Orchard", establishment=self.establishment, area=40.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="2026 Oranges",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _full_pesticide(self, **overrides):
        defaults = dict(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            manufacturer="Corteva",
            date=timezone.make_aware(datetime(2026, 6, 15, 7, 0)),
            application_start=timezone.make_aware(datetime(2026, 6, 15, 7, 0)),
            application_end=timezone.make_aware(datetime(2026, 6, 15, 9, 30)),
            volume="12",
            volume_unit="gal",
            area="8",
            area_unit="acres",
            planted_area="40",
            planted_area_unit="acres",
            operator_id="37-1234",
            site_id="0001",
            application_county="Fresno",
            mtrs_section="12",
            mtrs_township="14S",
            mtrs_range="22E",
            mtrs_base_meridian="M",
            epa_registration_number="62719-621",
            application_method_structured="air_blast",
            block_id="B7",
        )
        defaults.update(overrides)
        return ChemicalEvent.objects.create(**defaults)

    def test_excludes_fertilizers(self):
        self._full_pesticide()
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="UN-32",
            date=timezone.make_aware(datetime(2026, 6, 16, 8, 0)),
        )
        rows = PURExportService(self.establishment, 6, 2026).build_rows()
        self.assertEqual(len(rows), 1, "fertilizer must be excluded from the PUR")
        self.assertEqual(rows[0]["product_and_manufacturer"], "Entrust SC / Corteva")

    def test_dpr_box_mapping(self):
        self._full_pesticide()
        row = PURExportService(self.establishment, 6, 2026).build_rows()[0]
        self.assertEqual(row["operator_id"], "37-1234")
        self.assertEqual(row["operator_name"], "Salinas Citrus Co")
        self.assertEqual(row["city"], "Fresno")
        self.assertEqual(row["site_id"], "0001")
        self.assertEqual(row["county"], "Fresno")
        self.assertEqual(row["section"], "12")
        self.assertEqual(row["base_meridian"], "M")
        self.assertEqual(row["commodity"], "Navel Orange")
        self.assertEqual(row["field_location"], "North Orchard")
        self.assertEqual(row["acreage_treated"], "8 acres")
        self.assertEqual(row["planted_area"], "40 acres")
        self.assertEqual(row["total_product_used"], "12 gal")
        self.assertEqual(row["application_method"], "Ground (air-blast)")
        self.assertEqual(row["application_start"], "2026-06-15 0700")
        self.assertEqual(row["application_end"], "2026-06-15 0930")
        self.assertEqual(row["epa_registration_number"], "62719-621")
        self.assertEqual(row["_missing_required"], [], f"unexpected gaps: {row['notes']}")

    def test_completeness_flags_missing(self):
        # Minimal event: only the fields a careless quick-entry would have.
        self._full_pesticide(
            operator_id="",
            site_id="",
            application_county="",
            ca_dpr_permit_county="",
            mtrs_section="",
            mtrs_township="",
            mtrs_range="",
            mtrs_base_meridian="",
            application_start=None,
            application_end=None,
            epa_registration_number="",
            planted_area="",
        )
        row = PURExportService(self.establishment, 6, 2026).build_rows()[0]
        missing = set(row["_missing_required"])
        for key in ("operator_id", "site_id", "county", "section", "application_start", "epa_registration_number"):
            self.assertIn(key, missing, f"{key} should be flagged missing")
        self.assertIn("Missing required", row["notes"])

    def test_month_filter(self):
        self._full_pesticide()  # June
        self._full_pesticide(
            date=timezone.make_aware(datetime(2026, 5, 15, 7, 0)),
            commercial_name="May Spray",
        )
        rows = PURExportService(self.establishment, 6, 2026).build_rows()
        self.assertEqual(len(rows), 1, "only June applications belong in the June PUR")

    def test_fumigation_requires_ffm(self):
        self._full_pesticide(application_method_structured="fumigation", ffm_code="")
        row = PURExportService(self.establishment, 6, 2026).build_rows()[0]
        self.assertEqual(row["application_method"], "Fume")
        self.assertIn("ffm_code", row["_missing_required"])

    def test_csv_structure(self):
        self._full_pesticide()
        csv_bytes = PURExportService(self.establishment, 6, 2026).to_csv().read().decode("utf-8-sig")
        self.assertIn("California Pesticide Use Report (DPR-PML-017C)", csv_bytes)
        self.assertIn("Salinas Citrus Co", csv_bytes)
        self.assertIn("3. Operator ID/Permit No.", csv_bytes)
        self.assertIn("28. Product and Manufacturer", csv_bytes)
        self.assertIn("Entrust SC / Corteva", csv_bytes)

    def test_summary_counts(self):
        self._full_pesticide()  # complete
        self._full_pesticide(operator_id="", site_id="", commercial_name="Sparse")  # incomplete
        summary = PURExportService(self.establishment, 6, 2026).summary()
        self.assertEqual(summary["application_count"], 2)
        self.assertEqual(summary["complete_count"], 1)
        self.assertEqual(summary["incomplete_count"], 1)
        self.assertEqual(summary["filing_deadline"], "2026-07-10")
        self.assertEqual(summary["form"], "DPR-PML-017C")
