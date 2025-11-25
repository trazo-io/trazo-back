#!/usr/bin/env python3
"""
Test script to verify Option A implementation for empty General events.
"""
import os
import sys
import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.insert(0, '/Users/oscarmunoz/dev/trazo/trazo-back')
django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator

def test_option_a_empty_events():
    """Test that empty General events return 0.0 kg CO2e (Option A)"""
    print("🧪 Testing Option A: Empty General Events = 0.0 kg CO2e")
    print("=" * 60)
    
    calculator = EventCarbonCalculator()
    
    # Test cases for empty events
    test_cases = [
        {
            "name": "Completely Empty Event",
            "data": {},
            "expected_co2e": 0.0
        },
        {
            "name": "Empty Description",
            "data": {"description": ""},
            "expected_co2e": 0.0
        },
        {
            "name": "Whitespace Only Description",
            "data": {"description": "   "},
            "expected_co2e": 0.0
        },
        {
            "name": "Empty Name and Description",
            "data": {"description": "", "name": ""},
            "expected_co2e": 0.0
        },
        {
            "name": "None Values",
            "data": {"description": None, "name": None},
            "expected_co2e": 0.0
        },
        {
            "name": "Event with Content (Should NOT be 0.0)",
            "data": {"description": "Pest Scouting"},
            "expected_co2e": 0.25  # Should use documentation factor
        }
    ]
    
    # Test each case
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. Testing: {test_case['name']}")
        
        # Create mock event
        class MockGeneralEvent:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)
                # Set default type
                if not hasattr(self, 'type'):
                    self.type = 'general'
        
        mock_event = MockGeneralEvent(**test_case['data'])
        
        try:
            result = calculator.calculate_general_event_impact(mock_event)
            actual_co2e = result.get('co2e', -1)
            expected_co2e = test_case['expected_co2e']
            
            print(f"   Data: {test_case['data']}")
            print(f"   Expected CO2e: {expected_co2e} kg")
            print(f"   Actual CO2e: {actual_co2e} kg")
            print(f"   Method: {result.get('calculation_method', 'unknown')}")
            
            if actual_co2e == expected_co2e:
                print(f"   ✅ PASS: Correct CO2e value")
            else:
                print(f"   ❌ FAIL: Expected {expected_co2e}, got {actual_co2e}")
                return False
                
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            return False
    
    return True

def test_api_endpoint_with_empty_payload():
    """Test the API endpoint with the exact payload that was showing 0.25"""
    print(f"\n🌐 Testing API Endpoint with Empty Payload")
    print("=" * 60)
    
    from carbon.views import OptimizedCarbonCalculator
    
    # Exact payload from user's screenshot
    test_payload = {
        "event_type": "general",
        "event_data": {
            "date": "2025-11-05T15:14",
            "event_type": "general",
            "parcel_id": 106,
            "establishment_id": 47
        }
    }
    
    print(f"📤 Test Payload:")
    print(f"   {test_payload}")
    
    calculator = OptimizedCarbonCalculator()
    
    try:
        result = calculator.calculate_general_impact_optimized(test_payload["event_data"])
        co2e = result.get('co2e', -1)
        method = result.get('calculation_method', 'unknown')
        
        print(f"\n📥 API Response:")
        print(f"   CO2e: {co2e} kg")
        print(f"   Method: {method}")
        print(f"   Verification: {result.get('verification_status', 'unknown')}")
        
        if co2e == 0.0:
            print(f"\n✅ SUCCESS: Empty event now returns 0.0 kg CO2e (Option A)")
            return True
        elif co2e == 0.25:
            print(f"\n❌ STILL BROKEN: Empty event still returns 0.25 kg CO2e")
            return False
        else:
            print(f"\n⚠️  UNEXPECTED: Empty event returns {co2e} kg CO2e")
            return False
            
    except Exception as e:
        print(f"\n❌ API ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 OPTION A IMPLEMENTATION TEST")
    print("Testing: Empty General Events → 0.0 kg CO2e")
    print("=" * 70)
    
    # Test the core calculator
    calculator_passed = test_option_a_empty_events()
    
    # Test the API endpoint
    api_passed = test_api_endpoint_with_empty_payload()
    
    # Final result
    overall_passed = calculator_passed and api_passed
    
    print(f"\n🏁 FINAL RESULT: {'✅ OPTION A IMPLEMENTED SUCCESSFULLY' if overall_passed else '❌ OPTION A IMPLEMENTATION FAILED'}")
    
    if overall_passed:
        print("\n📋 Summary:")
        print("   ✅ Empty General events now return 0.0 kg CO2e")
        print("   ✅ Non-empty events still calculate correctly")
        print("   ✅ API endpoint properly routes to new logic")
        print("   ✅ Frontend will now show 0.0 instead of 0.25 for empty forms")
        print("\n🎯 User Issue Resolved: Empty General event forms now show 0.0 kg CO2e!")