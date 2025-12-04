#!/usr/bin/env python3
"""
Simple debug script to check event 178 database values
"""

import os
import sys

import django

# Add the project directory to Python path
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from history.models import ChemicalEvent, ProductionEvent


def debug_event_178_simple():
    """Simple debug of event 178 data"""

    print("🔧 DEBUGGING EVENT 178 - DATABASE VALUES")
    print("=" * 50)

    try:
        # First check ProductionEvent
        production_event = ProductionEvent.objects.filter(id=178).first()
        if production_event:
            print("✅ Event 178 found in ProductionEvent model")
            event = production_event
        else:
            # Check ChemicalEvent model
            chemical_event = ChemicalEvent.objects.filter(id=178).first()
            if chemical_event:
                print("✅ Event 178 found in ChemicalEvent model")
                event = chemical_event
            else:
                print("❌ Event 178 NOT found in either ProductionEvent or ChemicalEvent models!")

                # Show what events ARE available for production 232
                print("\n🔍 Available ProductionEvents for production 232:")
                prod_events = ProductionEvent.objects.filter(production_id=232)
                for pe in prod_events:
                    print(f"   ProductionEvent ID {pe.id}: {pe.type}")

                print("\n🔍 Available ChemicalEvents for production 232:")
                chem_events = ChemicalEvent.objects.filter(production_id=232)
                for ce in chem_events:
                    print(f"   ChemicalEvent ID {ce.id}: {ce.commercial_name}")
                return

        print(f"✅ Event 178 found in database")
        print(f"   ID: {event.id}")
        if hasattr(event, "type"):
            print(f"   Type: {event.type}")
        if hasattr(event, "commercial_name"):
            print(f"   Commercial Name: {event.commercial_name}")
        print(f"   Date: {event.date}")

        # Get production ID correctly for ChemicalEvent
        if hasattr(event, "production_id"):
            print(f"   Production ID: {event.production_id}")
        elif hasattr(event, "production"):
            print(f"   Production ID: {event.production.id if event.production else 'None'}")

        # Check the specific fields mentioned by user
        print("\n🔍 SPECIFIC FIELD VALUES:")
        if hasattr(event, "area"):
            print(f"   area: '{event.area}' (type: {type(event.area)})")
        else:
            print("   area: FIELD DOES NOT EXIST")

        # Check if application_timing field exists
        if hasattr(event, "application_timing"):
            print(f"   application_timing: '{event.application_timing}' (type: {type(event.application_timing)})")
        else:
            print("   application_timing: FIELD DOES NOT EXIST")

        # Check if way_of_application field exists
        if hasattr(event, "way_of_application"):
            print(f"   way_of_application: '{event.way_of_application}' (type: {type(event.way_of_application)})")
        else:
            print("   way_of_application: FIELD DOES NOT EXIST")

        # Show ALL non-empty fields
        print("\n📊 ALL NON-EMPTY FIELDS:")
        for field in event._meta.fields:
            field_name = field.name
            value = getattr(event, field_name, None)

            # Only show fields that have actual content
            if value is not None and str(value).strip():
                print(f"   {field_name}: '{value}' (type: {type(value)})")

        # Expected values from user's JSON
        print(f"\n📋 EXPECTED VALUES (from user's JSON):")
        print(f"   area: '21.88 ha'")
        print(f"   application_timing: 'pre_plant'")
        print(f"   way_of_application: 'spray_targeted'")

        # Check what fields contain the expected data
        print(f"\n🔍 SEARCHING FOR EXPECTED VALUES IN ALL FIELDS:")
        expected_area = "21.88"
        expected_timing = "pre_plant"
        expected_application = "spray_targeted"

        for field in event._meta.fields:
            field_name = field.name
            value = str(getattr(event, field_name, ""))

            if expected_area in value:
                print(f"   ✅ Found '21.88' in field: {field_name} = '{value}'")
            if expected_timing in value:
                print(f"   ✅ Found 'pre_plant' in field: {field_name} = '{value}'")
            if expected_application in value:
                print(f"   ✅ Found 'spray_targeted' in field: {field_name} = '{value}'")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_event_178_simple()
