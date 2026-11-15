"""GET /api/companies/<c>/establishments/<e>/parcel-geometry/: every parcel of one farm, mapped.

The parcel picker's Map mode draws all of a farm's parcels at once. The establishment payload has
no polygons (by design, to stay small) and the parcel list route filters by company, not by farm,
with the heavy retrieve serializer. This route is the slim, farm-scoped read: boundaries in the
one shape the map draws, open seasons (to grey out parcels a multi-parcel save would refuse) and
known sections (for the per-parcel chips), in a fixed number of queries.

Tenancy for a foreign farm under the caller's own company URL is pinned by
`test_establishment_actions_scoped` (ACTIONS includes `parcel-geometry`).
"""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rest_framework.test import APITestCase

from company.models import Company, Establishment
from history.models import GeneralEvent, Production
from history.services.block_ids import known_block_ids_for_parcel, known_block_ids_for_parcels
from product.models import Parcel, ParcelPlannedCrop
from users.models import WorksIn

DRAWN = [
    {"lat": 44.54, "lng": -123.11},
    {"lat": 44.54, "lng": -123.10},
    {"lat": 44.55, "lng": -123.10},
]
GEOJSON = {"type": "Polygon", "coordinates": [[[-123.2, 44.6], [-123.1, 44.6], [-123.1, 44.7], [-123.2, 44.6]]]}


class ParcelGeometryEndpointTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(email="geo-owner@example.com", password="pw-for-tests-only")
        cls.company = Company.objects.create(name="Geo Co")
        cls.user.companies.add(cls.company)
        WorksIn.objects.filter(user=cls.user, company=cls.company).update(role=WorksIn.COMPANY_ADMIN)
        cls.farm = Establishment.objects.create(name="Geo Farm", company=cls.company)
        other_farm = Establishment.objects.create(name="Other Farm", company=cls.company)
        Parcel.objects.create(name="Elsewhere", establishment=other_farm, area=1, polygon=DRAWN)

        cls.drawn = Parcel.objects.create(name="A Drawn", establishment=cls.farm, area=2.5, polygon=DRAWN)
        cls.seeded = Parcel.objects.create(name="B Seeded", establishment=cls.farm, area=4, polygon=GEOJSON)
        cls.bare = Parcel.objects.create(
            name="C Bare",
            establishment=cls.farm,
            area=1,
            polygon=None,
            map_metadata={"center": {"lat": 44.5, "lng": -123.0}, "zoom": 15},
        )
        season = Production.objects.create(parcel=cls.drawn, name="A 2026", start_date=timezone.now())
        Production.objects.create(parcel=cls.seeded, name="B 2026", start_date=timezone.now())
        Production.objects.create(parcel=cls.seeded, name="B 2027", start_date=timezone.now())
        GeneralEvent.objects.create(history=season, name="x", date=timezone.now(), block_id="Rows 1-12")
        GeneralEvent.objects.create(history=season, name="y", date=timezone.now(), block_id="rows 1-12")
        GeneralEvent.objects.create(history=season, name="z", date=timezone.now(), block_id="Rows 1-12")

    def _url(self, company=None, farm=None):
        return f"/api/companies/{(company or self.company).id}/establishments/{(farm or self.farm).id}/parcel-geometry/"

    def test_every_parcel_of_this_farm_and_only_this_farm(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200, res.content[:300])
        body = res.json()
        self.assertEqual([p["name"] for p in body], ["A Drawn", "B Seeded", "C Bare"])

        drawn, seeded, bare = body
        self.assertEqual(drawn["path"], DRAWN)
        self.assertTrue(drawn["has_boundary"])
        self.assertEqual(drawn["area"], 2.5)
        self.assertEqual(drawn["open_season_count"], 1)
        # Case variants collapse to the most-used spelling.
        self.assertEqual(drawn["known_block_ids"], ["Rows 1-12"])

        # GeoJSON comes back in the same [{lat, lng}] shape, closing point dropped.
        self.assertEqual(
            seeded["path"], [{"lat": 44.6, "lng": -123.2}, {"lat": 44.6, "lng": -123.1}, {"lat": 44.7, "lng": -123.1}]
        )
        self.assertEqual(seeded["open_season_count"], 2)

        self.assertIsNone(bare["path"])
        self.assertFalse(bare["has_boundary"])
        self.assertEqual(bare["center"], {"lat": 44.5, "lng": -123.0})
        self.assertEqual(bare["open_season_count"], 0)
        self.assertEqual(bare["known_block_ids"], [])

    def test_a_non_finite_map_centre_is_dropped_not_a_500_for_the_whole_farm(self):
        Parcel.objects.create(
            name="D Poisoned",
            establishment=self.farm,
            area=1,
            polygon=[{"lat": "Infinity", "lng": 1}, {"lat": 1, "lng": 1}, {"lat": 2, "lng": 2}],
            map_metadata={"center": {"lat": "Infinity", "lng": "NaN"}},
        )
        self.client.force_authenticate(user=self.user)
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200, res.content[:300])
        poisoned = next(p for p in res.json() if p["name"] == "D Poisoned")
        self.assertIsNone(poisoned["center"])
        self.assertIsNone(poisoned["path"])  # two finite points are not an area
        self.assertEqual(len(res.json()), 4)

    def test_query_count_does_not_grow_with_the_number_of_parcels(self):
        self.client.force_authenticate(user=self.user)
        with CaptureQueriesContext(connection) as three:
            self.assertEqual(self.client.get(self._url()).status_code, 200)
        for i in range(5):
            Parcel.objects.create(name=f"Z{i}", establishment=self.farm, area=1, polygon=DRAWN)
        with CaptureQueriesContext(connection) as eight:
            self.assertEqual(len(self.client.get(self._url()).json()), 8)
        self.assertEqual(len(eight), len(three))

    def test_another_company_url_and_anonymous_are_refused(self):
        stranger = get_user_model().objects.create_user(email="geo-stranger@example.com", password="pw-for-tests-only")
        stranger_co = Company.objects.create(name="Stranger Geo Co")
        stranger.companies.add(stranger_co)
        self.client.force_authenticate(user=stranger)
        res = self.client.get(self._url())
        self.assertIn(res.status_code, (403, 404))
        self.assertNotIn(b"A Drawn", res.content)

        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(self._url()).status_code, (401, 403))


