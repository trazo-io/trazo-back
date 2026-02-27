"""
Unit tests for anhydrous ammonia density fix.
Ensures accurate carbon calculations for high-nitrogen fertilizers.
"""

import unittest

from carbon.services.verified_emission_factors import VerifiedEmissionFactors


class TestAnhydrousAmmoniaDensityFix(unittest.TestCase):
    """Test suite for anhydrous ammonia carbon calculation accuracy."""

    def test_anhydrous_ammonia_density(self):
        """Test that anhydrous ammonia (82-0-0) uses correct density."""
        npk_content = {"N": 82, "P": 0, "K": 0}
        application_method = "injection"

        density = VerifiedEmissionFactors._get_fertilizer_density(npk_content, application_method)

        # Anhydrous ammonia should use 0.68 kg/L, not 1.0 kg/L
        self.assertEqual(density, 0.68, "Anhydrous ammonia density should be 0.68 kg/L")

    def test_anhydrous_ammonia_calculation_accuracy(self):
        """Test complete calculation for 300L anhydrous ammonia on 2.0 Ha."""
        result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type="FE",
            volume_liters=300.0,
            area_hectares=2.0,
            npk_content={"N": 82, "P": 0, "K": 0},
            application_method="injection",
        )

        breakdown = result["breakdown"]

        # Verify key breakdown fields exist
        self.assertIn("chemical_mass_kg", breakdown)
        self.assertIn("nitrogen_kg", breakdown)
        self.assertIn("manufacturing_emissions_kg_co2e", breakdown)
        self.assertIn("application_emissions_kg_co2e", breakdown)

        # Expected: 300L x 0.68 kg/L = 204 kg fertilizer mass
        expected_fertilizer_mass = 204.0
        self.assertAlmostEqual(breakdown["chemical_mass_kg"], expected_fertilizer_mass, places=1)

        # Expected: 204 kg x 0.82 = 167.28 kg nitrogen
        expected_nitrogen_mass = 167.28
        self.assertAlmostEqual(breakdown["nitrogen_kg"], expected_nitrogen_mass, places=1)

        # Manufacturing: 167.28 kg N x 10.5 kg CO2e/kg N = 1756.44 kg CO2e
        expected_manufacturing = expected_nitrogen_mass * 10.5
        self.assertAlmostEqual(breakdown["manufacturing_emissions_kg_co2e"], expected_manufacturing, places=0)

        # Total should be manufacturing + application (fuel)
        total = result["co2e_kg"]
        self.assertGreater(total, expected_manufacturing, "Total should include application emissions")

        # With density fix (0.68), total should be less than with wrong density (1.0)
        # Wrong density: 300*1.0*0.82*10.5 = 2583 vs correct ~1765
        self.assertLess(total, 2000, "Should not return inflated emissions from wrong density")

    def test_other_fertilizer_densities(self):
        """Test that other fertilizer types use appropriate densities."""

        # UAN 28% solution (liquid nitrogen)
        uan_density = VerifiedEmissionFactors._get_fertilizer_density({"N": 28, "P": 0, "K": 0}, "injection")
        self.assertEqual(uan_density, 1.30, "UAN solution should use 1.30 kg/L")

        # Standard liquid fertilizer
        liquid_density = VerifiedEmissionFactors._get_fertilizer_density({"N": 10, "P": 10, "K": 10}, "spray")
        self.assertEqual(liquid_density, 1.25, "Standard liquid fertilizer should use 1.25 kg/L")

        # Granular fertilizer
        granular_density = VerifiedEmissionFactors._get_fertilizer_density({"N": 16, "P": 16, "K": 16}, "broadcast")
        self.assertEqual(granular_density, 0.80, "Granular fertilizer should use 0.80 kg/L")

    def test_regression_prevention(self):
        """Ensure fix doesn't break other fertilizer calculations."""

        # Test standard 10-10-10 fertilizer (should not be affected)
        result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type="FE",
            volume_liters=100.0,
            area_hectares=1.0,
            npk_content={"N": 10, "P": 10, "K": 10},
            application_method="broadcast",
        )

        # Should calculate properly with 0.80 kg/L density for granular
        expected_fertilizer_mass = 80.0  # 100L x 0.80 kg/L
        self.assertAlmostEqual(result["breakdown"]["chemical_mass_kg"], expected_fertilizer_mass, places=1)

        # Should have reasonable total emissions (not inflated)
        self.assertGreater(result["co2e_kg"], 10, "Should have some emissions")
        self.assertLess(result["co2e_kg"], 200, "Should not be inflated")

    def test_scientific_accuracy(self):
        """Verify calculations align with EPA emission factors."""

        result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type="FE",
            volume_liters=300.0,
            area_hectares=2.0,
            npk_content={"N": 82, "P": 0, "K": 0},
            application_method="injection",
        )

        breakdown = result["breakdown"]

        # Verify EPA factors are being used
        # Nitrogen: 10.5 kg CO2e/kg N (manufacturing + field N2O, EPA + IPCC AR6)
        self.assertEqual(breakdown["epa_nitrogen_factor_kg_co2_per_kg_n"], 10.5)
        self.assertEqual(breakdown["epa_diesel_factor_kg_co2_per_gallon"], 10.21)

        # Verify CO2e per kg N ratio is reasonable
        nitrogen_kg = breakdown["nitrogen_kg"]
        total_co2e = result["co2e_kg"]
        co2e_per_kg_n = total_co2e / nitrogen_kg

        # Should be close to 10.5 (manufacturing + N2O) + small application fuel component
        self.assertGreater(co2e_per_kg_n, 10.4, "CO2e per kg N too low")
        self.assertLess(co2e_per_kg_n, 10.6, "CO2e per kg N too high")


if __name__ == "__main__":
    unittest.main()
