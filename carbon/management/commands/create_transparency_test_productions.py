from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from carbon.models import CropType, EventTemplate, ProductionTemplate
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel
from users.models import User


class Command(BaseCommand):
    help = "Create comprehensive test productions for QR transparency testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-email", type=str, default="oscar@trazo.io", help="Email of user to create productions for"
        )
        parser.add_argument(
            "--validate-only", action="store_true", help="Only validate what would be created, do not make changes"
        )

    def handle(self, *args, **options):
        """Create test productions with transparency features for QR testing"""

        self.stdout.write(self.style.SUCCESS("🧪 CREATING TRANSPARENCY TEST PRODUCTIONS"))
        self.stdout.write("=" * 55)

        user_email = options.get("user_email", "oscar@trazo.io")
        validate_only = options.get("validate_only", False)

        if validate_only:
            self.stdout.write(f"🔍 VALIDATION MODE - Checking {user_email}")
            self.validate_test_setup(user_email)
        else:
            self.stdout.write(f"✅ CREATION MODE - Creating test productions for {user_email}")
            self.create_test_productions(user_email)

    def validate_test_setup(self, user_email):
        """Validate what test productions would be created"""

        try:
            user = User.objects.get(email=user_email)
            self.stdout.write(f"✅ User found: {user.email}")

            # Get user's company and establishments
            from users.models import WorksIn

            works_in = WorksIn.objects.filter(user=user).first()

            if not works_in:
                self.stdout.write(self.style.ERROR("❌ User has no company association"))
                return

            company = works_in.company
            establishments = Establishment.objects.filter(company=company)

            self.stdout.write(f"🏢 Company: {company.name}")
            self.stdout.write(f"🏭 Establishments: {establishments.count()}")

            # Check target crops and their transparency events
            target_crops = [
                ("Corn (Field)", "Iowa Conservation Practices"),
                ("Soybeans", "Iowa Conservation Practices"),
                ("Almonds", "California Water Efficiency"),
                ("Citrus (Oranges)", "California Water Efficiency"),
                ("Avocados", "California Water Efficiency"),
            ]

            self.stdout.write("\n📋 PLANNED TEST PRODUCTIONS:")
            for crop_name, theme in target_crops:
                try:
                    crop = CropType.objects.get(name=crop_name, is_active=True)
                    template = ProductionTemplate.objects.filter(crop_type=crop).first()

                    if template:
                        transparency_events = []
                        events = EventTemplate.objects.filter(production_template=template)

                        for event in events:
                            if event.typical_amounts and "consumer_transparency" in event.typical_amounts:
                                transparency_events.append(event.name)

                        self.stdout.write(f"\n🌱 {crop_name} ({theme}):")
                        self.stdout.write(f"   Template ID: {template.id}")
                        self.stdout.write(f"   Transparency Events: {len(transparency_events)}")
                        for event_name in transparency_events:
                            self.stdout.write(f"     ✅ {event_name}")

                    else:
                        self.stdout.write(f"\n❌ {crop_name}: No production template")

                except CropType.DoesNotExist:
                    self.stdout.write(f"\n❌ {crop_name}: Crop not found")

            self.stdout.write(f"\n🎯 Will create 5 comprehensive test productions with transparency features")

        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ User {user_email} not found"))

    def create_test_productions(self, user_email):
        """Create comprehensive test productions with transparency features"""

        try:
            user = User.objects.get(email=user_email)

            # Get user's company and establishments
            from users.models import WorksIn

            works_in = WorksIn.objects.filter(user=user).first()

            if not works_in:
                self.stdout.write(self.style.ERROR("❌ User has no company association"))
                return

            company = works_in.company
            establishments = list(Establishment.objects.filter(company=company))

            if not establishments:
                self.stdout.write(self.style.ERROR("❌ No establishments found"))
                return

            # Test production configurations
            production_configs = [
                {
                    "crop_name": "Corn (Field)",
                    "production_name": "Iowa Conservation Corn - Test QR Transparency",
                    "amount": Decimal("1500.0"),  # 1500 kg
                    "theme": "Conservation practices with no-till and cover crops",
                    "establishment": establishments[0],  # Premium Citrus Ranch
                },
                {
                    "crop_name": "Soybeans",
                    "production_name": "Iowa Sustainable Soybeans - Test QR Transparency",
                    "amount": Decimal("1200.0"),  # 1200 kg
                    "theme": "Precision agriculture with conservation tillage",
                    "establishment": establishments[1] if len(establishments) > 1 else establishments[0],  # Grain Ranch
                },
                {
                    "crop_name": "Almonds",
                    "production_name": "California Water-Smart Almonds - Test QR Transparency",
                    "amount": Decimal("800.0"),  # 800 kg
                    "theme": "Water-efficient irrigation with soil monitoring",
                    "establishment": (
                        establishments[2] if len(establishments) > 2 else establishments[0]
                    ),  # Innovation Center
                },
                {
                    "crop_name": "Citrus (Oranges)",
                    "production_name": "California Premium Oranges - Test QR Transparency",
                    "amount": Decimal("2000.0"),  # 2000 kg
                    "theme": "Deficit irrigation with precision micro-sprinklers",
                    "establishment": establishments[0],  # Premium Citrus Ranch (perfect match)
                },
                {
                    "crop_name": "Avocados",
                    "production_name": "California Organic Avocados - Test QR Transparency",
                    "amount": Decimal("600.0"),  # 600 kg
                    "theme": "Mulching with precision soil monitoring",
                    "establishment": (
                        establishments[2] if len(establishments) > 2 else establishments[0]
                    ),  # Innovation Center
                },
            ]

            created_count = 0

            with transaction.atomic():
                for config in production_configs:
                    try:
                        # Get crop and template
                        crop = CropType.objects.get(name=config["crop_name"], is_active=True)
                        template = ProductionTemplate.objects.filter(crop_type=crop).first()

                        if not template:
                            self.stdout.write(f"❌ No template for {config['crop_name']}")
                            continue

                        # Create or get parcel for establishment
                        parcel, created = Parcel.objects.get_or_create(
                            establishment=config["establishment"],
                            name=f"Test Parcel - {config['crop_name']}",
                            defaults={
                                "area": Decimal("10.0"),  # 10 hectares
                                "coordinates": "40.7128,-74.0060",  # Sample coordinates
                                "soil_type": "Loam",
                                "is_active": True,
                            },
                        )

                        # Create production history
                        production = History.objects.create(
                            user=user,
                            parcel=parcel,
                            crop_type=crop,
                            production_template=template,
                            date_planted=datetime.now() - timedelta(days=120),  # 4 months ago
                            date_harvested=datetime.now() - timedelta(days=30),  # 1 month ago
                            amount=config["amount"],
                            confidence_score=Decimal("95.5"),  # High confidence
                            is_active=True,
                            notes=f"Test production for QR transparency testing. {config['theme']}. "
                            f"This production includes transparency features for consumer education.",
                            blockchain_verified=True,
                            qr_scanned=False,  # Ready for QR testing
                        )

                        # Add events with transparency data
                        transparency_events = self.get_transparency_events(template)

                        self.stdout.write(f"\n🌱 Created: {config['production_name']}")
                        self.stdout.write(f"   Production ID: {production.id}")
                        self.stdout.write(f"   Amount: {config['amount']} kg")
                        self.stdout.write(f"   Establishment: {config['establishment'].name}")
                        self.stdout.write(f"   Parcel: {parcel.name} ({parcel.area} ha)")
                        self.stdout.write(f"   Transparency Events: {len(transparency_events)}")

                        for event_name in transparency_events:
                            self.stdout.write(f"     ✅ {event_name}")

                        created_count += 1

                    except CropType.DoesNotExist:
                        self.stdout.write(f"❌ Crop {config['crop_name']} not found")
                        continue
                    except Exception as e:
                        self.stdout.write(f"❌ Error creating {config['crop_name']}: {e}")
                        continue

            self.stdout.write(f"\n🎉 SUCCESS: Created {created_count}/5 test productions")
            self.stdout.write("\n📱 QR TESTING INSTRUCTIONS:")
            self.stdout.write("1. Navigate to Production List in admin or app")
            self.stdout.write("2. Find the test productions created above")
            self.stdout.write("3. Generate QR codes for each production")
            self.stdout.write("4. Scan QR codes to test ProductDetail.tsx transparency display")
            self.stdout.write("5. Verify transparency content shows properly on mobile")

        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"❌ User {user_email} not found"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Unexpected error: {e}"))

    def get_transparency_events(self, template):
        """Get list of event names that have transparency data"""
        transparency_events = []
        events = EventTemplate.objects.filter(production_template=template)

        for event in events:
            if event.typical_amounts and "consumer_transparency" in event.typical_amounts:
                transparency_events.append(event.name)

        return transparency_events
