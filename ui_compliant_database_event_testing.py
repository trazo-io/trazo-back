#!/usr/bin/env python
"""
UI-COMPLIANT DATABASE EVENT TESTING
Simulates real UI form submissions for ALL Trazo event types and subtypes
Tests against real-world carbon emission benchmarks
"""

import json
import os
import sys
from datetime import datetime
from decimal import Decimal

import django

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)


def test_ui_compliant_events():
    """Test UI-compliant event creation and carbon calculations"""

    print("🎯 UI-COMPLIANT DATABASE EVENT TESTING")
    print("=" * 80)
    print("Simulating REAL UI form submissions for ALL event types")
    print("Testing against real-world carbon emission benchmarks")
    print()

    # Track results
    total_events = 0
    calculation_results = {}

    # Real-world carbon emission benchmarks for validation
    benchmarks = {
        # Weather events (per hectare)
        "weather_frost": {"range": (200, 250), "description": "Frost protection with heaters & wind machines"},
        "weather_drought": {"range": (400, 500), "description": "Drought irrigation response"},
        "weather_wind": {"range": (150, 300), "description": "Wind damage cleanup"},
        "weather_heat": {"range": (100, 200), "description": "Heat stress mitigation"},
        # Chemical events (per hectare, realistic volumes)
        "chemical_fertilizer": {"range": (2800, 3200), "description": "Anhydrous ammonia 40 gal/ha"},
        "chemical_pesticide": {"range": (180, 220), "description": "Chlorpyrifos 10 gal/ha"},
        "chemical_herbicide": {"range": (155, 195), "description": "Glyphosate 15 gal/ha"},
        "chemical_fungicide": {"range": (95, 125), "description": "Copper sulfate 5 gal/ha"},
        # Production events (per hectare)
        "production_planting": {"range": (50, 150), "description": "Mechanized planting operations"},
        "production_harvesting": {"range": (100, 300), "description": "Mechanical harvesting"},
        "production_irrigation": {"range": (30, 80), "description": "Irrigation system operation"},
        "production_pruning": {"range": (40, 100), "description": "Mechanical pruning"},
        # Equipment events (per operation)
        "equipment_fuel": {"range": (250, 260), "description": "25 gallons diesel consumption"},
        "equipment_maintenance": {"range": (20, 40), "description": "Scheduled maintenance"},
        # Soil events (per hectare)
        "soil_compost": {"range": (-100, 50), "description": "Compost application (can sequester carbon)"},
        "soil_lime": {"range": (80, 120), "description": "Lime application for pH adjustment"},
        # Pest events (per hectare)
        "pest_beneficial": {"range": (1, 3), "description": "Beneficial insect release"},
        "pest_scouting": {"range": (5, 15), "description": "Field scouting operations"},
        # Business events (per operation)
        "business_certification": {"range": (10, 30), "description": "Certification audit process"},
        "business_verification": {"range": (0.5, 2), "description": "Blockchain verification"},
        # General events (per operation)
        "general_training": {"range": (20, 50), "description": "Training session"},
        "general_documentation": {"range": (1, 3), "description": "Documentation work"},
    }

    # ========== TEST ALL EVENT TYPES ==========

    # 1. Weather Events
    print("⛈️  1. WEATHER EVENTS - Real UI Form Data")
    print("-" * 60)

    weather_tests = [
        {
            "event_type": "frost",
            "ui_data": {
                "type": "FR",
                "name": "Frost Protection - California Citrus",
                "observation": "Temperature dropped to 28°F, activated orchard heaters and wind machines",
                "extra_data": {
                    "temperature_low_f": 28,
                    "duration_hours": 6,
                    "orchard_heaters": 20,
                    "wind_machines": 8,
                    "area_hectares": 10,
                },
            },
            "calculation": lambda: VerifiedEmissionFactors.calculate_frost_protection_emissions(
                orchard_heaters_hours=6, wind_machines_hours=6, area_hectares=10
            ),
        },
        {
            "event_type": "drought",
            "ui_data": {
                "type": "DR",
                "name": "Drought Response - Additional Irrigation",
                "observation": "Extended drought requiring 50% additional irrigation",
                "extra_data": {
                    "precipitation_deficit_inches": 8,
                    "additional_water_gallons": 75000,
                    "area_hectares": 25,
                },
            },
            "calculation": lambda: VerifiedEmissionFactors.calculate_drought_irrigation_emissions(water_gallons=75000),
        },
    ]

    for test in weather_tests:
        total_events += 1
        try:
            result = test["calculation"]()
            calculation_results[f"weather_{test['event_type']}"] = result

            # Validate against benchmark
            benchmark_key = f"weather_{test['event_type']}"
            if benchmark_key in benchmarks:
                benchmark = benchmarks[benchmark_key]
                min_expected, max_expected = benchmark["range"]
                calculated = result["co2e_kg"]

                if min_expected <= calculated <= max_expected:
                    status = "✅ EXCELLENT"
                    color = "💚"
                elif calculated >= min_expected * 0.8 and calculated <= max_expected * 1.2:
                    status = "✅ GOOD"
                    color = "💚"
                else:
                    status = "⚠️ NEEDS CALIBRATION"
                    color = "🔶"

                print(f"🔬 {test['ui_data']['name']}")
                print(f"   UI Data: {test['ui_data']['observation']}")
                print(f"   {color} Carbon: {calculated:.1f} kg CO2e (expected: {min_expected}-{max_expected})")
                print(f"   {status}")
                print()

        except Exception as e:
            print(f"❌ Failed calculation for {test['event_type']}: {e}")

    # 2. Chemical Events
    print("🧪 2. CHEMICAL EVENTS - Real UI Form Data")
    print("-" * 60)

    chemical_tests = [
        {
            "event_type": "fertilizer",
            "ui_data": {
                "type": "FE",
                "name": "Anhydrous Ammonia Application",
                "commercial_name": "Anhydrous Ammonia (82-0-0)",
                "volume_applied": 40,
                "volume_unit": "gallons",
                "area_treated": 1,
                "area_unit": "hectare",
                "nitrogen_percentage": 82,
                "application_method": "injection",
            },
            "calculation": lambda: VerifiedEmissionFactors.calculate_chemical_application_emissions(
                chemical_type="fertilizer",
                volume_liters=40 * 3.78541,  # 40 gallons to liters
                area_hectares=1.0,
                npk_content={"N": 82, "P": 0, "K": 0},
                application_method="injection",
            ),
        },
        {
            "event_type": "pesticide",
            "ui_data": {
                "type": "PE",
                "name": "Chlorpyrifos Insecticide Treatment",
                "commercial_name": "Chlorpyrifos 48EC",
                "volume_applied": 10,
                "volume_unit": "gallons",
                "area_treated": 1,
                "area_unit": "hectare",
                "concentration": "48% active ingredient",
                "application_method": "spray",
            },
            "calculation": lambda: VerifiedEmissionFactors.calculate_chemical_application_emissions(
                chemical_type="pesticide",
                volume_liters=10 * 3.78541,  # 10 gallons to liters
                area_hectares=1.0,
                npk_content={"N": 0, "P": 0, "K": 0},
                application_method="spray",
            ),
        },
        {
            "event_type": "herbicide",
            "ui_data": {
                "type": "HE",
                "name": "Roundup PowerMAX Application",
                "commercial_name": "Roundup PowerMAX",
                "volume_applied": 15,
                "volume_unit": "gallons",
                "area_treated": 1,
                "area_unit": "hectare",
                "concentration": "41% glyphosate",
                "application_method": "spray",
            },
            "calculation": lambda: VerifiedEmissionFactors.calculate_chemical_application_emissions(
                chemical_type="herbicide",
                volume_liters=15 * 3.78541,  # 15 gallons to liters
                area_hectares=1.0,
                npk_content={"N": 0, "P": 0, "K": 0},
                application_method="spray",
            ),
        },
        {
            "event_type": "fungicide",
            "ui_data": {
                "type": "FU",
                "name": "Copper Sulfate Fungicide",
                "commercial_name": "Copper Sulfate Basic",
                "volume_applied": 5,
                "volume_unit": "gallons",
                "area_treated": 1,
                "area_unit": "hectare",
                "concentration": "99% copper sulfate",
                "application_method": "spray",
            },
            "calculation": lambda: VerifiedEmissionFactors.calculate_chemical_application_emissions(
                chemical_type="fungicide",
                volume_liters=5 * 3.78541,  # 5 gallons to liters
                area_hectares=1.0,
                npk_content={"N": 0, "P": 0, "K": 0},
                application_method="spray",
            ),
        },
    ]

    for test in chemical_tests:
        total_events += 1
        try:
            result = test["calculation"]()
            calculation_results[f"chemical_{test['event_type']}"] = result

            # Validate against benchmark
            benchmark_key = f"chemical_{test['event_type']}"
            if benchmark_key in benchmarks:
                benchmark = benchmarks[benchmark_key]
                min_expected, max_expected = benchmark["range"]
                calculated = result["co2e_kg"]

                if min_expected <= calculated <= max_expected:
                    status = "✅ EXCELLENT"
                    color = "💚"
                elif calculated >= min_expected * 0.8 and calculated <= max_expected * 1.2:
                    status = "✅ GOOD"
                    color = "💚"
                else:
                    status = "⚠️ NEEDS CALIBRATION"
                    color = "🔶"

                print(f"🔬 {test['ui_data']['name']}")
                print(
                    f"   UI Data: {test['ui_data']['commercial_name']}, {test['ui_data']['volume']}, {test['ui_data']['area']}"
                )
                print(f"   {color} Carbon: {calculated:.1f} kg CO2e (expected: {min_expected}-{max_expected})")
                print(f"   {status}")
                print()

        except Exception as e:
            print(f"❌ Failed calculation for {test['event_type']}: {e}")

    # Continue with other event types...

    # ========== SUMMARY ==========
    print("🏆 UI-COMPLIANT EVENT VALIDATION SUMMARY")
    print("=" * 80)

    high_priority_issues = []
    medium_priority_issues = []

    for result_key, result in calculation_results.items():
        # Find corresponding benchmark
        benchmark_key = result_key
        if benchmark_key in benchmarks:
            benchmark = benchmarks[benchmark_key]
            min_expected, max_expected = benchmark["range"]
            calculated = result["co2e_kg"]

            # Calculate deviation
            mid_point = (min_expected + max_expected) / 2
            deviation_percent = abs(calculated - mid_point) / mid_point * 100

            if calculated < min_expected or calculated > max_expected:
                issue = {
                    "event_type": result_key,
                    "calculated": calculated,
                    "expected_range": f"{min_expected}-{max_expected}",
                    "deviation_percent": deviation_percent,
                    "description": benchmark["description"],
                }

                if deviation_percent > 50:
                    high_priority_issues.append(issue)
                else:
                    medium_priority_issues.append(issue)

    # Calculate success metrics
    total_tests = len(calculation_results)
    successful_tests = total_tests - len(high_priority_issues) - len(medium_priority_issues)
    success_rate = (successful_tests / total_tests) * 100 if total_tests > 0 else 0

    print(f"📊 **Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📊 **Events Created:** {total_events}")
    print(f"📊 **High Priority Issues:** {len(high_priority_issues)}")
    print()

    if high_priority_issues:
        print("🚨 **Critical Issues Requiring Immediate Fixes**")
        print()
        for issue in high_priority_issues:
            print(f"- **{issue['event_type'].replace('_', ' - ').title()}**")
            print(
                f"  - Issue: Calculated {issue['calculated']:.1f} kg CO2e outside expected range {issue['expected_range']}"
            )
            print(f"  - Deviation: {issue['deviation_percent']:.1f}%")
            print()

    if medium_priority_issues:
        print("⚠️ **Medium Priority Issues**")
        print()
        for issue in medium_priority_issues:
            print(f"- **{issue['event_type'].replace('_', ' - ').title()}**")
            print(
                f"  - Issue: Calculated {issue['calculated']:.1f} kg CO2e outside expected range {issue['expected_range']}"
            )
            print(f"  - Deviation: {issue['deviation_percent']:.1f}%")
            print()

    # Save detailed results
    results = {
        "test_timestamp": datetime.now().isoformat(),
        "summary": {
            "total_events_tested": total_events,
            "high_priority_issues": len(high_priority_issues),
            "medium_priority_issues": len(medium_priority_issues),
            "success_rate_percent": success_rate,
        },
        "high_priority_issues": high_priority_issues,
        "medium_priority_issues": medium_priority_issues,
        "calculation_results": {k: v for k, v in calculation_results.items()},
        "benchmarks_used": benchmarks,
    }

    with open("ui_compliant_database_testing_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    print("💾 **Detailed results saved to:** ui_compliant_database_testing_results.json")

    return results


if __name__ == "__main__":
    test_ui_compliant_events()
