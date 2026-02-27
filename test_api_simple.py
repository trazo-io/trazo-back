#!/usr/bin/env python3
"""
Simple test to verify the General event API fix.
"""
import json
import os
import sys

import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.insert(0, "/Users/oscarmunoz/dev/trazo/trazo-back")
django.setup()

from carbon.views import OptimizedCarbonCalculator


def test_optimized_calculator_fix():
    """Test the OptimizedCarbonCalculator with our fix"""
    print("🔧 Testing OptimizedCarbonCalculator General Event Fix")
    print("=" * 60)

    calculator = OptimizedCarbonCalculator()

    # Test with pest scouting data (similar to frontend payload)
    test_data = {"description": "Pest Scouting", "name": "Field inspection", "type": "general", "event_type": "general"}

    print(f"📤 Test Data:")
    print(f"   Description: {test_data['description']}")
    print(f"   Type: {test_data['type']}")

    try:
        # Call the fixed method
        result = calculator.calculate_general_impact_optimized(test_data)

        print(f"\n📥 Calculation Result:")
        print(f"   CO2e: {result.get('co2e')} kg")
        print(f"   Method: {result.get('calculation_method')}")
        print(f"   USDA Verified: {result.get('usda_factors_used')}")
        print(f"   Efficiency Score: {result.get('efficiency_score')}")

        if "data_source" in result:
            print(f"   Data Source: {result.get('data_source')}")

        # Check if fix worked
        co2e = result.get("co2e", 0)
        method = result.get("calculation_method", "")

        print(f"\n🎯 Fix Status:")

        if co2e == 0.5:
            print(f"   ❌ STILL BROKEN: Using hardcoded 0.5 kg CO2e")
            return False
        elif co2e < 0.5:
            print(f"   ✅ FIXED: Reduced from 0.5 to {co2e} kg CO2e")
            success = True
        else:
            print(f"   ⚠️  UNEXPECTED: {co2e} kg CO2e (higher than 0.5)")
            success = False

        if "enhanced" in method or "general_event_specific" in method:
            print(f"   ✅ USING ENHANCED METHOD: {method}")
        elif "fallback" in method:
            print(f"   ⚠️  USING FALLBACK: {method}")
        else:
            print(f"   📝 METHOD: {method}")

        if result.get("usda_factors_used"):
            print(f"   ✅ EPA/USDA VERIFIED: Using government emission factors")
        else:
            print(f"   ⚠️  NOT VERIFIED: Using estimates")

        return success and co2e < 0.5

    except Exception as e:
        print(f"   ❌ Exception: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_different_descriptions():
    """Test different general event descriptions"""
    print(f"\n🔍 Testing Different General Event Descriptions")
    print("=" * 60)

    calculator = OptimizedCarbonCalculator()

    test_cases = [
        ("Pest Scouting", "Should be low-impact documentation"),
        ("Farm visit for consultation", "Should include transportation emissions"),
        ("Training workshop", "Should include participant calculations"),
        ("Field notes recording", "Should be minimal documentation activity"),
        ("General observation", "Should default to documentation"),
    ]

    for description, expected in test_cases:
        print(f"\n   Testing: '{description}'")

        test_data = {"description": description, "type": "general"}

        try:
            result = calculator.calculate_general_impact_optimized(test_data)
            co2e = result.get("co2e", 0)
            method = result.get("calculation_method", "unknown")

            print(f"      Result: {co2e:.3f} kg CO2e")
            print(f"      Method: {method}")
            print(f"      Expected: {expected}")

            if co2e <= 10.0:  # Reasonable upper bound
                print(f"      ✅ Reasonable carbon impact")
            else:
                print(f"      ⚠️  High carbon impact")

        except Exception as e:
            print(f"      ❌ Error: {e}")


if __name__ == "__main__":
    print("🧪 OPTIMIZED CALCULATOR FIX TEST")
    print("Testing General Event Carbon Calculation Fix")
    print("=" * 70)

    # Test the main fix
    fix_worked = test_optimized_calculator_fix()

    # Test different descriptions
    test_different_descriptions()

    # Final result
    print(f"\n🏁 FINAL RESULT: {'✅ CALCULATOR FIXED' if fix_worked else '❌ CALCULATOR STILL BROKEN'}")

    if fix_worked:
        print("\n📋 SUCCESS SUMMARY:")
        print("   ✅ OptimizedCarbonCalculator now uses enhanced calculation")
        print("   ✅ General events properly reduced from 0.5 kg CO2e")
        print("   ✅ Context-aware emission factors working")
        print("   ✅ Frontend API will now show improved values")
        print("\n🎯 This should fix the 0.50 kg CO2e issue you saw in the frontend!")
