"""
A4 — irrigation/well water-quality test (2026-06 NOP-alignment audit).

CCOF requires an annual water-source analysis (7 CFR 205.272 / 205.671). The IR subtype
previously carried only source/method/depth, so a water lab report had nowhere structured
to live and the irrigation export rendered no water-quality record. These tests confirm
the new IR water-test fields reach a certifier Water Quality sub-table, that an irrigation
record with no test fires a REVIEW flag, and that the test never leaks to consumers.
"""

import json

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import Production, ProductionEvent
from history.serializers import PublicHistorySerializer
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _section_text(elements):
    out = []
    for el in elements:
        text = getattr(el, "text", None)
        if text:
            out.append(text)
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                ctext = getattr(cell, "text", None)
                if ctext:
                    out.append(ctext)
    return " ".join(out)


class WaterQualityExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="water@test.com", password="x")
        self.company = Company.objects.create(name="Water Farm")
        self.establishment = Establishment.objects.create(name="WE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="WP", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = Production.objects.create(
            name="Water Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
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

    def _ir(self, **kw):
        return ProductionEvent.objects.create(history=self.history, type="IR", date=timezone.now(), **kw)

    def _text(self):
        svc = AuditExportService(self.history, certification_type="organic")
        return _section_text(svc._build_production_events())

    def test_water_test_renders_in_water_quality_table(self):
        self._ir(
            water_test_date=timezone.now().date(),
            water_test_lab="BlueWater Labs",
            water_test_results=[
                {"parameter": "Nitrate", "value": "2.1", "unit": "mg/L", "result": "Pass"},
                {"parameter": "E. coli", "value": "0", "unit": "CFU/100mL", "result": "Pass"},
            ],
            block_id="Block N",
        )
        text = self._text()
        self.assertIn("Irrigation Water Quality Test", text)
        self.assertIn("BlueWater Labs", text)
        self.assertIn("Nitrate", text)
        self.assertNotIn("[REVIEW]", text)

    def test_one_test_copied_onto_several_records_prints_once_with_its_blocks(self):
        """VID-12 (recordkeeping checklist run 2026-11-16): one water test carried onto three
        irrigation records printed three identical rows."""
        test = dict(
            water_test_date=timezone.now().date(),
            water_test_lab="BlueWater Labs",
            water_test_results=[{"parameter": "Nitrate", "value": "2.1", "unit": "mg/L", "result": "Pass"}],
        )
        self._ir(block_id="Block N", **test)
        self._ir(block_id="Block S", **test)
        self._ir(block_id="Block N", **test)
        text = self._text()
        self.assertEqual(text.count("BlueWater Labs"), 1, text)
        self.assertIn("Block N, Block S", text)
        self.assertNotIn("Block N, Block S, Block N", text)
        # A record of the same test with no block stays visible in the row.
        self._ir(**test)
        self.assertIn("Block N, Block S, not stated", self._text())
        # A second, different test is still its own row.
        self._ir(block_id="Block S", **{**test, "water_test_lab": "Cascade Water Lab"})
        text = self._text()
        self.assertEqual((text.count("BlueWater Labs"), text.count("Cascade Water Lab")), (1, 1))

    def test_two_sources_sampled_the_same_day_at_the_same_lab_stay_two_tests(self):
        test = dict(
            water_test_date=timezone.now().date(),
            water_test_lab="BlueWater Labs",
            water_test_results=[{"parameter": "E. coli", "value": "<1", "unit": "MPN", "result": "Pass"}],
        )
        self._ir(block_id="Block N", water_source="well_groundwater", **test)
        self._ir(block_id="Block S", water_source="irrigation_canal", **test)
        self.assertEqual(self._text().count("BlueWater Labs"), 2)

    def test_irrigation_without_water_test_fires_review(self):
        """The REVIEW still fires — but it must NOT be labelled 7 CFR 205.272.

        This asserted "[REVIEW] 7 CFR 205.272" until 2026-08-18. The service relabelled it
        deliberately, and the new wording says why in the body: water-quality testing is a
        CCOF / FDA FSMA Produce Safety Rule (21 CFR 112) expectation, NOT a Part 205
        requirement. Citing § 205.272 for it told a certifier the NOP requires something it
        does not — the same over-citation the "cite § 205.103, never 'USDA-required forms'"
        rule exists to prevent. § 205.272 remains the correct citation for the transport /
        commingling reviews, which is where the service still uses it.
        """
        self._ir()  # irrigation logged, no water analysis on file
        text = self._text()
        self.assertIn("[REVIEW]", text)
        self.assertIn("21 CFR 112", text)
        self.assertIn("not itself a 7 CFR Part 205 requirement", text)
        self.assertNotIn("[REVIEW] 7 CFR 205.272", text)

    def test_water_test_not_leaked_to_consumer(self):
        self._ir(
            water_test_lab="BlueWater Labs",
            water_test_results=[{"parameter": "Nitrate", "value": "2.1"}],
        )
        data = PublicHistorySerializer(self.history).data
        blob = json.dumps(data, default=str)
        self.assertNotIn("BlueWater Labs", blob, "water test lab leaked to consumer payload")
        for event in data.get("events") or []:
            self.assertNotIn("water_test_lab", event)
            self.assertNotIn("water_test_results", event)
