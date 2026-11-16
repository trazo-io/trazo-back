"""Farm actions answer only for a farm in the URL's company, and a farm cannot change company.

`EstablishmentViewSet` scopes `get_queryset` to the URL's company and the caller's companies, and
`CompanyNestedViewSet` checks the caller works in `company_pk`. But the URL kwarg here is `pk`, not
`establishment_pk`, so the nested establishment check never runs, and seven actions fetched the farm
with `get_object_or_404(Establishment, pk=pk)` instead of going through the queryset. A member of
company A therefore read company B's dashboard, unpublished seasons included, through A's own URL:

    GET /api/companies/<A>/establishments/<B's farm>/dashboard_comprehensive/

Separately, `company` is a writable field on `UpdateEstablishmentSerializer`, so a PATCH could move
a farm (and every parcel and season under it) into another company. Found by the 2026-10-20 route
inventory (`backend/route_tenancy.py`); reproduced here before the fix.
"""

from django.test import TestCase

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import Production
from product.models import Parcel
from users.constants import PRODUCER
from users.models import User, WorksIn

ACTIONS = (
    "products",
    "get_charts_data",
    "products_reputation",
    "last_reviews",
    "rating_reviews_percentage",
    "dashboard_comprehensive",
    "parcel-geometry",
)


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


class EstablishmentActionsScopedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.victim_co = Company.objects.create(name="Victim Farms")
        cls.victim_farm = Establishment.objects.create(name="Victim Farm", company=cls.victim_co)
        victim_parcel = Parcel.objects.create(name="Victim Parcel", establishment=cls.victim_farm, area=2.0)
        Production.objects.create(name="Victim Unpublished 2026", parcel=victim_parcel, published=False)

        cls.outsider_co = Company.objects.create(name="Outsider Co")
        cls.outsider = _admin_of(cls.outsider_co, "admin@outsider.example")
        cls.outsider_farm = Establishment.objects.create(name="Outsider Farm", company=cls.outsider_co)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.outsider)

    def _url(self, farm, action):
        return f"/api/companies/{self.outsider_co.id}/establishments/{farm.id}/{action}/?period=week"

    def test_actions_refuse_another_companys_farm_under_own_company_url(self):
        for action in ACTIONS:
            with self.subTest(action=action):
                response = self.client.get(self._url(self.victim_farm, action))
                self.assertEqual(response.status_code, 404, response.content[:300])
                self.assertNotIn(b"Victim", response.content)

    def test_actions_still_answer_for_own_farm(self):
        """The control: the same requests on the caller's own farm still succeed."""
        for action in ACTIONS:
            with self.subTest(action=action):
                response = self.client.get(self._url(self.outsider_farm, action))
                self.assertEqual(response.status_code, 200, response.content[:300])

    def test_patch_cannot_move_a_farm_into_another_company(self):
        url = f"/api/companies/{self.outsider_co.id}/establishments/{self.outsider_farm.id}/"
        response = self.client.patch(url, {"company": self.victim_co.id}, format="json")
        self.assertEqual(response.status_code, 400, response.content[:300])
        self.outsider_farm.refresh_from_db()
        self.assertEqual(self.outsider_farm.company_id, self.outsider_co.id)

    def test_patch_naming_the_same_company_still_saves(self):
        """The frontend sends the whole form, `company` included; an unchanged value is fine."""
        url = f"/api/companies/{self.outsider_co.id}/establishments/{self.outsider_farm.id}/"
        response = self.client.patch(url, {"company": self.outsider_co.id, "name": "Renamed Farm"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.outsider_farm.refresh_from_db()
        self.assertEqual(self.outsider_farm.name, "Renamed Farm")

    def test_query_params_cannot_probe_another_companys_ids(self):
        """`?parcel=` and `?production=` resolve inside the URL's farm, so a foreign id 404s
        exactly like a missing one instead of confirming it exists."""
        victim_parcel = self.victim_farm.parcels.get()
        victim_season = Production.objects.get(parcel=victim_parcel)
        probes = (
            ("get_charts_data", f"&parcel={victim_parcel.id}"),
            ("get_charts_data", f"&production={victim_season.id}"),
            ("products_reputation", f"&production={victim_season.id}"),
        )
        for action, query in probes:
            with self.subTest(action=action, query=query):
                response = self.client.get(self._url(self.outsider_farm, action) + query)
                self.assertEqual(response.status_code, 404, response.content[:300])
