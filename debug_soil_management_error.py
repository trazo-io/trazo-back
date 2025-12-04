#!/usr/bin/env python3
"""
Debug the exact soil management validation error
"""

import json
import os

import django

import requests

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from django.contrib.auth import get_user_model

from rest_framework.test import APIClient


def debug_soil_management_submission():
    print("🔍 DEBUGGING SOIL MANAGEMENT VALIDATION ERROR")
    print("=" * 60)

    # Test the exact payload that the frontend is sending
    test_payload = {
        "date": "2025-11-10T01:48",
        "event_type": 5,
        "type": "ST",
        "area": "2",
        "area_unit": "ha",
        "soil_ph": "6.5",
        "organic_matter_percentage": "3.5",
        "soil_texture": "loam",
        "soil_moisture": "moderate",
        "depth": "30",
        "depth_unit": "cm",
        "name": "Spring",
        "area_covered": "2",
        "fuel_consumed": "15",
        "fuel_unit": "L",
        "equipment_hours": "4",
        "transportation_unit": "km",
        "equipment_used": "soil auger",
        "weather_conditions": "dry conditions",
        "temperature_range": "20-25°C",
        "parcels": ["106"],
        "album_images": [],
        # The fix: Add description field mapped from observation
        "description": "Testing soil management with good pH levels and organic matter for spring season preparation.",
    }

    print("📤 Test payload:")
    print(json.dumps(test_payload, indent=2))
    print()

    # Get the user
    User = get_user_model()
    user = User.objects.filter(email="oscar+evento@trazo.io").first()

    if not user:
        print("❌ User oscar+evento@trazo.io not found")
        return

    print(f"👤 Found user: {user.email}")

    # Create authenticated client
    client = APIClient()
    client.force_authenticate(user=user)

    # Make the request
    url = "/api/companies/18/establishments/47/events/"
    response = client.post(url, test_payload, format="json")

    print(f"🌐 POST {url}")
    print(f"📊 Response Status: {response.status_code}")
    print(f"📄 Response Data: {response.data}")
    print()

    if response.status_code == 400:
        print("❌ VALIDATION ERRORS:")
        for field, errors in response.data.items():
            if isinstance(errors, list):
                for error in errors:
                    print(f"  • {field}: {error}")
            else:
                print(f"  • {field}: {errors}")
    elif response.status_code == 201:
        print("✅ SUCCESS: Event created successfully!")
        print(f"📝 Created event ID: {response.data.get('id')}")
    else:
        print(f"🤷 Unexpected response: {response.status_code}")
        print(f"Response: {response.data}")


if __name__ == "__main__":
    debug_soil_management_submission()
