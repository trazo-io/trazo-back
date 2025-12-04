#!/usr/bin/env python3
"""
Test the exact payload that's failing with the provided token.
"""

import json

import requests


def test_exact_failing_payload():
    """Test with the exact payload and token that's failing"""
    print("🔍 Testing EXACT failing payload with real token...")

    url = "http://localhost:8000/api/carbon/calculate-event-carbon/"

    # EXACT payload from user's error
    payload = {
        "event_type": "soil_management",
        "event_data": {
            "date": "2025-10-12T20:35",
            "event_type": "soil_management",
            "type": "ST",
            "area": "2",
            "area_unit": "hectares",
            "soil_ph": "6.5",
            "organic_matter_percentage": "3.5",
            "soil_texture": "loam",
            "soil_moisture": "moderate",
            "depth": "30",
            "depth_unit": "cm",
            "name": "",
            "area_covered": "",
            "fuel_consumed": "",
            "fuel_unit": "L",
            "equipment_hours": "",
            "production_efficiency": "",
            "transportation_distance": "",
            "transportation_unit": "km",
            "tillage_type": "",
            "tillage_intensity": "",
            "tillage_direction": "",
            "residue_management": "",
            "equipment_used": "soil auger",
            "weather_conditions": "dry conditions",
            "temperature_range": "20-25°C",
            "observation": "",
            "parcel_id": 105,
            "establishment_id": 44,
        },
    }

    # User's current token
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzYwMzAxNjg2LCJpYXQiOjE3NjAyOTk4ODYsImp0aSI6IjY2OTU4ZjFjYWZlMzQxNDI5YjM4MTNkMDMyZGFiODVkIiwidXNlcl9pZCI6NTZ9.aIhgnFC4dWTqscZW9FjuImcvABnqCuuxBglHLShs22g",
        "Content-Type": "application/json",
    }

    print(f"📤 Payload analysis:")
    print(f"   event_type: {payload['event_type']}")
    print(f"   type: {payload['event_data']['type']}")
    print(f"   area: {payload['event_data']['area']}")
    print(f"   fuel_consumed: '{payload['event_data']['fuel_consumed']}' (empty string)")
    print(f"   equipment_hours: '{payload['event_data']['equipment_hours']}' (empty string)")
    print(f"   area_covered: '{payload['event_data']['area_covered']}' (empty string)")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)

        print(f"\n📨 API Response:")
        print(f"   Status Code: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ SUCCESS!")
            print(f"   CO2e: {result.get('co2e', 'N/A')} kg")
            print(f"   Efficiency: {result.get('efficiency_score', 'N/A')}")
            print(f"   Method: {result.get('calculation_method', 'N/A')}")
            return True
        else:
            try:
                result = response.json()
                print(f"   ❌ FAILED!")
                print(f"   Response: {json.dumps(result, indent=4)}")
            except:
                print(f"   ❌ FAILED!")
                print(f"   Raw response: {response.text}")

            if response.status_code == 500:
                print(f"\n💥 500 ERROR CONFIRMED - Server-side issue!")

            return False

    except requests.exceptions.ConnectionError:
        print(f"\n🔌 CONNECTION ERROR: Can't connect to localhost:8000")
        return False
    except Exception as e:
        print(f"\n💥 REQUEST ERROR: {e}")
        return False


if __name__ == "__main__":
    print("🔍 EXACT FAILING PAYLOAD TEST")
    print("=" * 50)

    success = test_exact_failing_payload()

    if not success:
        print(f"\n🔧 NEED TO DEBUG SERVER-SIDE ISSUE")
        print(f"   The payload has good data but server returns 500")
        print(f"   Will investigate the backend calculator...")

    print(f"\n🏁 Test complete.")
