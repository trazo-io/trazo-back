"""
DMS tests (WS-3).

The properties that matter:

  1. Generated documents are immutable history — DELETE refused for anything the
     system generated; only farmer uploads can be removed.
  2. Filing failures never break the download (file_document returns None and logs).
  3. Tenant scoping — documents list only within the caller's company establishment.
  4. Explicit generate actions FILE a copy: the OSP submit snapshot lands on the shelf
     (the end-to-end wiring proof for the pattern all six sites share).
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from documents.services.filing import file_document
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn


class FilingServiceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="DMS Farm")
        self.establishment = Establishment.objects.create(name="Shelf Ranch", company=self.company, state="CA")

    def test_file_document_persists_row_and_bytes(self):
        doc = file_document(
            establishment=self.establishment,
            source="dossier",
            folder="exports",
            title="Test dossier",
            filename="test.pdf",
            content=b"%PDF-1.7 test",
            content_type="application/pdf",
        )
        self.assertIsNotNone(doc)
        self.assertEqual(doc.size_bytes, len(b"%PDF-1.7 test"))
        with doc.file.open("rb") as fh:
            self.assertEqual(fh.read(), b"%PDF-1.7 test")

    def test_filing_failure_returns_none(self):
        # Establishment=None breaks the FK — filing must swallow and return None,
        # never raise into the download path.
        doc = file_document(
            establishment=None,
            source="dossier",
            folder="exports",
            title="x",
            filename="x.pdf",
            content=b"x",
        )
        self.assertIsNone(doc)

    def test_deletable_only_for_uploads(self):
        gen = file_document(
            establishment=self.establishment,
            source="pur",
            folder="exports",
            title="PUR",
            filename="pur.csv",
            content=b"a,b",
        )
        up = file_document(
            establishment=self.establishment,
            source="upload",
            folder="uploads",
            title="Receipt",
            filename="r.pdf",
            content=b"%PDF",
        )
        self.assertFalse(gen.is_deletable)
        self.assertTrue(up.is_deletable)


class DocumentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="DMS API Farm")
        self.user = User.objects.create_user(email="dms@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Shelf", company=self.company, state="CA")
        # Uploading now passes through `check_storage_quota`. Documents are never refused
        # for being over quota, but a company with NO subscription has no storage at all,
        # so the fixture needs a plan the way every other write-path fixture does.
        grant_compliance_exports(self.company)
        self.client.force_authenticate(user=self.user)

    def _url(self, doc_id=None, suffix=""):
        base = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/documents/"
        if doc_id is not None:
            return f"{base}{doc_id}/{suffix}"
        return base

    def _seed(self, source="dossier", folder="exports", title="Doc"):
        return file_document(
            establishment=self.establishment,
            source=source,
            folder=folder,
            title=title,
            filename="doc.pdf",
            content=b"%PDF-doc",
            content_type="application/pdf",
        )

    def test_list_scoped_and_filterable(self):
        self._seed(title="Dossier A")
        self._seed(source="pur", title="PUR B")
        other_company = Company.objects.create(name="Other")
        other_est = Establishment.objects.create(name="Other Est", company=other_company, state="CA")
        file_document(
            establishment=other_est, source="pur", folder="exports", title="Foreign", filename="f.csv", content=b"x"
        )

        r = self.client.get(self._url())
        titles = [d["title"] for d in r.json()]
        self.assertIn("Dossier A", titles)
        self.assertNotIn("Foreign", titles)

        r2 = self.client.get(self._url() + "?source=pur")
        self.assertEqual([d["title"] for d in r2.json()], ["PUR B"])

        r3 = self.client.get(self._url() + "?search=dossier")
        self.assertEqual([d["title"] for d in r3.json()], ["Dossier A"])

    def test_upload_and_delete_upload(self):
        f = SimpleUploadedFile("weigh-ticket.pdf", b"%PDF-wt", content_type="application/pdf")
        r = self.client.post(self._url(), {"file": f, "title": "Weigh ticket", "folder": "uploads"})
        self.assertEqual(r.status_code, 201)
        doc_id = r.json()["id"]
        self.assertTrue(r.json()["is_deletable"])

        d = self.client.delete(self._url(doc_id))
        self.assertEqual(d.status_code, 204)
        self.assertFalse(GeneratedDocument.objects.filter(pk=doc_id).exists())

    def test_generated_documents_cannot_be_deleted(self):
        doc = self._seed()
        r = self.client.delete(self._url(doc.id))
        self.assertEqual(r.status_code, 400)
        self.assertTrue(GeneratedDocument.objects.filter(pk=doc.id).exists())

    def test_patch_edits_only_title_and_tags(self):
        doc = self._seed()
        r = self.client.patch(self._url(doc.id), {"title": "Renamed", "tags": ["renewal"]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["title"], "Renamed")
        self.assertEqual(r.json()["tags"], ["renewal"])
        r2 = self.client.patch(self._url(doc.id), {"folder": "uploads"}, format="json")
        self.assertEqual(r2.status_code, 400)

    def test_download_streams_bytes(self):
        doc = self._seed()
        r = self.client.get(self._url(doc.id, "download/"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"%PDF-doc")

    def test_viewer_reads_but_cannot_upload_or_delete(self):
        doc = self._seed()
        viewer = User.objects.create_user(email="dms-viewer@test.com", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(user=viewer)
        self.assertEqual(self.client.get(self._url()).status_code, 200)
        f = SimpleUploadedFile("x.pdf", b"%PDF", content_type="application/pdf")
        self.assertEqual(self.client.post(self._url(), {"file": f}).status_code, 403)
        self.assertEqual(self.client.delete(self._url(doc.id)).status_code, 403)


class GeneratorWiringTests(TestCase):
    """End-to-end proof of the filing pattern via the OSP submit snapshot."""

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Wire Farm")
        self.user = User.objects.create_user(email="wire@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Wire Ranch", company=self.company, state="CA")

        # Varied prose — the submit gate's padding detector (unique-token ratio)
        # correctly rejects repeated filler, so each section gets distinct sentences.
        def _narrative(topic):
            return (
                f"Our operation documents {topic} in detail for the certifier. We maintain "
                "records of every input application including the product name, the date it "
                "was applied, the rate used, and the parcel where the work occurred. Field "
                "staff record activities on the day they happen using mobile devices, and the "
                "farm manager reviews entries weekly against purchase receipts and invoices. "
                "Supporting documentation such as weigh tickets, seed tags, and laboratory "
                "results is retained for at least five years and made available at inspection."
            )

        sections = {k: {"narrative": _narrative(k.replace("_", " ")), "last_updated": None} for k in OSP_SECTION_KEYS}
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment, version_number=1, status="draft", sections=sections
        )
        self.client.force_authenticate(user=self.user)

    def test_submit_files_snapshot_into_dms(self):
        url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}" f"/osps/{self.osp.id}/submit/"
        r = self.client.post(url)
        self.assertEqual(r.status_code, 200, r.data)
        docs = GeneratedDocument.objects.filter(establishment=self.establishment, source="osp_snapshot")
        self.assertEqual(docs.count(), 1)
        doc = docs.get()
        self.assertEqual(doc.folder, "organic_system_plan")
        self.assertGreater(doc.size_bytes, 500)
        self.assertIn("OSP v1", doc.title)
