#!/usr/bin/env python3
"""
Test the actual API call with real authentication token to debug the 500 error.
"""

import requests
import json

def test_real_api_call():
    """Test the real API call with authentication"""
    print("🌐 Testing REAL API call with authentication...")
    
    url = "http://localhost:8000/api/carbon/calculate-event-carbon/"
    
    # User's minimal payload that's failing
    payload = {
        "event_type": "soil_management",
        "event_data": {
            "date": "2025-10-12T20:21",
            "event_type": "soil_management",
            "parcel_id": 105,
            "establishment_id": 44
        }
    }
    
    # User's authentication token
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzYwMzAwNzg2LCJpYXQiOjE3NjAyOTg5ODYsImp0aSI6IjI3OTQ2ZTc2ZDJlNTQwM2Y4NmNlYzk1MWRlMDI4NGE0IiwidXNlcl9pZCI6NTZ9.COsybihizpkAwSR9TsPGe5FjuSb_bc8yvNtHbNO4TE0",
        "Content-Type": "application/json"
    }
    
    print(f"📤 Payload: {json.dumps(payload, indent=2)}")
    print(f"🔑 Using provided auth token")
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        print(f"\n📨 Response:")
        print(f"   Status Code: {response.status_code}")
        print(f"   Headers: {dict(response.headers)}")
        
        try:
            result = response.json()
            print(f"   Body: {json.dumps(result, indent=2)}")
        except:
            print(f"   Body (raw): {response.text}")
        
        if response.status_code == 500:
            print(f"\n💥 500 ERROR CONFIRMED!")
            print(f"   This means there's a server-side error in the API")
            print(f"   The issue is not with authentication or payload format")
            return False
        elif response.status_code == 200:
            print(f"\n✅ SUCCESS!")
            print(f"   API call worked correctly")
            return True
        else:
            print(f"\n⚠️  UNEXPECTED STATUS: {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"\n🔌 CONNECTION ERROR: Django server not running on localhost:8000")
        print(f"   Need to start the development server first")
        return False
    except Exception as e:
        print(f"\n💥 REQUEST ERROR: {e}")
        return False

def test_with_complete_payload():
    """Test with a complete payload to see if that works"""
    print(f"\n🧪 Testing with COMPLETE payload...")
    
    url = "http://localhost:8000/api/carbon/calculate-event-carbon/"
    
    # Complete payload with all required fields
    complete_payload = {
        "event_type": "soil_management",
        "event_data": {
            "date": "2025-10-12T20:21",
            "event_type": "soil_management",
            "type": "ST",
            "area": "1.0",
            "area_unit": "hectares",
            "depth": "30",
            "depth_unit": "cm",
            "equipment_used": "soil auger",
            "method": "manual",
            "parcel_id": 105,
            "establishment_id": 44
        }
    }
    
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzYwMzAwNzg2LCJpYXQiOjE3NjAyOTg5ODYsImp0aSI6IjI3OTQ2ZTc2ZDJlNTQwM2Y4NmNlYzk1MWRlMDI4NGE0IiwidXNlcl9pZCI6NTZ9.COsybihizpkAwSR9TsPGe5FjuSb_bc8yvNtHbNO4TE0",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=complete_payload, headers=headers, timeout=10)
        
        print(f"   Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ SUCCESS: {result.get('co2e', 'N/A')} kg CO2e")
            return True
        else:
            try:
                result = response.json()
                print(f"   ❌ ERROR: {result}")
            except:
                print(f"   ❌ ERROR: {response.text}")
            return False
            
    except Exception as e:
        print(f"   💥 ERROR: {e}")
        return False

if __name__ == "__main__":
    print("🔍 REAL API CALL TEST WITH AUTHENTICATION")
    print("=" * 60)
    
    # Test the failing minimal payload
    minimal_success = test_real_api_call()
    
    # Test complete payload for comparison
    complete_success = test_with_complete_payload()
    
    print(f"\n" + "=" * 60)
    print(f"📊 RESULTS:")
    print(f"   Minimal payload:  {'✅ SUCCESS' if minimal_success else '❌ FAILED'}")
    print(f"   Complete payload: {'✅ SUCCESS' if complete_success else '❌ FAILED'}")
    
    print(f"\n💡 CONCLUSION:")
    if not minimal_success and complete_success:
        print(f"   Frontend should validate and include required soil management fields")
        print(f"   Don't send API calls with empty/missing soil management data")
    elif not minimal_success and not complete_success:
        print(f"   There's a server-side issue that needs fixing")
    elif minimal_success:
        print(f"   API works fine - issue might be elsewhere")
    
    print(f"\n🏁 Test complete.")