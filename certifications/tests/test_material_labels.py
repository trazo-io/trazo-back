"""
A label or container photo for each material, for OTCO C11 11.1.

OTCO C11 11.1 (rev. 2023/09/14, read live 2026-11-04): "Labels or photos of container are attached
for each product that is not OMRI or WSDA listed." CCOF's Materials Application and WSDA AGR 2196 do
not ask. Until now no material had anywhere to hold its label, so an OTCO reviewer received the rows
and no labels, and a National List substance printed "National List substance", which reads as
enough when for this form it is not.

Pinned here:
  * the label is a file uploaded to THIS farm, linked to the material, and cannot be deleted while
    linked;
  * the packet carries it under attachments/materials/, and the page gives its path only when the
    packet carries it;
  * "none on file" is stated only on an OTCO plan, and only for a product its listing does not cover
    (a National List substance and a lapsed OMRI listing need one; a current OMRI or WSDA listing
    does not);
  * next year's plan keeps the label.
"""

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, PlanMaterialEntry
from certifications.services.osp_fork import fork_plan
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from certifications.services.plan_materials import PlanMaterial, materials_list_rows
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from users.models import User, WorksIn

OTCO = "Oregon Tilth Certified Organic"
WSDA = "Washington State Department of Agriculture"


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="labels@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Label Orchards LLC")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Label Orchard", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name=OTCO
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _upload(self, est=None, source="upload", name="label.png"):
        return GeneratedDocument.objects.create(
            establishment=est or self.est,
            folder="uploads",
            source=source,
            title="Rexius compost bag",
            file=SimpleUploadedFile(name, b"label-bytes", content_type="image/png"),
        )

    def _answer(self, **body):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/materials-list/answer/"
        return self.client.post(url, body, format="json")


class AttachingTheLabelTests(_Farm):
    def test_a_file_on_this_farm_is_linked_and_shown_and_cleared(self):
        doc = self._upload()
        res = self._answer(name="Rexius Organic Compost", label_document=doc.pk)
        self.assertIn(res.status_code, (200, 201), res.content[:300])
        row = next(r for r in materials_list_rows(self.osp) if r["name"] == "Rexius Organic Compost")
        self.assertEqual((row["label_document"], row["label_document_title"]), (doc.pk, "Rexius compost bag"))
        self._answer(name="Rexius Organic Compost", label_document="")
        self.assertIsNone(PlanMaterialEntry.objects.get(osp=self.osp).label_document_id)

    def test_another_farms_file_and_a_generated_document_are_refused_alike(self):
        other = Establishment.objects.create(name="Other", company=Company.objects.create(name="Other Co"))
        for doc in (self._upload(est=other), self._upload(source="module_pdf")):
            with self.subTest(source=doc.source):
                res = self._answer(name="Rexius Organic Compost", label_document=doc.pk)
                self.assertEqual(res.status_code, 400, res.content[:300])
                self.assertIn("does not exist", str(res.json()["label_document"]))
        self.assertFalse(PlanMaterialEntry.objects.filter(label_document__isnull=False).exists())

    def test_a_linked_label_cannot_be_deleted_from_documents(self):
        doc = self._upload()
        self._answer(name="Rexius Organic Compost", label_document=doc.pk)
        self.client.raise_request_exception = False
        res = self.client.delete(f"/api/companies/{self.company.id}/establishments/{self.est.id}/documents/{doc.pk}/")
        self.assertEqual(res.status_code, 400, res.content[:300])
        self.assertEqual(res.json()["code"], "material_label_in_use")
        self.assertTrue(GeneratedDocument.objects.filter(pk=doc.pk).exists())

    def test_next_years_plan_keeps_the_label(self):
        doc = self._upload()
        PlanMaterialEntry.objects.create(osp=self.osp, product_name="Rexius Organic Compost", label_document=doc)
        self.osp.status = "active"
        self.osp.save(update_fields=["status"])
        clone = fork_plan(self.osp, self.user)
        self.assertEqual(clone.plan_material_entries.get().label_document_id, doc.pk)


class WhoNeedsALabelTests(TestCase):
    def test_only_a_current_omri_or_wsda_listing_is_exempt(self):
        cases = {
            ("OMRI", ""): False,
            ("WSDA", ""): False,
            ("OMRI", "2026-09-26"): True,
            ("National List", ""): True,
            ("Operator-entered", ""): True,
        }
        for (source, delisted), expected in cases.items():
            with self.subTest(source=source, delisted=delisted):
                row = PlanMaterial(name="X", source=source, delisted_on=delisted)
                self.assertEqual(row.needs_label, expected)


class PrintingTheLabelTests(_Farm):
    def setUp(self):
        super().setUp()
        self.omri = OMRIProduct.objects.create(product_name="Entrust SC", omri_id="dow-2900")
        self.sulfur = NationalListSubstance.objects.create(
            substance_name="Test sulfur", substance_name_normalized="test sulfur", cfr_section="205.601"
        )
        self.osp.approved_omri_products.add(self.omri)
        self.osp.approved_national_list_substances.add(self.sulfur)
        self.doc = self._upload()
        self.entry = PlanMaterialEntry.objects.create(
            osp=self.osp, product_name="Rexius Organic Compost", label_document=self.doc
        )

    def test_the_packet_carries_the_label_and_the_page_gives_its_path(self):
        data = generate_osp_packet(self.osp)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            path = f"attachments/materials/{self.entry.pk}-Rexius Organic Compost.png"
            self.assertIn(path, zf.namelist())
            self.assertEqual(zf.read(path), b"label-bytes")
            page = _pdf_text(zf.read("modules/materials_application.pdf"))
        self.assertIn(f"Label or container photo in this packet: {path}", page)
        # The National List substance has no label and OTCO asks for one; the OMRI listing does not.
        self.assertEqual(page.count("Label or container photo: none on file"), 1)

    def test_outside_a_packet_the_label_is_held_not_claimed(self):
        page = _pdf_text(generate_module_pdf(self.osp, "materials_application"))
        self.assertIn("Label or container photo: held in Trazo; not included in this document.", page)
        self.assertNotIn("in this packet", page)

    def test_an_agent_that_does_not_ask_is_not_told_one_is_missing(self):
        self.osp.certifier_name = WSDA
        self.osp.save(update_fields=["certifier_name"])
        page = _pdf_text(generate_module_pdf(self.osp, "materials_application"))
        self.assertNotIn("none on file", page)
        rows = materials_list_rows(self.osp)
        self.assertFalse(any(r["needs_label"] for r in rows))

    def test_the_editor_flags_the_rows_an_otco_plan_needs_a_label_for(self):
        flagged = {r["name"]: r["needs_label"] for r in materials_list_rows(self.osp)}
        # "Asked for", not "missing": the compost has its label and is still a product OTCO asks one for.
        self.assertEqual(flagged, {"Entrust SC": False, "Test sulfur": True, "Rexius Organic Compost": True})
