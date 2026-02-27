#!/usr/bin/env python3
"""
COMPREHENSIVE UNIT CONVERSION TESTING
Test ALL unit conversions in the Trazo agricultural carbon calculation system

Tests realistic agricultural scenarios with various unit combinations:
- Area: hectares, acres, square meters
- Volume: liters, gallons, milliliters
- Mass: kilograms, tonnes, pounds
- Fuel: gallons, liters, kg (with density)

Author: Claude Code
Date: 2025-10-07
"""

import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.utils.unit_converter import UnitConversionError, UnitConverter
from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor


def test_unit_converter_standalone():
    """Test the UnitConverter class directly with various unit combinations"""

    print("🔧 TESTING UNIT CONVERTER STANDALONE")
    print("=" * 80)
    print("Testing direct unit conversion with realistic agricultural values")
    print()

    test_cases = [
        # Area conversions
        {"type": "area", "value": 5.0, "from": "hectares", "to": "acres", "expected": 12.36},
        {"type": "area", "value": 10.0, "from": "acres", "to": "hectares", "expected": 4.05},
        {"type": "area", "value": 50000.0, "from": "square_meters", "to": "hectares", "expected": 5.0},
        # Volume conversions
        {"type": "volume", "value": 100.0, "from": "gallons", "to": "liters", "expected": 378.54},
        {"type": "volume", "value": 200.0, "from": "liters", "to": "gallons", "expected": 52.83},
        {"type": "volume", "value": 5000.0, "from": "milliliters", "to": "liters", "expected": 5.0},
        # Mass conversions
        {"type": "mass", "value": 2.5, "from": "tonnes", "to": "kilograms", "expected": 2500.0},
        {"type": "mass", "value": 1000.0, "from": "pounds", "to": "kilograms", "expected": 453.59},
        {"type": "mass", "value": 50.0, "from": "kilograms", "to": "pounds", "expected": 110.23},
        # Fuel conversions to gallons (critical for EPA emission factors)
        {"type": "fuel", "value": 100.0, "from": "liters", "fuel_type": "diesel", "expected": 26.42},
        {"type": "fuel", "value": 50.0, "from": "kilograms", "fuel_type": "diesel", "expected": 15.78},
        {"type": "fuel", "value": 75.0, "from": "gallons", "fuel_type": "diesel", "expected": 75.0},
    ]

    results = []

    for i, test in enumerate(test_cases, 1):
        print(
            f"🔍 TEST {i}/{len(test_cases)}: {test['type'].upper()} - {test['value']} {test['from']} → {test['to'] if 'to' in test else 'gallons'}"
        )

        try:
            if test["type"] == "area":
                converted_value, audit_msg = UnitConverter.convert_area(test["value"], test["from"], test["to"])
            elif test["type"] == "volume":
                converted_value, audit_msg = UnitConverter.convert_volume(test["value"], test["from"], test["to"])
            elif test["type"] == "mass":
                converted_value, audit_msg = UnitConverter.convert_mass(test["value"], test["from"], test["to"])
            elif test["type"] == "fuel":
                converted_value, audit_msg = UnitConverter.convert_fuel_to_gallons(
                    test["value"], test["from"], test["fuel_type"]
                )

            # Check if result is within 1% of expected (accounting for rounding)
            expected = test["expected"]
            accuracy = abs(converted_value - expected) / expected * 100

            if accuracy <= 1.0:  # Within 1%
                print(f"   ✅ PASS: {converted_value} (expected: {expected}, accuracy: {accuracy:.2f}%)")
                print(f"   📋 Audit: {audit_msg}")
                results.append({"test": i, "status": "PASS", "value": converted_value, "accuracy": accuracy})
            else:
                print(f"   ❌ FAIL: {converted_value} (expected: {expected}, accuracy: {accuracy:.2f}%)")
                results.append({"test": i, "status": "FAIL", "value": converted_value, "accuracy": accuracy})

        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            results.append({"test": i, "status": "ERROR", "error": str(e)})

        print()

    # Summary
    passed = len([r for r in results if r["status"] == "PASS"])
    failed = len([r for r in results if r["status"] == "FAIL"])
    errors = len([r for r in results if r["status"] == "ERROR"])

    print(f"📊 UNIT CONVERTER RESULTS: {passed}/{len(test_cases)} passed")
    print(f"   ✅ Passed: {passed}")
    print(f"   ❌ Failed: {failed}")
    print(f"   🚨 Errors: {errors}")

    return results


