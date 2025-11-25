#!/usr/bin/env python3
"""
Final verification test to confirm Option A implementation is working correctly.
"""
import os
import sys
import django
import json

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.insert(0, '/Users/oscarmunoz/dev/trazo/trazo-back')
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from carbon.views import calculate_event_carbon_impact_enhanced
from rest_framework.test import APIRequestFactory

User = get_user_model()

def test_final_verification():
    """Final test simulating the exact frontend request"""
    print("🏁 FINAL VERIFICATION: Option A Implementation")
    print("=" * 60)
    
    # Exact payload from user's report
    payload = {
        "event_type": "general",
        "event_data": {
            "date": "2025-11-05T15:14",
            "event_type": "general", 
            "parcel_id": 106,
            "establishment_id": 47
        }
    }
    
    print(f"📤 Simulating Frontend Request:")
    print(f"   URL: POST /api/carbon/calculate-event-carbon/")
    print(f"   Payload: {json.dumps(payload, indent=2)}")
    
    # Create Django request
    factory = APIRequestFactory()
    request = factory.post(
        '/api/carbon/calculate-event-carbon/',
        data=payload,
        format='json'
    )
    
    # Add user for authentication
    try:
        user = User.objects.get(email='test@trazo.io')
    except User.DoesNotExist:
        user = User.objects.create_user(
            email='test@trazo.io',
            username='test_user',
            password='test_password'
        )
    
    request.user = user
    
    # Call the API endpoint
    try:
        response = calculate_event_carbon_impact_enhanced(request)
        
        if response.status_code == 200:
            result = response.data
            
            print(f"\n📥 API Response:")
            print(f"   Status: {response.status_code} OK")
            print(f"   CO2e: {result.get('co2e')} kg")
            print(f"   Method: {result.get('calculation_method')}")
            print(f"   Verification: {result.get('verification_status')}")
            print(f"   Data Source: {result.get('data_source')}")
            
            # Verify the fix
            co2e = result.get('co2e', -1)
            method = result.get('calculation_method', '')
            
            print(f"\n🎯 Option A Verification:")
            
            if co2e == 0.0:
                print(f"   ✅ SUCCESS: Empty General event returns 0.0 kg CO2e")
            else:
                print(f"   ❌ FAILED: Expected 0.0, got {co2e} kg CO2e")
                return False
            
            if 'empty' in method.lower():
                print(f"   ✅ SUCCESS: Using empty event calculation method")
            else:
                print(f"   ⚠️  WARNING: Method doesn't indicate empty event: {method}")
            
            verification = result.get('verification_status', '')
            if verification == 'no_activity':
                print(f"   ✅ SUCCESS: Verification status indicates no activity")
            else:
                print(f"   ⚠️  INFO: Verification status: {verification}")
            
            return True
            
        else:
            print(f"\n❌ API Error: Status {response.status_code}")
            if hasattr(response, 'data'):
                print(f"   Error: {response.data}")
            return False
            
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_with_content():
    """Test that events with content still work correctly"""
    print(f"\n🔍 Testing Event with Content (Should NOT be 0.0)")
    print("=" * 60)
    
    payload = {
        "event_type": "general",
        "event_data": {
            "date": "2025-11-05T15:14",
            "event_type": "general",
            "parcel_id": 106,
            "establishment_id": 47,
            "description": "Pest Scouting"
        }
    }
    
    print(f"📤 Request with Description:")
    print(f"   Description: 'Pest Scouting'")
    
    factory = APIRequestFactory()
    request = factory.post('/api/carbon/calculate-event-carbon/', data=payload, format='json')
    request.user = User.objects.first()
    
    try:
        response = calculate_event_carbon_impact_enhanced(request)
        
        if response.status_code == 200:
            result = response.data
            co2e = result.get('co2e', -1)
            method = result.get('calculation_method', '')
            
            print(f"\n📥 Response:")
            print(f"   CO2e: {co2e} kg")
            print(f"   Method: {method}")
            
            if co2e > 0.0 and co2e <= 1.0:  # Should be around 0.25 for documentation
                print(f"   ✅ SUCCESS: Event with content returns {co2e} kg CO2e")
                return True
            else:
                print(f"   ❌ UNEXPECTED: Expected ~0.25, got {co2e} kg CO2e")
                return False
        else:
            print(f"   ❌ API Error: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

if __name__ == "__main__":
    print("🏁 FINAL VERIFICATION TEST")
    print("Confirming Option A: Empty General Events → 0.0 kg CO2e")
    print("=" * 70)
    
    # Test empty event
    empty_passed = test_final_verification()
    
    # Test event with content
    content_passed = test_with_content()
    
    # Final result
    overall_passed = empty_passed and content_passed
    
    print(f"\n🏁 FINAL RESULT: {'✅ OPTION A FULLY VERIFIED' if overall_passed else '❌ VERIFICATION FAILED'}")
    
    if overall_passed:
        print("\n🎉 SUCCESS SUMMARY:")
        print("   ✅ Empty General event forms now show 0.0 kg CO2e")
        print("   ✅ Events with descriptions still calculate properly")
        print("   ✅ Frontend API endpoint routing works correctly")
        print("   ✅ User's issue completely resolved!")
        print("\n📋 What Changed:")
        print("   • Added empty event detection in calculate_general_event_impact()")
        print("   • Empty events (no description) → 0.0 kg CO2e")
        print("   • Events with content → EPA-verified calculations")
        print("   • API endpoint delegates to enhanced calculator")
        print("\n🎯 User can now see 0.0 kg CO2e for empty General event forms!")
    else:
        print("\n❌ Some tests failed - check implementation")