#!/usr/bin/env python3
"""
Comprehensive validation script for Phase 1 electric equipment implementation
Tests all 6 updated production event calculation methods
"""

import os
import sys
from decimal import Decimal

# Add Django project to path
base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django

django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors


class Phase1ValidationTests:
    """Validation tests for Phase 1 electric equipment backend"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.test_results = []

    def assert_equal(self, actual, expected, test_name, tolerance=0.001):
        """Assert with tolerance for floating point comparison"""
        if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
            if abs(actual - expected) <= tolerance:
                self.passed += 1
                self.test_results.append(f"✓ {test_name}")
                return True
            else:
                self.failed += 1
                self.test_results.append(f"✗ {test_name}: Expected {expected}, got {actual}")
                return False
        else:
            if actual == expected:
                self.passed += 1
                self.test_results.append(f"✓ {test_name}")
                return True
            else:
                self.failed += 1
                self.test_results.append(f"✗ {test_name}: Expected {expected}, got {actual}")
                return False

    def test_backwards_compatibility(self):
        """Test that old calls without kwargs still work"""
        print("\n=== Testing Backwards Compatibility ===")

        methods = [
            ("planting", "_calculate_planting_emissions"),
            ("harvesting", "_calculate_harvesting_emissions"),
            ("transplanting", "_calculate_transplanting_emissions"),
            ("thinning", "_calculate_thinning_emissions"),
            ("cultivation", "_calculate_cultivation_emissions"),
            ("general", "_calculate_general_production_emissions"),
        ]

        for name, method_name in methods:
            method = getattr(VerifiedEmissionFactors, method_name)
            result = method(area_covered=1.0, fuel_consumed=5.0, equipment_hours=2.0)

            # Should default to diesel calculation
            self.assert_equal(result["breakdown"]["fuel_type"], "diesel", f"{name}: Defaults to diesel fuel_type")

            # Diesel emission: 5.0 gallons * 10.21 kg/gal = 51.05 kg
            self.assert_equal(
                result["co2e_kg"], 51.05, f"{name}: Correct diesel calculation (5 gal * 10.21)", tolerance=0.01
            )

    def test_electric_grid_calculation(self):
        """Test electric equipment with grid power"""
        print("\n=== Testing Electric Grid Equipment ===")

        methods = [
            ("planting", "_calculate_planting_emissions"),
            ("harvesting", "_calculate_harvesting_emissions"),
            ("transplanting", "_calculate_transplanting_emissions"),
            ("thinning", "_calculate_thinning_emissions"),
            ("cultivation", "_calculate_cultivation_emissions"),
            ("general", "_calculate_general_production_emissions"),
        ]

        for name, method_name in methods:
            method = getattr(VerifiedEmissionFactors, method_name)
            result = method(
                area_covered=1.0,
                fuel_consumed=10.0,  # 10 kWh
                equipment_hours=2.0,
                fuel_type="electric",
                energy_source="grid",
            )

            # Electric emission: 10 kWh * 0.39 kg/kWh = 3.9 kg
            self.assert_equal(
                result["co2e_kg"], 3.9, f"{name}: Correct electric grid calculation (10 kWh * 0.39)", tolerance=0.01
            )

            self.assert_equal(result["breakdown"]["fuel_type"], "electric", f"{name}: fuel_type is electric")

            self.assert_equal(result["breakdown"]["energy_source"], "grid", f"{name}: energy_source is grid")

            self.assert_equal(
                result["breakdown"]["calculation_basis"],
                "actual_electric_consumption_grid",
                f"{name}: calculation_basis is correct",
            )

    def test_electric_solar_calculation(self):
        """Test electric equipment with solar power (zero emissions)"""
        print("\n=== Testing Electric Solar Equipment ===")

        methods = [
            ("planting", "_calculate_planting_emissions"),
            ("harvesting", "_calculate_harvesting_emissions"),
            ("transplanting", "_calculate_transplanting_emissions"),
            ("thinning", "_calculate_thinning_emissions"),
            ("cultivation", "_calculate_cultivation_emissions"),
            ("general", "_calculate_general_production_emissions"),
        ]

        for name, method_name in methods:
            method = getattr(VerifiedEmissionFactors, method_name)
            result = method(
                area_covered=1.0,
                fuel_consumed=10.0,  # 10 kWh
                equipment_hours=2.0,
                fuel_type="electric",
                energy_source="solar",
            )

            # Solar: zero emissions
            self.assert_equal(result["co2e_kg"], 0.0, f"{name}: Solar equipment has zero emissions")

            self.assert_equal(result["breakdown"]["energy_source"], "solar", f"{name}: energy_source is solar")

    def test_electric_wind_calculation(self):
        """Test electric equipment with wind power (zero emissions)"""
        print("\n=== Testing Electric Wind Equipment ===")

        method = VerifiedEmissionFactors._calculate_planting_emissions
        result = method(
            area_covered=1.0, fuel_consumed=10.0, equipment_hours=2.0, fuel_type="electric", energy_source="wind"
        )

        self.assert_equal(result["co2e_kg"], 0.0, "Wind equipment has zero emissions")
        self.assert_equal(result["breakdown"]["energy_source"], "wind", "energy_source is wind")

    def test_emission_factor_values(self):
        """Test that emission factors are correctly applied"""
        print("\n=== Testing Emission Factor Values ===")

        # Diesel: 10.21 kg CO2/gal
        result = VerifiedEmissionFactors._calculate_planting_emissions(
            area_covered=1.0, fuel_consumed=1.0, fuel_type="diesel"
        )
        self.assert_equal(result["co2e_kg"], 10.21, "Diesel factor is 10.21 kg/gal", tolerance=0.01)

        # Electric grid: 0.39 kg CO2/kWh
        result = VerifiedEmissionFactors._calculate_planting_emissions(
            area_covered=1.0, fuel_consumed=1.0, fuel_type="electric", energy_source="grid"
        )
        self.assert_equal(result["co2e_kg"], 0.39, "Electric grid factor is 0.39 kg/kWh", tolerance=0.01)

    def test_breakdown_completeness(self):
        """Test that breakdown dictionaries contain all required fields"""
        print("\n=== Testing Breakdown Completeness ===")

        # Test diesel breakdown
        result = VerifiedEmissionFactors._calculate_planting_emissions(
            area_covered=1.0, fuel_consumed=5.0, fuel_type="diesel"
        )

        breakdown = result["breakdown"]
        required_diesel_fields = [
            "production_activity",
            "area_covered_acres",
            "area_covered_hectares",
            "fuel_type",
            "calculation_basis",
            "confidence_level",
            "diesel_emission_factor_kg_per_gallon",
        ]

        for field in required_diesel_fields:
            self.assert_equal(field in breakdown, True, f"Diesel breakdown contains '{field}'")

        # Test electric breakdown
        result = VerifiedEmissionFactors._calculate_planting_emissions(
            area_covered=1.0, fuel_consumed=5.0, fuel_type="electric", energy_source="grid"
        )

        breakdown = result["breakdown"]
        required_electric_fields = [
            "production_activity",
            "area_covered_acres",
            "area_covered_hectares",
            "fuel_type",
            "calculation_basis",
            "confidence_level",
            "electricity_emission_factor_kg_per_kwh",
            "energy_source",
        ]

        for field in required_electric_fields:
            self.assert_equal(field in breakdown, True, f"Electric breakdown contains '{field}'")

    def test_api_dispatcher(self):
        """Test that the dispatcher passes kwargs correctly"""
        print("\n=== Testing API Dispatcher ===")

        # Test planting dispatcher
        result = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type="Planting", area_covered=1.0, fuel_consumed=5.0, fuel_type="electric", energy_source="solar"
        )

        self.assert_equal(result["co2e_kg"], 0.0, "Dispatcher passes electric solar to planting")

        # Test harvesting dispatcher
        result = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type="Harvesting",
            area_covered=1.0,
            fuel_consumed=10.0,
            fuel_type="electric",
            energy_source="grid",
        )

        self.assert_equal(result["co2e_kg"], 3.9, "Dispatcher passes electric grid to harvesting", tolerance=0.01)

    def test_all_methods_follow_pattern(self):
        """Test that all 6 methods follow the identical pattern"""
        print("\n=== Testing Pattern Consistency ===")

        methods = [
            "_calculate_planting_emissions",
            "_calculate_harvesting_emissions",
            "_calculate_transplanting_emissions",
            "_calculate_thinning_emissions",
            "_calculate_cultivation_emissions",
            "_calculate_general_production_emissions",
        ]

        for method_name in methods:
            method = getattr(VerifiedEmissionFactors, method_name)

            # Test with identical inputs
            result = method(
                area_covered=2.0, fuel_consumed=8.0, equipment_hours=3.0, fuel_type="electric", energy_source="grid"
            )

            # All should calculate: 8 kWh * 0.39 = 3.12 kg
            self.assert_equal(
                result["co2e_kg"], 3.12, f"{method_name}: Consistent electric calculation", tolerance=0.01
            )

    def run_all_tests(self):
        """Run all validation tests"""
        print("\n" + "=" * 70)
        print("PHASE 1 ELECTRIC EQUIPMENT BACKEND VALIDATION")
        print("=" * 70)

        self.test_backwards_compatibility()
        self.test_electric_grid_calculation()
        self.test_electric_solar_calculation()
        self.test_electric_wind_calculation()
        self.test_emission_factor_values()
        self.test_breakdown_completeness()
        self.test_api_dispatcher()
        self.test_all_methods_follow_pattern()

        print("\n" + "=" * 70)
        print("TEST RESULTS")
        print("=" * 70)

        for result in self.test_results:
            print(result)

        print("\n" + "=" * 70)
        print(f"PASSED: {self.passed}")
        print(f"FAILED: {self.failed}")
        print(f"TOTAL:  {self.passed + self.failed}")
        print("=" * 70)

        if self.failed == 0:
            print("\n✓✓✓ ALL TESTS PASSED - BACKEND READY FOR PHASE 1 ✓✓✓\n")
            return True
        else:
            print(f"\n✗✗✗ {self.failed} TESTS FAILED - REVIEW REQUIRED ✗✗✗\n")
            return False


if __name__ == "__main__":
    validator = Phase1ValidationTests()
    success = validator.run_all_tests()
    sys.exit(0 if success else 1)
