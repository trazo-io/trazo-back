"""Cross-tenant isolation on the FLAT /api/events/ route (2026-08-18).

`events` is registered both nested under /companies/<pk>/... and flat at /api/events/.
On the flat route there is no `company_pk`, so `CompanyNestedViewSet.initial` left
`self.company` None, `EventViewSet` skipped its company filter, and
`ReadOnlyForViewers.has_permission` short-circuited to True for precisely that case —
while `AuthPermission` checks only that someone is logged in. No permission class
implements `has_object_permission`, so `check_object_permissions` added nothing either.

Net effect: any authenticated user could read, rewrite or delete any other farm's event
by guessing a numeric id. These tests pin every verb on that route.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from history.models import GeneralEvent, History
from product.models import Establishment, Parcel


class EventCrossTenantAccessTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        def build(prefix):
            user = get_user_model().objects.create_user(email=f"{prefix}@example.com", password="pw-for-tests-only")
            company = Company.objects.create(name=f"{prefix} Co")
            user.companies.add(company)
            est = Establishment.objects.create(name=f"{prefix} Farm", company=company)
            parcel = Parcel.objects.create(name=f"{prefix} Parcel", establishment=est, area=1)
            history = History.objects.create(parcel=parcel, name=f"{prefix} Season")
            event = GeneralEvent.objects.create(history=history, name=f"{prefix} event", date=timezone.now())
            return user, event

        cls.owner, cls.owner_event = build("owner")
        cls.stranger, cls.stranger_event = build("stranger")

    def _url(self, event):
        return reverse("events-detail", args=[event.pk])

    def test_owner_can_read_own_event(self):
        """The floor must not lock legitimate owners out."""
        self.client.force_authenticate(user=self.owner)
        res = self.client.get(self._url(self.owner_event), {"event_type": 3})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_stranger_cannot_read_foreign_event(self):
        self.client.force_authenticate(user=self.stranger)
        res = self.client.get(self._url(self.owner_event), {"event_type": 3})
        self.assertIn(res.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_stranger_cannot_read_foreign_event_without_event_type(self):
        """The no-event_type branch walks every model and had its own unscoped queryset."""
        self.client.force_authenticate(user=self.stranger)
        res = self.client.get(self._url(self.owner_event))
        self.assertIn(res.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

    def test_stranger_cannot_patch_foreign_event(self):
        """The write path is the one that mattered: a 200 here is a silent data rewrite."""
        self.client.force_authenticate(user=self.stranger)
        res = self.client.patch(self._url(self.owner_event), {"name": "rewritten by a stranger"}, format="json")
        self.assertIn(res.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.owner_event.refresh_from_db()
        self.assertEqual(self.owner_event.name, "owner event")

    def test_stranger_cannot_delete_foreign_event(self):
        self.client.force_authenticate(user=self.stranger)
        res = self.client.delete(self._url(self.owner_event))
        self.assertIn(res.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.assertTrue(GeneralEvent.objects.filter(pk=self.owner_event.pk).exists())

    def test_list_does_not_leak_foreign_events(self):
        self.client.force_authenticate(user=self.stranger)
        res = self.client.get(reverse("events-list"), {"event_type": 3})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        body = res.json()
        rows = body if isinstance(body, list) else body.get("results", [])
        returned = {row.get("id") for row in rows}
        self.assertNotIn(self.owner_event.pk, returned)
