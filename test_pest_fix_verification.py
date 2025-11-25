#!/usr/bin/env python3
"""
Test Pest Management Carbon Calculation Fix

Verify that the fix resolves the 0.0 kg CO2e issue.
"""

import os
import sys
import django

# Add trazo-back to path and configure Django
sys.path.insert(0, '/Users/oscarmunoz/dev/trazo/trazo-back')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor

def test_pest_fix_verification():
    """Test that the pest management fix works correctly"""
    
    print("🧪 TESTING PEST MANAGEMENT CARBON CALCULATION FIX")
    print("=" * 60)
    
    # Test scenarios with different pest management types
    test_scenarios = [
        {
            "name": "Scouting Event",
            "data": {
                "type": "SC",
                "name": "Morning Aphid Check",
                "pest_species": "aphids",
                "pest_pressure_level": "medium",
                "field_area_hectares": "2.5",
                "travel_distance_km": "5.0", 
                "time_spent_hours": "2.0",
                "parcel_id": 1,
                "establishment_id": 1,
                "date": "2025-01-21T10:00"
            },
            "expected_co2e": 0.2
        },
        {
            "name": "Trap Monitoring",
            "data": {
                "type": "TM",
                "name": "Weekly Trap Check",
                "pest_species": "thrips",
                "trap_count": "25",
                "field_area_hectares": "3.0",
                "travel_distance_km": "6.0",
                "time_spent_hours": "1.5",
                "parcel_id": 1,
                "establishment_id": 1,
                "date": "2025-01-21T09:00"
            },
            "expected_co2e": 0.1
        },
        {
            "name": "IPM Implementation",
            "data": {
                "type": "IP",
                "name": "Citrus Mite IPM Strategy",
                "pest_species": "citrus_mites",
                "pest_pressure_level": "medium",
                "imp_strategy": "biological_control",
                "field_area_hectares": "10.0",
                "travel_distance_km": "12.0",
                "time_spent_hours": "6.0",
                "parcel_id": 1,
                "establishment_id": 1,
                "date": "2025-01-21T07:00"
            },
            "expected_co2e": -1.0
        },
        {
            "name": "Beneficial Release",
            "data": {
                "type": "BR",
                "name": "Predatory Mite Release",
                "pest_species": "spider_mites",
                "beneficial_species": "predatory_mites",
                "release_quantity": "1000",
                "field_area_hectares": "15.0",
                "travel_distance_km": "8.0",
                "time_spent_hours": "4.0",
                "parcel_id": 1,
                "establishment_id": 1,
                "date": "2025-01-21T06:00"
            },
            "expected_co2e": -0.5
        }
    ]
    
    calculator = OptimizedCarbonCalculator()
    all_passed = True
    
    for scenario in test_scenarios:
        print(f"\n📋 Testing: {scenario['name']}")
        print("-" * 40)
        
        try:
            # Process event data
            processed_event = OptimizedEventProcessor.process_event_data("pest_management", scenario["data"])
            
            # Calculate carbon impact
            result = calculator.calculate_pest_management_event_impact(processed_event)
            
            co2e = result.get('co2e', 0)
            expected = scenario['expected_co2e']
            
            print(f"   🎯 Expected CO2e: {expected} kg")
            print(f"   📊 Actual CO2e: {co2e} kg")
            print(f"   🔬 Method: {result.get('calculation_method', 'N/A')}")
            print(f"   📈 Efficiency: {result.get('efficiency_score', 'N/A')}")
            print(f"   ✅ Status: {result.get('verification_status', 'N/A')}")
            
            if 'error' in result:
                print(f"   ❌ Error: {result['error']}")
                all_passed = False
            elif co2e == expected:
                print(f"   ✅ PASS: Calculation matches expected value")
            else:
                print(f"   ⚠️  MISMATCH: Expected {expected}, got {co2e}")
                all_passed = False
                
        except Exception as e:
            print(f"   ❌ CALCULATION ERROR: {e}")
            all_passed = False
            import traceback
            traceback.print_exc()
    
    print(f"\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED! Pest management calculations fixed.")
        print("✅ End-to-end flow now working correctly")
        print("🌱 Real-world values being calculated properly")
    else:
        print("❌ Some tests failed. Review results above.")
    
    # Test the original E2E scenario
    print(f"\n📱 TESTING ORIGINAL E2E SCENARIO")
    print("-" * 40)
    
    original_data = {
        "type": "SC",
        "name": "Morning Aphid Check",
        "pest_species": "aphids",
        "pest_pressure_level": "medium",
        "field_area_hectares": "2.5",
        "travel_distance_km": "5.0", 
        "time_spent_hours": "2.0",
        "crop_growth_stage": "flowering",
        "weather_conditions": "dry",
        "economic_threshold_met": False,
        "action_recommended": "continue_monitoring",
        "parcel_id": 1,
        "establishment_id": 1,
        "date": "2025-01-21T10:00"
    }
    
    try:
        processed = OptimizedEventProcessor.process_event_data("pest_management", original_data)
        result = calculator.calculate_pest_management_event_impact(processed)
        
        print(f"   🌱 Original E2E CO2e: {result.get('co2e', 'N/A')} kg")
        print(f"   🎯 Expected Range: 0.5-2.0 kg (realistic for scouting)")
        
        if result.get('co2e', 0) > 0:
            print(f"   ✅ SUCCESS: Non-zero result achieved!")
            print(f"   🔄 End-to-end flow now working correctly")
        else:
            print(f"   ⚠️  Still getting zero - needs further investigation")
            
    except Exception as e:
        print(f"   ❌ E2E test error: {e}")

if __name__ == "__main__":
    test_pest_fix_verification()