"""A stranger can record a scan, not delete or annotate somebody else's.

`PublicHistoryScanViewSet` subclassed `ModelViewSet` with `permission_classes = [AllowAny]` and a
queryset of every scan, so the router published list/retrieve/update/destroy too, although the
class only ever meant to define `create` and its actions. An anonymous
`DELETE /api/public_scans/<int>/` removed any farm's scan, and `comment` wrote text onto any farm's
scan by integer id, which then showed on that farm's dashboard. Found by the 2026-10-20 route
inventory (`backend/route_tenancy.py`); reproduced here before the fix.

`comment` was then authorised the way `consent` is, by the scan's `claim_token`. On 2026-11-13 it
was REMOVED: no surface has a comment input, and the app's two writers had zero call sites
(trazo-app #383). The route now answers like any other path that does not exist, with or without a
valid token.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import HistoryScan, Production
from product.models import Parcel


class PublicScansScopedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        company = Company.objects.create(name="Victim Farms")
        parcel = Parcel.objects.create(
            name="Victim Parcel", establishment=Establishment.objects.create(name="Farm", company=company), area=1
        )
        cls.season = Production.objects.create(name="Victim 2026", parcel=parcel, published=True)

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

    def test_nobody_can_write_a_comment_onto_a_scan(self):
        """Not a stranger, and not the browser holding the scan's own claim_token either."""
        for token in (None, self.scan.claim_token):
            with self.subTest(with_own_token=token is not None):
                body = {"comment": "PWNED"} | ({"claim_token": token} if token else {})
                response = self.client.post(f"/api/public_scans/{self.scan.id}/comment/", body, format="json")
                self.assertIn(response.status_code, (404, 405), response.content[:300])
        self.scan.refresh_from_db()
        self.assertFalse(self.scan.comment)

    def test_the_scan_itself_still_records(self):
        """The control: removing comment left the shopper scan route alive."""
        response = self.client.post("/api/public_scans/", {"production_id": str(self.season.public_id)}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
