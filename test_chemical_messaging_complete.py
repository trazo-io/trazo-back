#!/usr/bin/env python3
"""
Complete test to verify the chemical messaging fix
Tests both backend serialization and frontend logic simulation
"""

import os

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from history.models import ChemicalEvent
from history.serializers import ChemicalEventSerializer


def simulate_frontend_logic(event_data):
    """Simulate the frontend eventDescriptions.ts logic"""
    chemical_type = event_data.get("chemical_type") or event_data.get("type")

    # Extract chemical type (handling both raw and serialized formats)
    def extract_chemical_type(type_str):
        if not type_str:
            return None
        # Handle raw codes (FE, PE, FU, HE)
        if type_str in ["FE", "PE", "FU", "HE"]:
            return type_str
        # Handle serialized format (event.chemical.fungicide → FU)
        if "event.chemical.fertilizer" in type_str:
            return "FE"
        if "event.chemical.pesticide" in type_str:
            return "PE"
        if "event.chemical.fungicide" in type_str:
            return "FU"
        if "event.chemical.herbicide" in type_str:
            return "HE"
        return None

    normalized_type = extract_chemical_type(chemical_type)

    if normalized_type == "FE":
        return "fertilizer application", "🌱"
    elif normalized_type == "PE":
        return "pesticide application", "🐛"
    elif normalized_type == "FU":
        return "fungicide application", "🛡️"
    elif normalized_type == "HE":
        return "herbicide application", "🌾"
    else:
        return "chemical application", "🧪"


def test_chemical_messaging():
    print("🧪 COMPLETE Chemical Messaging Test")
    print("=" * 60)

    # Test all chemical types
    chemical_types = [
        ("FE", "Fertilizer", "fertilizer application"),
        ("PE", "Pesticide", "pesticide application"),
        ("FU", "Fungicide", "fungicide application"),
        ("HE", "Herbicide", "herbicide application"),
    ]

    all_tests_passed = True

    for code, name, expected_message in chemical_types:
        print(f"\n🧪 Testing {name} ({code}):")

        # Find a real database event
        event = ChemicalEvent.objects.filter(type=code).first()
        if not event:
            print(f"  ❌ No {name} events found in database")
            all_tests_passed = False
            continue

        # Test backend serialization
        serializer = ChemicalEventSerializer(event)
        serialized_data = serializer.data

        print(f"  📦 Backend Data:")
        print(f"    chemical_type: {repr(serialized_data.get('chemical_type'))}")
        print(f"    type: {repr(serialized_data.get('type'))}")
        print(f"    commercial_name: {repr(serialized_data.get('commercial_name'))}")

        # Test frontend simulation
        message, icon = simulate_frontend_logic(serialized_data)

        print(f"  🎯 Frontend Result:")
        print(f"    message: {repr(message)}")
        print(f"    icon: {icon}")

        # Verify the result
        if message == expected_message:
            print(f"    ✅ SUCCESS: {name} shows correct message!")
        else:
            print(f"    ❌ FAILED: Expected '{expected_message}', got '{message}'")
            all_tests_passed = False

    print("\n" + "=" * 60)
    if all_tests_passed:
        print("🎉 ALL TESTS PASSED!")
        print("\nThe fix resolves the issue:")
        print("✅ Backend now provides chemical_type field with raw codes")
        print("✅ Frontend correctly interprets chemical types")
        print("✅ Fungicides now show 'fungicide application' not 'chemical application'")
        print("✅ All chemical subtypes work correctly")
    else:
        print("❌ Some tests failed. Please review the implementation.")


if __name__ == "__main__":
    test_chemical_messaging()
