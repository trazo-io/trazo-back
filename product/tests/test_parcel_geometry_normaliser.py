"""`Parcel.polygon` read the same way whichever of its two stored shapes it holds.

A boundary a grower draws in the app is stored `[{lat, lng}]`; the seeders and fixture farms store
GeoJSON. The packet's parcel map and the parcel-application map status parsed GeoJSON only, so
every boundary a grower drew was "no geometry" on the certifier packet. These tests pin the shared
reading (`product.services.parcel_geometry`) and both readers on the drawn shape.
"""

from django.test import SimpleTestCase, TestCase

from certifications.services.parcel_map import parcel_boundary_ring, parcel_map_caption, parcel_map_drawing
from company.models import Company, Establishment
from product.models import Parcel
from product.services.parcel_application_status import parcel_evidence_status
from product.services.parcel_geometry import latlng_path, outer_ring_lnglat

# The same small square (about 0.9 ha) in both shapes.
GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[-123.11, 44.54], [-123.10, 44.54], [-123.10, 44.55], [-123.11, 44.55], [-123.11, 44.54]]],
}
DRAWN = [
    {"lat": 44.54, "lng": -123.11},
    {"lat": 44.54, "lng": -123.10},
    {"lat": 44.55, "lng": -123.10},
    {"lat": 44.55, "lng": -123.11},
]
OPEN_RING = [[-123.11, 44.54], [-123.10, 44.54], [-123.10, 44.55], [-123.11, 44.55]]


class NormaliserTests(SimpleTestCase):
    def test_both_shapes_read_as_the_same_open_ring(self):
        self.assertEqual(outer_ring_lnglat(GEOJSON), OPEN_RING)
        self.assertEqual(outer_ring_lnglat(DRAWN), OPEN_RING)

    def test_latlng_path_is_the_shape_the_map_draws(self):
        self.assertEqual(latlng_path(GEOJSON), DRAWN)
        self.assertEqual(latlng_path(DRAWN), DRAWN)

    def test_unusable_values_are_none_never_a_guess(self):
        for value in (
            None,
            "",
            {},
            [],
            {"type": "Point", "coordinates": [1, 2]},
            {"type": "Polygon", "coordinates": []},
            [{"lat": 1, "lng": 2}, {"lat": 3, "lng": 4}],  # two points are not an area
            [{"lat": "x", "lng": 2}] * 4,
            [{"lat": float("nan"), "lng": 2}] * 4,
            [{"lat": True, "lng": 2}] * 4,
            "[{'lat': 1}]",
        ):
            with self.subTest(value=value):
                self.assertIsNone(outer_ring_lnglat(value))
                self.assertIsNone(latlng_path(value))

    def test_bad_points_are_dropped_and_the_rest_kept(self):
        mixed = DRAWN + [{"lat": None, "lng": 1}, "junk"]
        self.assertEqual(outer_ring_lnglat(mixed), OPEN_RING)


class DrawnBoundaryReachesThePacketTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Drawn Co")
        farm = Establishment.objects.create(name="Drawn Farm", company=company)
        self.drawn = Parcel.objects.create(name="Drawn Field", establishment=farm, area=0.9, polygon=DRAWN)
        self.seeded = Parcel.objects.create(name="Seeded Field", establishment=farm, area=0.9, polygon=GEOJSON)

    def test_the_packet_map_draws_a_boundary_drawn_in_the_app(self):
        self.assertEqual(parcel_boundary_ring(self.drawn), OPEN_RING)
        self.assertIsNotNone(parcel_map_drawing(self.drawn))
        self.assertIn("center 44.545000, -123.105000", parcel_map_caption(self.drawn))

    def test_both_shapes_get_the_same_map_status(self):
        drawn = parcel_evidence_status(self.drawn)
        seeded = parcel_evidence_status(self.seeded)
        self.assertNotEqual(drawn["detail"].get("map"), None)
        self.assertEqual(drawn["detail"].get("map"), seeded["detail"].get("map"))
        self.assertNotIn(drawn["detail"].get("map"), ("none", None))
