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

    def test_upload_is_labelled_by_who_uploaded_not_as_the_farmers(self):
        """Pilot rehearsal 2026-10, finding 5: an upload by the operator account read "Farmer
        upload". The source label is neutral; the uploader's name travels separately."""
        self.user.first_name, self.user.last_name = "Ops", "Account"
        self.user.save(update_fields=["first_name", "last_name"])
        f = SimpleUploadedFile("invoice.pdf", b"%PDF-inv", content_type="application/pdf")
        r = self.client.post(self._url(), {"file": f, "title": "Invoice"})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["source_display"], "Upload")
        self.assertNotIn("farmer", r.json()["source_display"].lower())
        self.assertEqual(r.json()["created_by_name"], "Ops Account")

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


class DocumentSearchTests(TestCase):
    """`?search=` matches one term against title, tags, document kind and source label.

    A farmer types what the page shows: a tag they added ("Invoices"), a kind ("bill of
    lading"), a source label ("Audit dossier"). Each test seeds a decoy that must NOT come
    back, so a filter that silently returned everything would fail.
    """

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Search Farm")
        self.user = User.objects.create_user(email="dms-search@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Search Ranch", company=self.company, state="CA")
        self.client.force_authenticate(user=self.user)
        self._seed(self.establishment, title="Plain sheet")

    @staticmethod
    def _seed(establishment, title, source="upload", tags=None, source_kind=""):
        return file_document(
            establishment=establishment,
            source=source,
            folder="uploads" if source == "upload" else "exports",
            title=title,
            filename="doc.pdf",
            content=b"%PDF-doc",
            content_type="application/pdf",
            tags=tags,
            source_kind=source_kind,
        )

    def _titles(self, term):
        r = self.client.get(
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/documents/",
            {"search": term},
        )
        self.assertEqual(r.status_code, 200, r.content)
        return sorted(d["title"] for d in r.json())

    def test_title_matches_case_insensitively(self):
        self._seed(self.establishment, title="Walnut Weigh Ticket")
        self.assertEqual(self._titles("weigh TICK"), ["Walnut Weigh Ticket"])

    def test_tag_matches_partially_and_case_insensitively(self):
        self._seed(self.establishment, title="Scan 01", tags=["2026 season", "Invoices"])
        self.assertEqual(self._titles("invoi"), ["Scan 01"])
        self.assertEqual(self._titles("SEASON"), ["Scan 01"])

    def test_tag_match_is_per_element_not_the_json_text(self):
        """`tags__icontains` would cast the list to text, so JSON punctuation matched every
        tagged document. Matching element by element, it matches none."""
        self._seed(self.establishment, title="Scan 02", tags=["north block", "spring"])
        self.assertEqual(self._titles('", "'), [])
        self.assertEqual(self._titles("["), [])
        self.assertEqual(self._titles("block, spring"), [])

    def test_non_list_tags_do_not_break_the_search(self):
        doc = self._seed(self.establishment, title="Scan 03")
        GeneratedDocument.objects.filter(pk=doc.pk).update(tags={"not": "a list"})
        self.assertEqual(self._titles("scan 03"), ["Scan 03"])
        self.assertEqual(self._titles("zzz"), [])

    def test_source_kind_matches_code_and_display_label(self):
        self._seed(self.establishment, title="Scan 04", source_kind="receipt")
        self._seed(self.establishment, title="Scan 05", source_kind="bill_of_lading")
        self.assertEqual(self._titles("receipt"), ["Scan 04"])
        self.assertEqual(self._titles("Purchase receipt"), ["Scan 04"])
        self.assertEqual(self._titles("bill of lading"), ["Scan 05"])
        self.assertEqual(self._titles("bill_of_lading"), ["Scan 05"])

    def test_source_matches_display_label(self):
        self._seed(self.establishment, title="Q3 shelf export", source="dossier")
        self._seed(self.establishment, title="March run", source="pur")
        self.assertEqual(self._titles("dossier"), ["Q3 shelf export"])
        self.assertEqual(self._titles("audit DOSSIER"), ["Q3 shelf export"])
        self.assertEqual(self._titles("pur export"), ["March run"])

    def test_non_matching_term_returns_nothing(self):
        self._seed(self.establishment, title="Scan 06", tags=["Invoices"], source_kind="invoice")
        self.assertEqual(self._titles("zzqx-no-such-document"), [])

    def test_like_wildcards_are_literal(self):
        """A "%" or "_" is a character the farmer typed, not a pattern: it matches only a
        title or tag that contains it."""
        self._seed(self.establishment, title="Scan 07", tags=["block a"])
        self.assertEqual(self._titles("%"), [])
        self.assertEqual(self._titles("_"), [])
        self.assertEqual(self._titles("block%a"), [])
        self._seed(self.establishment, title="Scan 08", tags=["lot_7", "100% organic"])
        self.assertEqual(self._titles("_"), ["Scan 08"])
        self.assertEqual(self._titles("0% o"), ["Scan 08"])
        self.assertEqual(self._titles("\\"), [])

    def test_another_farms_tag_is_never_returned(self):
        self._seed(self.establishment, title="Ours", tags=["Walnut North"])
        sibling = Establishment.objects.create(name="Sibling Ranch", company=self.company, state="CA")
        self._seed(sibling, title="Sibling's", tags=["Walnut North"])
        other_company = Company.objects.create(name="Other Search Farm")
        foreign = Establishment.objects.create(name="Foreign Ranch", company=other_company, state="CA")
        self._seed(foreign, title="Foreign", tags=["Walnut North"], source_kind="invoice", source="dossier")
        self.assertEqual(self._titles("walnut north"), ["Ours"])
        self.assertEqual(self._titles("dossier"), [])
        self.assertEqual(self._titles("invoice"), [])


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
