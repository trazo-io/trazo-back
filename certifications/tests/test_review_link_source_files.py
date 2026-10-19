"""Source files through a certifier review link (handoff rehearsal 2026-10-18, H-3).

The recipient could see in the dossier's index that invoice ASTRA-INV-2605-01 existed and could
not open it. Oscar chose: the grower opts in PER LINK when creating it; with that set, every
upload the index lists can be opened through the link while it is active, streamed through the
token route (so revoke and expiry end access at once), logged per open, under the per-link hourly
ceiling. Without it, nothing changes: the index only.
"""

from datetime import timedelta

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from certifications.models import CertifierAccessLink, CertifierAccessLog
from certifications.serializers import CertifierAccessLinkSerializer
from company.models import Company, Establishment
from documents.services.filing import file_document

DUMMY_CACHE = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}


@override_settings(CACHES=DUMMY_CACHE)
class ReviewLinkSourceFilesTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Files Co")
        self.est = Establishment.objects.create(name="Test Block", company=self.company, state="WA")
        self.invoice = self._upload(self.est, "ASTRA TEST invoice ASTRA-INV-2605-01", b"%PDF-1.4 invoice")
        other = Establishment.objects.create(
            name="Other Farm", company=Company.objects.create(name="Other Co"), state="WA"
        )
        self.foreign = self._upload(other, "Someone else's invoice", b"%PDF-1.4 other")

    def _upload(self, est, title, content):
        return file_document(
            establishment=est,
            source="upload",
            folder="uploads",
            title=title,
            filename="invoice.pdf",
            content=ContentFile(content).read(),
        )

    def _link(self, **kwargs):
        defaults = dict(
            establishment=self.est,
            token=CertifierAccessLink.generate_token(),
            label="Rehearsal",
            audience="certifier",
            expires_at=timezone.now() + timedelta(days=30),
        )
        defaults.update(kwargs)
        return CertifierAccessLink.objects.create(**defaults)

    def _list(self, link):
        return self.client.get(reverse("certifier_review_documents", args=[link.token]))

    def _open(self, link, doc):
        return self.client.get(reverse("certifier_review_document_file", args=[link.token, str(doc.public_id)]))

    # ---- default: nothing changes ----

    def test_without_the_opt_in_the_page_says_so_and_no_file_opens(self):
        link = self._link()
        res = self._list(link)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"enabled": False, "documents": []})
        self.assertEqual(self._open(link, self.invoice).status_code, 404)
        self.assertFalse(CertifierAccessLog.objects.filter(action="document").exists())

    # ---- opted in ----

    def test_with_the_opt_in_the_operations_uploads_are_listed(self):
        link = self._link(include_source_files=True)
        body = self._list(link).json()
        self.assertTrue(body["enabled"])
        titles = [d["title"] for d in body["documents"]]
        self.assertEqual(titles, ["ASTRA TEST invoice ASTRA-INV-2605-01"])
        self.assertEqual(body["documents"][0]["id"], str(self.invoice.public_id))

    def test_a_file_opens_through_the_link_and_is_logged_with_its_title(self):
        link = self._link(include_source_files=True)
        res = self._open(link, self.invoice)
        self.assertEqual(res.status_code, 200)
        self.assertIn("attachment", res["Content-Disposition"])
        self.assertEqual(b"".join(res.streaming_content), b"%PDF-1.4 invoice")
        log = CertifierAccessLog.objects.get(link=link, action="document")
        self.assertEqual(log.document, self.invoice)
        data = CertifierAccessLinkSerializer(link).data
        self.assertEqual(data["accesses"][0]["document_title"], "ASTRA TEST invoice ASTRA-INV-2605-01")

    def test_another_farms_file_is_not_reachable_through_this_link(self):
        link = self._link(include_source_files=True)
        self.assertEqual(self._open(link, self.foreign).status_code, 404)
        self.assertNotIn("Someone else's invoice", str(self._list(link).json()))

    def test_a_generated_document_is_not_a_source_file(self):
        generated = file_document(
            establishment=self.est,
            source="export",
            folder="exports",
            title="Audit dossier",
            filename="dossier.pdf",
            content=b"%PDF-1.4 dossier",
        )
        link = self._link(include_source_files=True)
        self.assertEqual(self._open(link, generated).status_code, 404)

    def test_a_malformed_id_is_a_404(self):
        link = self._link(include_source_files=True)
        res = self.client.get(reverse("certifier_review_document_file", args=[link.token, "not-a-uuid"]))
        self.assertEqual(res.status_code, 404)

    # ---- the link's own controls ----

    def test_revoking_the_link_ends_access_to_the_files(self):
        link = self._link(include_source_files=True)
        self.assertEqual(self._open(link, self.invoice).status_code, 200)
        link.revoke()
        self.assertEqual(self._open(link, self.invoice).status_code, 404)
        self.assertEqual(self._list(link).status_code, 404)

    def test_an_expired_link_opens_no_file(self):
        link = self._link(include_source_files=True, expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self._open(link, self.invoice).status_code, 404)

    def test_a_buyer_token_opens_no_file(self):
        link = self._link(audience="buyer", include_source_files=True)
        self.assertEqual(self._open(link, self.invoice).status_code, 404)
        self.assertEqual(self._list(link).status_code, 404)

    # ---- review of back #183 ----

    def test_a_profile_without_the_document_index_opens_no_file(self):
        link = self._link(include_source_files=True, certification_type="fsma204")
        self.assertEqual(self._list(link).json()["documents"], [])
        self.assertEqual(self._open(link, self.invoice).status_code, 404)

    def test_the_download_header_is_escaped_by_django(self):
        quoted = file_document(
            establishment=self.est,
            source="upload",
            folder="uploads",
            title="Odd name",
            filename='fact"ura año.pdf',
            content=b"%PDF-1.4 odd",
        )
        link = self._link(include_source_files=True)
        res = self._open(link, quoted)
        self.assertEqual(res.status_code, 200)
        header = res["Content-Disposition"]
        self.assertTrue(header.startswith("attachment"))
        self.assertNotIn('fact"ura', header)
        # Local storage strips the quote from the stored name, so the non-ASCII half is what this
        # environment can exercise: Django encodes it (RFC 5987); a hand-written header did not.
        self.assertIn("filename*=utf-8''", header)

    def test_a_file_missing_from_storage_is_a_503_and_logs_nothing(self):
        link = self._link(include_source_files=True)
        self.invoice.file.storage.delete(self.invoice.file.name)
        res = self._open(link, self.invoice)
        self.assertEqual(res.status_code, 503)
        self.assertFalse(CertifierAccessLog.objects.filter(link=link, action="document").exists())

    @override_settings(CERTIFIER_REVIEW_LINK_HOURLY_LIMITS={"document": 2})
    def test_the_hourly_ceiling_applies_to_file_opens(self):
        link = self._link(include_source_files=True)
        self.assertEqual(self._open(link, self.invoice).status_code, 200)
        self.assertEqual(self._open(link, self.invoice).status_code, 200)
        res = self._open(link, self.invoice)
        self.assertEqual(res.status_code, 429)
        self.assertEqual(CertifierAccessLog.objects.filter(link=link, action="document").count(), 2)


