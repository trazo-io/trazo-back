"""
Regression: producer must be able to load their OWN unpublished (draft/in-progress)
production; the ProfileProduction page depends on it.

Before the fix, the two "public" endpoints ProfileProduction calls hard-gated on
published=True:
  - GET /api/histories/{id}/public_history/          → 404 for a draft (broke the page)
  - GET /api/carbon/public/productions/{id}/complete/ → 500 (unhandled DoesNotExist)

Fix: authenticated company members may load their own drafts on both endpoints;
anonymous / other-company users stay published-only, and a missing production
returns 404 (never 500).
"""

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User


def _make_production(published):
    company = Company.objects.create(name=f"Draft Farm {'pub' if published else 'draft'}")
    est = Establishment.objects.create(name="F", company=company)
    parcel = Parcel.objects.create(name="P", establishment=est, area=5.0)
    product = Product.objects.create(name="Walnut")
    user = User.objects.create_user(email=f"owner-{'pub' if published else 'draft'}@t.com", password="x")
    user.companies.add(company)
    history = History.objects.create(
        name="Prod",
        start_date=timezone.now(),
        product=product,
        parcel=parcel,
        operator=user,
        earning=0.0,
        production_amount=0.0,
        reputation=0.0,
        confidence_score=0.0,
        transparency_score=0.0,
        public_views=0,
        unique_visitors=0,
        is_outdoor=True,
        published=published,
    )
    return company, user, history


class OwnerDraftAccessRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company, self.owner, self.draft = _make_production(published=False)
        # An unrelated authenticated user (different company).
        self.stranger = User.objects.create_user(email="stranger@t.com", password="x")
        self.other_company = Company.objects.create(name="Other Co")
        self.stranger.companies.add(self.other_company)

    def _public_history_url(self, prod):
        return f"/api/histories/{prod.id}/public_history/"

    def _complete_url(self, prod):
        return f"/api/carbon/public/productions/{prod.id}/complete/"

    # --- public_history ---
    def test_owner_can_load_own_draft_public_history(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(self._public_history_url(self.draft))
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_anonymous_cannot_load_draft_public_history(self):
        resp = self.client.get(self._public_history_url(self.draft))
        self.assertIn(resp.status_code, (400, 404), resp.content)

    def test_stranger_cannot_load_others_draft_public_history(self):
        self.client.force_authenticate(user=self.stranger)
        resp = self.client.get(self._public_history_url(self.draft))
        self.assertIn(resp.status_code, (400, 404), resp.content)

    # --- carbon complete_summary: must be 200 for owner, 404 (never 500) otherwise ---
    def test_owner_can_load_own_draft_complete(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(self._complete_url(self.draft))
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_anonymous_draft_complete_is_not_500(self):
        # Endpoint requires auth → 401 for anonymous. The regression is that it
        # must never be a 500 (previously raised unhandled DoesNotExist).
        resp = self.client.get(self._complete_url(self.draft))
        self.assertIn(resp.status_code, (401, 403, 404), resp.content)
        self.assertNotEqual(resp.status_code, 500, resp.content)

    def test_stranger_draft_complete_is_404_not_500(self):
        self.client.force_authenticate(user=self.stranger)
        resp = self.client.get(self._complete_url(self.draft))
        self.assertEqual(resp.status_code, 404, resp.content)
