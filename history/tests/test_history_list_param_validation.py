"""
GET /api/productions/ query-param validation.

A frontend that stringifies an object sends `?establishment=[object Object]`. Before
2026-08-17 that value went straight into `.filter(parcel__establishment_id=...)`, where
Django's `int()` coercion raised an unhandled ValueError — an HTTP 500 with a full
traceback for what is a malformed request. Garbage in an id-shaped param must be a 400.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User, WorksIn


class HistoryListParamValidationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email="owner@params.test", password="x")
        self.company = Company.objects.create(name="Params Co")
        self.establishment = Establishment.objects.create(name="Params Est", company=self.company)
        WorksIn.objects.create(user=self.owner, company=self.company, role="CA")
        self.parcel = Parcel.objects.create(name="PP1", establishment=self.establishment, area=3.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = History.objects.create(
            name="Params Production",
            start_date=timezone.now() - timedelta(days=30),
            product=self.product,
            parcel=self.parcel,
            operator=self.owner,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        self.client.force_authenticate(user=self.owner)

    def _ids(self, response):
        payload = response.json()
        rows = payload["results"] if isinstance(payload, dict) else payload
        return [row["id"] for row in rows]

    def test_valid_establishment_filter_returns_the_farm_rows(self):
        response = self.client.get(f"/api/productions/?establishment={self.establishment.id}")
        self.assertEqual(response.status_code, 200)
        # Proves the happy path actually READ a row — a 400-only test would pass
        # even if the filter had been deleted outright.
        self.assertIn(self.history.id, self._ids(response))

    def test_stringified_object_establishment_is_a_400_not_a_500(self):
        response = self.client.get("/api/productions/?establishment=[object Object]")
        self.assertEqual(response.status_code, 400)
        self.assertIn("establishment", response.json())

    def test_stringified_object_product_is_a_400_not_a_500(self):
        response = self.client.get("/api/productions/?product=[object Object]")
        self.assertEqual(response.status_code, 400)
        self.assertIn("product", response.json())

    def test_empty_establishment_param_is_ignored(self):
        response = self.client.get("/api/productions/?establishment=")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.history.id, self._ids(response))
