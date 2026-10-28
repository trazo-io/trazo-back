"""A placeholder map centre is not a place, on any surface.

The app wrote two fixed centres when it did not know where a parcel was: the parcel form's Fresno,
CA fallback, and a New York default the parcel page injected on load and save whenever a parcel had
no saved map (both removed from the frontend in trazo-app #217). Parcels saved before then still
carry them, and at the default "approximate" disclosure level the public lot payload published the
saved centre as the parcel's area, so a buyer saw an Oregon farm's parcel in Manhattan.

Plain stubs, no database: these are pure readings of a JSON value.
"""

from types import SimpleNamespace

from django.test import SimpleTestCase

from history.services.privacy import public_map_metadata, public_parcel_geo
from product.services.parcel_geometry import is_placeholder_center, map_center

FRESNO = {"center": {"lat": 36.7378, "lng": -119.7871}, "zoom": 16}
NEW_YORK = {"center": {"lat": 40.7128, "lng": -74.006}, "zoom": 13}
TANGENT = {"center": {"lat": 44.540213, "lng": -123.108877}, "zoom": 17}


def parcel(level, map_metadata, polygon=None):
    return SimpleNamespace(location_disclosure_level=level, map_metadata=map_metadata, polygon=polygon)


class PlaceholderCenterTests(SimpleTestCase):
    def test_both_placeholders_are_recognised_and_a_real_centre_is_not(self):
        self.assertTrue(is_placeholder_center(36.7378, -119.7871))
        self.assertTrue(is_placeholder_center(40.7128, -74.006))
        self.assertFalse(is_placeholder_center(44.540213, -123.108877))
        # A real field near Fresno is still a real field.
        self.assertFalse(is_placeholder_center(36.74, -119.79))

    def test_map_center_reads_a_placeholder_as_no_centre(self):
        self.assertIsNone(map_center(FRESNO))
        self.assertIsNone(map_center(NEW_YORK))
        self.assertEqual(map_center(TANGENT), {"lat": 44.540213, "lng": -123.108877})

    def test_approximate_level_publishes_no_map_for_a_placeholder(self):
        for meta in (FRESNO, NEW_YORK):
            with self.subTest(meta=meta):
                geo = public_parcel_geo(parcel("approximate", meta))
                self.assertIsNone(geo["map_metadata"])
                self.assertIsNone(geo["polygon"])

    def test_approximate_level_still_publishes_a_real_centre_rounded(self):
        geo = public_parcel_geo(parcel("approximate", TANGENT))
        self.assertEqual(
            geo["map_metadata"],
            {"center": {"lat": 44.54, "lng": -123.11}, "zoom": 13, "approximate": True},
        )

    def test_exact_level_drops_a_placeholder_centre_and_its_zoom_but_keeps_the_boundary(self):
        polygon = [{"lat": 44.541, "lng": -123.111}, {"lat": 44.541, "lng": -123.109}, {"lat": 44.539, "lng": -123.109}]
        geo = public_parcel_geo(parcel("exact", {**NEW_YORK, "map_type": "satellite"}, polygon))
        self.assertEqual(geo["polygon"], polygon)
        self.assertEqual(geo["map_metadata"], {"map_type": "satellite"})
        self.assertIsNone(public_map_metadata(FRESNO))
        self.assertEqual(public_map_metadata(TANGENT), TANGENT)
