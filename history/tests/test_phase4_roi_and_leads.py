"""
Phase 4 tests — farmer ROI aggregates + buyer documentation requests.

ROI summary (AnalyticsService.get_roi_summary / GET /public_scans/roi_summary/):
scan trend 30d vs prior 30d, engagement rate, reviews, certification views.
Quality filter must match the dashboard (no duplicates, no likely bots).

BuyerDocRequest (POST /buyer_doc_requests/): public lead capture from the
proof view — dedup, notification to company admins, owner-only lead list.
"""

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import Certification
from company.models import Company, Establishment
from history.models import BuyerDocRequest, History, HistoryScan
from history.services.analytics_service import AnalyticsService
from notifications.models import Notification
from product.models import Parcel, Product
from reviews.models import Review
from users.models import User, WorksIn

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner = User.objects.create_user(email="owner@roi.test", password="x")
        self.company = Company.objects.create(name="ROI Farm Co")
        self.establishment = Establishment.objects.create(name="ROI Est", company=self.company)
        WorksIn.objects.create(user=self.owner, company=self.company, role="CA")
        self.parcel = Parcel.objects.create(name="RP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="ROI Production",
            start_date=timezone.now() - timedelta(days=90),
            finish_date=timezone.now() - timedelta(days=5),
            product=self.product,
            parcel=self.parcel,
            operator=self.owner,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _scan(self, days_ago=1, engagement=0.6, bot=0.1, duplicate=False):
        scan = HistoryScan.objects.create(
            history=self.history,
            engagement_score=engagement,
            bot_score=bot,
            is_duplicate=duplicate,
            consent_given=True,
        )
        # auto_now_add fights explicit dates — set after create.
        HistoryScan.objects.filter(id=scan.id).update(date=timezone.now() - timedelta(days=days_ago))
        return scan


class RoiSummaryServiceTests(_Base):
    def test_counts_and_trend(self):
        for _ in range(4):
            self._scan(days_ago=5)
        for _ in range(2):
            self._scan(days_ago=40)
        summary = AnalyticsService.get_roi_summary(self.establishment.id)
        self.assertEqual(summary["scans_30d"], 4)
        self.assertEqual(summary["scans_prev_30d"], 2)
        self.assertEqual(summary["mom_change_pct"], 100.0)
        self.assertEqual(summary["total_scans_all_time"], 6)

    def test_no_baseline_gives_null_trend(self):
        self._scan(days_ago=3)
        summary = AnalyticsService.get_roi_summary(self.establishment.id)
        self.assertIsNone(summary["mom_change_pct"])

    def test_quality_filter_excludes_bots_and_duplicates(self):
        self._scan(days_ago=2)
        self._scan(days_ago=2, bot=0.9)
        self._scan(days_ago=2, duplicate=True)
        summary = AnalyticsService.get_roi_summary(self.establishment.id)
        self.assertEqual(summary["scans_30d"], 1)

    def test_engaged_rate(self):
        self._scan(days_ago=1, engagement=0.8)
        self._scan(days_ago=1, engagement=0.1)
        summary = AnalyticsService.get_roi_summary(self.establishment.id)
        self.assertEqual(summary["engaged_rate_pct"], 50.0)

    def test_reviews_aggregates(self):
        Review.objects.create(headline="Great", written_review="Tasty", rating=5, production=self.history)
        Review.objects.create(headline="Good", written_review="Nice", rating=4, production=self.history)
        summary = AnalyticsService.get_roi_summary(self.establishment.id)
        self.assertEqual(summary["reviews_count"], 2)
        self.assertEqual(summary["average_rating"], 4.5)

    def test_certification_views_require_verified_cert(self):
        self._scan(days_ago=1)
        summary = AnalyticsService.get_roi_summary(self.establishment.id)
        self.assertFalse(summary["has_verified_certification"])
        self.assertEqual(summary["certification_views_30d"], 0)

        cache.clear()
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="CCOF",
            verification_status="verified",
            expiry_date=(timezone.now() + timedelta(days=100)).date(),
        )
        summary = AnalyticsService.get_roi_summary(self.establishment.id)
        self.assertTrue(summary["has_verified_certification"])
        self.assertEqual(summary["certification_views_30d"], 1)


