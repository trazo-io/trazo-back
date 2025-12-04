#!/usr/bin/env python3
"""
CRITICAL BUG INVESTIGATION: Fungicide Area Conversion
Tests the area conversion bug in the chemical calculation pipeline
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
import django

django.setup()


def test_area_conversion_bug():
    print("🚨 CRITICAL BUG INVESTIGATION: AREA CONVERSION")
    print("=" * 60)

    # User's exact scenario
    user_scenario = {
        "area": "123",  # Frontend sends as string
        "area_unit": "acres",  # Frontend specifies unit
        "type": "FU",  # Fungicide
        "way_of_application": "drip_irrigation",
    }

    print(f"📝 USER INPUT:")
    print(f"  Area: {user_scenario['area']} {user_scenario['area_unit']}")
    print(f"  Type: {user_scenario['type']} (Fungicide)")
    print(f"  Application: {user_scenario['way_of_application']}")
    print()

    # Test the area conversion manually
    from carbon.services.event_carbon_calculator import EventCarbonCalculator

    calculator = EventCarbonCalculator()

    # Test area conversion method directly
    area_string = f"{user_scenario['area']} {user_scenario['area_unit']}"
    converted_hectares = calculator._convert_area_to_hectares(area_string)

    print(f"🧮 AREA CONVERSION TEST:")
    print(f"  Input: '{area_string}'")
    print(f"  Expected: 123 acres × 0.404686 = {123 * 0.404686:.2f} hectares")
    print(f"  Actual: {converted_hectares:.2f} hectares")

    if abs(converted_hectares - (123 * 0.404686)) < 0.1:
        print(f"  ✅ Area conversion is CORRECT")
    else:
        print(f"  ❌ Area conversion is WRONG!")
    print()

    # Test the complete chemical data extraction
    class MockEvent:
        def __init__(self):
            self.area = "123 acres"
            self.type = "FU"
            self.way_of_application = "drip_irrigation"
            self.volume = "60"
            self.volume_unit = "liters"
            self.concentration = "1.5%"
            self.nitrogen_percentage = ""
            self.phosphorus_percentage = ""
            self.potassium_percentage = ""

    mock_event = MockEvent()
    chemical_data = calculator._extract_chemical_event_data(mock_event)

    print(f"🔍 CHEMICAL DATA EXTRACTION:")
    print(f"  area_hectares: {chemical_data['area_hectares']:.2f}")
    print(f"  Expected: {123 * 0.404686:.2f} hectares")

    if abs(chemical_data["area_hectares"] - (123 * 0.404686)) < 0.1:
        print(f"  ✅ Chemical data extraction is CORRECT")
    else:
        print(f"  ❌ Chemical data extraction is WRONG!")
        print(f"  🚨 BUG: area_hectares = {chemical_data['area_hectares']}")
        print(f"       Should be: {123 * 0.404686:.2f}")
    print()

    # Now test with VerifiedEmissionFactors directly
    from carbon.services.verified_emission_factors import VerifiedEmissionFactors

    # Test with correct area (hectares)
    correct_area_hectares = 123 * 0.404686
    result_correct = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type="FU",
        volume_liters=60.0,
        area_hectares=correct_area_hectares,
        npk_content={"N": 0.0, "P": 0.0, "K": 0.0},
        application_method="drip_irrigation",
    )

    # Test with wrong area (acres as hectares)
    wrong_area_hectares = 123.0  # User's bug scenario
    result_wrong = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type="FU",
        volume_liters=60.0,
        area_hectares=wrong_area_hectares,
        npk_content={"N": 0.0, "P": 0.0, "K": 0.0},
        application_method="drip_irrigation",
    )

    print(f"📊 EMISSION CALCULATION COMPARISON:")
    print()
    print(f"✅ CORRECT CALCULATION (49.78 hectares):")
    print(f"  • Total CO₂e: {result_correct['co2e_kg']:.3f} kg")
    print(f"  • Fuel: {result_correct['breakdown']['application_fuel_liters']:.1f} L")
    print(f"  • Fuel gallons: {result_correct['breakdown']['application_fuel_gallons']:.2f}")
    print(f"  • Application emissions: {result_correct['breakdown']['application_emissions_kg_co2e']:.3f} kg")
    print()
    print(f"❌ WRONG CALCULATION (123 hectares - user's bug):")
    print(f"  • Total CO₂e: {result_wrong['co2e_kg']:.3f} kg")
    print(f"  • Fuel: {result_wrong['breakdown']['application_fuel_liters']:.1f} L")
    print(f"  • Fuel gallons: {result_wrong['breakdown']['application_fuel_gallons']:.2f}")
    print(f"  • Application emissions: {result_wrong['breakdown']['application_emissions_kg_co2e']:.3f} kg")
    print()

    # Check if the bug matches user's reported values
    user_reported_fuel = 123.0
    user_reported_co2e = 331.755

    if abs(result_wrong["breakdown"]["application_fuel_liters"] - user_reported_fuel) < 0.1:
        print(f"🎯 BUG CONFIRMED: Fuel calculation matches user's report")
        print(f"   User reported: {user_reported_fuel} L")
        print(f"   Wrong calc: {result_wrong['breakdown']['application_fuel_liters']:.1f} L")

    if abs(result_wrong["co2e_kg"] - user_reported_co2e) < 1.0:
        print(f"🎯 BUG CONFIRMED: CO₂e matches user's report")
        print(f"   User reported: {user_reported_co2e} kg")
        print(f"   Wrong calc: {result_wrong['co2e_kg']:.3f} kg")

    print()
    print("=" * 60)
    print("📋 SUMMARY")
    print("=" * 60)

    error_factor = result_wrong["co2e_kg"] / result_correct["co2e_kg"]

    if abs(chemical_data["area_hectares"] - correct_area_hectares) < 0.1:
        print("✅ Area conversion is working correctly in _convert_area_to_hectares")
        print("✅ Chemical data extraction is working correctly")
        print("❌ Bug must be elsewhere in the calculation chain")
    else:
        print("❌ CRITICAL BUG FOUND in area conversion pipeline!")
        print(f"   Expected: {correct_area_hectares:.2f} hectares")
        print(f"   Actual: {chemical_data['area_hectares']:.2f} hectares")
        print(f"   Error: {error_factor:.1f}× inflation in emissions")


if __name__ == "__main__":
    test_area_conversion_bug()
