from django.core.management.base import BaseCommand
from django.db import transaction

from carbon.models import CropType, EventTemplate, ProductionTemplate


class Command(BaseCommand):
    help = "Add region-specific agricultural practices for Iowa and California MVP launch"

    def add_arguments(self, parser):
        parser.add_argument(
            "--state",
            type=str,
            required=True,
            choices=["Iowa", "California"],
            help="Target state for regional practices (Iowa or California)",
        )
        parser.add_argument(
            "--practice",
            type=str,
            choices=[
                "no_till",
                "cover_crops",
                "precision_nitrogen",
                "micro_sprinkler",
                "deficit_irrigation",
                "soil_sensors",
                "all",
            ],
            help="Specific practice to add, or 'all' for all state practices",
        )
        parser.add_argument(
            "--validate-only", action="store_true", help="Only validate what would be added, do not make changes"
        )

    def handle(self, *args, **options):
        """Add region-specific agricultural practices for MVP launch"""

        self.stdout.write(self.style.SUCCESS("🌾 ADDING REGIONAL AGRICULTURAL PRACTICES"))
        self.stdout.write("=" * 55)

        state = options["state"]
        practice = options.get("practice", "all")
        validate_only = options.get("validate_only", False)

        if validate_only:
            self.stdout.write(f"🔍 VALIDATION MODE - {state} regional practices")
            self.validate_regional_practices(state, practice)
        else:
            self.stdout.write(f"✅ IMPLEMENTATION MODE - Adding {state} practices")
            self.add_regional_practices(state, practice)

    def add_regional_practices(self, state, practice):
        """Add regional practices based on state and practice type"""

        if state == "Iowa":
            self.add_iowa_practices(practice)
        elif state == "California":
            self.add_california_practices(practice)

        self.stdout.write(self.style.SUCCESS(f"✅ {state} regional practices added successfully!"))

    def add_iowa_practices(self, practice_type):
        """Add Iowa-specific conservation practices for corn and soybeans"""

        # Iowa conservation practices for corn-soy rotation
        iowa_practices = {
            "no_till": [
                {
                    "crop": "Corn (Field)",
                    "name": "No-Till Planting (Conservation)",
                    "event_type": "equipment",
                    "carbon_impact": -25.0,  # Carbon sequestration benefit
                    "cost_estimate": 45.0,  # $/ha - slightly higher setup cost
                    "timing": "April - May",
                    "description": "Conservation tillage preserves soil carbon and reduces erosion",
                    "qr_consumer_message": "No-till farming stores carbon in soil for future generations",
                    "iowa_specific": True,
                    "conservation_practice": True,
                    "backend_event_type": 4,  # Equipment event
                },
                {
                    "crop": "Soybeans",
                    "name": "No-Till Soybean Planting",
                    "event_type": "equipment",
                    "carbon_impact": -20.0,  # Soybean no-till benefit
                    "cost_estimate": 40.0,
                    "timing": "May - June",
                    "description": "Direct seeding preserves soil structure and organic matter",
                    "qr_consumer_message": "No-till soybeans build soil health naturally",
                    "iowa_specific": True,
                    "conservation_practice": True,
                    "backend_event_type": 4,
                },
            ],
            "cover_crops": [
                {
                    "crop": "Corn (Field)",
                    "name": "Cover Crop Termination (Pre-Corn)",
                    "event_type": "soil_management",
                    "carbon_impact": -45.0,  # Major carbon sequestration
                    "cost_estimate": 25.0,  # Termination cost
                    "timing": "April - May",
                    "description": "Winter cover crops capture and store atmospheric carbon",
                    "qr_consumer_message": "Cover crops capture carbon year-round between growing seasons",
                    "iowa_specific": True,
                    "conservation_practice": True,
                    "backend_event_type": 2,  # Soil management
                },
                {
                    "crop": "Soybeans",
                    "name": "Cover Crop Integration (Post-Soybean)",
                    "event_type": "soil_management",
                    "carbon_impact": -40.0,  # Carbon sequestration
                    "cost_estimate": 35.0,  # Seeding cost
                    "timing": "September - October",
                    "description": "Post-harvest cover crop establishment for winter carbon capture",
                    "qr_consumer_message": "Cover crops prevent soil erosion and capture carbon",
                    "iowa_specific": True,
                    "conservation_practice": True,
                    "backend_event_type": 2,
                },
            ],
            "precision_nitrogen": [
                {
                    "crop": "Corn (Field)",
                    "name": "Variable-Rate Nitrogen Application (GPS)",
                    "event_type": "fertilization",
                    "carbon_impact": 180.0,  # 20% reduction from 220.0 broadcast
                    "cost_estimate": 85.0,  # Higher tech cost, lower input cost
                    "timing": "April - June",
                    "description": "GPS-guided precision reduces fertilizer waste and N2O emissions",
                    "qr_consumer_message": "Precision farming reduces fertilizer waste by 20%",
                    "iowa_specific": True,
                    "precision_agriculture": True,
                    "backend_event_type": 1,  # Fertilization
                },
                {
                    "crop": "Soybeans",
                    "name": "Precision Phosphorus/Potassium Application",
                    "event_type": "fertilization",
                    "carbon_impact": 25.0,  # Minimal fertilizer for soybeans
                    "cost_estimate": 30.0,
                    "timing": "April - May",
                    "description": "Variable-rate P&K application based on soil testing",
                    "qr_consumer_message": "Precision nutrients support nitrogen-fixing bacteria",
                    "iowa_specific": True,
                    "precision_agriculture": True,
                    "backend_event_type": 1,
                },
            ],
        }

        if practice_type == "all" or practice_type is None:
            practices_to_add = []
            for practice_name, events in iowa_practices.items():
                practices_to_add.extend(events)
            self.stdout.write(f"📋 Adding all Iowa practices: {list(iowa_practices.keys())}")
        else:
            practices_to_add = iowa_practices.get(practice_type, [])
            self.stdout.write(f"📋 Adding specific Iowa practice: {practice_type}")

        self.stdout.write(f"📊 Total practices to create: {len(practices_to_add)}")

        self.create_regional_events(practices_to_add, "Iowa")

    def add_california_practices(self, practice_type):
        """Add California-specific irrigation and water management practices"""

        # California water-efficient practices for tree crops
        california_practices = {
            "micro_sprinkler": [
                {
                    "crop": "Almonds",
                    "name": "Micro-Sprinkler Irrigation (Water-Efficient)",
                    "event_type": "irrigation",
                    "carbon_impact": 85.0,  # 40% less than flood irrigation (150.0)
                    "cost_estimate": 120.0,  # Higher setup, lower operating cost
                    "timing": "March - September",
                    "description": "90% application efficiency vs 65% for flood irrigation",
                    "qr_consumer_message": "Water-efficient irrigation saves 35% water usage",
                    "california_specific": True,
                    "water_efficient": True,
                    "backend_event_type": 3,  # Irrigation
                },
                {
                    "crop": "Citrus (Oranges)",
                    "name": "Precision Micro-Sprinkler System",
                    "event_type": "irrigation",
                    "carbon_impact": 75.0,  # Efficient water delivery
                    "cost_estimate": 100.0,
                    "timing": "Year-round",
                    "description": "Targeted water delivery reduces pumping energy",
                    "qr_consumer_message": "Smart irrigation optimizes tree health and water use",
                    "california_specific": True,
                    "water_efficient": True,
                    "backend_event_type": 3,
                },
                {
                    "crop": "Avocados",
                    "name": "Micro-Sprinkler with Mulching",
                    "event_type": "irrigation",
                    "carbon_impact": 70.0,  # Combined water efficiency
                    "cost_estimate": 95.0,
                    "timing": "Year-round",
                    "description": "Micro-sprinklers with mulch reduce evaporation by 30%",
                    "qr_consumer_message": "Water-smart avocado growing protects drought-stressed regions",
                    "california_specific": True,
                    "water_efficient": True,
                    "backend_event_type": 3,
                },
            ],
            "deficit_irrigation": [
                {
                    "crop": "Almonds",
                    "name": "Deficit Irrigation Strategy (July-August)",
                    "event_type": "irrigation",
                    "carbon_impact": 65.0,  # Strategic water stress
                    "cost_estimate": 45.0,  # Reduced water costs
                    "timing": "July - August",
                    "description": "Controlled water stress during shell hardening improves quality",
                    "qr_consumer_message": "Strategic watering produces higher-quality nuts",
                    "california_specific": True,
                    "water_management": True,
                    "backend_event_type": 3,
                },
                {
                    "crop": "Citrus (Oranges)",
                    "name": "Regulated Deficit Irrigation",
                    "event_type": "irrigation",
                    "carbon_impact": 60.0,  # Water conservation
                    "cost_estimate": 40.0,
                    "timing": "June - August",
                    "description": "Mild water stress concentrates fruit sugars and flavors",
                    "qr_consumer_message": "Water-efficient growing enhances fruit quality",
                    "california_specific": True,
                    "water_management": True,
                    "backend_event_type": 3,
                },
            ],
            "soil_sensors": [
                {
                    "crop": "Almonds",
                    "name": "Soil Moisture Monitoring Network",
                    "event_type": "equipment",
                    "carbon_impact": 5.0,  # Minimal direct emissions, major efficiency gains
                    "cost_estimate": 15.0,  # Sensor maintenance
                    "timing": "Year-round",
                    "description": "Real-time soil moisture prevents over-watering and optimizes timing",
                    "qr_consumer_message": "Smart sensors optimize water use with precision technology",
                    "california_specific": True,
                    "precision_agriculture": True,
                    "backend_event_type": 4,
                },
                {
                    "crop": "Avocados",
                    "name": "Precision Soil Monitoring System",
                    "event_type": "equipment",
                    "carbon_impact": 4.0,  # Efficiency gains
                    "cost_estimate": 12.0,
                    "timing": "Year-round",
                    "description": "Multi-depth sensors optimize irrigation scheduling",
                    "qr_consumer_message": "Technology-driven farming reduces water waste",
                    "california_specific": True,
                    "precision_agriculture": True,
                    "backend_event_type": 4,
                },
            ],
        }

        if practice_type == "all" or practice_type is None:
            practices_to_add = []
            for practice_name, events in california_practices.items():
                practices_to_add.extend(events)
            self.stdout.write(f"📋 Adding all California practices: {list(california_practices.keys())}")
        else:
            practices_to_add = california_practices.get(practice_type, [])
            self.stdout.write(f"📋 Adding specific California practice: {practice_type}")

        self.stdout.write(f"📊 Total practices to create: {len(practices_to_add)}")

        self.create_regional_events(practices_to_add, "California")

    def create_regional_events(self, practices_data, state):
        """Create EventTemplate records for regional practices"""

        created_count = 0

        with transaction.atomic():
            for practice in practices_data:
                crop_name = practice["crop"]

                # Get the crop type
                try:
                    crop_type = CropType.objects.get(name=crop_name, is_active=True)
                except CropType.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f"⚠️  Crop '{crop_name}' not found, skipping"))
                    continue

                # Get the production template
                production_template = ProductionTemplate.objects.filter(crop_type=crop_type).first()

                if not production_template:
                    self.stdout.write(self.style.WARNING(f"⚠️  No production template for '{crop_name}', skipping"))
                    continue

                # Check if this regional practice already exists
                existing_event = EventTemplate.objects.filter(
                    production_template=production_template, name=practice["name"]
                ).first()

                if existing_event:
                    self.stdout.write(f"⏭️  '{practice['name']}' already exists for {crop_name}")
                    continue

                self.stdout.write(f"🔨 Creating '{practice['name']}' for {crop_name}...")

                # Create the new regional event
                event_data = {
                    "production_template": production_template,
                    "name": practice["name"],
                    "event_type": practice["event_type"],
                    "carbon_impact": practice["carbon_impact"],
                    "cost_estimate": practice["cost_estimate"],
                    "timing": practice["timing"],
                    "description": practice["description"],
                    "backend_event_type": practice["backend_event_type"],
                    "typical_amounts": {
                        "regional_practice": True,
                        "state": state,
                        "consumer_message": practice["qr_consumer_message"],
                    },
                }

                # Add optional fields if present
                for optional_field in [
                    "iowa_specific",
                    "california_specific",
                    "conservation_practice",
                    "precision_agriculture",
                    "water_efficient",
                    "water_management",
                ]:
                    if optional_field in practice:
                        event_data["typical_amounts"][optional_field] = practice[optional_field]

                EventTemplate.objects.create(**event_data)
                created_count += 1

                self.stdout.write(f"✅ Created '{practice['name']}' for {crop_name}")

        self.stdout.write(self.style.SUCCESS(f"📈 Successfully created {created_count} {state} regional practices"))

    def validate_regional_practices(self, state, practice_type):
        """Validate what regional practices would be added"""

        self.stdout.write(f"🔍 Validating {state} regional practices")
        self.stdout.write("-" * 40)

        if state == "Iowa":
            target_crops = ["Corn (Field)", "Soybeans"]
            if practice_type == "all" or practice_type is None:
                practices = ["no_till", "cover_crops", "precision_nitrogen"]
            else:
                practices = [practice_type]

        elif state == "California":
            target_crops = ["Almonds", "Citrus (Oranges)", "Avocados"]
            if practice_type == "all" or practice_type is None:
                practices = ["micro_sprinkler", "deficit_irrigation", "soil_sensors"]
            else:
                practices = [practice_type]

        for crop_name in target_crops:
            try:
                crop_type = CropType.objects.get(name=crop_name, is_active=True)
                template = ProductionTemplate.objects.filter(crop_type=crop_type).first()

                if template:
                    current_events = EventTemplate.objects.filter(production_template=template).count()
                    self.stdout.write(f"✅ {crop_name}: {current_events} current events")
                else:
                    self.stdout.write(f"❌ {crop_name}: No production template found")

            except CropType.DoesNotExist:
                self.stdout.write(f"❌ {crop_name}: Crop type not found")

        self.stdout.write(f"\n📋 Would add practices: {', '.join(practices)}")
        self.stdout.write(f"🎯 Target crops: {', '.join(target_crops)}")