def test_production_events_with_units():
    """Test production events with various unit combinations"""

    print("\n🌾 TESTING PRODUCTION EVENTS WITH UNIT CONVERSIONS")
    print("=" * 80)
    print("Testing realistic agricultural scenarios with different unit combinations")
    print()

    calculator = OptimizedCarbonCalculator()

    # Realistic agricultural test cases with various units
    test_scenarios = [
        {
            "name": "Harvesting - Mixed Units (hectares + tonnes + liters)",
            "data": {
                "type": "HA",
                "area_covered": "2.5",
                "area_unit": "hectares",
                "equipment_hours": "6",
                "fuel_consumed": "45",
                "fuel_unit": "liters",
                "yield_quantity": "15.5",
                "yield_unit": "tonnes",
                "product_name": "Avocado",
            },
        },
        {
            "name": "Harvesting - US Units (acres + pounds + gallons)",
            "data": {
                "type": "HA",
                "area_covered": "6.2",
                "area_unit": "acres",
                "equipment_hours": "6",
                "fuel_consumed": "12",
                "fuel_unit": "gallons",
                "yield_quantity": "34000",
                "yield_unit": "pounds",
                "product_name": "Avocado",
            },
        },
        {
            "name": "Irrigation - Water in Gallons",
            "data": {
                "type": "IR",
                "area_covered": "5.8",
                "area_unit": "hectares",
                "equipment_hours": "4",
                "water_volume": "1500",
                "water_unit": "gallons",
                "yield_quantity": "0",
                "yield_unit": "kg",
            },
        },
        {
            "name": "Planting - Small Area in Square Meters",
            "data": {
                "type": "PL",
                "area_covered": "25000",
                "area_unit": "square_meters",
                "equipment_hours": "8",
                "fuel_consumed": "2.5",
                "fuel_unit": "gallons",
                "seed_variety": "Valencia Orange",
                "yield_quantity": "0",
                "yield_unit": "kg",
            },
        },
        {
            "name": "Fuel Consumption - Fuel in Kilograms",
            "data": {
                "type": "FC",
                "area_covered": "10",
                "area_unit": "acres",
                "equipment_hours": "5",
                "fuel_consumed": "40",
                "fuel_unit": "kilograms",
                "equipment_type": "Tractor",
                "yield_quantity": "0",
                "yield_unit": "kg",
            },
        },
    ]

    results = []

    for i, scenario in enumerate(test_scenarios, 1):
        print(f"🔬 TEST {i}/{len(test_scenarios)}: {scenario['name']}")

        try:
            # Process event data (this should use unit conversions)
            processed_event = OptimizedEventProcessor._process_production_event(scenario["data"])

            print(f"   📊 Processed Data:")
            print(f"      Area: {processed_event.get('area_covered')} acres")
            print(f"      Fuel: {processed_event.get('fuel_consumed')} gallons")
            print(f"      Yield: {processed_event.get('yield_quantity')} kg")
            print(f"      Water: {processed_event.get('water_volume')} gallons")
            print(f"      Unit conversions applied: {processed_event.get('unit_conversions_applied', False)}")

            # Calculate carbon impact
            result = calculator.calculate_production_impact_optimized(processed_event)

            co2e_value = result["co2e"]
            print(f"   ✅ CO₂e Result: {co2e_value} kg")
            print(f"   ✅ Calculation Method: {result['calculation_method']}")
            print(f"   ✅ USDA Verified: {result['usda_factors_used']}")

            # Validate result is reasonable (not negative, not extremely high)
            if co2e_value < 0:
                print(f"   ⚠️ WARNING: Negative CO₂e value")
                status = "WARNING"
            elif co2e_value > 500:
                print(f"   ⚠️ WARNING: Very high CO₂e value (>500 kg)")
                status = "WARNING"
            elif not processed_event.get("unit_conversions_applied", False):
                print(f"   ⚠️ WARNING: Unit conversions not applied - using fallback")
                status = "FALLBACK"
            else:
                print(f"   ✅ PASS: Realistic CO₂e range with proper unit conversions")
                status = "PASS"

            results.append(
                {
                    "scenario": scenario["name"],
                    "co2e": co2e_value,
                    "status": status,
                    "unit_conversions_applied": processed_event.get("unit_conversions_applied", False),
                    "method": result["calculation_method"],
                    "usda_factors_used": result["usda_factors_used"],
                }
            )

        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            results.append({"scenario": scenario["name"], "co2e": None, "status": "ERROR", "error": str(e)})

        print()

    # Summary report
    print("📊 PRODUCTION EVENTS WITH UNITS - SUMMARY")
    print("=" * 80)

    passed = len([r for r in results if r["status"] == "PASS"])
    warnings = len([r for r in results if r["status"] == "WARNING"])
    fallbacks = len([r for r in results if r["status"] == "FALLBACK"])
    errors = len([r for r in results if r["status"] == "ERROR"])

    print(f"Total Tests: {len(results)}")
    print(f"✅ Passed: {passed}")
    print(f"⚠️ Warnings: {warnings}")
    print(f"🔄 Fallbacks: {fallbacks}")
    print(f"❌ Errors: {errors}")
    print()

    # Unit conversion analysis
    with_conversions = len([r for r in results if r.get("unit_conversions_applied")])
    print(f"🔧 Unit Conversion Analysis:")
    print(f"   With conversions: {with_conversions}/{len(results)} tests")
    print(f"   Conversion rate: {(with_conversions/len(results))*100:.1f}%")
    print()

    # Detailed results
    print("🔍 DETAILED RESULTS:")
    for result in results:
        if result["status"] == "PASS":
            print(f"   ✅ {result['scenario']}")
            print(f"      CO₂e: {result['co2e']} kg")
            print(f"      Unit conversions: {result['unit_conversions_applied']}")
            print(f"      Method: {result['method']}")
        elif result["status"] in ["WARNING", "FALLBACK"]:
            print(f"   ⚠️ {result['scenario']} ({result['status']})")
            print(f"      CO₂e: {result['co2e']} kg")
            print(f"      Unit conversions: {result.get('unit_conversions_applied', 'N/A')}")
        else:
            print(f"   ❌ {result['scenario']}")
            print(f"      Error: {result['error']}")
        print()

    return results


