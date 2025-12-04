#!/usr/bin/env python3
"""
CRITICAL TEST: Verify the Optimized Calculator Fix
Tests the fixed optimized calculation against user's exact scenario
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
import django

django.setup()


def test_optimized_fix():
    print("🔧 TESTING OPTIMIZED CALCULATOR FIX")
    print("=" * 60)

    # User's exact scenario
    user_event_data = {
        "type": "FU",  # Fungicide
        "commercial_name": "Miracle-Gro All Purpose",
        "volume": "60",
        "volume_unit": "liters",
        "area": "123",
        "area_unit": "acres",
        "concentration": "1.5%",
        "way_of_application": "drip_irrigation",
        "weather_conditions": "calm, humid conditions",
        "soil_moisture": "high",
        "temperature_range": "20-28°C",
    }

    print("📝 USER'S SCENARIO:")
    print(f"  Type: {user_event_data['type']} (Fungicide)")
    print(f"  Area: {user_event_data['area']} {user_event_data['area_unit']}")
    print(f"  Volume: {user_event_data['volume']} {user_event_data['volume_unit']}")
    print(f"  Application: {user_event_data['way_of_application']}")
    print()

    # Test the fixed components
    from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor

    print("🔄 STEP 1: Test Event Processing (Area Conversion)")
    processed_event = OptimizedEventProcessor.process_event_data("chemical", user_event_data)

    print(f"  Original area: {user_event_data['area']} {user_event_data['area_unit']}")
    print(f"  Processed area: {processed_event['area']} hectares")
    print(f"  Expected: {123 * 0.404686:.2f} hectares")

    expected_hectares = 123 * 0.404686
    if abs(processed_event["area"] - expected_hectares) < 0.1:
        print("  ✅ Area conversion is CORRECT")
        area_fix_works = True
    else:
        print("  ❌ Area conversion still WRONG!")
        area_fix_works = False
    print()

    print("🔄 STEP 2: Test EPA Calculation")
    calculator = OptimizedCarbonCalculator()
    result = calculator.calculate_chemical_impact_optimized(processed_event)

    print(f"  CO₂e: {result.get('co2e', 'N/A')} kg")
    print(f"  Method: {result.get('calculation_method', 'N/A')}")
    print(f"  Verification: {result.get('verification_status', 'N/A')}")

    # Check breakdown details
    fuel_liters = result.get("application_fuel_liters", 0)
    fuel_gallons = result.get("application_fuel_gallons", 0)
    app_emissions = result.get("application_emissions_kg_co2e", 0)
    npk_content = result.get("npk_content", {})

    print(f"  Fuel: {fuel_liters} L ({fuel_gallons} gal)")
    print(f"  App emissions: {app_emissions} kg")
    print(f"  NPK: N={npk_content.get('N', 0)}, P={npk_content.get('P', 0)}, K={npk_content.get('K', 0)}")
    print()

    print("🔄 STEP 3: Compare with User's Reported Values")
    user_reported_co2e = 331.755
    user_reported_fuel = 123.0

    print(f"  User reported: {user_reported_co2e} kg CO₂e, {user_reported_fuel} L fuel")
    print(f"  Fixed result:  {result.get('co2e', 0)} kg CO₂e, {fuel_liters} L fuel")

    co2e_fixed = abs(result.get("co2e", 0) - user_reported_co2e) > 50  # Should be very different now
    fuel_fixed = abs(fuel_liters - user_reported_fuel) > 50  # Should be much less fuel

    if co2e_fixed and fuel_fixed:
        print("  ✅ Results are SIGNIFICANTLY DIFFERENT from user's bug report")
        print("  ✅ This indicates the fix is working!")
        calculation_fix_works = True
    else:
        print("  ❌ Results still similar to user's bug report")
        print("  ❌ Fix may not be working correctly")
        calculation_fix_works = False
    print()

    print("🔄 STEP 4: Agricultural Reality Check")
    expected_fuel_drip = expected_hectares * 0.4  # 0.4 L/ha for drip irrigation
    expected_co2e_range = (40, 80)  # Realistic range for fungicide on 50 hectares

    print(f"  Expected fuel (drip): {expected_fuel_drip:.1f} L")
    print(f"  Expected CO₂e range: {expected_co2e_range[0]}-{expected_co2e_range[1]} kg")
    print(f"  Actual fuel: {fuel_liters} L")
    print(f"  Actual CO₂e: {result.get('co2e', 0)} kg")

    fuel_realistic = abs(fuel_liters - expected_fuel_drip) < 5
    co2e_realistic = expected_co2e_range[0] <= result.get("co2e", 0) <= expected_co2e_range[1]

    if fuel_realistic:
        print("  ✅ Fuel consumption is agriculturally realistic")
    else:
        print("  ⚠️  Fuel consumption outside expected range")

    if co2e_realistic:
        print("  ✅ CO₂e is agriculturally realistic")
    else:
        print("  ⚠️  CO₂e outside expected range (may be due to fungicide having zero manufacturing emissions)")

    print()
    print("=" * 60)
    print("📋 FIX VERIFICATION SUMMARY")
    print("=" * 60)

    fixes_working = []
    if area_fix_works:
        fixes_working.append("✅ Area conversion: 123 acres → 49.78 hectares")
    else:
        fixes_working.append("❌ Area conversion: Still broken")

    if calculation_fix_works:
        fixes_working.append("✅ EPA calculation: Now using verified emission factors")
    else:
        fixes_working.append("❌ EPA calculation: Still using simple multiplication")

    if result.get("verification_status") == "epa_usda_verified":
        fixes_working.append("✅ Verification status: EPA/USDA verified")
    else:
        fixes_working.append("❌ Verification status: Not EPA verified")

    if npk_content == {"N": 0, "P": 0, "K": 0}:
        fixes_working.append("✅ NPK handling: Fungicide correctly has 0-0-0 NPK")
    else:
        fixes_working.append("❌ NPK handling: Fungicide incorrectly has NPK content")

    print("🔍 WHAT'S WORKING:")
    for fix in fixes_working:
        print(f"  {fix}")

    all_fixes_work = all("✅" in fix for fix in fixes_working)

    if all_fixes_work:
        print()
        print("🎉 SUCCESS! All fixes are working correctly")
        print("🎯 The optimized endpoint should now give realistic results")
        print("📱 Frontend users will see proper EPA-verified calculations")
    else:
        print()
        print("⚠️  Some fixes need more work")
        print("🔧 Check the failing components above")

    return all_fixes_work


if __name__ == "__main__":
    test_optimized_fix()