class SourceFilesConsentTests(TestCase):
    def setUp(self):
        self.est = Establishment.objects.create(name="E", company=Company.objects.create(name="C"))

    def _serializer(self, **data):
        return CertifierAccessLinkSerializer(data={"label": "x", "audience": "certifier", **data})

    def test_off_unless_the_grower_ticks_it(self):
        s = self._serializer()
        self.assertTrue(s.is_valid(), s.errors)
        link = s.save(establishment=self.est, token=CertifierAccessLink.generate_token())
        self.assertFalse(link.include_source_files)

    def test_ticked_at_creation_it_is_stored(self):
        s = self._serializer(include_source_files=True)
        self.assertTrue(s.is_valid(), s.errors)
        link = s.save(establishment=self.est, token=CertifierAccessLink.generate_token())
        self.assertTrue(link.include_source_files)

    def test_a_profile_without_the_document_index_cannot_share_files(self):
        s = self._serializer(include_source_files=True, certification_type="fsma204")
        self.assertFalse(s.is_valid())
        self.assertIn("include_source_files", s.errors)

    def test_a_buyer_link_cannot_share_source_files(self):
        s = self._serializer(audience="buyer", include_source_files=True)
        self.assertFalse(s.is_valid())
        self.assertIn("include_source_files", s.errors)
