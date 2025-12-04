#!/usr/bin/env python3
"""
Test the exact payload the browser is sending based on console logs
"""

import json
import os

import django

import requests

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()


def test_browser_payload():
    print("🔍 TESTING BROWSER PAYLOAD")
    print("=" * 60)

    # Create a new soil management event with current timestamp
    from datetime import datetime, timezone

    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")

    browser_payload = {
        "date": current_time,
        "event_type": 5,
        "type": "ST",
        "area": "2.5",
        "area_unit": "ha",  # ✅ This confirms Fix #1 is working
        "soil_ph": "7.0",
        "organic_matter_percentage": "4.2",
        "soil_texture": "clay_loam",
        "soil_moisture": "optimal",
        "depth": "25",
        "depth_unit": "cm",
        "name": "New Soil Analysis - Testing Event Creation",
        "area_covered": "2.5",
        "fuel_consumed": "12",
        "fuel_unit": "L",
        "equipment_hours": "3",
        "transportation_distance": "8",
        "transportation_unit": "km",
        "equipment_used": "soil probe",
        "weather_conditions": "clear skies",
        "temperature_range": "18-22°C",
        "parcels": ["106"],
        "album_images": [],
        # ✅ This confirms Fix #2 is working - description field is included
        "description": "New soil management event created to demonstrate successful validation fixes. This event tests comprehensive soil analysis with improved pH and organic matter levels for optimal crop production.",
    }

    print("📤 Browser payload (with both fixes):")
    print(json.dumps(browser_payload, indent=2))
    print()

    from django.contrib.auth import get_user_model

    from rest_framework.test import APIClient

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
    response = client.post(url, browser_payload, format="json")

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
        event_id = response.data.get("id")
        print(f"📝 Created event ID: {event_id}")

        # Also extract from response headers if ID is not in response data
        if not event_id and hasattr(response, "_request") and hasattr(response._request, "url"):
            # Try to extract from Location header or URL
            location = response.get("Location", "")
            if location:
                import re

                id_match = re.search(r"/(\d+)/$", location)
                if id_match:
                    event_id = id_match.group(1)
                    print(f"📍 Event ID from Location header: {event_id}")

        # Print a clear final result
        print("=" * 60)
        print(f"🎯 FINAL RESULT: Soil Management Event ID = {event_id}")
        print("=" * 60)
        return event_id
    else:
        print(f"🤷 Unexpected response: {response.status_code}")
        print(f"Response: {response.data}")
        return None


if __name__ == "__main__":
    test_browser_payload()
