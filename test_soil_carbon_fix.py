#!/usr/bin/env python3
"""
Test the soil management carbon calculation fix for string/int comparison
"""
import os
import sys
import django

# Setup Django
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from history.models import SoilManagementEvent

def test_soil_carbon_fix():
    """Test carbon calculation with string fuel_consumed values"""
    
    try:
        # Get the most recent soil management event with fuel data
        event = SoilManagementEvent.objects.filter(fuel_consumed__isnull=False).latest('date')
        print(f'🧪 Testing carbon calculation for soil event ID {event.id}')
        print(f'📋 Event details:')
        print(f'   - Fuel consumed: {event.fuel_consumed} (type: {type(event.fuel_consumed)})')
        print(f'   - Equipment hours: {event.equipment_hours} (type: {type(event.equipment_hours)})')
        print(f'   - Area covered: {event.area_covered}')
        print(f'   - Event type: {event.type}')
        
        # Test the calculation
        calculator = EventCarbonCalculator()
        result = calculator.calculate_soil_management_event_impact(event)
        
        print(f'\n✅ Carbon calculation successful!')
        print(f'   - CO2e: {result.get("co2e")} kg')
        print(f'   - Efficiency score: {result.get("efficiency_score")}')
        print(f'   - USDA factors: {result.get("usda_factors_based")}')
        print(f'   - Error: {result.get("error", "None")}')
        print(f'   - Verification status: {result.get("verification_status")}')
        
        if result.get("error"):
            print(f'❌ Still has error: {result.get("error")}')
            return False
        else:
            print(f'🎉 No errors - string/int comparison issue fixed!')
            return True
            
    except Exception as e:
        print(f'❌ Test failed with exception: {e}')
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    test_soil_carbon_fix()