class RoiSummaryEndpointTests(_Base):
    def test_requires_auth(self):
        resp = self.client.get(f"/api/public_scans/roi_summary/?establishment_id={self.establishment.id}")
        self.assertIn(resp.status_code, (401, 403))

    def test_owner_gets_summary(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/public_scans/roi_summary/?establishment_id={self.establishment.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("scans_30d", resp.json())

    def test_outsider_denied(self):
        outsider = User.objects.create_user(email="outsider@roi.test", password="x")
        self.client.force_authenticate(outsider)
        resp = self.client.get(f"/api/public_scans/roi_summary/?establishment_id={self.establishment.id}")
        self.assertEqual(resp.status_code, 403)


class BuyerDocRequestTests(_Base):
    def _payload(self, **overrides):
        payload = {
            "production_id": str(self.history.public_id),
            "requester_name": "Dana Buyer",
            "requester_email": "dana@retailer.com",
            "organization": "Sprouts",
            "message": "Please send your organic certificate and latest audit packet.",
        }
        payload.update(overrides)
        return payload

    def test_public_create(self):
        resp = self.client.post("/api/buyer_doc_requests/", self._payload(), format="json", HTTP_USER_AGENT=UA)
        self.assertEqual(resp.status_code, 201)
        self.assertFalse(resp.json()["duplicate"])
        lead = BuyerDocRequest.objects.get()
        self.assertEqual(lead.production, self.history)
        self.assertEqual(lead.requester_email, "dana@retailer.com")
        self.assertEqual(lead.status, "new")

    def test_create_notifies_company_admin(self):
        self.client.post("/api/buyer_doc_requests/", self._payload(), format="json", HTTP_USER_AGENT=UA)
        notes = Notification.objects.filter(recipient=self.owner, title="Buyer documentation request")
        self.assertEqual(notes.count(), 1)
        self.assertEqual(notes.first().extra_data.get("buyer_email"), "dana@retailer.com")

    def test_duplicate_within_24h_is_idempotent(self):
        self.client.post("/api/buyer_doc_requests/", self._payload(), format="json", HTTP_USER_AGENT=UA)
        resp = self.client.post("/api/buyer_doc_requests/", self._payload(), format="json", HTTP_USER_AGENT=UA)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["duplicate"])
        self.assertEqual(BuyerDocRequest.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(title="Buyer documentation request").count(), 1)

    def test_unpublished_production_rejected(self):
        History.objects.filter(id=self.history.id).update(published=False)
        resp = self.client.post("/api/buyer_doc_requests/", self._payload(), format="json", HTTP_USER_AGENT=UA)
        self.assertEqual(resp.status_code, 404)

    def test_missing_production_id(self):
        payload = self._payload()
        payload.pop("production_id")
        resp = self.client.post("/api/buyer_doc_requests/", payload, format="json", HTTP_USER_AGENT=UA)
        self.assertEqual(resp.status_code, 400)

    def test_invalid_email_rejected(self):
        resp = self.client.post(
            "/api/buyer_doc_requests/", self._payload(requester_email="nope"), format="json", HTTP_USER_AGENT=UA
        )
        self.assertEqual(resp.status_code, 400)

    def test_list_requires_owner(self):
        self.client.post("/api/buyer_doc_requests/", self._payload(), format="json", HTTP_USER_AGENT=UA)

        resp = self.client.get(f"/api/buyer_doc_requests/?establishment_id={self.establishment.id}")
        self.assertIn(resp.status_code, (401, 403))

        outsider = User.objects.create_user(email="other@roi.test", password="x")
        self.client.force_authenticate(outsider)
        resp = self.client.get(f"/api/buyer_doc_requests/?establishment_id={self.establishment.id}")
        self.assertEqual(resp.status_code, 403)

        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/buyer_doc_requests/?establishment_id={self.establishment.id}")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["requester_email"], "dana@retailer.com")
        self.assertEqual(rows[0]["production_public_id"], str(self.history.public_id))

    def test_status_update_owner_only(self):
        self.client.post("/api/buyer_doc_requests/", self._payload(), format="json", HTTP_USER_AGENT=UA)
        lead = BuyerDocRequest.objects.get()

        outsider = User.objects.create_user(email="other2@roi.test", password="x")
        self.client.force_authenticate(outsider)
        resp = self.client.patch(f"/api/buyer_doc_requests/{lead.id}/", {"status": "contacted"}, format="json")
        self.assertEqual(resp.status_code, 403)

        self.client.force_authenticate(self.owner)
        resp = self.client.patch(f"/api/buyer_doc_requests/{lead.id}/", {"status": "contacted"}, format="json")
        self.assertEqual(resp.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.status, "contacted")

        resp = self.client.patch(f"/api/buyer_doc_requests/{lead.id}/", {"status": "bogus"}, format="json")
        self.assertEqual(resp.status_code, 400)
