#!/usr/bin/env python3
"""
Test if the description field is actually being sent in the payload
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


def test_description_field_scenarios():
    print("🔍 TESTING DESCRIPTION FIELD MAPPING SCENARIOS")
    print("=" * 60)

    User = get_user_model()
    user = User.objects.filter(email="oscar+evento@trazo.io").first()

    if not user:
        print("❌ User not found")
        return

    client = APIClient()
    client.force_authenticate(user=user)

    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    base_payload = {
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
        "name": "Description Test",
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
    }

    # Test 1: With description field (should work)
    print("📝 TEST 1: With description field")
    payload_with_description = {**base_payload, "description": "Test with description field"}

    response1 = client.post("/api/companies/18/establishments/47/events/", payload_with_description, format="json")
    print(f"   Status: {response1.status_code}")
    if response1.status_code == 201:
        print(f"   ✅ SUCCESS: Event created")
    else:
        print(f"   ❌ FAILED: {response1.data}")

    # Test 2: Without description field (should fail with 400)
    print("\n📝 TEST 2: WITHOUT description field")
    payload_without_description = base_payload.copy()

    response2 = client.post("/api/companies/18/establishments/47/events/", payload_without_description, format="json")
    print(f"   Status: {response2.status_code}")
    if response2.status_code == 400:
        print(f"   ❌ EXPECTED FAILURE: {response2.data}")
    else:
        print(f"   ❓ Unexpected: {response2.data}")

    # Test 3: With empty description field (might work)
    print("\n📝 TEST 3: With EMPTY description field")
    payload_empty_description = {**base_payload, "description": ""}

    response3 = client.post("/api/companies/18/establishments/47/events/", payload_empty_description, format="json")
    print(f"   Status: {response3.status_code}")
    if response3.status_code == 201:
        print(f"   ✅ SUCCESS: Event created with empty description")
    else:
        print(f"   ❌ FAILED: {response3.data}")

    # Test 4: Simulate browser payload (no observation field)
    print("\n🌐 TEST 4: BROWSER SIMULATION - No observation field")
    browser_payload = {
        **base_payload,
        "name": "Browser Simulation Test",
        # No observation field, no description field - simulates browser issue
    }

    response4 = client.post("/api/companies/18/establishments/47/events/", browser_payload, format="json")
    print(f"   Status: {response4.status_code}")
    print(f"   Response: {response4.data}")

    print("=" * 60)
    print("🔍 CONCLUSION:")
    if response2.status_code == 400 and response4.status_code == 400:
        print("✅ The description field IS required - browser payload missing description")
        print("🔧 Fix needed: Ensure observation field has content and maps to description")
    else:
        print("🤔 Unexpected results - check responses above")


if __name__ == "__main__":
    test_description_field_scenarios()
