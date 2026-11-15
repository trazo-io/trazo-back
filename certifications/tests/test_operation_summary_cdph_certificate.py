"""The Operation module's last open asks: a business summary, the CDPH registration, and the filing agency's
certificate (2026-11-15).

CCOF's Certification Contract (V2, R6, 09/29/2026) asks a summary of the organic business or its plans (B1) and,
beside the CDFA number, a CDPH organic registration number for processing (E2), adding that an operation holds one
number. OTCO's O1 (rev. 2026/10/02) asks the same CDPH number (E-2) and, of a currently certified operation, its most
recent certificate attached (D-1). Every new question is optional.
"""

import io
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan, StateOrganicRegistration
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import progress, visible_questions
from certifications.serializers import StateOrganicRegistrationSerializer
from certifications.services.osp_module_pdf import _packet_cover_pdf, generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from documents.models import GeneratedDocument

MODULE = MODULES_BY_KEY["certification_contract"]
OTCO = "Oregon Tilth Certified Organic (OTCO)"
CCOF = "California Certified Organic Farmers (CCOF)"
NEW_KEYS = ("organic_business_summary", "history_certified_by_this_agency", "history_this_agency_certificate_upload")
SUMMARY = "Forty acres of certified organic walnuts in Butte County, sold in-shell to one huller."
CDFA = "California organic registration (CDFA):"
CDPH = "California organic registration (CDPH):"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _visible(answers) -> set:
    return {q.key for _page, q in visible_questions(MODULE, answers)}


class _Farm(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Valley Walnuts LLC")
        self.est = Establishment.objects.create(name="Valley Walnuts", company=company, state="CA")

    def plan(self, answers, certifier=OTCO):
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={
                "schema_version": 1,
                "modules": {
                    "certification_contract": {
                        "answers": {key: {"value": value} for key, value in answers.items()},
                        "definition_version": "2026.12.11",
                    }
                },
            },
        )
        return self.osp

    def upload(self, question_key):
        GeneratedDocument.objects.create(
            establishment=self.est,
            folder="uploads",
            source="upload",
            title=question_key,
            file=SimpleUploadedFile("file.pdf", b"%PDF-1.4 file"),
            requirement=f"certification_contract.{question_key}",
        )

    def row(self, agent, stem, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if f.path.stem == stem)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)

    def register(self, **kw):
        fields = dict(
            establishment=self.est,
            state="CA",
            status="registered",
            registration_number="12-123456",
            county="Butte",
            registration_date=date.today() - timedelta(days=30),
            renewal_date=date.today() + timedelta(days=300),
        )
        fields.update(kw)
        return StateOrganicRegistration.objects.create(**fields)

    def cover(self):
        return _text(_packet_cover_pdf(self.osp))


class EveryNewQuestionIsOptional(TestCase):
    def test_a_completed_profile_stays_complete(self):
        questions = {q.key: q for page in MODULE.pages for q in page.questions}
        for key in NEW_KEYS:
            with self.subTest(question=key):
                self.assertFalse(questions[key].required)
        answers = {"contract_notes": "Valley Walnuts LLC", "contract_scopes": ["crops"]}
        self.assertEqual(progress(MODULE, answers)["missing"], [])


class TheCertificateGates(TestCase):
    def test_the_filing_agency_question_follows_ever_certified(self):
        self.assertNotIn("history_certified_by_this_agency", _visible({"history_ever_certified": False}))
        self.assertIn("history_certified_by_this_agency", _visible({"history_ever_certified": True}))

    def test_the_certificate_shows_on_the_yes(self):
        shown = {"history_ever_certified": True}
        self.assertNotIn("history_this_agency_certificate_upload", _visible(shown))
        self.assertNotIn(
            "history_this_agency_certificate_upload", _visible({**shown, "history_certified_by_this_agency": False})
        )
        self.assertIn(
            "history_this_agency_certificate_upload", _visible({**shown, "history_certified_by_this_agency": True})
        )


class TheSummaryPrints(_Farm):
    def test_the_module_pdf_prints_the_summary(self):
        text = _text(generate_module_pdf(self.plan({"organic_business_summary": SUMMARY}), "certification_contract"))
        self.assertIn("Describe your organic business in a few sentences, and any plans to change it.", text)
        self.assertIn(SUMMARY, text)


class TheRegisterReadsThem(_Farm):
    def test_ccof_b1_reads_the_summary_and_not_the_naming_notes(self):
        self.plan({"contract_notes": "Valley Walnuts LLC, trading as Valley Walnuts."}, certifier=CCOF)
        self.assertTrue(self.row("ccof", "Certification-Contract", "B1").is_open)
        self.plan({"organic_business_summary": SUMMARY}, certifier=CCOF)
        self.assertEqual(self.row("ccof", "Certification-Contract", "B1").state, "answered")

    def test_a_renewal_needs_its_certificate_attached(self):
        self.plan(
            {
                "history_ever_certified": True,
                "history_certified_by_this_agency": True,
                "history_certified_elsewhere_now": False,
            }
        )
        self.assertEqual(
            self.row("otco", "O1-operation-information", "D-1 (certificate attachment)").state, "attachment_missing"
        )
        self.upload("history_this_agency_certificate_upload")
        self.assertEqual(self.row("otco", "O1-operation-information", "D-1 (certificate attachment)").state, "answered")

    def test_not_certified_today_needs_no_certificate(self):
        self.plan(
            {
                "history_ever_certified": True,
                "history_certified_by_this_agency": False,
                "history_certified_elsewhere_now": False,
            }
        )
        self.assertEqual(self.row("otco", "O1-operation-information", "D-1 (certificate attachment)").state, "answered")

    def test_the_question_unanswered_leaves_d1_open(self):
        self.plan({"history_ever_certified": True, "history_certified_elsewhere_now": False})
        self.assertTrue(self.row("otco", "O1-operation-information", "D-1 (certificate attachment)").is_open)


