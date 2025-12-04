#!/usr/bin/env python3
"""
Create a comprehensive soil management event to test enhanced display
"""
import json
import os
import sys

import django

# Setup Django
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from company.models import Company, Farm, Parcel
from history.models import SoilManagementEvent
from product.models import Production
from users.models import User


def create_enhanced_soil_event():
    """Create a comprehensive soil management event with all enhanced fields"""

    # Get required objects
    try:
        user = User.objects.get(email="oscar+evento@trazo.io")
        company = Company.objects.get(id=18)
        farm = Farm.objects.get(id=47)
        parcel = Parcel.objects.get(id=106)
        production = Production.objects.filter(parcel=parcel, status="ongoing").first()

        if not production:
            print("❌ No ongoing production found")
            return None

        print(f"✅ Found production: {production.name} (ID: {production.id})")

    except Exception as e:
        print(f"❌ Error finding required objects: {e}")
        return None

    try:
        # Create comprehensive soil management event with all enhanced fields
        event_data = {
            "name": "Enhanced Soil Analysis",
            "type": "Soil Testing",  # Will map to ST
            "description": "Comprehensive soil management event testing enhanced field display in Current Production cards",
            # Enhanced immediate display fields
            "area": 3.5,  # Will show as "Area Managed: 3.5 ha"
            "area_unit": "ha",
            "depth": 25,  # Will show as "Working Depth: 25 cm"
            "depth_unit": "cm",
            # Enhanced secondary display fields
            "area_covered": 3.2,  # Will show as "Area Covered: 3.2 hectares"
            "fuel_consumed": 4.8,  # Will show as "Fuel Consumed: 4.8 L"
            "fuel_unit": "L",
            "equipment_hours": 2.5,  # Will show as "Equipment Hours: 2.5 hours"
            "transportation_distance": 12,  # Will show as "Transportation Distance: 12 km"
            "transportation_unit": "km",
            # Soil properties
            "soil_ph": 6.8,
            "organic_matter_percentage": 3.2,
            "soil_texture": "Loamy sand",
            "soil_moisture": "Optimal",
            # Environmental conditions
            "weather_conditions": "Clear, mild temperature",
            "temperature_range": "18-22°C",
            "equipment_used": "Soil auger, pH meter, moisture probe",
            # Notes
            "observation": "Enhanced soil management event with comprehensive operational data for testing improved display in Current Production cards",
        }

        # Create the event
        soil_event = SoilManagementEvent.objects.create(
            company=company,
            farm=farm,
            parcel=parcel,
            production=production,
            user=user,
            date="2025-11-10T15:30:00Z",
            **event_data,
        )

        print(f"\n🎉 Successfully created enhanced soil management event!")
        print(f"📋 Event ID: {soil_event.id}")
        print(f"📝 Name: {soil_event.name}")
        print(f"📏 Area Managed: {soil_event.area} {soil_event.area_unit}")
        print(f"🔍 Working Depth: {soil_event.depth} {soil_event.depth_unit}")
        print(f"⛽ Fuel Consumed: {soil_event.fuel_consumed} {soil_event.fuel_unit}")
        print(f"🕐 Equipment Hours: {soil_event.equipment_hours} hours")
        print(f"🚛 Transportation: {soil_event.transportation_distance} {soil_event.transportation_unit}")
        print(f"🌱 Soil pH: {soil_event.soil_ph}")
        print(f"\n✨ This event will now show comprehensive operational data in Current Production cards!")

        return soil_event

    except Exception as e:
        print(f"❌ Error creating soil management event: {e}")
        return None


if __name__ == "__main__":
    create_enhanced_soil_event()
