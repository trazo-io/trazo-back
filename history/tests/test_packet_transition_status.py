"""§ 205.202(b) transition status may not assert a state Trazo cannot evidence.

`compute_transition_status` returns is_eligible=False for two very different reasons:

  a) a prohibited substance IS on record — there is a real clock, with a real start date and
     a real completion date; "In transition — N days remaining" is the correct sentence.
  b) nothing prohibited is on record, but an application exists whose organic status was
     never classified — so no start date can be fixed and there is no clock at all.

Until 2026-08-19 both fell into the same branch, and (b) printed
"In transition — 0 days remaining (eligible None)": a raw Python None in a certifier
document, attached to the unfavourable regulatory verdict, on a farm that had been certified
organic for decades. Trazo reports what its records show; § 205.202(b) is the certifying
agent's determination.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel, Product
from users.models import User


class PacketTransitionStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="transition@test.com", password="x")
        company = Company.objects.create(name="Transition Farm")
        self.est = Establishment.objects.create(name="T Block", company=company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.est, area=1.0)
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-transition",
            category="tree_nut",
            description="Tree nut",
            typical_farm_size="10-40 ha",
            growing_season="Feb-Oct",
            harvest_season="Sep-Oct",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnuts")
        self.history = Production.objects.create(
            parcel=self.parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def _cells(self):
        from history.services import audit_export_service as svc

        captured = []
        original = svc.AuditExportService._label_value

        def spy(self, label, value, *args, **kwargs):
            captured.append(f"{label}: {value}")
            return original(self, label, value, *args, **kwargs)

        svc.AuditExportService._label_value = spy
        try:
            svc.AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        finally:
            svc.AuditExportService._label_value = original
        return captured

    def test_unclassified_input_does_not_print_a_transition_countdown(self):
        """The parcel has an input of unknown status and nothing prohibited on record."""
        ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now() - timedelta(days=120),
            description="input of unrecorded status",
            commercial_name="Some Input",
            type="FU",
            created_by=self.user,
        )

        lines = [line for line in self._cells() if line.startswith("Organic Transition Status")]
        self.assertTrue(lines, "transition status row is missing from the packet")
        status = lines[0]

        self.assertNotIn("None", status, f"raw None reached the certifier document: {status!r}")
        self.assertNotIn(
            "In transition",
            status,
            "with no prohibited-substance date on record there is no clock to count down; " f"got {status!r}",
        )
        self.assertIn("Not established", status)
        self.assertIn("205.202(b)", status)
