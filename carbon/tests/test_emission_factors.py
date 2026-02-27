"""
Test Suite for Emission Factors
Ensures emission factors are accurate and consistent with scientific research
"""

import unittest

from django.test import TestCase

from carbon.services.emission_factors import emission_factors


class TestEmissionFactorAccuracy(TestCase):
    """Test emission factors match scientific research and standards"""

    def test_nitrogen_emission_factor_accuracy(self):
        """Verify nitrogen emission factor matches current scientific research"""
        nitrogen_factor = emission_factors.get_fertilizer_factor("nitrogen")

        # According to recent Nature Scientific Reports research (2022):
        # Global average is 10.48 kg CO2e/kg N, with range 8-13 kg CO2e/kg N
        # Current value of 10.5 is within acceptable range (EPA + IPCC AR6)
        self.assertEqual(nitrogen_factor["value"], 10.5)
        self.assertEqual(nitrogen_factor["unit"], "kg CO2e per kg N")
        self.assertIn("EPA", nitrogen_factor["source"])

        # Verify components match research findings
        self.assertAlmostEqual(nitrogen_factor["production_component"], 2.6, delta=0.5)
        self.assertAlmostEqual(nitrogen_factor["field_component"], 7.9, delta=0.5)

    def test_phosphorus_emission_factor(self):
        """Verify phosphorus emission factor includes full lifecycle"""
        phosphorus_factor = emission_factors.get_fertilizer_factor("phosphorus")

        # Corrected value includes mining, processing, and transportation
        self.assertEqual(phosphorus_factor["value"], 1.25)
        self.assertEqual(phosphorus_factor["unit"], "kg CO2e per kg P2O5")

    def test_potassium_emission_factor(self):
        """Verify potassium emission factor"""
        potassium_factor = emission_factors.get_fertilizer_factor("potassium")

        # Corrected value includes energy-intensive potash refining
        self.assertEqual(potassium_factor["value"], 0.60)
        self.assertEqual(potassium_factor["unit"], "kg CO2e per kg K2O")

    def test_fuel_emission_factors_epa_compliance(self):
        """Verify fuel emission factors match EPA standards"""
        diesel_factor = emission_factors.get_fuel_factor("diesel")
        gasoline_factor = emission_factors.get_fuel_factor("gasoline")
        natural_gas_factor = emission_factors.get_fuel_factor("natural_gas")

        # EPA 2023 values
        self.assertEqual(diesel_factor["value"], 2.70)  # kg CO2e per liter
        self.assertEqual(gasoline_factor["value"], 2.32)  # kg CO2e per liter
        self.assertEqual(natural_gas_factor["value"], 1.92)  # kg CO2e per m³

        # Check EPA source attribution
        for factor in [diesel_factor, gasoline_factor, natural_gas_factor]:
            self.assertIn("EPA", factor["source"])
            self.assertEqual(factor["confidence"], "high")

    def test_electricity_emission_factors(self):
        """Verify electricity emission factors"""
        grid_factor = emission_factors.get_electricity_factor("grid")
        solar_factor = emission_factors.get_electricity_factor("solar")
        wind_factor = emission_factors.get_electricity_factor("wind")

        # US grid average from EPA eGRID
        self.assertEqual(grid_factor["value"], 0.40)  # kg CO2e per kWh

        # Renewable sources - operational only
        self.assertEqual(solar_factor["value"], 0.00)
        self.assertEqual(wind_factor["value"], 0.00)

    def test_factor_metadata_completeness(self):
        """Verify all factors have complete metadata"""
        # Test nitrogen factor metadata
        nitrogen = emission_factors.get_fertilizer_factor("nitrogen")
        required_fields = ["value", "unit", "source", "reference", "confidence", "last_verified"]

        for field in required_fields:
            self.assertIn(field, nitrogen)
            self.assertIsNotNone(nitrogen[field])

        # Verify confidence levels are valid
        valid_confidence = ["high", "medium", "low"]
        self.assertIn(nitrogen["confidence"], valid_confidence)

    def test_registry_version_information(self):
        """Test registry version and tracking"""
        metadata = emission_factors.get_metadata()

        self.assertIn("version", metadata)
        self.assertIn("last_updated", metadata)
        self.assertIn("EPA", metadata["data_source"])
        self.assertTrue(metadata["usda_factors_used"])


