#!/usr/bin/env python3
"""
Create a comprehensive soil management event via API to test enhanced display
"""
import json

import requests


def create_enhanced_soil_event():
    """Create a comprehensive soil management event via API"""

    # Login to get token
    login_url = "http://localhost:8000/api/auth/login/"
    login_data = {"email": "oscar+evento@trazo.io", "password": "om123456"}

    session = requests.Session()

    try:
        # Login
        login_response = session.post(login_url, json=login_data)
        if login_response.status_code != 200:
            print(f"❌ Login failed: {login_response.status_code}")
            print(login_response.text)
            return

        token_data = login_response.json()
        access_token = token_data.get("access")

        # Set headers with token
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        # Create comprehensive soil management event
        event_data = {
            "event_type": 5,  # Soil Management
            "date": "2025-11-10T15:30:00Z",
            "company": 18,
            "farm": 47,
            "parcel": 106,
            "production": 110,
            # Enhanced immediate display fields
            "type": "ST",  # Soil Testing
            "name": "Enhanced Soil Analysis",
            "area": "3.5",  # Will show as "Area Managed: 3.5 ha"
            "area_unit": "ha",
            "depth": "25",  # Will show as "Working Depth: 25 cm"
            "depth_unit": "cm",
            # Enhanced secondary display fields
            "area_covered": "3.2",  # Will show as "Area Covered: 3.2 hectares"
            "fuel_consumed": "4.8",  # Will show as "Fuel Consumed: 4.8 L"
            "fuel_unit": "L",
            "equipment_hours": "2.5",  # Will show as "Equipment Hours: 2.5 hours"
            "transportation_distance": "12",  # Will show as "Transportation Distance: 12 km"
            "transportation_unit": "km",
            # Soil properties
            "soil_ph": "6.8",
            "organic_matter_percentage": "3.2",
            "soil_texture": "Loamy sand",
            "soil_moisture": "Optimal",
            # Environmental conditions
            "weather_conditions": "Clear, mild temperature",
            "temperature_range": "18-22°C",
            "equipment_used": "Soil auger, pH meter, moisture probe",
            # Description mapped from observation
            "observation": "Enhanced soil management event with comprehensive operational data for testing improved display in Current Production cards",
        }

        # Create the event
        create_url = "http://localhost:8000/api/events/"
        response = session.post(create_url, headers=headers, json=event_data)

        if response.status_code in [200, 201]:
            event = response.json()
            print(f"\n🎉 Successfully created enhanced soil management event!")
            print(f"📋 Event ID: {event.get('id')}")
            print(f"📝 Type: {event_data.get('type')}")
            print(f"📏 Area Managed: {event_data.get('area')} {event_data.get('area_unit')}")
            print(f"🔍 Working Depth: {event_data.get('depth')} {event_data.get('depth_unit')}")
            print(f"⛽ Fuel Consumed: {event_data.get('fuel_consumed')} {event_data.get('fuel_unit')}")
            print(f"🕐 Equipment Hours: {event_data.get('equipment_hours')} hours")
            print(
                f"🚛 Transportation: {event_data.get('transportation_distance')} {event_data.get('transportation_unit')}"
            )
            print(f"🌱 Soil pH: {event_data.get('soil_ph')}")
            print(f"\n✨ This event will now show comprehensive operational data in Current Production cards!")

            return event
        else:
            print(f"❌ Failed to create event: {response.status_code}")
            print(response.text)
            return None

    except Exception as e:
        print(f"❌ Error creating soil management event: {e}")
        return None


if __name__ == "__main__":
    create_enhanced_soil_event()
