#!/usr/bin/env python3
"""
Comprehensive EPA/USDA Production Event Test
Tests EPA-verified carbon calculations for production events using same standards as weather events

Test Coverage:
1. Production event types: Irrigation, Harvesting, Planting, General
2. EPA/USDA verification indicators in preview API
3. Form data extraction and calculation accuracy
4. Verification badges and transparency indicators
5. Confidence scoring and data source documentation

Expected Results: 95%+ success rate with EPA verification
"""

import os
import sys
from datetime import datetime, timezone

import django

# Setup Django environment
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trazo.settings.dev")
django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import VerifiedEmissionFactors


def run_test(test_name, event_data, expected_min=None, expected_max=None, should_have_epa_sources=True):
    """Run a single production event test"""
    print(f"\n🧪 Testing: {test_name}")

    # Create mock event
    class MockEvent:
        def __init__(self, data):
            self.type = data.get("type", "IR")
            self.production_type = data.get("production_type", "")
            self.area_covered = data.get("area_covered", 1.0)
            self.fuel_consumed = data.get("fuel_consumed")
            self.equipment_operating_hours = data.get("equipment_operating_hours")
            self.volume = data.get("volume", "100 liters")
            self.area = data.get("area", "1.0 hectares")
            self.equipment = data.get("equipment", "tractor")
            self.extra_data = data.get("extra_data", {})

            # Mock history for crop information
            class MockHistory:
                def __init__(self):
                    self.product = MockProduct()

            class MockProduct:
                def __init__(self):
                    self.name = data.get("crop_name", "avocado")

            self.history = MockHistory()

    event = MockEvent(event_data)

    try:
        calculator = EventCarbonCalculator()
        result = calculator.calculate_production_event_impact(event)

        co2e = result.get("co2e", 0)
        calculation_method = result.get("calculation_method", "unknown")
        data_sources = result.get("data_sources", [])
        verification_status = result.get("verification_status", "unknown")
        confidence_level = result.get("confidence_level", 0)

        # Check EPA sources
        issues = []
        if should_have_epa_sources:
            if not any("EPA" in str(source) or "USDA" in str(source) for source in data_sources):
                issues.append("❌ No EPA/USDA sources found")
            else:
                print("✅ EPA/USDA sources verified")

        # Check verification status
        if verification_status in ["epa_usda_verified", "factors_verified"]:
            print("✅ EPA verification status confirmed")
        else:
            issues.append(f"⚠️ Verification status: {verification_status}")

        # Check calculation method
        if calculation_method == "verified_epa_usda_factors":
            print("✅ Using EPA/USDA verified calculation method")
        else:
            issues.append(f"⚠️ Calculation method: {calculation_method}")

        # Check expected range
        if expected_min is not None and co2e < expected_min:
            issues.append(f"❌ CO2e {co2e} below minimum {expected_min}")
        if expected_max is not None and co2e > expected_max:
            issues.append(f"❌ CO2e {co2e} above maximum {expected_max}")

        if not issues:
            print(f"✅ PASS: {co2e} kg CO2e (Method: {calculation_method})")

        return {
            "test_name": test_name,
            "co2e": co2e,
            "calculation_method": calculation_method,
            "data_sources": data_sources,
            "verification_status": verification_status,
            "confidence_level": confidence_level,
            "issues": issues,
            "success": len(issues) == 0,
        }

    except Exception as e:
        print(f"❌ FAIL: {e}")
        return {
            "test_name": test_name,
            "co2e": 0,
            "calculation_method": "error",
            "data_sources": [],
            "verification_status": "error",
            "confidence_level": 0,
            "issues": [f"Exception: {e}"],
            "success": False,
        }


