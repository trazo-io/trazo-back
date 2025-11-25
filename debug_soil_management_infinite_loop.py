#!/usr/bin/env python3
"""
Debug script to investigate soil management infinite loop and 500 error issues.

Issue reported by user:
- Frontend makes API call to calculate-event-carbon with event_type: "soil_management"
- Backend returns: {"error": "Calculation failed", "co2e": 0.0, "efficiency_score": 50.0, "fallback": true}
- Infinite loop in frontend due to repeated API calls
"""

import os
import sys
import django
import json
import time

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.views import calculate_event_carbon_impact_enhanced
from django.test import RequestFactory
from django.http import JsonResponse
from rest_framework.request import Request
from rest_framework.parsers import JSONParser
import io

def test_calculator_directly():
    """Test the calculator directly without the API layer"""
    print("🧪 Testing CarbonFootprintCalculator directly...")
    
    calculator = EventCarbonCalculator()
    
    # Create a mock event object similar to what the API creates
    class MockEvent:
        def __init__(self, event_data):
            # Map the event data like OptimizedEventProcessor does
            self.type = event_data.get("type", "ST")
            self.area = event_data.get("area_worked", "1.0")
            self.area_unit = "hectares"  
            self.depth = event_data.get("depth", "30")
            self.depth_unit = "cm"
            self.method = event_data.get("method", "manual")
            self.equipment_used = event_data.get("equipment_used", "soil_auger")
            self.parcel_id = event_data.get("parcel_id", 1)
            self.establishment_id = event_data.get("establishment_id", 1)
    
    test_event_data = {
        "type": "ST",  # Soil Testing
        "area_worked": "1",
        "depth": "30", 
        "method": "manual",
        "equipment_used": "soil_auger",
        "parcel_id": 1,
        "establishment_id": 1
    }
    
    mock_event = MockEvent(test_event_data)
    
    try:
        result = calculator.calculate_soil_management_event_impact(mock_event)
        print("✅ Calculator direct test successful:")
        print(f"   Result: {json.dumps(result, indent=2)}")
        return True
    except Exception as e:
        print(f"❌ Calculator direct test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_api_layer():
    """Test the API layer with a simulated request"""
    print("\n🌐 Testing API layer (calculate_event_carbon_impact_enhanced)...")
    
    # Create a mock request
    factory = RequestFactory()
    
    test_payload = {
        "event_type": "soil_management",
        "event_data": {
            "type": "ST",
            "area_worked": "1",
            "depth": "30",
            "method": "manual", 
            "equipment_used": "soil_auger",
            "parcel_id": 1,
            "establishment_id": 1,
            "date": "2025-01-21T10:00"
        }
    }
    
    # Create request with JSON data
    request = factory.post(
        '/api/carbon/calculate-event-carbon/',
        data=json.dumps(test_payload),
        content_type='application/json'
    )
    
    # Parse the JSON data to simulate DRF behavior
    stream = io.BytesIO(request.body)
    data = JSONParser().parse(stream)
    request.data = data
    
    try:
        response = calculate_event_carbon_impact_enhanced(request)
        
        if hasattr(response, 'data'):
            result = response.data
        else:
            result = json.loads(response.content.decode())
            
        print(f"✅ API test - Status: {response.status_code}")
        print(f"   Result: {json.dumps(result, indent=2)}")
        
        # Check for fallback indication
        if result.get('fallback'):
            print("⚠️  WARNING: Result is using fallback values!")
            return False
        
        return response.status_code == 200
        
    except Exception as e:
        print(f"❌ API test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_event_processor():
    """Test the OptimizedEventProcessor"""
    print("\n⚡ Testing OptimizedEventProcessor...")
    
    try:
        from carbon.views import OptimizedEventProcessor
        
        test_event_data = {
            "type": "ST",
            "area_worked": "1", 
            "depth": "30",
            "method": "manual",
            "equipment_used": "soil_auger",
            "parcel_id": 1,
            "establishment_id": 1
        }
        
        processed_event = OptimizedEventProcessor.process_event_data("soil_management", test_event_data)
        print("✅ Event processor test successful:")
        print(f"   Processed event type: {type(processed_event)}")
        print(f"   Event attributes: {[attr for attr in dir(processed_event) if not attr.startswith('_')]}")
        return True
        
    except Exception as e:
        print(f"❌ Event processor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def analyze_issue():
    """Analyze the root cause of the issue"""
    print("\n🔍 ISSUE ANALYSIS:")
    print("=" * 50)
    
    # Test each layer
    calculator_ok = test_calculator_directly()
    processor_ok = test_event_processor()
    api_ok = test_api_layer()
    
    print("\n📊 RESULTS SUMMARY:")
    print(f"   Calculator Direct: {'✅ PASS' if calculator_ok else '❌ FAIL'}")
    print(f"   Event Processor:   {'✅ PASS' if processor_ok else '❌ FAIL'}")
    print(f"   API Layer:         {'✅ PASS' if api_ok else '❌ FAIL'}")
    
    print("\n💡 DIAGNOSIS:")
    if not calculator_ok:
        print("   🚨 ISSUE: Calculator implementation for soil_management is broken")
        print("   🔧 FIX: Need to fix calculate_soil_management_event_impact method")
    elif not processor_ok:
        print("   🚨 ISSUE: Event processor cannot handle soil_management data")
        print("   🔧 FIX: Need to fix OptimizedEventProcessor.process_event_data")
    elif not api_ok:
        print("   🚨 ISSUE: API layer has integration problems")
        print("   🔧 FIX: Need to fix calculate_event_carbon_impact_enhanced view")
    else:
        print("   ✅ All layers work individually")
        print("   🤔 Issue might be with authentication, caching, or frontend data format")
    
    print("\n🎯 NEXT STEPS:")
    if not any([calculator_ok, processor_ok, api_ok]):
        print("   1. Fix the calculator implementation first")
        print("   2. Then fix the event processor") 
        print("   3. Finally test the full API integration")
    else:
        print("   1. Check authentication requirements")
        print("   2. Verify frontend is sending correct data format")
        print("   3. Check for caching issues causing infinite loops")

if __name__ == "__main__":
    print("🔍 SOIL MANAGEMENT INFINITE LOOP DEBUG")
    print("=" * 50)
    
    analyze_issue()
    
    print("\n" + "=" * 50)
    print("🏁 Debug complete. Check results above for next steps.")