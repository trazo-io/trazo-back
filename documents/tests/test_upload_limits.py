"""What the DMS upload endpoint refuses, and why each refusal exists.

Before these guards the endpoint accepted any file of any size and read all of it into
memory (`content=f.read()`) before a byte reached storage. Neither Django setting that
looks like a size cap actually is one: `DATA_UPLOAD_MAX_MEMORY_SIZE` is enforced only in
the `item_type == FIELD` branch of `django/http/multipartparser.py` — the FILE branch has
no ceiling — and `FILE_UPLOAD_MAX_MEMORY_SIZE` only picks memory-vs-tempfile. A
per-endpoint limit was the only thing that could bound it, and there wasn't one.

The size test asserts against `settings.DOCUMENT_UPLOAD_MAX_BYTES` rather than a literal
so it keeps testing the policy, not a number that was true the day it was written.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from rest_framework.test import APIClient

from company.models import Company, Establishment
from documents.models import GeneratedDocument
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn


class DocumentUploadLimitTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Upload Limits Farm")
        self.user = User.objects.create_user(email="limits@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Limits Ranch", company=self.company, state="CA")
        # The endpoint now requires storage entitlement, which requires a subscription.
        grant_compliance_exports(self.company)
        self.client.force_authenticate(user=self.user)

    def _url(self):
        return f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/documents/"

    @override_settings(DOCUMENT_UPLOAD_MAX_BYTES=1024)
    def test_oversized_file_is_refused(self):
        big = SimpleUploadedFile("scan.pdf", b"x" * 4096, content_type="application/pdf")
        r = self.client.post(self._url(), {"file": big, "folder": "uploads"})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("file", r.json())
        self.assertEqual(GeneratedDocument.objects.filter(establishment=self.establishment).count(), 0)

    def test_disallowed_extension_is_refused(self):
        payload = SimpleUploadedFile("payload.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        r = self.client.post(self._url(), {"file": payload, "folder": "uploads"})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(GeneratedDocument.objects.filter(establishment=self.establishment).count(), 0)

    def test_spoofed_content_type_does_not_get_a_file_past_the_extension_gate(self):
        """The declared Content-Type is client-controlled, so it cannot be the gate."""
        payload = SimpleUploadedFile("payload.sh", b"#!/bin/sh\n", content_type="application/pdf")
        r = self.client.post(self._url(), {"file": payload, "folder": "uploads"})
        self.assertEqual(r.status_code, 400, r.content)

    def test_allowed_document_is_stored_with_its_real_size(self):
        body = b"%PDF-1.7 certificate body"
        f = SimpleUploadedFile("organic-certificate.pdf", body, content_type="application/pdf")
        r = self.client.post(self._url(), {"file": f, "title": "Organic certificate", "folder": "certifications"})
        self.assertEqual(r.status_code, 201, r.content)

        doc = GeneratedDocument.objects.get(pk=r.json()["id"])
        # Streamed rather than `.read()` into memory — the size still has to be exact, since
        # it is what the storage meter sums.
        self.assertEqual(doc.size_bytes, len(body))
        self.assertEqual(doc.folder, "certifications")
        with doc.file.open("rb") as fh:
            self.assertEqual(fh.read(), body)

    def test_every_allowed_extension_is_lowercase_and_dotted(self):
        """A stray 'PDF' or 'pdf' in the allowlist would silently reject that whole type,
        because the gate lowercases the extension and compares including the dot."""
        from documents.serializers import ALLOWED_DOCUMENT_EXTENSIONS

        self.assertTrue(ALLOWED_DOCUMENT_EXTENSIONS)
        for ext in ALLOWED_DOCUMENT_EXTENSIONS:
            self.assertTrue(ext.startswith("."), ext)
            self.assertEqual(ext, ext.lower(), ext)


class DocumentUploadRequiresSubscriptionTests(TestCase):
    """Documents are never refused for being over quota — but they are refused with no plan.

    `check_storage_quota` is called with `CATEGORY_DOCUMENTS`, which skips the ceiling
    entirely. What it still catches is the case that has nothing to do with how full the
    farm is: a company with no active subscription has no storage at all.
    """

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="No Plan Farm")
        self.user = User.objects.create_user(email="noplan@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="No Plan Ranch", company=self.company, state="CA")
        self.client.force_authenticate(user=self.user)

    def test_upload_without_subscription_is_refused(self):
        f = SimpleUploadedFile("receipt.pdf", b"%PDF", content_type="application/pdf")
        url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/documents/"
        r = self.client.post(url, {"file": f})
        self.assertEqual(r.status_code, 413, r.content)
        self.assertEqual(r.json()["code"], "NO_SUBSCRIPTION")
