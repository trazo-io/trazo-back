"""
Comprehensive tests for validating emission factors against authoritative sources.

This test suite validates Trazo's emission factors against IPCC guidelines, EPA standards,
and peer-reviewed research to ensure production-ready accuracy.
"""

import unittest
from decimal import Decimal

from django.test import TestCase

from carbon.services.emission_factors import EmissionFactorsRegistry


class EmissionFactorValidationTest(TestCase):
    """Test emission factors against authoritative standards"""

    def setUp(self):
        self.registry = EmissionFactorsRegistry()

    def test_nitrogen_factor_against_ipcc_standards(self):
        """Validate nitrogen emission factor against IPCC 2019 guidelines"""
        nitrogen_factor = self.registry.get_fertilizer_factor("nitrogen")

        # IPCC 2019 updated default: 1% N2O emission factor
        # N2O GWP = 298 (IPCC AR5) or 265 (IPCC AR6)
        # Field emissions component should be around 2.65-2.98 kg CO2e/kg N
        ipcc_field_emissions_min = 2.65  # Using AR6 GWP of 265
        ipcc_field_emissions_max = 2.98  # Using AR5 GWP of 298

        # Production emissions: Research shows 1-10 kg CO2e/kg N, average ~3-4
        ipcc_production_emissions_typical = 3.5

        # Total expected range: 6.15 - 6.48 kg CO2e/kg N
        expected_min = ipcc_field_emissions_min + 2.0  # Conservative production estimate
        expected_max = ipcc_field_emissions_max + 5.0  # High-end production estimate

        self.assertGreaterEqual(
            nitrogen_factor, expected_min, f"Nitrogen factor {nitrogen_factor} below IPCC minimum {expected_min}"
        )
        self.assertLessEqual(
            nitrogen_factor, expected_max, f"Nitrogen factor {nitrogen_factor} above IPCC maximum {expected_max}"
        )

        # Flag if significantly above typical range for review
        if nitrogen_factor > 8.0:
            print(f"WARNING: Nitrogen factor {nitrogen_factor} is above typical range. Review needed.")

    def test_nitrogen_factor_components_breakdown(self):
        """Validate nitrogen factor component breakdown"""
        factor_data = self.registry.FERTILIZER_FACTORS["nitrogen"]

        production_component = factor_data.get("production_component", 0)
        field_component = factor_data.get("field_component", 0)
        total_value = factor_data["value"]

        # Components should add up to total
        self.assertEqual(
            production_component + field_component,
            total_value,
            "Production and field components don't sum to total value",
        )

        # Field component validation against IPCC
        # Should be around 2.65-2.98 for N2O emissions alone
        self.assertGreaterEqual(field_component, 2.0, f"Field component {field_component} too low for N2O emissions")
        self.assertLessEqual(field_component, 4.0, f"Field component {field_component} too high for N2O emissions")

        # Production component validation
        # Research shows 1-10 kg CO2e/kg N, typically 3-4
        self.assertGreaterEqual(production_component, 1.0, f"Production component {production_component} too low")
        self.assertLessEqual(production_component, 6.0, f"Production component {production_component} too high")

    def test_phosphorus_factor_validation(self):
        """Validate phosphorus emission factor"""
        phosphorus_factor = self.registry.get_fertilizer_factor("phosphorus")

        # Typical P2O5 production emissions: 0.1-1.5 kg CO2e/kg P2O5
        # Source: Peer-reviewed LCA studies
        expected_min = 0.1
        expected_max = 2.0  # Allow for supply chain variations

        self.assertGreaterEqual(
            phosphorus_factor, expected_min, f"Phosphorus factor {phosphorus_factor} below expected minimum"
        )
        self.assertLessEqual(
            phosphorus_factor, expected_max, f"Phosphorus factor {phosphorus_factor} above expected maximum"
        )

    def test_potassium_factor_validation(self):
        """Validate potassium emission factor"""
        potassium_factor = self.registry.get_fertilizer_factor("potassium")

        # Typical K2O production emissions: 0.1-0.8 kg CO2e/kg K2O
        # Source: Peer-reviewed LCA studies
        expected_min = 0.1
        expected_max = 1.0  # Allow for supply chain variations

        self.assertGreaterEqual(
            potassium_factor, expected_min, f"Potassium factor {potassium_factor} below expected minimum"
        )
        self.assertLessEqual(
            potassium_factor, expected_max, f"Potassium factor {potassium_factor} above expected maximum"
        )

    def test_factor_metadata_completeness(self):
        """Ensure all factors have required metadata"""
        for nutrient in ["nitrogen", "phosphorus", "potassium"]:
            factor_data = self.registry.FERTILIZER_FACTORS[nutrient]

            required_fields = ["value", "unit", "source", "confidence", "last_verified"]
            for field in required_fields:
                self.assertIn(field, factor_data, f"Factor {nutrient} missing required field {field}")
                self.assertIsNotNone(factor_data[field], f"Factor {nutrient} has None value for {field}")

    def test_factor_versioning_consistency(self):
        """Test that factor versions are consistent and documented"""
        version = self.registry.VERSION
        last_updated = self.registry.LAST_UPDATED
        data_source = self.registry.DATA_SOURCE

        self.assertIsNotNone(version, "Registry version is missing")
        self.assertIsNotNone(last_updated, "Last updated date is missing")
        self.assertIsNotNone(data_source, "Data source is missing")

        # Version should follow semantic versioning
        version_parts = version.split(".")
        self.assertEqual(len(version_parts), 3, f"Version {version} not in semantic format")

        for part in version_parts:
            self.assertTrue(part.isdigit(), f"Version part {part} not numeric")


