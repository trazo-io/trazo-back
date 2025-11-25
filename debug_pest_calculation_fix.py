#!/usr/bin/env python3
"""
Debug Pest Management Carbon Calculation Fix

Test the data structure mismatch and fix the calculation logic.
"""

import os
import sys
import django

# Add trazo-back to path and configure Django
sys.path.insert(0, '/Users/oscarmunoz/dev/trazo/trazo-back')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor

def test_pest_calculation_debug():
    """Debug the pest management calculation issue"""
    
    print("🐛 DEBUGGING PEST MANAGEMENT CARBON CALCULATION")
    print("=" * 60)
    
    # Realistic test data from frontend
    test_event_data = {
        "type": "SC",  # Scouting
        "name": "Morning Aphid Check",
        "pest_species": "aphids",
        "pest_pressure_level": "medium",
        "field_area_hectares": "2.5",
        "travel_distance_km": "5.0", 
        "time_spent_hours": "2.0",
        "crop_growth_stage": "flowering",
        "weather_conditions": "dry",
        "economic_threshold_met": False,
        "parcel_id": 1,
        "establishment_id": 1,
        "date": "2025-01-21T10:00"
    }
    
    print("📤 Frontend Event Data:")
    for key, value in test_event_data.items():
        print(f"   {key}: {value}")
    
    # Step 1: Process event data (what OptimizedEventProcessor does)
    print(f"\n📥 Processing Event Data...")
    processed_event = OptimizedEventProcessor.process_event_data("pest_management", test_event_data)
    
    print(f"📊 Processed Event Data:")
    for key, value in processed_event.items():
        print(f"   {key}: {value}")
    
    # Step 2: Calculate carbon impact (what OptimizedCarbonCalculator does)
    print(f"\n🧮 Calculating Carbon Impact...")
    calculator = OptimizedCarbonCalculator()
    
    try:
        result = calculator.calculate_pest_management_event_impact(processed_event)
        
        print(f"✅ Calculation Result:")
        print(f"   CO2e: {result.get('co2e', 'N/A')} kg")
        print(f"   Method: {result.get('calculation_method', 'N/A')}")
        print(f"   Efficiency: {result.get('efficiency_score', 'N/A')}")
        print(f"   Status: {result.get('verification_status', 'N/A')}")
        
        if 'error' in result:
            print(f"   ❌ Error: {result['error']}")
            
        if 'breakdown' in result:
            print(f"   📊 Breakdown:")
            for key, value in result['breakdown'].items():
                print(f"      {key}: {value}")
                
    except Exception as e:
        print(f"❌ CALCULATION ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 3: Show the data structure mismatch
    print(f"\n🔍 DATA STRUCTURE ANALYSIS")
    print("-" * 40)
    print(f"EventCarbonCalculator expects: event.type")
    print(f"But processed_event contains: {list(processed_event.keys())}")
    print(f"Original 'type' becomes: 'pest_type' = {processed_event.get('pest_type', 'NOT_FOUND')}")
    
    # Step 4: Test the fix
    print(f"\n🔧 TESTING POTENTIAL FIX")
    print("-" * 40)
    
    # Create a mock event object with .type attribute
    class MockEvent:
        def __init__(self, event_data):
            self.type = event_data.get('pest_type', 'SC')
            self.pest_species = event_data.get('pest_species', '')
            self.pest_pressure_level = event_data.get('pest_pressure_level', '')
            # Add other attributes as needed
    
    mock_event = MockEvent(processed_event)
    print(f"Mock event.type: {mock_event.type}")
    
    # Direct test of EventCarbonCalculator
    from carbon.services.event_carbon_calculator import EventCarbonCalculator
    direct_calculator = EventCarbonCalculator()
    
    try:
        direct_result = direct_calculator.calculate_pest_management_event_impact(mock_event)
        print(f"✅ Direct calculation with mock object:")
        print(f"   CO2e: {direct_result.get('co2e', 'N/A')} kg")
        print(f"   Expected for SC (Scouting): 0.2 kg CO2e")
        
        if direct_result.get('co2e', 0) > 0:
            print(f"   🎯 SUCCESS: Non-zero result achieved!")
        else:
            print(f"   ⚠️  Still returning zero - check for other issues")
            
    except Exception as e:
        print(f"❌ Direct calculation error: {e}")

if __name__ == "__main__":
    test_pest_calculation_debug()