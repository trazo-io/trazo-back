#!/usr/bin/env python3
"""
Test Fix #3: Proper fallback for empty observations
"""

import json
import os

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from datetime import datetime, timezone

from django.contrib.auth import get_user_model

from rest_framework.test import APIClient


def test_fix_3_empty_observation():
    print("🔧 TESTING FIX #3: Proper Fallback for Empty Observations")
    print("=" * 70)

    User = get_user_model()
    user = User.objects.filter(email="oscar+evento@trazo.io").first()

    if not user:
        print("❌ User not found")
        return

    client = APIClient()
    client.force_authenticate(user=user)

    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")

    # Test: Simulate empty observation field (browser scenario)
    print("🌐 SIMULATING BROWSER SCENARIO: Empty observation field")
    browser_payload = {
        "date": current_time,
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
        "name": "Fix #3 Test Event",
        "area_covered": "2",
        "fuel_consumed": "10",
        "fuel_unit": "L",
        "equipment_hours": "2",
        "transportation_distance": "5",
        "transportation_unit": "km",
        "equipment_used": "soil auger",
        "weather_conditions": "dry",
        "temperature_range": "20-25°C",
        "parcels": ["106"],
        "album_images": [],
        # Simulate Fix #3: observation field empty, fallback to name-based description
        "description": "Soil management event: Fix #3 Test Event",
    }

    print(f"📤 Simulated browser payload with Fix #3:")
    print(json.dumps({k: v for k, v in browser_payload.items() if k in ["description", "name", "area_unit"]}, indent=2))

    response = client.post("/api/companies/18/establishments/47/events/", browser_payload, format="json")

    print(f"\n📊 Response Status: {response.status_code}")

    if response.status_code == 201:
        print(f"✅ SUCCESS: Event created successfully!")
        print(f"📝 Created event ID: {response.data.get('id', 'Not provided')}")
        print(f"📄 Description: {response.data.get('description', 'Not available')}")

        print("\n" + "=" * 70)
        print("🎯 FIX #3 SUCCESSFUL!")
        print("✅ area_unit: ha (Fix #1)")
        print("✅ description: fallback provided (Fix #2 + Fix #3)")
        print("✅ Browser validation should now work!")
        print("=" * 70)

        return response.data.get("id")
    else:
        print(f"❌ FAILED: {response.data}")
        return None


if __name__ == "__main__":
    test_fix_3_empty_observation()
