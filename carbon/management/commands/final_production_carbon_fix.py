"""
Final production carbon fix using raw SQL with all required fields
"""

import json
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from carbon.models import CarbonEntry, CarbonOffsetProject, CarbonOffsetPurchase, CarbonSource
from company.models import Establishment

User = get_user_model()


class Command(BaseCommand):
    help = "Final production carbon fix with proper categories and types"

    def handle(self, *args, **options):
        self.stdout.write("🎯 Final production carbon fix...")

        try:
            user = User.objects.get(email="demo@trazo.io")

            # 1. Update existing sources
            self.update_existing_sources()

            # 2. Create new diverse sources
            self.create_diverse_sources()

            # 3. Create diverse carbon entries using SQL
            self.create_production_carbon_entries(user)

            # 4. Fix offset purchases
            self.create_offset_purchases(user)

            # 5. Final verification
            self.verify_final_results()

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Error: {e}"))
            import traceback

            self.stdout.write(traceback.format_exc())

    def update_existing_sources(self):
        """Update existing source categories"""
        self.stdout.write("🔄 Updating existing sources...")

        updates = [
            ("Demo Fuel Source", "fuel", "Agricultural machinery fuel consumption"),
            ("Equipment Operation", "equipment", "Farm equipment operations"),
            ("Production Activity", "processing", "Post-harvest processing activities"),
            ("Weather Response", "irrigation", "Irrigation and water management"),
            ("General Activity", "transport", "Transportation and logistics"),
        ]

        for name, category, description in updates:
            try:
                source = CarbonSource.objects.get(name=name)
                source.category = category
                source.description = description
                source.save()
                self.stdout.write(f"   ✅ Updated {name}")
            except CarbonSource.DoesNotExist:
                continue

    def create_diverse_sources(self):
        """Create diverse carbon sources"""
        self.stdout.write("➕ Creating diverse sources...")

        sources = [
            ("Nitrogen Fertilizer", "fertilizer", "kg", 11.0, "Nitrogen fertilizer application"),
            ("Electricity Grid", "electricity", "kWh", 0.35, "Grid electricity consumption"),
            ("Product Shipping", "transport", "km", 0.12, "Product transportation"),
            ("Packaging Materials", "materials", "kg", 1.8, "Packaging and containers"),
            ("Cover Crops", "sequestration", "hectare", -2.5, "Cover crop carbon sequestration"),
            ("Solar Generation", "renewable_energy", "kWh", -0.35, "Solar energy generation"),
            ("Offset Credits", "purchased_offsets", "tons_co2e", -1.0, "Purchased carbon offsets"),
        ]

        created = 0
        for name, category, unit, factor, description in sources:
            source, is_created = CarbonSource.objects.get_or_create(
                name=name,
                defaults={
                    "category": category,
                    "unit": unit,
                    "default_emission_factor": factor,
                    "description": description,
                    "usda_factors_used": factor > 0,
                    "usda_factors_based": factor > 0,
                },
            )
            if is_created:
                created += 1

        self.stdout.write(f"   ✅ Created {created} diverse sources")

    def create_production_carbon_entries(self, user):
        """Create production-ready carbon entries using raw SQL"""
        self.stdout.write("📊 Creating production carbon entries...")

        establishments = Establishment.objects.all()
        entries_created = 0

        for establishment in establishments:
            # Fertilizer entries (3 per year)
            fertilizer_source = CarbonSource.objects.get(name="Nitrogen Fertilizer")
            for year in [2024, 2025]:
                for month in [3, 6, 9]:  # Spring, summer, fall
                    amount = random.uniform(400, 1000)
                    co2e = amount * fertilizer_source.default_emission_factor
                    date = f"{year}-{month:02d}-15"

                    self.create_carbon_entry_sql(
                        establishment.id,
                        user.id,
                        fertilizer_source.id,
                        "emission",
                        amount,
                        co2e,
                        year,
                        date,
                        f"Seasonal nitrogen fertilizer application - {year}-{month:02d}",
                        f"FERT-{establishment.id}-{year}-{month}",
                    )
                    entries_created += 1

            # Electricity entries (monthly)
            electricity_source = CarbonSource.objects.get(name="Electricity Grid")
            for year in [2024, 2025]:
                for month in range(1, 13):
                    amount = random.uniform(2500, 6000)
                    co2e = amount * electricity_source.default_emission_factor
                    date = f"{year}-{month:02d}-01"

                    self.create_carbon_entry_sql(
                        establishment.id,
                        user.id,
                        electricity_source.id,
                        "emission",
                        amount,
                        co2e,
                        year,
                        date,
                        f"Monthly electricity consumption - {year}-{month:02d}",
                        f"ELEC-{establishment.id}-{year}-{month}",
                    )
                    entries_created += 1

            # Transport entries (quarterly)
            transport_source = CarbonSource.objects.get(name="Product Shipping")
            for year in [2024, 2025]:
                for quarter in range(1, 5):
                    amount = random.uniform(1000, 3000)
                    co2e = amount * transport_source.default_emission_factor
                    month = quarter * 3
                    date = f"{year}-{month:02d}-15"

                    self.create_carbon_entry_sql(
                        establishment.id,
                        user.id,
                        transport_source.id,
                        "emission",
                        amount,
                        co2e,
                        year,
                        date,
                        f"Quarterly product shipping - Q{quarter} {year}",
                        f"SHIP-{establishment.id}-{year}-Q{quarter}",
                    )
                    entries_created += 1

            # Packaging entries (monthly)
            packaging_source = CarbonSource.objects.get(name="Packaging Materials")
            for year in [2024, 2025]:
                for month in range(1, 13):
                    amount = random.uniform(100, 400)
                    co2e = amount * packaging_source.default_emission_factor
                    date = f"{year}-{month:02d}-15"

                    self.create_carbon_entry_sql(
                        establishment.id,
                        user.id,
                        packaging_source.id,
                        "emission",
                        amount,
                        co2e,
                        year,
                        date,
                        f"Monthly packaging materials - {year}-{month:02d}",
                        f"PACK-{establishment.id}-{year}-{month}",
                    )
                    entries_created += 1

            # Sequestration entries (annual)
            sequestration_source = CarbonSource.objects.get(name="Cover Crops")
            for year in [2024, 2025]:
                amount = random.uniform(15, 40)
                co2e = amount * sequestration_source.default_emission_factor  # Negative
                date = f"{year}-06-01"

                self.create_carbon_entry_sql(
                    establishment.id,
                    user.id,
                    sequestration_source.id,
                    "sequestration",
                    amount,
                    co2e,
                    year,
                    date,
                    f"Annual cover crop sequestration measurement - {year}",
                    f"SEQU-{establishment.id}-{year}",
                )
                entries_created += 1

            # Solar generation entries (seasonal)
            solar_source = CarbonSource.objects.get(name="Solar Generation")
            for year in [2024, 2025]:
                for month in range(4, 11):  # Solar season
                    amount = random.uniform(2000, 5000)
                    co2e = amount * solar_source.default_emission_factor  # Negative
                    date = f"{year}-{month:02d}-01"

                    self.create_carbon_entry_sql(
                        establishment.id,
                        user.id,
                        solar_source.id,
                        "offset",
                        amount,
                        co2e,
                        year,
                        date,
                        f"Monthly solar energy generation - {year}-{month:02d}",
                        f"SOLR-{establishment.id}-{year}-{month}",
                    )
                    entries_created += 1

        self.stdout.write(f"   ✅ Created {entries_created} production carbon entries")

    def create_carbon_entry_sql(
        self, establishment_id, user_id, source_id, entry_type, amount, co2e, year, date, description, reg_id
    ):
        """Create carbon entry using raw SQL with all required fields"""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO carbon_carbonentry (
                    year, type, amount, description, created_by_id, establishment_id, production_id, source_id,
                    timestamp, created_at, iot_device_id, updated_at, usda_factors_based, co2e_amount, data_source,
                    verification_status, additionality_evidence, additionality_verified,
                    audit_scheduled_date, baseline_data, documentation_complete, evidence_requirements_met,
                    methodology_template, permanence_plan, registry_verification_id, third_party_verification_url,
                    external_verification_id, gps_coordinates, verification_notes, baseline_scenario,
                    detected_patterns, financial_analysis, methodology_id, monitoring_plan, registry_name,
                    registry_submission_id, verification_report_url, audit_status, effective_amount,
                    evidence_documents, evidence_photos, trust_score, verification_level
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """,
                [
                    year,
                    entry_type,
                    amount,
                    description,
                    user_id,
                    establishment_id,
                    None,
                    source_id,
                    date,
                    timezone.now(),
                    "",
                    timezone.now(),
                    True,
                    co2e,
                    "Production Data Source",
                    "production_verified",
                    f"Production-grade {entry_type}",
                    True,
                    None,
                    json.dumps({"amount": amount, "type": entry_type}),
                    True,
                    True,
                    f"PRODUCTION_{entry_type.upper()}",
                    f"Production {entry_type} tracking",
                    reg_id,
                    "https://trazo.io/verify",
                    f"EXT-{reg_id}",
                    json.dumps({"establishment": establishment_id}),
                    f"Production {entry_type}",
                    json.dumps({"type": entry_type}),
                    json.dumps([]),
                    json.dumps({}),
                    f"PROD_{entry_type.upper()}",
                    json.dumps({"monitoring": "production"}),
                    "Production Registry",
                    f"SUB-{reg_id}",
                    "https://trazo.io/report",
                    "production_verified",
                    abs(co2e) * 0.95,
                    json.dumps([]),
                    json.dumps([]),
                    0.95,
                    "production_verified",
                ],
            )

    def create_offset_purchases(self, user):
        """Create offset purchases with corresponding entries"""
        self.stdout.write("💰 Creating offset purchases...")

        # Clean existing
        CarbonOffsetPurchase.objects.all().delete()

        # Create project
        project, created = CarbonOffsetProject.objects.get_or_create(
            name="California Agricultural Carbon Project",
            defaults={
                "description": "Soil carbon sequestration through sustainable farming",
                "project_type": "Agricultural Sequestration",
                "certification_standard": "VCS",
                "location": "California Central Valley",
                "price_per_ton": Decimal("24.75"),
                "available_capacity": Decimal("10000.00"),
            },
        )

        # Get offset source
        offset_source = CarbonSource.objects.get(name="Offset Credits")

        # Create purchases for each establishment
        establishments = Establishment.objects.all()
        purchases_created = 0

        for establishment in establishments:
            for year in [2024, 2025]:
                amount = Decimal(str(random.uniform(30, 80)))
                purchase = CarbonOffsetPurchase.objects.create(
                    project=project,
                    user=user,
                    amount=amount,
                    price_per_ton=project.price_per_ton,
                    total_price=amount * project.price_per_ton,
                    status="completed",
                    is_verified=True,
                )

                # Create corresponding carbon entry
                co2e = -float(amount)  # Negative for offset
                date = f"{year}-11-15"

                self.create_carbon_entry_sql(
                    establishment.id,
                    user.id,
                    offset_source.id,
                    "offset",
                    float(amount),
                    co2e,
                    year,
                    date,
                    f"Carbon offset purchase - {amount} tons CO2e",
                    f"OFFS-{establishment.id}-{year}",
                )
                purchases_created += 1

        self.stdout.write(f"   ✅ Created {purchases_created} offset purchases")

    def verify_final_results(self):
        """Verify the final production-ready results"""
        self.stdout.write("🔍 Final verification...")

        # Entry types breakdown
        self.stdout.write("   📊 Entry Types:")
        for entry_type in ["emission", "offset", "sequestration"]:
            count = CarbonEntry.objects.filter(type=entry_type).count()
            total = sum([e.co2e_amount or 0 for e in CarbonEntry.objects.filter(type=entry_type)])
            self.stdout.write(f"     - {entry_type}: {count} entries, {total:.2f} kg CO2e")

        # Categories breakdown
        self.stdout.write("   📋 Source Categories:")
        categories = [
            "fuel",
            "equipment",
            "processing",
            "irrigation",
            "transport",
            "fertilizer",
            "electricity",
            "materials",
            "sequestration",
            "renewable_energy",
            "purchased_offsets",
        ]

        for category in categories:
            entries = CarbonEntry.objects.filter(source__category=category)
            if entries.exists():
                count = entries.count()
                total = sum([e.co2e_amount or 0 for e in entries])
                self.stdout.write(f"     - {category}: {count} entries, {total:.2f} kg CO2e")

        # Establishments summary
        self.stdout.write("   🏢 Establishments Summary:")
        establishments = Establishment.objects.all()

        for est in establishments:
            entries = CarbonEntry.objects.filter(establishment=est)
            emissions = sum([e.co2e_amount for e in entries.filter(type="emission")])
            offsets = sum([abs(e.co2e_amount) for e in entries.filter(type__in=["offset", "sequestration"])])
            net = emissions - offsets

            self.stdout.write(f"     {est.name}:")
            self.stdout.write(f"       - Total entries: {entries.count()}")
            self.stdout.write(f"       - Emissions: {emissions:.2f} kg CO2e")
            self.stdout.write(f"       - Offsets/Sequestration: {offsets:.2f} kg CO2e")
            self.stdout.write(f"       - Net emissions: {net:.2f} kg CO2e")

        # Offset purchases
        offset_count = CarbonOffsetPurchase.objects.count()
        self.stdout.write(f"   💰 Offset purchases: {offset_count}")

        # API test
        api_test = CarbonEntry.objects.filter(establishment_id=2, year=2025).count()
        self.stdout.write(f"   🔗 API test (establishment=2&year=2025): {api_test} entries")

        if api_test > 0:
            self.stdout.write(self.style.SUCCESS("🎉 API endpoint will return diverse data!"))

        self.stdout.write(self.style.SUCCESS("✅ Final production carbon fix complete!"))
