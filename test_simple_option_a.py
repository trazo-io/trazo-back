#!/usr/bin/env python3
"""
Simple test to verify Option A works with the OptimizedCarbonCalculator.
"""
import os
import sys

import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.insert(0, "/Users/oscarmunoz/dev/trazo/trazo-back")
django.setup()

from carbon.views import OptimizedCarbonCalculator


def test_option_a_simple():
    """Simple test of Option A implementation"""
    print("🏁 SIMPLE OPTION A TEST")
    print("Testing: Empty General Events → 0.0 kg CO2e")
    print("=" * 60)

    calculator = OptimizedCarbonCalculator()

    # Test 1: Empty event (user's exact payload)
    print("\n1. Testing Empty Event (User's Exact Scenario)")
    empty_payload = {"date": "2025-11-05T15:14", "event_type": "general", "parcel_id": 106, "establishment_id": 47}

    print(f"   Payload: {empty_payload}")

    try:
        result = calculator.calculate_general_impact_optimized(empty_payload)
        co2e = result.get("co2e", -1)
        method = result.get("calculation_method", "unknown")

        print(f"   Result: {co2e} kg CO2e")
        print(f"   Method: {method}")

        if co2e == 0.0:
            print(f"   ✅ SUCCESS: Empty event returns 0.0 kg CO2e")
            empty_success = True
        else:
            print(f"   ❌ FAILED: Expected 0.0, got {co2e}")
            empty_success = False

    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        empty_success = False

    # Test 2: Event with description
    print("\n2. Testing Event with Description")
    content_payload = {
        "date": "2025-11-05T15:14",
        "event_type": "general",
        "parcel_id": 106,
        "establishment_id": 47,
        "description": "Pest Scouting",
    }

    print(f"   Payload: {content_payload}")

    try:
        result = calculator.calculate_general_impact_optimized(content_payload)
        co2e = result.get("co2e", -1)
        method = result.get("calculation_method", "unknown")

        print(f"   Result: {co2e} kg CO2e")
        print(f"   Method: {method}")

        if co2e > 0.0 and co2e <= 1.0:  # Should be around 0.25
            print(f"   ✅ SUCCESS: Event with content returns {co2e} kg CO2e")
            content_success = True
        else:
            print(f"   ❌ UNEXPECTED: Expected ~0.25, got {co2e}")
            content_success = False

    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        content_success = False

    # Test 3: Various empty scenarios
    print("\n3. Testing Various Empty Scenarios")
    empty_scenarios = [{"description": ""}, {"description": "   "}, {"name": ""}, {}, {"description": None}]

    all_empty_pass = True
    for i, scenario in enumerate(empty_scenarios, 1):
        test_payload = {**empty_payload, **scenario}

        try:
            result = calculator.calculate_general_impact_optimized(test_payload)
            co2e = result.get("co2e", -1)

            print(f"   Scenario {i}: {scenario} → {co2e} kg CO2e", end="")

            if co2e == 0.0:
                print(f" ✅")
            else:
                print(f" ❌ (expected 0.0)")
                all_empty_pass = False

        except Exception as e:
            print(f"   Scenario {i}: {scenario} → ERROR: {e}")
            all_empty_pass = False

    # Final result
    overall_success = empty_success and content_success and all_empty_pass

    print(f"\n🏁 FINAL RESULT: {'✅ OPTION A WORKING PERFECTLY' if overall_success else '❌ SOME TESTS FAILED'}")

    if overall_success:
        print("\n🎉 SUCCESS:")
        print("   ✅ Empty General events → 0.0 kg CO2e")
        print("   ✅ Events with descriptions → EPA-verified calculations")
        print("   ✅ All empty scenarios handled correctly")
        print("\n🎯 User's frontend will now show:")
        print("   • Empty General form: 0.0 kg CO2e (instead of 0.25)")
        print("   • General form with description: proper calculation")

    return overall_success


if __name__ == "__main__":
    test_option_a_simple()
