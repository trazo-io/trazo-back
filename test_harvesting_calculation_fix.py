#!/usr/bin/env python3
"""
CRITICAL HARVESTING CALCULATION TEST
Test the harvesting calculation that shows 665.804 kg CO₂e instead of expected ~20-25 kg CO₂e
"""

import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors


def test_harvesting_calculation():
    """Test the harvesting calculation with the exact input values that are causing issues"""

    print("=== CRITICAL HARVESTING CALCULATION TEST ===")
    print("Testing carbon calculation that currently shows 665.804 kg CO₂e")
    print("Expected result: ~20-25 kg CO₂e for harvesting operation")
    print()

    # Test values based on the issue description
    print("Test Input Data:")
    print("- Event Type: HA (Harvesting)")
    print("- Area: 5.8 hectares (14.3 acres)")
    print("- Yield: 12.5 tonnes")
    print("- Equipment Hours: 8 hours")
    print("- Transportation Distance: 2.5 km")
    print()

    # Convert test data
    area_hectares = 5.8
    area_acres = area_hectares * 2.47105  # Convert to acres
    equipment_hours = 8.0
    fuel_consumed = None  # Let it calculate from standards

    print(f"Converted Values:")
    print(f"- Area: {area_hectares} hectares = {area_acres:.1f} acres")
    print(f"- Equipment Hours: {equipment_hours}")
    print()

    # Test the actual calculation
    print("=== CURRENT CALCULATION RESULT ===")
    result = VerifiedEmissionFactors._calculate_harvesting_emissions(
        area_covered=area_acres, fuel_consumed=fuel_consumed, equipment_hours=equipment_hours  # Method expects acres
    )

    # Also test without equipment hours to see the baseline calculation
    print("\n=== BASELINE CALCULATION (no equipment hours) ===")
    baseline_result = VerifiedEmissionFactors._calculate_harvesting_emissions(
        area_covered=area_acres, fuel_consumed=None, equipment_hours=None
    )
    print(f"Baseline CO₂e: {baseline_result['co2e_kg']:.3f} kg")
    print(f"Baseline per hectare: {baseline_result['co2e_kg'] / area_hectares:.1f} kg CO₂e/ha")

    print(f"Total CO₂e: {result['co2e_kg']:.3f} kg")
    print(f"Calculation Method: {result['calculation_method']}")

    # Check if validation warnings exist
    if "validation_warnings" in result and result["validation_warnings"]:
        print("🚨 VALIDATION WARNINGS:")
        for warning in result["validation_warnings"]:
            print(f"   - {warning}")

    print()

    # Show detailed breakdown
    breakdown = result["breakdown"]
    print("=== DETAILED BREAKDOWN ===")
    print(f"Production Activity: {breakdown['production_activity']}")
    print(f"Area Covered (acres): {breakdown['area_covered_acres']:.1f}")
    print(f"Area Covered (hectares): {breakdown['area_covered_hectares']:.1f}")
    print(f"Calculation Basis: {breakdown['calculation_basis']}")

    # Check validation data
    if "emissions_per_hectare" in breakdown:
        print(f"Emissions per hectare: {breakdown['emissions_per_hectare']:.1f} kg CO₂e/ha")
    if "validation_applied" in breakdown:
        print(f"Validation Applied: {breakdown['validation_applied']}")
        print(f"Original Result: {breakdown.get('original_result_kg', 'N/A')} kg CO₂e")
        print(f"Corrected Result: {breakdown.get('corrected_result_kg', 'N/A')} kg CO₂e")

    print()

    # Show emission factors being used
    print("=== EMISSION FACTORS ===")
    print(f"Diesel Emission Factor: {breakdown['diesel_emission_factor_kg_per_gallon']:.2f} kg CO₂e/gallon")
    print(f"USDA Harvesting Factor: {breakdown['usda_harvesting_factor_gallons_per_hectare']:.1f} gallons/hectare")
    print()

    # Show calculation steps
    print("=== CALCULATION ANALYSIS ===")
    area_hectares_calc = breakdown["area_covered_hectares"]
    harvesting_factor = breakdown["usda_harvesting_factor_gallons_per_hectare"]
    diesel_factor = breakdown["diesel_emission_factor_kg_per_gallon"]

    if breakdown["calculation_basis"] == "usda_standard_per_hectare":
        fuel_gallons = area_hectares_calc * harvesting_factor
        print(f"Fuel Consumption Calculation:")
        print(f"  {area_hectares_calc:.3f} hectares × {harvesting_factor} gallons/hectare = {fuel_gallons:.3f} gallons")
        print(f"Emissions Calculation:")
        print(f"  {fuel_gallons:.3f} gallons × {diesel_factor} kg CO₂e/gallon = {result['co2e_kg']:.3f} kg CO₂e")
    elif breakdown["calculation_basis"] == "estimated_from_hours_and_area":
        if "equipment_hours" in breakdown:
            estimated_fuel = (area_acres * harvesting_factor * 0.404686) * (equipment_hours / 8.0)
            print(f"Equipment-Based Calculation:")
            print(f"  Area: {area_acres:.1f} acres")
            print(f"  Factor: {harvesting_factor} gallons/hectare")
            print(f"  Hours: {equipment_hours} normalized to 8-hour day")
            print(f"  Estimated fuel: {estimated_fuel:.3f} gallons")
            print(f"  Emissions: {estimated_fuel:.3f} × {diesel_factor} = {result['co2e_kg']:.3f} kg CO₂e")

    print()

    # Identify potential issues
    print("=== ISSUE ANALYSIS ===")
    expected_min = 20.0
    expected_max = 25.0
    actual = result["co2e_kg"]

    if actual > expected_max:
        overestimation_factor = actual / expected_max
        print(f"🚨 CRITICAL OVERESTIMATION: {overestimation_factor:.1f}x higher than expected")
        print(f"   Current: {actual:.1f} kg CO₂e")
        print(f"   Expected: {expected_min}-{expected_max} kg CO₂e")
        print()

        # Analyze potential causes
        print("POTENTIAL CAUSES:")

        # Check if area conversion is the issue
        expected_fuel_per_hectare = 3.5  # From USDA factor
        expected_total_fuel = area_hectares * expected_fuel_per_hectare
        expected_emissions = expected_total_fuel * diesel_factor

        print(f"1. Expected calculation check:")
        print(
            f"   {area_hectares} hectares × {expected_fuel_per_hectare} gallons/hectare = {expected_total_fuel:.1f} gallons"
        )
        print(
            f"   {expected_total_fuel:.1f} gallons × {diesel_factor} kg CO₂e/gallon = {expected_emissions:.1f} kg CO₂e"
        )

        if abs(expected_emissions - actual) < 1.0:
            print("   ✅ Basic calculation is correct")
        else:
            print(f"   ❌ Calculation mismatch: expected {expected_emissions:.1f}, got {actual:.1f}")

        # Check unit conversion issues
        acres_to_hectares = 0.404686
        hectares_to_acres = 2.47105

        print(f"2. Unit conversion check:")
        print(f"   Input area: {area_hectares} hectares")
        print(f"   Converted to acres: {area_hectares * hectares_to_acres:.3f}")
        print(f"   Then back to hectares: {(area_hectares * hectares_to_acres) * acres_to_hectares:.3f}")

        if abs((area_hectares * hectares_to_acres) * acres_to_hectares - area_hectares) > 0.001:
            print("   ❌ Unit conversion rounding error detected")
        else:
            print("   ✅ Unit conversion is accurate")

        # Check if equipment hours are causing multiplication
        if breakdown["calculation_basis"] == "estimated_from_hours_and_area":
            print(f"3. Equipment hours impact:")
            print(f"   Hours provided: {equipment_hours}")
            print(f"   Normalization factor: {equipment_hours / 8.0}")
            print(f"   This could be multiplying the base calculation")

        print()
        print("RECOMMENDATIONS:")
        print("- Check if equipment hours are being double-applied")
        print("- Verify USDA harvesting factor is per hectare, not per operation")
        print("- Ensure area isn't being converted multiple times")
        print("- Add validation for results >50 kg CO₂e/hectare")

    elif actual < expected_min:
        print(f"⚠️ Underestimation: {actual:.1f} kg CO₂e is below expected range")
    else:
        print(f"✅ Result within expected range: {actual:.1f} kg CO₂e")

    return result


