"""
Phase 3 privacy regression tests for the public consumer QR payload.

Two consent-gated surfaces:
1. Worker names — performed_by is masked to "Farm team (A.T.)" unless the
   establishment opted in (Establishment.show_full_performer_names). Full
   name + farm geolocation on a public page is a CCPA exposure and a doxing
   vector.
2. Parcel geodata — polygon/map_metadata gated by
   Parcel.location_disclosure_level (exact | approximate | hidden). A public
   field polygon is a theft/scouting exposure.
"""

import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.serializers import PublicHistorySerializer
from history.services.privacy import public_parcel_geo
from product.models import Parcel, Product
from users.models import User


class _Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="priv@test.com", password="x")
        self.company = Company.objects.create(name="Privacy Farm")
        self.establishment = Establishment.objects.create(name="P1", company=self.company)
        self.parcel = Parcel.objects.create(
            name="PP1",
            establishment=self.establishment,
            area=5.0,
            polygon=[[34.3414, -119.1795], [34.3420, -119.1790], [34.3418, -119.1801]],
            map_metadata={"center": {"lat": 34.3414, "lng": -119.1795}, "zoom": 16},
        )
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="Privacy Test Production",
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
            published=True,
        )

    def _payload(self):
        return PublicHistorySerializer(self.history).data


class PerformerMaskingTests(_Base):
    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(
            history=self.history,
            type="PL",
            performed_by="Ana Torres",
            date=timezone.now(),
        )

    def _planting_event(self):
        events = self._payload().get("events") or []
        planting = [e for e in events if e.get("type") == "PL"]
        self.assertEqual(len(planting), 1)
        return planting[0]

    def test_full_name_masked_by_default(self):
        ev = self._planting_event()
        self.assertEqual(ev.get("performed_by"), "Farm team (A.T.)")

    def test_full_name_absent_from_entire_payload(self):
        blob = json.dumps(self._payload(), default=str)
        self.assertNotIn("Ana Torres", blob, "worker full name leaked into public payload")

    def test_opt_in_shows_full_name(self):
        self.establishment.show_full_performer_names = True
        self.establishment.save()
        ev = self._planting_event()
        self.assertEqual(ev.get("performed_by"), "Ana Torres")

    def test_empty_performer_stays_empty(self):
        ProductionEvent.objects.all().update(performed_by=None)
        ev = self._planting_event()
        self.assertIsNone(ev.get("performed_by"))

    def test_single_word_name_masks_to_one_initial(self):
        ProductionEvent.objects.all().update(performed_by="Roberto")
        ev = self._planting_event()
        self.assertEqual(ev.get("performed_by"), "Farm team (R.)")


class ParcelDisclosureTests(_Base):
    def test_exact_exposes_polygon(self):
        self.parcel.location_disclosure_level = "exact"
        self.parcel.save()
        parcel = self._payload().get("parcel") or {}
        self.assertTrue(parcel.get("polygon"))
        self.assertEqual(parcel.get("map_metadata", {}).get("zoom"), 16)

    def test_approximate_strips_polygon_and_rounds_center(self):
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.save()
        parcel = self._payload().get("parcel") or {}
        self.assertIsNone(parcel.get("polygon"), "polygon must not leak at approximate level")
        meta = parcel.get("map_metadata") or {}
        self.assertEqual(meta.get("center"), {"lat": 34.34, "lng": -119.18})
        self.assertTrue(meta.get("approximate"))
        self.assertLessEqual(meta.get("zoom"), 13, "zoom must be capped so the field can't be located")

    def test_hidden_strips_all_geo(self):
        self.parcel.location_disclosure_level = "hidden"
        self.parcel.save()
        parcel = self._payload().get("parcel") or {}
        self.assertIsNone(parcel.get("polygon"))
        self.assertIsNone(parcel.get("map_metadata"))

    def test_exact_coordinates_absent_from_blob_when_approximate(self):
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.save()
        blob = json.dumps(self._payload(), default=str)
        self.assertNotIn("34.3414", blob, "exact latitude leaked at approximate disclosure level")

    def test_helper_handles_missing_metadata(self):
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.map_metadata = None
        self.parcel.save()
        geo = public_parcel_geo(self.parcel)
        self.assertIsNone(geo["polygon"])
        self.assertIsNone(geo["map_metadata"])

    def test_helper_survives_malformed_metadata(self):
        # map_metadata is free-form JSON — garbage must degrade to "no map"
        # on the public endpoint, never to a 500.
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.map_metadata = {"center": {"lat": "garbage", "lng": -119.0}, "zoom": "huge"}
        self.parcel.save()
        geo = public_parcel_geo(self.parcel)
        self.assertIsNone(geo["map_metadata"])


class FarmerLocationPIITests(_Base):
    """P1 (2026-06): the public transparency endpoint must not leak the farm's
    street address, exact GPS coordinates, or zip. The consumer UI shows only
    city/state and the map uses the parcel's location_disclosure_level-gated
    geo; exposing establishment/company address + coords here bypassed that
    privacy control and handed any anonymous API caller the farm's exact spot.
    """

    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        self.establishment.address = "2847 Orchard Valley Road"
        self.establishment.city = "Fallbrook"
        self.establishment.state = "California"
        self.establishment.latitude = 33.3764
        self.establishment.longitude = -117.251
        self.establishment.zip_code = "92028"
        self.establishment.save()
        self.company.address = "2847 Orchard Valley Road"
        self.company.save()

    def _get(self):
        url = reverse("production-transparency-detail", kwargs={"production_public_id": str(self.history.public_id)})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp

    def test_location_pii_stripped(self):
        farmer = self._get().json()["farmer"]
        self.assertIsNone(farmer.get("address"))
        self.assertIsNone(farmer.get("latitude"))
        self.assertIsNone(farmer.get("longitude"))
        self.assertIsNone(farmer.get("zip_code"))
        self.assertIsNone((farmer.get("company") or {}).get("address"))

    def test_city_state_retained(self):
        # Coarse location is intended consumer transparency — must NOT be over-stripped.
        farmer = self._get().json()["farmer"]
        self.assertEqual(farmer.get("city"), "Fallbrook")
        self.assertEqual(farmer.get("state"), "California")
        self.assertEqual(farmer.get("location"), "Fallbrook, California")

    def test_exact_address_and_coords_absent_from_blob(self):
        blob = self._get().content.decode()
        self.assertNotIn("2847 Orchard Valley Road", blob, "street address leaked")
        self.assertNotIn("33.3764", blob, "exact latitude leaked")
        self.assertNotIn("-117.251", blob, "exact longitude leaked")
        self.assertNotIn("92028", blob, "zip leaked")
