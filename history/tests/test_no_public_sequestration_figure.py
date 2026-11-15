"""No soil-carbon sequestration figure reaches the anonymous QR payload (2026-11-13).

`SoilManagementEvent.carbon_sequestration_potential` is a modelled kg CO2e figure that no form
ever had an input for (the producer modal only shows a stored value). `PublicHistorySerializer`
served it to anyone with the QR. Soil-carbon stock change is excluded from Trazo's carbon
(.claude/rules/carbon-methodology.md, 2026-10-28), and the calculator's own per-hectare credits
left in #397; a sequestration number on a public page is the same claim by another door.

Three doors are held: the named field, any `extra_data` key shaped like one, and the update API
that could still write the field.
"""

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company, Establishment
from history.constants import SOIL_MANAGEMENT_EVENT_TYPE
from history.models import Production, SoilManagementEvent
from history.serializers import PublicHistorySerializer
from product.models import Parcel, Product
from users.models import WorksIn


def _keys(value):
    """Every dict key anywhere in a JSON-shaped value."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield str(key)
            yield from _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _keys(inner)


class NoPublicSequestrationFigureTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="soil@example.com", password="pw-for-tests-only")
        company = Company.objects.create(name="Soil Co")
        WorksIn.objects.create(user=cls.user, company=company, role=WorksIn.COMPANY_ADMIN)
        establishment = Establishment.objects.create(name="Soil Farm", company=company)
        parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=8)
        cls.history = Production.objects.create(
            name="Oranges 2026",
            start_date=timezone.now(),
            product=Product.objects.create(name="Oranges"),
            parcel=parcel,
            operator=cls.user,
            published=True,
        )
        cls.cover_crop = SoilManagementEvent.objects.create(
            history=cls.history,
            type="CC",
            date=timezone.now(),
            description="Annual ryegrass between rows",
            carbon_sequestration_potential=Decimal("1.2"),
            extra_data={"species": "Lolium multiflorum", "carbon_sequestration_kg": 9.6},
        )
        # A published season locks its events (423), so the write test uses an open one.
        cls.open_season = Production.objects.create(
            name="Oranges 2027", start_date=timezone.now(), parcel=parcel, operator=cls.user
        )
        cls.open_cover_crop = SoilManagementEvent.objects.create(
            history=cls.open_season, type="CC", date=timezone.now(), carbon_sequestration_potential=Decimal("1.2")
        )

    def test_the_public_payload_names_no_sequestration_anywhere(self):
        payload = json.loads(json.dumps(PublicHistorySerializer(self.history).data, default=str))
        keys = list(_keys(payload))
        self.assertIn("species", keys)  # the walk reached the soil event's extra_data
        self.assertEqual([k for k in keys if "sequestr" in k.lower()], [])

    def test_a_sequestration_key_is_dropped_even_if_allow_listed(self):
        """The allow-list holds no such key today; the substring guard is what stops the next one
        (the way `traceability_score` reached the payload while allow-listed, 2026-08-03)."""
        allowed = PublicHistorySerializer.ALLOWED_EXTRA_DATA_KEYS | {"carbon_sequestration_kg"}
        with mock.patch.object(PublicHistorySerializer, "ALLOWED_EXTRA_DATA_KEYS", allowed):
            out = PublicHistorySerializer()._sanitize_extra_data_for_public(
                SimpleNamespace(extra_data={"carbon_sequestration_kg": 9.6, "species": "ryegrass"})
            )
        self.assertIn("species", out)  # the sanitizer ran and kept an ordinary key
        self.assertNotIn("carbon_sequestration_kg", out)

    def test_the_update_api_no_longer_writes_the_figure(self):
        """Still shown to the producer when a record carries one; never written again."""
        self.client.force_authenticate(user=self.user)
        url = f"{reverse('events-detail', args=[self.open_cover_crop.pk])}?event_type={SOIL_MANAGEMENT_EVENT_TYPE}"
        res = self.client.patch(url, {"carbon_sequestration_potential": "50.0"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content)
        self.open_cover_crop.refresh_from_db()
        self.assertEqual(self.open_cover_crop.carbon_sequestration_potential, Decimal("1.2"))
        self.assertEqual(float(self.client.get(url).json()["carbon_sequestration_potential"]), 1.2)
