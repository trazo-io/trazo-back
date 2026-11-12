"""The people the operation names to its certifying agent (2026-11-12).

OTCO O1 (rev. 2026/10/02) §B asks the Legally Responsible Contact (B-2), the Primary Contact (B-3), the Billing
Contact (B-4), the Additional Contacts authorized to act for the operation (B-5: "Oregon Tilth will not conduct
business with any individual whose name does not appear on this list") and everyone Responsibly Connected (B-6,
7 CFR 205.2), each with name, title, phone and email. CCOF's Certification Contract asks the owners or officers
with their titles (A4), the Primary Contact (C1) and the Additional Contacts (C2). All of it lived as prose in
one notes field.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OperationContact, OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from users.models import User, WorksIn


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Marys River LLC")
        self.user = User.objects.create_user(email="contacts@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Marys River Farm", company=self.company, state="OR")
        self.other_est = Establishment.objects.create(name="Second Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            certifier_name="Oregon Tilth Certified Organic (OTCO)",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def url(self, suffix="", est=None):
        est = est or self.est
        return f"/api/companies/{self.company.id}/establishments/{est.id}/operation-contacts/{suffix}"

    def person(self, **kw):
        return OperationContact.objects.create(establishment=self.est, **{"name": "Ann Vos", **kw})

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, "certification_contract"))

    def row(self, agent, document_id, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if f.document_id == document_id)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)


class TheApiKeepsThePeople(_Farm):
    def test_add_a_person_with_several_roles(self):
        r = self.client.post(
            self.url(),
            {
                "name": " Ann  Vos ",
                "title": "Owner",
                "phone": "541-555-0100",
                "email": "ann@marysriver.example",
                "is_legally_responsible": True,
                "is_primary_contact": True,
                "is_responsibly_connected": True,
                "connection": "owner_10_percent",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["role_labels"], ["Legally responsible", "Primary contact", "Responsibly connected"])
        self.assertEqual(OperationContact.objects.get().name, "Ann Vos")

    def test_one_primary_contact_and_one_legally_responsible_contact_per_farm(self):
        self.person(is_primary_contact=True, is_legally_responsible=True)
        r = self.client.post(self.url(), {"name": "Ben Ruiz", "is_primary_contact": True}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Ann Vos is already the primary contact", str(r.json()))
        r = self.client.post(self.url(), {"name": "Ben Ruiz", "is_legally_responsible": True}, format="json")
        self.assertEqual(r.status_code, 400)
        # Another farm keeps its own.
        r = self.client.post(
            self.url(est=self.other_est), {"name": "Ben Ruiz", "is_primary_contact": True}, format="json"
        )
        self.assertEqual(r.status_code, 201, r.content)

    def test_a_connection_is_kept_only_for_a_responsibly_connected_person(self):
        r = self.client.post(self.url(), {"name": "Ben Ruiz", "connection": "officer"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(OperationContact.objects.get().connection, "")


class OperationContactTenancyTests(_Farm):
    def test_another_company_reaches_nothing(self):
        p = self.person()
        outsider = User.objects.create_user(email="other@contacts.test", password="x")
        WorksIn.objects.create(user=outsider, company=Company.objects.create(name="Other"), role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(outsider)
        self.assertIn(self.client.get(self.url()).status_code, (403, 404))
        self.assertIn(self.client.get(self.url(f"{p.id}/")).status_code, (403, 404))
        self.assertIn(self.client.patch(self.url(f"{p.id}/"), {"name": "X"}, format="json").status_code, (403, 404))
        self.assertIn(self.client.post(self.url(), {"name": "X"}, format="json").status_code, (403, 404))
        p.refresh_from_db()
        self.assertEqual(p.name, "Ann Vos")
        self.assertEqual(OperationContact.objects.count(), 1)

    def test_a_viewer_reads_nothing_and_writes_nothing(self):
        self.person()
        viewer = User.objects.create_user(email="viewer@contacts.test", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.post(self.url(), {"name": "X"}, format="json").status_code, 403)
        self.assertEqual(OperationContact.objects.count(), 1)


class TheModulePagePrintsThem(_Farm):
    def test_the_table_and_its_cells(self):
        self.person(
            title="Owner",
            phone="541-555-0100",
            email="ann@marysriver.example",
            is_legally_responsible=True,
            is_primary_contact=True,
            is_responsibly_connected=True,
            connection="owner_10_percent",
        )
        self.person(name="Ben Ruiz", is_authorized_representative=True, is_billing_contact=True)
        page = self.page()
        for words in (
            "The people you name to your certifier, and their roles",
            "Ann Vos, Owner",
            "541-555-0100",
            "ann@marysriver.example",
            "Legally responsible",
            "Owner of 10 percent or more",
            "Ben Ruiz",
            "Billing contact",
            "Not stated",
        ):
            self.assertIn(words, page)
        self.assertNotIn("[REVIEW] No primary contact", page)

    def test_missing_roles_are_review_lines(self):
        self.person(name="Ben Ruiz", is_billing_contact=True)
        page = self.page()
        self.assertIn("[REVIEW] No legally responsible contact is named.", page)
        self.assertIn("[REVIEW] No primary contact is named.", page)
        self.assertIn("[REVIEW] No responsibly connected person (7 CFR 205.2) is named.", page)

    def test_nobody_named_says_so(self):
        self.assertIn("[REVIEW] No person is named to the certifying agent.", self.page())


class TheRegisterReadsThem(_Farm):
    """Each row about the operation's people is judged on its own role (review of back PR 407)."""

    def test_each_otco_row_closes_on_its_own_role(self):
        for ref in ("B-2", "B-3", "B-4", "B-5", "B-6"):
            self.assertTrue(self.row("otco", "O1", ref).is_open, ref)
        self.person(is_primary_contact=True, is_legally_responsible=True)
        self.assertEqual(self.row("otco", "O1", "B-2").state, "answered")
        self.assertEqual(self.row("otco", "O1", "B-3").state, "answered")
        for ref, words in (
            ("B-4", "no billing contact is named"),
            ("B-5", "no person authorized to act for the operation is named"),
            ("B-6", "no responsibly connected person is named"),
        ):
            row = self.row("otco", "O1", ref)
            self.assertTrue(row.is_open, ref)
            self.assertIn(words, row.detail)
        self.person(
            name="Ben Ruiz", is_billing_contact=True, is_authorized_representative=True, is_responsibly_connected=True
        )
        for ref in ("B-4", "B-5", "B-6"):
            self.assertEqual(self.row("otco", "O1", ref).state, "answered", ref)

    def test_ccof_rows_close_on_their_roles(self):
        self.osp.certifier_name = "California Certified Organic Farmers (CCOF)"
        self.osp.save(update_fields=["certifier_name"])
        self.person(is_primary_contact=True)
        self.assertEqual(self.row("ccof", "ORGB06", "C1").state, "answered")
        self.assertTrue(self.row("ccof", "ORGB06", "C2").is_open)

    def test_the_detail_reads_as_a_sentence(self):
        from certifications.services.packet_answers import _Answers

        state, detail = _Answers(self.osp).operation_contacts_state()
        self.assertEqual(detail, "no primary contact or legally responsible contact is named")

    def test_every_row_citing_the_panel_names_its_role(self):
        from certifications.services.certifier_register import load_forms
        from certifications.services.packet_answers import CONTACT_ROLE_ROWS

        citing = {
            (form.document_id, item.ref)
            for agent in ("ccof", "otco", "wsda")
            for form in load_forms(agent)
            for item in form.items
            if "certification_contract.operation_contacts" in item.questions
        }
        self.assertTrue(citing)
        self.assertEqual(citing - set(CONTACT_ROLE_ROWS), set())
