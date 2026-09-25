"""Cross-tenant isolation on the FLAT /api/events/ route (2026-08-18).

`events` is registered both nested under /companies/<pk>/... and flat at /api/events/.
On the flat route there is no `company_pk`, so `CompanyNestedViewSet.initial` left
`self.company` None, `EventViewSet` skipped its company filter, and
`ReadOnlyForViewers.has_permission` short-circuited to True for precisely that case —
while `AuthPermission` checks only that someone is logged in. No permission class
implements `has_object_permission`, so `check_object_permissions` added nothing either.

Net effect: any authenticated user could read, rewrite or delete any other farm's event
by guessing a numeric id. These tests pin every verb on that route.

2026-09-16: "every verb" was not true. The 2026-08-18 fix scoped `get_queryset` and `get_object`,
which covers read, update and delete; CREATE resolves its parcels from request DATA, never touches
either, and had no ownership check at all. `EventCrossTenantCreateTests` below covers it.
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


class EventCrossTenantCreateTests(APITestCase):
    """CREATE was the verb this file's docstring claimed to cover and did not (2026-09-16).

    `_scope_to_caller` (history/views.py) is applied in `get_queryset` and `get_object`, so it
    guards read, update and delete. `perform_create` takes `parcels` straight off the request and
    resolves it with an UNSCOPED `Parcel.objects.filter(id__in=...)`, and nothing between that
    lookup and `event_model.objects.create(...)` asserts the parcel belongs to the caller. On the
    flat /api/events/ route `self.company` is None, so `ReadOnlyForViewers` short-circuits to True
    and the composite collapses to "is authenticated".

    Net effect before the fix: any authenticated user could write an event onto any farm's parcel
    by numeric id, and it counted toward that farm's `index` and trust metrics.
    """

    @classmethod
    def setUpTestData(cls):
        def build(prefix):
            user = get_user_model().objects.create_user(email=f"{prefix}-c@example.com", password="pw-for-tests-only")
            company = Company.objects.create(name=f"{prefix} Create Co")
            user.companies.add(company)
            est = Establishment.objects.create(name=f"{prefix} Create Farm", company=company)
            parcel = Parcel.objects.create(name=f"{prefix} Create Parcel", establishment=est, area=1)
            history = History.objects.create(parcel=parcel, name=f"{prefix} Create Season")
            parcel.current_history = history
            parcel.save(update_fields=["current_history"])
            return user, parcel, history

        cls.owner, cls.owner_parcel, cls.owner_history = build("owner")
        cls.stranger, cls.stranger_parcel, cls.stranger_history = build("stranger")

    def _payload(self, parcel, **extra):
        body = {
            "event_type": 3,
            "parcels": [parcel.pk],
            "name": "posted event",
            "description": "posted event",
            "date": timezone.now().isoformat(),
        }
        body.update(extra)
        return body

    def test_stranger_cannot_create_event_on_foreign_parcel(self):
        """The whole point. A 201 here is a write onto someone else's farm."""
        before = GeneralEvent.objects.filter(history=self.owner_history).count()
        self.client.force_authenticate(user=self.stranger)
        res = self.client.post(reverse("events-list"), self._payload(self.owner_parcel), format="json")
        self.assertIn(
            res.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
            f"cross-tenant create was accepted: {res.status_code} {getattr(res, 'data', None)}",
        )
        self.assertEqual(GeneralEvent.objects.filter(history=self.owner_history).count(), before)

    def test_stranger_cannot_create_by_naming_a_foreign_history(self):
        """`parcels` is derived from `history` when absent, so the same hole exists one field over."""
        before = GeneralEvent.objects.filter(history=self.owner_history).count()
        self.client.force_authenticate(user=self.stranger)
        body = self._payload(self.owner_parcel)
        body.pop("parcels")
        body["history"] = self.owner_history.pk
        res = self.client.post(reverse("events-list"), body, format="json")
        self.assertIn(
            res.status_code,
            (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
            f"cross-tenant create via history was accepted: {res.status_code} {getattr(res, 'data', None)}",
        )
        self.assertEqual(GeneralEvent.objects.filter(history=self.owner_history).count(), before)

    def test_stranger_cannot_smuggle_a_foreign_parcel_alongside_their_own(self):
        """A mixed list must not write the foreign half; `perform_create` loops over every parcel."""
        before = GeneralEvent.objects.filter(history=self.owner_history).count()
        self.client.force_authenticate(user=self.stranger)
        body = self._payload(self.stranger_parcel)
        body["parcels"] = [self.stranger_parcel.pk, self.owner_parcel.pk]
        self.client.post(reverse("events-list"), body, format="json")
        self.assertEqual(
            GeneralEvent.objects.filter(history=self.owner_history).count(),
            before,
            "a mixed parcel list wrote onto the foreign parcel",
        )

    def test_owner_can_still_create_on_own_parcel(self):
        """The floor must not lock legitimate owners out."""
        self.client.force_authenticate(user=self.owner)
        res = self.client.post(reverse("events-list"), self._payload(self.owner_parcel), format="json")
        self.assertEqual(
            res.status_code,
            status.HTTP_201_CREATED,
            f"owner was refused their own parcel: {res.status_code} {getattr(res, 'data', None)}",
        )
        self.assertEqual(GeneralEvent.objects.filter(history=self.owner_history).count(), 1)