class TestEmissionFactorConsistency(TestCase):
    """Test consistency across different calculation modules"""

    def test_factor_consistency_across_services(self):
        """Ensure all services use the same emission factors"""
        from carbon.services.calculator import CarbonFootprintCalculator
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calculator = CarbonFootprintCalculator()
        event_calculator = EventCarbonCalculator()

        # All should use the centralized registry values
        registry_nitrogen = emission_factors.get_fertilizer_factor("nitrogen")["value"]
        calc_nitrogen = calculator.usda_factors["fertilizer"]["nitrogen"]

        self.assertEqual(calc_nitrogen, registry_nitrogen)
        self.assertEqual(calc_nitrogen, 10.5)  # Current EPA/IPCC value

    def test_no_legacy_values_in_use(self):
        """Ensure no modules are using outdated emission factors"""
        # Check that no modules use the old incorrect values
        deprecated_nitrogen = 5.86  # Old IPCC value
        deprecated_phosphorus = 0.20  # Old value missing processing energy
        deprecated_potassium = 0.15  # Old value missing refining energy

        # These should not appear in any active calculation
        from carbon.services.calculator import CarbonFootprintCalculator

        calculator = CarbonFootprintCalculator()

        self.assertNotEqual(calculator.usda_factors["fertilizer"]["nitrogen"], deprecated_nitrogen)
        self.assertNotEqual(calculator.usda_factors["fertilizer"]["phosphorus"], deprecated_phosphorus)
        self.assertNotEqual(calculator.usda_factors["fertilizer"]["potassium"], deprecated_potassium)

    def test_factor_validation_system(self):
        """Test the built-in factor validation"""
        validation = emission_factors.validate_factor_consistency()

        self.assertIn("valid", validation)
        self.assertIn("issues", validation)
        self.assertIn("factor_count", validation)

        # Should have a reasonable number of factors
        self.assertGreater(validation["factor_count"], 10)


class TestRegionalAdjustments(TestCase):
    """Test regional emission factor adjustments"""

    def test_climate_specific_factors(self):
        """Test climate-specific N2O adjustments"""
        # Get climate factors
        wet_climate = emission_factors.CLIMATE_SPECIFIC_FACTORS["wet_climate"]
        dry_climate = emission_factors.CLIMATE_SPECIFIC_FACTORS["dry_climate"]
        moderate_climate = emission_factors.CLIMATE_SPECIFIC_FACTORS["moderate_climate"]

        # Wet climates should have higher N2O emissions
        self.assertGreater(wet_climate["n2o_factor"], 1.0)
        self.assertEqual(wet_climate["n2o_factor"], 1.35)

        # Dry climates should have lower N2O emissions
        self.assertLess(dry_climate["n2o_factor"], 1.0)
        self.assertEqual(dry_climate["n2o_factor"], 0.85)

        # Moderate climates are baseline
        self.assertEqual(moderate_climate["n2o_factor"], 1.0)

    def test_application_method_efficiency(self):
        """Test application method efficiency factors"""
        methods = emission_factors.APPLICATION_METHOD_FACTORS

        # Slow release should have highest reduction
        self.assertEqual(methods["slow_release"]["n_reduction"], 0.25)

        # Precision should have significant reduction
        self.assertEqual(methods["precision"]["n_reduction"], 0.18)

        # Broadcast should have no reduction (baseline)
        self.assertEqual(methods["broadcast"]["n_reduction"], 0.0)

    def test_regional_grid_factors(self):
        """Test regional electricity grid factors"""
        regions = emission_factors.REGIONAL_FACTORS

        # California should have lower grid factor (renewable heavy)
        ca_factor = regions["california_central_valley"]["electricity_grid_factor"]
        self.assertEqual(ca_factor, 0.25)

        # Midwest should have higher factor (coal heavy)
        midwest_factor = regions["midwest_corn_belt"]["electricity_grid_factor"]
        self.assertEqual(midwest_factor, 0.45)

        # Pacific Northwest should have lowest (hydro)
        pnw_factor = regions["pacific_northwest"]["electricity_grid_factor"]
        self.assertEqual(pnw_factor, 0.15)


class TestOrganicCertificationFactors(TestCase):
    """Test organic certification benefits and requirements"""

    def test_organic_carbon_benefits(self):
        """Test organic practice carbon benefits"""
        organic_factors = emission_factors.ORGANIC_CERTIFICATION_FACTORS

        # Carbon sequestration benefit
        carbon_benefit = organic_factors["carbon_sequestration_benefit"]
        self.assertEqual(carbon_benefit["value"], 0.15)  # 15% additional

        # Nitrogen efficiency bonus
        nitrogen_bonus = organic_factors["nitrogen_efficiency_bonus"]
        self.assertEqual(nitrogen_bonus["value"], 0.20)  # 20% reduction

        # Pest management efficiency
        pest_efficiency = organic_factors["pest_management_efficiency"]
        self.assertEqual(pest_efficiency["value"], 0.30)  # 30% reduction

    def test_organic_certification_requirements(self):
        """Test organic certification requirements"""
        requirements = emission_factors.ORGANIC_CERTIFICATION_FACTORS["certification_requirements"]

        self.assertEqual(requirements["minimum_transition_period"], 3)  # years
        self.assertEqual(requirements["required_inspections"], 1)  # per year
        self.assertIn("field_history", requirements["documentation_requirements"])
        self.assertIn("synthetic_pesticides", requirements["prohibited_substances"])


if __name__ == "__main__":
    unittest.main()
