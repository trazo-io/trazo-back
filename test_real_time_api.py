#!/usr/bin/env python3
"""
Test the real-time API endpoint directly with the same data from our form
"""

import json
import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from django.contrib.auth import get_user_model
from django.test import RequestFactory

from rest_framework.test import force_authenticate

from carbon.views import calculate_event_carbon_impact_enhanced


def test_real_time_api():
    """Test the real-time API directly with our form data"""

    print("=== TESTING REAL-TIME API ENDPOINT ===")

    # Create test user
    User = get_user_model()
    user = User.objects.create_user(email="test@example.com", password="testpass")

    # Create request factory
    factory = RequestFactory()

    # The exact data that the frontend sends
    request_data = {
        "event_type": "chemical",
        "event_data": {
            "type": "FE",  # Fertilizer
            "commercial_name": "Miracle-Gro All Purpose Plant Food",
            "concentration": "24-8-16",  # NPK content
            "volume": "500",  # Volume in liters
            "area": "2.5",  # Area in acres (will be converted)
            "area_unit": "acres",
            "way_of_application": "Broadcast",
        },
    }

    print("Request Data:")
    print(json.dumps(request_data, indent=2))
    print()

    # Create POST request
    request = factory.post(
        "/api/carbon/calculate-event-carbon-impact-enhanced/",
        data=json.dumps(request_data),
        content_type="application/json",
    )

    # Authenticate request
    force_authenticate(request, user=user)

    try:
        # Call the view directly
        response = calculate_event_carbon_impact_enhanced(request)

        print(f"Status Code: {response.status_code}")
        print()

        if response.status_code == 200:
            result = response.data
            print("=== API RESPONSE ===")
            print(json.dumps(result, indent=2))
            print()

            co2e = result.get("co2e", 0)
            print(f"CO2e Result: {co2e} kg")

            if co2e < 10:
                print("🚨 CRITICAL: API returning very low value (< 10 kg CO2e)")
                print("   Real-time API has the calculation bug")
            elif co2e > 300:
                print("✅ API calculation looks correct (> 300 kg CO2e)")
                print("   Real-time API is working properly")
            else:
                print("⚠️  Moderate value - need to investigate further")

        else:
            print(f"Error Response: {response.data}")

    except Exception as e:
        print(f"❌ Error testing API: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_real_time_api()
