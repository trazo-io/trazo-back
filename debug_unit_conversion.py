#!/usr/bin/env python3
"""
DEBUG UNIT CONVERSION ISSUES
Quick test to debug why unit conversions are failing
"""

import sys
import os
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import OptimizedEventProcessor
from carbon.utils.unit_converter import UnitConverter

def test_simple_conversion():
    """Test direct unit converter"""
    print("🔧 Testing UnitConverter directly:")
    
    # Test the fixed area conversion
    result, audit = UnitConverter.convert_area(50000.0, "square_meters", "hectares")
    print(f"50,000 m² → {result} hectares (should be 5.0)")
    
    # Test area to acres
    result, audit = UnitConverter.convert_area(5.0, "hectares", "acres") 
    print(f"5.0 hectares → {result} acres (should be ~12.36)")

def test_production_event_debug():
    """Debug why production events fail unit conversion"""
    print("\n🌾 Testing production event processing:")
    
    simple_test = {
        "type": "HA",
        "area_covered": "5.0",
        "area_unit": "hectares",
        "equipment_hours": "6",
        "fuel_consumed": "45",
        "fuel_unit": "liters",
        "yield_quantity": "15.5",
        "yield_unit": "tonnes",
        "product_name": "Avocado"
    }
    
    try:
        result = OptimizedEventProcessor._process_production_event(simple_test)
        print(f"✅ Success: {result}")
        print(f"   Unit conversions applied: {result.get('unit_conversions_applied', 'NOT SET')}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_simple_conversion()
    test_production_event_debug()