class KnownSectionsBatchTests(APITestCase):
    def test_batch_equals_the_per_parcel_answer_in_nine_queries(self):
        # Eight event models plus the crop table's block names (2026-11-11), whatever the number of parcels.
        company = Company.objects.create(name="Batch Co")
        farm = Establishment.objects.create(name="Batch Farm", company=company)
        parcels = [Parcel.objects.create(name=f"P{i}", establishment=farm, area=1) for i in range(4)]
        for i, parcel in enumerate(parcels[:3]):
            season = Production.objects.create(parcel=parcel, name=f"S{i}", start_date=timezone.now())
            for label in ("North", "north", "South", f"Only {i}"):
                GeneralEvent.objects.create(history=season, name=label, date=timezone.now(), block_id=label)
            ParcelPlannedCrop.objects.create(parcel=parcel, crop="Apples", block_name=f"Planted {i}")

        with CaptureQueriesContext(connection) as queries:
            batch = known_block_ids_for_parcels([p.id for p in parcels])
        self.assertEqual(len(queries), 9)
        self.assertIn("Planted 0", batch[parcels[0].id])
        self.assertNotIn("Planted 0", batch[parcels[1].id])
        for parcel in parcels:
            self.assertEqual(batch[parcel.id], known_block_ids_for_parcel(parcel))
        self.assertEqual(batch[parcels[3].id], [])
        self.assertEqual(known_block_ids_for_parcels([]), {})
