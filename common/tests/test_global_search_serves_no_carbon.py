"""Global search serves no carbon figure.

Until 2026-09-30 `global_search` set `carbon_score` to `parcel_count * 25.5` ("example
calculation") for every establishment, and a real `carbon_footprint` for parcels, under the same
key. The navbar search printed both as "kg CO₂" beside a leaf, so a farm with four parcels read
"102 kg CO₂" and nobody could tell the invented rows from the real one. Search finds a farm or a
parcel; it carries no carbon number at all.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company, Establishment
from product.models import Parcel
from users.models import User, WorksIn


class GlobalSearchCarbonTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="search@test.com", password="x")
        company = Company.objects.create(name="Search Orchards")
        WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Ridgeline Ranch", company=company)
        for name in ("Ridgeline North", "Ridgeline South", "Ridgeline East", "Ridgeline West"):
            Parcel.objects.create(name=name, establishment=self.est, area=2.0)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _results(self):
        response = self.client.get("/api/search/global/", {"q": "Ridgeline"})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]

    def test_search_still_finds_farms_and_parcels(self):
        types = {row["type"] for row in self._results()}
        self.assertEqual(types, {"establishment", "parcel"})

    def test_no_result_carries_a_carbon_figure(self):
        for row in self._results():
            keys = [key for key in row if "carbon" in key.lower() or "co2" in key.lower()]
            self.assertEqual(keys, [], f"{row['type']} {row['name']} still carries {keys}")
