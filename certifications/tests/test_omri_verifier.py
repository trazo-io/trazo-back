"""
OMRI / National List verifier tests — Sprint 3.1.
"""

from django.test import TestCase

from certifications.models import NationalListSubstance, OMRIProduct
from certifications.services.omri_verifier import OMRIProductVerifier


class OMRIVerifierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized="copper hydroxide",
            cfr_section="205.601",
            subsection="i",
            category="disease_control",
            status="allowed",
            restriction_notes="Minimize soil accumulation.",
        )
        NationalListSubstance.objects.create(
            substance_name="Rotenone",
            substance_name_normalized="rotenone",
            cfr_section="205.602",
            subsection=None,
            category="prohibited",
            status="prohibited",
            restriction_notes=None,
        )
        OMRIProduct.objects.create(
            omri_id="OMRI-99999",
            product_name="Example Organic Fungicide",
            manufacturer="Test Co",
        )

    def setUp(self):
        self.verifier = OMRIProductVerifier()

    def test_health_check_succeeds_with_seeded_data(self):
        self.assertTrue(self.verifier.health_check())

    def test_omri_id_lookup_returns_listing_match(self):
        result = self.verifier.verify("whatever", certification_number="OMRI-99999")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "listing_match")  # run 8: a listing never verifies
        self.assertIn("OMRI-99999", result.notes)

    def test_exact_name_match_allowed(self):
        result = self.verifier.verify("Copper hydroxide")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "listing_match")  # run 8: a listing never verifies
        self.assertEqual(result.confidence_score, 1.0)
        self.assertIn("205.601", result.certifier_name)

    def test_contained_name_match_allowed(self):
        # "Copper Hydroxide 25% WP" should still match "Copper hydroxide" via containment.
        result = self.verifier.verify("Copper Hydroxide 25% WP")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "listing_match")  # run 8: a listing never verifies
        self.assertLess(result.confidence_score, 1.0)  # containment match, not exact
        self.assertIn("contained", result.notes)

    def test_generic_word_does_not_falsely_match(self):
        # "hydroxide" alone must NOT match "Copper hydroxide" — farmer could mean
        # sodium hydroxide (prohibited conventional). False-positive safety check.
        result = self.verifier.verify("hydroxide")
        self.assertFalse(result.found)

    def test_sodium_hydroxide_is_not_found(self):
        # Explicit scenario: farmer applies sodium hydroxide (NOT on the allowed list).
        # Must return not_found, never match "copper hydroxide".
        result = self.verifier.verify("Sodium hydroxide")
        self.assertFalse(result.found)

    def test_longest_match_wins(self):
        # When both "Copper" and "Copper hydroxide" could match, the longest wins.
        NationalListSubstance.objects.create(
            substance_name="Copper",
            substance_name_normalized="copper",
            cfr_section="205.601",
            subsection="z",
            status="allowed",
        )
        result = self.verifier.verify("Copper hydroxide formulation")
        self.assertTrue(result.found)
        # Must be the more specific match, not the generic one.
        self.assertIn("Copper hydroxide", result.notes)

    def test_prohibited_substance_flagged(self):
        result = self.verifier.verify("Rotenone")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "revoked")  # prohibited
        self.assertIn("PROHIBITED", result.notes)
        self.assertIn("disqualifies", result.notes)

    def test_unknown_substance_not_found(self):
        result = self.verifier.verify("Totally Made Up Chemical")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "not_found")

    def test_empty_name_no_omri_returns_not_found(self):
        result = self.verifier.verify("")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "not_found")

    def test_bogus_omri_id_falls_through_to_name_match(self):
        # Bogus OMRI ID but valid name -> should still match via National List
        result = self.verifier.verify("Copper hydroxide", certification_number="OMRI-NOPE")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "listing_match")  # run 8: a listing never verifies
        self.assertIn("205.601", result.certifier_name)
