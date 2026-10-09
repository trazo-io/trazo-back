from datetime import date

from django.test import TestCase

from certifications.models import USDAOrganicOperation
from certifications.services.usda_organic_verifier import FUZZY_MATCH_THRESHOLD, USDAOrganicVerifier


class USDAOrganicVerifierPropertiesTest(TestCase):
    """Test verifier_name, source_identifier, supported_certification_types."""

    def setUp(self):
        self.verifier = USDAOrganicVerifier()

    def test_verifier_name(self):
        self.assertEqual(
            self.verifier.verifier_name,
            "USDA Organic Integrity Database",
        )

    def test_source_identifier(self):
        self.assertEqual(
            self.verifier.source_identifier,
            "usda_organic_integrity_db",
        )

    def test_supported_certification_types(self):
        types = self.verifier.supported_certification_types
        self.assertIsInstance(types, list)
        self.assertEqual(types, ["usda_organic"])


class NormalizeNameTest(TestCase):
    """Test the _normalize_name static method."""

    def test_strips_llc(self):
        self.assertEqual(USDAOrganicVerifier._normalize_name("Happy Farm LLC"), "happy")

    def test_strips_inc_and_the(self):
        self.assertEqual(
            USDAOrganicVerifier._normalize_name("The Green Valley Orchards Inc."),
            "green valley",
        )

    def test_strips_punctuation_and_ranch(self):
        self.assertEqual(
            USDAOrganicVerifier._normalize_name("Smith & Sons Ranch"),
            "smith sons",
        )

    def test_strips_multiple_keywords(self):
        self.assertEqual(
            USDAOrganicVerifier._normalize_name("The Estate Vineyards Company"),
            "",
        )

    def test_preserves_significant_words(self):
        self.assertEqual(
            USDAOrganicVerifier._normalize_name("Sunrise Meadow"),
            "sunrise meadow",
        )

    def test_handles_extra_whitespace(self):
        self.assertEqual(
            USDAOrganicVerifier._normalize_name("  Happy   Farm   LLC  "),
            "happy",
        )


class NormalizeStateToFullTest(TestCase):
    """Test _normalize_state_to_full (abbreviation -> full name)."""

    def test_abbreviation_to_full(self):
        self.assertEqual(USDAOrganicVerifier._normalize_state_to_full("CA"), "California")

    def test_lowercase_abbreviation(self):
        # len("ca") == 2, .upper() -> "CA"
        self.assertEqual(USDAOrganicVerifier._normalize_state_to_full("ca"), "California")

    def test_full_name_passthrough(self):
        self.assertEqual(
            USDAOrganicVerifier._normalize_state_to_full("California"),
            "California",
        )

    def test_unknown_abbreviation_passthrough(self):
        self.assertEqual(USDAOrganicVerifier._normalize_state_to_full("XX"), "XX")

    def test_strips_whitespace(self):
        self.assertEqual(USDAOrganicVerifier._normalize_state_to_full(" OR "), "Oregon")


class NormalizeStateToAbbrevTest(TestCase):
    """Test _normalize_state_to_abbrev (full name -> abbreviation)."""

    def test_full_name_to_abbreviation(self):
        self.assertEqual(USDAOrganicVerifier._normalize_state_to_abbrev("California"), "CA")

    def test_abbreviation_passthrough(self):
        self.assertEqual(USDAOrganicVerifier._normalize_state_to_abbrev("CA"), "CA")

    def test_lowercase_full_name(self):
        self.assertEqual(USDAOrganicVerifier._normalize_state_to_abbrev("california"), "CA")

    def test_unknown_full_name_returns_first_two(self):
        result = USDAOrganicVerifier._normalize_state_to_abbrev("Unknown State")
        self.assertEqual(result, "UN")

    def test_strips_whitespace(self):
        self.assertEqual(USDAOrganicVerifier._normalize_state_to_abbrev(" Oregon "), "OR")


class VerifyNoDataLoadedTest(TestCase):
    """Test verify() when no USDA data is loaded (count=0) -> self_reported."""

    def setUp(self):
        self.verifier = USDAOrganicVerifier()

    def test_returns_self_reported_when_no_data(self):
        result = self.verifier.verify("Happy Farm", "CA")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "self_reported")
        self.assertIn("not available", result.notes)


