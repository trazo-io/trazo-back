"""The packet may only claim "USDA OID verified" when a database match substantiates it.

`Certification.consumer_display_status` already closed this hole on the public QR page: a row
marked verified by a manual edit, an import or a fixture was asserting a database match that
never happened, so the consumer claim was gated on
`verification_source == "usda_organic_integrity_db"` (16 CFR 260.6).

The Land requirements (§ 205.202) snapshot row was still taking `verification_status` at face
value, and its PASS text reads "(USDA OID verified)" — in the document that goes to a
certifier. A self-reported certificate must stay REVIEW no matter how the flag was set.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from certifications.models import Certification
from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class LandRequirementsVerificationSourceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="land@test.com", password="x")
        company = Company.objects.create(name="Land Farm")
        self.est = Establishment.objects.create(name="L Block", company=company)
        parcel = Parcel.objects.create(name="P1", establishment=self.est, area=1.0)
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-land",
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
        self.history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def _make_cert(self, **kwargs):
        defaults = dict(
            establishment=self.est,
            certification_type="usda_organic",
            effective_date=date(2020, 1, 1),
            verification_status="verified",
        )
        defaults.update(kwargs)
        return Certification.objects.create(**defaults)

    def _land_row(self):
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        return next(r for r in rows if r["label"] == "Land requirements (§ 205.202)")

    def test_verified_without_a_database_source_does_not_claim_oid_verification(self):
        self._make_cert(verification_source="")
        row = self._land_row()
        self.assertNotIn(
            "USDA OID verified",
            row["detail"],
            "a flag set by hand, an import or a fixture must not assert a database match",
        )
        self.assertNotEqual(row["status"], "PASS")

    def test_a_real_database_match_does_pass(self):
        self._make_cert(verification_source=Certification.DATABASE_VERIFICATION_SOURCE)
        row = self._land_row()
        self.assertEqual(row["status"], "PASS")
        self.assertIn("USDA OID verified", row["detail"])

    def test_field_history_is_reported_when_there_is_no_certificate_yet(self):
        """A first-year applicant HAS the § 205.202 evidence — USDA's own instrument for this
        rule is the Field History / Previous Land Use Record, filed to "determine eligibility
        for organic certification", i.e. before any certificate exists. Reporting only the
        missing certificate tells that grower what they lack and never what they hold."""
        from product.models import ParcelCropHistory

        parcel = self.history.parcel
        for yr in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(
                parcel=parcel,
                year=yr,
                crop_grown="Walnuts",
                production_method="organic",
                substances_applied="None prohibited.",
                date_last_prohibited=None,
            )

        row = self._land_row()
        self.assertEqual(
            row["status"],
            "INFO",
            "complete field history with nothing prohibited is the § 205.202 evidence USDA's "
            "own form asks for — there is nothing for the grower to fix, so it must not sit "
            "on the readiness card as an action",
        )
        self.assertIn("field history on file", row["detail"])
        self.assertIn("205.202(b)", row["detail"])
        self.assertNotIn(
            "No active organic certification",
            row["detail"],
            "the row should name the evidence held, not only the certificate absent",
        )

    def test_without_history_or_certificate_the_row_still_says_what_is_missing(self):
        """The one case that IS a real gap: nothing on record evidences § 205.202 at all."""
        row = self._land_row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertIn("nothing on record evidences", row["detail"])

    def test_a_recorded_certificate_is_reported_not_flagged(self):
        """A certified farm's § 205.202 position was settled by the agent that issued the
        certificate. An applicant cannot have one at all. Amber in either case is cry-wolf."""
        from company.views import ACTIONABLE_READINESS_STATUSES

        self._make_cert(verification_source="")
        row = self._land_row()
        self.assertEqual(row["status"], "INFO")
        self.assertNotIn(row["status"], ACTIONABLE_READINESS_STATUSES)
        self.assertIn("certifying agent", row["detail"])

    def test_an_unclassified_input_is_still_actionable(self):
        """Classifying an input IS something the grower can do, so it stays REVIEW."""
        from history.models import ChemicalEvent
        from product.models import ParcelCropHistory

        parcel = self.history.parcel
        for yr in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(
                parcel=parcel,
                year=yr,
                crop_grown="Walnuts",
                production_method="organic",
                substances_applied="None prohibited.",
                date_last_prohibited=None,
            )
        ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now() - timedelta(days=100),
            description="unclassified input",
            commercial_name="Some Input",
            type="FU",
            created_by=self.user,
        )
        row = self._land_row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertIn("no organic status recorded", row["detail"])
