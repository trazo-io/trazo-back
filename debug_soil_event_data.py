#!/usr/bin/env python3
"""
Debug soil management event data to see what's actually being stored
"""
import os
import sys

import django

# Setup Django
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from history.models import SoilManagementEvent


def debug_soil_event_data():
    """Debug the most recent soil management events to see stored data"""

    try:
        # Get the most recent soil management events
        recent_events = SoilManagementEvent.objects.all().order_by("-date")[:5]

        if not recent_events:
            print("❌ No soil management events found")
            return

        print(f"🔍 Found {len(recent_events)} recent soil management events:")
        print("=" * 80)

        for i, event in enumerate(recent_events, 1):
            print(f"\n📋 Event #{i} - ID: {event.id}")
            print(f"📅 Date: {event.date}")
            print(f"🏷️ Type: {event.type}")
            print(f"📄 Description: {event.description}")

            # Enhanced fields we're looking for (based on model field list)
            enhanced_fields = {
                "Area Covered": getattr(event, "area_covered", "NOT_FOUND"),
                "Area Unit": getattr(event, "area_unit", "NOT_FOUND"),
                "Fuel Consumed": getattr(event, "fuel_consumed", "NOT_FOUND"),
                "Fuel Unit": getattr(event, "fuel_unit", "NOT_FOUND"),
                "Equipment Hours": getattr(event, "equipment_hours", "NOT_FOUND"),
                "Transportation Distance": getattr(event, "transportation_distance", "NOT_FOUND"),
                "Transportation Unit": getattr(event, "transportation_unit", "NOT_FOUND"),
                "Soil pH": getattr(event, "soil_ph", "NOT_FOUND"),
                "Organic Matter": getattr(event, "organic_matter_percentage", "NOT_FOUND"),
                "Amendment Type": getattr(event, "amendment_type", "NOT_FOUND"),
                "Amendment Amount": getattr(event, "amendment_amount", "NOT_FOUND"),
                "Test Results": getattr(event, "test_results", "NOT_FOUND"),
                "Production Efficiency": getattr(event, "production_efficiency", "NOT_FOUND"),
                "Carbon Sequestration": getattr(event, "carbon_sequestration_potential", "NOT_FOUND"),
                "Name": getattr(event, "name", "NOT_FOUND"),
            }

            print("\n🔍 Enhanced Field Data:")
            for field_name, value in enhanced_fields.items():
                if value is not None and value != "NOT_FOUND" and value != "":
                    print(f"  ✅ {field_name}: {value}")
                else:
                    print(f"  ❌ {field_name}: {value}")

            print("-" * 60)

        print(f"\n💡 Analysis: Check which enhanced fields have actual data vs empty/missing values")

    except Exception as e:
        print(f"❌ Error debugging soil events: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_soil_event_data()