class VerifyWithDatabaseRecordsTest(TestCase):
    """Test verify() with real USDAOrganicOperation records in the test DB."""

    def setUp(self):
        self.verifier = USDAOrganicVerifier()
        self.snapshot_date = date(2025, 12, 1)

        self.certified_op = USDAOrganicOperation.objects.create(
            op_name="Earthbound Farm, LLC",
            op_name_normalized="earthbound",
            state="California",
            status="Certified",
            status_effective_date="2024-01-15",
            certifier_name="CCOF",
            certified_products="Avocados, Lemons, Oranges",
            scope_crops="Yes",
            scope_livestock=None,
            scope_handling="Yes",
            scope_wild_crops=None,
            data_snapshot_date=self.snapshot_date,
        )

        self.revoked_op = USDAOrganicOperation.objects.create(
            op_name="Shady Acres Farm",
            op_name_normalized="shady acres",
            state="California",
            status="Revoked",
            status_effective_date="2024-06-01",
            certifier_name="Oregon Tilth",
            certified_products="Tomatoes",
            scope_crops="Yes",
            data_snapshot_date=self.snapshot_date,
        )

        self.suspended_op = USDAOrganicOperation.objects.create(
            op_name="Suspended Valley Growers",
            op_name_normalized="suspended valley growers",
            state="Oregon",
            status="Suspended",
            certifier_name="Oregon Tilth",
            data_snapshot_date=self.snapshot_date,
        )

        self.surrendered_op = USDAOrganicOperation.objects.create(
            op_name="Old Times Ranch",
            op_name_normalized="old times",
            state="California",
            status="Surrendered",
            certifier_name="CCOF",
            data_snapshot_date=self.snapshot_date,
        )

    def test_verify_certified_operation(self):
        result = self.verifier.verify("Earthbound Farm", "California")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.certifier_name, "CCOF")
        self.assertGreater(result.confidence_score, FUZZY_MATCH_THRESHOLD)
        self.assertIn("Earthbound Farm, LLC", result.notes)
        self.assertEqual(result.source_url, "https://organic.ams.usda.gov/integrity/")

    def test_verify_certified_items_parsed(self):
        result = self.verifier.verify("Earthbound Farm", "CA")
        self.assertTrue(result.found)
        self.assertIsInstance(result.certified_items, list)
        self.assertIn("Avocados", result.certified_items)
        self.assertIn("Lemons", result.certified_items)
        self.assertIn("Oranges", result.certified_items)

    def test_verify_certification_scope_built(self):
        result = self.verifier.verify("Earthbound Farm", "CA")
        self.assertTrue(result.found)
        self.assertIn("Crops", result.certification_scope)
        self.assertIn("Handling", result.certification_scope)

    def test_verify_revoked_operation(self):
        result = self.verifier.verify("Shady Acres Farm", "CA")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "revoked")

    def test_verify_suspended_operation(self):
        result = self.verifier.verify("Suspended Valley Growers", "Oregon")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "suspended")

    def test_verify_surrendered_maps_to_revoked(self):
        result = self.verifier.verify("Old Times Ranch", "CA")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "revoked")

    def test_verify_with_state_abbreviation(self):
        result = self.verifier.verify("Earthbound Farm", "CA")
        self.assertTrue(result.found)
        self.assertEqual(result.status, "verified")

    def test_verify_not_found_wrong_name(self):
        result = self.verifier.verify("Completely Nonexistent Farm XYZ", "CA")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "not_found")

    def test_verify_not_found_wrong_state(self):
        result = self.verifier.verify("Earthbound Farm", "Texas")
        self.assertFalse(result.found)
        self.assertEqual(result.status, "not_found")

    def test_verify_raw_response_fields(self):
        result = self.verifier.verify("Earthbound Farm", "CA")
        self.assertTrue(result.found)
        self.assertIn("op_name", result.raw_response)
        self.assertIn("state", result.raw_response)
        self.assertIn("status", result.raw_response)
        self.assertIn("certifier", result.raw_response)
        self.assertIn("snapshot_date", result.raw_response)


class HealthCheckTest(TestCase):
    """Test health_check() with and without data loaded."""

    def setUp(self):
        self.verifier = USDAOrganicVerifier()

    def test_health_check_no_data(self):
        self.assertFalse(self.verifier.health_check())

    def test_health_check_with_data(self):
        USDAOrganicOperation.objects.create(
            op_name="Test Farm",
            op_name_normalized="test",
            state="California",
            status="Certified",
            data_snapshot_date=date(2025, 12, 1),
        )
        self.assertTrue(self.verifier.health_check())
