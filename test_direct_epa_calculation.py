#!/usr/bin/env python3
"""
Direct EPA Calculation Test
Tests EPA calculation directly without MockEvent to isolate the issue
"""


def test_direct_epa_calculation():
    print("🧮 Direct EPA Calculation Test")
    print("=" * 40)

    # Import the EPA calculation service
    import os
    import sys

    sys.path.append(os.path.dirname(os.path.abspath(__file__)))

    try:
        from carbon.services.verified_emission_factors import VerifiedEmissionFactors

        # Test data from screenshot
        production_type = "planting avocado"  # PL maps to planting
        area_covered_acres = 140.0 * 2.47105  # Convert 140 ha to acres
        fuel_consumed_gallons = 150.0 / 3.78541  # Convert 150 L to gallons
        equipment_hours = 2.0

        print(f"📝 Test Input:")
        print(f"  Production Type: {production_type}")
        print(f"  Area: 140 ha = {area_covered_acres:.1f} acres")
        print(f"  Fuel: 150 L = {fuel_consumed_gallons:.2f} gallons")
        print(f"  Equipment Hours: {equipment_hours}")

        # Call EPA calculation directly
        print(f"\n🔬 Calling EPA Calculation...")
        result = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type=production_type,
            area_covered=area_covered_acres,
            fuel_consumed=fuel_consumed_gallons,
            equipment_hours=equipment_hours,
        )

        print(f"\n✅ EPA Calculation Result:")
        print(f"  CO2e: {result['co2e_kg']:.2f} kg")
        print(f"  Method: {result['calculation_method']}")
        print(f"  Data Sources: {result['data_sources']}")

        if "breakdown" in result:
            print(f"  Breakdown: {result['breakdown']}")

        # Expected calculation
        EPA_DIESEL = 10.21
        expected_co2e = fuel_consumed_gallons * EPA_DIESEL
        print(f"\n📊 Manual Verification:")
        print(f"  Expected: {fuel_consumed_gallons:.2f} gal × {EPA_DIESEL} = {expected_co2e:.2f} kg CO₂e")
        print(f"  Actual: {result['co2e_kg']:.2f} kg CO₂e")

        if abs(result["co2e_kg"] - expected_co2e) < 1.0:
            print(f"  ✅ Results match (within 1 kg tolerance)")
            print(f"\n🎯 CONCLUSION: EPA calculation is working correctly!")
            print(f"     Issue must be in MockEvent or data extraction")
        else:
            print(f"  ❌ Results don't match")
            print(f"     Difference: {abs(result['co2e_kg'] - expected_co2e):.2f} kg")

    except Exception as e:
        print(f"❌ EPA Calculation Failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_direct_epa_calculation()
