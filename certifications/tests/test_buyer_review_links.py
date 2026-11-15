"""Buyer review links — the in-season, non-public, claim-safe surface (2026-08-25).

"Your buyer" is two different people. The QR page serves the shopper after
harvest; the wholesale procurement buyer decides BEFORE it, and what they need
is the record so far. This suite pins the three load-bearing properties:

- AUDIENCE ISOLATION. One model, two disjoint content classes. A buyer token on
  any certifier endpoint (metadata/readiness/dossier — the surface with supplier
  invoices, prices, applicator names) is a 404, and vice versa. Cross-audience
  use must read as "no such link", never as a downgrade.
- CLAIM-SAFE BY CONSTRUCTION. The buyer token changes WHICH productions resolve
  on the public endpoints (adds this one establishment's unpublished seasons),
  never WHAT a production shows: the payload is the same PublicHistorySerializer
  the shopper page uses, so the withheld subtypes stay withheld.
- DILIGENCE IS NOT ENGAGEMENT. A buyer open is logged to the link's access log
  (the farmer can see it) and must NOT create a HistoryScan or fire scan
  notifications.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import CertifierAccessLink, CertifierAccessLog
from company.models import Company, Establishment
from history.models import HistoryScan, Production, ProductionEvent
from product.models import Parcel, Product


def _mk_link(establishment, audience, **extra):
    return CertifierAccessLink.objects.create(
        establishment=establishment,
        token=CertifierAccessLink.generate_token(),
        audience=audience,
        expires_at=timezone.now() + timedelta(days=30),
        **extra,
    )


class BuyerReviewLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Buyer Farm Co")
        cls.establishment = Establishment.objects.create(name="Main", company=cls.company, state="WA")
        cls.parcel = Parcel.objects.create(name="P1", establishment=cls.establishment, area=5.0)
        # UNPUBLISHED, in-season: the whole point of the buyer surface.
        cls.history = Production.objects.create(
            name="In-season 2026",
            start_date=timezone.now(),
            product=Product.objects.create(name="Apple"),
            parcel=cls.parcel,
            published=False,
        )
        ProductionEvent.objects.create(history=cls.history, type="HA", description="First pick", date=timezone.now())
        # A withheld-subtype record: must never reach the buyer payload.
        ProductionEvent.objects.create(history=cls.history, type="SS", description="Seed search", date=timezone.now())
        cls.buyer_link = _mk_link(cls.establishment, "buyer", label="June diligence")
        cls.certifier_link = _mk_link(cls.establishment, "certifier", label="CCOF 2026")

        other_company = Company.objects.create(name="Other Co")
        other_est = Establishment.objects.create(name="Elsewhere", company=other_company)
        cls.foreign_buyer_link = _mk_link(other_est, "buyer")

    # -- audience isolation ------------------------------------------------

    def test_buyer_token_is_404_on_every_certifier_endpoint(self):
        client = APIClient()
        for path in ("", "readiness/", "dossier/"):
            url = f"/api/certifier-review/{self.buyer_link.token}/{path}"
            self.assertEqual(client.get(url).status_code, 404, url)

    def test_certifier_token_is_404_on_the_buyer_endpoint(self):
        url = f"/api/buyer-review/{self.certifier_link.token}/"
        self.assertEqual(APIClient().get(url).status_code, 404)

    # -- buyer metadata ----------------------------------------------------

    def test_buyer_metadata_lists_the_unpublished_open_season(self):
        url = f"/api/buyer-review/{self.buyer_link.token}/"
        response = APIClient().get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["operation_name"], "Main")
        self.assertEqual(len(data["seasons"]), 1)
        season = data["seasons"][0]
        self.assertEqual(season["public_id"], str(self.history.public_id))
        self.assertTrue(season["in_progress"])
        self.assertFalse(season["published"])
        # Never the internal integer id, never the token echoed back.
        self.assertNotIn("id", season)
        self.assertNotIn("token", data)

    def test_buyer_metadata_open_is_logged(self):
        url = f"/api/buyer-review/{self.buyer_link.token}/"
        APIClient().get(url)
        self.assertTrue(CertifierAccessLog.objects.filter(link=self.buyer_link, action="metadata").exists())

    def test_revoked_buyer_link_is_404(self):
        link = _mk_link(self.establishment, "buyer")
        link.revoke()
        url = f"/api/buyer-review/{link.token}/"
        self.assertEqual(APIClient().get(url).status_code, 404)

    # -- the public endpoints with review_token ----------------------------

    def _public_url(self, token=None):
        url = f"/api/productions/{self.history.public_id}/public_history/"
        return f"{url}?review_token={token}" if token else url

    def test_unpublished_production_is_404_without_a_token(self):
        self.assertEqual(APIClient().get(self._public_url()).status_code, 404)

    def test_buyer_token_opens_the_unpublished_production_claim_safe(self):
        response = APIClient().get(self._public_url(self.buyer_link.token))
        self.assertEqual(response.status_code, 200)
        events = response.json().get("events") or []
        subtypes = {
            e.get("production_type") or e.get("type")
            for e in events
            if isinstance(e, dict) and e.get("event_type") == 1
        }
        self.assertIn("HA", subtypes, "ordinary field activity must reach the buyer")
        self.assertNotIn(
            "SS",
            subtypes,
            "withheld subtype leaked: the buyer surface must be the SAME claim-safe "
            "class as the shopper page, not the certifier dossier",
        )

    def test_buyer_open_logs_to_the_link_not_as_a_scan(self):
        before_scans = HistoryScan.objects.count()
        APIClient().get(self._public_url(self.buyer_link.token))
        self.assertEqual(HistoryScan.objects.count(), before_scans, "diligence open counted as a consumer scan")
        self.assertTrue(CertifierAccessLog.objects.filter(link=self.buyer_link, action="production").exists())

    def test_certifier_token_does_not_open_the_public_surface(self):
        response = APIClient().get(self._public_url(self.certifier_link.token))
        self.assertEqual(response.status_code, 404)

    def test_foreign_establishment_buyer_token_does_not_open_it(self):
        response = APIClient().get(self._public_url(self.foreign_buyer_link.token))
        self.assertEqual(response.status_code, 404)

    def test_revoked_buyer_token_does_not_open_it(self):
        link = _mk_link(self.establishment, "buyer")
        link.revoke()
        response = APIClient().get(self._public_url(link.token))
        self.assertEqual(response.status_code, 404)

    def test_transparency_detail_honours_the_buyer_token(self):
        base = f"/api/transparency/{self.history.public_id}/"
        self.assertEqual(APIClient().get(base).status_code, 404)
        with_token = f"{base}?review_token={self.buyer_link.token}"
        self.assertEqual(APIClient().get(with_token).status_code, 200)
        # The consumer page fetches THIS endpoint, not public_history — caught in
        # the live E2E: the open rendered but the farmer's access log stayed empty.
        self.assertTrue(
            CertifierAccessLog.objects.filter(link=self.buyer_link, action="production").exists(),
            "buyer open via the transparency endpoint must reach the link's access log",
        )

    # -- minting -----------------------------------------------------------

    def test_buyer_link_mints_without_certifier_readiness(self):
        """The readiness blocker is a certifier-submission gate; a buyer link is
        minted mid-season, exactly when readiness is incomplete. This operation
        has no OFPP/OSP at all — a certifier link refuses, a buyer link mints."""
        from unittest.mock import patch

        from subscriptions.testing import grant_compliance_exports
        from users.models import User, WorksIn

        grant_compliance_exports(self.company)
        owner = User.objects.create_user(email="owner@buyerfarm.test", password="x")
        WorksIn.objects.create(user=owner, company=self.company, role=WorksIn.COMPANY_ADMIN)
        client = APIClient()
        client.force_authenticate(user=owner)
        url = f"/api/companies/{self.company.id}/establishments/" f"{self.establishment.id}/certifier-links/"
        # Pin the BRANCH, not the fixture: with readiness hard-refusing, the
        # certifier mint must 400 and the buyer mint must still succeed.
        with patch(
            "history.services.operation_readiness_service.OperationReadinessService.evaluate",
            return_value={"ready": False, "blockers": ["no OSP"]},
        ):
            refused = client.post(url, {"audience": "certifier", "label": "too early"}, format="json")
            self.assertEqual(refused.status_code, 400, refused.content)
            self.assertIn("readiness", refused.json())

            minted = client.post(url, {"audience": "buyer", "label": "June diligence"}, format="json")
            self.assertEqual(minted.status_code, 201, minted.content)
            self.assertEqual(minted.json()["audience"], "buyer")
