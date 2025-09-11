#!/usr/bin/env python
"""
Debug script to understand why carbon calculations return 0
"""

import os
import sys

import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from history.models import ChemicalEvent, GeneralEvent, ProductionEvent


def debug_carbon_calculations():
    """Debug carbon calculations for Production 125 events"""

    calculator = EventCarbonCalculator()

    print("=== DEBUGGING CARBON CALCULATIONS FOR PRODUCTION 125 ===\n")

    # Check Chemical Events
    chemical_events = ChemicalEvent.objects.filter(history_id=125)
    print(f"Chemical Events: {chemical_events.count()}")

    for event in chemical_events:
        print(f"\n--- Chemical Event {event.id} ---")
        print(f"Type: {event.get_type_display()}")
        print(f"Commercial Name: {event.commercial_name}")
        print(f"Volume: {event.volume}")
        print(f"Concentration: {event.concentration}")
        print(f"Area: {event.area}")
        print(f"Date: {event.date}")
        print(f"History: {event.history}")

        if event.history and hasattr(event.history, "product"):
            print(f"Product: {event.history.product}")
            print(f"Crop Type: {event.history.crop_type}")

        print("Calculating impact...")
        try:
            result = calculator.calculate_chemical_event_impact(event)
            print(f"Calculation Result: {result}")

            if result.get("co2e", 0) == 0:
                print("❌ Zero emissions calculated - analyzing why...")
                print(f"Breakdown: {result.get('breakdown', {})}")
                print(f"Confidence: {result.get('confidence_score', 0)}")
                print(f"USDA Factors: {result.get('usda_factors_based', False)}")

        except Exception as e:
            print(f"❌ Calculation Error: {e}")
            import traceback

            traceback.print_exc()

    # Check Production Events
    production_events = ProductionEvent.objects.filter(history_id=125)
    print(f"\n\nProduction Events: {production_events.count()}")

    for event in production_events[:2]:  # Just check first 2
        print(f"\n--- Production Event {event.id} ---")
        print(f"Type: {event.get_type_display()}")
        print(f"Date: {event.date}")
        print(f"Description: {event.description}")

        print("Calculating impact...")
        try:
            result = calculator.calculate_production_event_impact(event)
            print(f"Calculation Result: {result}")

            if result.get("co2e", 0) == 0:
                print("❌ Zero emissions calculated")
                print(f"Method: {result.get('calculation_method', 'unknown')}")

        except Exception as e:
            print(f"❌ Calculation Error: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    debug_carbon_calculations()
