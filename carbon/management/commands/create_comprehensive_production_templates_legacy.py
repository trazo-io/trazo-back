from django.core.management.base import BaseCommand
from django.db import transaction

from carbon.models import CropType, EventTemplate, ProductionTemplate


class Command(BaseCommand):
    help = "Create comprehensive production templates with realistic agricultural practices for all 16 crop types"

    def handle(self, *args, **options):
        """
        Create production templates and event templates for all crop types
        Based on USDA agricultural practices and real farming operations
        """

        with transaction.atomic():
            self.create_production_templates()

    def create_production_templates(self):
        """Create production templates and associated event templates for each crop type"""

        # Get all active crop types
        crop_types = CropType.objects.filter(is_active=True)

        if not crop_types.exists():
            self.stdout.write(
                self.style.ERROR("No crop types found. Please run populate_usda_crop_types command first.")
            )
            return

        created_templates = 0
        created_events = 0

        for crop_type in crop_types:
            # Create conventional production template
            template_data = self.get_template_data(crop_type)

            template, created = ProductionTemplate.objects.get_or_create(
                crop_type=crop_type, slug=f"{crop_type.slug}_conventional", defaults=template_data
            )

            if created:
                created_templates += 1
                self.stdout.write(f"✅ Created template: {template.name}")

                # Create event templates for this production template
                events_data = self.get_events_data(crop_type)
                for event_data in events_data:
                    event_data["production_template"] = template
                    event, event_created = EventTemplate.objects.get_or_create(
                        production_template=template, name=event_data["name"], defaults=event_data
                    )
                    if event_created:
                        created_events += 1

            else:
                self.stdout.write(f"🔄 Template already exists: {template.name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n🎉 Production Templates Creation Complete!"
                f"\n📊 Created: {created_templates} production templates"
                f"\n📅 Created: {created_events} event templates"
                f"\n\n✅ All crop types now have comprehensive production templates!"
            )
        )

    def get_template_data(self, crop_type):
        """Get production template data based on crop type"""

        base_data = {
            "name": f"{crop_type.name} - Conventional Production",
            "farming_approach": "conventional",
            "description": f"Standard conventional production practices for {crop_type.name.lower()}. Includes all essential agricultural events from land preparation through harvest.",
            "complexity_level": "intermediate",
            "estimated_setup_time": 8,
            "projected_emissions_reduction": 15.0,
            "projected_cost_change": -5.0,
            "projected_yield_impact": 0.0,
            "premium_pricing_potential": crop_type.sustainable_premium,
            "market_demand": "high",
            "usage_count": 0,
            "success_rate": 85.0,
            "usda_reviewed": True,
            "compliance_notes": f"Based on USDA best practices for {crop_type.name.lower()} production",
            "is_active": True,
        }

        return base_data

    def get_events_data(self, crop_type):
        """Get event templates data based on crop type and agricultural practices"""

        # Base events that apply to most crops
        base_events = []

        # Customize events based on crop category
        if crop_type.category in ["grain", "oilseed"]:
            base_events = self.get_grain_events(crop_type)
        elif crop_type.category == "vegetable":
            base_events = self.get_vegetable_events(crop_type)
        elif crop_type.category in ["tree_fruit", "tree_nut"]:
            base_events = self.get_tree_crop_events(crop_type)
        elif crop_type.category == "berry":
            base_events = self.get_berry_events(crop_type)
        else:  # other (cotton)
            base_events = self.get_other_crop_events(crop_type)

        return base_events

    def get_grain_events(self, crop_type):
        """Events for grain crops (corn, wheat, soybeans, rice)"""

        events = [
            {
                "name": "Land Preparation",
                "event_type": "soil_management",
                "description": "Field preparation including tillage and soil conditioning",
                "timing": "March - April",
                "frequency": "annual",
                "carbon_category": "medium",
                "cost_estimate": 85.0,
                    "carbon_impact": 35.0,
                    "carbon_category": "low",
                "labor_hours": 3.0,
                "typical_duration": "1-2 days",
                "efficiency_tips": "Consider no-till practices to reduce fuel consumption by 35%",
                "sustainability_score": 6,
                "qr_visibility": "medium",
                "consumer_message": "Sustainable soil preparation practices",
                "backend_event_type": 5,  # 5=Soil
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 1,
                "backend_event_fields": {
                    "type": "ST",
                    "observation": "Land preparation and soil conditioning",
                    "area_covered": 10.0,
                    "area_unit": "ha",
                    "working_depth": 20,
                    "depth_unit": "cm",
                    "soil_texture": None,
                    "soil_moisture": "moderate",
                    "fuel_consumed": 18.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 3.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Planting",
                "event_type": "planting",
                "description": "Seed planting with appropriate spacing and depth",
                "timing": "April - May",
                "frequency": "annual",
                "carbon_category": "low",
                "cost_estimate": 120.0,
                    "carbon_impact": 65.0,
                    "carbon_category": "medium",
                "labor_hours": 2.0,
                "typical_duration": "1-2 days",
                "efficiency_tips": "Use precision planting for optimal seed placement",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Precision planting for optimal growth",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 2,
                "backend_event_fields": {
                    "type": "PL",
                    "observation": "Precision seed planting operation",
                    "area_covered": 10.0,
                    "area_unit": "ha",
                    "seeds_source": "commercial",
                    "fuel_consumed": 8.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 2.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Fertilizer Application",
                "event_type": "fertilization",
                "description": "Application of nitrogen, phosphorus, and potassium fertilizers",
                "timing": "May - June",
                "frequency": "seasonal",
                "carbon_category": "high",
                "cost_estimate": 250.0,
                    "carbon_impact": 125.0,
                    "carbon_category": "high",
                "labor_hours": 2.5,
                "typical_duration": "4-6 hours",
                "efficiency_tips": "Soil testing can reduce fertilizer needs by 20-30%",
                "sustainability_score": 6,
                "qr_visibility": "high",
                "consumer_message": "Precision nutrient management for sustainable growth",
                "backend_event_type": 1,  # 1=Chemical
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 3,
                "backend_event_fields": {
                    "type": "FE",
                    "commercial_name": "NPK Fertilizer 16-16-16",
                    "volume": 250,
                    "volume_unit": "kg/ha",
                    "way_of_application": "broadcast",
                    "time_period": "spring",
                    "chemical_subtype": "synthetic_fertilizer",
                    "nitrogen_percentage": 16.0,
                    "phosphorus_percentage": 16.0,
                    "potassium_percentage": 16.0,
                    "application_method_structured": "broadcast",
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 6.0,
                    "application_fuel_unit": "L",
                    "organic_approved": "no",
                },
            },
            {
                "name": "Pest Management",
                "event_type": "pest_control",
                "description": "Integrated pest management for vegetable crops",
                "timing": "June - July",
                "frequency": "as_needed",
                "carbon_category": "medium",
                "cost_estimate": 95.0,
                "carbon_impact": 55.0,
                "labor_hours": 2.0,
                "typical_duration": "3-4 hours",
                "efficiency_tips": "IPM practices can reduce pesticide use by 40%",
                "sustainability_score": 7,
                "qr_visibility": "high",
                "consumer_message": "Responsible pest management practices",
                "backend_event_type": 6,  # 6=Pest (PestManagementEvent)
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 4,
                "backend_event_fields": {
                    # CORRECT: PestManagementEvent fields
                    "type": "SC",  # SC=Scouting (valid PestManagementEvent type)
                    "pest_species": "Aphids, Caterpillars, Whiteflies",
                    "pest_pressure_level": "medium",
                    "beneficial_species": "Ladybugs, Parasitic wasps",
                    "release_quantity": "",
                    "ipm_strategy": "Integrated pest management with regular scouting and threshold-based interventions",
                    "beneficial_insects_used": "no",
                    "chemical_free_period_days": None,
                    "action_threshold_met": False,
                    "extra_data": {
                        "field_area_hectares": 5.0,
                        "travel_distance_km": 1.5,
                        "time_spent_hours": 2.0,
                        "crop_growth_stage": "vegetative",
                    },
                },
            },
            {
                "name": "Irrigation Management",
                "event_type": "irrigation",
                "description": "Water application based on crop needs and soil moisture",
                "timing": "June - August",
                "frequency": "weekly",
                "carbon_category": "medium",
                "cost_estimate": 120.0,
                    "carbon_impact": 78.0,
                    "carbon_category": "medium",
                "labor_hours": 1.5,
                "typical_duration": "2-3 hours setup",
                "efficiency_tips": "Smart irrigation controllers can save 25% energy",
                "sustainability_score": 8,
                "qr_visibility": "medium",
                "consumer_message": "Efficient water management systems",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 5,
                "backend_event_fields": {
                    "type": "IR",
                    "observation": "Field irrigation cycle",
                    "area_covered": 10.0,
                    "area_unit": "ha",
                    "irrigation_method": "flood",
                    "irrigation_depth": 2.5,
                    "irrigation_depth_unit": "inches",
                    "water_source": "well_groundwater",
                    "fuel_consumed": 15.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Harvest",
                "event_type": "harvest",
                "description": "Mechanical harvest and grain handling",
                "timing": "September - October",
                "frequency": "annual",
                "carbon_category": "medium",
                "cost_estimate": 180.0,
                    "carbon_impact": 95.0,
                    "carbon_category": "medium",
                "labor_hours": 4.0,
                "typical_duration": "2-3 days",
                "efficiency_tips": "Optimize harvest timing for maximum yield and quality",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Efficient harvest practices",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 6,
                "backend_event_fields": {
                    "type": "HA",
                    "observation": "Mechanical grain harvest",
                    "area_covered": 10.0,
                    "area_unit": "ha",
                    "yield_quantity": 10.0,
                    "yield_unit": "tons",
                    "fuel_consumed": 12.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 4.0,
                    "production_efficiency": "normal",
                },
            },
        ]

        # Add crop-specific events
        if crop_type.slug == "rice":
            events.append(
                {
                    "name": "Field Flooding",
                    "event_type": "irrigation",
                    "description": "Controlled flooding of rice fields",
                    "timing": "May - June",
                    "frequency": "annual",
                    "carbon_category": "high",
                    "cost_estimate": 150.0,
                    "carbon_impact": 78.0,
                    "carbon_category": "medium",
                    "labor_hours": 2.0,
                    "typical_duration": "1 day",
                    "efficiency_tips": "Alternate wetting and drying can reduce methane by 30%",
                    "sustainability_score": 6,
                    "qr_visibility": "high",
                    "consumer_message": "Water-efficient rice production",
                    "backend_event_type": 2,  # 2=Production
                    "is_default_enabled": True,
                    "is_required": True,
                    "order_sequence": 3,
                    "backend_event_fields": {
                        "type": "IR",
                        "observation": "Rice field flooding operation",
                        "area_covered": 10.0,
                        "area_unit": "ha",
                        "irrigation_method": "flood",
                        "irrigation_depth": 4.0,
                        "irrigation_depth_unit": "inches",
                        "water_source": "well_groundwater",
                        "fuel_consumed": 20.0,
                        "fuel_unit": "L",
                        "fuel_type": "diesel",
                        "production_efficiency": "normal",
                    },
                }
            )

        return events

    def get_vegetable_events(self, crop_type):
        """Events for vegetable crops (tomatoes, potatoes, lettuce, carrots, onions)"""

        events = [
            {
                "name": "Soil Preparation",
                "event_type": "soil_management",
                "description": "Intensive soil preparation including bed formation",
                "timing": "March - April",
                "frequency": "annual",
                "carbon_category": "medium",
                "cost_estimate": 120.0,
                    "carbon_impact": 35.0,
                    "carbon_category": "low",
                "labor_hours": 4.0,
                "typical_duration": "1-2 days",
                "efficiency_tips": "Cover crops can improve soil structure naturally",
                "sustainability_score": 7,
                "qr_visibility": "low",
                "consumer_message": "Sustainable soil management",
                "backend_event_type": 5,  # 5=Soil
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 1,
                "backend_event_fields": {
                    "type": "ST",
                    "observation": "Intensive soil preparation with bed formation",
                    "area_covered": 5.0,
                    "area_unit": "ha",
                    "working_depth": 25,
                    "depth_unit": "cm",
                    "soil_texture": None,
                    "soil_moisture": "moderate",
                    "fuel_consumed": 15.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 4.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Transplanting/Seeding",
                "event_type": "planting",
                "description": "Transplanting seedlings or direct seeding",
                "timing": "April - May",
                "frequency": "annual",
                "carbon_category": "low",
                "cost_estimate": 180.0,
                    "carbon_impact": 65.0,
                    "carbon_category": "medium",
                "labor_hours": 6.0,
                "typical_duration": "2-3 days",
                "efficiency_tips": "Precision spacing optimizes plant development",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Careful planting for optimal growth",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 2,
                "backend_event_fields": {
                    "type": "PL",
                    "observation": "Transplanting seedlings with precision spacing",
                    "area_covered": 5.0,
                    "area_unit": "ha",
                    "seeds_source": "commercial",
                    "fuel_consumed": 6.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 6.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Drip Irrigation Setup",
                "event_type": "irrigation",
                "description": "Installation and management of drip irrigation systems",
                "timing": "May",
                "frequency": "annual",
                "carbon_category": "low",
                "cost_estimate": 200.0,
                    "carbon_impact": 78.0,
                    "carbon_category": "medium",
                "labor_hours": 3.0,
                "typical_duration": "1 day",
                "efficiency_tips": "Drip systems can reduce water use by 40%",
                "sustainability_score": 9,
                "qr_visibility": "medium",
                "consumer_message": "Water-efficient irrigation technology",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 3,
                "backend_event_fields": {
                    "type": "IR",
                    "observation": "Drip irrigation system setup",
                    "area_covered": 5.0,
                    "area_unit": "ha",
                    "irrigation_method": "drip",
                    "irrigation_depth": 1.5,
                    "irrigation_depth_unit": "inches",
                    "water_source": "well_groundwater",
                    "fuel_consumed": 5.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Fertilizer Program",
                "event_type": "fertilization",
                "description": "Precision fertigation through drip system",
                "timing": "May - August",
                "frequency": "weekly",
                "carbon_category": "high",
                "cost_estimate": 320.0,
                    "carbon_impact": 125.0,
                    "carbon_category": "high",
                "labor_hours": 2.0,
                "typical_duration": "2-3 hours",
                "efficiency_tips": "Fertigation reduces nutrient runoff by 50%",
                "sustainability_score": 8,
                "qr_visibility": "high",
                "consumer_message": "Precision nutrition management",
                "backend_event_type": 1,  # 1=Chemical
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 4,
                "backend_event_fields": {
                    "type": "FE",
                    "commercial_name": "Balanced Fertilizer 12-12-12",
                    "volume": 150,
                    "volume_unit": "kg/ha",
                    "way_of_application": "fertigation",
                    "time_period": "growing_season",
                    "chemical_subtype": "synthetic_fertilizer",
                    "nitrogen_percentage": 12.0,
                    "phosphorus_percentage": 12.0,
                    "potassium_percentage": 12.0,
                    "application_method_structured": "fertigation",
                    "application_fuel_type": "none",
                    "application_fuel_consumed": 0.0,
                    "application_fuel_unit": "L",
                    "organic_approved": "no",
                },
            },
            {
                "name": "Integrated Pest Management",
                "event_type": "pest_control",
                "description": "IPM including beneficial insects and targeted treatments",
                "timing": "June - September",
                "frequency": "as_needed",
                "carbon_category": "medium",
                "cost_estimate": 150.0,
                "carbon_impact": 55.0,
                "labor_hours": 2.5,
                "typical_duration": "3-4 hours",
                "efficiency_tips": "Beneficial insects reduce pesticide needs by 60%",
                "sustainability_score": 9,
                "qr_visibility": "high",
                "consumer_message": "Natural pest control methods",
                "backend_event_type": 6,  # 6=Pest (PestManagementEvent)
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 5,
                "backend_event_fields": {
                    # CORRECT: PestManagementEvent fields
                    "type": "BR",  # BR=Beneficial Release (valid PestManagementEvent type)
                    "pest_species": "Aphids, Spider mites, Thrips",
                    "pest_pressure_level": "low",
                    "beneficial_species": "Ladybugs, Lacewings, Predatory mites",
                    "release_quantity": "1000 per hectare",
                    "ipm_strategy": "Organic IPM with beneficial insect releases and habitat management",
                    "beneficial_insects_used": "yes",
                    "chemical_free_period_days": 30,
                    "action_threshold_met": False,
                    "extra_data": {
                        "field_area_hectares": 5.0,
                        "travel_distance_km": 1.0,
                        "time_spent_hours": 2.5,
                        "crop_growth_stage": "flowering",
                    },
                },
            },
            {
                "name": "Harvest",
                "event_type": "harvest",
                "description": "Hand or mechanical harvest depending on crop",
                "timing": "July - October",
                "frequency": "seasonal",
                "carbon_category": "low",
                "cost_estimate": 280.0,
                    "carbon_impact": 95.0,
                    "carbon_category": "medium",
                "labor_hours": 8.0,
                "typical_duration": "3-5 days",
                "efficiency_tips": "Optimal timing maximizes quality and shelf life",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Fresh, quality harvest",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 6,
                "backend_event_fields": {
                    "type": "HA",
                    "observation": "Hand or mechanical vegetable harvest",
                    "area_covered": 5.0,
                    "area_unit": "ha",
                    "yield_quantity": 25.0,
                    "yield_unit": "tons",
                    "fuel_consumed": 8.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 8.0,
                    "production_efficiency": "normal",
                },
            },
        ]

        return events

    def get_tree_crop_events(self, crop_type):
        """Events for tree crops (citrus, apples, grapes, avocados, almonds)"""

        events = [
            {
                "name": "Winter Pruning",
                "event_type": "pruning",
                "description": "Dormant season pruning for tree structure and health",
                "timing": "December - February",
                "frequency": "annual",
                "carbon_category": "low",
                "cost_estimate": 180.0,
                    "carbon_impact": 45.0,
                    "carbon_category": "low",
                "labor_hours": 6.0,
                "typical_duration": "3-5 days",
                "efficiency_tips": "Proper pruning increases fruit quality and reduces disease",
                "sustainability_score": 9,
                "qr_visibility": "low",
                "consumer_message": "Expert tree care for healthy fruit",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 1,
                "backend_event_fields": {
                    "type": "PR",
                    "observation": "Winter pruning for tree structure",
                    "area_covered": 8.0,
                    "area_unit": "ha",
                    "fuel_consumed": 10.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 6.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Spring Fertilization",
                "event_type": "fertilization",
                "description": "Avocado-specific nutrition for spring growth and fruit development",
                "timing": "March - April",
                "frequency": "annual",
                "carbon_category": "medium",
                "cost_estimate": 220.0,
                "carbon_impact": 125.0,
                "labor_hours": 2.0,
                "typical_duration": "1-2 days",
                "efficiency_tips": "Soil testing optimizes nutrient application. Avocados need higher potassium for fruit quality.",
                "sustainability_score": 7,
                "qr_visibility": "medium",
                "consumer_message": "Specialized avocado nutrition for quality fruit",
                "backend_event_type": 1,  # 1=Chemical (ChemicalEvent)
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 2,
                "backend_event_fields": {
                    "type": "FE",
                    # AVOCADO-SPECIFIC: 8-3-9 ratio (higher K for fruit development)
                    "commercial_name": "Avocado Special NPK 8-3-9 + 2MgO",
                    "volume": 300,  # Increased for mature orchards (250-350 kg/ha)
                    "volume_unit": "kg/ha",
                    "way_of_application": "broadcast",
                    "time_period": "spring",
                    "chemical_subtype": "synthetic_fertilizer",
                    "nitrogen_percentage": 8.0,  # Moderate N for avocados
                    "phosphorus_percentage": 3.0,  # Lower P (avocados sensitive)
                    "potassium_percentage": 9.0,  # Higher K for fruit quality
                    "application_method_structured": "broadcast",
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 6.0,
                    "application_fuel_unit": "L",
                    "organic_approved": "no",
                    "target_pest_disease": "Spring flush nutrition",
                    "weather_conditions": "dry",  # Avoid wet conditions
                },
            },
            {
                "name": "Bloom Support",
                "event_type": "fertilization",
                "description": "Specialized nutrition during flowering period",
                "timing": "April - May",
                "frequency": "annual",
                "carbon_category": "low",
                "cost_estimate": 95.0,
                    "carbon_impact": 125.0,
                    "carbon_category": "high",
                "labor_hours": 1.5,
                "typical_duration": "1 day",
                "efficiency_tips": "Timing nutrition with bloom improves fruit set",
                "sustainability_score": 8,
                "qr_visibility": "medium",
                "consumer_message": "Supporting natural flowering process",
                "backend_event_type": 1,  # 1=Chemical
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 3,
                "backend_event_fields": {
                    "type": "FE",
                    "commercial_name": "Bloom booster fertilizer",
                    "volume": 100,
                    "volume_unit": "kg/ha",
                    "way_of_application": "spray",
                    "time_period": "spring",
                    "chemical_subtype": "synthetic_fertilizer",
                    "nitrogen_percentage": 5.0,
                    "phosphorus_percentage": 15.0,
                    "potassium_percentage": 10.0,
                    "application_method_structured": "spray",
                    "application_fuel_type": "none",
                    "application_fuel_consumed": 0.0,
                    "application_fuel_unit": "L",
                    "organic_approved": "no",
                },
            },
            {
                "name": "Irrigation Management",
                "event_type": "irrigation",
                "description": "Precision irrigation based on tree water needs",
                "timing": "April - October",
                "frequency": "weekly",
                "carbon_category": "medium",
                "cost_estimate": 180.0,
                    "carbon_impact": 78.0,
                    "carbon_category": "medium",
                "labor_hours": 2.0,
                "typical_duration": "2-3 hours",
                "efficiency_tips": "Micro-irrigation reduces water use by 30%",
                "sustainability_score": 9,
                "qr_visibility": "medium",
                "consumer_message": "Efficient water management",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 4,
                "backend_event_fields": {
                    "type": "IR",
                    "observation": "Drip irrigation for tree crops",
                    "area_covered": 8.0,
                    "area_unit": "ha",
                    "irrigation_method": "drip",
                    "irrigation_depth": 2.0,
                    "irrigation_depth_unit": "inches",
                    "water_source": "well_groundwater",
                    "fuel_consumed": 12.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Pest and Disease Management",
                "event_type": "pest_control",
                "description": "Integrated approach to pest and disease control for tree crops",
                "timing": "May - September",
                "frequency": "as_needed",
                "carbon_category": "medium",
                "cost_estimate": 160.0,
                "carbon_impact": 55.0,
                "labor_hours": 3.0,
                "typical_duration": "4-6 hours",
                "efficiency_tips": "IPM reduces chemical treatments by 50%",
                "sustainability_score": 8,
                "qr_visibility": "high",
                "consumer_message": "Responsible crop protection using beneficial insects",
                "backend_event_type": 6,  # 6=Pest (PestManagementEvent)
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 5,
                "backend_event_fields": {
                    # CORRECT: PestManagementEvent fields (not ChemicalEvent!)
                    "type": "IP",  # IP=IPM Implementation (valid PestManagementEvent type)
                    "pest_species": "Avocado thrips, Persea mite, Avocado lace bug",
                    "pest_pressure_level": "low",
                    "beneficial_species": "Predatory mites, Lacewings, Ladybugs",
                    "release_quantity": "500 per hectare",
                    "ipm_strategy": "Integrated pest management targeting avocado thrips and Phytophthora root rot with beneficial insects and selective treatments",
                    "beneficial_insects_used": "yes",
                    "chemical_free_period_days": 30,
                    "action_threshold_met": False,
                    "extra_data": {
                        "field_area_hectares": 8.0,
                        "travel_distance_km": 2.0,
                        "time_spent_hours": 3.0,
                        "crop_growth_stage": "vegetative",
                    },
                },
            },
            {
                "name": "Harvest",
                "event_type": "harvest",
                "description": "Careful harvest to maintain fruit quality",
                "timing": "August - November",
                "frequency": "annual",
                "carbon_category": "medium",
                "cost_estimate": 320.0,
                    "carbon_impact": 95.0,
                    "carbon_category": "medium",
                "labor_hours": 12.0,
                "typical_duration": "5-10 days",
                "efficiency_tips": "Optimal timing preserves fruit quality and shelf life",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Carefully harvested premium fruit",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 6,
                "backend_event_fields": {
                    "type": "HA",
                    "observation": "Careful fruit harvest for premium quality",
                    "area_covered": 8.0,
                    "area_unit": "ha",
                    "yield_quantity": 20.0,
                    "yield_unit": "tons",
                    "fuel_consumed": 8.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 12.0,
                    "production_efficiency": "normal",
                },
            },
        ]

        return events

    def get_berry_events(self, crop_type):
        """Events for berry crops (strawberries)"""

        events = [
            {
                "name": "Bed Preparation",
                "event_type": "soil_management",
                "description": "Raised bed formation and soil conditioning",
                "timing": "August - September",
                "frequency": "annual",
                "carbon_category": "medium",
                "cost_estimate": 180.0,
                    "carbon_impact": 35.0,
                    "carbon_category": "low",
                "labor_hours": 5.0,
                "typical_duration": "2-3 days",
                "efficiency_tips": "Proper bed formation improves drainage and root health",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Optimal growing conditions",
                "backend_event_type": 5,  # 5=Soil
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 1,
                "backend_event_fields": {
                    "type": "ST",
                    "observation": "Raised bed formation for strawberries",
                    "area_covered": 3.0,
                    "area_unit": "ha",
                    "working_depth": 30,
                    "depth_unit": "cm",
                    "soil_texture": None,
                    "soil_moisture": "moderate",
                    "fuel_consumed": 12.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 5.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Plant Installation",
                "event_type": "planting",
                "description": "Transplanting strawberry plants with precise spacing",
                "timing": "September - October",
                "frequency": "annual",
                "carbon_category": "low",
                "cost_estimate": 320.0,
                    "carbon_impact": 65.0,
                    "carbon_category": "medium",
                "labor_hours": 12.0,
                "typical_duration": "3-5 days",
                "efficiency_tips": "Proper spacing ensures optimal plant development",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Expert planting for premium berries",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 2,
                "backend_event_fields": {
                    "type": "PL",
                    "observation": "Transplanting strawberry plants",
                    "area_covered": 3.0,
                    "area_unit": "ha",
                    "seeds_source": "certified_organic",
                    "fuel_consumed": 4.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 12.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Fertigation System",
                "event_type": "fertilization",
                "description": "Precision nutrition through drip irrigation",
                "timing": "October - August",
                "frequency": "weekly",
                "carbon_category": "high",
                "cost_estimate": 450.0,
                    "carbon_impact": 125.0,
                    "carbon_category": "high",
                "labor_hours": 3.0,
                "typical_duration": "2-3 hours",
                "efficiency_tips": "Fertigation reduces nutrient waste by 60%",
                "sustainability_score": 9,
                "qr_visibility": "high",
                "consumer_message": "Precision nutrition for sweet berries",
                "backend_event_type": 1,  # 1=Chemical
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 3,
                "backend_event_fields": {
                    "type": "FE",
                    "commercial_name": "Balanced Fertilizer 10-10-10",
                    "volume": 120,
                    "volume_unit": "kg/ha",
                    "way_of_application": "fertigation",
                    "time_period": "growing_season",
                    "chemical_subtype": "synthetic_fertilizer",
                    "nitrogen_percentage": 10.0,
                    "phosphorus_percentage": 10.0,
                    "potassium_percentage": 10.0,
                    "application_method_structured": "fertigation",
                    "application_fuel_type": "none",
                    "application_fuel_consumed": 0.0,
                    "application_fuel_unit": "L",
                    "organic_approved": "no",
                },
            },
            {
                "name": "Beneficial Insect Release",
                "event_type": "pest_control",
                "description": "Release of beneficial insects for natural pest control",
                "timing": "March - September",
                "frequency": "monthly",
                "carbon_category": "low",
                "cost_estimate": 85.0,
                "carbon_impact": 55.0,
                "labor_hours": 1.0,
                "typical_duration": "1-2 hours",
                "efficiency_tips": "Beneficial insects reduce pesticide needs by 80%",
                "sustainability_score": 10,
                "qr_visibility": "high",
                "consumer_message": "Natural pest control for clean berries",
                "backend_event_type": 6,  # 6=Pest (PestManagementEvent)
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 4,
                "backend_event_fields": {
                    # CORRECT: PestManagementEvent fields
                    "type": "BR",  # BR=Beneficial Release (valid PestManagementEvent type)
                    "pest_species": "Spider mites, Aphids, Spotted wing drosophila",
                    "pest_pressure_level": "low",
                    "beneficial_species": "Predatory mites, Parasitic wasps, Ground beetles",
                    "release_quantity": "2000 per hectare monthly",
                    "ipm_strategy": "Year-round beneficial insect program for berry pest prevention with regular releases",
                    "beneficial_insects_used": "yes",
                    "chemical_free_period_days": 60,
                    "action_threshold_met": False,
                    "extra_data": {
                        "field_area_hectares": 2.0,
                        "travel_distance_km": 0.5,
                        "time_spent_hours": 1.0,
                        "crop_growth_stage": "fruiting",
                    },
                },
            },
            {
                "name": "Harvest",
                "event_type": "harvest",
                "description": "Hand harvest of ripe strawberries",
                "timing": "April - November",
                "frequency": "weekly",
                "carbon_category": "low",
                "cost_estimate": 650.0,
                    "carbon_impact": 95.0,
                    "carbon_category": "medium",
                "labor_hours": 20.0,
                "typical_duration": "3-4 days",
                "efficiency_tips": "Frequent harvest maintains berry quality",
                "sustainability_score": 9,
                "qr_visibility": "low",
                "consumer_message": "Hand-picked for perfect ripeness",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 5,
                "backend_event_fields": {
                    "type": "HA",
                    "observation": "Hand harvest of premium strawberries",
                    "area_covered": 3.0,
                    "area_unit": "ha",
                    "yield_quantity": 35.0,
                    "yield_unit": "tons",
                    "fuel_consumed": 0.0,
                    "fuel_unit": "L",
                    "fuel_type": "none",
                    "equipment_hours": 20.0,
                    "production_efficiency": "normal",
                },
            },
        ]

        return events

    def get_other_crop_events(self, crop_type):
        """Events for other crops (cotton)"""

        events = [
            {
                "name": "Land Preparation",
                "event_type": "soil_management",
                "description": "Field preparation and bed formation",
                "timing": "March - April",
                "frequency": "annual",
                "carbon_category": "medium",
                "cost_estimate": 95.0,
                    "carbon_impact": 35.0,
                    "carbon_category": "low",
                "labor_hours": 3.0,
                "typical_duration": "1-2 days",
                "efficiency_tips": "Conservation tillage reduces fuel consumption",
                "sustainability_score": 7,
                "qr_visibility": "low",
                "consumer_message": "Sustainable soil preparation",
                "backend_event_type": 5,  # 5=Soil
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 1,
                "backend_event_fields": {
                    "type": "ST",
                    "observation": "Field preparation and conditioning",
                    "area_covered": 12.0,
                    "area_unit": "ha",
                    "working_depth": 15,
                    "depth_unit": "cm",
                    "soil_texture": None,
                    "soil_moisture": "moderate",
                    "fuel_consumed": 20.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 3.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Planting",
                "event_type": "planting",
                "description": "Precision cotton seed planting",
                "timing": "April - May",
                "frequency": "annual",
                "carbon_category": "low",
                "cost_estimate": 120.0,
                    "carbon_impact": 65.0,
                    "carbon_category": "medium",
                "labor_hours": 2.0,
                "typical_duration": "1-2 days",
                "efficiency_tips": "Precision planting optimizes plant population",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Precision planting for quality fiber",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 2,
                "backend_event_fields": {
                    "type": "PL",
                    "observation": "Precision cotton seed planting",
                    "area_covered": 12.0,
                    "area_unit": "ha",
                    "seeds_source": "commercial",
                    "fuel_consumed": 10.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 2.0,
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Fertilization",
                "event_type": "fertilization",
                "description": "Balanced nutrition for cotton development",
                "timing": "May - June",
                "frequency": "seasonal",
                "carbon_category": "high",
                "cost_estimate": 280.0,
                    "carbon_impact": 125.0,
                    "carbon_category": "high",
                "labor_hours": 2.5,
                "typical_duration": "1 day",
                "efficiency_tips": "Variable rate application optimizes nutrient use",
                "sustainability_score": 7,
                "qr_visibility": "medium",
                "consumer_message": "Responsible nutrient management",
                "backend_event_type": 1,  # 1=Chemical
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 3,
                "backend_event_fields": {
                    "type": "FE",
                    "commercial_name": "High-Nitrogen Fertilizer 20-10-10",
                    "volume": 280,
                    "volume_unit": "kg/ha",
                    "way_of_application": "broadcast",
                    "time_period": "spring",
                    "chemical_subtype": "synthetic_fertilizer",
                    "nitrogen_percentage": 20.0,
                    "phosphorus_percentage": 10.0,
                    "potassium_percentage": 10.0,
                    "application_method_structured": "broadcast",
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 7.0,
                    "application_fuel_unit": "L",
                    "organic_approved": "no",
                },
            },
            {
                "name": "Irrigation Management",
                "event_type": "irrigation",
                "description": "Efficient water application for cotton",
                "timing": "June - August",
                "frequency": "weekly",
                "carbon_category": "medium",
                "cost_estimate": 150.0,
                    "carbon_impact": 78.0,
                    "carbon_category": "medium",
                "labor_hours": 2.0,
                "typical_duration": "2-3 hours",
                "efficiency_tips": "Precision irrigation reduces water use by 30%",
                "sustainability_score": 8,
                "qr_visibility": "medium",
                "consumer_message": "Water-efficient cotton production",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 4,
                "backend_event_fields": {
                    "type": "IR",
                    "observation": "Drip or furrow irrigation",
                    "area_covered": 12.0,
                    "area_unit": "ha",
                    "irrigation_method": "flood",
                    "irrigation_depth": 3.0,
                    "irrigation_depth_unit": "inches",
                    "water_source": "well_groundwater",
                    "fuel_consumed": 18.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "production_efficiency": "normal",
                },
            },
            {
                "name": "Integrated Pest Management",
                "event_type": "pest_control",
                "description": "IPM approach for cotton and grain pests",
                "timing": "June - September",
                "frequency": "as_needed",
                "carbon_category": "high",
                "cost_estimate": 180.0,
                "carbon_impact": 55.0,
                "labor_hours": 3.0,
                "typical_duration": "4-6 hours",
                "efficiency_tips": "IPM reduces pesticide applications by 40%",
                "sustainability_score": 8,
                "qr_visibility": "high",
                "consumer_message": "Responsible pest management",
                "backend_event_type": 6,  # 6=Pest (PestManagementEvent)
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": 5,
                "backend_event_fields": {
                    # CORRECT: PestManagementEvent fields
                    "type": "SC",  # SC=Scouting (valid PestManagementEvent type)
                    "pest_species": "Bollworm, Aphids, Spider mites",
                    "pest_pressure_level": "medium",
                    "beneficial_species": "Parasitic wasps, Ladybugs",
                    "release_quantity": "",
                    "ipm_strategy": "Integrated pest management with scouting and threshold-based selective treatments",
                    "beneficial_insects_used": "no",
                    "chemical_free_period_days": None,
                    "action_threshold_met": False,
                    "extra_data": {
                        "field_area_hectares": 12.0,
                        "travel_distance_km": 3.0,
                        "time_spent_hours": 3.0,
                        "crop_growth_stage": "flowering",
                    },
                },
            },
            {
                "name": "Harvest",
                "event_type": "harvest",
                "description": "Mechanical cotton harvest",
                "timing": "September - November",
                "frequency": "annual",
                "carbon_category": "medium",
                "cost_estimate": 220.0,
                    "carbon_impact": 95.0,
                    "carbon_category": "medium",
                "labor_hours": 4.0,
                "typical_duration": "3-5 days",
                "efficiency_tips": "Optimal timing maximizes fiber quality",
                "sustainability_score": 8,
                "qr_visibility": "low",
                "consumer_message": "Quality fiber harvest",
                "backend_event_type": 2,  # 2=Production
                "is_default_enabled": True,
                "is_required": True,
                "order_sequence": 6,
                "backend_event_fields": {
                    "type": "HA",
                    "observation": "Mechanical cotton harvest",
                    "area_covered": 12.0,
                    "area_unit": "ha",
                    "yield_quantity": 5.0,
                    "yield_unit": "tons",
                    "fuel_consumed": 15.0,
                    "fuel_unit": "L",
                    "fuel_type": "diesel",
                    "equipment_hours": 4.0,
                    "production_efficiency": "normal",
                },
            },
        ]

        return events
