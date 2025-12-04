#!/usr/bin/env python
import os
import sys

import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
django.setup()

from carbon.models import CarbonEntry
from company.models import Establishment


def analyze_establishment_events():
    # Get establishment 20
    establishment = Establishment.objects.get(id=20)
    print(f"Establishment: {establishment.name}")

    # Get all carbon entries for establishment 20
    carbon_entries = CarbonEntry.objects.filter(establishment_id=20).order_by("created_at")
    print(f"Total entries: {carbon_entries.count()}")

    # Agricultural categories from frontend
    fertilizer_keywords = [
        "fe event",
        "fertilizer",
        "chemical application",
        "anhydrous ammonia",
        "synthetic fertilizer",
    ]
    irrigation_keywords = ["ir event", "irrigation", "water"]
    pesticide_keywords = ["pe event", "pesticide", "herbicide", "insecticide", "fungicide"]
    soil_keywords = ["soil preparation", "tillage", "planting", "seeding", "cover crop"]
    harvest_keywords = ["harvest", "picking", "processing"]
    transport_keywords = ["transport", "shipping", "delivery"]

    categorized_ids = set()
    uncategorized_entries = []

    print("\n=== DETAILED ANALYSIS OF ALL ENTRIES ===")
    for i, entry in enumerate(carbon_entries, 1):
        description = entry.description.lower()
        category = "UNCATEGORIZED"

        if any(keyword in description for keyword in fertilizer_keywords):
            category = "Fertilizer Application"
            categorized_ids.add(entry.id)
        elif any(keyword in description for keyword in irrigation_keywords):
            category = "Irrigation Management"
            categorized_ids.add(entry.id)
        elif any(keyword in description for keyword in pesticide_keywords):
            category = "Pest Management"
            categorized_ids.add(entry.id)
        elif any(keyword in description for keyword in soil_keywords):
            category = "Soil Health & Preparation"
            categorized_ids.add(entry.id)
        elif any(keyword in description for keyword in harvest_keywords):
            category = "Harvest & Processing"
            categorized_ids.add(entry.id)
        elif any(keyword in description for keyword in transport_keywords):
            category = "Transportation"
            categorized_ids.add(entry.id)
        else:
            uncategorized_entries.append(entry)

        print(f"{i:2d}. [{category:25s}] {entry.description}")
        print(f'    Type: {entry.type}, Amount: {entry.amount}, Date: {entry.timestamp.strftime("%Y-%m-%d")}')

    print(f"\nCATEGORIZATION SUMMARY:")
    print(f"Categorized: {len(categorized_ids)} entries")
    print(f"Uncategorized: {len(uncategorized_entries)} entries")

    print(f"\n=== UNCATEGORIZED ENTRIES ANALYSIS ===")
    offset_entries = []
    emission_entries = []

    for entry in uncategorized_entries:
        print(f"- {entry.description}")
        print(f"  Type: {entry.type}, Amount: {entry.amount}")

        if entry.type == "offset":
            offset_entries.append(entry)
        elif entry.type == "emission":
            emission_entries.append(entry)
        print()

    print(f"UNCATEGORIZED BREAKDOWN:")
    print(f"- Offset entries: {len(offset_entries)}")
    print(f"- Emission entries: {len(emission_entries)}")

    # Suggest new categories
    print(f"\n=== SUGGESTED NEW CATEGORIES ===")

    # Look for patterns in uncategorized entries
    auto_calc_patterns = [entry for entry in uncategorized_entries if "auto-calculated" in entry.description.lower()]
    cover_crop_patterns = [entry for entry in uncategorized_entries if "cover crop" in entry.description.lower()]
    packaging_patterns = [entry for entry in uncategorized_entries if "packaging" in entry.description.lower()]
    soil_management_patterns = [
        entry for entry in uncategorized_entries if "soilmanagementevent" in entry.description.lower()
    ]
    pest_management_patterns = [
        entry for entry in uncategorized_entries if "pestmanagementevent" in entry.description.lower()
    ]

    if cover_crop_patterns:
        print(f"1. CARBON SEQUESTRATION ACTIVITIES ({len(cover_crop_patterns)} entries)")
        print("   - Cover crop carbon sequestration")
        print("   - Soil carbon storage practices")

    if soil_management_patterns:
        print(f"2. SOIL MANAGEMENT PRACTICES ({len(soil_management_patterns)} entries)")
        print("   - Auto-calculated soil management impacts")
        print("   - Soil health improvements")

    if pest_management_patterns:
        print(f"3. INTEGRATED PEST MANAGEMENT ({len(pest_management_patterns)} entries)")
        print("   - Auto-calculated pest management impacts")
        print("   - Biological pest control")

    if packaging_patterns:
        print(f"4. PACKAGING & MATERIALS ({len(packaging_patterns)} entries)")
        print("   - NOTE: This should NOT exist for farm establishments!")
        print("   - Suggests data integrity issue")

    print(f"\nRECOMMENDATIONS:")
    print('1. Add "Carbon Sequestration" category for cover crop and soil carbon storage')
    print('2. Add "Sustainability Practices" category for auto-calculated offsets')
    print("3. Investigate packaging entries - farms should not have packaging activities")
    print('4. Consider "Other Farm Activities" catch-all for remaining legitimate entries')


if __name__ == "__main__":
    analyze_establishment_events()
