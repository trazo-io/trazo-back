import random
from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from carbon.models import EventTemplate, ProductionTemplate
from history.models import ChemicalEvent, GeneralEvent, History, ProductionEvent


class Command(BaseCommand):
    help = "Add comprehensive events to existing test productions for transparency testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--production-ids",
            type=str,
            default="125,126,127,128,129",
            help="Comma-separated production IDs to add events to",
        )
        parser.add_argument(
            "--validate-only", action="store_true", help="Only validate what would be created, do not make changes"
        )

    def handle(self, *args, **options):
        """Add events to test productions for comprehensive transparency testing"""

        self.stdout.write(self.style.SUCCESS("🎯 ADDING EVENTS TO TEST PRODUCTIONS"))
        self.stdout.write("=" * 55)

        production_ids = [int(x.strip()) for x in options.get("production_ids", "125,126,127,128,129").split(",")]
        validate_only = options.get("validate_only", False)

        if validate_only:
            self.stdout.write(f"🔍 VALIDATION MODE - Checking productions {production_ids}")
            self.validate_productions(production_ids)
        else:
            self.stdout.write(f"✅ CREATION MODE - Adding events to productions {production_ids}")
            self.add_events_to_productions(production_ids)

    def validate_productions(self, production_ids):
        """Validate what events would be created for each production"""

        for prod_id in production_ids:
            try:
                production = History.objects.get(id=prod_id)
                self.stdout.write(f"\n🌱 Production {prod_id}: {production.crop_type.name}")

                # Get existing events
                existing_chemical = ChemicalEvent.objects.filter(history=production).count()
                existing_production = ProductionEvent.objects.filter(history=production).count()
                existing_general = GeneralEvent.objects.filter(history=production).count()
                total_existing = existing_chemical + existing_production + existing_general

                self.stdout.write(f"   Existing events: {total_existing}")

                # Get template and potential events
                template = ProductionTemplate.objects.filter(crop_type=production.crop_type).first()
                if template:
                    event_templates = EventTemplate.objects.filter(production_template=template)
                    transparency_count = 0

                    for et in event_templates:
                        has_transparency = et.typical_amounts and "consumer_transparency" in et.typical_amounts
                        if has_transparency:
                            transparency_count += 1

                    self.stdout.write(f"   Template: {template.name}")
                    self.stdout.write(f"   Available event templates: {event_templates.count()}")
                    self.stdout.write(f"   With transparency data: {transparency_count}")
                else:
                    self.stdout.write(f"   ❌ No template found for {production.crop_type.name}")

            except History.DoesNotExist:
                self.stdout.write(f"❌ Production {prod_id} not found")

    def add_events_to_productions(self, production_ids):
        """Add comprehensive events to test productions"""

        created_count = 0

        for prod_id in production_ids:
            try:
                production = History.objects.get(id=prod_id)
                self.stdout.write(f"\n🌱 Processing Production {prod_id}: {production.crop_type.name}")

                # Skip if already has events
                existing_events = (
                    ChemicalEvent.objects.filter(history=production).count()
                    + ProductionEvent.objects.filter(history=production).count()
                    + GeneralEvent.objects.filter(history=production).count()
                )

                if existing_events > 0:
                    self.stdout.write(f"   ⏭️ Skipping - already has {existing_events} events")
                    continue

                # Get template for this crop
                template = ProductionTemplate.objects.filter(crop_type=production.crop_type).first()
                if not template:
                    self.stdout.write(f"   ❌ No template found for {production.crop_type.name}")
                    continue

                # Create events from template
                events_created = self.create_events_for_production(production, template)

                self.stdout.write(f"   ✅ Created {events_created} events")
                created_count += 1

            except History.DoesNotExist:
                self.stdout.write(f"❌ Production {prod_id} not found")
                continue
            except Exception as e:
                self.stdout.write(f"❌ Error processing production {prod_id}: {e}")
                continue

        self.stdout.write(f"\n🎉 SUCCESS: Added events to {created_count} productions")
        self.stdout.write("\n📱 TIMELINE TESTING INSTRUCTIONS:")
        self.stdout.write("1. Refresh the QR production pages")
        self.stdout.write("2. Check that timeline section now shows events instead of 'app.noTimelineData'")
        self.stdout.write("3. Verify transparency events display consumer-friendly information")
        self.stdout.write("4. Test mobile responsiveness of timeline section")

    def create_events_for_production(self, production, template):
        """Create comprehensive events for a specific production"""

        events_created = 0
        event_templates = EventTemplate.objects.filter(production_template=template)

        # Calculate date ranges for events (spread over production period)
        start_date = production.start_date or (datetime.now() - timedelta(days=120))
        finish_date = production.finish_date or (datetime.now() - timedelta(days=30))
        production_days = (finish_date - start_date).days

        for i, event_template in enumerate(event_templates):
            try:
                # Calculate event date (spread events across production period)
                days_offset = int((production_days / event_templates.count()) * i)
                event_date = start_date + timedelta(days=days_offset)

                # Generate realistic amounts based on template typical amounts
                amount = self.get_realistic_amount(event_template, production)
                unit = self.get_appropriate_unit(event_template)

                # Determine event type and create appropriate event
                event_type = self.determine_event_type(event_template)

                if event_type == "chemical":
                    event = ChemicalEvent.objects.create(
                        history=production,
                        date=event_date,
                        description=f"Applied {event_template.name.lower()} to enhance crop sustainability and reduce environmental impact",
                        type="F" if "fertiliz" in event_template.name.lower() else "P",
                        commercial_name=f"Professional {event_template.name}",
                        volume=f"{amount}",
                        concentration="N/A",
                        area=f"{production.parcel.area}",
                        way_of_application="Ground application",
                        time_period="Full season",
                        observation=f"Professional agricultural practice for optimal soil health",
                        extra_data={
                            "test_production": True,
                            "transparency_testing": True,
                            "consumer_ready": True,
                            "event_template_id": event_template.id,
                            "event_template_name": event_template.name,
                            "amount": amount,
                            "unit": unit,
                            "transparency_data": (
                                event_template.typical_amounts.get("consumer_transparency", {})
                                if event_template.typical_amounts
                                else {}
                            ),
                        },
                    )
                elif event_type == "production":
                    event = ProductionEvent.objects.create(
                        history=production,
                        date=event_date,
                        description=f"Applied {event_template.name.lower()} to enhance crop sustainability and reduce environmental impact",
                        type="H" if "harvest" in event_template.name.lower() else "P",
                        observation=f"Professional agricultural practice for optimal soil health",
                        extra_data={
                            "test_production": True,
                            "transparency_testing": True,
                            "consumer_ready": True,
                            "event_template_id": event_template.id,
                            "event_template_name": event_template.name,
                            "amount": amount,
                            "unit": unit,
                            "transparency_data": (
                                event_template.typical_amounts.get("consumer_transparency", {})
                                if event_template.typical_amounts
                                else {}
                            ),
                        },
                    )
                else:  # general
                    event = GeneralEvent.objects.create(
                        history=production,
                        date=event_date,
                        description=f"Applied {event_template.name.lower()} to enhance crop sustainability and reduce environmental impact",
                        name=event_template.name,
                        observation=f"Professional agricultural practice for optimal soil health",
                        extra_data={
                            "test_production": True,
                            "transparency_testing": True,
                            "consumer_ready": True,
                            "event_template_id": event_template.id,
                            "event_template_name": event_template.name,
                            "amount": amount,
                            "unit": unit,
                            "transparency_data": (
                                event_template.typical_amounts.get("consumer_transparency", {})
                                if event_template.typical_amounts
                                else {}
                            ),
                        },
                    )

                events_created += 1

                # Log transparency events
                has_transparency = (
                    event_template.typical_amounts and "consumer_transparency" in event_template.typical_amounts
                )
                if has_transparency:
                    self.stdout.write(f"     🔍 {event_template.name} (transparency ready)")
                else:
                    self.stdout.write(f"     ⚙️ {event_template.name}")

            except Exception as e:
                self.stdout.write(f"     ❌ Failed to create event {event_template.name}: {e}")
                continue

        return events_created

    def get_realistic_amount(self, event_template, production):
        """Generate realistic amounts based on template and production size"""

        # Base amounts on production amount and event type
        base_amount = float(production.production_amount or 1000)

        # Different scaling for different event types
        event_name_lower = event_template.name.lower()

        if "irrigation" in event_name_lower or "water" in event_name_lower:
            # Water events: gallons or liters per kg of production
            return round(base_amount * random.uniform(2.0, 5.0), 1)
        elif "fertiliz" in event_name_lower or "nutrient" in event_name_lower:
            # Fertilizer: kg per hectare or per kg production
            return round(base_amount * random.uniform(0.05, 0.15), 2)
        elif "pruning" in event_name_lower or "equipment" in event_name_lower:
            # Labor/equipment: hours
            return round(base_amount * random.uniform(0.01, 0.05), 1)
        elif "monitoring" in event_name_lower or "sensor" in event_name_lower:
            # Monitoring: data points or hours
            return round(random.uniform(50, 200), 0)
        else:
            # General events: proportional to production
            return round(base_amount * random.uniform(0.1, 0.3), 1)

    def get_appropriate_unit(self, event_template):
        """Get appropriate unit based on event template name"""

        event_name_lower = event_template.name.lower()

        if "irrigation" in event_name_lower or "water" in event_name_lower:
            return "gallons"
        elif "fertiliz" in event_name_lower:
            return "kg"
        elif "pruning" in event_name_lower or "equipment" in event_name_lower:
            return "hours"
        elif "monitoring" in event_name_lower or "sensor" in event_name_lower:
            return "data points"
        else:
            return "units"

    def determine_event_type(self, event_template):
        """Determine the appropriate Django event model type"""

        event_name_lower = event_template.name.lower()

        # Chemical events
        if any(word in event_name_lower for word in ["fertiliz", "pesticide", "herbicide", "chemical", "nutrient"]):
            return "chemical"

        # Production events
        elif any(word in event_name_lower for word in ["harvest", "plant", "seed", "production", "yield"]):
            return "production"

        # Default to general events
        else:
            return "general"
