"""Brands a farm packs for: the brand-owner register and G7.0 page C (2026.11.07).

CCOF G7.0 C1/C2, OTCO C8 8.3-2 to 8.3-4 and WSDA AGR 2121 N 6-7 ask who owns each brand the crop is
packed into, whether that company is certified, and the copy behind it: its certificate, or for an
uncertified owner the agent's own agreement (CCOF's Co-Packer Application, OTCO's Private Label
Agreement). Until this slice the plan held one checkbox option, "Sold under the buyer's own label",
with nothing behind it.
"""

import io
import zipfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import BrandOwner, OrganicSystemPlan
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn

AT = "2026-11-07T10:00:00+00:00"
CCOF = "CCOF Certification Services, LLC"
OTCO = "Oregon Tilth Certified Organic"
WSDA = "Washington State Department of Agriculture"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Packed For Orchards")
        self.user = User.objects.create_user(email="brands@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        grant_compliance_exports(self.company)
        self.est = Establishment.objects.create(name="Home Orchard", company=self.company, state="WA")
        self.other_est = Establishment.objects.create(name="North Orchard", company=self.company, state="WA")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def url(self, suffix="", est=None):
        est = est or self.est
        return f"/api/companies/{self.company.id}/establishments/{est.id}/brand-owners/{suffix}"

    def upload(self, est=None, title="Brand owner certificate"):
        est = est or self.est
        r = self.client.post(
            f"/api/companies/{self.company.id}/establishments/{est.id}/documents/",
            {
                "file": SimpleUploadedFile("copy.pdf", b"%PDF-1.4 brand owner copy", content_type="application/pdf"),
                "title": title,
                "folder": "certifications",
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        return GeneratedDocument.objects.get(pk=r.json()["id"])

    def owner(self, **fields):
        data = {"name": "Cascade Fresh LLC", "brand_names": "Cascade Fresh", **fields}
        r = self.client.post(self.url(), data, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return BrandOwner.objects.get(pk=r.json()["id"])

    def plan(self, certifier=CCOF, leaves=("consumer_packaging", "buyer_label"), extra=None):
        answers = {"product_leaves_as": {"at": AT, "value": list(leaves)}, **(extra or {})}
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {"g7_0_labeling": {"answers": answers}},
            },
        )

    def g7(self, osp) -> str:
        return _text(generate_module_pdf(osp, "g7_0_labeling"))

    def row(self, osp, agent, code, ref):
        form = next(f for f in load_forms(agent) if f.code == code)
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)


class BrandOwnerTenancyTests(_Farm):
    def test_another_company_reaches_nothing(self):
        owner = self.owner()
        outsider = User.objects.create_user(email="other@brands.test", password="x")
        other = Company.objects.create(name="Elsewhere")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(outsider)
        self.assertIn(self.client.get(self.url()).status_code, (403, 404))
        self.assertIn(self.client.get(self.url(f"{owner.id}/")).status_code, (403, 404))
        r = self.client.patch(self.url(f"{owner.id}/"), {"name": "Mine now"}, format="json")
        self.assertIn(r.status_code, (403, 404))
        owner.refresh_from_db()
        self.assertEqual(owner.name, "Cascade Fresh LLC")

    def test_another_farms_document_fails_like_a_missing_one(self):
        theirs = self.upload(est=self.other_est)
        foreign = self.client.post(
            self.url(),
            {"name": "X", "certificate_document": theirs.id, "certificate_issued_on": "2026-01-10"},
            format="json",
        )
        missing = self.client.post(
            self.url(),
            {"name": "X", "certificate_document": 999999, "certificate_issued_on": "2026-01-10"},
            format="json",
        )
        self.assertEqual(foreign.status_code, 400)
        # The same refusal, its own id aside: nothing says the foreign id exists.
        self.assertEqual(
            str(foreign.json()).replace(str(theirs.id), "<id>"), str(missing.json()).replace("999999", "<id>")
        )
        self.assertFalse(BrandOwner.objects.exists())

    def test_a_viewer_is_refused(self):
        viewer = User.objects.create_user(email="viewer@brands.test", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_a_file_a_brand_owner_names_cannot_be_deleted_from_documents(self):
        doc = self.upload()
        self.owner(certification_status="certified", certificate_document=doc.id, certificate_issued_on="2026-01-10")
        r = self.client.delete(f"/api/companies/{self.company.id}/establishments/{self.est.id}/documents/{doc.id}/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "brand_owner_document_in_use")
        self.assertTrue(GeneratedDocument.objects.filter(pk=doc.pk).exists())

    def test_the_api_states_what_the_plan_says_of_each_owner(self):
        self.owner(name="A", certification_status="certified")
        self.owner(name="B", certification_status="not_certified")
        self.owner(name="C")
        doc = self.upload()
        self.owner(
            name="D",
            certification_status="certified",
            certificate_document=doc.id,
            certificate_issued_on=date.today().isoformat(),
        )
        rows = self.client.get(self.url()).json()
        states = {row["name"]: row["state"] for row in rows}
        # Every row carries both title keys, null when there is no document (review of #268).
        for row in rows:
            self.assertIn("agreement_document_title", row)
            self.assertIn("certificate_document_title", row)
        self.assertIsNone(next(r for r in rows if r["name"] == "A")["certificate_document_title"])
        self.assertEqual(
            states, {"A": "certificate_missing", "B": "agreement_missing", "C": "status_unknown", "D": "on_file"}
        )

    def test_a_certificate_needs_its_issue_date(self):
        doc = self.upload()
        r = self.client.post(self.url(), {"name": "X", "certificate_document": doc.id}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("certificate_issued_on", r.json())


class PageCTests(_Farm):
    def test_the_page_is_asked_only_when_some_crop_leaves_under_a_buyers_label(self):
        self.owner()
        text = self.g7(self.plan(leaves=("consumer_packaging",)))
        self.assertNotIn("Cascade Fresh LLC", text)
        self.assertIn("C. Brands you pack for", text)

    def test_a_certified_owner_with_a_current_copy(self):
        doc = self.upload()
        self.owner(
            certification_status="certified",
            certifier_name="Washington State Department of Agriculture",
            nop_operation_id="8150000123",
            certificate_document=doc.id,
            certificate_issued_on=(date.today() - timedelta(days=60)).isoformat(),
            products="Honeycrisp apples, 3 lb bag: Organic\nGala apples, bulk tote: Organic",
        )
        text = self.g7(self.plan())
        self.assertIn("Cascade Fresh LLC Brands: Cascade Fresh.", text)
        self.assertIn(
            "Certified organic operation (Washington State Department of Agriculture, NOP ID 8150000123).", text
        )
        self.assertIn("is on file.", text)
        self.assertIn(
            "Products packed under this brand, with each label's organic claim: Honeycrisp apples, 3 lb bag: Organic; "
            "Gala apples, bulk tote: Organic.",
            text,
        )
        self.assertIn("A copy is held in Trazo; it is not included in this document.", text)
        self.assertNotIn("[REVIEW]", text)
        self.assertNotIn("verified", text.lower())

    def test_a_certified_owner_with_no_copy_or_an_old_one_is_flagged(self):
        self.owner(certification_status="certified")
        self.assertIn(
            "[REVIEW] No copy of this brand owner's organic certificate is on file in Trazo.", self.g7(self.plan())
        )
        BrandOwner.objects.all().delete()
        doc = self.upload()
        old = date.today() - timedelta(days=500)
        self.owner(certification_status="certified", certificate_document=doc.id, certificate_issued_on=old.isoformat())
        self.assertIn(
            f"[REVIEW] The certificate copy on file was issued {old.isoformat()}, more than 15 months ago.",
            self.g7(self.plan()),
        )

    def test_an_uncertified_owner_names_the_plans_own_agents_agreement(self):
        self.owner(certification_status="not_certified")
        self.assertIn("Co-Packer Application (ORGB26); none is on file", self.g7(self.plan(certifier=CCOF)))
        self.assertIn("Private Label Agreement (PLA); none is on file", self.g7(self.plan(certifier=OTCO)))
        wsda = self.g7(self.plan(certifier=WSDA))
        self.assertIn("certifying agent's private-label or co-packer agreement; none is on file", wsda)
        self.assertNotIn("ORGB26", wsda)
        self.assertNotIn("Private Label Agreement (PLA)", wsda)

    def test_an_owner_whose_status_is_not_stated_and_an_empty_register_are_flagged(self):
        self.assertIn(
            "[REVIEW] The plan says some crop leaves under a buyer's label, and no brand owner", self.g7(self.plan())
        )
        self.owner()
        self.assertIn(
            "[REVIEW] Whether this brand owner is a certified organic operation is not stated.", self.g7(self.plan())
        )

    def test_labels_not_submitted_or_said_attached_with_none_print_for_review(self):
        text = self.g7(self.plan(extra={"labels_submitted_to_certifier": {"at": AT, "value": "not_submitted"}}))
        self.assertIn("[REVIEW] Labels packed for a brand owner have not been submitted to the certifying agent", text)
        text = self.g7(
            self.plan(extra={"labels_submitted_to_certifier": {"at": AT, "value": "new_or_updated_attached"}})
        )
        self.assertIn("[REVIEW]", text)


class PacketAndCoverageTests(_Farm):
    def certified_with_copy(self):
        doc = self.upload()
        return self.owner(
            certification_status="certified",
            certificate_document=doc.id,
            certificate_issued_on=(date.today() - timedelta(days=30)).isoformat(),
            products="Apples: Organic",
        )

    def test_the_copy_rides_under_brand_owners_and_the_page_names_it(self):
        owner = self.certified_with_copy()
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.plan())))
        path = f"brand-owners/{owner.pk}-Cascade Fresh LLC-certificate.pdf"
        self.assertIn(path, packet.namelist())
        self.assertEqual(packet.read(path), b"%PDF-1.4 brand owner copy")
        self.assertIn(f"Copy in this packet: {path}", _text(packet.read("modules/G7_0.pdf")))

    def test_nothing_ships_when_no_crop_leaves_under_a_buyers_label(self):
        self.certified_with_copy()
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.plan(leaves=("consumer_packaging",)))))
        self.assertFalse([n for n in packet.namelist() if n.startswith("brand-owners/")])

    def test_ccof_c2_is_answered_only_when_every_owner_has_its_copy(self):
        self.owner(name="Uncertified Brand Co", certification_status="not_certified")
        # C2 also asks how owners' certificates are kept current; answered here, so only the copy decides.
        osp = self.plan(
            extra={
                "brand_owner_certificate_check": {"at": AT, "value": ["certificates_on_file"]},
                "brand_owner_certificate_frequency": {"at": AT, "value": "annually"},
            }
        )
        state = self.row(osp, "ccof", "G7.0", "C2")
        self.assertEqual(state.state, "attachment_missing")
        self.assertIn("Uncertified Brand Co", state.detail)
        owner = BrandOwner.objects.get()
        owner.agreement_document = self.upload(title="Co-Packer Application")
        owner.save()
        self.assertEqual(self.row(osp, "ccof", "G7.0", "C2").state, "answered")

    def test_the_rows_do_not_apply_when_no_crop_leaves_under_a_buyers_label(self):
        osp = self.plan(leaves=("consumer_packaging",))
        self.assertEqual(self.row(osp, "ccof", "G7.0", "C2").state, "not_applicable")
        self.assertEqual(self.row(osp, "otco", "C8", "8.3-4").state, "not_applicable")

    def test_wsda_n7_and_otco_8_3_3_read_the_page_c_answers(self):
        self.certified_with_copy()
        osp = self.plan(
            certifier=WSDA,
            extra={
                "labels_name_other_agency": {"at": AT, "value": False},
                "brand_owner_certificate_check": {"at": AT, "value": ["certificates_on_file", "oid_check"]},
                "brand_owner_certificate_frequency": {"at": AT, "value": "annually"},
            },
        )
        self.assertEqual(self.row(osp, "wsda", "N", "7").state, "answered")
        self.assertEqual(self.row(osp, "wsda", "N", "7a").state, "answered")
        self.assertEqual(self.row(osp, "otco", "C8", "8.3-3").state, "answered")
