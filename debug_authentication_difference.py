#!/usr/bin/env python3
"""
Debug the authentication difference between browser and backend script
"""

import json
import os

import django

import requests

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from datetime import datetime, timezone

from django.contrib.auth import get_user_model

from rest_framework.test import APIClient


def debug_authentication_difference():
    print("🔍 DEBUGGING AUTHENTICATION DIFFERENCE")
    print("=" * 60)

    # Test 1: Backend script method (WORKING)
    print("🔬 TEST 1: Backend Script Method (Known to work)")
    print("-" * 40)

    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    payload = {
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
        "name": "Auth Debug Test",
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
        "description": "Authentication debugging test event",
    }

    User = get_user_model()
    user = User.objects.filter(email="oscar+evento@trazo.io").first()

    if not user:
        print("❌ User not found")
        return

    client = APIClient()
    client.force_authenticate(user=user)

    url = "/api/companies/18/establishments/47/events/"
    response = client.post(url, payload, format="json")

    print(f"📊 Backend Script Response: {response.status_code}")
    if response.status_code == 201:
        print(f"✅ SUCCESS: Event {response.data.get('name')} created")
    else:
        print(f"❌ FAILED: {response.data}")

    print()

    # Test 2: HTTP session method (like browser)
    print("🌐 TEST 2: HTTP Session Method (Like Browser)")
    print("-" * 40)

    session = requests.Session()

    # Step 1: Login like browser
    login_data = {"email": "oscar+evento@trazo.io", "password": "om123456"}

    # Get CSRF token first
    csrf_response = session.get("http://localhost:8000/api/csrf-token/")
    print(f"🔑 CSRF Response: {csrf_response.status_code}")

    if csrf_response.status_code == 200:
        csrf_token = csrf_response.json().get("csrf_token")  # Fixed: was 'csrfToken'
        if csrf_token:
            print(f"🎫 CSRF Token: {csrf_token[:20]}...")
        else:
            print("❌ CSRF token not found in response")
            return
    else:
        print("❌ Failed to get CSRF token")
        return

    headers = {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf_token,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "http://app.localhost:3000/admin/dashboard/establishment/47/parcel/106/event/add",
        "Origin": "http://app.localhost:3000",
    }

    # Login
    login_response = session.post("http://localhost:8000/api/auth/login/", json=login_data, headers=headers)

    print(f"🔐 Login Response: {login_response.status_code}")

    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.text}")
        return

    # Get new CSRF token after login
    csrf_response = session.get("http://localhost:8000/api/csrf-token/")
    if csrf_response.status_code == 200:
        csrf_token = csrf_response.json().get("csrf_token")  # Fixed: was 'csrfToken'
        headers["X-CSRFToken"] = csrf_token

    # Test event creation with session
    event_response = session.post(
        "http://localhost:8000/api/companies/18/establishments/47/events/", json=payload, headers=headers
    )

    print(f"📊 HTTP Session Response: {event_response.status_code}")
    print(f"📄 Response Headers: {dict(event_response.headers)}")

    if event_response.status_code == 201:
        print(f"✅ SUCCESS: Event created via HTTP session")
        try:
            data = event_response.json()
            print(f"📝 Event Name: {data.get('name')}")
        except:
            print("⚠️ Response not JSON")
    else:
        print(f"❌ FAILED: Status {event_response.status_code}")
        try:
            error_data = event_response.json()
            print(f"🚨 Error Details: {json.dumps(error_data, indent=2)}")
        except:
            print(f"🚨 Error Text: {event_response.text}")

    print("=" * 60)


if __name__ == "__main__":
    debug_authentication_difference()
