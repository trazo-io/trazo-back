#!/usr/bin/env python3
"""
PRODUCTION READINESS VALIDATION: Chemical Event System
Comprehensive test of all chemical event input combinations for production deployment
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
import django

django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor


def test_production_readiness():
    print("🚀 TRAZO CHEMICAL EVENT SYSTEM - PRODUCTION READINESS VALIDATION")
    print("=" * 80)

    # Initialize calculators
    standard_calculator = EventCarbonCalculator()
    optimized_calculator = OptimizedCarbonCalculator()

    # Test scenarios covering all chemical types and application methods
    test_scenarios = [
        {
            "name": "Fertilizer - Broadcast Application (Common)",
            "event_data": {
                "type": "FE",
                "commercial_name": "10-10-10 NPK Fertilizer",
                "volume": "50",
                "volume_unit": "liters",
                "area": "25",
                "area_unit": "acres",
                "concentration": "10-10-10",
                "way_of_application": "broadcast",
                "nitrogen_percentage": "10",
                "phosphorus_percentage": "10",
                "potassium_percentage": "10",
            },
            "expected_range": (80, 200),  # kg CO₂e
            "critical_checks": ["npk_content", "manufacturing_emissions", "application_emissions"],
        },
        {
            "name": "Pesticide - Spray Application (User's Original Scenario)",
            "event_data": {
                "type": "PE",
                "commercial_name": "Roundup Herbicide",
                "volume": "20",
                "volume_unit": "liters",
                "area": "50",
                "area_unit": "acres",
                "concentration": "2%",
                "way_of_application": "spray",
                "nitrogen_percentage": "",
                "phosphorus_percentage": "",
                "potassium_percentage": "",
            },
            "expected_range": (15, 40),  # kg CO₂e - NO manufacturing emissions
            "critical_checks": ["zero_npk", "application_only", "realistic_fuel"],
        },
        {
            "name": "Fungicide - Drip Irrigation (User's Fixed Scenario)",
            "event_data": {
                "type": "FU",
                "commercial_name": "Fungicide Treatment",
                "volume": "60",
                "volume_unit": "liters",
                "area": "123",
                "area_unit": "acres",
                "concentration": "1.5%",
                "way_of_application": "drip_irrigation",
                "nitrogen_percentage": "",
                "phosphorus_percentage": "",
                "potassium_percentage": "",
            },
            "expected_range": (40, 80),  # kg CO₂e - Efficient drip application
            "critical_checks": ["zero_npk", "drip_efficiency", "area_conversion"],
        },
        {
            "name": "Herbicide - Injection Application (Intensive)",
            "event_data": {
                "type": "HE",
                "commercial_name": "Pre-emergent Herbicide",
                "volume": "30",
                "volume_unit": "liters",
                "area": "15",
                "area_unit": "acres",
                "concentration": "3%",
                "way_of_application": "injection",
                "nitrogen_percentage": "",
                "phosphorus_percentage": "",
                "potassium_percentage": "",
            },
            "expected_range": (20, 60),  # kg CO₂e - Higher fuel consumption
            "critical_checks": ["zero_npk", "injection_fuel", "application_only"],
        },
        {
            "name": "Organic Fertilizer - Foliar Application",
            "event_data": {
                "type": "FE",
                "commercial_name": "Organic Fish Emulsion",
                "volume": "40",
                "volume_unit": "liters",
                "area": "10",
                "area_unit": "acres",
                "concentration": "5-3-2",
                "way_of_application": "foliar",
                "nitrogen_percentage": "5",
                "phosphorus_percentage": "3",
                "potassium_percentage": "2",
            },
            "expected_range": (25, 75),  # kg CO₂e - Lower NPK, moderate fuel
            "critical_checks": ["low_npk", "manufacturing_emissions", "foliar_efficiency"],
        },
    ]

    print("📝 TESTING COMPREHENSIVE CHEMICAL EVENT SCENARIOS")
    print("-" * 60)

    results_summary = []

    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n🧪 TEST {i}: {scenario['name']}")
        print(f"   Chemical Type: {scenario['event_data']['type']}")
        print(f"   Area: {scenario['event_data']['area']} {scenario['event_data']['area_unit']}")
        print(f"   Application: {scenario['event_data']['way_of_application']}")

        # Test optimized endpoint (the one users hit)
        processed_event = OptimizedEventProcessor.process_event_data("chemical", scenario["event_data"])
        result = optimized_calculator.calculate_chemical_impact_optimized(processed_event)

        co2e = result.get("co2e", 0)
        fuel_liters = result.get("application_fuel_liters", 0)
        npk_content = result.get("npk_content", {})
        manufacturing_emissions = result.get("manufacturing_emissions_kg_co2e", 0)

        print(f"   Results: {co2e} kg CO₂e, {fuel_liters:.1f}L fuel")
        print(f"   NPK: N={npk_content.get('N', 0)}, P={npk_content.get('P', 0)}, K={npk_content.get('K', 0)}")

        # Validation checks
        validations = []

        # Range check
        in_range = scenario["expected_range"][0] <= co2e <= scenario["expected_range"][1]
        validations.append(("Range Check", in_range, f"CO₂e within {scenario['expected_range']} kg"))

        # Critical checks based on scenario
        if "zero_npk" in scenario["critical_checks"]:
            zero_npk = all(npk_content.get(k, 0) == 0 for k in ["N", "P", "K"])
            validations.append(("Zero NPK", zero_npk, "Non-fertilizers have 0-0-0 NPK"))

        if "npk_content" in scenario["critical_checks"]:
            has_npk = any(npk_content.get(k, 0) > 0 for k in ["N", "P", "K"])
            validations.append(("NPK Content", has_npk, "Fertilizers have NPK content"))

        if "manufacturing_emissions" in scenario["critical_checks"]:
            has_manufacturing = manufacturing_emissions > 0
            validations.append(("Manufacturing", has_manufacturing, "Fertilizers have manufacturing emissions"))

        if "application_only" in scenario["critical_checks"]:
            no_manufacturing = manufacturing_emissions == 0
            validations.append(
                ("Application Only", no_manufacturing, "Non-fertilizers have NO manufacturing emissions")
            )

        if "area_conversion" in scenario["critical_checks"]:
            # Check that area was properly converted (acres to hectares)
            area_hectares = processed_event.get("area")
            original_acres = float(scenario["event_data"]["area"])
            expected_hectares = original_acres * 0.404686
            area_correct = abs(area_hectares - expected_hectares) < 0.1
            validations.append(
                ("Area Conversion", area_correct, f"Area: {original_acres} acres → {area_hectares:.1f} ha")
            )

        if "drip_efficiency" in scenario["critical_checks"]:
            # Drip irrigation should use ~0.4 L/ha
            area_hectares = processed_event.get("area")
            expected_fuel = area_hectares * 0.4
            drip_efficient = abs(fuel_liters - expected_fuel) < 2
            validations.append(
                ("Drip Efficiency", drip_efficient, f"Fuel: {fuel_liters:.1f}L (expected ~{expected_fuel:.1f}L)")
            )

        # EPA verification
        epa_verified = result.get("verification_status") == "epa_usda_verified"
        validations.append(("EPA Verified", epa_verified, "Using EPA/USDA emission factors"))

        # Display validation results
        passed = sum(1 for _, valid, _ in validations if valid)
        total = len(validations)

        print(f"   Validations: {passed}/{total} passed")
        for check_name, valid, description in validations:
            status = "✅" if valid else "❌"
            print(f"     {status} {check_name}: {description}")

        # Overall scenario assessment
        scenario_passed = passed == total
        results_summary.append(
            {"name": scenario["name"], "passed": scenario_passed, "score": f"{passed}/{total}", "co2e": co2e}
        )

        if scenario_passed:
            print(f"   🎉 SCENARIO PASSED")
        else:
            print(f"   ⚠️  SCENARIO NEEDS ATTENTION")

    print("\n" + "=" * 80)
    print("📊 PRODUCTION READINESS ASSESSMENT")
    print("=" * 80)

    total_scenarios = len(test_scenarios)
    passed_scenarios = sum(1 for r in results_summary if r["passed"])

    print(
        f"🎯 OVERALL RESULTS: {passed_scenarios}/{total_scenarios} scenarios passed ({passed_scenarios/total_scenarios*100:.1f}%)"
    )
    print()

    # Detailed breakdown
    for result in results_summary:
        status = "✅" if result["passed"] else "❌"
        print(f"{status} {result['name']}: {result['score']} ({result['co2e']} kg CO₂e)")

    print()
    print("🔍 KEY PRODUCTION READINESS INDICATORS:")

    # Critical fixes verification
    fertilizer_scenario = next((r for r in results_summary if "Fertilizer" in r["name"]), None)
    pesticide_scenario = next((r for r in results_summary if "Pesticide" in r["name"]), None)
    fungicide_scenario = next((r for r in results_summary if "Fungicide" in r["name"]), None)

    indicators = []

    if fertilizer_scenario and fertilizer_scenario["passed"]:
        indicators.append("✅ Fertilizer calculations with NPK handling")
    else:
        indicators.append("❌ Fertilizer calculations need work")

    if pesticide_scenario and pesticide_scenario["passed"]:
        indicators.append("✅ Pesticide calculations (application only)")
    else:
        indicators.append("❌ Pesticide calculations need work")

    if fungicide_scenario and fungicide_scenario["passed"]:
        indicators.append("✅ User's fungicide bug fixed")
    else:
        indicators.append("❌ User's fungicide bug still exists")

    # EPA compliance
    all_epa_verified = all(r["passed"] for r in results_summary)
    if all_epa_verified:
        indicators.append("✅ EPA/USDA compliance across all scenarios")
    else:
        indicators.append("⚠️  Some scenarios not EPA compliant")

    # Unit conversion handling
    area_scenarios_passed = sum(1 for r in results_summary if r["passed"])
    if area_scenarios_passed == total_scenarios:
        indicators.append("✅ Area unit conversions working correctly")
    else:
        indicators.append("❌ Area conversion issues detected")

    for indicator in indicators:
        print(f"  {indicator}")

    # Final recommendation
    print("\n" + "=" * 80)
    if passed_scenarios >= total_scenarios * 0.9:  # 90%+ pass rate
        print("🚀 PRODUCTION READY: Chemical event system meets production standards")
        print("✅ Farmers can trust the accuracy of carbon calculations")
        print("✅ EPA/USDA compliance maintained across chemical types")
        print("✅ Real-world agricultural scenarios properly handled")
        production_ready = True
    elif passed_scenarios >= total_scenarios * 0.7:  # 70%+ pass rate
        print("⚠️  NEARLY READY: Minor improvements needed before production")
        print("🔧 Address failing scenarios above")
        print("✅ Core functionality is solid")
        production_ready = False
    else:
        print("❌ NOT PRODUCTION READY: Significant issues need resolution")
        print("🚨 Multiple critical scenarios failing")
        print("🔧 Requires comprehensive fixes before deployment")
        production_ready = False

    print("=" * 80)

    return production_ready, results_summary


if __name__ == "__main__":
    ready, summary = test_production_readiness()
    exit(0 if ready else 1)
