"""Packet sentences state what a record shows, never more.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10 (documentation/audits/OSP-ALIGNMENT-2026-10/LEDGER.md):

  T21  A parcel printed "Eligible" beside "none recorded" and an unanswered land declaration; a
       "yes" to currently_certified was rewritten into a sentence about prohibited inputs the
       operator never declared.
  T22  The trace exhibit said the gap between harvest and pack-out "is the handler's culls and
       shrink". No cull or loss record exists anywhere in the data model.
  T25  Every OSP version, drafts included, was titled "Submission Snapshot".
  cite 205.103(b)(3) was cited for five-year retention. Retention is (b)(4); (b)(3) is the audit
       trail and the labeling category (eCFR, read 2026-09-30).
"""

import re
from datetime import date, timedelta
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from carbon.models import CropType
from certifications.models import OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.osp_pdf_snapshot import generate_osp_snapshot_pdf, snapshot_title
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, ParcelCropHistory, Product
from product.services.transition_status_service import operator_statement_lines
from users.models import User

from .test_renewal_packet_contents import _pdf_text


def _parcel(**answers):
    parcel = Parcel(name="North Block", area=2.0, application_answers=answers)
    parcel.date_began_managing = date(2021, 3, 1)
    return parcel


class OperatorStatementTests(SimpleTestCase):
    def test_a_declaration_made_is_stated_as_the_operators(self):
        lines = operator_statement_lines(_parcel(currently_certified="no", dlpm_none_within_tenure=True))
        self.assertIn("The operator declares no prohibited material has been applied since 2021-03-01.", lines)

    def test_a_negative_declaration_is_stated_and_not_turned_into_a_clean_one(self):
        lines = " ".join(operator_statement_lines(_parcel(currently_certified="no", dlpm_none_within_tenure=False)))
        self.assertIn("The operator answered No: a prohibited material may have been applied since 2021-03-01", lines)
        self.assertNotIn("declares no prohibited", lines)

    def test_a_missing_declaration_is_stated_as_missing(self):
        lines = " ".join(operator_statement_lines(_parcel(currently_certified="previously")))
        self.assertIn("has not declared whether a prohibited material was applied", lines)
        self.assertNotIn("declares no prohibited", lines)

    def test_certification_status_never_implies_the_declaration(self):
        """The declaration is not asked of a currently certified parcel (its visible_when). Saying
        so is true; inferring "none applied" from the certificate is not."""
        lines = " ".join(operator_statement_lines(_parcel(currently_certified="yes")))
        self.assertIn("The operation states this parcel is currently certified organic", lines)
        self.assertIn("not asked", lines)
        self.assertNotIn("declares no prohibited", lines)
        self.assertNotIn("none", lines.lower().replace("not asked", ""))

    def test_an_unstated_certification_status_is_said_to_be_unstated(self):
        lines = " ".join(operator_statement_lines(_parcel()))
        self.assertIn("has not stated this parcel's certification status", lines)

    def test_answers_stored_in_the_envelope_shape_read_the_same(self):
        parcel = _parcel(
            currently_certified={"value": "no", "at": "2026-09-30T00:00:00Z"},
            dlpm_none_within_tenure={"value": False, "at": "2026-09-30T00:00:00Z"},
        )
        self.assertIn("answered No", " ".join(operator_statement_lines(parcel)))


class ParcelPageTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Wording Co")
        self.est = Establishment.objects.create(name="Wording Farm", company=company, state="WA")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=2.0)
        for year in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(
                parcel=self.parcel, year=year, crop_grown="Apples", production_method="organic"
            )
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def _page(self):
        return _pdf_text(generate_module_pdf(self.osp, "parcel_application", parcel=self.parcel))

    def test_three_clean_years_and_no_declaration_print_no_eligibility(self):
        text = self._page()
        self.assertNotIn("Eligible", text)
        self.assertIn("No prohibited substance on record in Trazo", text)
        self.assertIn("has not declared whether a prohibited material was applied", text)

    def test_a_negative_declaration_reaches_the_page(self):
        self.parcel.application_answers = {"currently_certified": "no", "dlpm_none_within_tenure": False}
        self.parcel.save(update_fields=["application_answers"])
        text = self._page()
        self.assertIn("The operator answered No", text)
        self.assertNotIn("Eligible", text)


