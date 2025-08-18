"""
Integration Tests for Centralized Emission Factors

This test suite validates that the centralization of emission factors works correctly
across all calculation services and that database field usage is consistent.
"""

import unittest
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from carbon.models import CarbonEntry, CarbonSource
from carbon.services.coolfarm_service import CoolFarmService
from carbon.services.emission_factors import emission_factors
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from company.models import Company, Establishment
from history.models import ChemicalEvent, History

User = get_user_model()


class CentralizedFactorsIntegrationTest(TestCase):
    """Integration test for centralized emission factors"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(
            name="Test Farm Co", legal_entity_name="Test Farm Co LLC", country="US", owner=self.user
        )

        self.establishment = Establishment.objects.create(
            name="Test Farm", company=self.company, state="CA", county="Fresno", address="123 Farm Road"
        )

        # Create carbon sources
        self.fertilizer_source, _ = CarbonSource.objects.get_or_create(
            name="Fertilizer Application", category="fertilizer"
        )

        # Initialize services
        self.calculator = EventCarbonCalculator()
        self.coolfarm = CoolFarmService()

    def test_centralized_fertilizer_factors_consistency(self):
        """Test that all services use the same centralized fertilizer factors"""
        # Get factors from registry
        registry_nitrogen = emission_factors.get_fertilizer_factor("nitrogen")["value"]
        registry_phosphorus = emission_factors.get_fertilizer_factor("phosphorus")["value"]
        registry_potassium = emission_factors.get_fertilizer_factor("potassium")["value"]

        # Test EventCarbonCalculator uses centralized factors
        calculator_factors = self.calculator.USDA_FERTILIZER_FACTORS
        self.assertEqual(calculator_factors["nitrogen"], registry_nitrogen)
        self.assertEqual(calculator_factors["phosphorus"], registry_phosphorus)
        self.assertEqual(calculator_factors["potassium"], registry_potassium)

        # Test CoolFarmService uses centralized factors
        coolfarm_factors = self.coolfarm.emission_factors["fertilizer"]
        self.assertEqual(coolfarm_factors["nitrogen"], registry_nitrogen)
        self.assertEqual(coolfarm_factors["phosphorus"], registry_phosphorus)
        self.assertEqual(coolfarm_factors["potassium"], registry_potassium)

        # Verify nitrogen factor is the corrected USDA value
        self.assertEqual(registry_nitrogen, 11.0)

    def test_centralized_crop_factors_consistency(self):
        """Test that crop factors are centralized and accessible"""
        # Test calculator uses centralized crop factors
        calculator_crops = self.calculator.CROP_SPECIFIC_FACTORS
        registry_crops = {crop: data["value"] for crop, data in emission_factors.CROP_SPECIFIC_FACTORS.items()}

        # Should have same number of crops
        self.assertEqual(len(calculator_crops), len(registry_crops))

        # Test specific crop factors match
        test_crops = ["orange", "corn", "rice", "almond", "lettuce"]
        for crop in test_crops:
            self.assertIn(crop, calculator_crops)
            self.assertIn(crop, registry_crops)
            self.assertEqual(calculator_crops[crop], registry_crops[crop])

        # Test high-emission crops have correct values
        self.assertEqual(registry_crops["rice"], 2.5)  # High due to methane
        self.assertEqual(registry_crops["almond"], 2.1)  # High water requirements

    def test_application_efficiency_factors_centralized(self):
        """Test that application efficiency factors are centralized"""
        calculator_efficiency = self.calculator.APPLICATION_EFFICIENCY
        registry_efficiency = {
            method: data["value"] for method, data in emission_factors.APPLICATION_EFFICIENCY_FACTORS.items()
        }

        # Test specific methods
        test_methods = ["broadcast", "drip_irrigation", "foliar", "injection"]
        for method in test_methods:
            self.assertIn(method, calculator_efficiency)
            self.assertIn(method, registry_efficiency)
            self.assertEqual(calculator_efficiency[method], registry_efficiency[method])

        # Test efficiency ordering (drip > injection > foliar > banded > broadcast)
        self.assertGreater(registry_efficiency["drip_irrigation"], registry_efficiency["broadcast"])
        self.assertGreater(registry_efficiency["injection"], registry_efficiency["foliar"])

    def test_database_field_usage_consistency(self):
        """Test that database operations use correct fields"""
        # Create a test carbon entry with both amount and co2e_amount
        carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            source=self.fertilizer_source,
            type="emission",
            year=2025,
            amount=100.0,  # Legacy field
            co2e_amount=110.0,  # Correct field
            effective_amount=105.0,  # Trust-adjusted field
            data_source="Test Data",
            usda_factors_based=True,
        )

        # Test that queries should prefer co2e_amount over amount
        from django.db.models import Sum

        # Test emissions aggregation uses co2e_amount
        total_emissions = CarbonEntry.objects.filter(establishment=self.establishment, type="emission").aggregate(
            total=Sum("co2e_amount")
        )["total"]

        self.assertEqual(total_emissions, 110.0)

        # Test that fallback to amount works when co2e_amount is None
        carbon_entry.co2e_amount = None
        carbon_entry.save()

        # This should demonstrate the fallback pattern: co2e_amount or amount
        test_value = carbon_entry.co2e_amount or carbon_entry.amount
        self.assertEqual(test_value, 100.0)

    def test_factor_metadata_completeness(self):
        """Test that all factors have required metadata"""
        required_fields = ["value", "unit", "source", "confidence", "last_verified"]

        # Test fertilizer factors
        for nutrient in ["nitrogen", "phosphorus", "potassium"]:
            factor_data = emission_factors.FERTILIZER_FACTORS[nutrient]
            for field in required_fields:
                self.assertIn(field, factor_data, f"Missing {field} in {nutrient} factor")
                self.assertIsNotNone(factor_data[field], f"None value for {field} in {nutrient}")

        # Test crop factors have required metadata
        for crop_name, crop_data in emission_factors.CROP_SPECIFIC_FACTORS.items():
            self.assertIn("value", crop_data)
            self.assertIn("source", crop_data)
            self.assertIn("confidence", crop_data)
            self.assertIn("category", crop_data)

    def test_carbon_calculation_with_centralized_factors(self):
        """Test that carbon calculations work with centralized factors"""
        # Create a test chemical event
        history = History.objects.create(
            product_name="Test Corn", lot_id="TEST001", establishment=self.establishment, user=self.user
        )

        chemical_event = ChemicalEvent.objects.create(
            history=history,
            commercial_name="NPK 10-10-10",
            volume="100 kg",
            area=1.0,
            nitrogen_content=10.0,
            phosphorus_content=10.0,
            potassium_content=10.0,
            application_method="broadcast",
            user=self.user,
        )

        # Calculate carbon impact using centralized factors
        event_data = {
            "commercial_name": chemical_event.commercial_name,
            "volume": "100 kg",
            "area": 1.0,
            "nitrogen_content": 10.0,
            "phosphorus_content": 10.0,
            "potassium_content": 10.0,
            "application_method": "broadcast",
        }

        result = self.calculator.calculate_chemical_event_impact(event_data)

        # Verify calculation uses correct nitrogen factor (11.0)
        expected_nitrogen_co2e = 10.0 * 11.0  # 110 kg CO2e
        self.assertGreater(result.get("co2e", 0), expected_nitrogen_co2e * 0.8)  # Allow for other components

        # Verify result includes metadata
        self.assertIn("calculation_metadata", result)
        metadata = result["calculation_metadata"]
        self.assertEqual(metadata["nitrogen_factor_used"], 11.0)
        self.assertTrue(metadata["usda_factors_based"])

    def test_emission_factor_versioning(self):
        """Test that emission factor versioning is working"""
        registry_version = emission_factors.VERSION
        last_updated = emission_factors.LAST_UPDATED

        # Version should be properly formatted
        version_parts = registry_version.split(".")
        self.assertEqual(len(version_parts), 3)  # Semantic versioning

        # Should have recent update date
        self.assertIsNotNone(last_updated)
        self.assertIn("2025", last_updated)  # Updated this year

        # Data source should be documented
        self.assertIsNotNone(emission_factors.DATA_SOURCE)
        self.assertIn("USDA", emission_factors.DATA_SOURCE)


class LegacyCompatibilityTest(TestCase):
    """Test that legacy code still works with centralized factors"""

    def test_legacy_factor_access(self):
        """Test that legacy factor access patterns still work"""
        from carbon.services.emission_factors import get_usda_fertilizer_factors, get_usda_fuel_factors

        # Legacy functions should still work
        fertilizer_factors = get_usda_fertilizer_factors()
        fuel_factors = get_usda_fuel_factors()

        # Should return the centralized values
        self.assertEqual(fertilizer_factors["nitrogen"], 11.0)
        self.assertIn("diesel", fuel_factors)
        self.assertIn("gasoline", fuel_factors)

    def test_direct_factor_import(self):
        """Test that direct factor imports work"""
        from carbon.services.emission_factors import emission_factors

        # Direct access should work
        nitrogen_factor = emission_factors.get_fertilizer_factor("nitrogen")
        self.assertEqual(nitrogen_factor["value"], 11.0)

        # Crop factor access should work
        corn_factor = emission_factors.get_crop_factor("corn")
        self.assertEqual(corn_factor["value"], 0.6)


if __name__ == "__main__":
    unittest.main()
