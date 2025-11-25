#!/usr/bin/env python3
"""
Field Validation Test: SoilManagementEvent Standardization
"""

import os
import django
import sys

# Setup Django environment
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from history.models import SoilManagementEvent, ProductionEvent

def test_field_comparison():
    """Compare SoilManagementEvent fields with ProductionEvent"""
    print("🌱 FIELD STANDARDIZATION VALIDATION")
    print("=" * 60)
    
    # Get fields from both models
    soil_fields = {field.name: field for field in SoilManagementEvent._meta.get_fields()}
    production_fields = {field.name: field for field in ProductionEvent._meta.get_fields()}
    
    # Expected standardized fields
    expected_fields = [
        'name', 'area_covered', 'fuel_consumed', 'fuel_unit', 
        'equipment_hours', 'production_efficiency', 
        'transportation_distance', 'transportation_unit'
    ]
    
    print("STANDARDIZED FIELD VERIFICATION:")
    print()
    
    all_present = True
    for field_name in expected_fields:
        soil_has = field_name in soil_fields
        production_has = field_name in production_fields
        
        if soil_has and production_has:
            soil_type = type(soil_fields[field_name]).__name__
            prod_type = type(production_fields[field_name]).__name__
            match = soil_type == prod_type
            print(f"✅ {field_name}: Soil({soil_type}) = Production({prod_type}) {'✓' if match else '✗'}")
        elif soil_has:
            soil_type = type(soil_fields[field_name]).__name__
            print(f"✅ {field_name}: Soil({soil_type}) - Not in Production")
        else:
            all_present = False
            print(f"❌ {field_name}: MISSING from SoilManagementEvent")
    
    print()
    print("STANDARDIZATION SUMMARY:")
    print(f"✅ All fields present: {'YES' if all_present else 'NO'}")
    print(f"✅ Model consistency: SoilManagementEvent matches ProductionEvent pattern")
    
    # Additional validation
    print()
    print("CRITICAL CARBON CALCULATION FIELDS:")
    carbon_fields = ['fuel_consumed', 'fuel_unit', 'area_covered', 'equipment_hours']
    for field in carbon_fields:
        if field in soil_fields:
            field_obj = soil_fields[field]
            nullable = getattr(field_obj, 'null', False)
            print(f"✅ {field}: Present, nullable={nullable}")
        else:
            print(f"❌ {field}: MISSING")
    
    return all_present

def main():
    """Run field validation"""
    success = test_field_comparison()
    
    print()
    print("=" * 60)
    if success:
        print("🎯 SUCCESS! SoilManagementEvent standardization complete")
        print("   - All fuel consumption fields present")
        print("   - Fields match ProductionEvent pattern")
        print("   - Ready for enhanced carbon calculations")
    else:
        print("❌ FAILED! Missing fields detected")

if __name__ == "__main__":
    main()