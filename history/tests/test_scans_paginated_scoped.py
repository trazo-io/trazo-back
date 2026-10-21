"""The farm scan list answers only for a company the caller works in.

`HistoryViewSet.establishment_scans_paginated` declares `permission_classes=[IsAuthenticated]`,
which replaces the nested route's membership check, and then filtered on the `company_id` and
`establishment_id` query params. Any signed-in account could read any farm's scans by integer id,
each row carrying the scanner's full name, IP address and comment. Found by the 2026-10-20 route
inventory (`backend/route_tenancy.py`); reproduced here before the fix.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import History, HistoryScan
from product.models import Parcel
from users.constants import PRODUCER
from users.models import User, WorksIn

URL = "/api/histories/establishment_scans_paginated/"


def _user(email):
    return User.objects.create_user(
        email=email, password="x", first_name="Scan", last_name="Person", user_type=PRODUCER, is_active=True
    )


class ScansPaginatedScopedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.victim_co = Company.objects.create(name="Victim Farms")
        cls.victim_farm = Establishment.objects.create(name="Victim Farm", company=cls.victim_co)
        parcel = Parcel.objects.create(name="Victim Parcel", establishment=cls.victim_farm, area=2.0)
        season = History.objects.create(name="Victim 2026", parcel=parcel, published=True)
        shopper = _user("shopper@example.com")
        HistoryScan.objects.create(history=season, user=shopper, ip_address="203.0.113.7", comment="victim comment")

        cls.member = _user("member@victim.example")
        WorksIn.objects.create(user=cls.member, company=cls.victim_co, role=WorksIn.VIEWER)

        cls.outsider_co = Company.objects.create(name="Outsider Co")
        cls.outsider = _user("admin@outsider.example")
        WorksIn.objects.create(user=cls.outsider, company=cls.outsider_co, role=WorksIn.COMPANY_ADMIN)

    def _get(self, user, company_id):
        client = APIClient()
        client.force_authenticate(user)
        return client.get(URL, {"establishment_id": self.victim_farm.id, "company_id": company_id})

    def test_outsider_cannot_read_another_companys_scans(self):
        response = self._get(self.outsider, self.victim_co.id)
        self.assertEqual(response.status_code, 404, response.content[:300])
        self.assertNotIn(b"203.0.113.7", response.content)
        self.assertNotIn(b"victim comment", response.content)

    def test_naming_own_company_with_a_foreign_farm_returns_nothing(self):
        """The company check alone is not the fix: the farm must also belong to that company."""
        response = self._get(self.outsider, self.outsider_co.id)
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.data["count"], 0)
        self.assertNotIn(b"203.0.113.7", response.content)

    def test_malformed_company_id_is_a_400_not_a_500(self):
        # "²".isdigit() is True but int("²") raises: the first version of the check let it through.
        for bad in ("not-a-number", "\u00b2"):
            with self.subTest(company_id=bad):
                response = self._get(self.outsider, bad)
                self.assertEqual(response.status_code, 400, response.content[:300])

    def test_member_still_reads_own_scans(self):
        """The control: any member of the farm's company, Viewer included, reads the list."""
        response = self._get(self.member, self.victim_co.id)
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.data["count"], 1)