class TheCoverNamesTheAgency(_Farm):
    def setUp(self):
        super().setUp()
        self.plan({})

    def test_a_cdph_registration_prints_under_cdph(self):
        self.register(registering_agency="cdph", registration_number="12345", county="")
        text = self.cover()
        self.assertIn(f"{CDPH} 12345", text)
        self.assertNotIn(CDFA, text)

    def test_both_agencies_on_file_print_both(self):
        self.register()
        self.register(registering_agency="cdph", registration_number="12345", county="")
        text = self.cover()
        self.assertIn(f"{CDFA} 12-123456", text)
        self.assertIn(f"{CDPH} 12345", text)

    def test_a_cdfa_registration_prints_as_before(self):
        self.register()
        text = self.cover()
        self.assertIn(f"{CDFA} 12-123456", text)
        self.assertNotIn(CDPH, text)

    def test_none_on_file_names_both_agencies(self):
        text = self.cover()
        self.assertIn(f"{CDFA} none on file", text)
        self.assertIn("CDFA's, or CDPH's for processed products", text)

    def test_a_lapsed_cdph_registration_is_flagged(self):
        self.register(
            registering_agency="cdph",
            registration_number="12345",
            county="",
            renewal_date=date.today() - timedelta(days=1),
            registration_date=date.today() - timedelta(days=400),
        )
        self.assertIn("[REVIEW] The registration's renewal date", self.cover())


class TheRowNamesItsProgram(_Farm):
    def test_the_program_follows_the_agency(self):
        reg = self.register(registering_agency="cdph")
        self.assertEqual(reg.program_name, "CDPH Organic Processed Product Registration")
        reg.registering_agency = "cdfa"
        reg.save()
        self.assertEqual(reg.program_name, "CDFA State Organic Program")

    def test_a_program_typed_by_hand_is_kept(self):
        reg = self.register(program_name="County organic program", registering_agency="cdph")
        self.assertEqual(reg.program_name, "County organic program")

    def test_the_api_takes_and_returns_the_agency(self):
        serializer = StateOrganicRegistrationSerializer(
            data={
                "establishment": self.est.pk,
                "state": "CA",
                "registering_agency": "cdph",
                "operation_type": "processor",
                "registration_number": "12345",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        reg = serializer.save()
        data = StateOrganicRegistrationSerializer(reg).data
        self.assertEqual(data["registering_agency"], "cdph")
        self.assertEqual(data["operation_type_display"], "Processor (CDPH processed products)")

    def test_cdph_outside_california_is_refused(self):
        serializer = StateOrganicRegistrationSerializer(
            data={"establishment": self.est.pk, "state": "OR", "registering_agency": "cdph"}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("registering_agency", serializer.errors)


class TheDossierReadsEachAgency(TestCase):
    """Review of back #433: the audit dossier (PDF and CSV) took one row with `.order_by("-registration_date")
    .first()`. A pending CDPH row with no date yet sorts first in Postgres and printed under the CDFA section,
    flagged as not current, for an operation validly registered with CDFA."""

    def setUp(self):
        from django.utils import timezone

        from history.models import Production
        from product.models import Parcel, Product
        from users.models import User

        user = User.objects.create_user(email="cdph-dossier@test.com", password="x")
        company = Company.objects.create(name="Valley Walnuts LLC")
        self.est = Establishment.objects.create(name="Valley Walnuts", company=company, state="CA")
        parcel = Parcel.objects.create(name="Home Block", establishment=self.est, area=10.0)
        self.history = Production.objects.create(
            name="Walnuts 2026",
            start_date=timezone.now(),
            product=Product.objects.create(name="Walnut"),
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        self.cdfa = StateOrganicRegistration.objects.create(
            establishment=self.est,
            state="CA",
            status="registered",
            registration_number="12-123456",
            county="Butte",
            registration_date=date.today() - timedelta(days=30),
            renewal_date=date.today() + timedelta(days=300),
        )
        self.cdph = StateOrganicRegistration.objects.create(
            establishment=self.est,
            state="CA",
            registering_agency="cdph",
            status="pending",
        )

    def service(self):
        from history.services.audit_export_service import AuditExportService

        return AuditExportService(self.history, certification_type="organic")

    def test_the_latest_row_of_each_agency_cdfa_first(self):
        self.assertEqual(StateOrganicRegistration.latest_per_agency(self.est), [self.cdfa, self.cdph])
        # A newer undated CDFA row does not displace the dated one.
        StateOrganicRegistration.objects.create(establishment=self.est, state="CA", status="pending")
        self.assertEqual(StateOrganicRegistration.latest_per_agency(self.est)[0], self.cdfa)

    def test_the_pdf_flags_only_the_pending_cdph_row(self):
        from reportlab.platypus import Paragraph

        text = " ".join(
            e.text for e in self.service()._build_state_organic_registration_section() if isinstance(e, Paragraph)
        )
        self.assertIn("[REVIEW] CDPH Organic Processed Product Registration:", text)
        self.assertNotIn("[REVIEW] CDFA State Organic Program", text)

    def test_the_csv_carries_both_registrations(self):
        csv_text = self.service().generate_csv().read().decode("utf-8-sig")
        section = csv_text.split("=== STATE ORGANIC PROGRAM REGISTRATION ===")[1].split("===")[0]
        self.assertIn("CDFA State Organic Program", section)
        self.assertIn("CDPH Organic Processed Product Registration", section)
        self.assertEqual(section.count("Registration not current"), 1)
        self.assertLess(section.index("CDPH Organic"), section.index("Registration not current"))
