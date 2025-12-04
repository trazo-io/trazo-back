#!/usr/bin/env python3
"""
CRITICAL TEST: Compare API Endpoints for User's Fungicide Scenario
Tests both standard and optimized endpoints to identify which one is producing the bug
"""

import json
import os
import sys

import requests


def test_both_endpoints():
    print("🚨 CRITICAL API ENDPOINT COMPARISON TEST")
    print("=" * 70)

    # User's exact scenario from frontend
    user_data = {
        "event_type": "chemical",
        "event_data": {
            "type": "FU",  # Fungicide
            "commercial_name": "Miracle-Gro All Purpose",
            "volume": "60",
            "volume_unit": "liters",
            "area": "123",
            "area_unit": "acres",
            "concentration": "1.5%",
            "way_of_application": "drip_irrigation",
            "weather_conditions": "calm, humid conditions",
            "soil_moisture": "high",
            "temperature_range": "20-28°C",
            "wind_speed": "",
            "time_period": "evening",
            "observation": "",
            "nitrogen_percentage": "",
            "phosphorus_percentage": "",
            "potassium_percentage": "",
        },
    }

    print("📝 USER'S EXACT SCENARIO:")
    print(f"  Type: {user_data['event_data']['type']} (Fungicide)")
    print(f"  Area: {user_data['event_data']['area']} {user_data['event_data']['area_unit']}")
    print(f"  Volume: {user_data['event_data']['volume']} {user_data['event_data']['volume_unit']}")
    print(f"  Application: {user_data['event_data']['way_of_application']}")
    print()

    # Test endpoints (assuming Django dev server on localhost:8000)
    base_url = "http://localhost:8000/api/carbon"

    endpoints = {
        "Standard (EPA)": f"{base_url}/calculate-event-impact/",
        "Optimized (Fast)": f"{base_url}/calculate-event-impact-optimized/",
    }

    headers = {
        "Content-Type": "application/json",
    }

    print("🔍 TESTING BOTH ENDPOINTS:")
    print("-" * 50)

    results = {}

    for endpoint_name, endpoint_url in endpoints.items():
        print(f"\n📡 Testing {endpoint_name} endpoint...")
        print(f"   URL: {endpoint_url}")

        try:
            response = requests.post(endpoint_url, data=json.dumps(user_data), headers=headers, timeout=30)

            if response.status_code == 200:
                result = response.json()
                results[endpoint_name] = result

                co2e = result.get("co2e", "N/A")
                method = result.get("calculation_method", "N/A")

                print(f"   ✅ SUCCESS")
                print(f"   • CO₂e: {co2e} kg")
                print(f"   • Method: {method}")

                # Check for breakdown details
                breakdown = result.get("breakdown", {})
                if breakdown:
                    fuel_liters = breakdown.get("application_fuel_liters", "N/A")
                    fuel_gallons = breakdown.get("application_fuel_gallons", "N/A")
                    app_emissions = breakdown.get("application_emissions_kg_co2e", "N/A")
                    print(f"   • Fuel: {fuel_liters} L ({fuel_gallons} gal)")
                    print(f"   • App emissions: {app_emissions} kg")

            else:
                print(f"   ❌ FAILED: HTTP {response.status_code}")
                print(f"   Error: {response.text[:200]}...")

        except requests.exceptions.RequestException as e:
            print(f"   ❌ CONNECTION ERROR: {str(e)[:100]}...")
        except Exception as e:
            print(f"   ❌ UNEXPECTED ERROR: {str(e)[:100]}...")

    print()
    print("=" * 70)
    print("📊 COMPARISON ANALYSIS")
    print("=" * 70)

    # User's reported values
    user_reported_co2e = 331.755
    user_reported_fuel = 123.0

    print(f"🎯 USER REPORTED VALUES:")
    print(f"   • CO₂e: {user_reported_co2e} kg")
    print(f"   • Fuel: {user_reported_fuel} L")
    print()

    if results:
        for endpoint_name, result in results.items():
            co2e = result.get("co2e", 0)
            breakdown = result.get("breakdown", {})
            fuel_liters = breakdown.get("application_fuel_liters", 0)

            co2e_match = abs(float(co2e) - user_reported_co2e) < 5.0
            fuel_match = abs(float(fuel_liters) - user_reported_fuel) < 1.0

            print(f"🔍 {endpoint_name.upper()} ENDPOINT:")
            if co2e_match:
                print(f"   🎯 CO₂e MATCHES user report: {co2e} ≈ {user_reported_co2e}")
            else:
                print(f"   ❌ CO₂e different: {co2e} vs {user_reported_co2e}")

            if fuel_match:
                print(f"   🎯 FUEL MATCHES user report: {fuel_liters} ≈ {user_reported_fuel}")
            else:
                print(f"   ❌ Fuel different: {fuel_liters} vs {user_reported_fuel}")

            if co2e_match and fuel_match:
                print(f"   🚨 THIS IS THE BUGGY ENDPOINT!")
            elif not co2e_match and not fuel_match:
                print(f"   ✅ This endpoint likely has the fix")

            print()
    else:
        print("❌ No successful responses from either endpoint")
        print("🔧 Make sure Django dev server is running: python manage.py runserver")

    print("=" * 70)
    print("📋 NEXT STEPS")
    print("=" * 70)
    print("1. Start Django server: poetry run python manage.py runserver")
    print("2. Run this test again to identify the buggy endpoint")
    print("3. Fix the identified endpoint's area conversion")
    print("4. Ensure frontend uses the fixed endpoint")


if __name__ == "__main__":
    test_both_endpoints()
