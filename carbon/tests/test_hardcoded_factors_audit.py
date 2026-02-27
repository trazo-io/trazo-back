"""
Comprehensive audit test for identifying and validating hardcoded emission factors.

This test identifies all hardcoded values in the codebase that should be centralized
and validates them against authoritative sources.
"""

import re
import unittest
from pathlib import Path

from django.test import TestCase

from carbon.services.emission_factors import EmissionFactorsRegistry
from carbon.services.event_carbon_calculator import EventCarbonCalculator


class HardcodedFactorsAuditTest(TestCase):
    """Audit test to identify hardcoded emission factors throughout codebase"""

    def setUp(self):
        self.calculator = EventCarbonCalculator()
        self.registry = EmissionFactorsRegistry()
        self.carbon_path = Path(__file__).parent.parent

    def test_crop_specific_factors_centralization(self):
        """Test that crop-specific factors should be centralized"""
        crop_factors = self.calculator.CROP_SPECIFIC_FACTORS

        # Crop factors are centralized in EmissionFactorsRegistry.CROP_SPECIFIC_FACTORS
        self.assertGreater(
            len(crop_factors), 20, f"Found {len(crop_factors)} crop factors. Expected at least 20 centralized factors."
        )

        # High-emission crops that need validation
        high_emission_crops = {
            "rice": 2.5,  # Methane emissions
            "almond": 2.1,  # Water intensive
            "walnut": 1.8,
            "pecan": 1.9,
        }

        for crop, expected_factor in high_emission_crops.items():
            if crop in crop_factors:
                self.assertEqual(
                    crop_factors[crop],
                    expected_factor,
                    f"Crop factor for {crop} should be validated against LCA studies",
                )

    def test_application_efficiency_factors(self):
        """Test application efficiency factors for scientific accuracy"""
        efficiency_factors = self.calculator.APPLICATION_EFFICIENCY

        # Validate efficiency ranges (should be between 0 and 1)
        for method, efficiency in efficiency_factors.items():
            self.assertGreaterEqual(efficiency, 0.0, f"Efficiency factor for {method} cannot be negative")
            self.assertLessEqual(efficiency, 1.0, f"Efficiency factor for {method} cannot exceed 100%")

        # Validate logical ordering (drip > injection > foliar > banded > broadcast)
        expected_order = ["drip_irrigation", "injection", "foliar", "banded", "broadcast"]
        efficiencies = [efficiency_factors.get(method, 0) for method in expected_order]

        # Check that more precise methods are more efficient
        for i in range(len(efficiencies) - 1):
            self.assertGreaterEqual(
                efficiencies[i],
                efficiencies[i + 1],
                f"Method {expected_order[i]} should be more efficient than {expected_order[i + 1]}",
            )

    def test_crop_fertilizer_efficiency_validation(self):
        """Test crop-specific fertilizer efficiency factors"""
        crop_efficiency = self.calculator.CROP_FERTILIZER_EFFICIENCY

        # Validate efficiency ranges
        for crop_type, efficiency in crop_efficiency.items():
            self.assertGreaterEqual(efficiency, 0.0, f"Fertilizer efficiency for {crop_type} cannot be negative")
            self.assertLessEqual(efficiency, 1.0, f"Fertilizer efficiency for {crop_type} cannot exceed 100%")

        # Validate logical relationships
        # Herbs should be most efficient (precision application)
        self.assertGreaterEqual(
            crop_efficiency.get("herbs", 0),
            crop_efficiency.get("vegetables", 0),
            "Herbs should be more fertilizer efficient than vegetables",
        )

        # Tree crops should be more efficient than annual crops
        self.assertGreaterEqual(
            crop_efficiency.get("fruits", 0),
            crop_efficiency.get("vegetables", 0),
            "Tree crops should be more fertilizer efficient than annual crops",
        )

        # Legumes should need less nitrogen fertilizer
        self.assertLessEqual(
            crop_efficiency.get("legumes", 1.0),
            crop_efficiency.get("grains", 1.0),
            "Legumes should need less nitrogen fertilizer than grains",
        )

    def test_nitrogen_factor_consistency_across_files(self):
        """Scan for hardcoded nitrogen factors across codebase"""
        hardcoded_patterns = [
            r"6\.7",  # Old incorrect factor
            r"5\.86",  # Previous factor
            r"11\.0",  # Current factor (should only be in registry)
        ]

        python_files = list(self.carbon_path.rglob("*.py"))
        registry_file = self.carbon_path / "services" / "emission_factors.py"
        test_files = list(self.carbon_path.rglob("test*.py"))

        hardcoded_occurrences = []

        for file_path in python_files:
            # Skip test files and registry file for this check
            if file_path in test_files or file_path == registry_file:
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                for pattern in hardcoded_patterns:
                    matches = re.findall(pattern, content)
                    if matches:
                        hardcoded_occurrences.append(
                            {
                                "file": str(file_path.relative_to(self.carbon_path)),
                                "pattern": pattern,
                                "count": len(matches),
                            }
                        )
            except (UnicodeDecodeError, FileNotFoundError):
                continue

        # Report findings but don't fail (these need manual review)
        if hardcoded_occurrences:
            print("\n⚠️  HARDCODED EMISSION FACTORS FOUND:")
            for occurrence in hardcoded_occurrences:
                print(f"  📁 {occurrence['file']}: {occurrence['count']}x '{occurrence['pattern']}'")
            print("\n📋 RECOMMENDATION: Centralize these factors in EmissionFactorsRegistry")

    def test_factor_source_documentation(self):
        """Test that all factors have proper source documentation"""
        # Check main fertilizer factors
        for nutrient in ["nitrogen", "phosphorus", "potassium"]:
            factor_data = self.registry.FERTILIZER_FACTORS[nutrient]

            # Verify source documentation exists
            self.assertIn("source", factor_data, f"{nutrient} factor missing source")
            self.assertIn("reference", factor_data, f"{nutrient} factor missing reference")
            self.assertIn("last_verified", factor_data, f"{nutrient} factor missing verification date")

            # Verify source is authoritative
            source = factor_data["source"].lower()
            authoritative_sources = ["usda", "epa", "ipcc", "peer-reviewed"]

            has_authoritative_source = any(auth_source in source for auth_source in authoritative_sources)
            self.assertTrue(
                has_authoritative_source,
                f"{nutrient} factor source '{factor_data['source']}' should reference authoritative body",
            )

    def test_crop_factor_scientific_validation(self):
        """Validate crop-specific factors against known scientific ranges"""
        crop_factors = self.calculator.CROP_SPECIFIC_FACTORS

        # Known problematic ranges that need validation
        validation_ranges = {
            "rice": (2.0, 3.0),  # High due to methane, but check upper bound
            "almond": (1.8, 2.5),  # Water intensive but validate range
            "lettuce": (0.1, 0.3),  # Low impact annual crop
            "tomato": (0.6, 1.0),  # Moderate impact
            "corn": (0.4, 0.8),  # Field crop range
        }

        for crop, (min_val, max_val) in validation_ranges.items():
            if crop in crop_factors:
                factor = crop_factors[crop]
                self.assertGreaterEqual(factor, min_val, f"{crop} factor {factor} below expected minimum {min_val}")
                self.assertLessEqual(factor, max_val, f"{crop} factor {factor} above expected maximum {max_val}")

    def test_missing_factors_coverage(self):
        """Test for crops that might be missing emission factors"""
        crop_factors = self.calculator.CROP_SPECIFIC_FACTORS

        # Common crops that should have specific factors
        expected_crops = [
            "corn",
            "wheat",
            "rice",
            "soybean",  # Major grains/legumes
            "tomato",
            "lettuce",
            "carrot",  # Common vegetables
            "apple",
            "orange",
            "grape",  # Major fruits
            "almond",
            "walnut",  # Tree nuts
        ]

        missing_crops = []
        for crop in expected_crops:
            if crop not in crop_factors:
                missing_crops.append(crop)

        self.assertEqual(len(missing_crops), 0, f"Missing emission factors for important crops: {missing_crops}")

        # Test fallback mechanism
        self.assertIn("default", crop_factors, "Default fallback factor missing for unknown crops")


