"""The operation's legal entity and addresses (2026-11-13).

CCOF's Certification Contract (ORGB06 V2 R6) asks the registered legal business name, DBA, phone, website and a
public-facing email (A1), the registered legal business address (A2), where the DBA appears in the audit trail and
where it is registered (A3), the legal structure and state of incorporation (A4), and the mailing (A6) and billing
(A7) addresses. OTCO's O1 (rev. 2026/10/02) asks whether the operation name is a legally registered business (A-1),
every registered DBA (A-3), the mailing and billing addresses (B-1) and which contact details may be published
(B-7). All of it was prose in one notes field, or nowhere.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OperationContact, OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import progress
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment

MODULE = MODULES_BY_KEY["certification_contract"]
OTCO = "Oregon Tilth Certified Organic (OTCO)"
CCOF = "California Certified Organic Farmers (CCOF)"

ANSWERS = {
    "contract_notes": "The certificate is issued to Marys River LLC; both DBAs are on our invoices.",
    "legally_registered": True,
    "legal_structure": "llc",
    "state_of_incorporation": "Oregon",
    "uses_dba": True,
    "dba_names": "Marys River Fruit\nRiverbend Orchards",
    "dba_registration": ["state"],
    "dba_use": "some",
    "dba_use_detail": "Riverbend Orchards appears only on the fresh-pack pear invoices.",
    "legal_address_is": "other",
    "legal_address_street": "1200 SW Main St Suite 300",
    "legal_address_city": "Portland",
    "legal_address_state": "OR",
    "legal_address_zip": "97205",
    "legal_address_country": "United States",
    "mailing_address_is": "legal",
    "billing_address_is": "other",
    "billing_address_street": "PO Box 88",
    "billing_address_city": "Philomath",
    "billing_address_state": "OR",
    "billing_address_zip": "97370",
    "billing_address_country": "United States",
    "public_contact_shared": ["email", "website"],
    "public_email": "orders@marysriver.example",
    "public_website": "https://marysriver.example",
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
                        "definition_version": "2026.12.08",
                    }
                },
            },
        )
        return self.osp

    def row(self, agent, document_id, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if f.document_id == document_id)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)

    def page_d(self, answers) -> str:
        text = _text(generate_module_pdf(self.plan(answers), "certification_contract"))
        return text[text.index("D. Legal entity and addresses") :]


class EveryQuestionIsOptional(TestCase):
    def test_a_completed_profile_stays_complete(self):
        page = next(p for p in MODULE.pages if p.key == "d_legal_entity")
        for question in page.questions:
            with self.subTest(question=question.key):
                self.assertFalse(question.required)
        answers = {"contract_notes": "Marys River LLC", "contract_scopes": ["crops"]}
        self.assertEqual(progress(MODULE, answers)["missing"], [])


class TheModulePdfPrintsThem(_Plan):
    def test_every_answer_prints(self):
        text = self.page_d(ANSWERS)
        for words in (
            "Limited liability company (LLC)",
            "Oregon",
            "Marys River Fruit",
            "Riverbend Orchards appears only on the fresh-pack pear invoices.",
            "1200 SW Main St Suite 300",
            "97205",
            "The registered legal address",
            "PO Box 88",
            "orders@marysriver.example",
            "https://marysriver.example",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)

    def test_a_same_as_answer_prints_no_empty_address(self):
        text = self.page_d({"legal_address_is": "physical", "mailing_address_is": "physical"})
        self.assertIn("The farm's physical address", text)
        self.assertNotIn("Street address", text)


class TheRegisterReadsThem(_Plan):
    def test_otco_rows_close_with_the_answers(self):
        self.plan(ANSWERS)
        OperationContact.objects.create(establishment=self.est, name="Ann Vos", is_billing_contact=True)
        for ref in ("A-1", "A-3", "B-1 (mailing)", "B-1 (billing)", "B-7"):
            with self.subTest(ref=ref):
                self.assertEqual(self.row("otco", "O1", ref).state, "answered")

    def test_otco_rows_are_open_without_them(self):
        self.plan({})
        for ref in ("A-1", "A-3", "B-1 (mailing)", "B-1 (billing)", "B-7"):
            with self.subTest(ref=ref):
                self.assertTrue(self.row("otco", "O1", ref).is_open)

    def test_billing_needs_the_billing_contact_too(self):
        """OTCO B-1 asks the billing contact's name and email beside the billing address."""
        self.plan(ANSWERS)
        row = self.row("otco", "O1", "B-1 (billing)")
        self.assertTrue(row.is_open)
        self.assertIn("no billing contact is named", row.detail)

    def test_nothing_published_is_an_answer(self):
        self.plan({"public_contact_shared": ["none"]})
        self.assertEqual(self.row("otco", "O1", "B-7").state, "answered")

    def test_a_chosen_detail_left_blank_keeps_the_row_open(self):
        self.plan({"public_contact_shared": ["email"]})
        self.assertTrue(self.row("otco", "O1", "B-7").is_open)

    def test_ccof_rows_close_with_the_answers(self):
        self.plan(ANSWERS, certifier=CCOF)
        for ref in ("A2", "A3", "A6", "A7"):
            with self.subTest(ref=ref):
                self.assertEqual(self.row("ccof", "ORGB06", ref).state, "answered")


class SameAsFollowsTheChain(_Plan):
    """A "same as" answer answers its row only if the address it points to is given (review of back #410)."""

    def test_same_as_an_ungiven_legal_address_keeps_mailing_open(self):
        self.plan({"mailing_address_is": "legal"})
        row = self.row("otco", "O1", "B-1 (mailing)")
        self.assertTrue(row.is_open)
        self.assertIn("the registered legal address it points to is not given", row.detail)

    def test_billing_same_as_mailing_same_as_an_ungiven_legal_address_stays_open(self):
        self.plan({"billing_address_is": "mailing", "mailing_address_is": "legal", "legal_address_is": "other"})
        OperationContact.objects.create(establishment=self.est, name="Ann Vos", is_billing_contact=True)
        self.assertTrue(self.row("otco", "O1", "B-1 (billing)").is_open)

    def test_same_as_a_complete_physical_address_is_answered(self):
        self.est.address, self.est.city, self.est.zip_code = "31480 Calapooia Rd", "Tangent", "97389"
        self.est.save()
        self.plan({"billing_address_is": "mailing", "mailing_address_is": "legal", "legal_address_is": "physical"})
        OperationContact.objects.create(establishment=self.est, name="Ann Vos", is_billing_contact=True)
        self.assertEqual(self.row("otco", "O1", "B-1 (mailing)").state, "answered")
        self.assertEqual(self.row("otco", "O1", "B-1 (billing)").state, "answered")

    def test_same_as_a_physical_address_missing_from_the_profile_stays_open(self):
        self.plan({"mailing_address_is": "physical"})
        row = self.row("otco", "O1", "B-1 (mailing)")
        self.assertTrue(row.is_open)
        self.assertIn("physical address is not complete", row.detail)