def main():
    print("🌱 EPA/USDA Production Event Carbon Calculation Test")
    print("=" * 60)

    test_results = []

    # Test 1: Irrigation with area only (USDA standard factors)
    test_results.append(
        run_test(
            "Irrigation - Area Only (USDA standard)",
            {
                "type": "IR",
                "production_type": "irrigation",
                "area_covered": 2.0,
                "crop_name": "avocado",
                "extra_data": {},
            },
            expected_min=0.5,
            expected_max=10.0,
        )
    )

    # Test 2: Harvesting with fuel consumption (EPA actual data)
    test_results.append(
        run_test(
            "Harvesting - Actual Fuel Data (EPA verified)",
            {
                "type": "HA",
                "production_type": "harvesting avocado",
                "area_covered": 1.0,
                "fuel_consumed": 5.0,  # gallons
                "crop_name": "avocado",
                "extra_data": {},
            },
            expected_min=40.0,  # 5 gallons * 10.21 kg CO2/gallon
            expected_max=60.0,
        )
    )

    # Test 3: Planting with equipment hours (USDA estimate)
    test_results.append(
        run_test(
            "Planting - Equipment Hours (USDA estimate)",
            {
                "type": "PL",
                "production_type": "planting strawberry",
                "area_covered": 0.5,
                "equipment_operating_hours": 3.0,
                "crop_name": "strawberry",
                "extra_data": {},
            },
            expected_min=1.0,
            expected_max=15.0,
        )
    )

    # Test 4: General production (USDA standard factors)
    test_results.append(
        run_test(
            "General Production - Standard Factors",
            {
                "type": "GE",
                "production_type": "general production almond",
                "area_covered": 3.0,
                "crop_name": "almond",
                "extra_data": {},
            },
            expected_min=5.0,
            expected_max=25.0,
        )
    )

    # Test 5: Large irrigation with water volume
    test_results.append(
        run_test(
            "Large Irrigation - High Volume",
            {
                "type": "IR",
                "production_type": "irrigating avocado",
                "area_covered": 10.0,  # 10 acres
                "crop_name": "avocado",
                "extra_data": {},
            },
            expected_min=5.0,
            expected_max=50.0,
        )
    )

    # Test 6: Zero area edge case
    test_results.append(
        run_test(
            "Edge Case - Zero Area",
            {
                "type": "IR",
                "production_type": "irrigation",
                "area_covered": 0.0,
                "crop_name": "lettuce",
                "extra_data": {},
            },
            expected_min=0.0,
            expected_max=5.0,
        )
    )

    # Print summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for r in test_results if r["success"])
    total = len(test_results)
    success_rate = (passed / total) * 100

    print(f"Tests Passed: {passed}/{total} ({success_rate:.1f}%)")
    print(f"Expected: >95% success rate with EPA verification")

    # EPA verification summary
    epa_verified = sum(1 for r in test_results if r["calculation_method"] == "verified_epa_usda_factors")
    print(f"EPA/USDA Verified Calculations: {epa_verified}/{total} ({(epa_verified/total)*100:.1f}%)")

    # Data sources summary
    has_sources = sum(1 for r in test_results if len(r["data_sources"]) > 0)
    print(f"Tests with Data Sources: {has_sources}/{total} ({(has_sources/total)*100:.1f}%)")

    # Failed tests detail
    failed_tests = [r for r in test_results if not r["success"]]
    if failed_tests:
        print("\n❌ FAILED TESTS:")
        for test in failed_tests:
            print(f"  • {test['test_name']}")
            for issue in test["issues"]:
                print(f"    - {issue}")

    # Successful verification examples
    epa_verified_tests = [r for r in test_results if r["calculation_method"] == "verified_epa_usda_factors"]
    if epa_verified_tests:
        print("\n✅ EPA VERIFIED EXAMPLES:")
        for test in epa_verified_tests[:3]:  # Show first 3
            print(f"  • {test['test_name']}: {test['co2e']} kg CO2e")
            if test["data_sources"]:
                print(f"    Sources: {len(test['data_sources'])} EPA/USDA references")

    if success_rate >= 95:
        print(f"\n🎉 SUCCESS! Production events now use EPA/USDA verified emission factors")
        print("   Ready for production deployment with transparency standards")
    else:
        print(f"\n⚠️  Need improvement: {100-success_rate:.1f}% of tests failed")
        print("   Review failed calculations before deployment")

    return success_rate >= 95


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
