"""Reading an event's corrections trail is a CA/FM decision, not a safe-method accident.

`EventViewSet.amend` applied its role check below the `GET` branch, so a VIEWER-role member
could read every correction on every event — the original value, the corrected value, who
changed it and the stated reason — while the sibling season-header route
(`HistoryViewSet.amend` -> `_owned_history_or_403`) gated its GET on the same roles.

`CompanyNestedViewSet`'s class permissions do not close this: `ReadOnlyForViewers` returns True
for any safe method, which is what makes viewer read-access the DEFAULT rather than a decision.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel, Product
from users.models import User, WorksIn


class EventAmendPermissionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Amend Co")
        self.establishment = Establishment.objects.create(name="Amend Farm", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="Amend Block", establishment=self.establishment, area=3.0)
        self.product = Product.objects.create(name="Pears")
        self.admin = User.objects.create_user(email="amend-admin@test.com", password="x")
        self.viewer = User.objects.create_user(email="amend-viewer@test.com", password="x")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        WorksIn.objects.create(user=self.viewer, company=self.company, role="VI")
        self.history = History.objects.create(
            name="Amend Season",
            start_date=timezone.now() - timedelta(days=30),
            product=self.product,
            parcel=self.parcel,
            operator=self.admin,
            earning=0.0,
            production_amount=10.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        self.event = ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            date=timezone.now(),
            commercial_name="Bordeaux Mix",
            description="Sprayed",
        )
        self.url = (
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}"
            f"/events/{self.event.id}/amend/?event_type=2"
        )

    def _client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_a_company_admin_may_read_the_corrections_trail(self):
        """The mirror. Without it, refusing everyone would also pass."""
        response = self._client(self.admin).get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("amendments", response.json())

    def test_a_viewer_may_not_read_the_corrections_trail(self):
        response = self._client(self.viewer).get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_a_viewer_may_not_write_a_correction(self):
        response = self._client(self.viewer).post(
            self.url,
            {"field_name": "commercial_name", "new_value": "Something else", "reason": "no"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_an_anonymous_caller_gets_nothing(self):
        self.assertIn(APIClient().get(self.url).status_code, (401, 403))
