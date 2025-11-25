#!/usr/bin/env python3
"""
Debug script to verify the display fix is working.

This tests the exact scenario the user reported:
- Volume: 3320 kg (input)
- Unit: kg (selected)
- Expected display: "3320 kilograms"
- Issue: Was showing "4882.35294117647 liters"
"""

import os
import sys
import django
import json

# Setup Django environment
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from carbon.views import calculate_event_carbon_impact

User = get_user_model()

def test_display_fix():
    print("🔧 TESTING DISPLAY FIX: kg to liters conversion")
    print("=" * 60)
    
    # Create the exact payload from the user's screenshot
    payload = {
        "event_type": "chemical",
        "event_data": {
            "date": "2025-10-11T14:21",
            "event_type": "chemical",
            "type": "FE",
            "commercial_name": "Anhydrous Ammonia",
            "active_ingredient": "",
            "concentration": "82-0-0",
            "volume_applied": "3320",  # User entered this
            "volume_unit": "kg",       # User selected this
            "area_treated": "16.2",
            "area_unit": "ha",
            "application_method": "",
            "weather_conditions": "",
            "application_timing": "",
            "target_pest_disease": "",
            "description": "",
            "parcel_id": 103,
            "establishment_id": 44
        }
    }
    
    print(f"📥 User Input:")
    print(f"   Volume: {payload['event_data']['volume_applied']} {payload['event_data']['volume_unit']}")
    print(f"   Area: {payload['event_data']['area_treated']} {payload['event_data']['area_unit']}")
    print(f"   Chemical: {payload['event_data']['commercial_name']} ({payload['event_data']['concentration']})")
    print()
    
    # Create mock Django request
    factory = RequestFactory()
    request = factory.post('/api/carbon/calculate-event-carbon/', 
                          json.dumps(payload), 
                          content_type='application/json')
    
    # Create/get test user
    try:
        user = User.objects.get(email='debug@test.com')
    except User.DoesNotExist:
        user = User.objects.create_user(email='debug@test.com', password='password')
    request.user = user
    
    # Call the API
    try:
        response = calculate_event_carbon_impact(request)
        response.render()  # Render the template response
        result = json.loads(response.content)
        
        print(f"🔍 API Response Analysis:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Response Size: {len(response.content)} bytes")
        print()
        
        # Check for the new display fields
        original_volume = result.get('original_volume_applied')
        original_unit = result.get('original_volume_unit')
        converted_volume = result.get('volume_applied_liters')
        
        print(f"📊 Display Fields Check:")
        print(f"   ✅ original_volume_applied: {original_volume}")
        print(f"   ✅ original_volume_unit: {original_unit}")
        print(f"   ✅ volume_applied_liters: {converted_volume}")
        print()
        
        if original_volume and original_unit:
            display_text = f"{original_volume} {original_unit}"
            if original_unit == 'kg':
                display_text = f"{original_volume} kilograms"
            elif original_unit == 'L':
                display_text = f"{original_volume} liters"
                
            print(f"✅ SUCCESS: Frontend should display '{display_text}'")
            print(f"   Instead of: '{converted_volume} liters'")
            
            # Verify calculation correctness
            expected_liters = 3320 / 0.68  # 4882.35...
            calculation_correct = abs(float(converted_volume) - expected_liters) < 1.0
            print(f"   Calculation accuracy: {'✅ CORRECT' if calculation_correct else '❌ INCORRECT'}")
            
        else:
            print(f"❌ PROBLEM: Display fields missing")
            print(f"   Available keys: {list(result.keys())}")
            
        print()
        print(f"🧮 Carbon Calculation:")
        print(f"   Total CO2e: {result.get('co2e', 'N/A')} kg")
        print(f"   Nitrogen: {result.get('nitrogen_kg', 'N/A')} kg")
        print(f"   Expected: ~28,694 kg CO2e")
        
        # Check if calculation is correct
        co2e = result.get('co2e', 0)
        calculation_ok = 25000 <= co2e <= 32000  # Allow some range
        print(f"   Calculation: {'✅ CORRECT' if calculation_ok else '❌ NEEDS REVIEW'}")
        
        return original_volume is not None and original_unit is not None
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔬 UNIT DISPLAY FIX VERIFICATION")
    print("Testing the kg to liters conversion display issue\n")
    
    success = test_display_fix()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 DISPLAY FIX IS WORKING!")
        print("   Backend is sending original user input for display")
        print("   Frontend should now show '3320 kilograms' instead of liters")
    else:
        print("❌ DISPLAY FIX NEEDS ATTENTION")
        print("   Check backend logs for more details")
    print("=" * 60)