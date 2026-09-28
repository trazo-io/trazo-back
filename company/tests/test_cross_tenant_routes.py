"""
No signed-in account may read or change another company's rows through any route.

Found 2026-09-28 by probing every router: the permission classes in `backend/permissions.py`
return True whenever `view.company` is None, which is every flat route and every nested route
whose viewset never checks that the row belongs to the URL's company. Each test below is one
route that leaked, proven with an outsider account (admin of an unrelated company).
`CompanyViewSet` itself is covered in `test_company_tenant_isolation.py`.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from carbon.models import CarbonEntry
from company.models import Company, Establishment
from history.models import History, HistoryScan
from product.models import Parcel
from reviews.models import Review
from users.constants import PRODUCER
from users.models import User, WorksIn


def _admin_of(company, email):
    user = User.objects.create_user(
        email=email,
        password="x",
        first_name="T",
        last_name="T",
        user_type=PRODUCER,
        is_active=True,
    )
    WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
    return user


class CrossTenantRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.victim_co = Company.objects.create(name="Victim Farms")
        cls.victim = _admin_of(cls.victim_co, "admin@victim.example")
        cls.victim_farm = Establishment.objects.create(name="Victim Farm", company=cls.victim_co)
        cls.victim_parcel = Parcel.objects.create(name="Victim Parcel", establishment=cls.victim_farm, area=2.0)
        cls.victim_season = History.objects.create(
            name="Victim 2026",
            parcel=cls.victim_parcel,
            published=False,
            earning=12345.67,
        )
        cls.victim_scan = HistoryScan.objects.create(history=cls.victim_season)
        cls.victim_entry = CarbonEntry.objects.create(
            establishment=cls.victim_farm, type="emission", amount=10.0, year=2026
        )

        cls.outsider_co = Company.objects.create(name="Outsider Co")
        cls.outsider = _admin_of(cls.outsider_co, "admin@outsider.example")
        cls.outsider_farm = Establishment.objects.create(name="Outsider Farm", company=cls.outsider_co)
        cls.outsider_parcel = Parcel.objects.create(name="Outsider Parcel", establishment=cls.outsider_farm, area=1.0)
        cls.outsider_season = History.objects.create(name="Outsider 2026", parcel=cls.outsider_parcel)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.outsider)

    def assertBlocked(self, response):
        self.assertIn(response.status_code, (403, 404), response.content[:300])

    # Seasons ---------------------------------------------------------------------------------

    def test_season_retrieve_by_id_and_uuid(self):
        self.assertBlocked(self.client.get(f"/api/histories/{self.victim_season.id}/"))
        self.assertBlocked(self.client.get(f"/api/histories/{self.victim_season.public_id}/"))

    def test_season_list_shows_only_own(self):
        response = self.client.get("/api/histories/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Outsider 2026", body)  # proves the list was read
        self.assertNotIn("Victim 2026", body)

    def test_owner_still_reads_own_season(self):
        self.client.force_authenticate(self.victim)
        response = self.client.get(f"/api/histories/{self.victim_season.id}/")
        self.assertEqual(response.status_code, 200, response.content[:300])

    # Parcels ---------------------------------------------------------------------------------

    def test_parcel_read_edit_delete(self):
        url = f"/api/parcels/{self.victim_parcel.id}/"
        self.assertBlocked(self.client.get(url))
        self.assertBlocked(self.client.patch(url, {"name": "PWNED"}, format="multipart"))
        self.assertBlocked(self.client.delete(url))
        self.victim_parcel.refresh_from_db()
        self.assertEqual(self.victim_parcel.name, "Victim Parcel")

    def test_owner_still_reads_own_parcel(self):
        self.client.force_authenticate(self.victim)
        self.assertEqual(self.client.get(f"/api/parcels/{self.victim_parcel.id}/").status_code, 200)

    # Scans -----------------------------------------------------------------------------------

    def test_scan_read_and_delete(self):
        url = f"/api/scans/{self.victim_scan.id}/"
        self.assertBlocked(self.client.get(url))
        self.assertBlocked(self.client.delete(url))
        self.assertTrue(HistoryScan.objects.filter(pk=self.victim_scan.pk).exists())

    # Establishments under the caller's OWN company URL ---------------------------------------

    def test_foreign_establishment_under_own_company_url(self):
        url = f"/api/companies/{self.outsider_co.id}/establishments/{self.victim_farm.id}/"
        self.assertBlocked(self.client.get(url))
        self.assertBlocked(self.client.patch(url, {"name": "PWNED FARM"}, format="json"))
        self.victim_farm.refresh_from_db()
        self.assertEqual(self.victim_farm.name, "Victim Farm")

    def test_own_establishment_still_reachable(self):
        url = f"/api/companies/{self.outsider_co.id}/establishments/{self.outsider_farm.id}/"
        self.assertEqual(self.client.get(url).status_code, 200)

    # Reviews ---------------------------------------------------------------------------------

    def test_review_edit_and_delete_only_by_author(self):
        review = Review.objects.create(
            production=self.victim_season,
            user=self.victim,
            headline="Great",
            written_review="Crisp",
            rating=5,
        )
        url = f"/api/reviews/{review.id}/"
        self.assertBlocked(self.client.patch(url, {"headline": "PWNED"}, format="json"))
        self.assertBlocked(self.client.delete(url))
        self.assertTrue(Review.objects.filter(pk=review.pk, headline="Great").exists())

        self.client.force_authenticate(self.victim)
        # The serializer requires `production` on every write (pre-existing), so send it.
        response = self.client.patch(
            url,
            {"headline": "Very good", "production": self.victim_season.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content[:300])

    # Carbon entries --------------------------------------------------------------------------

    def test_carbon_entries_scoped(self):
        response = self.client.get("/api/carbon/entries/")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertNotIn(self.victim_entry.id, [r["id"] for r in rows])
        self.assertBlocked(self.client.get(f"/api/carbon/entries/{self.victim_entry.id}/"))
        self.assertBlocked(self.client.delete(f"/api/carbon/entries/{self.victim_entry.id}/"))
        self.assertTrue(CarbonEntry.objects.filter(pk=self.victim_entry.pk).exists())

        self.client.force_authenticate(self.victim)
        response = self.client.get("/api/carbon/entries/")
        rows = response.json()
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertIn(self.victim_entry.id, [r["id"] for r in rows])
