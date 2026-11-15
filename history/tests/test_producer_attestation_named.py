"""The § 205.401 attestation must name a producer whenever the operation has one.

The attestation page carries "certify under penalty of law" above a signature line. It took
its name from `production.operator` alone, so a season row with a null operator printed
"Producer / Operator: (operator not set)" for a farm with a named producer on file. A
certifier reads an unnamed attestation as an unsigned one.

§ 205.401 and § 205.400(a) attest for the OPERATION, not for one season, so the name may
legitimately come from the establishment's contact or from whoever authored the OSP under
§ 205.201(a). The placeholder is correct only when the operation names nobody at all.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from certifications.models import OrganicSystemPlan
from company.models import Company, Establishment
from history.models import Production
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class ProducerAttestationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="paula@attest.test", password="x", first_name="Paula", last_name="Reyes"
        )
        company = Company.objects.create(name="Attest Farm")
        self.est = Establishment.objects.create(name="A Block", company=company)
        parcel = Parcel.objects.create(name="P1", establishment=self.est, area=1.0)
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-attest",
            category="tree_nut",
            description="n",
            typical_farm_size="10",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Walnuts")
        # A season with NO operator — the shape that produced the bug.
        self.history = Production.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def _attestation_text(self):
        svc = AuditExportService(self.history, certification_type="organic")
        captured = []
        import reportlab.platypus as platypus

        from history.services import audit_export_service as mod

        orig = platypus.Paragraph

        def spy(text, *a, **kw):
            captured.append(str(text))
            return orig(text, *a, **kw)

        platypus.Paragraph = spy
        mod.Paragraph = spy
        try:
            svc._build_producer_attestation_section()
        finally:
            platypus.Paragraph = orig
            mod.Paragraph = orig
        return "\n".join(captured)

    def test_the_osp_author_is_named_when_the_season_has_no_operator(self):
        OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="submitted", created_by=self.user
        )
        text = self._attestation_text()
        self.assertIn("Paula Reyes", text)
        self.assertNotIn("(operator not set)", text)

    def test_the_establishment_contact_wins_over_the_osp_author(self):
        self.est.contact_person = "Marco Delgado"
        self.est.save(update_fields=["contact_person"])
        OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="submitted", created_by=self.user
        )
        self.assertIn("Marco Delgado", self._attestation_text())

    def test_an_operation_naming_nobody_still_says_so(self):
        """The placeholder is right when it is true — it must not be replaced by a guess."""
        text = self._attestation_text()
        self.assertIn("(operator not set)", text)
