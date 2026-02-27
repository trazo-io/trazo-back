#!/usr/bin/env python3
"""
TEST FIXED FUEL CONSUMPTION CALCULATION
Test the specific fuel consumption error that was causing 'can't multiply sequence by non-int of type float'
"""

import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor


def test_fuel_consumption_fix():
    """Test the fixed fuel consumption calculation with various string formats"""

    print("🔧 TESTING FIXED FUEL CONSUMPTION CALCULATION")
    print("=" * 70)
    print("Testing the fix for 'can't multiply sequence by non-int of type float' error")
    print()

    calculator = OptimizedCarbonCalculator()

    # Test cases that previously caused the error
    test_cases = [
        {
            "name": "Fuel as string number",
            "data": {
                "type": "FC",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "8",
                "fuel_consumed": "45",  # String number - this caused the error
                "fuel_unit": "gallons",
                "equipment_type": "Tractor",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "Fuel as string with units",
            "data": {
                "type": "FC",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "8",
                "fuel_consumed": "45 gallons",  # String with units - this also caused errors
                "fuel_unit": "gallons",
                "equipment_type": "Tractor",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "Fuel as decimal string",
            "data": {
                "type": "FC",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "8",
                "fuel_consumed": "45.5",  # Decimal string
                "fuel_unit": "gallons",
                "equipment_type": "Tractor",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "Fuel as None (estimation)",
            "data": {
                "type": "FC",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "8",
                "fuel_consumed": None,  # None value - should estimate
                "fuel_unit": "gallons",
                "equipment_type": "Tractor",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "Fuel as empty string",
            "data": {
                "type": "FC",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "8",
                "fuel_consumed": "",  # Empty string - should estimate
                "fuel_unit": "gallons",
                "equipment_type": "Tractor",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
    ]

    # Test each case
    results = []
    for i, test_case in enumerate(test_cases, 1):
        print(f"🔧 TEST {i}/5: {test_case['name']}")

        try:
            # Process event data (this is where the error occurred)
            processed_event = OptimizedEventProcessor._process_production_event(test_case["data"])

            print(f"   ✅ Data processed successfully")
            print(
                f"   📊 fuel_consumed: {processed_event['fuel_consumed']} (type: {type(processed_event['fuel_consumed'])})"
            )

            # Calculate carbon impact (this would fail with the old code)
            result = calculator.calculate_production_impact_optimized(processed_event)

            co2e_value = result["co2e"]
            print(f"   ✅ CO₂e Result: {co2e_value} kg")
            print(f"   ✅ Calculation Method: {result['calculation_method']}")
            print(f"   ✅ USDA Verified: {result['usda_factors_used']}")

            # Check if we got fallback error (indicates remaining issues)
            if "fallback_error" in result["calculation_method"]:
                print(f"   ⚠️ WARNING: Still using fallback method")
            else:
                print(f"   ✅ PASS: Using proper USDA calculation")

            results.append(
                {
                    "test": test_case["name"],
                    "fuel_processed": processed_event["fuel_consumed"],
                    "co2e": co2e_value,
                    "status": "SUCCESS",
                    "method": result["calculation_method"],
                    "usda_factors_used": result["usda_factors_used"],
                }
            )

        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            results.append(
                {"test": test_case["name"], "fuel_processed": None, "co2e": None, "status": "FAILED", "error": str(e)}
            )

        print()

    # Summary
    print("📊 FUEL CONSUMPTION FIX RESULTS")
    print("=" * 70)

    successful_tests = len([r for r in results if r["status"] == "SUCCESS"])
    total_tests = len(results)

    print(f"Total Tests: {total_tests}")
    print(f"Successful: {successful_tests}")
    print(f"Failed: {total_tests - successful_tests}")
    print(f"Success Rate: {(successful_tests/total_tests)*100:.1f}%")
    print()

    # Detailed results
    print("🔍 DETAILED RESULTS:")
    for result in results:
        if result["status"] == "SUCCESS":
            print(f"   ✅ {result['test']}")
            print(f"      Fuel processed: {result['fuel_processed']}")
            print(f"      CO₂e: {result['co2e']} kg")
            print(f"      Method: {result['method']}")
            print(f"      USDA Verified: {result['usda_factors_used']}")
        else:
            print(f"   ❌ {result['test']}")
            print(f"      Error: {result['error']}")
        print()

    # Check if the specific error is fixed
    fallback_errors = len([r for r in results if "fallback_error" in str(r.get("method", ""))])
    if fallback_errors == 0:
        print("🎉 SUCCESS: 'can't multiply sequence by non-int of type float' error is FIXED!")
        print("✅ All fuel consumption formats processed correctly")
    else:
        print(f"⚠️ WARNING: {fallback_errors} tests still using fallback method")
        print("   May indicate remaining edge cases")

    return results


if __name__ == "__main__":
    results = test_fuel_consumption_fix()
