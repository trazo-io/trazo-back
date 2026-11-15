"""A basis recorded as "not yet confirmed" is an answer, never a gap (recordkeeping review S4).

F-08 (2026-10-07): the grower's "Not yet confirmed" pick (R8-08, kept as an open item) was
classed with blanks, so the save nudge, the certifier page and the dossier called it missing,
and ONE such input turned a certified parcel's § 205.202(b) line into "Not established: input
status not recorded … no start date can be fixed". F-13: a cleanout tile landed on an Equipment
Maintenance record and the certifier's cleaning log read "Equipment Maintenance".

Each test here went red on the code before the fix, on an assertion.
"""

from datetime import date, timedelta

from django.utils import timezone

from rest_framework.test import APITestCase

from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, ProductionEvent
from product.models import Parcel, ParcelCropHistory, Product
from product.services import input_evidence
from product.services.input_evidence import UNKNOWN, classify

# Read lazily so the red check on the old module fails on the assertion, not on the import.
NOT_CONFIRMED = getattr(input_evidence, "NOT_CONFIRMED", "not_confirmed")
from product.services.transition_status_service import compute_transition_status, transition_verdict
from users.models import User, WorksIn


class UnconfirmedIsAnAnswerTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="unconfirmed@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Answer Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Answer Farm", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Home Field East", establishment=self.est, area=5.0)
        self.product = Product.objects.create(name="Blueberries")
        self.history = Production.objects.create(
            name="Duke 2026",
            start_date=timezone.now() - timedelta(days=120),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=False,
        )

    def _chem(self, organic_approved, name="Rex Lime Sulfur", days_ago=30):
        return ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now() - timedelta(days=days_ago),
            description="dormant spray",
            commercial_name=name,
            organic_approved=organic_approved,
            created_by=self.user,
            type="FU",
        )

    def test_not_yet_confirmed_is_its_own_class_and_blank_is_still_unknown(self):
        self.assertEqual(classify("unverified"), NOT_CONFIRMED)
        self.assertEqual(classify(""), UNKNOWN)
        self.assertEqual(classify(None), UNKNOWN)

    def test_one_unconfirmed_input_never_unsets_a_certified_parcels_date(self):
        # Last prohibited application 40 months ago: the clock has run, the date is fixed.
        last = date.today() - timedelta(days=40 * 30)
        ParcelCropHistory.objects.create(
            parcel=self.parcel, year=last.year, crop_grown="Blueberries", date_last_prohibited=last
        )
        self._chem("unverified")
        status = compute_transition_status(self.parcel)
        self.assertEqual(status.unclassified, [])
        self.assertEqual(len(status.unconfirmed), 1)
        self.assertTrue(status.is_eligible)
        self.assertIsNotNone(status.transition_complete_date)
        self.assertEqual(status.last_prohibited_date, last)
        self.assertIn("not yet confirmed", status.note)
        self.assertIn("Rex Lime Sulfur", status.note)
        verdict = transition_verdict(status, has_field_history=True)
        self.assertNotIn("Not established", verdict)
        self.assertNotIn("no start date can be fixed", verdict)
        self.assertIn("basis recorded as not yet confirmed", verdict)
        self.assertIn("Rex Lime Sulfur", verdict)
        self.assertEqual(len(status.to_dict()["unconfirmed"]), 1)

    def test_a_blank_still_blocks_a_clean_statement(self):
        self._chem("")
        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible)
        self.assertEqual(len(status.unclassified), 1)
        self.assertEqual(status.unconfirmed, [])

    def test_the_certified_branch_names_the_unconfirmed_input_as_such(self):
        from certifications.services.certified_parcel_branch import _review

        self._chem("unverified")
        kinds = {item.kind: item for item in _review(self.parcel, date.today())}
        self.assertIn("unconfirmed_input", kinds)
        self.assertNotIn("unknown_input", kinds)
        self.assertIn("not yet confirmed", kinds["unconfirmed_input"].text)
        self.assertNotIn("not recorded", kinds["unconfirmed_input"].text)

    def test_the_completeness_row_says_not_yet_confirmed_not_missing(self):
        from history.services.audit_export_service import AuditExportService
        from history.services.record_completeness import missing_required_fields

        event = self._chem("unverified")
        ChemicalEvent.objects.filter(pk=event.pk).update(volume=2.0, area=1.0, target_pest_disease="mildew")
        event.refresh_from_db()
        labels = [m["label"] for m in missing_required_fields(event)]
        self.assertEqual(labels, ["organic basis not yet confirmed"])
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        row = next(r for r in rows if r["label"].startswith("Record completeness — chemical"))
        self.assertEqual(row["status"], "REVIEW")
        self.assertIn("not yet confirmed", row["detail"])
        self.assertNotIn("missing", row["detail"].lower())
        # Beside a genuine gap, the unconfirmed basis is stated apart, never among the missing.
        self._chem("omri_listed", name="Entrust SC")  # no amount, area or target pest
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        row = next(r for r in rows if r["label"].startswith("Record completeness — chemical"))
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("1/2 chemical records missing required fields", row["detail"])
        self.assertNotIn("organic basis not yet confirmed (", row["detail"])
        self.assertIn("; 1 carry an organic basis not yet confirmed", row["detail"])

    def test_a_cleanout_prints_as_a_cleaning_in_the_tables(self):
        from history.services.audit_export_service import production_type_display

        cleanout = ProductionEvent.objects.create(
            history=self.history,
            type="EM",
            equipment_operation_type="CL",
            date=timezone.now() - timedelta(days=3),
            created_by=self.user,
            description="Sprayer tank and lines flushed",
        )
        self.assertEqual(production_type_display(cleanout), "Equipment Maintenance — Cleaning")
        repair = ProductionEvent.objects.create(
            history=self.history, type="EM", date=timezone.now(), created_by=self.user, description="belt"
        )
        self.assertEqual(production_type_display(repair), "Equipment Maintenance")
        # Review of back #134: the CSV export is a parallel surface and must agree.
        from history.services.audit_export_service import AuditExportService

        csv_out = AuditExportService(self.history, certification_type="organic").generate_csv()
        csv_text = csv_out.getvalue() if hasattr(csv_out, "getvalue") else csv_out
        if isinstance(csv_text, bytes):
            csv_text = csv_text.decode("utf-8")
        self.assertIn("Equipment Maintenance — Cleaning", csv_text)
