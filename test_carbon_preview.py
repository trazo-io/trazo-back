#!/usr/bin/env python3
"""
Test the carbon impact preview functionality for soil management events
"""
import json
import os
import sys

import django

import requests

# Setup Django
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator


def test_carbon_api_preview():
    """Test carbon calculation via API endpoints"""

    # Test data similar to what the frontend would send
    test_event_data = {
        "event_type": "soil_management",
        "event_data": {
            "type": "ST",
            "area": "2.0",
            "area_unit": "ha",
            "soil_ph": "6.5",
            "organic_matter_percentage": "3.5",
            "depth": "30",
            "depth_unit": "cm",
            "fuel_consumed": "20.0",
            "fuel_unit": "L",
            "equipment_hours": "4.0",
            "name": "Spring Soil Testing",
            "area_covered": "2.0",
            "date": "2024-11-10T12:00:00",
            "parcel_id": 106,
            "establishment_id": 47,
        },
    }

    try:
        # Test the API endpoint directly
        api_url = "http://localhost:8000/api/carbon/calculate-event-carbon/"

        print("🧪 Testing carbon preview API...")
        print(f"📡 POST {api_url}")
        print(f"📋 Data: {json.dumps(test_event_data, indent=2)}")

        response = requests.post(
            api_url,
            json=test_event_data,
            headers={
                "Content-Type": "application/json",
            },
            timeout=10,
        )

        print(f"📈 Response Status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print("✅ Carbon preview API successful!")
            print(f"   - CO2e: {result.get('co2e')} kg")
            print(f"   - Efficiency score: {result.get('efficiency_score')}")
            print(f"   - Event type: {result.get('event_type')}")
            print(f"   - USDA verified: {result.get('usda_verified')}")
            print(f"   - Error: {result.get('error', 'None')}")
            print(f"   - Timestamp: {result.get('timestamp')}")
            return True
        else:
            print(f"❌ API request failed: {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Error details: {error_data}")
            except:
                print(f"   Raw response: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to Django server. Is it running on localhost:8000?")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


def test_direct_calculation():
    """Test carbon calculation directly via service"""

    print("\n🧪 Testing direct carbon calculation...")

    try:
        calculator = EventCarbonCalculator()

        # Test data for soil management event
        test_data = {
            "type": "ST",
            "area": 2.0,
            "area_unit": "ha",
            "fuel_consumed": 20.0,
            "fuel_unit": "L",
            "equipment_hours": 4.0,
            "soil_ph": 6.5,
            "organic_matter_percentage": 3.5,
            "depth": 30,
            "depth_unit": "cm",
        }

        # Create a mock event object
        class MockEvent:
            def __init__(self, data):
                for key, value in data.items():
                    setattr(self, key, value)

        mock_event = MockEvent(test_data)

        result = calculator.calculate_soil_management_event_impact(mock_event)

        print("✅ Direct calculation successful!")
        print(f"   - CO2e: {result.get('co2e')} kg")
        print(f"   - Efficiency score: {result.get('efficiency_score')}")
        print(f"   - USDA factors: {result.get('usda_factors_based')}")
        print(f"   - Error: {result.get('error', 'None')}")
        return True

    except Exception as e:
        print(f"❌ Direct calculation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🧪 Testing Carbon Preview Functionality for Soil Management")
    print("=" * 60)

    # Test direct calculation
    direct_success = test_direct_calculation()

    # Test API endpoint
    api_success = test_carbon_api_preview()

    print("\n" + "=" * 60)
    if direct_success and api_success:
        print("🎉 All tests passed! Carbon preview should work correctly.")
    elif direct_success:
        print("⚠️ Direct calculation works, but API has issues. Check Django server.")
    elif api_success:
        print("⚠️ API works, but direct calculation has issues. Check service logic.")
    else:
        print("❌ Both tests failed. Carbon preview likely broken.")