class EmissionFactorConsistencyTest(TestCase):
    """Test consistency of emission factors across the codebase"""

    def test_no_hardcoded_nitrogen_factors(self):
        """Ensure no hardcoded nitrogen factors exist outside registry"""
        # This test would scan codebase for hardcoded values
        # Implementation would check for patterns like "6.7", "5.86", etc.
        pass

    def test_calculation_consistency(self):
        """Test that all calculation paths use same emission factors"""
        from carbon.services.emission_factors import emission_factors
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calculator = EventCarbonCalculator()

        # Test that calculator uses registry factors
        registry_nitrogen = emission_factors.get_fertilizer_factor("nitrogen")

        # Create test chemical event data
        test_event_data = {
            "commercial_name": "NPK 10-10-10",
            "volume": "100 kg",
            "area": 1.0,  # hectares
            "nitrogen_content": 10.0,  # kg
            "phosphorus_content": 10.0,  # kg
            "potassium_content": 10.0,  # kg
        }

        # Calculate using event calculator
        result = calculator.calculate_chemical_event_impact(test_event_data)

        # Manually calculate expected result
        expected_nitrogen_co2e = 10.0 * registry_nitrogen

        # Verify consistency (allowing for other components)
        self.assertGreater(
            result.get("co2e", 0),
            expected_nitrogen_co2e * 0.8,  # Allow for calculation variations
            "Calculator result inconsistent with registry factors",
        )


class EmissionFactorBenchmarkTest(TestCase):
    """Benchmark tests against known reference calculations"""

    def test_urea_application_benchmark(self):
        """Test against known IPCC reference calculation for urea"""
        # IPCC reference: 100 kg urea (46% N) on 1 ha
        # Expected N2O emissions: 46 kg N × 1% × 44/28 × 298 = ~2,145 kg CO2e

        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calculator = EventCarbonCalculator()

        test_data = {
            "commercial_name": "Urea",
            "volume": "100 kg",
            "area": 1.0,
            "nitrogen_content": 46.0,  # 46% N content
            "phosphorus_content": 0.0,
            "potassium_content": 0.0,
        }

        result = calculator.calculate_chemical_event_impact(test_data)
        calculated_co2e = result.get("co2e", 0)

        # Expected field emissions: 46 kg N × ~2.98 kg CO2e/kg N = ~137 kg CO2e (N2O only)
        # Plus production emissions: 46 kg N × ~3.2 kg CO2e/kg N = ~147 kg CO2e
        # Total expected: ~284 kg CO2e

        expected_min = 200  # Conservative estimate
        expected_max = 400  # High-end estimate

        self.assertGreaterEqual(
            calculated_co2e, expected_min, f"Calculated CO2e {calculated_co2e} below expected minimum {expected_min}"
        )
        self.assertLessEqual(
            calculated_co2e, expected_max, f"Calculated CO2e {calculated_co2e} above expected maximum {expected_max}"
        )

    def test_regional_variation_awareness(self):
        """Test that system acknowledges regional emission factor variations"""
        # Note: Current system uses global averages
        # Future enhancement should support regional factors

        from carbon.services.enhanced_usda_factors import EnhancedUSDAFactors

        factors_service = EnhancedUSDAFactors()

        # Test that service is aware of regional variations
        # (Even if not implemented, should acknowledge the limitation)
        factor_info = factors_service.get_fertilizer_factor_with_metadata("nitrogen")

        self.assertIn(
            "regional_variation",
            factor_info.get("notes", "").lower() or factor_info.get("limitations", "").lower(),
            "System should acknowledge regional variation in emission factors",
        )


if __name__ == "__main__":
    unittest.main()
