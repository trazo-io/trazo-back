"""Scopes, standards, regulators, another agency today, and who signed (2026-11-13).

OTCO's O1 (rev. 2026/10/02) asks the scopes applied for, transitional and fungi among them (C-1), the standards to be
assessed to (C-2), which regulators inspect the operation (C-5) and any negative report one gave, with the reports
and responses attached (C-6); whether another agency certifies the operation today and whether that stays, with its
certificate (D-1A, D-1B); and the signer's name, title and date beside the signature (I-B). CCOF's Certification
Contract asks the same certified-today question with the certificate (D4) and the same signature block (G).

Trazo signs nothing: the signed form is the agency's own, attached to `contract_upload`.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import progress
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from documents.models import GeneratedDocument

MODULE = MODULES_BY_KEY["certification_contract"]
OTCO = "Oregon Tilth Certified Organic (OTCO)"
CCOF = "California Certified Organic Farmers (CCOF)"
NEW_KEYS = (
    "contract_signed_by",
    "contract_signed_on",
    "history_certified_elsewhere_now",
    "history_keeping_other_certification",
    "history_current_certificate_upload",
    "standards_requested",
    "standards_requested_other",
    "regulatory_agencies",
    "regulatory_negative_report",
    "regulatory_reports_upload",
)

ANSWERS = {
    "contract_notes": "Marys River LLC",
    "contract_scopes": ["crops", "transitional"],
    "contract_signed_by": "Ann Vos, managing member",
    "contract_signed_on": "2026-10-30",
    "history_ever_certified": True,
    "history_prior_agents": "Oregon Tilth, 2015 to date; Organic Certifiers, 2019 to date",
    "history_certified_elsewhere_now": True,
    "history_keeping_other_certification": False,
    "standards_requested": ["usda_nop", "us_canada", "other"],
    "standards_requested_other": "Demeter Biodynamic",
    "regulatory_agencies": "Oregon Department of Agriculture, Food Safety Program",
    "regulatory_negative_report": True,
}


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Marys River LLC")
        self.est = Establishment.objects.create(name="Marys River Farm", company=company, state="OR")

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
                        "definition_version": "2026.12.09",
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

    def row(self, agent, document_id, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if f.document_id == document_id)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)

    def pdf(self, answers) -> str:
        return _text(generate_module_pdf(self.plan(answers), "certification_contract"))


class EveryNewQuestionIsOptional(TestCase):
    def test_a_completed_profile_stays_complete(self):
        questions = {q.key: q for page in MODULE.pages for q in page.questions}
        for key in NEW_KEYS:
            with self.subTest(question=key):
                self.assertFalse(questions[key].required)
        answers = {"contract_notes": "Marys River LLC", "contract_scopes": ["crops"]}
        self.assertEqual(progress(MODULE, answers)["missing"], [])


class TheScopesKeepTheirMeaning(TestCase):
    def test_the_new_scopes_are_appended(self):
        """Stored answers name options by value, so the four that were there keep their place and words."""
        question = next(q for page in MODULE.pages for q in page.questions if q.key == "contract_scopes")
        values = [o.value for o in question.options]
        self.assertEqual(values[:4], ["crops", "wild_crops", "livestock", "handling"])
        self.assertEqual(values[4:], ["transitional", "fungi"])


class TheModulePdfPrintsThem(_Plan):
    def test_every_answer_prints(self):
        text = self.pdf(ANSWERS)
        for words in (
            "Ann Vos, managing member",
            "Transitional",
            "Organic Certifiers, 2019 to date",
            "US-Canada organic equivalency",
            "Demeter Biodynamic",
            "Oregon Department of Agriculture, Food Safety Program",
            "E. Standards and regulatory agencies",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)


class TheRegisterReadsThem(_Plan):
    OTCO_ANSWERED = ("C-1", "C-2", "C-5", "D-1A", "D-1B")

    def test_otco_rows_close_with_the_answers(self):
        self.plan(ANSWERS)
        for ref in self.OTCO_ANSWERED:
            with self.subTest(ref=ref):
                self.assertEqual(self.row("otco", "O1", ref).state, "answered")

    def test_otco_rows_are_open_without_them(self):
        self.plan({"contract_scopes": ["crops"]})
        for ref in ("C-2", "C-5", "C-6", "D-1A", "D-1B", "I-B (signature)"):
            with self.subTest(ref=ref):
                self.assertTrue(self.row("otco", "O1", ref).is_open)

    def test_a_negative_report_needs_the_reports_attached(self):
        self.plan(ANSWERS)
        self.assertTrue(self.row("otco", "O1", "C-6").is_open)
        self.upload("regulatory_reports_upload")
        self.assertEqual(self.row("otco", "O1", "C-6").state, "answered")

    def test_no_negative_report_is_an_answer(self):
        self.plan({"regulatory_negative_report": False})
        self.assertEqual(self.row("otco", "O1", "C-6").state, "answered")

    def test_not_certified_elsewhere_answers_d1a_and_d1b(self):
        self.plan({"history_ever_certified": True, "history_certified_elsewhere_now": False})
        for ref in ("D-1A", "D-1B"):
            with self.subTest(ref=ref):
                self.assertEqual(self.row("otco", "O1", ref).state, "answered")

    def test_certified_elsewhere_needs_that_certificate(self):
        self.plan(ANSWERS)
        before = self.row("otco", "O1", "D-1 (certificate attachment)")
        self.assertEqual(before.state, "attachment_missing")
        self.upload("history_current_certificate_upload")
        # The other agency's certificate answers what was asked; the row stays partial for the register's own
        # gap (the certificate of the agency the plan is filed with does not travel), never "answered".
        self.assertEqual(self.row("otco", "O1", "D-1 (certificate attachment)").state, "partial")

    def test_the_signature_needs_the_signed_form_and_the_signer(self):
        self.plan({"contract_signed_by": "Ann Vos, managing member", "contract_signed_on": "2026-10-30"})
        self.assertTrue(self.row("otco", "O1", "I-B (signature)").is_open)
        self.upload("contract_upload")
        self.assertEqual(self.row("otco", "O1", "I-B (signature)").state, "answered")

    def test_a_signed_form_without_the_signer_stays_open(self):
        """O1 I-B asks Name/Title beside the date: the file and the date alone do not answer it."""
        self.plan({"contract_signed_on": "2026-10-30"})
        self.upload("contract_upload")
        self.assertTrue(self.row("otco", "O1", "I-B (signature)").is_open)
        self.assertTrue(self.row("otco", "O1", "I-A").is_open)

    def test_ccof_d4_and_the_signature(self):
        self.plan(
            {
                "history_ever_certified": True,
                "history_certified_elsewhere_now": False,
                "contract_signed_by": "Ann Vos, managing member",
                "contract_signed_on": "2026-10-30",
            },
            certifier=CCOF,
        )
        self.upload("contract_upload")
        for ref in ("D4", "G (signature)"):
            with self.subTest(ref=ref):
                self.assertEqual(self.row("ccof", "ORGB06", ref).state, "answered")
