"""A review link's hourly ceiling holds without a cache.

Every DRF throttle on the anonymous review routes counts in the cache, and production's cache
is DummyCache while REDIS_URL is unset (system check security.W001), so those throttles never
refuse anything there. Found while preparing the certifier handoff rehearsal (2026-10-17): with
a valid link, metadata, readiness and dossier requests were unlimited.

The ceiling here counts the link's own `CertifierAccessLog` rows, which every served request
already writes. These tests run with DummyCache on purpose: that is the production condition.
"""

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from certifications.models import CertifierAccessLink, CertifierAccessLog
from company.models import Company, Establishment
from documents.models import ExportJob

DUMMY_CACHE = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
SMALL = {"metadata": 3, "readiness": 3, "dossier": 2}


@override_settings(CACHES=DUMMY_CACHE, CERTIFIER_REVIEW_LINK_HOURLY_LIMITS=SMALL)
class ReviewLinkHourlyLimitTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Limit Co")
        self.establishment = Establishment.objects.create(name="Limit Farm", company=self.company, state="WA")
        self.link = self._link()

    def _link(self, audience="certifier"):
        return CertifierAccessLink.objects.create(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            label="Limit",
            audience=audience,
            expires_at=timezone.now() + timedelta(days=30),
        )

    def _seed(self, link, action, count, minutes_ago=5):
        """Served requests already on file, `minutes_ago` back (auto_now_add is set on create)."""
        rows = [CertifierAccessLog.objects.create(link=link, action=action) for _ in range(count)]
        CertifierAccessLog.objects.filter(pk__in=[r.pk for r in rows]).update(
            accessed_at=timezone.now() - timedelta(minutes=minutes_ago)
        )

    def _get(self, name, token):
        return self.client.get(reverse(name, args=[token]))

    def test_metadata_is_refused_once_the_hour_is_spent_with_no_cache(self):
        for _ in range(3):
            self.assertEqual(self._get("certifier_review_metadata", self.link.token).status_code, 200)
        response = self._get("certifier_review_metadata", self.link.token)
        self.assertEqual(response.status_code, 429)
        self.assertTrue(1 <= int(response["Retry-After"]) <= 3600)

    def test_a_refusal_writes_no_access_row(self):
        self._seed(self.link, "metadata", 3)
        self.assertEqual(self._get("certifier_review_metadata", self.link.token).status_code, 429)
        self.assertEqual(self.link.accesses.filter(action="metadata").count(), 3)

    def test_retry_after_counts_from_the_oldest_row_in_the_window(self):
        self._seed(self.link, "metadata", 3, minutes_ago=50)
        response = self._get("certifier_review_metadata", self.link.token)
        self.assertEqual(response.status_code, 429)
        # The oldest row leaves the window in about 10 minutes.
        self.assertTrue(540 <= int(response["Retry-After"]) <= 610, response["Retry-After"])

    def test_rows_older_than_an_hour_do_not_count(self):
        self._seed(self.link, "metadata", 3, minutes_ago=61)
        self.assertEqual(self._get("certifier_review_metadata", self.link.token).status_code, 200)

    def test_the_ceiling_is_per_link(self):
        self._seed(self.link, "metadata", 3)
        other = self._link()
        self.assertEqual(self._get("certifier_review_metadata", self.link.token).status_code, 429)
        self.assertEqual(self._get("certifier_review_metadata", other.token).status_code, 200)

    def test_each_action_has_its_own_allowance(self):
        self._seed(self.link, "metadata", 3)
        self.assertEqual(self._get("certifier_review_metadata", self.link.token).status_code, 429)
        self.assertNotEqual(self._get("certifier_review_readiness", self.link.token).status_code, 429)

    def test_readiness_is_refused_once_the_hour_is_spent(self):
        self._seed(self.link, "readiness", 3)
        with mock.patch(
            "history.services.operation_audit_export_service.OperationAuditExportService.readiness_rows_for_certifier",
            side_effect=AssertionError("readiness rows built past the hourly ceiling"),
        ) as rows:
            response = self._get("certifier_review_readiness", self.link.token)
        self.assertEqual(response.status_code, 429)
        rows.assert_not_called()

    def test_a_spent_dossier_allowance_starts_no_build_and_streams_nothing(self):
        self._seed(self.link, "dossier", 2)
        # Raising mocks: past the ceiling they must never be reached. (A plain MagicMock would
        # stream itself forever as a "file" if the ceiling were missing.)
        reached = AssertionError("dossier work started past the hourly ceiling")
        with (
            mock.patch("documents.services.export_jobs.fresh_document", side_effect=reached) as fresh,
            mock.patch("documents.services.export_jobs.enqueue", side_effect=reached) as enqueue,
        ):
            response = self._get("certifier_review_dossier", self.link.token)
            with_job = self.client.get(
                reverse("certifier_review_dossier", args=[self.link.token]),
                {"job": "00000000-0000-0000-0000-000000000000"},
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(with_job.status_code, 429)
        fresh.assert_not_called()
        enqueue.assert_not_called()
        self.assertFalse(ExportJob.objects.filter(establishment=self.establishment).exists())

    def test_the_buyer_landing_route_has_the_same_ceiling(self):
        buyer = self._link(audience="buyer")
        self._seed(buyer, "metadata", 3)
        self.assertEqual(self._get("buyer_review_metadata", buyer.token).status_code, 429)

    def test_an_inactive_link_is_still_404_before_any_count(self):
        """The limit never tells an anonymous caller that a dead token was once real."""
        self._seed(self.link, "metadata", 3)
        self.link.revoke()
        self.assertEqual(self._get("certifier_review_metadata", self.link.token).status_code, 404)


class ReviewLinkHourlyLimitSettingTests(TestCase):
    def test_every_review_action_that_writes_a_row_has_a_ceiling(self):
        from django.conf import settings

        limits = settings.CERTIFIER_REVIEW_LINK_HOURLY_LIMITS
        for action in ("metadata", "readiness", "dossier"):
            self.assertGreater(limits.get(action, 0), 0, action)
