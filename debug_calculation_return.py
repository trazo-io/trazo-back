#!/usr/bin/env python3

import os
import sys
import django
from datetime import datetime

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from history.models import ChemicalEvent, History, WeatherEvent
from carbon.services.event_carbon_calculator import EventCarbonCalculator

def debug_calculation_response():
    """Debug what the EventCarbonCalculator actually returns"""
    
    # Get the latest chemical event
    try:
        chemical_event = ChemicalEvent.objects.latest('id')
        print(f"🔬 Testing Chemical Event {chemical_event.id}")
        print(f"   Type: {chemical_event.type}")
        print(f"   Commercial Name: {chemical_event.commercial_name}")
        print(f"   Volume: {chemical_event.volume}")
        print(f"   Area: {chemical_event.area}")
        print(f"   Concentration: {chemical_event.concentration}")
        
        calculator = EventCarbonCalculator()
        result = calculator.calculate_chemical_event_impact(chemical_event)
        
        print(f"\n📊 CALCULATOR RESULT:")
        print(f"   Type: {type(result)}")
        print(f"   Content: {result}")
        
        if isinstance(result, dict):
            print(f"\n🔍 DICT KEYS:")
            for key, value in result.items():
                print(f"   '{key}': {value} ({type(value)})")
        
        # Try different ways to extract the result
        print(f"\n🧪 EXTRACTION ATTEMPTS:")
        print(f"   result.get('total_co2e'): {result.get('total_co2e', 'KEY NOT FOUND')}")
        print(f"   result.get('total_co2e_kg'): {result.get('total_co2e_kg', 'KEY NOT FOUND')}")
        print(f"   result.get('total_emissions'): {result.get('total_emissions', 'KEY NOT FOUND')}")
        print(f"   result.get('carbon_footprint'): {result.get('carbon_footprint', 'KEY NOT FOUND')}")
        print(f"   result.get('emissions'): {result.get('emissions', 'KEY NOT FOUND')}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_calculation_response()