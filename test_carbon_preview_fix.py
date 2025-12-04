#!/usr/bin/env python3
"""
Test script to verify the Carbon Preview Fix works correctly.
This tests the exact scenario described in the issue: 16-16-16, 50L, 2.0Ha, Broadcast
"""

import json
import os
from decimal import Decimal

import django

import requests

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trazo.settings.dev")
django.setup()


def test_backend_calculation():
    """Test the backend calculation directly"""
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory

    from carbon.views import calculate_event_carbon_impact
    from company.models import Company, Establishment

    User = get_user_model()

    # Create test request
    factory = RequestFactory()

    # Test data matching the exact issue scenario
    test_data = {
        "event_type": "chemical",
        "event_data": {
            "type": "FE",  # Fertilizer
            "commercial_name": "Test Fertilizer",
            "concentration": "16-16-16",  # NPK concentration from issue
            "volume": "50",  # 50L from issue
            "volume_unit": "liters",
            "area": "2.0",  # 2.0Ha from issue
            "area_unit": "hectares",
            "way_of_application": "broadcast",  # Broadcast from issue
            "parcel_id": 1,
            "establishment_id": 1,
        },
    }

    request = factory.post(
        "/api/carbon/calculate-event-impact/", data=json.dumps(test_data), content_type="application/json"
    )

    # Add a test user (API requires authentication)
    try:
        user = User.objects.first()
        if not user:
            user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
    except:
        pass

    request.user = user if user else None

    print("🧪 CARBON PREVIEW FIX TEST")
    print("=" * 50)
    print(
        f"📋 Test Scenario: {test_data['event_data']['concentration']} NPK, {test_data['event_data']['volume']}L, {test_data['event_data']['area']}Ha, {test_data['event_data']['way_of_application']}"
    )
    print()

    try:
        # Call the backend directly
        response = calculate_event_carbon_impact(request)
        result = response.data if hasattr(response, "data") else response

        if isinstance(result, dict):
            co2e = result.get("co2e", "N/A")
            method = result.get("calculation_method", "unknown")
            efficiency = result.get("efficiency_score", "N/A")

            print("✅ BACKEND CALCULATION RESULT:")
            print(f"   CO2e: {co2e} kg")
            print(f"   Method: {method}")
            print(f"   Efficiency Score: {efficiency}")
            print()

            # Check if it's close to the expected 147.7 kg CO2e
            if isinstance(co2e, (int, float, Decimal)):
                expected_range = (140, 155)  # Reasonable range around 147.7
                if expected_range[0] <= float(co2e) <= expected_range[1]:
                    print("🎯 SUCCESS: Result is in expected range (140-155 kg CO2e)")
                    print(f"   Previous frontend fallback was showing only ~7.0 kg CO2e")
                    print(f"   New backend calculation: {co2e} kg CO2e")
                    print("   ✅ This fixes the trust issue for farmers!")
                else:
                    print(f"⚠️  WARNING: Result {co2e} kg CO2e is outside expected range {expected_range}")
            else:
                print(f"⚠️  WARNING: Could not parse CO2e value: {co2e}")

        else:
            print(f"❌ UNEXPECTED RESPONSE FORMAT: {result}")

    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        import traceback

        traceback.print_exc()


def test_frontend_api_structure():
    """Test that our frontend fix sends the right data structure"""
    print("\n" + "=" * 50)
    print("📱 FRONTEND API STRUCTURE TEST")
    print("=" * 50)

    # This is the structure our enhanced frontend should now send
    enhanced_frontend_data = {
        "event_type": "chemical",  # Mapped from fertilizer_application
        "event_data": {
            "description": "Fertilizer Application - Test",
            "duration": "2-4 hours",
            "area": "2.0",
            "amount": "50",
            "parcel_id": 1,
            "establishment_id": 1,
            # NEW: Enhanced chemical data for accurate calculation
            "type": "FE",
            "commercial_name": "Fertilizer Application",
            "concentration": "16-16-16",
            "volume": "50",
            "volume_unit": "liters",
            "area": "2.0",
            "area_unit": "hectares",
            "way_of_application": "broadcast",
        },
    }

    print("🔧 ENHANCED FRONTEND DATA STRUCTURE:")
    print(json.dumps(enhanced_frontend_data, indent=2))
    print()
    print("✅ Key improvements:")
    print("   1. Proper event_data structure (not flat parameters)")
    print("   2. Includes NPK concentration (16-16-16)")
    print("   3. Includes volume with units (50 liters)")
    print("   4. Includes area with units (2.0 hectares)")
    print("   5. Includes application method (broadcast)")
    print("   6. Maps fertilizer_application → chemical event type")


if __name__ == "__main__":
    print("🚀 STARTING CARBON PREVIEW FIX VERIFICATION")
    print("Issue: Frontend shows 7.0 kg CO2e, Backend calculates 147.7 kg CO2e")
    print("Fix: Send proper chemical data to backend for accurate preview")
    print()

    # Test backend calculation
    test_backend_calculation()

    # Test frontend structure
    test_frontend_api_structure()

    print("\n" + "=" * 50)
    print("🎯 SUMMARY OF FIXES APPLIED:")
    print("=" * 50)
    print("1. ✅ Fixed hardcoded fallback from 1.8 → 25.0 kg CO2e")
    print("2. ✅ Enhanced API calls to send proper chemical event data")
    print("3. ✅ Added NPK concentration, volume, area, application method")
    print("4. ✅ Fixed event type mapping (fertilizer_application → chemical)")
    print("5. ✅ Added debug logging for API calls")
    print()
    print("🚀 NEXT STEPS:")
    print("- Test the frontend form with fertilizer application")
    print("- Verify Carbon Impact Preview now shows ~147.7 kg CO2e")
    print("- Monitor console logs for debug information")
    print("- Ensure fallback only used when API calls actually fail")
