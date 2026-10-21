"""A stranger can record a scan, not delete or annotate somebody else's.

`PublicHistoryScanViewSet` subclassed `ModelViewSet` with `permission_classes = [AllowAny]` and a
queryset of every scan, so the router published list/retrieve/update/destroy too, although the
class only ever meant to define `create` and its actions. An anonymous
`DELETE /api/public_scans/<int>/` removed any farm's scan, and `comment` wrote text onto any farm's
scan by integer id, which then showed on that farm's dashboard. Found by the 2026-10-20 route
inventory (`backend/route_tenancy.py`); reproduced here before the fix.

`comment` is now authorised the way `consent` already is: by the scan's `claim_token`, the 256-bit
value only the browser that made the scan received. Nothing in the app calls `comment` today
(`useCommentHistoryMutation` has no call sites), so the contract can tighten without a client change.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import History, HistoryScan
from product.models import Parcel


class PublicScansScopedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = Company.objects.create(name="Victim Farms")
        parcel = Parcel.objects.create(
            name="Victim Parcel", establishment=Establishment.objects.create(name="Farm", company=company), area=1
        )
        cls.season = History.objects.create(name="Victim 2026", parcel=parcel, published=True)

    def setUp(self):
        self.scan = HistoryScan.objects.create(history=self.season)
        self.client = APIClient()

    def test_stranger_cannot_delete_read_or_edit_a_scan(self):
        url = f"/api/public_scans/{self.scan.id}/"
        for method in ("delete", "get", "patch", "put"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(url, {"comment": "PWNED"}, format="json")
                self.assertIn(response.status_code, (404, 405), response.content[:300])
        self.assertTrue(HistoryScan.objects.filter(pk=self.scan.pk).exists())
        self.assertIn(self.client.get("/api/public_scans/").status_code, (404, 405))

    def test_comment_without_the_claim_token_is_refused(self):
        response = self.client.post(f"/api/public_scans/{self.scan.id}/comment/", {"comment": "PWNED"}, format="json")
        self.assertIn(response.status_code, (403, 404), response.content[:300])
        self.scan.refresh_from_db()
        self.assertFalse(self.scan.comment)

    def test_comment_with_another_scans_token_is_refused(self):
        other = HistoryScan.objects.create(history=self.season)
        response = self.client.post(
            f"/api/public_scans/{self.scan.id}/comment/",
            {"comment": "PWNED", "claim_token": other.claim_token},
            format="json",
        )
        self.assertIn(response.status_code, (403, 404), response.content[:300])
        self.scan.refresh_from_db()
        self.assertFalse(self.scan.comment)

    def test_comment_with_its_own_claim_token_saves(self):
        """The control: the browser that made the scan can still leave its one comment."""
        response = self.client.post(
            f"/api/public_scans/{self.scan.id}/comment/",
            {"comment": "Tasty", "claim_token": self.scan.claim_token},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.scan.refresh_from_db()
        self.assertEqual(self.scan.comment, "Tasty")
