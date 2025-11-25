#!/usr/bin/env python3
"""
Simple Test: SoilManagementEvent Standardization Validation
Tests that SoilManagementEvent now has standardized fuel consumption fields
"""

import os
import django
import sys
from decimal import Decimal

# Setup Django environment
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from history.models import SoilManagementEvent, History
from carbon.services.event_carbon_calculator import EventCarbonCalculator

def test_model_fields():
    """Test that SoilManagementEvent has all standardized fields"""
    print("🌱 TESTING SOILMANAGEMENTEVENT STANDARDIZATION")
    print("=" * 60)
    
    # Get SoilManagementEvent model fields
    soil_fields = {field.name: field for field in SoilManagementEvent._meta.get_fields()}
    
    # Expected standardized fields (matching ProductionEvent)
    expected_fields = [
        'name', 'area_covered', 'fuel_consumed', 'fuel_unit', 
        'equipment_hours', 'production_efficiency', 
        'transportation_distance', 'transportation_unit'
    ]
    
    print("STANDARDIZED FIELD VERIFICATION:")
    print()
    
    missing_fields = []
    present_fields = []
    
    for field_name in expected_fields:
        if field_name in soil_fields:
            field = soil_fields[field_name]
            field_type = type(field).__name__
            present_fields.append((field_name, field_type))
            print(f"✅ {field_name} ({field_type})")
        else:
            missing_fields.append(field_name)
            print(f"❌ {field_name} - MISSING")
    
    print()
    print(f"RESULT: {len(present_fields)}/{len(expected_fields)} standardized fields present")
    
    if missing_fields:
        print(f"❌ MISSING FIELDS: {missing_fields}")
        return False
    else:
        print("✅ ALL STANDARDIZED FIELDS PRESENT")
        return True

def test_carbon_calculation():
    """Test carbon calculation with fuel data"""
    print()
    print("CARBON CALCULATION TEST:")
    print("=" * 60)
    
    # Create test history
    try:
        history = History.objects.get(crop_type_name="test_avocados")
    except History.DoesNotExist:
        history = History.objects.create(
            crop_type_name="test_avocados",
            phase="growing"
        )
    
    print("Creating test soil management event with fuel data...")
    
    # Create test event with fuel data
    event = SoilManagementEvent.objects.create(
        history=history,
        type='TI',  # Tillage
        area=Decimal('2.5'),
        area_unit='hectares',
        # NEW STANDARDIZED FIELDS
        name='Test Tillage Operation',
        area_covered=Decimal('2.5'),
        fuel_consumed=Decimal('15.0'),  # Liters
        fuel_unit='L',
        equipment_hours=Decimal('3.0'),
        observation='Test tillage with fuel data'
    )
    
    print(f"Event created with:")
    print(f"  - Type: {event.type}")
    print(f"  - Area: {event.area} {event.area_unit}")
    print(f"  - Fuel: {event.fuel_consumed} {event.fuel_unit}")
    print(f"  - Equipment Hours: {event.equipment_hours}")
    print()
    
    # Calculate carbon impact
    calculator = EventCarbonCalculator()
    result = calculator.calculate_soil_management_event_impact(event)
    
    print("CARBON CALCULATION RESULTS:")
    print(f"  Total CO2e: {result['co2e']} kg")
    print(f"  Confidence: {result['efficiency_score']}%")
    print(f"  Method: {result['calculation_method']}")
    
    if 'breakdown' in result:
        breakdown = result['breakdown']
        print(f"  Fuel Emissions: {breakdown.get('fuel_emissions', 0)} kg CO2e")
        print(f"  Area Emissions: {breakdown.get('area_emissions', 0)} kg CO2e")
    
    # Clean up
    event.delete()
    
    # Validate enhanced accuracy
    enhanced_accuracy = result['efficiency_score'] >= 85
    fuel_calculation = 'fuel_emissions' in result.get('breakdown', {})
    
    print()
    print("VALIDATION:")
    print(f"  ✅ Enhanced accuracy (≥85%): {'PASS' if enhanced_accuracy else 'FAIL'}")
    print(f"  ✅ Fuel emissions calculated: {'PASS' if fuel_calculation else 'FAIL'}")
    
    return enhanced_accuracy and fuel_calculation

def main():
    """Run simple validation tests"""
    print("🔍 SOIL MANAGEMENT STANDARDIZATION VALIDATION")
    print()
    
    # Test 1: Model fields
    fields_ok = test_model_fields()
    
    # Test 2: Carbon calculation
    calculation_ok = test_carbon_calculation()
    
    print()
    print("=" * 60)
    print("FINAL SUMMARY:")
    print(f"✅ Model Standardization: {'PASS' if fields_ok else 'FAIL'}")
    print(f"✅ Enhanced Calculation: {'PASS' if calculation_ok else 'FAIL'}")
    
    if fields_ok and calculation_ok:
        print()
        print("🎯 SUCCESS! SoilManagementEvent standardization complete:")
        print("   - All fuel consumption fields present")
        print("   - Enhanced carbon calculation accuracy")
        print("   - Consistent with other Trazo event types")
    else:
        print()
        print("❌ FAILED! Issues found in standardization")

if __name__ == "__main__":
    main()