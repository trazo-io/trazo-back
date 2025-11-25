#!/usr/bin/env python3
"""
Simple test to verify the _process_chemical_event method is returning original values
"""

import os
import sys
import django

# Setup Django environment
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import OptimizedEventProcessor

def test_original_values():
    print("🧪 Testing _process_chemical_event method directly")
    print("=" * 55)
    
    # Test the exact event data that the frontend sends
    event_data = {
        "type": "FE",
        "concentration": "82-0-0",
        "volume_applied": "3320",  # User entered this
        "volume_unit": "kg",       # User selected this
        "area_treated": "16.2",
        "area_unit": "ha",
        "application_method": "injection"
    }
    
    print(f"📥 Input event data:")
    for key, value in event_data.items():
        print(f"   {key}: {value}")
    print()
    
    # Process the event data
    processed_data = OptimizedEventProcessor._process_chemical_event(event_data)
    
    print(f"🔧 Processed data:")
    for key, value in processed_data.items():
        print(f"   {key}: {value}")
    print()
    
    # Check for original values
    original_volume = processed_data.get('original_volume')
    original_volume_unit = processed_data.get('original_volume_unit')
    converted_volume = processed_data.get('volume')
    
    print(f"🎯 Key fields check:")
    print(f"   original_volume: {original_volume}")
    print(f"   original_volume_unit: {original_volume_unit}")
    print(f"   converted volume: {converted_volume}")
    print()
    
    if original_volume and original_volume_unit:
        print(f"✅ SUCCESS: Original values are preserved")
        print(f"   Display should show: {original_volume} {original_volume_unit}")
        print(f"   Calculations use: {converted_volume} L")
        return True
    else:
        print(f"❌ PROBLEM: Original values are missing")
        return False

if __name__ == "__main__":
    success = test_original_values()
    print("\n" + "=" * 55)
    if success:
        print("🎉 BACKEND METHOD IS WORKING!")
    else:
        print("❌ BACKEND METHOD NEEDS FIXING")
    print("=" * 55)