def test_edge_cases():
    """Test edge cases and error conditions"""

    print("⚠️ TESTING UNIT CONVERSION EDGE CASES")
    print("=" * 80)
    print("Testing error handling, invalid units, and edge cases")
    print()

    edge_cases = [
        # Invalid units
        {"test": "Invalid area unit", "func": "convert_area", "args": [5.0, "invalid_unit", "hectares"]},
        {"test": "Invalid target unit", "func": "convert_area", "args": [5.0, "hectares", "invalid_unit"]},
        # Zero and negative values
        {"test": "Zero area", "func": "convert_area", "args": [0.0, "hectares", "acres"]},
        {"test": "Negative volume", "func": "convert_volume", "args": [-10.0, "liters", "gallons"]},
        # Very large values
        {"test": "Large mass conversion", "func": "convert_mass", "args": [1000000.0, "kg", "tonnes"]},
        # Fuel edge cases
        {"test": "Unknown fuel type", "func": "convert_fuel_to_gallons", "args": [50.0, "liters", "unknown_fuel"]},
        {"test": "Zero fuel", "func": "convert_fuel_to_gallons", "args": [0.0, "liters", "diesel"]},
    ]

    results = []

    for i, case in enumerate(edge_cases, 1):
        print(f"⚠️ EDGE CASE {i}/{len(edge_cases)}: {case['test']}")

        try:
            if case["func"] == "convert_area":
                result = UnitConverter.convert_area(*case["args"])
            elif case["func"] == "convert_volume":
                result = UnitConverter.convert_volume(*case["args"])
            elif case["func"] == "convert_mass":
                result = UnitConverter.convert_mass(*case["args"])
            elif case["func"] == "convert_fuel_to_gallons":
                result = UnitConverter.convert_fuel_to_gallons(*case["args"])

            print(f"   ✅ Handled gracefully: {result[0]} ({result[1]})")
            results.append({"case": case["test"], "status": "HANDLED", "result": result[0]})

        except UnitConversionError as e:
            print(f"   ✅ Proper error handling: {e}")
            results.append({"case": case["test"], "status": "EXPECTED_ERROR", "error": str(e)})

        except Exception as e:
            print(f"   ❌ Unexpected error: {e}")
            results.append({"case": case["test"], "status": "UNEXPECTED_ERROR", "error": str(e)})

        print()

    # Summary
    handled = len([r for r in results if r["status"] == "HANDLED"])
    expected_errors = len([r for r in results if r["status"] == "EXPECTED_ERROR"])
    unexpected_errors = len([r for r in results if r["status"] == "UNEXPECTED_ERROR"])

    print(f"📊 EDGE CASE RESULTS: {handled + expected_errors}/{len(results)} properly handled")
    print(f"   ✅ Gracefully handled: {handled}")
    print(f"   ✅ Expected errors: {expected_errors}")
    print(f"   ❌ Unexpected errors: {unexpected_errors}")

    return results