def test_realistic_harvesting_ranges():
    """Test harvesting calculations with different realistic scenarios"""
    print("\n" + "=" * 60)
    print("REALISTIC HARVESTING SCENARIO TESTS")
    print("=" * 60)

    scenarios = [
        {"name": "Small avocado farm", "hectares": 2.0, "hours": 4, "expected_kg": "8-12"},
        {"name": "Medium avocado farm", "hectares": 5.8, "hours": 8, "expected_kg": "20-25"},
        {"name": "Large avocado farm", "hectares": 15.0, "hours": 20, "expected_kg": "50-65"},
        {"name": "Very small plot", "hectares": 0.5, "hours": 1, "expected_kg": "2-4"},
    ]

    for scenario in scenarios:
        print(f"\n🌱 {scenario['name']}:")
        print(f"   Area: {scenario['hectares']} hectares")
        print(f"   Equipment Hours: {scenario['hours']}")
        print(f"   Expected CO₂e: {scenario['expected_kg']} kg")

        area_acres = scenario["hectares"] * 2.47105
        result = VerifiedEmissionFactors._calculate_harvesting_emissions(
            area_covered=area_acres, equipment_hours=scenario["hours"]
        )

        actual_kg = result["co2e_kg"]
        print(f"   Actual CO₂e: {actual_kg:.1f} kg")

        # Parse expected range
        expected_range = scenario["expected_kg"].split("-")
        expected_min = float(expected_range[0])
        expected_max = float(expected_range[1])

        if expected_min <= actual_kg <= expected_max:
            print(f"   ✅ Within expected range")
        elif actual_kg > expected_max:
            factor = actual_kg / expected_max
            print(f"   🚨 {factor:.1f}x higher than expected")
        else:
            factor = expected_min / actual_kg
            print(f"   ⚠️ {factor:.1f}x lower than expected")


if __name__ == "__main__":
    print("🚜 HARVESTING CARBON CALCULATION DIAGNOSTIC TEST")
    print("Investigating the 26x overestimation issue")
    print("=" * 60)

    # Test the specific problematic case
    test_harvesting_calculation()

    # Test realistic ranges
    test_realistic_harvesting_ranges()

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
