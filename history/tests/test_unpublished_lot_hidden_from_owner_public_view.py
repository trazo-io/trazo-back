"""
An unpublished lot answers 404 on the consumer page for its OWN grower too (2026-10-08).

The auth cookies are scoped to `.trazo.io`, so a grower signed in to app.trazo.io who opens
consumer.trazo.io/production/<uuid> arrives authenticated. The transparency endpoint exempted
owners from `published=True`, so after switching a lot's Public toggle off the grower still saw
the full page and concluded the toggle did nothing.

The consumer page now sends `public_view=1`, which drops the owner exemption. The producer
dashboard (ProfileProduction, FinishProduction) calls the same endpoint WITHOUT the flag and must
keep its preview of in-season and unpublished lots.
"""

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User


class UnpublishedLotPublicViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        company = Company.objects.create(name="Public View Farm")
        est = Establishment.objects.create(name="F", company=company)
        parcel = Parcel.objects.create(name="P", establishment=est, area=5.0)
        product = Product.objects.create(name="Spinach")
        self.owner = User.objects.create_user(email="owner-public-view@t.com", password="x")
        self.owner.companies.add(company)

        def make(published):
            return History.objects.create(
                name=f"Spinach {'pub' if published else 'unpub'}",
                start_date=timezone.now(),
                finish_date=timezone.now(),
                product=product,
                parcel=parcel,
                operator=self.owner,
                earning=0.0,
                production_amount=0.0,
                reputation=0.0,
                confidence_score=0.0,
                public_views=0,
                unique_visitors=0,
                is_outdoor=True,
                published=published,
            )

        self.unpublished = make(published=False)
        self.published = make(published=True)

    def _url(self, history, public_view=False):
        return f"/api/transparency/{history.public_id}/" + ("?public_view=1" if public_view else "")

    def test_owner_public_view_of_unpublished_lot_is_404(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(self._url(self.unpublished, public_view=True))
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_anonymous_unpublished_lot_is_404(self):
        resp = self.client.get(self._url(self.unpublished, public_view=True))
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_owner_dashboard_call_still_previews_unpublished_lot(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(self._url(self.unpublished))
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_owner_public_view_of_published_lot_is_200(self):
        self.client.force_authenticate(user=self.owner)
        resp = self.client.get(self._url(self.published, public_view=True))
        self.assertEqual(resp.status_code, 200, resp.content)
