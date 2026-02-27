#!/usr/bin/env python3
"""
TEST FIXED HARVESTING CALCULATION
Test the fixed optimized production endpoint with B3 harvesting scenario
"""

import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor


def test_fixed_harvesting_calculation():
    """Test the fixed harvesting calculation with B3 scenario data"""

    print("=== TESTING FIXED HARVESTING CALCULATION ===")
    print("B3 Scenario: Apple Harvest (Washington State)")
    print("- Area: 5.8 hectares (14.3 acres)")
    print("- Equipment Hours: 8 hours")
    print("- Production Type: HA (Harvesting)")
    print()

    # Simulate the frontend data that would be sent to the API
    event_data = {
        "type": "HA",  # Harvesting
        "area_covered": "5.8",  # hectares
        "area_unit": "ha",
        "equipment_hours": "8",
        "fuel_consumed": None,  # Let USDA calculation estimate
        "yield_quantity": "12.5",
        "yield_unit": "tons",
        "transportation_distance": "2.5",
        "transportation_unit": "km",
    }

    # Test 1: Event Processing
    print("🔧 TEST 1: Event Data Processing")
    processed_event = OptimizedEventProcessor._process_production_event(event_data)
    print(f"   Processed production_type: {processed_event['production_type']}")
    print(f"   Processed area_covered: {processed_event['area_covered']} acres")
    print(f"   Processed equipment_hours: {processed_event['equipment_hours']}")
    print(f"   Processed fuel_consumed: {processed_event['fuel_consumed']}")
    print()

    # Test 2: Carbon Calculation
    print("🧮 TEST 2: Carbon Calculation")
    calculator = OptimizedCarbonCalculator()

    try:
        result = calculator.calculate_production_impact_optimized(processed_event)

        print(f"   ✅ CO₂e Result: {result['co2e']} kg")
        print(f"   ✅ Efficiency Score: {result['efficiency_score']}")
        print(f"   ✅ Calculation Method: {result['calculation_method']}")
        print(f"   ✅ USDA Verified: {result['usda_factors_used']}")

        if "validation_warnings" in result and result["validation_warnings"]:
            print("   ⚠️ Validation Warnings:")
            for warning in result["validation_warnings"]:
                print(f"      - {warning}")

        if "breakdown" in result and result["breakdown"]:
            breakdown = result["breakdown"]
            print("   📊 Calculation Breakdown:")
            print(f"      - Production Activity: {breakdown.get('production_activity', 'N/A')}")
            print(f"      - Area (hectares): {breakdown.get('area_covered_hectares', 'N/A')}")
            print(f"      - USDA Factor: {breakdown.get('usda_harvesting_factor_gallons_per_hectare', 'N/A')} gal/ha")
            print(f"      - Diesel Factor: {breakdown.get('diesel_emission_factor_kg_per_gallon', 'N/A')} kg CO₂e/gal")
            print(f"      - Calculation Basis: {breakdown.get('calculation_basis', 'N/A')}")

            if "emissions_per_hectare" in breakdown:
                print(f"      - Emissions per hectare: {breakdown['emissions_per_hectare']:.1f} kg CO₂e/ha")
                realistic_range = breakdown.get("realistic_range_kg_per_hectare", {})
                if realistic_range:
                    print(
                        f"      - Realistic range: {realistic_range.get('min', 'N/A')}-{realistic_range.get('max', 'N/A')} kg CO₂e/ha"
                    )

        print()

        # Test 3: Validation Check
        print("✅ TEST 3: Results Validation")
        co2e_value = result["co2e"]
        expected_min = 15.0  # Lower bound for realistic harvesting
        expected_max = 50.0  # Upper bound for realistic harvesting

        if expected_min <= co2e_value <= expected_max:
            print(
                f"   ✅ PASS: Result {co2e_value} kg CO₂e is within realistic range ({expected_min}-{expected_max} kg)"
            )
        elif co2e_value < expected_min:
            print(f"   ⚠️ LOW: Result {co2e_value} kg CO₂e is below expected range ({expected_min}-{expected_max} kg)")
        else:
            print(f"   ❌ HIGH: Result {co2e_value} kg CO₂e is above expected range ({expected_min}-{expected_max} kg)")

        # Comparison with previous problematic values
        print()
        print("📈 COMPARISON WITH PREVIOUS ISSUES:")
        print(f"   - Current result: {co2e_value} kg CO₂e")
        print(f"   - Previous broken result 1: 665.804 kg CO₂e (26x overestimation)")
        print(f"   - Previous broken result 2: 53.889 kg CO₂e (inconsistent)")
        print(f"   - Expected range: 20-25 kg CO₂e")

        if co2e_value < 100:  # Much better than 665.804
            improvement_factor = 665.804 / co2e_value
            print(f"   ✅ IMPROVEMENT: {improvement_factor:.1f}x reduction from overestimation")

        return result

    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        return None


def test_area_conversion():
    """Test area conversion logic"""
    print("🌍 AREA CONVERSION TEST")

    test_cases = [
        {"area_covered": "5.8", "area_unit": "ha", "expected_acres": 14.3},
        {"area_covered": "14.3", "area_unit": "acres", "expected_acres": 14.3},
        {"area_covered": "1.0", "area_unit": "ha", "expected_acres": 2.47},
    ]

    for i, test_case in enumerate(test_cases, 1):
        event_data = {
            "type": "HA",
            "area_covered": test_case["area_covered"],
            "area_unit": test_case["area_unit"],
            "equipment_hours": "8",
        }

        processed = OptimizedEventProcessor._process_production_event(event_data)
        actual_acres = processed["area_covered"]
        expected_acres = test_case["expected_acres"]

        print(f"   Test {i}: {test_case['area_covered']} {test_case['area_unit']} → {actual_acres:.2f} acres")

        if abs(actual_acres - expected_acres) < 0.1:
            print(f"            ✅ PASS (expected ~{expected_acres} acres)")
        else:
            print(f"            ❌ FAIL (expected ~{expected_acres} acres)")


if __name__ == "__main__":
    print("🚜 TESTING FIXED HARVESTING CARBON CALCULATION")
    print("=" * 60)

    # Test the fixed calculation
    result = test_fixed_harvesting_calculation()

    print()
    test_area_conversion()

    print()
    print("=" * 60)
    print("✅ TESTING COMPLETE")

    if result and result.get("usda_factors_used"):
        print("🎉 SUCCESS: Fixed calculation is using USDA verified emission factors!")
    else:
        print("❌ ISSUE: Calculation may still have problems")