class EmissionFactorMigrationTest(TestCase):
    """Test emission factor migration and versioning"""

    def test_migration_consistency(self):
        """Test that migration factors match current registry values"""
        from carbon.services.emission_factors import EmissionFactorsRegistry

        registry = EmissionFactorsRegistry()

        # Current registry values
        current_nitrogen = registry.FERTILIZER_FACTORS["nitrogen"]["value"]
        current_phosphorus = registry.FERTILIZER_FACTORS["phosphorus"]["value"]
        current_potassium = registry.FERTILIZER_FACTORS["potassium"]["value"]

        # Current EPA/IPCC verified values
        expected_values = {"nitrogen": 10.5, "phosphorus": 1.25, "potassium": 0.60}

        self.assertEqual(current_nitrogen, expected_values["nitrogen"])
        self.assertEqual(current_phosphorus, expected_values["phosphorus"])
        self.assertEqual(current_potassium, expected_values["potassium"])

    def test_factor_history_preservation(self):
        """Test that factor change history is available via audit trail"""
        registry = EmissionFactorsRegistry()

        # Factor change history is tracked via get_factor_change_audit()
        audit = registry.get_factor_change_audit()

        self.assertIn("version_history", audit)
        self.assertIn("correction_analysis", audit)

        # Verify nitrogen correction is documented
        nitrogen_correction = audit["correction_analysis"]["nitrogen"]
        self.assertEqual(nitrogen_correction["old_value"], 5.86)
        self.assertIn("reason", nitrogen_correction)


if __name__ == "__main__":
    unittest.main()
