#!/usr/bin/env python3
"""
Debug the minimal payload that's causing 500 error.
This payload has no soil management data, just basic required fields.
"""

import os
import sys
import django
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import OptimizedEventProcessor, EventCarbonCalculator

def test_minimal_payload():
    """Test with the minimal payload that's failing"""
    print("🔍 Testing MINIMAL payload causing 500 error...")
    
    # EXACT minimal payload from user's latest error
    minimal_payload = {
        "event_type": "soil_management",
        "event_data": {
            "date": "2025-10-12T20:21",
            "event_type": "soil_management", 
            "parcel_id": 105,
            "establishment_id": 44
        }
    }
    
    event_type = minimal_payload["event_type"]
    event_data = minimal_payload["event_data"]
    
    print(f"📤 Testing minimal payload:")
    print(f"   event_type: {event_type}")
    print(f"   event_data keys: {list(event_data.keys())}")
    print(f"   Missing: type, area, fuel_consumed, etc.")
    
    try:
        # Step 1: Test OptimizedEventProcessor
        print(f"\n1️⃣ Processing with OptimizedEventProcessor...")
        processed_event = OptimizedEventProcessor.process_event_data(event_type, event_data)
        print(f"   ✅ Event processor completed")
        
        # Check what defaults were applied
        print(f"\n   🔍 Default values applied:")
        print(f"      soil_type: {processed_event.get('soil_type', 'MISSING')}")
        print(f"      area: {processed_event.get('area', 'MISSING')}")
        print(f"      area_covered: {processed_event.get('area_covered', 'MISSING')}")
        print(f"      fuel_consumed: {processed_event.get('fuel_consumed', 'MISSING')}")
        print(f"      equipment_hours: {processed_event.get('equipment_hours', 'MISSING')}")
        
        # Step 2: Test calculator
        print(f"\n2️⃣ Testing calculator with minimal data...")
        
        class MockEvent:
            def __init__(self, processed_data):
                for key, value in processed_data.items():
                    setattr(self, key, value)
                
                # Ensure basic mappings
                if hasattr(self, 'soil_type'):
                    self.type = self.soil_type
                if hasattr(self, 'area_covered'):
                    self.area = self.area_covered
                elif hasattr(self, 'area'):
                    self.area_covered = self.area
                
                # Add IDs from event_data
                self.parcel_id = event_data.get('parcel_id')
                self.establishment_id = event_data.get('establishment_id')
                self.date = event_data.get('date')
        
        mock_event = MockEvent(processed_event)
        
        print(f"   📦 Mock event created with attributes:")
        attrs = [attr for attr in dir(mock_event) if not attr.startswith('_') and not callable(getattr(mock_event, attr))]
        for attr in sorted(attrs):
            value = getattr(mock_event, attr)
            print(f"      {attr}: {value}")
        
        # Step 3: Run calculation
        print(f"\n3️⃣ Running carbon calculation...")
        calculator = EventCarbonCalculator()
        result = calculator.calculate_soil_management_event_impact(mock_event)
        
        print(f"   📈 RESULT:")
        print(f"      CO2e: {result.get('co2e', 'N/A')} kg")
        print(f"      Efficiency: {result.get('efficiency_score', 'N/A')}")
        print(f"      Method: {result.get('calculation_method', 'N/A')}")
        print(f"      Error: {result.get('error', 'None')}")
        print(f"      Fallback: {result.get('fallback_used', 'None')}")
        
        if result.get('error') or result.get('fallback_used'):
            print(f"\n⚠️  ISSUE FOUND: Minimal data causes fallback!")
            print(f"   Need to provide better defaults for missing soil management data")
            return False
        else:
            print(f"\n✅ SUCCESS: Minimal payload works!")
            return True
            
    except Exception as e:
        print(f"\n💥 EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_with_better_defaults():
    """Test what happens if we provide better defaults for missing data"""
    print(f"\n🔧 Testing with improved defaults for minimal payload...")
    
    # Simulate what happens if we improve the _process_soil_management_event method
    minimal_event_data = {
        "date": "2025-10-12T20:21",
        "event_type": "soil_management",
        "parcel_id": 105,
        "establishment_id": 44
    }
    
    # Manually add better defaults (simulating improved processor)
    improved_processed = {
        "event_type": "soil_management",
        "description": "",
        "observation": "",
        "duration_hours": 2.0,
        "amount_kg": 1.0,
        "soil_type": "ST",  # Default to Soil Testing
        "area": "1.0",      # Default area
        "area_covered": "1.0",
        "area_unit": "hectares",
        "soil_ph": None,
        "organic_matter_percentage": None,
        "soil_texture": None,
        "soil_moisture": None,
        "depth": "30",      # Default depth
        "depth_unit": "cm",
        "equipment_used": "",
        "method": "",
        "fuel_consumed": 0.0,  # Default no fuel
        "fuel_unit": "L",
        "equipment_hours": 0.0,  # Default no equipment hours
        "tillage_type": "",
        "tillage_intensity": "",
        "tillage_direction": "",
        "residue_management": "",
        "weather_conditions": "",
        "temperature_range": "",
    }
    
    try:
        class MockEvent:
            def __init__(self, processed_data):
                for key, value in processed_data.items():
                    setattr(self, key, value)
                
                if hasattr(self, 'soil_type'):
                    self.type = self.soil_type
                if hasattr(self, 'area_covered'):
                    self.area = self.area_covered
                
                # Add IDs
                self.parcel_id = minimal_event_data.get('parcel_id')
                self.establishment_id = minimal_event_data.get('establishment_id')
                self.date = minimal_event_data.get('date')
        
        mock_event = MockEvent(improved_processed)
        
        calculator = EventCarbonCalculator()
        result = calculator.calculate_soil_management_event_impact(mock_event)
        
        print(f"   📈 IMPROVED RESULT:")
        print(f"      CO2e: {result.get('co2e', 'N/A')} kg")
        print(f"      Efficiency: {result.get('efficiency_score', 'N/A')}")
        print(f"      Error: {result.get('error', 'None')}")
        print(f"      Fallback: {result.get('fallback_used', 'None')}")
        
        if not result.get('error') and not result.get('fallback_used'):
            print(f"   ✅ SUCCESS: Better defaults work!")
            return True
        else:
            print(f"   ❌ STILL FAILING: Even with defaults")
            return False
            
    except Exception as e:
        print(f"   💥 EXCEPTION: {e}")
        return False

if __name__ == "__main__":
    print("🔍 MINIMAL SOIL MANAGEMENT PAYLOAD DEBUG")
    print("=" * 60)
    
    # Test the failing minimal payload
    success = test_minimal_payload()
    
    if not success:
        # Try with better defaults
        test_with_better_defaults()
    
    print(f"\n" + "=" * 60)
    print(f"💡 RECOMMENDATION:")
    if not success:
        print(f"   The _process_soil_management_event method needs better defaults")
        print(f"   for minimal payloads that have no soil management specific data")
    else:
        print(f"   The processor should handle minimal payloads correctly")
    
    print(f"\n🏁 Debug complete.")