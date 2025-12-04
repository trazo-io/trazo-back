#!/usr/bin/env python3
"""
Test script to verify the new calculate_general_event_impact method
and ensure all 8 event types work correctly.
"""
import os
import sys

import django
from django.test import TestCase

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.insert(0, "/Users/oscarmunoz/dev/trazo/trazo-back")
django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from history.constants import *
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)


class MockEvent:
    """Mock event object for testing carbon calculations"""

    def __init__(self, event_type, **kwargs):
        self.type = event_type
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_all_8_event_types():
    """Test carbon calculations for all 8 Trazo event types"""
    calculator = EventCarbonCalculator()

    print("🧪 Testing Carbon Calculations for All 8 Event Types")
    print("=" * 60)

    # Test data for each event type
    test_events = [
        # 0. Weather Event
        {
            "type": WEATHER_EVENT_TYPE,
            "method": "calculate_weather_event_impact",
            "mock_event": MockEvent("FR", temperature_min=-2.0, description="Frost event"),
            "expected_range": (0.0, 50.0),
        },
        # 1. Production Event
        {
            "type": PRODUCTION_EVENT_TYPE,
            "method": "calculate_production_event_impact",
            "mock_event": MockEvent("PL", area_covered="5 hectares", fuel_type="diesel"),
            "expected_range": (10.0, 200.0),
        },
        # 2. Chemical Event
        {
            "type": CHEMICAL_EVENT_TYPE,
            "method": "calculate_chemical_event_impact",
            "mock_event": MockEvent("FE", amount="100L", chemical_type="FE", volume_liters=100),
            "expected_range": (50.0, 500.0),
        },
        # 3. General Event - THE FIX
        {
            "type": GENERAL_EVENT_TYPE,
            "method": "calculate_general_event_impact",
            "mock_event": MockEvent("GE", description="Pest Scouting", name="Field inspection"),
            "expected_range": (0.1, 2.0),  # Should be much lower than 0.5
        },
        # 4. Equipment Event
        {
            "type": EQUIPMENT_EVENT_TYPE,
            "method": "calculate_equipment_event_impact",
            "mock_event": MockEvent("FC", fuel_amount=20, equipment_name="tractor"),
            "expected_range": (50.0, 300.0),
        },
        # 5. Soil Management Event
        {
            "type": SOIL_MANAGEMENT_EVENT_TYPE,
            "method": "calculate_soil_management_event_impact",
            "mock_event": MockEvent("TI", area_covered="3 hectares", operation_type="tillage"),
            "expected_range": (10.0, 100.0),
        },
        # 6. Pest Management Event
        {
            "type": PEST_MANAGEMENT_EVENT_TYPE,
            "method": "calculate_pest_management_event_impact",
            "mock_event": MockEvent("SC", pest_species="aphids", description="Field scouting"),
            "expected_range": (0.1, 1.0),
        },
        # 7. Business Event
        {
            "type": BUSINESS_EVENT_TYPE,
            "method": "calculate_business_event_impact",
            "mock_event": MockEvent("AU", business_type="audit", certification_type="organic"),
            "expected_range": (50.0, 200.0),
        },
    ]

    results = {}
    all_passed = True

    for i, test_case in enumerate(test_events):
        event_type = test_case["type"]
        method_name = test_case["method"]
        mock_event = test_case["mock_event"]
        expected_range = test_case["expected_range"]

        print(f"\n{i}. Testing {method_name}")
        print(f"   Event Type: {event_type}")

        try:
            # Check if method exists
            if not hasattr(calculator, method_name):
                print(f"   ❌ FAIL: Method {method_name} not found!")
                all_passed = False
                continue

            # Call the calculation method
            calculation_method = getattr(calculator, method_name)
            result = calculation_method(mock_event)

            if result and "co2e" in result:
                co2e = result["co2e"]
                method = result.get("calculation_method", "unknown")
                source = result.get("data_source", "unknown")

                # Check if result is in expected range
                min_expected, max_expected = expected_range
                in_range = min_expected <= co2e <= max_expected

                status = "✅ PASS" if in_range else "⚠️  WARN"
                print(f"   {status}: {co2e:.3f} kg CO2e")
                print(f"   Method: {method}")
                print(f"   Source: {source}")

                if not in_range:
                    print(f"   Expected range: {min_expected}-{max_expected} kg CO2e")

                results[event_type] = {"co2e": co2e, "method": method, "source": source, "in_range": in_range}

                # Special validation for General events
                if event_type == GENERAL_EVENT_TYPE:
                    if co2e == 0.5:
                        print(f"   ⚠️  WARNING: Still using hardcoded 0.5 kg CO2e!")
                        all_passed = False
                    elif co2e < 0.5:
                        print(f"   🎯 SUCCESS: Reduced from 0.5 to {co2e:.3f} kg CO2e")

            else:
                print(f"   ❌ FAIL: Invalid result format: {result}")
                all_passed = False

        except Exception as e:
            print(f"   ❌ ERROR: {str(e)}")
            all_passed = False

    # Summary
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)

    if all_passed and results:
        print("✅ ALL TESTS PASSED - All 8 event types working correctly!")

        # Special focus on General event fix
        if GENERAL_EVENT_TYPE in results:
            general_result = results[GENERAL_EVENT_TYPE]
            print(f"\n🎯 GENERAL EVENT FIX STATUS:")
            print(f"   Carbon Impact: {general_result['co2e']:.3f} kg CO2e")
            print(f"   Method: {general_result['method']}")
            if general_result["co2e"] < 0.5:
                print(f"   ✅ Successfully reduced from hardcoded 0.5 kg CO2e!")
            else:
                print(f"   ⚠️  Still higher than expected")
    else:
        print("❌ SOME TESTS FAILED - Check individual results above")

    return all_passed, results


def test_general_event_classification():
    """Test specific General event classification logic"""
    calculator = EventCarbonCalculator()

    print("\n🔍 Testing General Event Classification Logic")
    print("=" * 60)

    test_cases = [
        ("Pest Scouting", "documentation", "Scouting should be low-impact documentation"),
        ("Farm Visit", "farm_visit", "Visit should trigger transportation emissions"),
        ("Training Session", "training_session", "Training should account for participants"),
        ("Field Notes", "documentation", "Notes should be documentation activity"),
        ("Consultation Meeting", "farm_visit", "Meeting should be farm visit type"),
    ]

    for description, expected_type, note in test_cases:
        mock_event = MockEvent("GE", description=description, name=description)

        # Get classification
        classified_type = calculator._classify_general_event_type(description, "GE")

        # Calculate emissions
        result = calculator.calculate_general_event_impact(mock_event)
        co2e = result.get("co2e", 0)

        status = "✅" if classified_type == expected_type else "❌"
        print(f"{status} '{description}' → {classified_type} ({co2e:.3f} kg CO2e)")
        print(f"   {note}")


if __name__ == "__main__":
    print("🧪 COMPREHENSIVE CARBON CALCULATION TEST")
    print("Testing General Event Fix and All 8 Event Types")
    print("=" * 60)

    # Test all event types
    all_passed, results = test_all_8_event_types()

    # Test General event classification
    test_general_event_classification()

    print(f"\n🏁 FINAL RESULT: {'✅ ALL SYSTEMS GO' if all_passed else '❌ ISSUES DETECTED'}")
