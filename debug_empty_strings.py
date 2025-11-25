#!/usr/bin/env python3
"""
Debug the empty string issue in soil management processing.
"""

import os
import django
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import OptimizedEventProcessor, EventCarbonCalculator

def test_empty_string_issue():
    """Test with empty strings like the failing payload"""
    print("🔍 Testing empty string handling...")
    
    # Simulate the problematic payload
    event_data = {
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
        "area_covered": "",  # EMPTY STRING
        "fuel_consumed": "",  # EMPTY STRING
        "fuel_unit": "L",
        "equipment_hours": "",  # EMPTY STRING
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
    
    print(f"📤 Problematic fields:")
    print(f"   fuel_consumed: '{event_data['fuel_consumed']}' (empty string)")
    print(f"   equipment_hours: '{event_data['equipment_hours']}' (empty string)")
    print(f"   area_covered: '{event_data['area_covered']}' (empty string)")
    
    try:
        # Test the processor
        print(f"\n1️⃣ Testing OptimizedEventProcessor...")
        processed_event = OptimizedEventProcessor.process_event_data("soil_management", event_data)
        
        print(f"   ✅ Processor completed")
        print(f"   fuel_consumed result: {processed_event.get('fuel_consumed', 'MISSING')}")
        print(f"   equipment_hours result: {processed_event.get('equipment_hours', 'MISSING')}")
        print(f"   area_covered result: {processed_event.get('area_covered', 'MISSING')}")
        
        # Test the calculator
        print(f"\n2️⃣ Testing calculator...")
        
        class MockEvent:
            def __init__(self, processed_data):
                for key, value in processed_data.items():
                    setattr(self, key, value)
                
                if hasattr(self, 'soil_type'):
                    self.type = self.soil_type
                if hasattr(self, 'area_covered'):
                    self.area = self.area_covered
                elif hasattr(self, 'area'):
                    self.area_covered = self.area
                
                self.parcel_id = event_data.get('parcel_id')
                self.establishment_id = event_data.get('establishment_id')
                self.date = event_data.get('date')
        
        mock_event = MockEvent(processed_event)
        
        # Print the actual values the calculator will see
        print(f"   Calculator will see:")
        print(f"      fuel_consumed: {getattr(mock_event, 'fuel_consumed', 'MISSING')} (type: {type(getattr(mock_event, 'fuel_consumed', None))})")
        print(f"      equipment_hours: {getattr(mock_event, 'equipment_hours', 'MISSING')} (type: {type(getattr(mock_event, 'equipment_hours', None))})")
        print(f"      area: {getattr(mock_event, 'area', 'MISSING')}")
        
        calculator = EventCarbonCalculator()
        result = calculator.calculate_soil_management_event_impact(mock_event)
        
        print(f"\n📈 RESULT:")
        print(f"   CO2e: {result.get('co2e', 'N/A')} kg")
        print(f"   Error: {result.get('error', 'None')}")
        print(f"   Fallback: {result.get('fallback_used', 'None')}")
        
        if result.get('error') or result.get('fallback_used'):
            print(f"\n⚠️  ISSUE FOUND!")
            print(f"   Error: {result.get('error')}")
            return False
        else:
            print(f"\n✅ SUCCESS!")
            return True
            
    except Exception as e:
        print(f"\n💥 EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🔍 EMPTY STRING DEBUG")
    print("=" * 40)
    
    success = test_empty_string_issue()
    
    if not success:
        print(f"\n🔧 FIX NEEDED:")
        print(f"   The _process_soil_management_event method needs to handle empty strings better")
        print(f"   Empty strings should be converted to None or 0, not cause conversion errors")
    
    print(f"\n🏁 Debug complete.")