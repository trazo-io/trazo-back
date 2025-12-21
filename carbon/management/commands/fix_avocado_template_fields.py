"""
Management command to fix Avocados template with proper backend_event_fields.

This fixes the issue where template events have empty backend_event_fields,
causing events to be created with empty/missing values.

Agricultural defaults are based on:
- Conventional avocado farming best practices
- EPA/USDA verified emission factors
- California/Mexico avocado production standards
"""

from django.core.management.base import BaseCommand

from carbon.models import EventTemplate, ProductionTemplate


class Command(BaseCommand):
    help = "Fix Avocados template with proper backend_event_fields data"

    def handle(self, *args, **options):
        self.stdout.write("Fixing Avocados template backend_event_fields...")

        # Find Avocados templates
        avocado_templates = ProductionTemplate.objects.filter(
            name__icontains="avocado"
        )

        if not avocado_templates.exists():
            self.stdout.write(self.style.ERROR("No Avocados templates found!"))
            return

        # Smart agricultural defaults for avocado farming events
        # 🔧 FIX: Store numeric values separately from units for frontend form compatibility
        # Frontend expects: volume (numeric) + volume_unit (string)
        # NOT combined strings like "400 kg/ha"
        event_field_mappings = {
            # Fertilization events
            "fertilization": {
                "backend_event_fields": {
                    "type": "FE",
                    "commercial_name": "Avocado Special NPK 8-3-9",
                    "volume": 400,  # Numeric value
                    "volume_unit": "kg/ha",  # Separate unit
                    "way_of_application": "broadcast",
                    "time_period": "spring",
                    "nitrogen_percentage": 8.0,
                    "phosphorus_percentage": 3.0,
                    "potassium_percentage": 9.0,
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 6.0,
                    "weather_conditions": "dry",
                    "target_pest_disease": "Spring growth nutrition",
                    "organic_approved": False,
                },
            },
            "spring fertilization": {
                "backend_event_fields": {
                    "type": "FE",
                    "commercial_name": "Avocado Special NPK 8-3-9 + 2MgO",
                    "volume": 400,  # Numeric value
                    "volume_unit": "kg/ha",  # Separate unit
                    "way_of_application": "broadcast",
                    "time_period": "spring",
                    "nitrogen_percentage": 8.0,
                    "phosphorus_percentage": 3.0,
                    "potassium_percentage": 9.0,
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 6.0,
                    "weather_conditions": "dry",
                    "target_pest_disease": "Spring flush nutrition",
                    "organic_approved": False,
                },
            },
            # Irrigation events
            "irrigation": {
                "backend_event_fields": {
                    "type": "IR",
                    "observation": "Drip irrigation cycle for avocados",
                    "area_covered": 8.0,
                    "area_unit": "ha",
                    "irrigation_method": "drip",
                    "water_amount_gallons": 15000,
                    "fuel_consumed": 4.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                },
            },
            "irrigation management": {
                "backend_event_fields": {
                    "type": "IR",
                    "observation": "Precision drip irrigation with soil moisture sensors",
                    "area_covered": 8.0,
                    "area_unit": "ha",
                    "irrigation_method": "drip",
                    "water_amount_gallons": 15000,
                    "fuel_consumed": 4.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                },
            },
            # Pest control events
            "pest control": {
                "backend_event_fields": {
                    "type": "PE",
                    "commercial_name": "Movento (Spirotetramat 24%)",
                    "volume": 600,  # Numeric value
                    "volume_unit": "L/ha",  # Separate unit
                    "way_of_application": "spray",
                    "time_period": "spring",
                    "chemical_subtype": "insecticide",
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 3.5,
                    "weather_conditions": "calm",
                    "target_pest_disease": "Avocado thrips (Scirtothrips perseae)",
                    "organic_approved": False,
                    "buffer_zone": 30,
                },
            },
            "pest and disease monitoring": {
                "backend_event_fields": {
                    "type": "SC",
                    "pest_type": "thrips",
                    "severity_level": "low",
                    "commercial_name": "IPM Monitoring Program",
                    "observation": "Monthly pest and disease scouting",
                    "beneficial_insects_used": "yes",
                    "chemical_free_period_days": 30,
                    "ipm_strategy": "integrated_pest_management",
                },
            },
            # Pruning events
            "pruning": {
                "backend_event_fields": {
                    "type": "PR",
                    "observation": "Winter structural pruning for tree health",
                    "area_covered": 8.0,
                    "area_unit": "ha",
                    "fuel_consumed": 8.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 12.0,
                },
            },
            # Harvest events
            "harvest": {
                "backend_event_fields": {
                    "type": "HA",
                    "observation": "Hand-picking mature avocados at optimal oil content",
                    "area_covered": 8.0,
                    "area_unit": "ha",
                    "yield_quantity": 12.0,
                    "yield_unit": "tons",
                    "fuel_consumed": 15.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 16.0,
                },
            },
            # Fungicide events (for anthracnose/root rot)
            "disease control": {
                "backend_event_fields": {
                    "type": "FU",
                    "commercial_name": "Copper Hydroxide 77WP",
                    "volume": 500,  # Numeric value
                    "volume_unit": "L/ha",  # Separate unit
                    "way_of_application": "foliar_spray",
                    "time_period": "spring",
                    "chemical_subtype": "fungicide",
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 3.5,
                    "weather_conditions": "dry",
                    "target_pest_disease": "Anthracnose (Colletotrichum gloeosporioides)",
                    "organic_approved": True,
                    "buffer_zone": 30,
                },
            },
            # Root rot prevention
            "root rot prevention": {
                "backend_event_fields": {
                    "type": "FU",
                    "commercial_name": "Aliette WDG (Fosetyl-aluminum 80%)",
                    "volume": 800,  # Numeric value
                    "volume_unit": "L/ha",  # Separate unit
                    "way_of_application": "soil_drench",
                    "time_period": "spring",
                    "chemical_subtype": "fungicide",
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 5.0,
                    "weather_conditions": "before_irrigation",
                    "target_pest_disease": "Phytophthora root rot",
                    "organic_approved": False,
                },
            },
            # Soil management
            "soil management": {
                "backend_event_fields": {
                    "type": "ST",
                    "observation": "Soil health maintenance and mulching",
                    "area_covered": 8.0,
                    "area_unit": "ha",
                    "working_depth": 15,
                    "depth_unit": "cm",
                    "soil_texture": "loam",
                    "soil_ph": 6.5,
                    "organic_matter": 4.0,
                    "fuel_consumed": 10.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                },
            },
        }

        updated_count = 0
        for template in avocado_templates:
            self.stdout.write(f"Processing template: {template.name} (ID: {template.id})")

            events = EventTemplate.objects.filter(production_template=template)
            for event in events:
                event_name_lower = event.name.lower()
                event_type_lower = event.event_type.lower()

                # Find matching field mapping
                mapping = None

                # First try exact name match
                if event_name_lower in event_field_mappings:
                    mapping = event_field_mappings[event_name_lower]
                # Then try event type match
                elif event_type_lower in event_field_mappings:
                    mapping = event_field_mappings[event_type_lower]
                # Try partial matches
                else:
                    for key, value in event_field_mappings.items():
                        if key in event_name_lower or event_name_lower in key:
                            mapping = value
                            break

                if mapping and not event.backend_event_fields:
                    event.backend_event_fields = mapping["backend_event_fields"]
                    event.save(update_fields=["backend_event_fields"])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Updated: {event.name} with {len(mapping['backend_event_fields'])} fields"
                        )
                    )
                    updated_count += 1
                elif event.backend_event_fields:
                    self.stdout.write(f"  Skipped: {event.name} (already has fields)")
                else:
                    self.stdout.write(
                        self.style.WARNING(f"  No mapping for: {event.name} ({event.event_type})")
                    )

        self.stdout.write(
            self.style.SUCCESS(f"\nDone! Updated {updated_count} event templates with backend_event_fields")
        )
