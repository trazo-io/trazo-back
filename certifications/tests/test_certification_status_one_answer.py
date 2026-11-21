"""One answer on whether the operation is certified, on every surface (walkthrough 2026-11-20).

W3. A parcel answered "currently certified" (Parcel Application F) on an operation Trazo holds no
certificate for printed three statements with nothing joining them: the parcel page said the
parcel is certified, the packet cover said "No certificate on file ... first application", and the
dossier's Land requirements row said nothing on record evidences the 36-month period. The packet's
parcel page now carries the gap as a review note (so the cover lists it) and the dossier row names
the statement beside the missing certificate.

W4. The OSP page asked the same never-certified operation for the § 205.406(a) annual update while
the packet cover said none applies. The plan list now carries the cover's own test.
"""

import io
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text

from carbon.models import CropType
from certifications.models import Certification, OrganicSystemPlan
from certifications.serializers import OrganicSystemPlanListSerializer
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from history.models import Production
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User

_NOTE = "[REVIEW] The parcel is stated above as currently certified, but no organic certificate"
_PLAIN = "No certificate is on file for this operation in Trazo. The parcel is stated above as"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Operation(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="bench@test.com", password="x")
        company = Company.objects.create(name="Coldwater Bench LLC")
        self.est = Establishment.objects.create(name="Coldwater Bench", company=company, state="WA")
        self.plan = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            created_by=self.user,
            certifier_name="Washington State Department of Agriculture",
        )
        self.parcel = Parcel.objects.create(
            name="Block 1 Gala",
            establishment=self.est,
            area=12.5,
            application_answers={
                "currently_certified": "yes",
                "prior_certifier_name": "Washington State Department of Agriculture",
                "no_lapse_attested": True,
            },
        )

    def _certify(self):
        # A certification row with no certificate number: the cover reads the operation as renewing,
        # and the parcel page's certificate line is still not on file (it needs a number).
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certifier_name="Washington State Department of Agriculture",
            effective_date=date(2020, 1, 1),
        )


class ParcelPageNamesTheMissingCertificateTests(_Operation):
    def _page(self) -> str:
        return _text(generate_module_pdf(self.plan, "parcel_application", parcel=self.parcel))

    def test_a_never_certified_operation_gets_a_review_note_beside_the_statement(self):
        text = self._page()
        self.assertIn("The operation states this parcel is currently certified organic", text)
        self.assertIn(_NOTE, text)
        self.assertIn("Add the certificate to the farm profile, or correct the answer above", text)
        self.assertNotIn(_PLAIN, text)

    def test_an_operation_with_a_certification_on_record_keeps_the_plain_sentence(self):
        """The cover reads that operation as renewing, so there is no first-application reading to
        reconcile; the certificate line is still honest that no numbered certificate is on file."""
        self._certify()
        text = self._page()
        self.assertIn(_PLAIN, text)
        self.assertNotIn(_NOTE, text)

    def test_a_parcel_not_stated_certified_prints_neither(self):
        self.parcel.application_answers = {"currently_certified": "no"}
        self.parcel.save(update_fields=["application_answers"])
        text = self._page()
        self.assertNotIn(_NOTE, text)
        self.assertNotIn(_PLAIN, text)

    def test_the_cover_collects_the_note(self):
        """A note is any [REVIEW] line in a packet document; the cover lists what `collect` finds."""
        from certifications.services.packet_review_notes import collect

        pdf = generate_module_pdf(self.plan, "parcel_application", parcel=self.parcel)
        [doc] = collect([("parcels/parcel-application-Block 1 Gala.pdf", pdf)])
        self.assertTrue(any("stated above as currently certified" in note for note in doc.notes), doc.notes)


class LandRequirementsRowNamesTheStatementTests(_Operation):
    def setUp(self):
        super().setUp()
        crop = CropType.objects.create(
            name="Apples",
            slug="apples-w3",
            category="tree_fruit",
            description="n",
            typical_farm_size="10",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=False,
        )
        self.history = Production.objects.create(
            parcel=self.parcel,
            product=Product.objects.create(name="Apples"),
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def _land_row(self):
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        return next(r for r in rows if r["label"] == "Land requirements (§ 205.202)")

    def test_a_stated_certified_parcel_with_no_certificate_names_both(self):
        row = self._land_row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertIn("Parcel Application F states this parcel is currently certified organic", row["detail"])
        self.assertIn("no organic certificate for this operation is on file in Trazo", row["detail"])
        self.assertNotIn("nothing on record evidences", row["detail"])
        self.assertEqual(row["detail_code"], "land_requirements.stated_certified")

    def test_clean_field_history_does_not_hide_the_missing_certificate(self):
        """Three clean years read INFO on an applicant's parcel. On a parcel stated certified, the
        certificate is what the agent's route asks for, so the row stays a review item."""
        from product.models import ParcelCropHistory

        for yr in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(
                parcel=self.parcel,
                year=yr,
                crop_grown="Apples",
                production_method="organic",
                substances_applied="None prohibited.",
                date_last_prohibited=None,
            )
        row = self._land_row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertEqual(row["detail_code"], "land_requirements.stated_certified")

    def test_a_parcel_not_stated_certified_keeps_the_old_sentence(self):
        self.parcel.application_answers = {"currently_certified": "no"}
        self.parcel.save(update_fields=["application_answers"])
        row = self._land_row()
        self.assertEqual(row["detail_code"], "land_requirements.no_history")
        self.assertIn("nothing on record evidences", row["detail"])

    def test_a_certificate_that_does_not_cover_this_season_is_not_called_missing(self):
        """A certificate reissued after the season began (or lapsed) is on file but covers nothing
        here. Telling that operation to add it to the farm profile would be wrong advice, so the
        row keeps its own sentence (review of back #511)."""
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certifier_name="Washington State Department of Agriculture",
            effective_date=date.today(),
        )
        row = self._land_row()
        self.assertNotEqual(row["detail_code"], "land_requirements.stated_certified")
        self.assertNotIn("add it to the farm profile", row["detail"])

    def test_a_covering_certificate_is_reported_as_before(self):
        self._certify()
        row = self._land_row()
        self.assertEqual(row["status"], "INFO")
        self.assertIn("Organic certification recorded", row["detail"])


class PlanListSaysWhetherAnAnnualUpdateAppliesTests(_Operation):
    def _flags(self):
        plans = OrganicSystemPlan.objects.filter(establishment=self.est).order_by("version_number")
        return [row["never_certified"] for row in OrganicSystemPlanListSerializer(plans, many=True).data]

    def test_a_never_certified_operation_reads_true_on_every_version(self):
        OrganicSystemPlan.objects.create(establishment=self.est, version_number=2, status="draft", created_by=self.user)
        self.assertEqual(self._flags(), [True, True])

    def test_a_certification_on_record_reads_false(self):
        self._certify()
        self.assertEqual(self._flags(), [False])

    def test_an_annual_update_on_record_reads_false(self):
        """The OSP page leaves the annual update card out when this is True, so a farm with a filing
        on record must never read True: the card is where that filing is listed (review of app
        #444)."""
        from certifications.models import OSPAnnualUpdate

        OSPAnnualUpdate.objects.create(prior_osp=self.plan, reporting_year=2026, changes_summary="Hedgerow.")
        self.assertEqual(self._flags(), [False])

    def test_an_approved_version_reads_false(self):
        self.plan.status = "active"
        self.plan.save(update_fields=["status"])
        self.assertEqual(self._flags(), [False])
