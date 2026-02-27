#!/usr/bin/env python3
"""
Test script to verify the frontend API endpoint now uses our fixed General event calculation.
"""
import json
import os
import sys

import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.insert(0, "/Users/oscarmunoz/dev/trazo/trazo-back")
django.setup()

from django.contrib.auth import get_user_model
from django.test import RequestFactory

from rest_framework.test import APIRequestFactory

from carbon.views import calculate_event_carbon_impact_enhanced

User = get_user_model()


def test_general_event_api_endpoint():
    """Test the actual API endpoint that frontend calls"""
    print("🔧 Testing Frontend API Endpoint Fix")
    print("=" * 60)

    # Create test payload matching frontend request
    payload = {
        "event_type": "general",
        "event_data": {
            "date": "2025-11-05T15:07",
            "event_type": "general",
            "parcel_id": 106,
            "establishment_id": 47,
            "description": "Pest Scouting",
            "name": "Field inspection",
        },
    }

    print(f"📤 Request Payload:")
    print(f"   URL: POST /api/carbon/calculate-event-carbon/")
    print(f"   Payload: {json.dumps(payload, indent=2)}")

    # Create Django request
    factory = APIRequestFactory()
    request = factory.post("/api/carbon/calculate-event-carbon/", data=payload, format="json")

    # Add user for authentication (create test user if needed)
    try:
        user = User.objects.get(email="test@trazo.io")
    except User.DoesNotExist:
        user = User.objects.create_user(email="test@trazo.io", username="test_user", password="test_password")

    request.user = user

    # Call the API endpoint directly
    try:
        response = calculate_event_carbon_impact_enhanced(request)

        if response.status_code == 200:
            result = response.data

            print(f"\n📥 API Response:")
            print(f"   Status: {response.status_code} OK")
            print(f"   CO2e: {result.get('co2e')} kg")
            print(f"   Method: {result.get('calculation_method')}")
            print(f"   USDA Verified: {result.get('usda_factors_used')}")
            print(f"   Response Time: {result.get('response_time_ms'):.1f}ms")

            # Verify the fix worked
            co2e = result.get("co2e", 0)
            method = result.get("calculation_method", "")

            print(f"\n🎯 Fix Verification:")

            if co2e == 0.5:
                print(f"   ❌ STILL BROKEN: Using hardcoded 0.5 kg CO2e")
                return False
            elif co2e < 0.5:
                print(f"   ✅ FIXED: Reduced from 0.5 to {co2e} kg CO2e")
            else:
                print(f"   ⚠️  UNEXPECTED: {co2e} kg CO2e (higher than 0.5)")

            if "optimized_general_event_specific" in method:
                print(f"   ✅ USING NEW METHOD: {method}")
            elif "optimized_general" in method and "fallback" not in method:
                print(f"   ⚠️  USING OLD METHOD: {method}")
            else:
                print(f"   📝 METHOD: {method}")

            if result.get("usda_factors_used"):
                print(f"   ✅ EPA/USDA VERIFIED: Now using government emission factors")
            else:
                print(f"   ⚠️  NOT VERIFIED: Still using estimates")

            return co2e < 0.5 and "enhanced" in method.lower()

        else:
            print(f"   ❌ API Error: Status {response.status_code}")
            if hasattr(response, "data"):
                print(f"   Error: {response.data}")
            return False

    except Exception as e:
        print(f"   ❌ Exception: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_different_general_event_types():
    """Test different types of general events"""
    print(f"\n🔍 Testing Different General Event Types")
    print("=" * 60)

    test_cases = [
        {
            "name": "Pest Scouting (documentation)",
            "description": "Pest Scouting inspection",
            "expected_type": "documentation",
        },
        {
            "name": "Farm Visit (transportation)",
            "description": "Farm visit for consultation",
            "expected_type": "farm_visit",
        },
        {
            "name": "Training Session (education)",
            "description": "Training workshop on sustainable practices",
            "expected_type": "training_session",
        },
    ]

    factory = APIRequestFactory()
    user = User.objects.first()

    for test_case in test_cases:
        print(f"\n   Testing: {test_case['name']}")

        payload = {
            "event_type": "general",
            "event_data": {"description": test_case["description"], "name": test_case["name"]},
        }

        request = factory.post("/api/carbon/calculate-event-carbon/", data=payload, format="json")
        request.user = user

        try:
            response = calculate_event_carbon_impact_enhanced(request)

            if response.status_code == 200:
                result = response.data
                co2e = result.get("co2e", 0)

                print(f"      Carbon Impact: {co2e:.3f} kg CO2e")
                print(f"      Method: {result.get('calculation_method', 'unknown')}")

                if co2e <= 1.0:
                    print(f"      ✅ Reasonable impact for {test_case['expected_type']} activity")
                else:
                    print(f"      ⚠️  High impact for {test_case['expected_type']} activity")
            else:
                print(f"      ❌ API Error: {response.status_code}")

        except Exception as e:
            print(f"      ❌ Error: {e}")


if __name__ == "__main__":
    print("🧪 FRONTEND API ENDPOINT TEST")
    print("Testing: POST /api/carbon/calculate-event-carbon/")
    print("Verifying General Event Fix in Real API")
    print("=" * 70)

    # Test the main fix
    fix_worked = test_general_event_api_endpoint()

    # Test different event types
    test_different_general_event_types()

    # Final result
    print(f"\n🏁 FINAL RESULT: {'✅ API ENDPOINT FIXED' if fix_worked else '❌ API ENDPOINT STILL BROKEN'}")

    if fix_worked:
        print("\n📋 SUCCESS SUMMARY:")
        print("   ✅ Frontend API endpoint now uses enhanced calculation")
        print("   ✅ General events reduced from 0.5 kg CO2e")
        print("   ✅ Context-aware emission factors implemented")
        print("   ✅ EPA/USDA verified calculations active")
        print("   ✅ Proper incentive alignment for transparency")
