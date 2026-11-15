"""A detail request on /events/<pk>/ must name its event type (2026-11-04).

Event ids are per-table sequences: `CommonEvent` is abstract, so pk 42 can be a GeneralEvent, a
ChemicalEvent and a ProductionEvent at the same time, all in the same company. Until this change
`EventViewSet` resolved a detail request that omitted `?event_type=` by guessing:

- retrieve / update / partial_update / amend took the FIRST table that had the id;
- destroy and crew-note fell through to `get_queryset`, which defaulted to GeneralEvent, so
  `DELETE /events/42/` deleted GeneralEvent 42 whatever record the caller meant;
- `get_serializer_class` read the type from the BODY first while `get_object` read the QUERY, so
  one request could validate against one model and write another.

Every test here builds two records that share a pk on purpose. That collision is the condition
the old code mishandled; without it these tests would pass against the old code too.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from history.constants import CHEMICAL_EVENT_TYPE, GENERAL_EVENT_TYPE
from history.models import ChemicalEvent, GeneralEvent, Production
from product.models import Establishment, Parcel
from users.models import WorksIn

SHARED_PK = 987_654


class EventDetailRequiresTypeTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="owner@example.com", password="pw-for-tests-only")
        company = Company.objects.create(name="Owner Co")
        WorksIn.objects.create(user=cls.user, company=company, role=WorksIn.COMPANY_ADMIN)
        est = Establishment.objects.create(name="Owner Farm", company=company)
        parcel = Parcel.objects.create(name="North", establishment=est, area=1)
        history = Production.objects.create(parcel=parcel, name="2026 Season")
        cls.general = GeneralEvent.objects.create(
            pk=SHARED_PK, history=history, name="general record", description="general", date=timezone.now()
        )
        cls.chemical = ChemicalEvent.objects.create(
            pk=SHARED_PK,
            history=history,
            type=ChemicalEvent.FERTILIZER,
            commercial_name="Fish Emulsion",
            description="chemical",
            date=timezone.now(),
        )

    def setUp(self):
        self.client.force_authenticate(user=self.user)

    def _detail(self):
        return reverse("events-detail", args=[SHARED_PK])

    def test_the_two_records_really_share_a_pk(self):
        """Guards the premise: without the collision nothing below tests the old guessing."""
        self.assertEqual(self.general.pk, self.chemical.pk)

    def _assert_type_required(self, res):
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, res.content)
        self.assertIn("event_type", res.json())

    def test_retrieve_without_type_is_refused(self):
        self._assert_type_required(self.client.get(self._detail()))

    def test_patch_without_type_is_refused_and_writes_nothing(self):
        res = self.client.patch(self._detail(), {"description": "rewritten"}, format="json")
        self._assert_type_required(res)
        self.general.refresh_from_db()
        self.chemical.refresh_from_db()
        self.assertEqual(self.general.description, "general")
        self.assertEqual(self.chemical.description, "chemical")

    def test_put_without_type_is_refused(self):
        self._assert_type_required(self.client.put(self._detail(), {"description": "x"}, format="json"))

    def test_delete_without_type_is_refused_and_deletes_nothing(self):
        """The old code deleted the GeneralEvent here, whichever record the caller meant."""
        self._assert_type_required(self.client.delete(self._detail()))
        self.assertTrue(GeneralEvent.objects.filter(pk=SHARED_PK).exists())
        self.assertTrue(ChemicalEvent.objects.filter(pk=SHARED_PK).exists())

    def test_amend_without_type_is_refused(self):
        self._assert_type_required(self.client.get(reverse("events-amend", args=[SHARED_PK])))

    def test_crew_note_without_type_is_refused(self):
        self._assert_type_required(self.client.get(reverse("events-crew-note", args=[SHARED_PK])))

    def test_unknown_type_is_refused(self):
        self._assert_type_required(self.client.get(self._detail(), {"event_type": 99}))

    def test_non_integer_type_is_refused(self):
        self._assert_type_required(self.client.get(self._detail(), {"event_type": "chemical"}))

    def test_body_type_that_contradicts_the_url_type_is_refused(self):
        url = f"{self._detail()}?event_type={GENERAL_EVENT_TYPE}"
        res = self.client.patch(url, {"event_type": CHEMICAL_EVENT_TYPE, "description": "rewritten"}, format="json")
        self._assert_type_required(res)
        self.general.refresh_from_db()
        self.chemical.refresh_from_db()
        self.assertEqual(self.general.description, "general")
        self.assertEqual(self.chemical.description, "chemical")

    def test_retrieve_with_type_returns_that_record(self):
        res = self.client.get(self._detail(), {"event_type": CHEMICAL_EVENT_TYPE})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.json()["description"], "chemical")
        res = self.client.get(self._detail(), {"event_type": GENERAL_EVENT_TYPE})
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.assertEqual(res.json()["description"], "general")

    def test_type_in_the_body_alone_is_enough(self):
        res = self.client.patch(
            self._detail(), {"event_type": GENERAL_EVENT_TYPE, "description": "edited"}, format="json"
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.general.refresh_from_db()
        self.chemical.refresh_from_db()
        self.assertEqual(self.general.description, "edited")
        self.assertEqual(self.chemical.description, "chemical")

    def test_delete_with_type_deletes_only_that_record(self):
        res = self.client.delete(f"{self._detail()}?event_type={CHEMICAL_EVENT_TYPE}")
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT, res.content)
        self.assertFalse(ChemicalEvent.objects.filter(pk=SHARED_PK).exists())
        self.assertTrue(GeneralEvent.objects.filter(pk=SHARED_PK).exists())
