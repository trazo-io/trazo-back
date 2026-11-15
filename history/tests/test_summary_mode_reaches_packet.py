"""Summary mode is a record, not a shortcut — and it must reach the certifier.

WHAT WENT WRONG. A grower can log a season of work as ONE event: twelve fertigations, eighteen
scouting passes, four harvest days. The per-event columns are then blank BY DESIGN — the totals
carried in `extra_data` are the record. None of those totals reached the packet for chemical,
pest or production events, so a farm using the feature handed its certifier a product name and
a row of dashes where twelve applications and 480 kg of nitrogen should have been.

WHY IT SURVIVED EVERY OTHER CHECK. Summary handling DID exist — for grazing, in the soil
section. So the feature read as covered, and a structural check ("does this codebase know about
is_summary?") answered yes. The field-coverage sweep flagged the totals as unreferenced, and
they were dismissed as "aggregates, probably intentional". They were not.

The lesson worth keeping: "the feature is handled somewhere" is not evidence that it is handled
where it matters. Each family needed its own check, which is what this file is.
"""

import io
import re

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, PestManagementEvent, Production, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class SummaryModeReachesPacketTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="summary@test.com", password="x")
        company = Company.objects.create(name="Summary Co")
        est = Establishment.objects.create(name="S1", company=company, state="California")
        parcel = Parcel.objects.create(name="Block 1", establishment=est, area=120)
        product = Product.objects.create(name="Walnuts")
        self.history = Production.objects.create(
            name="Summary Production",
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

    def _pdf(self):
        from pdfminer.high_level import extract_text

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def test_a_season_of_applications_reaches_the_certifier(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            date=timezone.now(),
            commercial_name="Compost tea",
            description="Season fertigation summary",
            created_by=self.user,
            extra_data={
                "is_summary": "true",
                "date_start": "2026-03-01",
                "date_end": "2026-08-01",
                "event_count": 12,
                "nitrogen_total_kg": 480,
                "volume_applied_total": "9600 L",
                "area_treated_total": "120 acres",
            },
        )
        t = self._pdf()
        self.assertIn("Summary-Mode Applications", t)
        self.assertIn("Applications: 12", t, "the pass count is the record in summary mode")
        self.assertIn("480", t, "480 kg of nitrogen did not reach the certifier")
        self.assertIn("2026-03-01 to 2026-08-01", t, "the period the summary covers is missing")

    def test_a_season_of_scouting_reaches_the_certifier(self):
        PestManagementEvent.objects.create(
            history=self.history,
            type="SC",
            date=timezone.now(),
            description="Season scouting summary",
            created_by=self.user,
            extra_data={
                "is_summary": "true",
                "event_count": 18,
                "pest_species_observed": "Navel orangeworm, mites",
                "average_pest_pressure": "Low",
            },
        )
        t = self._pdf()
        self.assertIn("Summary-Mode Monitoring", t)
        self.assertIn("Scouting passes: 18", t)
        # § 205.206(a) turns on the monitoring record; species and pressure ARE that record.
        self.assertIn("Navel orangeworm", t)
        self.assertIn("Average pressure: Low", t)

    def test_season_harvest_and_irrigation_totals_reach_the_certifier(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="Season harvest summary",
            created_by=self.user,
            extra_data={"is_summary": "true", "event_count": 4, "yield_total": "88000", "yield_total_unit": "lb"},
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="IR",
            date=timezone.now(),
            description="Season irrigation summary",
            created_by=self.user,
            extra_data={
                "is_summary": "true",
                "event_count": 22,
                "water_volume_total": "640",
                "water_volume_unit": "acre-inches",
            },
        )
        t = self._pdf()
        self.assertIn("Season yield: 88000", t)
        self.assertIn("Water applied: 640", t)

    def test_a_non_summary_event_adds_no_summary_table(self):
        """The mirror. An empty section on every packet trains a reader to skip it."""
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FERTILIZER,
            date=timezone.now(),
            commercial_name="Compost tea",
            description="One ordinary application",
            created_by=self.user,
        )
        t = self._pdf()
        self.assertNotIn("Summary-Mode Applications", t)
