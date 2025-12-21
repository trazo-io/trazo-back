from django.core.management.base import BaseCommand
from django.db import transaction

from carbon.models import CropType, EventTemplate, ProductionTemplate


class Command(BaseCommand):
    help = "Enhance production templates with equipment events for USDA-accurate carbon tracking"

    def add_arguments(self, parser):
        parser.add_argument(
            "--crop",
            type=str,
            help='Enhance specific crop (e.g., "Corn (Field)", "Soybeans")',
        )
        parser.add_argument(
            "--phase",
            type=str,
            choices=["1", "2", "all"],
            default="all",
            help="Phase 1: Major crops (Corn, Soybeans, Wheat, Hay/Alfalfa), Phase 2: All remaining crops",
        )

    def handle(self, *args, **options):
        """
        Enhance production templates with equipment events for accurate carbon tracking
        Brings templates to USDA compliance standards (800-1200 kg CO2e/ha)
        """

        self.stdout.write(self.style.SUCCESS("🚜 ENHANCING TEMPLATES WITH EQUIPMENT EVENTS"))
        self.stdout.write("=" * 60)

        with transaction.atomic():
            if options["crop"]:
                self.enhance_specific_crop(options["crop"])
            elif options["phase"] == "1":
                self.enhance_major_crops()
            elif options["phase"] == "2":
                self.enhance_remaining_crops()
            else:
                self.enhance_all_crops()

    def enhance_specific_crop(self, crop_name):
        """Enhance a specific crop template"""
        try:
            crop = CropType.objects.get(name=crop_name)
            template = ProductionTemplate.objects.get(crop_type=crop)

            self.stdout.write(f"🎯 Enhancing {crop_name}...")
            before_carbon = template.total_carbon_impact

            if crop_name == "Corn (Field)":
                self.add_corn_equipment_events(template)
            elif crop_name == "Soybeans":
                self.add_soybean_equipment_events(template)
            elif crop_name == "Wheat":
                self.add_wheat_equipment_events(template)
            elif crop_name == "Hay/Alfalfa":
                self.add_alfalfa_equipment_events(template)
            else:
                self.add_generic_equipment_events(template)

            template.refresh_from_db()
            after_carbon = template.total_carbon_impact

            self.stdout.write(
                f"✅ {crop_name}: {before_carbon} → {after_carbon} kg CO2e/ha"
                f" ({template.event_templates.count()} events)"
            )

        except CropType.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ Crop '{crop_name}' not found"))
        except ProductionTemplate.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ No template found for '{crop_name}'"))

    def enhance_major_crops(self):
        """Enhance the 4 major crops: Corn, Soybeans, Wheat, Hay/Alfalfa"""
        major_crops = ["Corn (Field)", "Soybeans", "Wheat", "Hay/Alfalfa"]

        self.stdout.write("🌾 PHASE 1: Enhancing Major Crops (275M acres)")

        total_improved = 0
        for crop_name in major_crops:
            try:
                crop = CropType.objects.get(name=crop_name)
                template = ProductionTemplate.objects.get(crop_type=crop)
                before_carbon = template.total_carbon_impact

                if crop_name == "Corn (Field)":
                    added = self.add_corn_equipment_events(template)
                elif crop_name == "Soybeans":
                    added = self.add_soybean_equipment_events(template)
                elif crop_name == "Wheat":
                    added = self.add_wheat_equipment_events(template)
                elif crop_name == "Hay/Alfalfa":
                    added = self.add_alfalfa_equipment_events(template)

                template.refresh_from_db()
                after_carbon = template.total_carbon_impact

                if added > 0:
                    total_improved += 1
                    status = "✅" if self.check_usda_compliance(crop_name, after_carbon) else "⚠️"
                    self.stdout.write(
                        f"{status} {crop_name:15}: {before_carbon:6.1f} → {after_carbon:6.1f} kg CO2e/ha (+{added} events)"
                    )

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Error with {crop_name}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\n🎉 Phase 1 Complete! Enhanced {total_improved}/4 major crops"))

    def enhance_all_crops(self):
        """Enhance all crop templates"""
        self.stdout.write("🌍 Enhancing ALL crop templates...")

        crops = CropType.objects.filter(is_active=True).order_by("name")
        enhanced_count = 0

        for crop in crops:
            try:
                template = ProductionTemplate.objects.get(crop_type=crop)
                before_carbon = template.total_carbon_impact

                # Add equipment events based on crop type
                if crop.name == "Corn (Field)":
                    added = self.add_corn_equipment_events(template)
                elif crop.name == "Soybeans":
                    added = self.add_soybean_equipment_events(template)
                elif crop.name == "Wheat":
                    added = self.add_wheat_equipment_events(template)
                elif crop.name == "Hay/Alfalfa":
                    added = self.add_alfalfa_equipment_events(template)
                else:
                    added = self.add_generic_equipment_events(template)

                if added > 0:
                    enhanced_count += 1
                    template.refresh_from_db()
                    after_carbon = template.total_carbon_impact
                    self.stdout.write(f"✅ {crop.name:20}: {after_carbon:6.1f} kg CO2e/ha (+{added} equipment events)")

            except ProductionTemplate.DoesNotExist:
                self.stdout.write(f"⚠️  No template for {crop.name}")

        self.stdout.write(self.style.SUCCESS(f"\n🎉 Enhancement Complete! Updated {enhanced_count} crop templates"))

    def add_corn_equipment_events(self, template):
        """Add equipment events specific to corn production"""

        equipment_events = [
            {
                "name": "Fall Tillage - Primary (Chisel Plow)",
                "event_type": "equipment",
                "description": "Primary tillage operation with chisel plow for residue management and soil preparation",
                "carbon_impact": 28.0,
                "carbon_category": "medium",
                "cost_estimate": 42.0,
                "labor_hours": 0.8,
                "timing": "October - November",
                "frequency": "annual",
                "typical_duration": "0.8 hours per hectare",
                "order_sequence": 1,
                "typical_amounts": {"fuel_liters_per_ha": 22, "tractor_hp": 180},
                "carbon_sources": ["diesel_fuel", "equipment_manufacturing"],
                "efficiency_tips": "Use GPS guidance to reduce overlap. Consider reduced tillage for carbon savings.",
                "sustainability_score": 6,
                "alternative_methods": ["no_till", "strip_till", "vertical_tillage"],
                "qr_visibility": "medium",
                "consumer_message": "Soil preparation for optimal corn growth using fuel-efficient equipment",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Fall Tillage - Primary (Chisel Plow)",
                    "equipment_type": "tractor_large",
                    "implement_type": "chisel_plow",
                    "fuel_consumed": 22.0,
                    "fuel_type": "diesel",
                    "fuel_unit": "L",
                    "equipment_hours": 0.8,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "329",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Spring Field Preparation (Disk Harrow)",
                "event_type": "equipment",
                "description": "Secondary tillage with disk harrow for seedbed preparation",
                "carbon_impact": 18.0,
                "carbon_category": "low",
                "cost_estimate": 28.0,
                "labor_hours": 0.6,
                "timing": "March - April",
                "frequency": "annual",
                "typical_duration": "0.6 hours per hectare",
                "order_sequence": 2,
                "typical_amounts": {"fuel_liters_per_ha": 14, "tractor_hp": 140},
                "carbon_sources": ["diesel_fuel", "equipment_wear"],
                "efficiency_tips": "Combine operations when possible. Use controlled traffic farming patterns.",
                "sustainability_score": 7,
                "alternative_methods": ["no_till_planting", "strip_till"],
                "qr_visibility": "low",
                "consumer_message": "Preparing optimal seedbed conditions for corn planting",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Spring Field Preparation (Disk Harrow)",
                    "equipment_type": "tractor_medium",
                    "implement_type": "disk_harrow",
                    "fuel_consumed": 14.0,
                    "fuel_type": "diesel",
                    "fuel_unit": "L",
                    "equipment_hours": 0.6,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "329",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Planting Equipment Operation (Tractor + Planter)",
                "event_type": "equipment",
                "description": "Precision corn planting with GPS-guided tractor and planter",
                "carbon_impact": 15.0,
                "carbon_category": "low",
                "cost_estimate": 35.0,
                "labor_hours": 0.5,
                "timing": "April - May",
                "frequency": "annual",
                "typical_duration": "0.5 hours per hectare",
                "order_sequence": 3,
                "typical_amounts": {"fuel_liters_per_ha": 12, "tractor_hp": 160},
                "carbon_sources": ["diesel_fuel", "hydraulic_systems"],
                "efficiency_tips": "Use variable rate planting. Maintain optimal speed for seed placement.",
                "sustainability_score": 8,
                "alternative_methods": ["no_till_planter", "reduced_speed_planting"],
                "qr_visibility": "medium",
                "consumer_message": "Precision planting technology for optimal corn emergence",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Planting Equipment Operation (Tractor + Planter)",
                    "equipment_type": "tractor_large",
                    "implement_type": "precision_planter",
                    "fuel_type": "diesel",
                    "fuel_consumed": 12.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.5,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
            {
                "name": "Sprayer Operations (Fertilizer & Pesticide Application)",
                "event_type": "equipment",
                "description": "Self-propelled sprayer for fertilizer and pesticide applications",
                "carbon_impact": 25.0,
                "carbon_category": "medium",
                "cost_estimate": 45.0,
                "labor_hours": 1.2,
                "timing": "May - August",
                "frequency": "seasonal",
                "typical_duration": "3-4 applications, 0.3 hours each",
                "order_sequence": 4,
                "typical_amounts": {"fuel_liters_per_ha": 20, "applications": 3},
                "carbon_sources": ["diesel_fuel", "hydraulic_pumps"],
                "efficiency_tips": "Use GPS section control to reduce overlap.",
                "sustainability_score": 6,
                "alternative_methods": ["precision_application", "variable_rate"],
                "qr_visibility": "high",
                "consumer_message": "Precision application ensures optimal crop protection",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Sprayer Operations (Fertilizer & Pesticide Application)",
                    "equipment_type": "sprayer_self_propelled",
                    "implement_type": "sprayer",
                    "fuel_type": "diesel",
                    "fuel_consumed": 20.0,
                    "fuel_unit": "L",
                    "equipment_hours": 1.2,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "590",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Combine Harvest Operation",
                "event_type": "equipment",
                "description": "Combine harvester operation with grain cart for corn harvest",
                "carbon_impact": 45.0,
                "carbon_category": "high",
                "cost_estimate": 85.0,
                "labor_hours": 1.0,
                "timing": "September - November",
                "frequency": "annual",
                "typical_duration": "1.0 hour per hectare",
                "order_sequence": 7,
                "typical_amounts": {"fuel_liters_per_ha": 35, "combine_hp": 350},
                "carbon_sources": ["diesel_fuel", "grain_handling_systems"],
                "efficiency_tips": "Maintain optimal ground speed. Use yield mapping.",
                "sustainability_score": 7,
                "alternative_methods": ["custom_harvesting", "biofuel_use"],
                "qr_visibility": "high",
                "consumer_message": "Modern harvest equipment captures corn efficiently",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Combine Harvest Operation",
                    "equipment_type": "combine_harvester",
                    "implement_type": "combine",
                    "fuel_type": "diesel",
                    "fuel_consumed": 35.0,
                    "fuel_unit": "L",
                    "equipment_hours": 1.0,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
            {
                "name": "Sidedress Nitrogen Application (June)",
                "event_type": "fertilization",
                "description": "Mid-season nitrogen application using high-clearance applicator",
                "carbon_impact": 35.0,
                "carbon_category": "medium",
                "cost_estimate": 48.0,
                "labor_hours": 0.4,
                "timing": "June - July",
                "frequency": "annual",
                "typical_duration": "0.4 hours per hectare",
                "order_sequence": 5,
                "typical_amounts": {"nitrogen_kg_per_ha": 45, "fuel_liters_per_ha": 8},
                "carbon_sources": ["nitrogen_fertilizer", "diesel_fuel"],
                "efficiency_tips": "Use soil testing and tissue analysis to optimize rates.",
                "sustainability_score": 6,
                "alternative_methods": ["variable_rate_application", "enhanced_efficiency_fertilizer"],
                "qr_visibility": "high",
                "consumer_message": "Precision nitrogen application for optimal corn nutrition",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "FE",
                    "commercial_name": "Urea Ammonium Nitrate (UAN 28%)",
                    "volume": 45,
                    "volume_unit": "kg/ha",
                    "way_of_application": "high_clearance_sprayer",
                    "time_period": "mid_season",
                    "chemical_subtype": "synthetic_fertilizer",
                    "nitrogen_percentage": 28.0,
                    "phosphorus_percentage": 0.0,
                    "potassium_percentage": 0.0,
                    "application_fuel_type": "diesel",
                    "application_fuel_consumed": 8.0,
                    "application_fuel_unit": "L",
                    "organic_approved": "no",
                },
                "usda_practice_code": "590",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
        ]

        return self.create_events_for_template(template, equipment_events)

    def add_soybean_equipment_events(self, template):
        """Add equipment events specific to soybean production"""

        equipment_events = [
            {
                "name": "Fall Tillage - No-Till/Min-Till Prep",
                "event_type": "equipment",
                "description": "Light tillage or no-till preparation for soybean rotation",
                "carbon_impact": 15.0,
                "carbon_category": "low",
                "cost_estimate": 25.0,
                "labor_hours": 0.4,
                "timing": "October - November",
                "frequency": "annual",
                "typical_duration": "0.4 hours per hectare",
                "order_sequence": 1,
                "typical_amounts": {"fuel_liters_per_ha": 12, "tractor_hp": 140},
                "carbon_sources": ["diesel_fuel"],
                "efficiency_tips": "Soybeans work well with no-till systems.",
                "sustainability_score": 8,
                "alternative_methods": ["no_till", "cover_crop_termination"],
                "qr_visibility": "low",
                "consumer_message": "Minimal soil disturbance for sustainable production",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Fall Tillage - No-Till/Min-Till Prep",
                    "equipment_type": "tractor_medium",
                    "implement_type": "no_till_prep",
                    "fuel_type": "diesel",
                    "fuel_consumed": 12.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.4,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "high",
                },
                "usda_practice_code": "329",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Precision Planting Equipment (Tractor + Planter)",
                "event_type": "equipment",
                "description": "Precision soybean planting with GPS guidance",
                "carbon_impact": 14.0,
                "carbon_category": "low",
                "cost_estimate": 32.0,
                "labor_hours": 0.45,
                "timing": "April - June",
                "frequency": "annual",
                "typical_duration": "0.45 hours per hectare",
                "order_sequence": 3,
                "typical_amounts": {"fuel_liters_per_ha": 11, "tractor_hp": 150},
                "carbon_sources": ["diesel_fuel", "hydraulic_systems"],
                "efficiency_tips": "Use variable rate seeding based on field zones.",
                "sustainability_score": 8,
                "alternative_methods": ["no_till_planter", "high_speed_planting"],
                "qr_visibility": "medium",
                "consumer_message": "Precision technology optimizes soybean emergence",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Precision Planting Equipment (Tractor + Planter)",
                    "equipment_type": "tractor_large",
                    "implement_type": "precision_planter",
                    "fuel_type": "diesel",
                    "fuel_consumed": 11.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.45,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
            {
                "name": "Sprayer Operations (Herbicide & Fungicide)",
                "event_type": "equipment",
                "description": "Field sprayer for weed and disease management",
                "carbon_impact": 20.0,
                "carbon_category": "medium",
                "cost_estimate": 38.0,
                "labor_hours": 0.8,
                "timing": "May - August",
                "frequency": "seasonal",
                "typical_duration": "2-3 applications",
                "order_sequence": 5,
                "typical_amounts": {"fuel_liters_per_ha": 15, "applications": 2.5},
                "carbon_sources": ["diesel_fuel", "hydraulic_systems"],
                "efficiency_tips": "Use GPS section control for precision.",
                "sustainability_score": 6,
                "alternative_methods": ["precision_application", "IPM"],
                "qr_visibility": "high",
                "consumer_message": "Targeted application minimizes chemical use",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Sprayer Operations (Herbicide & Fungicide)",
                    "equipment_type": "sprayer_self_propelled",
                    "implement_type": "field_sprayer",
                    "fuel_type": "diesel",
                    "fuel_consumed": 15.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.8,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "590",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Combine Harvest Operation",
                "event_type": "equipment",
                "description": "Combine harvester for soybean harvest with grain handling",
                "carbon_impact": 38.0,
                "carbon_category": "high",
                "cost_estimate": 75.0,
                "labor_hours": 0.9,
                "timing": "September - November",
                "frequency": "annual",
                "typical_duration": "0.9 hours per hectare",
                "order_sequence": 7,
                "typical_amounts": {"fuel_liters_per_ha": 30, "combine_hp": 350},
                "carbon_sources": ["diesel_fuel", "grain_handling_systems"],
                "efficiency_tips": "Monitor moisture for optimal harvest timing.",
                "sustainability_score": 7,
                "alternative_methods": ["custom_harvesting", "cooperative_ownership"],
                "qr_visibility": "high",
                "consumer_message": "Efficient harvest preserves soybean quality",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Combine Harvest Operation",
                    "equipment_type": "combine_harvester",
                    "implement_type": "combine",
                    "fuel_type": "diesel",
                    "fuel_consumed": 30.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.9,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
        ]

        return self.create_events_for_template(template, equipment_events)

    def add_wheat_equipment_events(self, template):
        """Add equipment events specific to wheat production"""

        equipment_events = [
            {
                "name": "Fall Seedbed Preparation (Disk + Field Cultivator)",
                "event_type": "equipment",
                "description": "Fall tillage for winter wheat seedbed preparation",
                "carbon_impact": 22.0,
                "carbon_category": "medium",
                "cost_estimate": 35.0,
                "labor_hours": 0.7,
                "timing": "August - September",
                "frequency": "annual",
                "typical_duration": "0.7 hours per hectare",
                "order_sequence": 1,
                "typical_amounts": {"fuel_liters_per_ha": 17, "tractor_hp": 160},
                "carbon_sources": ["diesel_fuel", "equipment_operations"],
                "efficiency_tips": "Combine operations when possible.",
                "sustainability_score": 6,
                "alternative_methods": ["no_till", "strip_till"],
                "qr_visibility": "low",
                "consumer_message": "Preparing optimal seedbed for wheat establishment",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Fall Seedbed Preparation (Disk + Field Cultivator)",
                    "equipment_type": "tractor_large",
                    "implement_type": "disk_cultivator",
                    "fuel_type": "diesel",
                    "fuel_consumed": 17.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.7,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "329",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Wheat Planting Equipment (Drill/Air Seeder)",
                "event_type": "equipment",
                "description": "Precision wheat seeding with grain drill",
                "carbon_impact": 16.0,
                "carbon_category": "low",
                "cost_estimate": 28.0,
                "labor_hours": 0.5,
                "timing": "September - November",
                "frequency": "annual",
                "typical_duration": "0.5 hours per hectare",
                "order_sequence": 3,
                "typical_amounts": {"fuel_liters_per_ha": 12, "seeding_rate_kg_ha": 135},
                "carbon_sources": ["diesel_fuel", "seed_delivery_system"],
                "efficiency_tips": "Maintain consistent seeding depth and rate.",
                "sustainability_score": 8,
                "alternative_methods": ["no_till_drill", "broadcast_seeding"],
                "qr_visibility": "medium",
                "consumer_message": "Precision seeding ensures optimal wheat emergence",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Wheat Planting Equipment (Drill/Air Seeder)",
                    "equipment_type": "tractor_large",
                    "implement_type": "grain_drill",
                    "fuel_type": "diesel",
                    "fuel_consumed": 12.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.5,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
            {
                "name": "Sprayer Operations (Herbicide & Fungicide)",
                "event_type": "equipment",
                "description": "Field sprayer for weed control and disease management",
                "carbon_impact": 22.0,
                "carbon_category": "medium",
                "cost_estimate": 40.0,
                "labor_hours": 0.9,
                "timing": "October - June",
                "frequency": "seasonal",
                "typical_duration": "2-3 applications",
                "order_sequence": 5,
                "typical_amounts": {"fuel_liters_per_ha": 16, "applications": 2.5},
                "carbon_sources": ["diesel_fuel", "hydraulic_systems"],
                "efficiency_tips": "Time applications for optimal control.",
                "sustainability_score": 6,
                "alternative_methods": ["IPM", "precision_application"],
                "qr_visibility": "high",
                "consumer_message": "Targeted protection ensures healthy wheat",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Sprayer Operations (Herbicide & Fungicide)",
                    "equipment_type": "sprayer_self_propelled",
                    "implement_type": "field_sprayer",
                    "fuel_type": "diesel",
                    "fuel_consumed": 16.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.9,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "590",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Combine Harvest Operation",
                "event_type": "equipment",
                "description": "Combine harvester for wheat harvest with grain handling",
                "carbon_impact": 32.0,
                "carbon_category": "medium",
                "cost_estimate": 65.0,
                "labor_hours": 0.8,
                "timing": "June - August",
                "frequency": "annual",
                "typical_duration": "0.8 hours per hectare",
                "order_sequence": 7,
                "typical_amounts": {"fuel_liters_per_ha": 25, "combine_hp": 300},
                "carbon_sources": ["diesel_fuel", "grain_handling"],
                "efficiency_tips": "Harvest at optimal moisture content.",
                "sustainability_score": 7,
                "alternative_methods": ["custom_harvesting"],
                "qr_visibility": "high",
                "consumer_message": "Efficient harvest captures wheat grain",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Combine Harvest Operation",
                    "equipment_type": "combine_harvester",
                    "implement_type": "combine",
                    "fuel_type": "diesel",
                    "fuel_consumed": 25.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.8,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
        ]

        return self.create_events_for_template(template, equipment_events)

    def add_alfalfa_equipment_events(self, template):
        """Add equipment events specific to hay/alfalfa production"""

        equipment_events = [
            {
                "name": "Field Preparation - Establishment Year",
                "event_type": "equipment",
                "description": "One-time field preparation for alfalfa establishment",
                "carbon_impact": 35.0,
                "carbon_category": "medium",
                "cost_estimate": 55.0,
                "labor_hours": 1.2,
                "timing": "March - April (Establishment Year)",
                "frequency": "one_time",
                "typical_duration": "1.2 hours per hectare",
                "order_sequence": 1,
                "typical_amounts": {"fuel_liters_per_ha": 28, "tractor_hp": 180},
                "carbon_sources": ["diesel_fuel", "tillage_equipment"],
                "efficiency_tips": "Deep tillage for alfalfa root development.",
                "sustainability_score": 7,
                "alternative_methods": ["no_till_establishment"],
                "qr_visibility": "low",
                "consumer_message": "One-time field preparation for long-term alfalfa production",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Field Preparation - Establishment Year",
                    "equipment_type": "tractor_large",
                    "implement_type": "deep_tillage",
                    "fuel_type": "diesel",
                    "fuel_consumed": 28.0,
                    "fuel_unit": "L",
                    "equipment_hours": 1.2,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "329",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Alfalfa Seeding Equipment",
                "event_type": "equipment",
                "description": "Precision seeding for alfalfa establishment",
                "carbon_impact": 18.0,
                "carbon_category": "low",
                "cost_estimate": 35.0,
                "labor_hours": 0.6,
                "timing": "March - April (Establishment Year)",
                "frequency": "one_time",
                "typical_duration": "0.6 hours per hectare",
                "order_sequence": 2,
                "typical_amounts": {"fuel_liters_per_ha": 14, "seed_rate_kg_ha": 22},
                "carbon_sources": ["diesel_fuel", "seeding_equipment"],
                "efficiency_tips": "Ensure proper seed depth and inoculation.",
                "sustainability_score": 9,
                "alternative_methods": ["broadcast_seeding"],
                "qr_visibility": "medium",
                "consumer_message": "Establishing nitrogen-fixing alfalfa for sustainable production",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Alfalfa Seeding Equipment",
                    "equipment_type": "tractor_medium",
                    "implement_type": "grain_drill",
                    "fuel_type": "diesel",
                    "fuel_consumed": 14.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.6,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
            {
                "name": "Mowing Equipment Operation (Multiple Cuts)",
                "event_type": "equipment",
                "description": "Mowing operation for hay production (3-5 cuts annually)",
                "carbon_impact": 25.0,
                "carbon_category": "medium",
                "cost_estimate": 45.0,
                "labor_hours": 1.5,
                "timing": "May - September (Multiple Cuts)",
                "frequency": "seasonal",
                "typical_duration": "0.3 hours per cut per hectare",
                "order_sequence": 4,
                "typical_amounts": {"fuel_liters_per_ha": 20, "cuts_per_year": 4},
                "carbon_sources": ["diesel_fuel", "mowing_equipment"],
                "efficiency_tips": "Cut at optimal growth stage for quality and yield.",
                "sustainability_score": 8,
                "alternative_methods": ["rotational_grazing"],
                "qr_visibility": "high",
                "consumer_message": "Multiple cuts capture high-quality protein-rich forage",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Mowing Equipment Operation (Multiple Cuts)",
                    "equipment_type": "tractor_medium",
                    "implement_type": "mower_conditioner",
                    "fuel_type": "diesel",
                    "fuel_consumed": 20.0,
                    "fuel_unit": "L",
                    "equipment_hours": 1.5,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "511",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
            {
                "name": "Hay Raking and Baling Equipment",
                "event_type": "equipment",
                "description": "Raking and baling operations for hay collection",
                "carbon_impact": 22.0,
                "carbon_category": "medium",
                "cost_estimate": 55.0,
                "labor_hours": 1.2,
                "timing": "May - September (After Each Cut)",
                "frequency": "seasonal",
                "typical_duration": "0.3 hours per operation per hectare",
                "order_sequence": 5,
                "typical_amounts": {"fuel_liters_per_ha": 18, "bales_per_hectare": 12},
                "carbon_sources": ["diesel_fuel", "baling_equipment"],
                "efficiency_tips": "Bale at proper moisture content for quality storage.",
                "sustainability_score": 7,
                "alternative_methods": ["chopped_haylage", "grazing_only"],
                "qr_visibility": "high",
                "consumer_message": "Efficient collection preserves nutritional quality of alfalfa",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Hay Raking and Baling Equipment",
                    "equipment_type": "baler_self_propelled",
                    "implement_type": "rake_baler",
                    "fuel_type": "diesel",
                    "fuel_consumed": 18.0,
                    "fuel_unit": "L",
                    "equipment_hours": 1.2,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "511",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
        ]

        return self.create_events_for_template(template, equipment_events)

    def add_generic_equipment_events(self, template):
        """Add generic equipment events for other crop types"""

        equipment_events = [
            {
                "name": "Field Preparation Equipment",
                "event_type": "equipment",
                "description": "General field preparation with tractor and implements",
                "carbon_impact": 20.0,
                "carbon_category": "medium",
                "cost_estimate": 35.0,
                "labor_hours": 0.8,
                "timing": "Pre-season",
                "frequency": "annual",
                "typical_duration": "0.8 hours per hectare",
                "order_sequence": 1,
                "typical_amounts": {"fuel_liters_per_ha": 16, "tractor_hp": 150},
                "carbon_sources": ["diesel_fuel", "equipment_operations"],
                "efficiency_tips": "Combine operations to reduce passes.",
                "sustainability_score": 7,
                "alternative_methods": ["reduced_tillage", "no_till"],
                "qr_visibility": "low",
                "consumer_message": "Efficient field preparation for optimal crop establishment",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Field Preparation Equipment",
                    "equipment_type": "tractor_medium",
                    "implement_type": "field_preparation",
                    "fuel_type": "diesel",
                    "fuel_consumed": 16.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.8,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "329",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": False,
            },
            {
                "name": "Planting/Seeding Equipment",
                "event_type": "equipment",
                "description": "Planting or seeding operation with appropriate equipment",
                "carbon_impact": 15.0,
                "carbon_category": "low",
                "cost_estimate": 30.0,
                "labor_hours": 0.6,
                "timing": "Planting Season",
                "frequency": "annual",
                "typical_duration": "0.6 hours per hectare",
                "order_sequence": 3,
                "typical_amounts": {"fuel_liters_per_ha": 12, "tractor_hp": 140},
                "carbon_sources": ["diesel_fuel", "planting_equipment"],
                "efficiency_tips": "Use precision planting for optimal spacing.",
                "sustainability_score": 8,
                "alternative_methods": ["precision_planting", "variable_rate"],
                "qr_visibility": "medium",
                "consumer_message": "Precision planting ensures optimal crop establishment",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Planting/Seeding Equipment",
                    "equipment_type": "tractor_medium",
                    "implement_type": "planter",
                    "fuel_type": "diesel",
                    "fuel_consumed": 12.0,
                    "fuel_unit": "L",
                    "equipment_hours": 0.6,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
            {
                "name": "Harvest Equipment Operation",
                "event_type": "equipment",
                "description": "Harvest operation with appropriate machinery",
                "carbon_impact": 30.0,
                "carbon_category": "medium",
                "cost_estimate": 60.0,
                "labor_hours": 1.0,
                "timing": "Harvest Season",
                "frequency": "annual",
                "typical_duration": "1.0 hour per hectare",
                "order_sequence": 7,
                "typical_amounts": {"fuel_liters_per_ha": 24, "equipment_hp": 250},
                "carbon_sources": ["diesel_fuel", "harvest_equipment"],
                "efficiency_tips": "Harvest at optimal timing for quality and yield.",
                "sustainability_score": 7,
                "alternative_methods": ["custom_harvesting", "mechanical_harvesting"],
                "qr_visibility": "high",
                "consumer_message": "Efficient harvest preserves crop quality and nutrition",
                "backend_event_type": 1,
                "backend_event_fields": {
                    "type": "EM",
                    "equipment_operation_type": "MN",
                    "name": "Harvest Equipment Operation",
                    "equipment_type": "combine_harvester",
                    "implement_type": "harvester",
                    "fuel_type": "diesel",
                    "fuel_consumed": 24.0,
                    "fuel_unit": "L",
                    "equipment_hours": 1.0,
                    "area_worked": 1.0,
                    "area_unit": "ha",
                    "operation_efficiency": "normal",
                },
                "usda_practice_code": "328",
                "usda_compliant": True,
                "emission_factor_source": "USDA Agricultural Research Service",
                "is_active": True,
                "is_default_enabled": True,
                "is_required": True,
            },
        ]

        return self.create_events_for_template(template, equipment_events)

    def create_events_for_template(self, template, equipment_events):
        """Create equipment events for a template, avoiding duplicates"""

        created_count = 0
        for event_data in equipment_events:
            event_data["production_template"] = template

            # Check if event already exists
            existing = EventTemplate.objects.filter(production_template=template, name=event_data["name"]).first()

            if not existing:
                EventTemplate.objects.create(**event_data)
                created_count += 1

        return created_count

    def check_usda_compliance(self, crop_name, carbon_footprint):
        """Check if carbon footprint is within USDA compliance ranges"""

        usda_ranges = {
            "Corn (Field)": (800, 1200),
            "Soybeans": (600, 900),
            "Wheat": (700, 1000),
            "Hay/Alfalfa": (400, 800),
            "Cotton": (1200, 1800),
            "Rice": (1000, 1500),
        }

        if crop_name in usda_ranges:
            min_val, max_val = usda_ranges[crop_name]
            return min_val <= carbon_footprint <= max_val

        # Generic range for other crops
        return 500 <= carbon_footprint <= 1200

    def enhance_remaining_crops(self):
        """Enhance all remaining crops beyond the major 4"""
        major_crops = ["Corn (Field)", "Soybeans", "Wheat", "Hay/Alfalfa"]
        remaining_crops = CropType.objects.filter(is_active=True).exclude(name__in=major_crops)

        self.stdout.write("🌱 PHASE 2: Enhancing Remaining Crops")

        enhanced_count = 0
        for crop in remaining_crops:
            try:
                template = ProductionTemplate.objects.get(crop_type=crop)
                before_carbon = template.total_carbon_impact

                added = self.add_generic_equipment_events(template)

                if added > 0:
                    enhanced_count += 1
                    template.refresh_from_db()
                    after_carbon = template.total_carbon_impact

                    self.stdout.write(f"✅ {crop.name:20}: {after_carbon:6.1f} kg CO2e/ha (+{added} equipment events)")

            except ProductionTemplate.DoesNotExist:
                self.stdout.write(f"⚠️  No template for {crop.name}")

        self.stdout.write(self.style.SUCCESS(f"\n🎉 Phase 2 Complete! Enhanced {enhanced_count} additional crops"))
