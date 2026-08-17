"""Write-time completeness nudge: the events endpoint echoes `completeness_gaps`.

Contract under test (EventViewSet.create/update → _attach_completeness_gaps):
- a ChemicalEvent response carries `completeness_gaps` — machine keys from
  `record_completeness.CHEMICAL_EVENT_REQUIRED_FIELDS` still missing on the saved row;
- an incomplete record STILL SAVES (201/200) — the nudge is advisory, never blocking;
- non-chemical events carry no `completeness_gaps` key at all.

Fixture pattern copied from `test_record_completeness_snapshot.py` (`state="CA"` per the
2026-07-30 fixture-trap postmortem) plus `parcel.current_history`, which perform_create requires.
"""

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, Product
from users.models import User, WorksIn


class EventCompletenessNudgeTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="nudge@test.com", password="x")
        self.company = Company.objects.create(name="Nudge Farm Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="Nudge Farm", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="NP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Walnut")
        self.history = History.objects.create(
            name="NH1",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        self.parcel.current_history = self.history
        self.parcel.save(update_fields=["current_history"])
        self.client.force_authenticate(user=self.user)
        self.events_url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/events/"

    def _post_event(self, **payload):
        base = {
            "description": "Field log",
            "date": "2026-08-10T10:00:00Z",
            "parcels": [self.parcel.id],
        }
        base.update(payload)
        return self.client.post(self.events_url, base, format="json")

    def test_incomplete_chemical_event_saves_and_lists_every_gap(self):
        resp = self._post_event(event_type=2, type="PE")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            resp.data.get("completeness_gaps"),
            ["commercial_name", "volume", "area", "target_pest_disease"],
        )

    def test_complete_chemical_event_reports_no_gaps(self):
        resp = self._post_event(
            event_type=2,
            type="PE",
            commercial_name="Example 10G",
            volume="5 gal",
            area="2 ac",
            target_pest_disease="Aphids",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data.get("completeness_gaps"), [])

    def test_update_recomputes_gaps_from_the_saved_row(self):
        created = self._post_event(event_type=2, type="PE")
        self.assertEqual(created.status_code, 201, created.data)
        resp = self.client.patch(
            f"{self.events_url}{created.data['id']}/?event_type=2",
            {"event_type": 2, "commercial_name": "Example 10G"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data.get("completeness_gaps"), ["volume", "area", "target_pest_disease"])

    def test_non_chemical_event_carries_no_completeness_key(self):
        resp = self._post_event(event_type=3, name="Walkthrough")
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertNotIn("completeness_gaps", resp.data)