class AuditExportTransitionTests(TestCase):
    """The per-production audit export prints the same lines as the packet (sibling surface)."""

    def setUp(self):
        self.user = User.objects.create_user(email="wording@test.com", password="x")
        company = Company.objects.create(name="Export Farm")
        est = Establishment.objects.create(name="E Block", company=company)
        self.parcel = Parcel.objects.create(name="P1", establishment=est, area=1.0)
        for year in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(
                parcel=self.parcel, year=year, crop_grown="Walnuts", production_method="organic"
            )
        crop = CropType.objects.create(
            name="Walnuts",
            slug="walnuts-wording",
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
        self.history = History.objects.create(
            parcel=self.parcel,
            product=Product.objects.create(name="Walnuts"),
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )

    def test_the_export_states_the_record_and_the_missing_declaration(self):
        from history.services import audit_export_service as svc

        captured = []
        label_value, body = svc.AuditExportService._label_value, svc.AuditExportService._body

        def spy_label(self, label, value, *args, **kwargs):
            captured.append(f"{label}: {value}")
            return label_value(self, label, value, *args, **kwargs)

        def spy_body(self, text, *args, **kwargs):
            captured.append(str(text))
            return body(self, text, *args, **kwargs)

        svc.AuditExportService._label_value, svc.AuditExportService._body = spy_label, spy_body
        try:
            svc.AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        finally:
            svc.AuditExportService._label_value, svc.AuditExportService._body = label_value, body

        status = next(line for line in captured if line.startswith("Organic Transition Status"))
        self.assertNotIn("Eligible", status)
        self.assertIn("No prohibited substance on record in Trazo", status)
        self.assertTrue(any("has not declared whether a prohibited material" in line for line in captured))


class SnapshotTitleTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Title Co")
        self.est = Establishment.objects.create(name="Title Farm", company=company)

    def _osp(self, status, submitted_at=None, version=1):
        return OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=version, status=status, submitted_at=submitted_at
        )

    def test_only_a_submitted_plan_with_a_submission_time_is_a_submission(self):
        now = timezone.now()
        cases = [
            ("draft", None, "Draft, not submitted"),
            ("withdrawn", now, "Withdrawn, not in effect"),
            ("submitted", None, "Organic System Plan"),
            ("active", None, "Organic System Plan"),
            ("submitted", now, "Submission Snapshot"),
            ("active", now, "Submission Snapshot"),
            ("superseded", now, "Submission Snapshot"),
        ]
        for version, (status, submitted_at, expected) in enumerate(cases, start=1):
            with self.subTest(status=status, submitted=bool(submitted_at)):
                osp = self._osp(status, submitted_at, version=version)
                title = snapshot_title(osp)
                self.assertIn(expected, title)
                if expected != "Submission Snapshot":
                    self.assertNotIn("Submission", title)

    def test_the_rendered_draft_page_does_not_call_itself_a_submission(self):
        text = _pdf_text(generate_osp_snapshot_pdf(self._osp("draft")))
        self.assertIn("Draft, not submitted", text)
        self.assertNotIn("Submission Snapshot", text)


class RetentionCiteTests(SimpleTestCase):
    """Five-year retention is 7 CFR 205.103(b)(4). (b)(3) is audit trail + labeling category, and
    stays correct wherever it is cited for that."""

    RETENTION = re.compile(r"(5|five)[ -]year|retention|retain|keep[^.]{0,40}years", re.IGNORECASE)

    def test_no_backend_source_cites_b3_for_retention(self):
        root = Path(__file__).resolve().parents[2]
        wrong = []
        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if {".venv", "migrations", "tests", ".claude", "node_modules"} & parts:
                continue
            text = path.read_text(errors="ignore")
            for match in re.finditer(r"205\.103\(b\)\(3\)", text):
                window = text[max(0, match.start() - 120) : match.end() + 120]
                if self.RETENTION.search(window):
                    line = text.count("\n", 0, match.start()) + 1
                    wrong.append(f"{path.relative_to(root)}:{line}")
        self.assertEqual(wrong, [], "205.103(b)(3) cited for record retention; retention is (b)(4)")
