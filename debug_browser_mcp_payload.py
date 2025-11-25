#!/usr/bin/env python3
"""
Debug the exact payload that browser MCP is sending to find validation issue
"""

import os
import django
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from datetime import datetime, timezone

def debug_mcp_browser_payload():
    print("🔍 DEBUGGING MCP BROWSER PAYLOAD")
    print("=" * 60)
    
    # The payload that browser MCP would be sending based on the form fields
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    
    mcp_payload = {
        "date": current_time,
        "event_type": 5,  # Soil Management
        "type": "ST",     # Soil Testing
        "area": "3",
        "area_unit": "ha", # ✅ Fix #1 working
        "soil_ph": "7.2",
        "organic_matter_percentage": "4.1", 
        "soil_texture": "clay_loam",
        "soil_moisture": "optimal",
        "depth": "25",
        "depth_unit": "cm",
        "name": "MCP Browser Test - Soil Analysis",
        "area_covered": "3",
        "fuel_consumed": "12",
        "fuel_unit": "L", 
        "equipment_hours": "2.5",
        "transportation_distance": "5",
        "transportation_unit": "km",
        "equipment_used": "soil probe",
        "weather_conditions": "clear and dry",
        "temperature_range": "18-22°C",
        "parcels": ["106"],
        "album_images": [],
        # ✅ Fix #2 working - description field mapping
        "description": "MCP Browser automation test for creating Soil Management event. Testing pH levels, organic matter content, and soil texture analysis for spring season preparation."
    }
    
    print("📤 MCP Browser payload:")
    print(json.dumps(mcp_payload, indent=2))
    print()
    
    # Get the user 
    User = get_user_model()
    user = User.objects.filter(email='oscar+evento@trazo.io').first()
    
    if not user:
        print("❌ User oscar+evento@trazo.io not found")
        return
    
    print(f"👤 Found user: {user.email}")
    
    # Create authenticated client
    client = APIClient()
    client.force_authenticate(user=user)
    
    # Make the request
    url = "/api/companies/18/establishments/47/events/"
    response = client.post(url, mcp_payload, format='json')
    
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
        event_id = response.data.get('id')
        print(f"📝 Created event ID: {event_id}")
        print("=" * 60)
        print(f"🎯 FINAL RESULT: MCP Browser Test Event ID = {event_id}")
        print("=" * 60)
        return event_id
    else:
        print(f"🤷 Unexpected response: {response.status_code}")
        print(f"Response: {response.data}")
        return None

if __name__ == "__main__":
    debug_mcp_browser_payload()