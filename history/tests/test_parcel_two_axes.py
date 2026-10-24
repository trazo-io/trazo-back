"""Answering a question and holding the document that backs it are different facts.

WHAT WAS WRONG (2026-09-24)
---------------------------
`parcel_application_status` ran six checks, one of which was:

    has_map = bool(parcel.polygon) or bool(parcel_map_documents(parcel))

so RECORDED GEOMETRY ALONE satisfied "map". A parcel with a drawn boundary and no uploaded map
reported `complete`, and the packet printed

    Parcel application: complete

one page above section E's own

    [REVIEW] No operator-supplied map is attached.

One document, two verdicts, and the more confident one was the wrong one — a reviewer reading
the header had no reason to keep reading.

THE SPLIT
---------
  answers axis   the five questions. The map term LEFT this axis entirely: a map is evidence,
                 not an answer, and leaving it here is what put an attachment requirement in
                 both halves.
  evidence axis  graded, never boolean, and never an adequacy verdict.

⛔ WHAT THIS MUST NOT BECOME. A generated schematic is not worthless — it carries a north arrow,
the boundary, total acreage and compass-labelled adjoining land, which is a real subset of CCOF
ORGB49 §E's eleven elements. So `schematic` is a state, not a failure. Equally, no state here
means "this satisfies WSDA/CCOF/OTCO": Trazo has not run that check and must not imply it.

⛔ EVERY NEGATIVE ASSERTION IN THIS FILE CARRIES A PREMISE. Three guards earlier in this same
correction pass passed vacuously because the fixture never reached the code under test, and all
three were absence-assertions. An `assertNotIn` that never loaded the thing it is looking for
proves nothing.
"""

from datetime import date

from django.test import TestCase

from company.models import Company, Establishment
from product.models import Parcel
from product.services.parcel_application_status import (
    GEOMETRY_AREA_TOLERANCE,
    parcel_application_status,
    parcel_evidence_status,
)


#: A ~4 ha square near Naches, WA. Built from the stated area so the two agree by construction.
def _square_ring(center_lon, center_lat, hectares):
    import math

    side_m = math.sqrt(hectares * 10_000.0)
    half_lat = (side_m / 2.0) / 111_132.0
    half_lon = (side_m / 2.0) / (111_320.0 * math.cos(math.radians(center_lat)))
    return [
        [center_lon - half_lon, center_lat - half_lat],
        [center_lon + half_lon, center_lat - half_lat],
        [center_lon + half_lon, center_lat + half_lat],
        [center_lon - half_lon, center_lat + half_lat],
        [center_lon - half_lon, center_lat - half_lat],
    ]


class ParcelTwoAxesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Two Axes Co")
        cls.establishment = Establishment.objects.create(name="Two Axes Farm", company=cls.company, state="WA")

    def _parcel(self, name, *, area_ha=4.0, polygon=True, answered=True, geometry_ha=None):
        """A parcel whose ANSWERS are complete unless `answered=False`, and whose geometry
        agrees with its stated area unless `geometry_ha` says otherwise."""
        ring = _square_ring(-120.74, 46.76, geometry_ha if geometry_ha else area_ha)
        parcel = Parcel.objects.create(
            name=name,
            establishment=self.establishment,
            area=area_ha,
            apn="000000-00001" if answered else "",
            date_began_managing=date(2011, 3, 1) if answered else None,
            polygon={"type": "Polygon", "coordinates": [ring]} if polygon else None,
            buffer_zones=[{"direction": "north", "adjoining_land_use": "County road"}] if answered else [],
            application_answers={"currently_certified": "yes"} if answered else {},
        )
        if answered:
            for year in (2023, 2024, 2025):
                parcel.crop_history.create(year=year, crop_grown="Apples")
        return parcel

    # -- the split itself --------------------------------------------------------------------

    def test_the_map_term_appears_in_exactly_one_axis(self):
        """⛔ The attachment requirement must not live in both halves.

        ⚠️ THE FIXTURE IS THE TEST. This must run on a parcel with NO geometry and NO upload —
        the only state in which the old `has_map` check would have appended "map". The first
        cut used a parcel WITH a polygon, so `answers_missing` was empty, the loop body never
        executed, and restoring the original defect broke nothing. Its "premise" was
        `assertTrue(missing == [] or missing)`, which is true of every list.
        """
        parcel = self._parcel("Mapless", polygon=False, answered=False)
        status = parcel_application_status(parcel)

        self.assertTrue(
            status["answers_missing"],
            "premise: this fixture must leave answers outstanding, or the loop below is empty " "and asserts nothing",
        )
        for key in status["answers_missing"]:
            self.assertNotIn("map", key, f"the answers axis still carries a map term: {key}")

        # And the same parcel, fully answered but still map-less: the answers axis must reach
        # `complete` WITHOUT a map, which is the behaviour the split exists to produce.
        answered = self._parcel("Mapless answered", polygon=False)
        answered_status = parcel_application_status(answered)
        self.assertEqual(
            answered_status["answers_state"],
            "complete",
            "a map is evidence, not an answer — its absence must not hold the answers axis open",
        )
        self.assertEqual(answered_status["evidence_state"], "outstanding")

    def test_geometry_alone_completes_the_answers_but_not_the_evidence(self):
        """The exact Cascade Ridge shape: boundary recorded, no operator map."""
        parcel = self._parcel("Geometry only")
        status = parcel_application_status(parcel)

        self.assertEqual(status["answers_state"], "complete")
        self.assertEqual(status["state"], "complete", "the legacy alias tracks the answers axis")
        # …and the evidence axis says what is actually outstanding.
        self.assertEqual(status["evidence_state"], "outstanding")
        self.assertIn("operator_map", status["evidence_missing"])
        self.assertEqual(status["evidence_detail"]["map"], "schematic")

    def test_a_parcel_with_nothing_is_outstanding_on_both(self):
        parcel = self._parcel("Empty", polygon=False, answered=False)
        status = parcel_application_status(parcel)
        self.assertNotEqual(status["answers_state"], "complete")
        self.assertEqual(status["evidence_state"], "outstanding")
        self.assertIn("map", status["evidence_missing"])

    # -- the graded map states ---------------------------------------------------------------

    def test_geometry_that_agrees_with_the_stated_area_reads_as_a_schematic(self):
        parcel = self._parcel("Agreeing", area_ha=4.0)
        detail = parcel_evidence_status(parcel)["detail"]
        self.assertEqual(detail["map"], "schematic")
        self.assertNotIn(
            "map_geometry_disagrees_with_area",
            parcel_evidence_status(parcel)["missing"],
        )

    def test_geometry_that_disagrees_with_the_stated_area_is_flagged_unverified(self):
        """A placeholder boundary, or one drawn on the wrong field, looks exactly like a real
        one — structurally valid, three or more well-formed points. The only cheap signal is
        whether it covers the area the operator says the parcel covers."""
        parcel = self._parcel("Disagreeing", area_ha=4.0, geometry_ha=40.0)
        evidence = parcel_evidence_status(parcel)
        self.assertEqual(evidence["detail"]["map"], "geometry_unverified")
        self.assertIn("map_geometry_disagrees_with_area", evidence["missing"])
        # The numbers travel so the page can state the comparison rather than just the verdict.
        self.assertIn("map_area_derived_ha", evidence["detail"])
        self.assertIn("map_area_stated_ha", evidence["detail"])

    def test_the_tolerance_is_wide_enough_for_a_hand_drawn_boundary(self):
        """Premise-carrying: a 20% drift must NOT flag, or the signal is noise."""
        self.assertGreater(GEOMETRY_AREA_TOLERANCE, 0.2)
        parcel = self._parcel("Slightly off", area_ha=4.0, geometry_ha=4.8)
        evidence = parcel_evidence_status(parcel)
        self.assertEqual(
            evidence["detail"]["map"],
            "schematic",
            "a traced boundary is not a survey; flagging every 20% drift makes the flag useless",
        )

    def test_a_parcel_with_no_geometry_and_no_upload_reads_as_no_map(self):
        parcel = self._parcel("No map", polygon=False)
        evidence = parcel_evidence_status(parcel)
        self.assertEqual(evidence["detail"]["map"], "none")
        self.assertIn("map", evidence["missing"])

    # -- what the evidence axis must never say ------------------------------------------------

    def test_no_evidence_state_asserts_that_a_map_satisfies_a_certifier(self):
        """⛔ Trazo has not run any agent's element checklist and must not imply it.

        PREMISE first: the states below are genuinely produced, so the absence of the forbidden
        words is evidence rather than an empty read.
        """
        produced = set()
        for name, kwargs in (
            ("A", {}),
            ("B", {"geometry_ha": 40.0}),
            ("C", {"polygon": False}),
        ):
            evidence = parcel_evidence_status(self._parcel(f"Claims {name}", **kwargs))
            produced.add(evidence["detail"]["map"])
            blob = " ".join([evidence["state"], *evidence["missing"], *map(str, evidence["detail"].values())])
            for forbidden in ("satisfies", "compliant", "meets the requirement", "approved", "sufficient"):
                self.assertNotIn(forbidden, blob.lower(), f"{name}: evidence state claims adequacy")
        self.assertEqual(
            produced,
            {"schematic", "geometry_unverified", "none"},
            "premise: all three map states were exercised",
        )
