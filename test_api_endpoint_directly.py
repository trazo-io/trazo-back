#!/usr/bin/env python3
"""
Test the API endpoint directly by simulating the Django request processing.
"""

import os
import django
import json
import io

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import calculate_event_carbon_impact_enhanced
from django.test import RequestFactory
from rest_framework.parsers import JSONParser
from django.contrib.auth.models import User
from rest_framework.request import Request

def test_api_endpoint_directly():
    """Test the API endpoint directly without network calls"""
    print("🔍 Testing API endpoint directly...")
    
    # EXACT payload from user's failing request
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
            "establishment_id": 44
        }
    }
    
    try:
        # Create a mock request like Django would
        factory = RequestFactory()
        request = factory.post(
            '/api/carbon/calculate-event-carbon/',
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        # Parse the JSON data like DRF would
        stream = io.BytesIO(request.body)
        data = JSONParser().parse(stream)
        request.data = data
        
        # Create a mock user for authentication (user_id: 56 from the JWT)
        try:
            user = User.objects.get(id=56)
            print(f"   Found user: {user.username} (id: {user.id})")
        except User.DoesNotExist:
            # Create a mock user if doesn't exist
            user = User.objects.create_user(username='testuser', password='testpass')
            user.id = 56
            user.save()
            print(f"   Created mock user: {user.username} (id: {user.id})")
        
        request.user = user
        
        print(f"📤 Calling calculate_event_carbon_impact_enhanced...")
        print(f"   Payload: soil_management with area=2, empty fuel_consumed")
        
        # Call the actual API function
        response = calculate_event_carbon_impact_enhanced(request)
        
        print(f"\n📨 API Response:")
        print(f"   Status Code: {response.status_code}")
        
        # Extract response data
        if hasattr(response, 'data'):
            result = response.data
        else:
            result = json.loads(response.content.decode())
        
        print(f"   Response: {json.dumps(result, indent=2)}")
        
        if response.status_code == 200:
            print(f"\n✅ SUCCESS!")
            print(f"   CO2e: {result.get('co2e', 'N/A')} kg")
            return True
        else:
            print(f"\n❌ FAILED!")
            
            # Check for specific error patterns
            if result.get('fallback'):
                print(f"   🚨 API is using fallback values - there's an internal error")
            
            if 'error' in result:
                print(f"   🚨 Error message: {result['error']}")
            
            return False
            
    except Exception as e:
        print(f"\n💥 EXCEPTION in API call: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_view_components_separately():
    """Test different parts of the view function separately to isolate the issue"""
    print(f"\n🔧 Testing view components separately...")
    
    from carbon.views import OptimizedEventProcessor
    from carbon.services.event_carbon_calculator import EventCarbonCalculator
    
    event_type = "soil_management"
    event_data = {
        "date": "2025-10-12T20:35",
        "event_type": "soil_management",
        "type": "ST",
        "area": "2",
        "area_unit": "hectares",
        "fuel_consumed": "",  # Empty string - this is the problem
        "equipment_hours": "",
        "parcel_id": 105,
        "establishment_id": 44
    }
    
    try:
        # Test 1: Event processor
        print(f"   1️⃣ Testing OptimizedEventProcessor...")
        processed_event = OptimizedEventProcessor.process_event_data(event_type, event_data)
        print(f"      ✅ Processor OK")
        
        # Test 2: Calculator instance creation
        print(f"   2️⃣ Testing calculator instance...")
        from carbon.views import calculator_instance
        print(f"      ✅ Calculator instance OK")
        
        # Test 3: Calculator method call (this might be where it fails)
        print(f"   3️⃣ Testing calculator method call...")
        result = calculator_instance.calculate_soil_management_event_impact(processed_event)
        print(f"      ✅ Calculator method OK")
        print(f"      Result: {result.get('co2e', 'N/A')} kg CO2e")
        
        return True
        
    except Exception as e:
        print(f"      💥 ERROR in component: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔍 API ENDPOINT DIRECT TEST")
    print("=" * 50)
    
    # Test the API endpoint directly
    api_success = test_api_endpoint_directly()
    
    if not api_success:
        # Test components separately to find the issue
        component_success = test_view_components_separately()
    
    print(f"\n🏁 Test complete.")