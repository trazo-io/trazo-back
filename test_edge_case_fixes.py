#!/usr/bin/env python3

import os
import sys
from decimal import Decimal

import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trazo.settings.dev")
django.setup()

from carbon.services.event_carbon_calculator import EventCarbonCalculator


class MockWeatherEvent:
    def __init__(self, event_type, **kwargs):
        self.type = event_type
        for key, value in kwargs.items():
            setattr(self, key, value)


# Test the specific edge cases that were failing
calculator = EventCarbonCalculator()

print("=" * 60)
print("TESTING EDGE CASE FIXES")
print("=" * 60)

# Test 1: Frost with extreme high temperature
print("\n🧪 TEST: Frost: Impossible high temp (150°F)")
event = MockWeatherEvent("FR", lower_temperature="150", way_of_protection="heaters")
result = calculator.calculate_weather_event_impact(event)
co2e = result.get("co2e", 0)
data_sources = result.get("data_sources", [])
breakdown = result.get("breakdown", {})

print(f"   CO2e: {co2e} kg")
print(f"   Data Sources: {len(data_sources)} sources")
for source in data_sources:
    print(f"     - {source}")
print(f"   Has Breakdown: {bool(breakdown)}")
print(f"   Method: {result.get('calculation_method', 'unknown')}")

if data_sources and breakdown:
    print("   ✅ FIXED - Now has data sources and breakdown")
else:
    print("   ❌ STILL BROKEN - Missing data sources or breakdown")

# Test 2: Frost with extreme low temperature
print("\n🧪 TEST: Frost: Negative temperature (-50°F)")
event = MockWeatherEvent("FR", lower_temperature="-50", way_of_protection="heaters")
result = calculator.calculate_weather_event_impact(event)
co2e = result.get("co2e", 0)
data_sources = result.get("data_sources", [])
breakdown = result.get("breakdown", {})

print(f"   CO2e: {co2e} kg")
print(f"   Data Sources: {len(data_sources)} sources")
for source in data_sources:
    print(f"     - {source}")
print(f"   Has Breakdown: {bool(breakdown)}")
print(f"   Method: {result.get('calculation_method', 'unknown')}")

if data_sources and breakdown:
    print("   ✅ FIXED - Now has data sources and breakdown")
else:
    print("   ❌ STILL BROKEN - Missing data sources or breakdown")

# Test 3: Normal case to verify we didn't break anything
print("\n🧪 TEST: Frost: Normal case (28°F)")
event = MockWeatherEvent("FR", lower_temperature="28", way_of_protection="heaters")
result = calculator.calculate_weather_event_impact(event)
co2e = result.get("co2e", 0)
data_sources = result.get("data_sources", [])

print(f"   CO2e: {co2e} kg")
print(f"   Data Sources: {len(data_sources)} sources")
print(f"   Method: {result.get('calculation_method', 'unknown')}")

if co2e > 0 and data_sources and result.get("calculation_method") == "verified_epa_factors":
    print("   ✅ NORMAL CASE STILL WORKING")
else:
    print("   ❌ NORMAL CASE BROKEN")

print("\n" + "=" * 60)
print("EDGE CASE FIX TEST COMPLETE")
print("=" * 60)
