"""No new EquipmentEvent through the API (2026-11-11).

Equipment work is a Production activity (subtype EM, "Equipment maintenance") since the wizard
merged the two: the Equipment tile is gone (NewEvent.jsx) and the V2 template seeder marks
`backend_event_type=4` deprecated. `EventViewSet` still created an EquipmentEvent for any client
that sent `event_type=4`, single or multi-parcel. Creation is refused now.

The 21 rows production holds stay readable and editable: 15 sit on sealed seasons, and the v1 seal
hash names "EquipmentEvent" and their ids, so they cannot be folded into another table.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from history.constants import EQUIPMENT_EVENT_TYPE, GENERAL_EVENT_TYPE
from history.models import EquipmentEvent, GeneralEvent, History
from product.models import Establishment, Parcel
from users.models import WorksIn


class EquipmentEventCreateClosedTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="owner@example.com", password="pw-for-tests-only")
        company = Company.objects.create(name="Owner Co")
        WorksIn.objects.create(user=cls.user, company=company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Owner Farm", company=company)
        cls.parcel = Parcel.objects.create(name="North", establishment=est, area=1)
        cls.other_parcel = Parcel.objects.create(name="South", establishment=est, area=1)
        cls.history = History.objects.create(parcel=cls.parcel, name="2026 Season")
        cls.legacy = EquipmentEvent.objects.create(
            history=cls.history, type="MN", description="legacy maintenance", date=timezone.now()
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def _body(self, **extra):
        return {
            "event_type": EQUIPMENT_EVENT_TYPE,
            "history": self.history.pk,
            "type": "MN",
            "description": "new maintenance",
            "date": timezone.now().isoformat(),
            **extra,
        }

    def _assert_refused(self, res):
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn("Equipment maintenance", res.json()["event_type"][0])
        self.assertEqual(EquipmentEvent.objects.count(), 1)  # only the legacy row

    def test_a_new_equipment_event_is_refused(self):
        self._assert_refused(self.client.post(reverse("events-list"), self._body(), format="json"))

    def test_the_type_in_the_query_string_is_refused_too(self):
        body = self._body()
        body.pop("event_type")
        url = f"{reverse('events-list')}?event_type={EQUIPMENT_EVENT_TYPE}"
        self._assert_refused(self.client.post(url, body, format="json"))

    def test_a_multi_parcel_equipment_event_is_refused(self):
        body = self._body(targets=[{"parcel": self.parcel.pk}, {"parcel": self.other_parcel.pk}])
        self._assert_refused(self.client.post(reverse("events-list"), body, format="json"))

    def test_another_type_is_still_created(self):
        """The guard reads the type: it does not refuse every create."""
        body = {
            "event_type": GENERAL_EVENT_TYPE,
            "history": self.history.pk,
            "name": "walked the block",
            "description": "general",
            "date": timezone.now().isoformat(),
        }
        res = self.client.post(reverse("events-list"), body, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content)
        self.assertTrue(GeneralEvent.objects.filter(history=self.history, name="walked the block").exists())

    def test_an_existing_equipment_event_stays_readable_and_editable(self):
        url = f"{reverse('events-detail', args=[self.legacy.pk])}?event_type={EQUIPMENT_EVENT_TYPE}"
        self.assertEqual(self.client.get(url).status_code, status.HTTP_200_OK)
        res = self.client.patch(url, {"description": "corrected"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.description, "corrected")
