#!/usr/bin/env python3
"""
Debug script to investigate why event 178 is returning empty field values
in the complete summary API endpoint.
"""

import os
import sys

import django

# Add the project directory to Python path
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

import json

from carbon.views import get_complete_summary
from history.models import ProductionEvent


def debug_event_178():
    """Debug event 178 data at different levels"""

    print("🔧 DEBUGGING EVENT 178 DATA DISCREPANCY")
    print("=" * 60)

    try:
        # 1. Direct database query
        print("\n1️⃣ DIRECT DATABASE QUERY:")
        event = ProductionEvent.objects.filter(id=178).first()
        if event:
            print(f"✅ Event found: ID={event.id}")
            print(f"   Type: {event.type}")
            print(f"   Raw area field: '{event.area}'")
            print(f"   Raw application_timing field: '{getattr(event, 'application_timing', 'NOT_FOUND')}'")
            print(f"   Raw way_of_application field: '{getattr(event, 'way_of_application', 'NOT_FOUND')}'")

            # Check all field values
            print("\n   🔍 ALL EVENT FIELDS:")
            for field in event._meta.fields:
                value = getattr(event, field.name, "N/A")
                if value and str(value).strip():  # Only show non-empty fields
                    print(f"   {field.name}: '{value}'")
        else:
            print("❌ Event 178 not found in database!")
            return

        # 2. Production context
        print(f"\n2️⃣ PRODUCTION CONTEXT:")
        production = event.production
        print(f"   Production ID: {production.id}")
        print(f"   Production name: {production.name}")

        # 3. Check complete summary API data
        print(f"\n3️⃣ COMPLETE SUMMARY API DATA:")
        try:
            # This simulates what the API endpoint returns
            from django.contrib.auth.models import AnonymousUser
            from django.http import HttpRequest

            from carbon.views import get_complete_summary

            # Create a mock request
            request = HttpRequest()
            request.user = AnonymousUser()
            request.method = "GET"

            # Get the complete summary data (this is what the frontend receives)
            response = get_complete_summary(request, production_id=production.id)

            if hasattr(response, "data"):
                data = json.loads(response.content)

                # Find event 178 in the timeline
                timeline_events = data.get("timeline", [])
                event_178_data = None

                for timeline_event in timeline_events:
                    if str(timeline_event.get("id")) == "178" or timeline_event.get("id") == 178:
                        event_178_data = timeline_event
                        break

                if event_178_data:
                    print("   ✅ Event 178 found in complete summary API response:")
                    print(f"   API area field: '{event_178_data.get('area', 'NOT_FOUND')}'")
                    print(f"   API application_timing field: '{event_178_data.get('application_timing', 'NOT_FOUND')}'")
                    print(f"   API way_of_application field: '{event_178_data.get('way_of_application', 'NOT_FOUND')}'")

                    # Show all API fields for event 178
                    print("\n   🔍 ALL API FIELDS FOR EVENT 178:")
                    for key, value in event_178_data.items():
                        if value and str(value).strip():  # Only show non-empty fields
                            print(f"   API {key}: '{value}'")
                else:
                    print("   ❌ Event 178 NOT found in complete summary API response!")
                    print(f"   Available event IDs: {[e.get('id') for e in timeline_events]}")
            else:
                print(f"   ❌ API returned non-data response: {type(response)}")

        except Exception as api_error:
            print(f"   ❌ API Error: {api_error}")

        # 4. Expected vs actual comparison
        print(f"\n4️⃣ EXPECTED vs ACTUAL COMPARISON:")
        expected = {"area": "21.88 ha", "application_timing": "pre_plant", "way_of_application": "spray_targeted"}

        actual_db = {
            "area": event.area,
            "application_timing": getattr(event, "application_timing", None),
            "way_of_application": getattr(event, "way_of_application", None),
        }

        print("   📊 EXPECTED (from user's JSON):")
        for key, value in expected.items():
            print(f"   {key}: '{value}'")

        print("   📊 ACTUAL (from database):")
        for key, value in actual_db.items():
            print(f"   {key}: '{value}'")

        print("   📊 DIFFERENCES:")
        for key in expected.keys():
            expected_val = expected[key]
            actual_val = actual_db[key] or ""
            if str(expected_val).strip() != str(actual_val).strip():
                print(f"   ⚠️  {key}: expected '{expected_val}' but got '{actual_val}'")

    except Exception as e:
        print(f"❌ Error during debugging: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    debug_event_178()
