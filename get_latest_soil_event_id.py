#!/usr/bin/env python3
"""
Get the ID of the latest created Soil Management event
"""

import os

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from history.models import SoilManagementEvent


def get_latest_soil_event_id():
    print("🔍 FINDING LATEST SOIL MANAGEMENT EVENT")
    print("=" * 60)

    # Get the latest soil management event
    latest_event = SoilManagementEvent.objects.filter(name__icontains="MCP Browser Test").order_by("-id").first()

    if latest_event:
        print(f"✅ FOUND LATEST EVENT:")
        print(f"📝 Event ID: {latest_event.id}")
        print(f"📅 Date: {latest_event.date}")
        print(f"🏷️ Name: {latest_event.name}")
        print(f"🔬 Type: {latest_event.type}")
        print(f"📏 Area: {latest_event.area_covered} {latest_event.area_unit}")
        print(f"⛽ Fuel: {latest_event.fuel_consumed} {latest_event.fuel_unit}")
        print(f"📝 Description: {latest_event.description}")
        print("=" * 60)
        print(f"🎯 MCP BROWSER TEST EVENT ID: {latest_event.id}")
        print("=" * 60)
        return latest_event.id
    else:
        print("❌ No MCP Browser Test events found")
        return None


if __name__ == "__main__":
    get_latest_soil_event_id()
