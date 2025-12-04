#!/usr/bin/env python3
"""Debug Equipment Type display issue for Event 114"""

import os

import django
from django.conf import settings

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from history.models import EquipmentEvent

# Check Event 114 data
print("=== EQUIPMENT EVENT 114 DATABASE INVESTIGATION ===")

try:
    event = EquipmentEvent.objects.get(id=114)
    print(f"✅ Event 114 found")
    print(f"📋 Description: {event.description}")
    print(f"🚜 equipment_type_structured: '{event.equipment_type_structured}'")
    print(f"📝 equipment_name: '{event.equipment_name}'")
    print(f"🔍 equipment_type_structured is not None: {event.equipment_type_structured is not None}")
    print(f"🔍 equipment_type_structured is not empty: {event.equipment_type_structured != ''}")
    print(f"🔍 equipment_type_structured type: {type(event.equipment_type_structured)}")
    print(f"🔍 equipment_type_structured repr: {repr(event.equipment_type_structured)}")

    # Check full data
    print("\n=== FULL EVENT DATA ===")
    for field_name in [
        "id",
        "description",
        "equipment_type_structured",
        "equipment_name",
        "fuel_consumed",
        "fuel_type",
        "area_worked",
        "hours_operated",
    ]:
        value = getattr(event, field_name, "FIELD_NOT_FOUND")
        print(f"{field_name}: {repr(value)}")

    print("\n=== FIELD DISPLAY CONDITIONS CHECK ===")
    # Replicate the condition from fieldDisplayUtils.ts line 1467
    if event.equipment_type_structured:
        print("✅ Condition 'if (event.equipment_type_structured)' would be TRUE")
        print(f"🎯 Would display: Equipment Type = {event.equipment_type_structured}")
    else:
        print("❌ Condition 'if (event.equipment_type_structured)' would be FALSE")
        print("🚨 This is why Equipment Type field is not showing!")

except EquipmentEvent.DoesNotExist:
    print("❌ Event 114 not found")
except Exception as e:
    print(f"❌ Error: {e}")
