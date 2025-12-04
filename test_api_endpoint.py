#!/usr/bin/env python3
"""
Test the API endpoint that the frontend is calling to identify the discrepancy
"""

import json
import os
import sys

import django

import requests

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from django.contrib.auth import get_user_model

from rest_framework.authtoken.models import Token


def test_api_endpoint():
    """Test the API endpoint with the exact data from the form"""

    print("=== TESTING API ENDPOINT DIRECTLY ===")

    # Create a test user and token for authentication
    User = get_user_model()
    user, created = User.objects.get_or_create(email="test@example.com", defaults={"role": "admin", "is_active": True})
    token, _ = Token.objects.get_or_create(user=user)

    # The exact data that the frontend would send based on our form test
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
            "active_ingredient": "NPK 24-8-16",
        },
    }

    print("Request Data:")
    print(json.dumps(request_data, indent=2))
    print()

    # Test the optimized endpoint that the frontend likely uses
    url = "http://127.0.0.1:8000/api/carbon/calculate-event-carbon-impact-enhanced/"
    headers = {
        "Authorization": f"Token {token.key}",
        "Content-Type": "application/json",
    }

    try:
        print(f"Making request to: {url}")
        response = requests.post(url, json=request_data, headers=headers, timeout=10)

        print(f"Status Code: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print()

        if response.status_code == 200:
            result = response.json()
            print("=== API RESPONSE ===")
            print(json.dumps(result, indent=2))
            print()

            co2e = result.get("co2e", 0)
            print(f"CO2e Result: {co2e} kg")

            if co2e < 10:
                print("🚨 CRITICAL: API returning very low value (< 10 kg CO2e)")
                print("   This confirms the frontend-backend communication issue")
            elif co2e > 300:
                print("✅ API calculation looks correct (> 300 kg CO2e)")
                print("   Issue might be in frontend display or processing")
            else:
                print("⚠️  Moderate value - need to investigate further")

        else:
            print(f"Error Response: {response.text}")

    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to API - is the Django server running?")
        print("   Start it with: cd trazo-back && poetry run python manage.py runserver")
    except Exception as e:
        print(f"❌ Error testing API: {e}")


if __name__ == "__main__":
    test_api_endpoint()
