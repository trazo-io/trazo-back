"""A farmer-typed certification row may not print as Trazo's verdict.

The Inspection & Compliance Event History table is built from BusinessEvent rows, which the
operator fills in themselves — certifier name, certificate number and verification_status are
all free choices in the form. On 2026-08-19 a dress-rehearsal packet printed a bare
"Verified" in the Status column, immediately above the section's own note that these events
"are self-reported by the farmer ... and are not independently verified by Trazo".

That matters more than an ordinary copy slip because of where the artifact goes: the dossier
is what a grower hands their certifier, and the buyer-documentation request sends the same
records to a buyer. "Verified" with no qualifier is the self-reported trust signal that FTC
16 CFR 260.6 and EU ECGT 2024/825 both reach.

Establishment-level verification (the USDA Organic Integrity Database cross-reference) is
reported in the Active Certification Summary. That section is entitled to say a claim was
checked; this one is not.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import BusinessEvent, History
from product.models import Parcel, Product
from users.models import User


class PacketSelfReportedStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pilot-status@test.com", password="x")
        company = Company.objects.create(name="Status Farm")
        est = Establishment.objects.create(name="Status Block", company=company)
        parcel = Parcel.objects.create(name="P1", establishment=est, area=1.0)
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-status",
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
        self.history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )
        self.est = est

    def _render_text(self):
        from history.services.audit_export_service import AuditExportService

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return buf.getvalue() if hasattr(buf, "getvalue") else buf

    def test_a_self_reported_verified_row_is_qualified_in_the_packet(self):
        BusinessEvent.objects.create(
            history=self.history,
            date=timezone.now() - timedelta(days=20),
            description="cert",
            name="Certificate renewed",
            business_type="certification",
            certification_type="organic_usda",
            verified_certifier_name="Some Certifier",
            certificate_number="X-1",
            verification_status="verified",
            created_by=self.user,
        )

        from history.services import audit_export_service as svc

        captured = []
        original_cell = svc.AuditExportService._cell

        def spy(self, value, *args, **kwargs):
            captured.append(value)
            return original_cell(self, value, *args, **kwargs)

        svc.AuditExportService._cell = spy
        try:
            self._render_text()
        finally:
            svc.AuditExportService._cell = original_cell

        texts = [str(c) for c in captured if c is not None]
        self.assertIn(
            "Verified (self-reported)",
            texts,
            "the farmer-entered verification status should be qualified in the packet",
        )
        self.assertNotIn(
            "Verified",
            texts,
            "a bare 'Verified' cell reads as Trazo's verdict on a row the farmer typed",
        )
