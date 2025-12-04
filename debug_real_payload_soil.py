#!/usr/bin/env python3
"""
Debug the exact payload that's causing the 500 error in production.
"""

import json
import os
import sys

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.views import EventCarbonCalculator, OptimizedEventProcessor


def test_real_payload():
    """Test with the exact payload from the user's error"""
    print("🔍 Testing REAL payload that's causing 500 error...")

    # EXACT payload from user's error report
    real_payload = {
        "event_type": "soil_management",
        "event_data": {
            "date": "2025-10-12T20:16",
            "event_type": "soil_management",
            "type": "ST",
            "area": "50",
            "area_unit": "hectares",
            "soil_ph": "6.5",
            "organic_matter_percentage": "3.5",
            "soil_texture": "loam",
            "soil_moisture": "moderate",
            "depth": "20",
            "depth_unit": "cm",
            "name": "Annual GPS Grid Soil Testing - Organic Certification",
            "area_covered": "50",
            "fuel_consumed": "20",
            "fuel_unit": "L",
            "equipment_hours": "12.5",
            "production_efficiency": "0.85",
            "transportation_distance": "2",
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

    event_type = real_payload["event_type"]
    event_data = real_payload["event_data"]

    print(f"📤 Testing with:")
    print(f"   event_type: {event_type}")
    print(f"   area: {event_data['area']} {event_data['area_unit']}")
    print(f"   fuel_consumed: {event_data['fuel_consumed']} {event_data['fuel_unit']}")
    print(f"   establishment_id: {event_data['establishment_id']}")
    print(f"   parcel_id: {event_data['parcel_id']}")

    try:
        # Step 1: Test OptimizedEventProcessor
        print(f"\n1️⃣ Processing with OptimizedEventProcessor...")
        processed_event = OptimizedEventProcessor.process_event_data(event_type, event_data)
        print(f"   ✅ Event processor completed")
        print(f"   📦 Processed keys: {list(processed_event.keys())}")

        # Check for any problematic values
        print(f"\n   🔍 Key processed values:")
        print(f"      area: {processed_event.get('area', 'MISSING')}")
        print(f"      area_covered: {processed_event.get('area_covered', 'MISSING')}")
        print(f"      fuel_consumed: {processed_event.get('fuel_consumed', 'MISSING')}")
        print(f"      equipment_hours: {processed_event.get('equipment_hours', 'MISSING')}")

        # Step 2: Test calculator with processed data
        print(f"\n2️⃣ Testing calculator...")

        class MockEvent:
            def __init__(self, processed_data):
                # Map all processed data to event attributes
                for key, value in processed_data.items():
                    setattr(self, key, value)

                # Add any missing attributes that calculator might need
                if hasattr(self, "soil_type"):
                    self.type = self.soil_type

                # Ensure area fields exist in multiple formats
                if hasattr(self, "area_covered"):
                    self.area = self.area_covered
                elif hasattr(self, "area"):
                    self.area_covered = self.area

                # Add IDs from event_data
                self.parcel_id = event_data.get("parcel_id")
                self.establishment_id = event_data.get("establishment_id")

                # Add date if needed
                self.date = event_data.get("date")

        mock_event = MockEvent(processed_event)

        print(f"   📦 Mock event attributes:")
        event_attrs = [attr for attr in dir(mock_event) if not attr.startswith("_")]
        for attr in sorted(event_attrs):
            value = getattr(mock_event, attr)
            if not callable(value):
                print(f"      {attr}: {value}")

        # Step 3: Run calculation
        print(f"\n3️⃣ Running carbon calculation...")
        calculator = EventCarbonCalculator()
        result = calculator.calculate_soil_management_event_impact(mock_event)

        print(f"   ✅ Calculation completed!")
        print(f"\n📈 RESULT:")
        print(f"   CO2e: {result.get('co2e', 'N/A')} kg")
        print(f"   Efficiency: {result.get('efficiency_score', 'N/A')}")
        print(f"   Method: {result.get('calculation_method', 'N/A')}")
        print(f"   Error: {result.get('error', 'None')}")
        print(f"   Fallback: {result.get('fallback_used', 'None')}")

        if result.get("error") or result.get("fallback_used"):
            print(f"\n⚠️  WARNING: Calculation had issues!")
            print(f"   This explains the 500 error response")
            return False
        else:
            print(f"\n✅ SUCCESS: No errors found!")
            return True

    except Exception as e:
        print(f"\n💥 EXCEPTION: {e}")
        import traceback

        traceback.print_exc()
        print(f"\n   This is likely the source of the 500 error!")
        return False


def test_api_simulation():
    """Simulate the complete API call process"""
    print(f"\n🌐 Simulating complete API process...")

    import io

    from django.test import RequestFactory

    from rest_framework.parsers import JSONParser

    from carbon.views import calculate_event_carbon_impact_enhanced

    # Real payload from user
    test_payload = {
        "event_type": "soil_management",
        "event_data": {
            "date": "2025-10-12T20:16",
            "event_type": "soil_management",
            "type": "ST",
            "area": "50",
            "area_unit": "hectares",
            "soil_ph": "6.5",
            "organic_matter_percentage": "3.5",
            "soil_texture": "loam",
            "soil_moisture": "moderate",
            "depth": "20",
            "depth_unit": "cm",
            "name": "Annual GPS Grid Soil Testing - Organic Certification",
            "area_covered": "50",
            "fuel_consumed": "20",
            "fuel_unit": "L",
            "equipment_hours": "12.5",
            "production_efficiency": "0.85",
            "transportation_distance": "2",
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

    try:
        # Create mock request (without authentication for testing)
        factory = RequestFactory()
        request = factory.post(
            "/api/carbon/calculate-event-carbon/", data=json.dumps(test_payload), content_type="application/json"
        )

        # Parse JSON data
        stream = io.BytesIO(request.body)
        data = JSONParser().parse(stream)
        request.data = data

        # Mock user for auth bypass
        from django.contrib.auth.models import AnonymousUser

        request.user = AnonymousUser()

        print(f"   📤 Sending request to API...")

        # This will likely fail due to authentication, but let's see what error we get
        response = calculate_event_carbon_impact_enhanced(request)

        print(f"   📨 Response status: {response.status_code}")

        if hasattr(response, "data"):
            result = response.data
        else:
            result = json.loads(response.content.decode())

        print(f"   📄 Response body: {json.dumps(result, indent=2)}")

        return response.status_code == 200

    except Exception as e:
        print(f"   💥 API simulation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🔍 REAL PAYLOAD SOIL MANAGEMENT DEBUG")
    print("=" * 60)

    # Test with the exact failing payload
    success = test_real_payload()

    if success:
        print(f"\n✅ The payload should work fine - issue might be elsewhere")
    else:
        print(f"\n❌ Found the problem with this specific payload")

    # Test API simulation
    print(f"\n" + "=" * 60)
    test_api_simulation()

    print(f"\n" + "=" * 60)
    print(f"🏁 Debug complete.")
