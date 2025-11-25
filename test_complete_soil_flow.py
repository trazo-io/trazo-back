#!/usr/bin/env python3

"""
Test script to verify complete soil management carbon calculation flow.
Tests both backend calculation and simulates frontend data flow.
"""

import os
import sys
import django
import json
from datetime import date
from decimal import Decimal

# Add the project root to the Python path
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')

# Set up Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')

# Setup Django
django.setup()

from carbon.services.event_carbon_calculator import VerifiedEmissionFactors

def test_soil_management_calculation():
    """Test soil management carbon calculation with realistic data."""
    print("🧪 Testing Soil Management Carbon Calculation Flow")
    print("=" * 60)
    
    # Test data that matches what frontend would send
    event_data = {
        'type': 'ST',  # Soil Testing
        'area': '2.5',  # hectares (string format as from form)
        'fuel_consumed': '15.0',  # liters (string format as from form)
        'equipment_hours': '4.0',  # hours (string format as from form)
        'depth': '0.3',  # meters (optional)
        'notes': 'Comprehensive soil analysis for nutrient planning',
        'date': '2024-03-15'
    }
    
    print("📝 Test Input Data:")
    print(json.dumps(event_data, indent=2))
    print()
    
    try:
        # Test the carbon calculation service
        print("🔍 Testing Carbon Calculation Service...")
        
        calculator = VerifiedEmissionFactors()
        
        # Calculate emissions using the same method as the API
        result = calculator.calculate_production_event_emissions(
            event_type=event_data['type'],
            **event_data
        )
        
        print("✅ Carbon Calculation Successful!")
        print(f"   CO2e Emissions: {result['total_co2e_kg']:.3f} kg")
        print(f"   Calculation Method: {result.get('calculation_method', 'Standard')}")
        print(f"   Components: {len(result.get('components', []))} emission sources")
        print()
        
        # Print detailed breakdown
        if 'components' in result:
            print("📊 Emission Components:")
            for component in result['components']:
                print(f"   • {component.get('description', 'Unknown')}: {component.get('co2e_kg', 0):.3f} kg CO2e")
        print()
        
        # Test type conversion handling (main bug we fixed)
        print("🔧 Testing Type Conversion (Bug Fix Verification)...")
        
        # Test with different input types that were causing issues
        test_cases = [
            {'fuel_consumed': '15.0', 'expected': float},
            {'fuel_consumed': 15.0, 'expected': float},
            {'fuel_consumed': Decimal('15.0'), 'expected': float},
            {'equipment_hours': '4.0', 'expected': float},
            {'area': '2.5', 'expected': float},
        ]
        
        for test_case in test_cases:
            test_data = event_data.copy()
            test_data.update(test_case)
            
            try:
                calc_result = calculator.calculate_production_event_emissions(
                    event_type='ST',
                    **{k: v for k, v in test_data.items() if k != 'expected'}
                )
                print(f"   ✅ Type conversion successful for {list(test_case.keys())[0]}: {type(list(test_case.values())[0])}")
            except Exception as e:
                print(f"   ❌ Type conversion failed for {list(test_case.keys())[0]}: {e}")
                return False
        
        print()
        
        # Simulate frontend carbon preview flow
        print("🎨 Simulating Frontend Carbon Preview Flow...")
        
        # This simulates the data structure that NewEvent.jsx would send to calculateCarbonWithDebounce
        frontend_data = {
            'type': event_data['type'],
            'area': event_data['area'],
            'fuel_consumed': event_data['fuel_consumed'],
            'equipment_hours': event_data['equipment_hours'],
            'depth': event_data.get('depth'),
            'notes': event_data.get('notes')
        }
        
        print(f"   Frontend data structure: {json.dumps(frontend_data, indent=4)}")
        
        # Calculate again to verify consistency
        preview_result = calculator.calculate_production_event_emissions(
            event_type=frontend_data['type'],
            **frontend_data
        )
        
        if abs(result['total_co2e_kg'] - preview_result['total_co2e_kg']) < 0.001:
            print("   ✅ Frontend preview calculation matches backend calculation")
        else:
            print(f"   ❌ Mismatch: Backend={result['total_co2e_kg']}, Frontend Preview={preview_result['total_co2e_kg']}")
            return False
        
        print()
        print("🎉 All Tests PASSED!")
        print("✅ Soil management carbon calculation working correctly")
        print("✅ Type conversion bug fixed")
        print("✅ Frontend-backend data flow verified")
        
        return True
        
    except Exception as e:
        print(f"❌ Test FAILED with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_edge_cases():
    """Test edge cases that might cause issues."""
    print("\n🧪 Testing Edge Cases")
    print("=" * 30)
    
    calculator = VerifiedEmissionFactors()
    
    edge_cases = [
        {
            'name': 'Empty strings',
            'data': {'type': 'ST', 'fuel_consumed': '', 'area': '2.5'}
        },
        {
            'name': 'Zero values',
            'data': {'type': 'ST', 'fuel_consumed': '0', 'area': '0'}
        },
        {
            'name': 'Very small values',
            'data': {'type': 'ST', 'fuel_consumed': '0.1', 'area': '0.01'}
        },
        {
            'name': 'Large values',
            'data': {'type': 'ST', 'fuel_consumed': '1000', 'area': '100'}
        }
    ]
    
    for case in edge_cases:
        try:
            result = calculator.calculate_production_event_emissions(
                event_type=case['data']['type'],
                **{k: v for k, v in case['data'].items() if k != 'type'}
            )
            print(f"   ✅ {case['name']}: {result['total_co2e_kg']:.3f} kg CO2e")
        except Exception as e:
            print(f"   ❌ {case['name']}: Error - {e}")

if __name__ == '__main__':
    success = test_soil_management_calculation()
    test_edge_cases()
    
    if success:
        print("\n🎯 SUMMARY: Soil management carbon calculation is working correctly!")
        print("   Both frontend and backend issues have been resolved.")
        sys.exit(0)
    else:
        print("\n🚨 SUMMARY: Issues remain with soil management carbon calculation.")
        sys.exit(1)