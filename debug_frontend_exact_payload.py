#!/usr/bin/env python3
"""
Debug the exact payload that the frontend is sending vs what works
"""

import os
import django
import requests
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

def test_frontend_vs_working_payload():
    print("🔍 TESTING FRONTEND PAYLOAD VS WORKING PAYLOAD")
    print("=" * 60)
    
    # The payload from frontend console logs (shortened keys)
    frontend_payload = {
        "date": "2025-11-10T01:48", 
        "event_type": 5, 
        "type": "ST", 
        "area": "2", 
        "area_unit": "ha", 
        "soil_ph": "6.5", 
        "organic_matter_percentage": "3.5",  # truncated in logs as "organic_matter_perce"
        "soil_texture": "loam", 
        "soil_moisture": "moderate", 
        "depth": "30", 
        "depth_unit": "cm", 
        "name": "Spring",
        "area_covered": "2", 
        "fuel_consumed": "15", 
        "fuel_unit": "L", 
        "equipment_hours": "4", 
        "transportation_unit": "km", 
        "equipment_used": "soil auger", 
        "weather_conditions": "dry conditions", 
        "temperature_range": "20-25°C", 
        "parcels": ["106"], 
        "album_images": [],
        # This is the key - check if frontend has this
        "observation": "Testing soil management with good pH levels and organic matter for spring season preparation."
    }
    
    print("📤 Frontend-like payload (with 'observation'):")
    print(json.dumps(frontend_payload, indent=2))
    print()
    
    # Test without description (what frontend might be sending)
    frontend_no_description = frontend_payload.copy()
    if 'description' in frontend_no_description:
        del frontend_no_description['description']
    
    print("📤 Frontend payload without description field:")
    print(json.dumps(frontend_no_description, indent=2))
    print()
    
    # Use direct HTTP request like browser would
    url = "http://localhost:8000/api/companies/18/establishments/47/events/"
    
    # Get CSRF token first
    csrf_response = requests.get("http://localhost:8000/api/csrf-token/")
    csrf_token = csrf_response.json().get('csrfToken')
    
    headers = {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf_token,
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
        'Referer': 'http://app.localhost:3000/admin/dashboard/establishment/47/parcel/106/event/add'
    }
    
    # Login first to get session
    login_data = {
        'email': 'oscar+evento@trazo.io',
        'password': 'om123456'
    }
    
    session = requests.Session()
    
    # Get CSRF for login
    csrf_response = session.get("http://localhost:8000/api/csrf-token/")
    csrf_token = csrf_response.json().get('csrfToken')
    
    headers['X-CSRFToken'] = csrf_token
    
    # Login
    login_response = session.post("http://localhost:8000/api/auth/login/", 
                                json=login_data, 
                                headers=headers)
    
    print(f"🔑 Login Status: {login_response.status_code}")
    
    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.text}")
        return
        
    # Update headers with new CSRF token if needed
    csrf_response = session.get("http://localhost:8000/api/csrf-token/")
    csrf_token = csrf_response.json().get('csrfToken')
    headers['X-CSRFToken'] = csrf_token
    
    # Test the frontend payload
    response = session.post(url, json=frontend_no_description, headers=headers)
    
    print(f"🌐 POST {url}")
    print(f"📊 Response Status: {response.status_code}")
    print(f"📄 Response Text: {response.text}")
    
    if response.status_code == 400:
        try:
            error_data = response.json()
            print("❌ VALIDATION ERRORS:")
            for field, errors in error_data.items():
                if isinstance(errors, list):
                    for error in errors:
                        print(f"  • {field}: {error}")
                else:
                    print(f"  • {field}: {errors}")
        except:
            print(f"❌ Error response (not JSON): {response.text}")

if __name__ == "__main__":
    test_frontend_vs_working_payload()