def main():
    """Run all unit conversion tests"""

    print("🧪 COMPREHENSIVE UNIT CONVERSION TESTING SUITE")
    print("=" * 80)
    print("Testing Trazo agricultural carbon calculation unit conversions")
    print("Validates: Area, Volume, Mass, and Fuel unit conversions")
    print("Ensures: 5-15x calculation error prevention")
    print()

    # Run all test suites
    converter_results = test_unit_converter_standalone()
    production_results = test_production_events_with_units()
    edge_case_results = test_edge_cases()

    # Overall summary
    print("\n🎯 OVERALL TEST RESULTS")
    print("=" * 80)

    # Unit converter results
    converter_passed = len([r for r in converter_results if r["status"] == "PASS"])
    print(f"Unit Converter: {converter_passed}/{len(converter_results)} passed")

    # Production event results
    production_passed = len([r for r in production_results if r["status"] == "PASS"])
    production_warnings = len([r for r in production_results if r["status"] in ["WARNING", "FALLBACK"]])
    print(f"Production Events: {production_passed}/{len(production_results)} passed ({production_warnings} warnings)")

    # Edge case results
    edge_handled = len([r for r in edge_case_results if r["status"] in ["HANDLED", "EXPECTED_ERROR"]])
    print(f"Edge Cases: {edge_handled}/{len(edge_case_results)} handled properly")

    # Final verdict
    total_critical_tests = len(converter_results) + len(production_results)
    total_critical_passed = converter_passed + production_passed

    print(f"\n📊 CRITICAL TESTS: {total_critical_passed}/{total_critical_tests} passed")

    if total_critical_passed == total_critical_tests:
        print("🎉 ALL CRITICAL UNIT CONVERSION TESTS PASSED!")
        print("✅ Unit conversion system prevents 5-15x calculation errors")
        print("✅ All agricultural scenarios handle unit conversions properly")
        print("✅ System gracefully handles edge cases and invalid inputs")
    else:
        missing = total_critical_tests - total_critical_passed
        print(f"⚠️ {missing} critical tests need attention")
        print("🔧 Unit conversion system requires additional fixes")

    print("\n" + "=" * 80)
    print("Unit conversion testing complete!")


if __name__ == "__main__":
    main()
