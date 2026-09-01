"""A demo farm's map must point at the town the page names.

WHAT WENT WRONG
---------------
`backfill_demo_claim_safety` has relocated the ESTABLISHMENT to its fixture's coordinates since
2026-08-01, and separately downgraded each parcel's `location_disclosure_level` from `exact` to
`approximate`. Neither touched the parcel's own geometry — and `map_metadata.center`, which is
what the consumer map renders, derives from the PARCEL.

So production served Solana Verde Organic Ranch with "Fallbrook, CA" in the location block, over
a satellite view centred at 36.63 / -119.38: Fresno County, 410 km away. A reader comparing the
two is looking at a page that contradicts itself about where the food came from.

WHY `approximate` DID NOT COVER IT
----------------------------------
It rounds the centre to two decimals, about 1 km. That is noise against a 410 km error. The
disclosure level is a PRIVACY control — how precisely a farmer is willing to be located — and
was doing its job correctly; it was never a correctness control, and reading it as one is how
the contradiction survived a command written specifically to fix demo geography.

WHY THE POLYGON IS DROPPED RATHER THAN MOVED
--------------------------------------------
Those vertices describe a real field somewhere in Fresno County. Translating the shape to
Fallbrook would draw an equally real boundary over land the demo has nothing to do with, and
`approximate` withholds boundaries from the public payload anyway, so nothing legitimate is
left for it to feed.
"""

from django.test import TestCase

from history.management.commands.backfill_demo_claim_safety import FIXTURES
from product.models import Parcel


class DemoMapMatchesStatedLocationTests(TestCase):
    def test_every_fixture_declares_the_coordinates_the_parcel_fix_needs(self):
        """Anti-vacuity, and a fence on the config the relocation reads.

        `_fix_parcel` takes its target from `cfg["latitude"] / cfg["longitude"]`. A fixture added
        without them raises KeyError mid-run, after earlier rows in the same transaction have
        already been written on a `--apply` pass.
        """
        self.assertTrue(FIXTURES, "no fixtures declared — the relocation guard is vacuous")
        for name, cfg in FIXTURES.items():
            self.assertIn("latitude", cfg, name)
            self.assertIn("longitude", cfg, name)
            self.assertIsInstance(cfg["latitude"], float, name)
            self.assertIsInstance(cfg["longitude"], float, name)

    def test_fixture_coordinates_sit_in_the_state_the_page_names(self):
        """Both demo fixtures are Californian; a transposed sign or swapped pair moves them oceans.

        Cheap sanity fence rather than a geocoder: California spans roughly 32.5–42 N and
        114–124.5 W. The failure this catches is not subtlety, it is Fresno-for-Fallbrook.
        """
        for name, cfg in FIXTURES.items():
            self.assertTrue(32.0 <= cfg["latitude"] <= 42.5, f"{name}: latitude {cfg['latitude']} is not in California")
            self.assertTrue(
                -125.0 <= cfg["longitude"] <= -114.0,
                f"{name}: longitude {cfg['longitude']} is not in California",
            )

    def test_the_relocation_moves_the_map_centre_and_drops_the_boundary(self):
        """Drive the real command method against a parcel sitting 410 km from its fixture."""
        from history.management.commands.backfill_demo_claim_safety import Command

        cfg = FIXTURES["solana"]
        parcel = Parcel(
            name="Hillside Grove A",
            area=34.4,
            location_disclosure_level="exact",
            polygon=[{"lat": 36.6362, "lng": -119.3831}, {"lat": 36.6328, "lng": -119.3832}],
            map_metadata={"center": {"lat": 36.63, "lng": -119.38}, "zoom": 15},
        )

        command = Command()
        command.dry_run = True
        # `_save` is the only side effect; stub it so the fix can be exercised without a database
        # row, and so this test pins the FIELD SELECTION the command reports as changed.
        saved = {}

        def _capture(obj, fields, label):
            saved["fields"] = list(fields)

        command._save = _capture
        command._fix_parcel(parcel, cfg)

        self.assertEqual(parcel.map_metadata["center"], {"lat": cfg["latitude"], "lng": cfg["longitude"]})
        self.assertIsNone(parcel.polygon, "a boundary from the wrong county must not survive relocation")
        self.assertEqual(parcel.location_disclosure_level, "approximate")
        self.assertIn("map_metadata", saved["fields"])
        self.assertIn("polygon", saved["fields"])

    def test_a_parcel_already_correct_is_left_alone(self):
        """Idempotence, and the reason this command is safe to re-run in production."""
        from history.management.commands.backfill_demo_claim_safety import Command

        cfg = FIXTURES["solana"]
        parcel = Parcel(
            name="Already Fixed",
            area=10.0,
            location_disclosure_level="approximate",
            polygon=None,
            map_metadata={"center": {"lat": cfg["latitude"], "lng": cfg["longitude"]}, "zoom": 13},
        )

        command = Command()
        command.dry_run = True
        command._save = lambda *a, **k: self.fail("an already-correct parcel was rewritten")

        self.assertEqual(command._fix_parcel(parcel, cfg), 0)
