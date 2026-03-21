"""
Ultimate Trazo Demo Data Seeder - Production-Ready Showcase
===========================================================

Creates comprehensive, realistic agricultural data that highlights all Trazo features:
- Accurate carbon calculations based on real USDA emission factors
- Multiple production cycles showing trends and ROI
- Compelling storytelling for different farm types
- Realistic financial metrics and premium pricing achievements
- Complete blockchain verification and transparency
- Extensive consumer engagement and reviews
- IoT integration with real-time monitoring
- Carbon offset marketplace integration
- Sustainability badges and certifications
- Complete audit trail and compliance data

This data is designed to impress potential Trazo users and demonstrate
clear ROI and competitive advantages.
"""

import datetime
import random
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from carbon.models import (
    AutomationRule,
    CarbonBenchmark,
    CarbonCertification,
    CarbonEntry,
    CarbonOffsetProject,
    CarbonOffsetPurchase,
    CarbonReport,
    CarbonSource,
    IoTDataPoint,
    IoTDevice,
    SustainabilityBadge,
)
from company.models import Company, Establishment
from history.models import (
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    HistoryScan,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
)
from product.models import Parcel, Product
from reviews.models import Review
from subscriptions.models import Plan, Subscription
from users.models import WorksIn

User = get_user_model()


class Command(BaseCommand):
    help = "Create ultimate Trazo demo data - production-ready showcase for potential users"

    def __init__(self):
        super().__init__()
        self.carbon_entries_created = 0
        self.events_created = 0
        self.productions_created = 0
        self.reviews_created = 0
        self.scans_created = 0

        # USDA-verified emission factors (kg CO2e per unit)
        self.emission_factors = {
            "nitrogen_fertilizer": 11.0,  # kg CO2e per kg N
            "phosphorus_fertilizer": 1.25,  # kg CO2e per kg P2O5
            "potassium_fertilizer": 0.6,  # kg CO2e per kg K2O
            "organic_compost": 0.28,  # kg CO2e per kg
            "diesel_fuel": 2.70,  # kg CO2e per liter
            "electricity_grid": 0.429,  # kg CO2e per kWh (US average)
            "electricity_renewable": -0.02,  # kg CO2e per kWh (slight benefit)
            "transportation": 0.12,  # kg CO2e per km per kg
            "packaging_cardboard": 1.05,  # kg CO2e per kg
            "packaging_plastic": 1.8,  # kg CO2e per kg
            "cold_storage": 0.45,  # kg CO2e per kWh
            "cover_crop_sequestration": -2.5,  # kg CO2e per hectare per year
            "no_till_sequestration": -0.7,  # kg CO2e per hectare per year
            "tree_sequestration": -22.0,  # kg CO2e per mature tree per year
        }

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear-existing",
            action="store_true",
            help="Clear existing demo data before creating new data",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("🌟 Creating ULTIMATE Trazo Demo Data - Production Showcase 🌟"))

        if options["clear_existing"]:
            self.clear_existing_demo_data()

        with transaction.atomic():
            # Phase 1: Foundation
            self.stdout.write(self.style.SUCCESS("\n📋 Phase 1: Foundation Setup"))
            user = self.create_demo_user()
            company = self.create_demo_company()
            self.create_work_relationship(user, company)
            subscription = self.create_subscription(company)

            # Phase 2: Carbon Framework
            self.stdout.write(self.style.SUCCESS("\n🌍 Phase 2: Carbon Framework"))
            self.create_comprehensive_carbon_sources()
            self.create_carbon_benchmarks()

            # Phase 3: Farm Infrastructure
            self.stdout.write(self.style.SUCCESS("\n🏭 Phase 3: Farm Infrastructure"))
            establishment1 = self.create_premium_citrus_ranch(company)
            establishment2 = self.create_organic_innovation_farm(company)
            establishment3 = self.create_regenerative_grain_farm(company)

            parcels_1 = self.create_citrus_ranch_parcels(establishment1)
            parcels_2 = self.create_organic_farm_parcels(establishment2)
            parcels_3 = self.create_grain_farm_parcels(establishment3)

            # Phase 4: Product Catalog
            self.stdout.write(self.style.SUCCESS("\n📦 Phase 4: Product Catalog"))
            products = self.create_comprehensive_product_catalog()

            # Phase 5: Production Cycles (Multi-year with trends)
            self.stdout.write(self.style.SUCCESS("\n🌱 Phase 5: Multi-Year Production Cycles"))
            all_productions = []

            # Create 3 years of production data to show trends
            for year_offset in [730, 365, 0]:  # 2022, 2023, 2024
                year_label = 2024 - (year_offset // 365)
                self.stdout.write(f"   📅 Creating {year_label} production cycle...")

                year_productions = []

                # Establishment 1: Premium Citrus Ranch
                year_productions.extend(
                    self.create_valencia_orange_production(
                        parcels_1[0], products["valencia_orange"], user, year_offset, year_label
                    )
                )
                year_productions.extend(
                    self.create_navel_orange_production(
                        parcels_1[1], products["navel_orange"], user, year_offset, year_label
                    )
                )
                year_productions.extend(
                    self.create_premium_almond_production(
                        parcels_1[2], products["nonpareil_almond"], user, year_offset, year_label
                    )
                )

                # Establishment 2: Organic Innovation Farm
                year_productions.extend(
                    self.create_hass_avocado_production(
                        parcels_2[0], products["hass_avocado"], user, year_offset, year_label
                    )
                )
                year_productions.extend(
                    self.create_organic_strawberry_production(
                        parcels_2[1], products["organic_strawberry"], user, year_offset, year_label
                    )
                )
                year_productions.extend(
                    self.create_hydroponic_lettuce_production(
                        parcels_2[2], products["butter_lettuce"], user, year_offset, year_label
                    )
                )

                # Establishment 3: Regenerative Grain Farm
                year_productions.extend(
                    self.create_regenerative_wheat_production(
                        parcels_3[0], products["organic_wheat"], user, year_offset, year_label
                    )
                )
                year_productions.extend(
                    self.create_cover_crop_production(
                        parcels_3[1], products["cover_crop_mix"], user, year_offset, year_label
                    )
                )

                all_productions.extend(year_productions)

            # Phase 6: Advanced Technology Integration
            self.stdout.write(self.style.SUCCESS("\n📡 Phase 6: IoT & Technology Integration"))
            self.create_advanced_iot_infrastructure(establishment1, establishment2, establishment3, user)
            self.create_automated_carbon_monitoring(all_productions, user)

            # Phase 7: Carbon Marketplace & Offsets
            self.stdout.write(self.style.SUCCESS("\n💰 Phase 7: Carbon Marketplace"))
            self.create_carbon_offset_marketplace([establishment1, establishment2, establishment3], user)
            self.create_carbon_credit_generation(all_productions, user)

            # Phase 8: Compliance & Certifications
            self.stdout.write(self.style.SUCCESS("\n🏆 Phase 8: Certifications & Compliance"))
            self.create_comprehensive_certifications(all_productions)
            self.create_sustainability_achievement_badges(all_productions)
            self.create_carbon_reports_with_trends(all_productions, [establishment1, establishment2, establishment3])

            # Phase 9: Consumer Experience
            self.stdout.write(self.style.SUCCESS("\n👥 Phase 9: Consumer Engagement"))
            self.create_consumer_users()
            self.create_extensive_scan_activity(all_productions)
            self.create_compelling_reviews_and_stories(all_productions)

            # Phase 10: Financial Performance
            self.stdout.write(self.style.SUCCESS("\n💸 Phase 10: Financial Performance"))
            self.calculate_and_apply_premium_pricing(all_productions)
            self.create_roi_analysis(all_productions, [establishment1, establishment2, establishment3])

            # Phase 11: Blockchain & Verification
            self.stdout.write(self.style.SUCCESS("\n⛓️  Phase 11: Blockchain Verification"))
            self.create_blockchain_verification_network(all_productions)

            # Phase 12: Publishing & QR Generation
            self.stdout.write(self.style.SUCCESS("\n📱 Phase 12: QR Codes & Publishing"))
            self.publish_productions_with_qr_codes(all_productions)

            # Final Analysis & Demo Summary
            self.create_ultimate_demo_summary(
                company, user, all_productions, [establishment1, establishment2, establishment3]
            )

    def clear_existing_demo_data(self):
        """Clear existing demo data"""
        self.stdout.write("🧹 Clearing existing demo data...")

        # Delete in proper order to avoid foreign key constraints
        Review.objects.filter(user__email="demo@trazo.io").delete()
        HistoryScan.objects.filter(
            history__parcel__establishment__company__name="GreenHarvest Agricultural Enterprises"
        ).delete()
        CarbonEntry.objects.filter(establishment__company__name="GreenHarvest Agricultural Enterprises").delete()
        CarbonOffsetPurchase.objects.filter(user__email="demo@trazo.io").delete()
        IoTDataPoint.objects.filter(
            device__establishment__company__name="GreenHarvest Agricultural Enterprises"
        ).delete()
        IoTDevice.objects.filter(establishment__company__name="GreenHarvest Agricultural Enterprises").delete()

        # Delete productions and related data
        History.objects.filter(parcel__establishment__company__name="GreenHarvest Agricultural Enterprises").delete()
        Parcel.objects.filter(establishment__company__name="GreenHarvest Agricultural Enterprises").delete()
        Establishment.objects.filter(company__name="GreenHarvest Agricultural Enterprises").delete()

        # Delete company and user
        Company.objects.filter(name="GreenHarvest Agricultural Enterprises").delete()
        User.objects.filter(email="demo@trazo.io").delete()

        # Clear carbon framework data to ensure fresh data
        CarbonBenchmark.objects.all().delete()
        CarbonSource.objects.all().delete()

        self.stdout.write("   ✅ Existing demo data cleared")

    def create_demo_user(self):
        """Create the ultimate demo user with full profile"""
        user, created = User.objects.get_or_create(
            email="oscar@trazo.io",
            defaults={
                "first_name": "Sarah",
                "last_name": "Martinez",
                "is_active": True,
            },
        )
        if created:
            user.set_password("om123456")
            user.save()

        self.stdout.write(f"   ✅ Demo user: {user.email} (password: TrazoDemo2025!)")
        return user

    def create_demo_company(self):
        """Create flagship demo company showcasing all Trazo benefits"""
        company, _ = Company.objects.get_or_create(
            name="GreenHarvest Agricultural Enterprises",
            defaults={
                "tradename": "GreenHarvest Farms",
                "description": "Leading sustainable agriculture operation pioneering carbon-negative farming. Operates 2,100+ acres across California with complete supply chain transparency, premium market access, and 40% above-market pricing through verified sustainability practices.",
                "address": "15847 Carbon Neutral Agriculture Boulevard",
                "city": "Fresno",
                "state": "California",
                "zip_code": "93711",
                "country": "USA",
                "contact_phone": "+1-559-872-9699",
                "contact_email": "transparency@greenharvest.com",
                "website": "https://greenharvest.com",
                "facebook": "https://facebook.com/GreenHarvestFarms",
                "instagram": "https://instagram.com/greenharvest_sustainable",
                "employee_count": 125,
                "industry": "Regenerative Agriculture & Carbon Sequestration",
                "legal_structure": "Certified B-Corporation LLC",
                "sustainability_commitment": "Carbon Negative by 2025 - Currently at 78% reduction",
                "blockchain_subscription_status": True,
                "primary_commodities": "Premium Citrus, Tree Nuts, Organic Vegetables, Carbon Credits",
                "certifications": "USDA Organic, Regenerative Organic Certified, Carbon Trust Standard, B-Corp Certified, Fair Trade USA, Rainforest Alliance",
                "sustainability_metadata": {
                    "carbon_negative_since": "2023",
                    "premium_pricing_achieved": "42%",
                    "water_reduction": "58%",
                    "soil_carbon_increase": "35%",
                    "biodiversity_index": "91/100",
                    "worker_satisfaction": "96%",
                    "customer_retention": "94%",
                    "carbon_credits_generated": "2,847 tons CO2e",
                    "blockchain_verifications": "100% of production",
                    "traceability_score": "99.7%",
                    "annual_revenue": "$24.5M",
                    "twitter": "https://twitter.com/GreenHarvestCA",
                },
            },
        )

        self.stdout.write(f"   ✅ Flagship company: {company.name}")
        return company

    def create_work_relationship(self, user, company):
        """Create work relationship between user and company"""
        work_relationship, _ = WorksIn.objects.get_or_create(
            user=user,
            company=company,
            defaults={
                "role": "CA",  # Company Admin
            },
        )
        self.stdout.write(f"   ✅ Work relationship: {user.email} → {company.name}")
        return work_relationship

    def create_subscription(self, company):
        """Create enterprise subscription showcasing full platform value"""
        # Handle case where multiple plans exist with same name
        try:
            plan = Plan.objects.filter(name="Enterprise").first()
            if not plan:
                plan = Plan.objects.create(
                    name="Enterprise",
                    slug="enterprise",
                    description="Enterprise tier with unlimited features, dedicated support, and custom analytics",
                    price=float(Decimal("499.00")),
                    interval="monthly",
                    features={
                        "unlimited_establishments": True,
                        "unlimited_parcels": True,
                        "unlimited_productions": True,
                        "unlimited_scans": True,
                        "unlimited_storage": True,
                        "carbon_tracking": True,
                        "blockchain_verification": True,
                        "advanced_analytics": True,
                        "custom_reporting": True,
                        "api_access": True,
                        "iot_integration": True,
                        "usda_verification": True,
                        "carbon_offset_marketplace": True,
                        "white_label_options": True,
                        "dedicated_support": True,
                        "custom_integrations": True,
                        "multi_language_support": True,
                        "advanced_security": True,
                        "audit_compliance": True,
                        "premium_certifications": True,
                    },
                )
        except Exception as e:
            # If there are multiple plans, just use the first one
            plan = Plan.objects.filter(name="Enterprise").first()

        subscription, _ = Subscription.objects.get_or_create(
            company=company,
            defaults={
                "plan": plan,
                "status": "active",
                "current_period_start": timezone.now() - datetime.timedelta(days=750),  # Customer for 2+ years
                "current_period_end": timezone.now() + datetime.timedelta(days=30),
                "used_productions": 47,  # Heavy usage showing value
                "used_storage_gb": float(Decimal("1247.8")),
                "scan_count": 28459,  # High consumer engagement
                "stripe_subscription_id": "sub_enterprise_demo_12345",
            },
        )

        self.stdout.write(f"   ✅ Enterprise subscription: ${plan.price}/month - {subscription.scan_count:,} scans")
        return subscription

    def create_comprehensive_carbon_sources(self):
        """Create comprehensive, USDA-verified carbon sources"""
        self.stdout.write("   🔧 Setting up carbon calculation framework...")

        sources_data = [
            # Fertilizer emissions (major source in agriculture)
            (
                "Nitrogen Fertilizer (Synthetic)",
                "fertilizer",
                "kg_n",
                11.0,
                "IPCC Tier 1 - Synthetic nitrogen fertilizer production and N2O emissions",
            ),
            (
                "Phosphorus Fertilizer (P2O5)",
                "fertilizer",
                "kg_p2o5",
                1.25,
                "Life cycle emissions from phosphate rock mining and processing",
            ),
            (
                "Potassium Fertilizer (K2O)",
                "fertilizer",
                "kg_k2o",
                0.6,
                "Potash mining, processing and transportation emissions",
            ),
            ("Organic Compost", "fertilizer", "kg", 0.28, "Composting process emissions minus soil carbon benefits"),
            (
                "Liquid Organic Fertilizer",
                "fertilizer",
                "liters",
                0.35,
                "Liquid organic fertilizer production and application",
            ),
            # Fuel emissions (equipment operations)
            ("Diesel Fuel", "fuel", "liters", 2.70, "Combustion emissions from agricultural diesel fuel"),
            ("Gasoline", "fuel", "liters", 2.32, "Combustion emissions from gasoline equipment"),
            ("Propane", "fuel", "kg", 3.0, "Propane combustion for heating and drying"),
            ("Natural Gas", "fuel", "m3", 1.92, "Natural gas combustion emissions"),
            # Energy emissions
            ("Grid Electricity", "electricity", "kWh", 0.429, "US average grid electricity emissions (EPA eGRID)"),
            ("Solar Electricity", "electricity", "kWh", 0.041, "Solar PV lifecycle emissions"),
            # Equipment operations
            ("Tractor Operations", "equipment", "hours", 8.5, "Tractor fuel consumption and maintenance emissions"),
            ("Harvesting Equipment", "equipment", "hours", 12.3, "Combine harvester and specialized equipment"),
            ("Irrigation Pump", "equipment", "hours", 4.2, "Irrigation pump electricity and maintenance"),
            ("Cold Storage Operations", "processing", "kWh", 0.45, "Refrigeration energy consumption"),
            # Transportation
            ("Local Transportation", "transportation", "km_ton", 0.12, "Local farm-to-market transportation"),
            ("Long Distance Transport", "transportation", "km_ton", 0.089, "Efficient long-distance transportation"),
            ("Air Freight", "transportation", "km_ton", 1.15, "Air transportation for premium exports"),
            # Materials and packaging
            ("Cardboard Packaging", "packaging", "kg", 1.05, "Corrugated cardboard box production"),
            ("Plastic Packaging", "packaging", "kg", 1.8, "Plastic film and container production"),
            ("Wooden Crates", "packaging", "kg", 0.72, "Wooden packaging materials"),
            # Processing
            ("Washing and Cleaning", "processing", "kg_product", 0.08, "Water heating and processing emissions"),
            ("Sorting and Grading", "processing", "kg_product", 0.05, "Automated sorting equipment energy"),
            ("Drying Operations", "processing", "kg_product", 0.35, "Thermal drying energy consumption"),
            # Carbon sequestration and offsets (negative values)
            (
                "Cover Crop Sequestration",
                "sequestration",
                "hectare_year",
                -2.5,
                "Annual soil carbon sequestration from cover crops",
            ),
            (
                "Tree Carbon Sequestration",
                "sequestration",
                "tree_year",
                -22.0,
                "Annual carbon storage in mature fruit trees",
            ),
            (
                "No-Till Soil Carbon",
                "sequestration",
                "hectare_year",
                -0.7,
                "Soil carbon preservation from no-till practices",
            ),
            (
                "Compost Application",
                "sequestration",
                "ton_compost",
                -0.5,
                "Soil carbon increase from compost application",
            ),
            ("Regenerative Grazing", "sequestration", "hectare_year", -1.8, "Soil carbon from managed grazing"),
            # Renewable energy and efficiency
            (
                "Solar Panel Generation",
                "renewable_energy",
                "kWh",
                -0.388,
                "Grid electricity offset by solar generation",
            ),
            ("Wind Energy", "renewable_energy", "kWh", -0.385, "Grid electricity offset by wind power"),
            ("Energy Efficiency Gains", "efficiency", "kWh_saved", -0.429, "Emissions avoided through efficiency"),
            # Purchased offsets
            (
                "Forest Conservation Offsets",
                "purchased_offsets",
                "tons_co2e",
                -1.0,
                "Third-party verified forest conservation",
            ),
            ("Renewable Energy Credits", "purchased_offsets", "mWh", -0.429, "Renewable energy certificates"),
        ]

        sources_created = 0
        for name, category, unit, factor, description in sources_data:
            source, created = CarbonSource.objects.get_or_create(
                name=name,
                defaults={
                    "category": category,
                    "unit": unit,
                    "default_emission_factor": float(Decimal(str(factor))),
                    "description": description,
                    "usda_factors_used": abs(factor) > 0.01,  # All significant factors are verified
                    "usda_factors_based": abs(factor) > 0.01,
                    "verification_status": "factors_verified" if abs(factor) > 0.01 else "estimated",
                    "data_source": "USDA Agricultural Research Service / EPA / IPCC Guidelines",
                },
            )
            if created:
                sources_created += 1

        self.stdout.write(f"   ✅ Created {sources_created} carbon sources with USDA verification")

    def create_carbon_benchmarks(self):
        """Create industry benchmarks for comparison"""
        self.stdout.write("   📊 Creating industry carbon benchmarks...")

        benchmarks_data = [
            ("Citrus Production", 2025, 0.42, 0.25, 0.68, "kg CO2e per kg fruit", "Valencia and Navel oranges"),
            ("Tree Nut Production", 2025, 0.58, 0.35, 0.85, "kg CO2e per kg nuts", "Almonds and walnuts"),
            ("Avocado Production", 2025, 0.35, 0.22, 0.55, "kg CO2e per kg fruit", "Hass avocados"),
            ("Berry Production", 2025, 0.28, 0.18, 0.45, "kg CO2e per kg berries", "Strawberries and blueberries"),
            ("Leafy Greens", 2025, 0.15, 0.08, 0.28, "kg CO2e per kg greens", "Lettuce and spinach"),
            ("Grain Production", 2025, 0.32, 0.18, 0.52, "kg CO2e per kg grain", "Wheat and barley"),
        ]

        for industry, year, avg, min_val, max_val, unit, description in benchmarks_data:
            CarbonBenchmark.objects.get_or_create(
                industry=industry,
                year=year,
                defaults={
                    "average_emissions": float(Decimal(str(avg))),
                    "min_emissions": float(Decimal(str(min_val))),
                    "max_emissions": float(Decimal(str(max_val))),
                    "unit": unit,
                    "company_count": random.randint(250, 450),
                    "source": "USDA Agricultural Research Service 2024",
                    "usda_factors_used": True,
                    "crop_type": description,
                },
            )

        self.stdout.write("   ✅ Industry benchmarks established")

    def create_premium_citrus_ranch(self, company):
        """Create flagship premium citrus operation - the success story"""
        establishment, _ = Establishment.objects.get_or_create(
            company=company,
            name="GreenHarvest Premium Citrus Ranch",
            defaults={
                "description": "Award-winning 950-acre premium citrus operation generating $18.2M annually with 45% premium pricing through verified carbon-negative practices. Industry leader in regenerative agriculture with complete supply chain transparency.",
                "address": "15847 Carbon Neutral Agriculture Boulevard",
                "city": "Fresno",
                "state": "California",
                "zip_code": "93711",
                "country": "USA",
                "latitude": float(Decimal("36.7378")),
                "longitude": float(Decimal("-119.7871")),
                "phone": "+1-559-248-7871",
                "email": "citrus@greenharvest.com",
                "contact_phone": "+1-559-248-7871",
                "contact_email": "citrus@greenharvest.com",
                "about": "75 years of citrus excellence meets cutting-edge sustainability. Our carbon-negative operations demonstrate how agriculture can be part of the climate solution while achieving premium market pricing.",
                "custom_message": "Every orange tells a story of regenerative farming, verified carbon sequestration, and transparent supply chains. Scan to see the complete journey from tree to table.",
                "total_acreage": 950.0,
                "employee_count": 45,
                "year_established": 1948,
                "establishment_type": "Premium Citrus Ranch",
                "farming_method": "Regenerative Agriculture",
                "crops_grown": ["Premium Valencia Oranges", "Navel Oranges", "Specialty Almonds"],
                "sustainability_practices": [
                    "Carbon-negative certified",
                    "Solar-powered operations",
                    "Regenerative soil management",
                    "Precision agriculture",
                    "Blockchain transparency",
                ],
                "water_sources": [
                    "Smart irrigation with AI optimization",
                    "Groundwater wells",
                    "Recycled water system",
                ],
                "soil_types": ["Hanford Sandy Loam", "Dinuba Clay Loam", "Tujunga Loamy Sand"],
                "conservation_practices": [
                    "Cover crops",
                    "No-till farming",
                    "Beneficial microorganism inoculation",
                    "Buffer strips",
                ],
                "irrigation_methods": [
                    "Micro-sprinkler with soil sensors",
                    "Precision drip with fertigation",
                    "Subsurface drip automation",
                ],
                "certifications": "Carbon Trust Standard, Regenerative Organic Certified, GlobalGAP, SQF Level 2, Rainforest Alliance",
                "main_activities": "Premium citrus production, Carbon credit generation, Agritourism, Direct-to-consumer sales",
                "location_highlights": "Solar-powered operations, Beneficial insect habitat, Carbon demonstration plots, Blockchain verified supply chain",
            },
        )

        self.stdout.write(f"   ✅ Premium Citrus Ranch: {establishment.total_acreage} acres, Premium operation")
        return establishment

    def create_organic_innovation_farm(self, company):
        """Create cutting-edge organic innovation center"""
        establishment, _ = Establishment.objects.get_or_create(
            company=company,
            name="GreenHarvest Organic Innovation Center",
            defaults={
                "description": "Revolutionary 450-acre certified organic research facility pioneering next-generation sustainable agriculture. Combines traditional organic practices with AI, IoT, and precision agriculture to achieve 70% higher yields than conventional organic.",
                "address": "8932 Innovation Valley Road",
                "city": "Salinas",
                "state": "California",
                "zip_code": "93901",
                "country": "USA",
                "latitude": float(Decimal("36.6777")),
                "longitude": float(Decimal("-121.6555")),
                "phone": "+1-831-674-2642",
                "email": "innovation@greenharvest.com",
                "contact_phone": "+1-831-674-2642",
                "contact_email": "innovation@greenharvest.com",
                "about": "Where tradition meets innovation. Our certified organic operations use cutting-edge technology to prove that sustainable farming can outperform conventional agriculture in both yield and profitability.",
                "custom_message": "Experience the future of organic agriculture. Every product is grown with zero synthetic inputs while achieving superior yields through innovation and technology.",
                "total_acreage": 450.0,
                "employee_count": 28,
                "year_established": 2015,
                "establishment_type": "Organic Research Center",
                "farming_method": "Certified Organic + AI Technology",
                "crops_grown": ["Organic Avocados", "Organic Strawberries", "Organic Leafy Greens", "Organic Herbs"],
                "sustainability_practices": [
                    "USDA Organic Certified",
                    "Biodynamic principles",
                    "AI-powered optimization",
                    "Zero waste operations",
                    "Renewable energy",
                ],
                "water_sources": ["Rainwater harvesting", "Greywater recycling", "Precision irrigation"],
                "soil_types": ["Salinas Clay", "Pacheco Clay", "Yolo Loam"],
                "conservation_practices": [
                    "Composting facility",
                    "Biodiversity corridors",
                    "Pollinator habitat",
                    "Soil carbon sequestration",
                ],
                "irrigation_methods": ["Precision drip irrigation", "Micro-sprinkler systems", "Soil moisture sensors"],
                "certifications": "USDA Organic, Demeter Biodynamic, CCOF, Rainforest Alliance, Carbon Trust Standard",
                "main_activities": "Organic research, Premium produce, Technology development, Education programs",
                "location_highlights": "IoT sensor networks, AI crop monitoring, Renewable energy systems, Research partnerships",
            },
        )

        self.stdout.write(f"   ✅ Organic Innovation Center: {establishment.total_acreage} acres, Technology leader")
        return establishment

    def create_regenerative_grain_farm(self, company):
        """Create regenerative grain operation showcasing carbon farming"""
        establishment, _ = Establishment.objects.get_or_create(
            company=company,
            name="GreenHarvest Regenerative Grain Ranch",
            defaults={
                "description": "875-acre regenerative grain operation demonstrating large-scale carbon farming. Generates substantial revenue from both grain sales and carbon credit sales while rebuilding prairie ecosystems.",
                "address": "4521 Carbon Valley Highway",
                "city": "Bakersfield",
                "state": "California",
                "zip_code": "93308",
                "country": "USA",
                "latitude": float(Decimal("35.3733")),
                "longitude": float(Decimal("-119.0187")),
                "phone": "+1-661-227-2665",
                "email": "regenerative@greenharvest.com",
                "contact_phone": "+1-661-227-2665",
                "contact_email": "regenerative@greenharvest.com",
                "about": "Proving that grain farming can be a powerful tool for climate action. Our regenerative practices sequester massive amounts of carbon while producing premium grains for discerning markets.",
                "custom_message": "Every grain represents carbon pulled from the atmosphere and stored in healthy soil. Our products feed people while healing the planet.",
                "total_acreage": 875.0,
                "employee_count": 18,
                "year_established": 2010,
                "establishment_type": "Regenerative Grain Ranch",
                "farming_method": "Regenerative Agriculture",
                "crops_grown": ["Regenerative Wheat", "Cover Crop Mixes", "Native Prairie Restoration"],
                "sustainability_practices": [
                    "Regenerative agriculture",
                    "Carbon farming",
                    "No-till operations",
                    "Diverse cover crops",
                    "Rotational grazing integration",
                ],
                "water_sources": ["Dryland farming with water harvesting", "Minimal irrigation with smart sensors"],
                "soil_types": ["Wasco Sandy Loam", "Panoche Clay Loam", "Kettleman Clay"],
                "conservation_practices": [
                    "Multi-species cover crops",
                    "Livestock integration",
                    "Mycorrhizal enhancement",
                    "Zero tillage",
                ],
                "irrigation_methods": ["Dryland farming", "Precision irrigation", "Water harvesting systems"],
                "certifications": "Regenerative Organic Certified, Carbon Cycle Institute Verified, Land to Market Certified",
                "main_activities": "Regenerative grain production, Carbon credit generation, Prairie restoration, Livestock integration",
                "location_highlights": "Carbon farming demonstration, Wildlife habitat restoration, Soil health research, Climate solutions",
            },
        )

        self.stdout.write(
            f"   ✅ Regenerative Grain Ranch: {establishment.total_acreage} acres, Carbon farming pioneer"
        )
        return establishment

    def create_citrus_ranch_parcels(self, establishment):
        """Create premium citrus ranch parcels with detailed specifications"""
        parcels = []

        parcel_configs = [
            {
                "name": "Valencia Heritage Grove",
                "area": 285.0,
                "variety": "Valencia Orange",
                "planted_year": 2016,
                "tree_count": 3420,
                "soil_type": "Hanford Sandy Loam",
                "irrigation": "Micro-sprinkler with soil sensors",
                "certifications": "Regenerative Organic Certified",
                "lat_offset": 0.0,
                "lng_offset": 0.0,
                "special_features": "Heritage variety selection, Beneficial insect habitat, Carbon demonstration plot",
            },
            {
                "name": "Navel Premium Block",
                "area": 245.0,
                "variety": "Navel Orange",
                "planted_year": 2018,
                "tree_count": 2940,
                "soil_type": "Dinuba Clay Loam",
                "irrigation": "Precision drip with fertigation",
                "certifications": "Carbon Trust Standard, GlobalGAP",
                "lat_offset": 0.01,
                "lng_offset": 0.01,
                "special_features": "High-density planting, AI-powered nutrition, Solar-powered systems",
            },
            {
                "name": "Almond Innovation Orchard",
                "area": 345.0,
                "variety": "Nonpareil Almond",
                "planted_year": 2019,
                "tree_count": 5175,
                "soil_type": "Tujunga Loamy Sand",
                "irrigation": "Subsurface drip automation",
                "certifications": "Bee-Friendly Certified, Rainforest Alliance",
                "lat_offset": 0.02,
                "lng_offset": -0.01,
                "special_features": "Pollinator corridors, Smart beehive monitoring, Water recycling system",
            },
        ]

        for config in parcel_configs:
            parcel, _ = Parcel.objects.get_or_create(
                establishment=establishment,
                name=config["name"],
                defaults={
                    "unique_code": f"GH-CR-{config['name'][:3].upper()}-2024",
                    "area": float(Decimal(str(config["area"]))),
                    "soil_type": config["soil_type"],
                    "certification_type": config["certifications"],
                    "polygon": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [
                                    float(establishment.longitude + float(str(config["lng_offset"])) - float("0.02")),
                                    float(establishment.latitude + float(str(config["lat_offset"])) - float("0.02")),
                                ],
                                [
                                    float(establishment.longitude + float(str(config["lng_offset"])) + float("0.02")),
                                    float(establishment.latitude + float(str(config["lat_offset"])) - float("0.02")),
                                ],
                                [
                                    float(establishment.longitude + float(str(config["lng_offset"])) + float("0.02")),
                                    float(establishment.latitude + float(str(config["lat_offset"])) + float("0.02")),
                                ],
                                [
                                    float(establishment.longitude + float(str(config["lng_offset"])) - float("0.02")),
                                    float(establishment.latitude + float(str(config["lat_offset"])) + float("0.02")),
                                ],
                                [
                                    float(establishment.longitude + float(str(config["lng_offset"])) - float("0.02")),
                                    float(establishment.latitude + float(str(config["lat_offset"])) - float("0.02")),
                                ],
                            ]
                        ],
                    },
                    "map_metadata": {
                        "variety": config["variety"],
                        "planted_year": config["planted_year"],
                        "tree_count": config["tree_count"],
                        "trees_per_acre": round(config["tree_count"] / config["area"]),
                        "irrigation_system": config["irrigation"],
                        "soil_health_score": random.randint(88, 96),
                        "carbon_sequestration_rate": round(random.uniform(3.8, 4.5), 1),
                        "water_efficiency_rating": "A+",
                        "biodiversity_score": random.randint(85, 94),
                        "special_features": config["special_features"],
                    },
                },
            )
            parcels.append(parcel)

        total_area = sum(config["area"] for config in parcel_configs)
        self.stdout.write(f"   ✅ Citrus ranch parcels: {len(parcels)} parcels, {total_area} acres total")
        return parcels

    def create_organic_farm_parcels(self, establishment):
        """Create organic innovation farm parcels"""
        parcels = []

        parcel_configs = [
            {
                "name": "Avocado Innovation Grove",
                "area": 125.0,
                "crop": "Hass Avocado",
                "system": "AI-optimized micro-sprinkler",
                "certification": "USDA Organic, Biodynamic",
                "special": "Drought-resistant rootstock, Smart irrigation, Companion planting",
            },
            {
                "name": "Strawberry Research Field",
                "area": 95.0,
                "crop": "Organic Strawberry",
                "system": "Substrate beds with precision fertigation",
                "certification": "USDA Organic, Zero Residue",
                "special": "Beneficial insect integration, Plastic-free mulch, Research partnership",
            },
            {
                "name": "Hydroponic Innovation Center",
                "area": 200.0,
                "crop": "Lettuce & Leafy Greens",
                "system": "Climate-controlled hydroponic towers",
                "certification": "USDA Organic, Living Building",
                "special": "95% water savings, Year-round production, Solar-powered climate control",
            },
        ]

        for i, config in enumerate(parcel_configs):
            parcel, _ = Parcel.objects.get_or_create(
                establishment=establishment,
                name=config["name"],
                defaults={
                    "unique_code": f"GH-OIC-{i+1:02d}-2024",
                    "area": float(Decimal(str(config["area"]))),
                    "soil_type": "Organic-enriched Salinas Clay Loam",
                    "certification_type": config["certification"],
                    "polygon": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [
                                    float(establishment.longitude - float("0.01") + float(str(i * 0.005))),
                                    float(establishment.latitude - float("0.01")),
                                ],
                                [
                                    float(establishment.longitude + float("0.01") + float(str(i * 0.005))),
                                    float(establishment.latitude - float("0.01")),
                                ],
                                [
                                    float(establishment.longitude + float("0.01") + float(str(i * 0.005))),
                                    float(establishment.latitude + float("0.01")),
                                ],
                                [
                                    float(establishment.longitude - float("0.01") + float(str(i * 0.005))),
                                    float(establishment.latitude + float("0.01")),
                                ],
                                [
                                    float(establishment.longitude - float("0.01") + float(str(i * 0.005))),
                                    float(establishment.latitude - float("0.01")),
                                ],
                            ]
                        ],
                    },
                    "map_metadata": {
                        "crop_type": config["crop"],
                        "production_system": config["system"],
                        "organic_certification_date": "2018-03-15",
                        "soil_biology_score": random.randint(92, 98),
                        "carbon_sequestration_rate": round(random.uniform(3.2, 4.1), 1),
                        "water_recycling_rate": random.randint(88, 96),
                        "yield_vs_conventional": f"+{random.randint(55, 85)}%",
                        "special_features": config["special"],
                    },
                },
            )
            parcels.append(parcel)

        self.stdout.write(f"   ✅ Organic farm parcels: {len(parcels)} parcels, certified organic & biodynamic")
        return parcels

    def create_grain_farm_parcels(self, establishment):
        """Create regenerative grain farm parcels"""
        parcels = []

        parcel_configs = [
            {
                "name": "Regenerative Wheat Fields",
                "area": 625.0,
                "crop": "Ancient Grain Wheat",
                "practice": "No-till, Cover crop integration",
                "carbon_rate": 5.2,
            },
            {
                "name": "Carbon Farming Research Plot",
                "area": 200.0,
                "crop": "Multi-species Cover Crops",
                "practice": "Rotational grazing, Prairie restoration",
                "carbon_rate": 7.8,
            },
        ]

        for i, config in enumerate(parcel_configs):
            parcel, _ = Parcel.objects.get_or_create(
                establishment=establishment,
                name=config["name"],
                defaults={
                    "unique_code": f"GH-RGR-{i+1:02d}-2024",
                    "area": float(Decimal(str(config["area"]))),
                    "soil_type": "Wasco Sandy Loam",
                    "certification_type": "Regenerative Organic Certified",
                    "polygon": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [
                                    float(establishment.longitude - float("0.02")),
                                    float(establishment.latitude - float("0.02")),
                                ],
                                [
                                    float(establishment.longitude + float("0.02")),
                                    float(establishment.latitude - float("0.02")),
                                ],
                                [
                                    float(establishment.longitude + float("0.02")),
                                    float(establishment.latitude + float("0.02")),
                                ],
                                [
                                    float(establishment.longitude - float("0.02")),
                                    float(establishment.latitude + float("0.02")),
                                ],
                                [
                                    float(establishment.longitude - float("0.02")),
                                    float(establishment.latitude - float("0.02")),
                                ],
                            ]
                        ],
                    },
                    "map_metadata": {
                        "crop_type": config["crop"],
                        "regenerative_practices": config["practice"],
                        "carbon_sequestration_rate": config["carbon_rate"],
                        "soil_carbon_increase": f"+{random.randint(55, 75)}%",
                        "no_till_since": "2019",
                        "cover_crop_diversity": random.randint(8, 15),
                        "carbon_credits_eligible": True,
                    },
                },
            )
            parcels.append(parcel)

        self.stdout.write(f"   ✅ Grain farm parcels: {len(parcels)} parcels, regenerative practices")
        return parcels

    def create_comprehensive_product_catalog(self):
        """Create comprehensive product catalog with premium positioning"""
        self.stdout.write("   📦 Building premium product catalog...")

        products = {}
        product_configs = [
            # Premium Citrus (keeping names under 30 characters)
            (
                "valencia_orange",
                "Premium Valencia Orange",
                "Carbon-negative premium Valencia oranges with verified sustainable practices. Perfect for fresh consumption and premium juice markets. Blockchain-verified from tree to table.",
                "kg",
            ),
            (
                "navel_orange",
                "Heritage Navel Orange",
                "Sweet, seedless Navel oranges from heritage trees. Regenerative farming practices ensure superior flavor while sequestering carbon. Premium export quality.",
                "kg",
            ),
            (
                "nonpareil_almond",
                "Premium Nonpareil Almond",
                "Gourmet Nonpareil almonds grown with bee-friendly practices. Superior blanching characteristics and exceptional taste. Carbon-neutral certified.",
                "kg",
            ),
            # Organic Innovation Products
            (
                "hass_avocado",
                "Organic Hass Avocado",
                "Certified organic Hass avocados with perfect ripeness guarantee. Grown using biodynamic principles and innovative water conservation. Zero chemical residues.",
                "kg",
            ),
            (
                "organic_strawberry",
                "Premium Organic Strawberry",
                "Pesticide-free strawberries with exceptional flavor and extended shelf life. Grown in substrate systems with beneficial insect partnerships.",
                "kg",
            ),
            (
                "butter_lettuce",
                "Hydroponic Butter Lettuce",
                "Premium butterhead lettuce grown in climate-controlled hydroponic systems. 95% water savings, year-round availability, exceptional freshness.",
                "kg",
            ),
            # Regenerative Grain Products
            (
                "organic_wheat",
                "Regenerative Wheat",
                "Ancient grain wheat varieties grown using carbon farming practices. Superior nutrition profile and exceptional baking qualities. Supports soil health.",
                "kg",
            ),
            (
                "cover_crop_mix",
                "Cover Crop Mix",
                "Specialized multi-species cover crop seeds designed for maximum carbon sequestration and soil health improvement. Research-backed blend.",
                "kg",
            ),
        ]

        for key, name, description, unit in product_configs:
            # Enhance description with unit and sustainability attributes since Product model is simple
            enhanced_description = f"{description}\n\nUnit: {unit}\nCategory: {'Premium Sustainable' if 'Premium' in name else 'Organic Certified' if 'Organic' in name else 'Regenerative'}\nAttributes: Blockchain verified, fully traceable, {'carbon-negative' if 'Premium' in name else 'certified organic' if 'Organic' in name else 'regenerative agriculture'}"

            product, _ = Product.objects.get_or_create(name=name, defaults={"description": enhanced_description})
            products[key] = product

        self.stdout.write(f"   ✅ Product catalog: {len(products)} premium products with sustainability attributes")
        return products

    # PRODUCTION CREATION METHODS WITH ACCURATE CARBON CALCULATIONS

    def create_valencia_orange_production(self, parcel, product, user, year_offset, year_label):
        """Create Valencia orange production with comprehensive carbon tracking"""
        productions = []

        # Convert parcel area to float for calculations
        area = float(parcel.area)

        # Determine if this is current, recent, or historical
        is_current = year_offset == 0
        is_recent = year_offset == 365

        # Production scaling based on year (showing improvement over time)
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.08  # 8% improvement per year
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.12  # 12% carbon efficiency improvement per year

        production = History.objects.create(
            name=f"Valencia Orange Premium Harvest {year_label}",
            parcel=parcel,
            product=product,
            type="OR",  # Orchard
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 365),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 60),
            published=not is_current,
            production_amount=int(area * 28.5 * yield_scaling),  # kg per hectare (realistic citrus yield)
            description=f"Premium Valencia oranges {year_label} - Carbon-negative production with verified regenerative practices and {int((yield_scaling - 1) * 100)}% yield improvement through sustainable intensification.",
            is_outdoor=True,
            age_of_plants=8 + (year_offset // 365),  # Trees getting older
            number_of_plants=int(area * 120),  # 120 trees per hectare
            soil_ph=float(Decimal("6.8")),
            earning=int(
                area * 28.5 * yield_scaling * 3.25 * (1 + (yield_scaling - 1) * 2)
            ),  # Premium pricing increases with sustainability
            extra_data={
                "variety": "Valencia",
                "harvest_window": "April-June",
                "quality_grade": "Premium Export",
                "premium_achieved": f"{int((yield_scaling - 1) * 100 + 35)}%",
                "carbon_negative_certified": True,
                "blockchain_verified": True,
                "certifications": ["Regenerative Organic Certified", "Carbon Trust Standard", "GlobalGAP"],
                "sustainability_score": int(85 + (yield_scaling - 1) * 30),
                "year_label": year_label,
            },
        )

        # Create comprehensive event sequence with accurate carbon calculations
        self.create_citrus_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_citrus_event_sequence_with_carbon(self, production, user, year_offset, carbon_efficiency):
        """Create realistic citrus production events with accurate carbon calculations"""

        # Convert parcel area to float for calculations
        area = float(production.parcel.area)

        # 1. SOIL PREPARATION & CARBON SEQUESTRATION (January)
        soil_prep = SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=15),
            type="CO",  # Cover crop
            description="Multi-species cover crop establishment for carbon sequestration",
            soil_ph=float(Decimal("6.8")),
            organic_matter_percentage=float(Decimal("4.2")),
            amendment_type="9-species cover crop mix (legumes, brassicas, grasses)",
            amendment_amount=f"{int(area * 25)} kg seed mix",
            carbon_sequestration_potential=float(Decimal(str(area * 2.5 * carbon_efficiency))),
            extra_data={
                "species_count": 9,
                "nitrogen_fixation_potential": f"{int(production.parcel.area * 120)} kg N/year",
                "soil_carbon_target": "40% increase by 2026",
                "biodiversity_enhancement": True,
            },
        )
        self.events_created += 1

        # Create carbon entry for cover crop sequestration (NEGATIVE emissions)
        self.create_accurate_carbon_entry(
            production,
            user,
            soil_prep,
            "Cover Crop Sequestration",
            production.parcel.area,  # hectares
            -float(production.parcel.area) * 2.5 * carbon_efficiency,  # negative CO2e
            f"Cover crop carbon sequestration - {soil_prep.amendment_type}",
        )

        # 2. ORGANIC FERTILIZATION (February)
        spring_fert = ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=45),
            type="FE",
            description="Organic citrus fertilizer application - precision targeted",
            commercial_name="OMRI Certified Citrus-Tone Organic 6-3-3",
            volume=f"{int(production.parcel.area * 400)} kg",
            concentration="6% N, 3% P2O5, 3% K2O plus micronutrients",
            area=f"{production.parcel.area} hectares",
            way_of_application="Precision banded application with soil testing guidance",
            time_period="Early morning application before rain",
            observation="Applied based on soil analysis and tree nutritional needs. Organic certification maintained.",
            extra_data={
                "n_content_kg": production.parcel.area * 24,  # 6% of 400kg/ha
                "p2o5_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "k2o_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "organic_matter_content": "85%",
                "slow_release": True,
                "soil_test_based": True,
            },
        )
        self.events_created += 1

        # Create carbon entries for organic fertilizer (much lower emissions than synthetic)
        self.create_accurate_carbon_entry(
            production,
            user,
            spring_fert,
            "Organic Compost",
            production.parcel.area * 400,  # kg of fertilizer
            production.parcel.area * 400 * 0.28,  # kg CO2e
            f"Organic fertilizer application - {spring_fert.commercial_name}",
        )

        # 3. SOLAR-POWERED IRRIGATION (March-October)
        irrigation_event = GeneralEvent.objects.create(
            history=production,
            created_by=user,
            name="AI-Optimized Solar Irrigation System",
            date=production.start_date + timezone.timedelta(days=75),
            observation=f"Precision irrigation with {int(production.parcel.area * 4)} soil moisture sensors. 65% water reduction vs industry average. 100% solar powered with battery backup.",
            extra_data={
                "sensor_count": int(production.parcel.area * 4),
                "water_savings_percentage": 65,
                "energy_source": "100% solar",
                "irrigation_efficiency": "95%",
                "total_water_m3": int(production.parcel.area * 3200),  # Reduced water usage
                "energy_consumption_kwh": int(production.parcel.area * 180),  # Annual irrigation energy
                "solar_generation_kwh": int(production.parcel.area * 220),  # Excess solar generation
            },
        )
        self.events_created += 1

        # Solar energy generates NEGATIVE emissions (offset)
        self.create_accurate_carbon_entry(
            production,
            user,
            irrigation_event,
            "Solar Panel Generation",
            production.parcel.area * 220,  # kWh generated
            -production.parcel.area * 220 * 0.388,  # negative CO2e (grid offset)
            "Solar-powered irrigation system with grid tie-in",
        )

        # 4. BENEFICIAL INSECT HABITAT (April)
        habitat_event = ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="PL",
            date=production.start_date + timezone.timedelta(days=105),
            observation=f"Established {int(production.parcel.area * 0.1)} hectares of native flowering plants. Reduced pesticide needs by 90%. Supporting 25+ beneficial species.",
            extra_data={
                "habitat_area_hectares": production.parcel.area * 0.1,
                "native_species_planted": 12,
                "beneficial_insects_supported": 25,
                "pesticide_reduction": "90%",
                "biodiversity_score_improvement": "+35%",
                "pollination_services_value": f"${int(production.parcel.area * 450)}",
            },
        )
        self.events_created += 1

        # 5. PRECISION EQUIPMENT OPERATIONS (May)
        equipment_event = EquipmentEvent.objects.create(
            history=production,
            created_by=user,
            type="FC",
            description="Precision canopy management with renewable diesel",
            date=production.start_date + timezone.timedelta(days=135),
            equipment_name="Solar-Electric Kubota M7-172 with GPS guidance",
            fuel_type="renewable_diesel",
            fuel_amount=production.parcel.area * 15,  # liters of B20 biodiesel
            area_covered=f"{production.parcel.area} hectares",
            hours_used=production.parcel.area * 0.8,
            maintenance_cost=production.parcel.area * 45,
            index=1,
            extra_data={
                "fuel_type": "B20 biodiesel (20% bio, 80% diesel)",
                "gps_precision": "2cm accuracy",
                "variable_rate_application": True,
                "emission_reduction_vs_diesel": "15%",
            },
        )
        self.events_created += 1

        # Equipment fuel consumption
        self.create_accurate_carbon_entry(
            production,
            user,
            equipment_event,
            "Diesel Fuel",
            production.parcel.area * 15,  # liters
            production.parcel.area * 15 * 2.70 * 0.85,  # CO2e with B20 reduction
            "Equipment operations with B20 biodiesel blend",
        )

        # 6. INTEGRATED PEST MANAGEMENT (June)
        ipm_event = PestManagementEvent.objects.create(
            history=production,
            created_by=user,
            description="Organic IPM Program",
            date=production.start_date + timezone.timedelta(days=165),
            type="IP",  # IPM Implementation
            pest_species="Citrus leafminer, Scale insects, Aphids",
            pest_pressure_level="Medium",
            beneficial_species="Beneficial insects + organic oils",
            release_quantity="50000 beneficial insects",
            action_threshold_met=True,
            ipm_strategy="Beneficial insect releases + organic oils targeting citrus leafminer and aphids",
            extra_data={
                "beneficial_insects_released": 50000,
                "organic_treatments": ["Neem oil", "Insecticidal soap", "Bacillus thuringiensis"],
                "pest_reduction_percentage": 95,
                "cost_vs_conventional": "-45%",
                "residue_free": True,
                "area_treated": production.parcel.area,
                "effectiveness": "high",
                "environmental_impact": "positive",
            },
        )
        self.events_created += 1

        # 7. HARVEST OPERATIONS (April-June of following year)
        if production.finish_date:  # Only for completed productions
            harvest_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                description="Premium Hand Harvest",
                type="HA",
                date=production.finish_date - timezone.timedelta(days=30),
                observation=f"Hand-picked at optimal ripeness. {production.production_amount:,} kg harvested. Premium pricing achieved. Quality: Premium Export. Destination: Premium markets + Direct-to-consumer.",
                index=7,
                extra_data={
                    "harvest_method": "selective hand picking",
                    "crew_size": 24,
                    "harvest_duration_days": 21,
                    "quality_rejection_rate": "2.1%",
                    "brix_levels": "12.8-14.5",
                    "premium_market_percentage": 85,
                    "amount": production.production_amount,
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium markets + Direct-to-consumer",
                },
            )
            self.events_created += 1

            # 8. PROCESSING & COLD STORAGE
            processing_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                description="Solar-Powered Processing & Cold Storage",
                type="PR",
                date=production.finish_date - timezone.timedelta(days=15),
                observation="Solar-powered washing, grading, and cold storage. Blockchain verification applied.",
                index=8,
                extra_data={
                    "processing_energy_kwh": production.production_amount * 0.08,
                    "cold_storage_days": 14,
                    "packaging_materials_kg": production.production_amount * 0.05,
                    "solar_energy_percentage": 100,
                    "blockchain_hash": f"0x{uuid.uuid4().hex[:16]}",
                    "traceability_score": "100%",
                    "amount": float(production.production_amount) * 0.98,
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium retail + Export markets",
                },
            )
            self.events_created += 1

            # Processing energy (solar-powered = net negative)
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Solar Panel Generation",
                float(production.production_amount) * 0.08,  # kWh
                -float(production.production_amount) * 0.08 * 0.388,  # negative CO2e
                "Solar-powered post-harvest processing",
            )

            # Packaging materials
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Cardboard Packaging",
                float(production.production_amount) * 0.05,  # kg packaging
                float(production.production_amount) * 0.05 * 1.05,  # CO2e
                "Recyclable cardboard packaging materials",
            )

    def create_accurate_carbon_entry(self, production, user, event, source_name, amount, co2e_amount, description):
        """Create accurate carbon entry with proper verification and methodology"""
        try:
            # Get carbon source
            carbon_source = CarbonSource.objects.get(name=source_name)

            # Determine entry type
            entry_type = "offset" if co2e_amount < 0 else "emission"

            # Create carbon entry with proper verification data
            carbon_entry = CarbonEntry.objects.create(
                establishment=production.parcel.establishment,
                production=production,
                created_by=user,
                source=carbon_source,
                type=entry_type,
                year=2025,  # Use 2025 as the demo year for all carbon entries
                amount=abs(amount),
                co2e_amount=co2e_amount,
                description=description,
                timestamp=event.date if hasattr(event, "date") else timezone.now(),
                usda_factors_based=True,
                verification_status="factors_verified",
                data_source="USDA Agricultural Research Service / IPCC Guidelines",
                additionality_verified=True,
                additionality_evidence=f"Verified {event.__class__.__name__} data with USDA emission factors",
                documentation_complete=True,
                evidence_requirements_met=True,
                methodology_template=f"USDA_{carbon_source.category.upper()}",
                permanence_plan="Event-based carbon tracking with verified methodologies",
                registry_verification_id=f"USDA-{production.id}-{event.id}-{carbon_source.id}",
                audit_status="passed",
                effective_amount=float(abs(co2e_amount)) * 0.95,  # 95% confidence
                evidence_documents=[],
                evidence_photos=[],
                trust_score=0.95,
                verification_level="certified_project",
            )

            self.carbon_entries_created += 1
            return carbon_entry

        except CarbonSource.DoesNotExist:
            self.stdout.write(f'      ⚠️  Carbon source "{source_name}" not found')
            return None
        except Exception as e:
            self.stdout.write(f"      ⚠️  Failed to create carbon entry: {e}")
            return None

    def create_navel_orange_production(self, parcel, product, user, year_offset, year_label):
        """Create Navel orange production with premium market focus"""
        productions = []

        is_current = year_offset == 0
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.06  # 6% improvement per year
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.10

        production = History.objects.create(
            name=f"Navel Orange Premium Export {year_label}",
            parcel=parcel,
            product=product,
            type="OR",
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 365),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 45),
            published=not is_current,
            production_amount=int(parcel.area * 32.0 * yield_scaling),  # Navels typically higher yield
            description=f"Premium Navel oranges {year_label} - Export quality with verified carbon-negative practices. Direct relationships with premium retailers achieving {int((yield_scaling - 1) * 100 + 40)}% premium pricing.",
            is_outdoor=True,
            age_of_plants=6 + (year_offset // 365),
            number_of_plants=int(parcel.area * 130),  # Higher density for Navels
            soil_ph=7.0,
            earning=int(parcel.area * 32.0 * yield_scaling * 3.85 * (1 + (yield_scaling - 1) * 2.5)),
            extra_data={
                "variety": "Navel",
                "harvest_window": "December-April",
                "quality_grade": "Premium Export",
                "export_percentage": 78,
                "premium_achieved": f"{int((yield_scaling - 1) * 100 + 40)}%",
                "carbon_negative_certified": True,
                "direct_retail_partnerships": ["Whole Foods", "Fresh Market", "Harrods London"],
                "certifications": ["Carbon Trust Standard", "GlobalGAP", "Rainforest Alliance"],
                "year_label": year_label,
            },
        )

        # Similar comprehensive event sequence as Valencia (condensed for space)
        self.create_citrus_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_premium_almond_production(self, parcel, product, user, year_offset, year_label):
        """Create premium almond production with bee-friendly practices"""
        productions = []

        is_current = year_offset == 0
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.12  # Almonds show higher improvement
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.15

        production = History.objects.create(
            name=f"Nonpareil Almond Premium {year_label}",
            parcel=parcel,
            product=product,
            type="OR",
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 400),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 30),
            published=not is_current,
            production_amount=int(parcel.area * 2.8 * yield_scaling),  # tons per hectare
            description=f"Premium Nonpareil almonds {year_label} - Bee-friendly practices with verified pollinator habitat. Industry-leading yields with carbon-neutral certification.",
            is_outdoor=True,
            age_of_plants=5 + (year_offset // 365),
            number_of_plants=int(parcel.area * 170),
            soil_ph=float(Decimal("7.2")),
            earning=int(parcel.area * 2.8 * yield_scaling * 6500),  # Premium almond pricing
            extra_data={
                "variety": "Nonpareil with Monterey pollinizers",
                "harvest_window": "August-September",
                "quality_grade": "Premium Export",
                "bee_hives_per_hectare": 5,
                "pollinator_habitat_hectares": parcel.area * 0.15,
                "yield_improvement": f"{int((yield_scaling - 1) * 100)}%",
                "bee_friendly_certified": True,
                "carbon_neutral_certified": True,
                "year_label": year_label,
            },
        )

        # Create almond-specific events
        self.create_almond_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_almond_event_sequence_with_carbon(self, production, user, year_offset, carbon_efficiency):
        """Create almond-specific event sequence"""

        # Dormant spray (January)
        dormant_spray = ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=30),
            type="PE",
            description="Organic dormant season treatment",
            commercial_name="Organic Horticultural Oil + Lime Sulfur",
            volume=f"{int(production.parcel.area * 200)} liters",
            concentration="2% horticultural oil + 1% lime sulfur",
            area=f"{production.parcel.area} hectares",
            way_of_application="High-pressure spray application",
            time_period="Dormant season - before bud break",
            observation="Organic-approved dormant treatment for scale and mite prevention",
            extra_data={"organic_approved": True, "resistance_management": True},
        )
        self.events_created += 1

        # Bee pollination service (February-March)
        pollination_event = GeneralEvent.objects.create(
            history=production,
            created_by=user,
            name="Premium Bee Pollination Service",
            date=production.start_date + timezone.timedelta(days=60),
            observation=f"Placed {int(production.parcel.area * 5)} strong bee hives. Achieved 82% nut set. Enhanced pollinator habitat with native flowering plants.",
            extra_data={
                "hive_count": int(production.parcel.area * 5),
                "hive_strength": "Strong (50,000+ bees)",
                "nut_set_percentage": 82,
                "pollinator_habitat_enhancement": True,
                "native_plants_area_hectares": production.parcel.area * 0.15,
                "bee_friendly_certification": True,
            },
        )
        self.events_created += 1

        # Hull split monitoring and harvest (August)
        if production.finish_date:
            harvest_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                description="Precision Almond Harvest",
                type="HA",
                date=production.finish_date - timezone.timedelta(days=15),
                observation=f"Mechanical harvest with optimal timing. {production.production_amount} tons harvested at 6.5% moisture.",
                extra_data={
                    "harvest_method": "tree shaker + sweeper",
                    "moisture_content": "6.5%",
                    "quality_grade_distribution": {"Premium": 85, "Standard": 15},
                    "hull_split_timing": "optimal",
                    "equipment_efficiency": "high",
                    "amount": production.production_amount,
                    "unit": "tons",
                    "quality_grade": "Premium Export",
                    "destination": "Premium export markets",
                },
            )
            self.events_created += 1

            # Processing emissions
            self.create_accurate_carbon_entry(
                production,
                user,
                harvest_event,
                "Harvesting Equipment",
                float(production.parcel.area * 2.5),  # hours
                float(production.parcel.area * 2.5) * 12.3,  # CO2e
                "Mechanical almond harvest equipment",
            )

    def create_hass_avocado_production(self, parcel, product, user, year_offset, year_label):
        """Create Hass avocado production with comprehensive carbon tracking"""
        productions = []

        # Determine if this is current, recent, or historical
        is_current = year_offset == 0
        is_recent = year_offset == 365

        # Production scaling based on year (showing improvement over time)
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.08  # 8% improvement per year
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.12  # 12% carbon efficiency improvement per year

        production = History.objects.create(
            name=f"Hass Avocado Premium Harvest {year_label}",
            parcel=parcel,
            product=product,
            type="OR",  # Orchard
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 365),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 60),
            published=not is_current,
            production_amount=int(parcel.area * 28.5 * yield_scaling),  # kg per hectare (realistic avocado yield)
            description=f"Premium Hass avocados {year_label} - Carbon-negative production with verified regenerative practices and {int((yield_scaling - 1) * 100)}% yield improvement through sustainable intensification.",
            is_outdoor=True,
            age_of_plants=8 + (year_offset // 365),  # Trees getting older
            number_of_plants=int(parcel.area * 120),  # 120 trees per hectare
            soil_ph=float(Decimal("6.8")),
            earning=int(
                parcel.area * 28.5 * yield_scaling * 3.25 * (1 + (yield_scaling - 1) * 2)
            ),  # Premium pricing increases with sustainability
            extra_data={
                "variety": "Hass",
                "harvest_window": "June-October",
                "quality_grade": "Premium Export",
                "premium_achieved": f"{int((yield_scaling - 1) * 100 + 35)}%",
                "carbon_negative_certified": True,
                "blockchain_verified": True,
                "certifications": ["Regenerative Organic Certified", "Carbon Trust Standard", "GlobalGAP"],
                "sustainability_score": int(85 + (yield_scaling - 1) * 30),
                "year_label": year_label,
            },
        )

        # Create comprehensive event sequence with accurate carbon calculations
        self.create_avocado_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_avocado_event_sequence_with_carbon(self, production, user, year_offset, carbon_efficiency):
        """Create avocado-specific event sequence"""

        # 1. SOIL PREPARATION & CARBON SEQUESTRATION (January)
        soil_prep = SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=15),
            type="CO",  # Cover crop
            description="Multi-species cover crop establishment for carbon sequestration",
            soil_ph=float(Decimal("6.8")),
            organic_matter_percentage=float(Decimal("4.2")),
            amendment_type="9-species cover crop mix (legumes, brassicas, grasses)",
            amendment_amount=f"{int(production.parcel.area * 25)} kg seed mix",
            carbon_sequestration_potential=float(Decimal(str(production.parcel.area * 2.5 * carbon_efficiency))),
            extra_data={
                "species_count": 9,
                "nitrogen_fixation_potential": f"{int(production.parcel.area * 120)} kg N/year",
                "soil_carbon_target": "40% increase by 2026",
                "biodiversity_enhancement": True,
            },
        )
        self.events_created += 1

        # Create carbon entry for cover crop sequestration (NEGATIVE emissions)
        self.create_accurate_carbon_entry(
            production,
            user,
            soil_prep,
            "Cover Crop Sequestration",
            production.parcel.area,  # hectares
            -float(production.parcel.area) * 2.5 * carbon_efficiency,  # negative CO2e
            f"Cover crop carbon sequestration - {soil_prep.amendment_type}",
        )

        # 2. ORGANIC FERTILIZATION (February)
        spring_fert = ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=45),
            type="FE",
            description="Organic avocado fertilizer application - precision targeted",
            commercial_name="OMRI Certified Avocado-Tone Organic 6-3-3",
            volume=f"{int(production.parcel.area * 400)} kg",
            concentration="6% N, 3% P2O5, 3% K2O plus micronutrients",
            area=f"{production.parcel.area} hectares",
            way_of_application="Precision banded application with soil testing guidance",
            time_period="Early morning application before rain",
            observation="Applied based on soil analysis and tree nutritional needs. Organic certification maintained.",
            extra_data={
                "n_content_kg": production.parcel.area * 24,  # 6% of 400kg/ha
                "p2o5_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "k2o_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "organic_matter_content": "85%",
                "slow_release": True,
                "soil_test_based": True,
            },
        )
        self.events_created += 1

        # Create carbon entries for organic fertilizer (much lower emissions than synthetic)
        self.create_accurate_carbon_entry(
            production,
            user,
            spring_fert,
            "Organic Compost",
            production.parcel.area * 400,  # kg of fertilizer
            production.parcel.area * 400 * 0.28,  # kg CO2e
            f"Organic fertilizer application - {spring_fert.commercial_name}",
        )

        # 3. SOLAR-POWERED IRRIGATION (March-October)
        irrigation_event = GeneralEvent.objects.create(
            history=production,
            created_by=user,
            name="AI-Optimized Solar Irrigation System",
            date=production.start_date + timezone.timedelta(days=75),
            observation=f"Precision irrigation with {int(production.parcel.area * 4)} soil moisture sensors. 65% water reduction vs industry average. 100% solar powered with battery backup.",
            extra_data={
                "sensor_count": int(production.parcel.area * 4),
                "water_savings_percentage": 65,
                "energy_source": "100% solar",
                "irrigation_efficiency": "95%",
                "total_water_m3": int(production.parcel.area * 3200),  # Reduced water usage
                "energy_consumption_kwh": int(production.parcel.area * 180),  # Annual irrigation energy
                "solar_generation_kwh": int(production.parcel.area * 220),  # Excess solar generation
            },
        )
        self.events_created += 1

        # Solar energy generates NEGATIVE emissions (offset)
        self.create_accurate_carbon_entry(
            production,
            user,
            irrigation_event,
            "Solar Panel Generation",
            production.parcel.area * 220,  # kWh generated
            -production.parcel.area * 220 * 0.388,  # negative CO2e (grid offset)
            "Solar-powered irrigation system with grid tie-in",
        )

        # 4. BENEFICIAL INSECT HABITAT (April)
        habitat_event = ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="PL",
            date=production.start_date + timezone.timedelta(days=105),
            observation=f"Established {int(production.parcel.area * 0.1)} hectares of native flowering plants. Reduced pesticide needs by 90%. Supporting 25+ beneficial species.",
            extra_data={
                "habitat_area_hectares": production.parcel.area * 0.1,
                "native_species_planted": 12,
                "beneficial_insects_supported": 25,
                "pesticide_reduction": "90%",
                "biodiversity_score_improvement": "+35%",
                "pollination_services_value": f"${int(production.parcel.area * 450)}",
            },
        )
        self.events_created += 1

        # 5. PRECISION EQUIPMENT OPERATIONS (May)
        equipment_event = EquipmentEvent.objects.create(
            history=production,
            created_by=user,
            type="FC",
            description="Precision canopy management with renewable diesel",
            date=production.start_date + timezone.timedelta(days=135),
            equipment_name="Solar-Electric Kubota M7-172 with GPS guidance",
            fuel_type="renewable_diesel",
            fuel_amount=production.parcel.area * 15,  # liters of B20 biodiesel
            area_covered=f"{production.parcel.area} hectares",
            hours_used=production.parcel.area * 0.8,
            maintenance_cost=production.parcel.area * 45,
            index=1,
            extra_data={
                "fuel_type": "B20 biodiesel (20% bio, 80% diesel)",
                "gps_precision": "2cm accuracy",
                "variable_rate_application": True,
                "emission_reduction_vs_diesel": "15%",
            },
        )
        self.events_created += 1

        # Equipment fuel consumption
        self.create_accurate_carbon_entry(
            production,
            user,
            equipment_event,
            "Diesel Fuel",
            production.parcel.area * 15,  # liters
            production.parcel.area * 15 * 2.70 * 0.85,  # CO2e with B20 reduction
            "Equipment operations with B20 biodiesel blend",
        )

        # 6. INTEGRATED PEST MANAGEMENT (June)
        ipm_event = PestManagementEvent.objects.create(
            history=production,
            created_by=user,
            description="Organic IPM Program",
            date=production.start_date + timezone.timedelta(days=165),
            type="IP",  # IPM Implementation
            pest_species="Citrus leafminer, Scale insects, Aphids",
            pest_pressure_level="Medium",
            beneficial_species="Beneficial insects + organic oils",
            release_quantity=50000,
            action_threshold_met=True,
            extra_data={
                "imp_strategy": "Beneficial insect releases + organic oils targeting citrus leafminer and aphids",
                "beneficial_insects_released": 50000,
                "organic_treatments": ["Neem oil", "Insecticidal soap", "Bacillus thuringiensis"],
                "pest_reduction_percentage": 95,
                "cost_vs_conventional": "-45%",
                "residue_free": True,
                "area_treated": production.parcel.area,
                "effectiveness": "high",
                "environmental_impact": "positive",
            },
        )
        self.events_created += 1

        # 7. HARVEST OPERATIONS (June-October of following year)
        if production.finish_date:  # Only for completed productions
            harvest_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=30),
                type="HA",
                description="Premium Hand Harvest",
                observation=f"Hand-picked at optimal ripeness. {production.production_amount:,} kg harvested. Premium pricing achieved.",
                extra_data={
                    "name": "Premium Hand Harvest",
                    "amount": production.production_amount,
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium markets + Direct-to-consumer",
                    "harvest_method": "selective hand picking",
                    "crew_size": 24,
                    "harvest_duration_days": 21,
                    "quality_rejection_rate": "2.1%",
                    "brix_levels": "12.8-14.5",
                    "premium_market_percentage": 85,
                },
            )
            self.events_created += 1

            # 8. PROCESSING & COLD STORAGE
            processing_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=15),
                type="PR",
                description="Solar-Powered Processing & Cold Storage",
                observation="Solar-powered washing, grading, and cold storage. Blockchain verification applied.",
                extra_data={
                    "name": "Solar-Powered Processing & Cold Storage",
                    "amount": float(production.production_amount) * 0.98,  # After quality sorting
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium retail + Export markets",
                    "processing_energy_kwh": production.production_amount * 0.08,
                    "cold_storage_days": 14,
                    "packaging_materials_kg": production.production_amount * 0.05,
                    "solar_energy_percentage": 100,
                    "blockchain_hash": f"0x{uuid.uuid4().hex[:16]}",
                    "traceability_score": "100%",
                },
            )
            self.events_created += 1

            # Processing energy (solar-powered = net negative)
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Solar Panel Generation",
                float(production.production_amount) * 0.08,  # kWh
                -float(production.production_amount) * 0.08 * 0.388,  # negative CO2e
                "Solar-powered post-harvest processing",
            )

            # Packaging materials
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Cardboard Packaging",
                float(production.production_amount) * 0.05,  # kg packaging
                float(production.production_amount) * 0.05 * 1.05,  # CO2e
                "Recyclable cardboard packaging materials",
            )

    def create_organic_strawberry_production(self, parcel, product, user, year_offset, year_label):
        """Create organic strawberry production with comprehensive carbon tracking"""
        productions = []

        # Determine if this is current, recent, or historical
        is_current = year_offset == 0
        is_recent = year_offset == 365

        # Production scaling based on year (showing improvement over time)
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.08  # 8% improvement per year
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.12  # 12% carbon efficiency improvement per year

        production = History.objects.create(
            name=f"Organic Strawberry Premium Harvest {year_label}",
            parcel=parcel,
            product=product,
            type="OR",  # Orchard
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 365),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 60),
            published=not is_current,
            production_amount=int(parcel.area * 28.5 * yield_scaling),  # kg per hectare (realistic strawberry yield)
            description=f"Premium organic strawberries {year_label} - Carbon-negative production with verified regenerative practices and {int((yield_scaling - 1) * 100)}% yield improvement through sustainable intensification.",
            is_outdoor=True,
            age_of_plants=8 + (year_offset // 365),  # Plants getting older
            number_of_plants=int(parcel.area * 120),  # 120 plants per hectare
            soil_ph=float(Decimal("6.8")),
            earning=int(
                parcel.area * 28.5 * yield_scaling * 3.25 * (1 + (yield_scaling - 1) * 2)
            ),  # Premium pricing increases with sustainability
            extra_data={
                "variety": "Organic Strawberry",
                "harvest_window": "June-October",
                "quality_grade": "Premium Export",
                "premium_achieved": f"{int((yield_scaling - 1) * 100 + 35)}%",
                "carbon_negative_certified": True,
                "blockchain_verified": True,
                "certifications": ["Regenerative Organic Certified", "Carbon Trust Standard", "GlobalGAP"],
                "sustainability_score": int(85 + (yield_scaling - 1) * 30),
                "year_label": year_label,
            },
        )

        # Create comprehensive event sequence with accurate carbon calculations
        self.create_strawberry_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_strawberry_event_sequence_with_carbon(self, production, user, year_offset, carbon_efficiency):
        """Create strawberry-specific event sequence"""

        # 1. SOIL PREPARATION & CARBON SEQUESTRATION (January)
        soil_prep = SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=15),
            type="CO",  # Cover crop
            description="Multi-species cover crop establishment for carbon sequestration",
            soil_ph=float(Decimal("6.8")),
            organic_matter_percentage=float(Decimal("4.2")),
            amendment_type="9-species cover crop mix (legumes, brassicas, grasses)",
            amendment_amount=f"{int(production.parcel.area * 25)} kg seed mix",
            carbon_sequestration_potential=float(Decimal(str(production.parcel.area * 2.5 * carbon_efficiency))),
            extra_data={
                "species_count": 9,
                "nitrogen_fixation_potential": f"{int(production.parcel.area * 120)} kg N/year",
                "soil_carbon_target": "40% increase by 2026",
                "biodiversity_enhancement": True,
            },
        )
        self.events_created += 1

        # Create carbon entry for cover crop sequestration (NEGATIVE emissions)
        self.create_accurate_carbon_entry(
            production,
            user,
            soil_prep,
            "Cover Crop Sequestration",
            production.parcel.area,  # hectares
            -float(production.parcel.area) * 2.5 * carbon_efficiency,  # negative CO2e
            f"Cover crop carbon sequestration - {soil_prep.amendment_type}",
        )

        # 2. ORGANIC FERTILIZATION (February)
        spring_fert = ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=45),
            type="FE",
            description="Organic strawberry fertilizer application - precision targeted",
            commercial_name="OMRI Certified Strawberry-Tone Organic 6-3-3",
            volume=f"{int(production.parcel.area * 400)} kg",
            concentration="6% N, 3% P2O5, 3% K2O plus micronutrients",
            area=f"{production.parcel.area} hectares",
            way_of_application="Precision banded application with soil testing guidance",
            time_period="Early morning application before rain",
            observation="Applied based on soil analysis and plant nutritional needs. Organic certification maintained.",
            extra_data={
                "n_content_kg": production.parcel.area * 24,  # 6% of 400kg/ha
                "p2o5_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "k2o_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "organic_matter_content": "85%",
                "slow_release": True,
                "soil_test_based": True,
            },
        )
        self.events_created += 1

        # Create carbon entries for organic fertilizer (much lower emissions than synthetic)
        self.create_accurate_carbon_entry(
            production,
            user,
            spring_fert,
            "Organic Compost",
            production.parcel.area * 400,  # kg of fertilizer
            production.parcel.area * 400 * 0.28,  # kg CO2e
            f"Organic fertilizer application - {spring_fert.commercial_name}",
        )

        # 3. SOLAR-POWERED IRRIGATION (March-October)
        irrigation_event = GeneralEvent.objects.create(
            history=production,
            created_by=user,
            name="AI-Optimized Solar Irrigation System",
            date=production.start_date + timezone.timedelta(days=75),
            observation=f"Precision irrigation with {int(production.parcel.area * 4)} soil moisture sensors. 65% water reduction vs industry average. 100% solar powered with battery backup.",
            extra_data={
                "sensor_count": int(production.parcel.area * 4),
                "water_savings_percentage": 65,
                "energy_source": "100% solar",
                "irrigation_efficiency": "95%",
                "total_water_m3": int(production.parcel.area * 3200),  # Reduced water usage
                "energy_consumption_kwh": int(production.parcel.area * 180),  # Annual irrigation energy
                "solar_generation_kwh": int(production.parcel.area * 220),  # Excess solar generation
            },
        )
        self.events_created += 1

        # Solar energy generates NEGATIVE emissions (offset)
        self.create_accurate_carbon_entry(
            production,
            user,
            irrigation_event,
            "Solar Panel Generation",
            production.parcel.area * 220,  # kWh generated
            -production.parcel.area * 220 * 0.388,  # negative CO2e (grid offset)
            "Solar-powered irrigation system with grid tie-in",
        )

        # 4. BENEFICIAL INSECT HABITAT (April)
        habitat_event = ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="PL",
            date=production.start_date + timezone.timedelta(days=105),
            description="Beneficial Insect Habitat Establishment",
            observation=f"Established {int(production.parcel.area * 0.1)} hectares of native flowering plants. Reduced pesticide needs by 90%. Supporting 25+ beneficial species.",
            extra_data={
                "habitat_area_hectares": production.parcel.area * 0.1,
                "native_species_planted": 12,
                "beneficial_insects_supported": 25,
                "pesticide_reduction": "90%",
                "biodiversity_score_improvement": "+35%",
                "pollination_services_value": f"${int(production.parcel.area * 450)}",
            },
        )
        self.events_created += 1

        # 5. HARVEST OPERATIONS (June-October of following year)
        if production.finish_date:  # Only for completed productions
            harvest_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=30),
                type="HA",
                description="Premium Hand Harvest",
                observation=f"Hand-picked at optimal ripeness. {production.production_amount:,} kg harvested. Premium pricing achieved.",
                extra_data={
                    "name": "Premium Hand Harvest",
                    "amount": production.production_amount,
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium markets + Direct-to-consumer",
                    "harvest_method": "selective hand picking",
                    "crew_size": 24,
                    "harvest_duration_days": 21,
                    "quality_rejection_rate": "2.1%",
                    "brix_levels": "12.8-14.5",
                    "premium_market_percentage": 85,
                },
            )
            self.events_created += 1

            # 8. PROCESSING & COLD STORAGE
            processing_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=15),
                type="PR",
                description="Solar-Powered Processing & Cold Storage",
                observation="Solar-powered washing, grading, and cold storage. Blockchain verification applied.",
                extra_data={
                    "name": "Solar-Powered Processing & Cold Storage",
                    "amount": float(production.production_amount) * 0.98,  # After quality sorting
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium retail + Export markets",
                    "processing_energy_kwh": production.production_amount * 0.08,
                    "cold_storage_days": 14,
                    "packaging_materials_kg": production.production_amount * 0.05,
                    "solar_energy_percentage": 100,
                    "blockchain_hash": f"0x{uuid.uuid4().hex[:16]}",
                    "traceability_score": "100%",
                },
            )
            self.events_created += 1

            # Processing energy (solar-powered = net negative)
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Solar Panel Generation",
                float(production.production_amount) * 0.08,  # kWh
                -float(production.production_amount) * 0.08 * 0.388,  # negative CO2e
                "Solar-powered post-harvest processing",
            )

            # Packaging materials
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Cardboard Packaging",
                float(production.production_amount) * 0.05,  # kg packaging
                float(production.production_amount) * 0.05 * 1.05,  # CO2e
                "Recyclable cardboard packaging materials",
            )

    def create_hydroponic_lettuce_production(self, parcel, product, user, year_offset, year_label):
        """Create hydroponic lettuce production with comprehensive carbon tracking"""
        productions = []

        # Determine if this is current, recent, or historical
        is_current = year_offset == 0
        is_recent = year_offset == 365

        # Production scaling based on year (showing improvement over time)
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.08  # 8% improvement per year
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.12  # 12% carbon efficiency improvement per year

        production = History.objects.create(
            name=f"Hydroponic Lettuce Premium Harvest {year_label}",
            parcel=parcel,
            product=product,
            type="OR",  # Orchard
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 365),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 60),
            published=not is_current,
            production_amount=int(parcel.area * 28.5 * yield_scaling),  # kg per hectare (realistic lettuce yield)
            description=f"Premium hydroponic lettuce {year_label} - Carbon-negative production with verified regenerative practices and {int((yield_scaling - 1) * 100)}% yield improvement through sustainable intensification.",
            is_outdoor=True,
            age_of_plants=8 + (year_offset // 365),  # Plants getting older
            number_of_plants=int(parcel.area * 120),  # 120 plants per hectare
            soil_ph=float(Decimal("6.8")),
            earning=int(
                parcel.area * 28.5 * yield_scaling * 3.25 * (1 + (yield_scaling - 1) * 2)
            ),  # Premium pricing increases with sustainability
            extra_data={
                "variety": "Hydroponic Lettuce",
                "harvest_window": "June-October",
                "quality_grade": "Premium Export",
                "premium_achieved": f"{int((yield_scaling - 1) * 100 + 35)}%",
                "carbon_negative_certified": True,
                "blockchain_verified": True,
                "certifications": ["Regenerative Organic Certified", "Carbon Trust Standard", "GlobalGAP"],
                "sustainability_score": int(85 + (yield_scaling - 1) * 30),
                "year_label": year_label,
            },
        )

        # Create comprehensive event sequence with accurate carbon calculations
        self.create_lettuce_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_lettuce_event_sequence_with_carbon(self, production, user, year_offset, carbon_efficiency):
        """Create lettuce-specific event sequence"""

        # 1. SOIL PREPARATION & CARBON SEQUESTRATION (January)
        soil_prep = SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=15),
            type="CO",  # Cover crop
            description="Multi-species cover crop establishment for carbon sequestration",
            soil_ph=float(Decimal("6.8")),
            organic_matter_percentage=float(Decimal("4.2")),
            amendment_type="9-species cover crop mix (legumes, brassicas, grasses)",
            amendment_amount=f"{int(production.parcel.area * 25)} kg seed mix",
            carbon_sequestration_potential=float(Decimal(str(production.parcel.area * 2.5 * carbon_efficiency))),
            extra_data={
                "species_count": 9,
                "nitrogen_fixation_potential": f"{int(production.parcel.area * 120)} kg N/year",
                "soil_carbon_target": "40% increase by 2026",
                "biodiversity_enhancement": True,
            },
        )
        self.events_created += 1

        # Create carbon entry for cover crop sequestration (NEGATIVE emissions)
        self.create_accurate_carbon_entry(
            production,
            user,
            soil_prep,
            "Cover Crop Sequestration",
            production.parcel.area,  # hectares
            -float(production.parcel.area) * 2.5 * carbon_efficiency,  # negative CO2e
            f"Cover crop carbon sequestration - {soil_prep.amendment_type}",
        )

        # 2. ORGANIC FERTILIZATION (February)
        spring_fert = ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=45),
            type="FE",
            description="Organic lettuce fertilizer application - precision targeted",
            commercial_name="OMRI Certified Lettuce-Tone Organic 6-3-3",
            volume=f"{int(production.parcel.area * 400)} kg",
            concentration="6% N, 3% P2O5, 3% K2O plus micronutrients",
            area=f"{production.parcel.area} hectares",
            way_of_application="Precision banded application with soil testing guidance",
            time_period="Early morning application before rain",
            observation="Applied based on soil analysis and plant nutritional needs. Organic certification maintained.",
            extra_data={
                "n_content_kg": production.parcel.area * 24,  # 6% of 400kg/ha
                "p2o5_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "k2o_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "organic_matter_content": "85%",
                "slow_release": True,
                "soil_test_based": True,
            },
        )
        self.events_created += 1

        # Create carbon entries for organic fertilizer (much lower emissions than synthetic)
        self.create_accurate_carbon_entry(
            production,
            user,
            spring_fert,
            "Organic Compost",
            production.parcel.area * 400,  # kg of fertilizer
            production.parcel.area * 400 * 0.28,  # kg CO2e
            f"Organic fertilizer application - {spring_fert.commercial_name}",
        )

        # 3. SOLAR-POWERED IRRIGATION (March-October)
        irrigation_event = GeneralEvent.objects.create(
            history=production,
            created_by=user,
            name="AI-Optimized Solar Irrigation System",
            date=production.start_date + timezone.timedelta(days=75),
            observation=f"Precision irrigation with {int(production.parcel.area * 4)} soil moisture sensors. 65% water reduction vs industry average. 100% solar powered with battery backup.",
            extra_data={
                "sensor_count": int(production.parcel.area * 4),
                "water_savings_percentage": 65,
                "energy_source": "100% solar",
                "irrigation_efficiency": "95%",
                "total_water_m3": int(production.parcel.area * 3200),  # Reduced water usage
                "energy_consumption_kwh": int(production.parcel.area * 180),  # Annual irrigation energy
                "solar_generation_kwh": int(production.parcel.area * 220),  # Excess solar generation
            },
        )
        self.events_created += 1

        # Solar energy generates NEGATIVE emissions (offset)
        self.create_accurate_carbon_entry(
            production,
            user,
            irrigation_event,
            "Solar Panel Generation",
            production.parcel.area * 220,  # kWh generated
            -production.parcel.area * 220 * 0.388,  # negative CO2e (grid offset)
            "Solar-powered irrigation system with grid tie-in",
        )

        # 4. BENEFICIAL INSECT HABITAT (April)
        habitat_event = ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="PL",
            date=production.start_date + timezone.timedelta(days=105),
            description="Beneficial Insect Habitat Establishment",
            observation=f"Established {int(production.parcel.area * 0.1)} hectares of native flowering plants. Reduced pesticide needs by 90%. Supporting 25+ beneficial species.",
            extra_data={
                "habitat_area_hectares": production.parcel.area * 0.1,
                "native_species_planted": 12,
                "beneficial_insects_supported": 25,
                "pesticide_reduction": "90%",
                "biodiversity_score_improvement": "+35%",
                "pollination_services_value": f"${int(production.parcel.area * 450)}",
            },
        )
        self.events_created += 1

        # 5. HARVEST OPERATIONS (June-October of following year)
        if production.finish_date:  # Only for completed productions
            harvest_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=30),
                type="HA",
                description="Premium Hand Harvest",
                observation=f"Hand-picked at optimal ripeness. {production.production_amount:,} kg harvested. Premium pricing achieved.",
                extra_data={
                    "name": "Premium Hand Harvest",
                    "amount": production.production_amount,
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium markets + Direct-to-consumer",
                    "harvest_method": "selective hand picking",
                    "crew_size": 24,
                    "harvest_duration_days": 21,
                    "quality_rejection_rate": "2.1%",
                    "brix_levels": "12.8-14.5",
                    "premium_market_percentage": 85,
                },
            )
            self.events_created += 1

            # 8. PROCESSING & COLD STORAGE
            processing_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=15),
                type="PR",
                description="Solar-Powered Processing & Cold Storage",
                observation="Solar-powered washing, grading, and cold storage. Blockchain verification applied.",
                extra_data={
                    "name": "Solar-Powered Processing & Cold Storage",
                    "amount": float(production.production_amount) * 0.98,  # After quality sorting
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium retail + Export markets",
                    "processing_energy_kwh": production.production_amount * 0.08,
                    "cold_storage_days": 14,
                    "packaging_materials_kg": production.production_amount * 0.05,
                    "solar_energy_percentage": 100,
                    "blockchain_hash": f"0x{uuid.uuid4().hex[:16]}",
                    "traceability_score": "100%",
                },
            )
            self.events_created += 1

            # Processing energy (solar-powered = net negative)
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Solar Panel Generation",
                float(production.production_amount) * 0.08,  # kWh
                -float(production.production_amount) * 0.08 * 0.388,  # negative CO2e
                "Solar-powered post-harvest processing",
            )

            # Packaging materials
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Cardboard Packaging",
                float(production.production_amount) * 0.05,  # kg packaging
                float(production.production_amount) * 0.05 * 1.05,  # CO2e
                "Recyclable cardboard packaging materials",
            )

    def create_regenerative_wheat_production(self, parcel, product, user, year_offset, year_label):
        """Create regenerative wheat production with comprehensive carbon tracking"""
        productions = []

        # Determine if this is current, recent, or historical
        is_current = year_offset == 0
        is_recent = year_offset == 365

        # Production scaling based on year (showing improvement over time)
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.08  # 8% improvement per year
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.12  # 12% carbon efficiency improvement per year

        production = History.objects.create(
            name=f"Regenerative Wheat Premium Harvest {year_label}",
            parcel=parcel,
            product=product,
            type="OR",  # Orchard
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 365),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 60),
            published=not is_current,
            production_amount=int(parcel.area * 28.5 * yield_scaling),  # kg per hectare (realistic wheat yield)
            description=f"Premium regenerative wheat {year_label} - Carbon-negative production with verified regenerative practices and {int((yield_scaling - 1) * 100)}% yield improvement through sustainable intensification.",
            is_outdoor=True,
            age_of_plants=8 + (year_offset // 365),  # Plants getting older
            number_of_plants=int(parcel.area * 120),  # 120 plants per hectare
            soil_ph=float(Decimal("6.8")),
            earning=int(
                parcel.area * 28.5 * yield_scaling * 3.25 * (1 + (yield_scaling - 1) * 2)
            ),  # Premium pricing increases with sustainability
            extra_data={
                "variety": "Regenerative Wheat",
                "harvest_window": "June-October",
                "quality_grade": "Premium Export",
                "premium_achieved": f"{int((yield_scaling - 1) * 100 + 35)}%",
                "carbon_negative_certified": True,
                "blockchain_verified": True,
                "certifications": ["Regenerative Organic Certified", "Carbon Trust Standard", "GlobalGAP"],
                "sustainability_score": int(85 + (yield_scaling - 1) * 30),
                "year_label": year_label,
            },
        )

        # Create comprehensive event sequence with accurate carbon calculations
        self.create_wheat_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_wheat_event_sequence_with_carbon(self, production, user, year_offset, carbon_efficiency):
        """Create wheat-specific event sequence"""

        # 1. SOIL PREPARATION & CARBON SEQUESTRATION (January)
        soil_prep = SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=15),
            type="CO",  # Cover crop
            description="Multi-species cover crop establishment for carbon sequestration",
            soil_ph=float(Decimal("6.8")),
            organic_matter_percentage=float(Decimal("4.2")),
            amendment_type="9-species cover crop mix (legumes, brassicas, grasses)",
            amendment_amount=f"{int(production.parcel.area * 25)} kg seed mix",
            carbon_sequestration_potential=float(Decimal(str(production.parcel.area * 2.5 * carbon_efficiency))),
            extra_data={
                "species_count": 9,
                "nitrogen_fixation_potential": f"{int(production.parcel.area * 120)} kg N/year",
                "soil_carbon_target": "40% increase by 2026",
                "biodiversity_enhancement": True,
            },
        )
        self.events_created += 1

        # Create carbon entry for cover crop sequestration (NEGATIVE emissions)
        self.create_accurate_carbon_entry(
            production,
            user,
            soil_prep,
            "Cover Crop Sequestration",
            production.parcel.area,  # hectares
            -float(production.parcel.area) * 2.5 * carbon_efficiency,  # negative CO2e
            f"Cover crop carbon sequestration - {soil_prep.amendment_type}",
        )

        # 2. ORGANIC FERTILIZATION (February)
        spring_fert = ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=45),
            type="FE",
            description="Organic wheat fertilizer application - precision targeted",
            commercial_name="OMRI Certified Wheat-Tone Organic 6-3-3",
            volume=f"{int(production.parcel.area * 400)} kg",
            concentration="6% N, 3% P2O5, 3% K2O plus micronutrients",
            area=f"{production.parcel.area} hectares",
            way_of_application="Precision banded application with soil testing guidance",
            time_period="Early morning application before rain",
            observation="Applied based on soil analysis and plant nutritional needs. Organic certification maintained.",
            extra_data={
                "n_content_kg": production.parcel.area * 24,  # 6% of 400kg/ha
                "p2o5_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "k2o_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "organic_matter_content": "85%",
                "slow_release": True,
                "soil_test_based": True,
            },
        )
        self.events_created += 1

        # Create carbon entries for organic fertilizer (much lower emissions than synthetic)
        self.create_accurate_carbon_entry(
            production,
            user,
            spring_fert,
            "Organic Compost",
            production.parcel.area * 400,  # kg of fertilizer
            production.parcel.area * 400 * 0.28,  # kg CO2e
            f"Organic fertilizer application - {spring_fert.commercial_name}",
        )

        # 3. SOLAR-POWERED IRRIGATION (March-October)
        irrigation_event = GeneralEvent.objects.create(
            history=production,
            created_by=user,
            name="AI-Optimized Solar Irrigation System",
            date=production.start_date + timezone.timedelta(days=75),
            observation=f"Precision irrigation with {int(production.parcel.area * 4)} soil moisture sensors. 65% water reduction vs industry average. 100% solar powered with battery backup.",
            extra_data={
                "sensor_count": int(production.parcel.area * 4),
                "water_savings_percentage": 65,
                "energy_source": "100% solar",
                "irrigation_efficiency": "95%",
                "total_water_m3": int(production.parcel.area * 3200),  # Reduced water usage
                "energy_consumption_kwh": int(production.parcel.area * 180),  # Annual irrigation energy
                "solar_generation_kwh": int(production.parcel.area * 220),  # Excess solar generation
            },
        )
        self.events_created += 1

        # Solar energy generates NEGATIVE emissions (offset)
        self.create_accurate_carbon_entry(
            production,
            user,
            irrigation_event,
            "Solar Panel Generation",
            production.parcel.area * 220,  # kWh generated
            -production.parcel.area * 220 * 0.388,  # negative CO2e (grid offset)
            "Solar-powered irrigation system with grid tie-in",
        )

        # 4. BENEFICIAL INSECT HABITAT (April)
        habitat_event = ProductionEvent.objects.create(
            history=production,
            created_by=user,
            type="PL",
            date=production.start_date + timezone.timedelta(days=105),
            observation=f"Established {int(production.parcel.area * 0.1)} hectares of native flowering plants. Reduced pesticide needs by 90%. Supporting 25+ beneficial species.",
            extra_data={
                "habitat_area_hectares": production.parcel.area * 0.1,
                "native_species_planted": 12,
                "beneficial_insects_supported": 25,
                "pesticide_reduction": "90%",
                "biodiversity_score_improvement": "+35%",
                "pollination_services_value": f"${int(production.parcel.area * 450)}",
            },
        )
        self.events_created += 1

        # 5. HARVEST OPERATIONS (June-October of following year)
        if production.finish_date:  # Only for completed productions
            harvest_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                name="Premium Hand Harvest",
                type="HA",
                date=production.finish_date - timezone.timedelta(days=30),
                amount=production.production_amount,
                unit="kg",
                quality_grade="Premium Export",
                destination="Premium markets + Direct-to-consumer",
                notes=f"Hand-picked at optimal ripeness. {production.production_amount:,} kg harvested. Premium pricing achieved.",
                extra_data={
                    "harvest_method": "selective hand picking",
                    "crew_size": 24,
                    "harvest_duration_days": 21,
                    "quality_rejection_rate": "2.1%",
                    "brix_levels": "12.8-14.5",
                    "premium_market_percentage": 85,
                },
            )
            self.events_created += 1

            # 8. PROCESSING & COLD STORAGE
            processing_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                name="Solar-Powered Processing & Cold Storage",
                type="PR",
                date=production.finish_date - timezone.timedelta(days=15),
                amount=float(production.production_amount) * 0.98,  # After quality sorting
                unit="kg",
                quality_grade="Premium Export",
                destination="Premium retail + Export markets",
                notes="Solar-powered washing, grading, and cold storage. Blockchain verification applied.",
                extra_data={
                    "processing_energy_kwh": production.production_amount * 0.08,
                    "cold_storage_days": 14,
                    "packaging_materials_kg": production.production_amount * 0.05,
                    "solar_energy_percentage": 100,
                    "blockchain_hash": f"0x{uuid.uuid4().hex[:16]}",
                    "traceability_score": "100%",
                },
            )
            self.events_created += 1

            # Processing energy (solar-powered = net negative)
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Solar Panel Generation",
                float(production.production_amount) * 0.08,  # kWh
                -float(production.production_amount) * 0.08 * 0.388,  # negative CO2e
                "Solar-powered post-harvest processing",
            )

            # Packaging materials
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Cardboard Packaging",
                float(production.production_amount) * 0.05,  # kg packaging
                float(production.production_amount) * 0.05 * 1.05,  # CO2e
                "Recyclable cardboard packaging materials",
            )

    def create_cover_crop_production(self, parcel, product, user, year_offset, year_label):
        """Create cover crop production with comprehensive carbon tracking"""
        productions = []

        # Determine if this is current, recent, or historical
        is_current = year_offset == 0
        is_recent = year_offset == 365

        # Production scaling based on year (showing improvement over time)
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.08  # 8% improvement per year
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.12  # 12% carbon efficiency improvement per year

        production = History.objects.create(
            name=f"Cover Crop {year_label}",
            parcel=parcel,
            product=product,
            type="CO",  # Cover crop
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 365),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 60),
            published=not is_current,
            production_amount=int(parcel.area * 28.5 * yield_scaling),  # kg per hectare (realistic cover crop yield)
            description=f"Cover crop {year_label} - Carbon-negative production with verified regenerative practices and {int((yield_scaling - 1) * 100)}% yield improvement through sustainable intensification.",
            is_outdoor=True,
            age_of_plants=8 + (year_offset // 365),  # Plants getting older
            number_of_plants=int(parcel.area * 120),  # 120 plants per hectare
            soil_ph=float(Decimal("6.8")),
            earning=int(
                parcel.area * 28.5 * yield_scaling * 3.25 * (1 + (yield_scaling - 1) * 2)
            ),  # Premium pricing increases with sustainability
            extra_data={
                "variety": "Cover Crop",
                "harvest_window": "June-October",
                "quality_grade": "Premium Export",
                "premium_achieved": f"{int((yield_scaling - 1) * 100 + 35)}%",
                "carbon_negative_certified": True,
                "blockchain_verified": True,
                "certifications": ["Regenerative Organic Certified", "Carbon Trust Standard", "GlobalGAP"],
                "sustainability_score": int(85 + (yield_scaling - 1) * 30),
                "year_label": year_label,
            },
        )

        # Create comprehensive event sequence with accurate carbon calculations
        self.create_cover_crop_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_cover_crop_event_sequence_with_carbon(self, production, user, year_offset, carbon_efficiency):
        """Create cover crop-specific event sequence"""

        # 1. SOIL PREPARATION & CARBON SEQUESTRATION (January)
        soil_prep = SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=15),
            type="CO",  # Cover crop
            description="Multi-species cover crop establishment for carbon sequestration",
            soil_ph=float(Decimal("6.8")),
            organic_matter_percentage=float(Decimal("4.2")),
            amendment_type="9-species cover crop mix (legumes, brassicas, grasses)",
            amendment_amount=f"{int(production.parcel.area * 25)} kg seed mix",
            carbon_sequestration_potential=float(Decimal(str(production.parcel.area * 2.5 * carbon_efficiency))),
            extra_data={
                "species_count": 9,
                "nitrogen_fixation_potential": f"{int(production.parcel.area * 120)} kg N/year",
                "soil_carbon_target": "40% increase by 2026",
                "biodiversity_enhancement": True,
            },
        )
        self.events_created += 1

        # Create carbon entry for cover crop sequestration (NEGATIVE emissions)
        self.create_accurate_carbon_entry(
            production,
            user,
            soil_prep,
            "Cover Crop Sequestration",
            production.parcel.area,  # hectares
            -float(production.parcel.area) * 2.5 * carbon_efficiency,  # negative CO2e
            f"Cover crop carbon sequestration - {soil_prep.amendment_type}",
        )

        # 2. ORGANIC FERTILIZATION (February)
        spring_fert = ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=45),
            type="FE",
            description="Organic cover crop fertilizer application - precision targeted",
            commercial_name="OMRI Certified Cover Crop-Tone Organic 6-3-3",
            volume=f"{int(production.parcel.area * 400)} kg",
            concentration="6% N, 3% P2O5, 3% K2O plus micronutrients",
            area=f"{production.parcel.area} hectares",
            way_of_application="Precision banded application with soil testing guidance",
            time_period="Early morning application before rain",
            observation="Applied based on soil analysis and plant nutritional needs. Organic certification maintained.",
            extra_data={
                "n_content_kg": production.parcel.area * 24,  # 6% of 400kg/ha
                "p2o5_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "k2o_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "organic_matter_content": "85%",
                "slow_release": True,
                "soil_test_based": True,
            },
        )
        self.events_created += 1

        # Create carbon entries for organic fertilizer (much lower emissions than synthetic)
        self.create_accurate_carbon_entry(
            production,
            user,
            spring_fert,
            "Organic Compost",
            production.parcel.area * 400,  # kg of fertilizer
            production.parcel.area * 400 * 0.28,  # kg CO2e
            f"Organic fertilizer application - {spring_fert.commercial_name}",
        )

        # 3. SOLAR-POWERED IRRIGATION (March-October)
        irrigation_event = GeneralEvent.objects.create(
            history=production,
            created_by=user,
            name="AI-Optimized Solar Irrigation System",
            date=production.start_date + timezone.timedelta(days=75),
            observation=f"Precision irrigation with {int(production.parcel.area * 4)} soil moisture sensors. 65% water reduction vs industry average. 100% solar powered with battery backup.",
            extra_data={
                "sensor_count": int(production.parcel.area * 4),
                "water_savings_percentage": 65,
                "energy_source": "100% solar",
                "irrigation_efficiency": "95%",
                "total_water_m3": int(production.parcel.area * 3200),  # Reduced water usage
                "energy_consumption_kwh": int(production.parcel.area * 180),  # Annual irrigation energy
                "solar_generation_kwh": int(production.parcel.area * 220),  # Excess solar generation
            },
        )
        self.events_created += 1

        # Solar energy generates NEGATIVE emissions (offset)
        self.create_accurate_carbon_entry(
            production,
            user,
            irrigation_event,
            "Solar Panel Generation",
            production.parcel.area * 220,  # kWh generated
            -production.parcel.area * 220 * 0.388,  # negative CO2e (grid offset)
            "Solar-powered irrigation system with grid tie-in",
        )

        # 4. HARVEST OPERATIONS (June-October of following year)
        if production.finish_date:  # Only for completed productions
            harvest_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=30),
                type="HA",
                description="Premium Hand Harvest",
                observation=f"Hand-picked at optimal ripeness. {production.production_amount:,} kg harvested. Premium pricing achieved.",
                extra_data={
                    "name": "Premium Hand Harvest",
                    "amount": production.production_amount,
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium markets + Direct-to-consumer",
                    "harvest_method": "selective hand picking",
                    "crew_size": 24,
                    "harvest_duration_days": 21,
                    "quality_rejection_rate": "2.1%",
                    "brix_levels": "12.8-14.5",
                    "premium_market_percentage": 85,
                },
            )
            self.events_created += 1

            # 8. PROCESSING & COLD STORAGE
            processing_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=15),
                type="PR",
                description="Solar-Powered Processing & Cold Storage",
                observation="Solar-powered washing, grading, and cold storage. Blockchain verification applied.",
                extra_data={
                    "name": "Solar-Powered Processing & Cold Storage",
                    "amount": float(production.production_amount) * 0.98,  # After quality sorting
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium retail + Export markets",
                    "processing_energy_kwh": production.production_amount * 0.08,
                    "cold_storage_days": 14,
                    "packaging_materials_kg": production.production_amount * 0.05,
                    "solar_energy_percentage": 100,
                    "blockchain_hash": f"0x{uuid.uuid4().hex[:16]}",
                    "traceability_score": "100%",
                },
            )
            self.events_created += 1

            # Processing energy (solar-powered = net negative)
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Solar Panel Generation",
                float(production.production_amount) * 0.08,  # kWh
                -float(production.production_amount) * 0.08 * 0.388,  # negative CO2e
                "Solar-powered post-harvest processing",
            )

            # Packaging materials
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Cardboard Packaging",
                float(production.production_amount) * 0.05,  # kg packaging
                float(production.production_amount) * 0.05 * 1.05,  # CO2e
                "Recyclable cardboard packaging materials",
            )

    def create_regenerative_wheat_production(self, parcel, product, user, year_offset, year_label):
        """Create regenerative wheat production with comprehensive carbon tracking"""
        productions = []

        # Determine if this is current, recent, or historical
        is_current = year_offset == 0
        is_recent = year_offset == 365

        # Production scaling based on year (showing improvement over time)
        yield_scaling = 1.0 + (3 - year_offset // 365) * 0.08  # 8% improvement per year
        carbon_efficiency = 1.0 + (3 - year_offset // 365) * 0.12  # 12% carbon efficiency improvement per year

        production = History.objects.create(
            name=f"Regenerative Wheat Premium Harvest {year_label}",
            parcel=parcel,
            product=product,
            type="OR",  # Orchard
            start_date=timezone.now() - timezone.timedelta(days=year_offset + 365),
            finish_date=None if is_current else timezone.now() - timezone.timedelta(days=year_offset + 60),
            published=not is_current,
            production_amount=int(parcel.area * 28.5 * yield_scaling),  # kg per hectare (realistic wheat yield)
            description=f"Premium regenerative wheat {year_label} - Carbon-negative production with verified regenerative practices and {int((yield_scaling - 1) * 100)}% yield improvement through sustainable intensification.",
            is_outdoor=True,
            age_of_plants=8 + (year_offset // 365),  # Plants getting older
            number_of_plants=int(parcel.area * 120),  # 120 plants per hectare
            soil_ph=float(Decimal("6.8")),
            earning=int(
                parcel.area * 28.5 * yield_scaling * 3.25 * (1 + (yield_scaling - 1) * 2)
            ),  # Premium pricing increases with sustainability
            extra_data={
                "variety": "Regenerative Wheat",
                "harvest_window": "June-October",
                "quality_grade": "Premium Export",
                "premium_achieved": f"{int((yield_scaling - 1) * 100 + 35)}%",
                "carbon_negative_certified": True,
                "blockchain_verified": True,
                "certifications": ["Regenerative Organic Certified", "Carbon Trust Standard", "GlobalGAP"],
                "sustainability_score": int(85 + (yield_scaling - 1) * 30),
                "year_label": year_label,
            },
        )

        # Create comprehensive event sequence with accurate carbon calculations
        self.create_wheat_event_sequence_with_carbon(production, user, year_offset, carbon_efficiency)

        productions.append(production)
        self.productions_created += 1

        return productions

    def create_wheat_event_sequence_with_carbon(self, production, user, year_offset, carbon_efficiency):
        """Create wheat-specific event sequence"""

        # 1. SOIL PREPARATION & CARBON SEQUESTRATION (January)
        soil_prep = SoilManagementEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=15),
            type="CO",  # Cover crop
            description="Multi-species cover crop establishment for carbon sequestration",
            soil_ph=float(Decimal("6.8")),
            organic_matter_percentage=float(Decimal("4.2")),
            amendment_type="9-species cover crop mix (legumes, brassicas, grasses)",
            amendment_amount=f"{int(production.parcel.area * 25)} kg seed mix",
            carbon_sequestration_potential=float(Decimal(str(production.parcel.area * 2.5 * carbon_efficiency))),
            extra_data={
                "species_count": 9,
                "nitrogen_fixation_potential": f"{int(production.parcel.area * 120)} kg N/year",
                "soil_carbon_target": "40% increase by 2026",
                "biodiversity_enhancement": True,
            },
        )
        self.events_created += 1

        # Create carbon entry for cover crop sequestration (NEGATIVE emissions)
        self.create_accurate_carbon_entry(
            production,
            user,
            soil_prep,
            "Cover Crop Sequestration",
            production.parcel.area,  # hectares
            -float(production.parcel.area) * 2.5 * carbon_efficiency,  # negative CO2e
            f"Cover crop carbon sequestration - {soil_prep.amendment_type}",
        )

        # 2. ORGANIC FERTILIZATION (February)
        spring_fert = ChemicalEvent.objects.create(
            history=production,
            created_by=user,
            date=production.start_date + timezone.timedelta(days=45),
            type="FE",
            description="Organic wheat fertilizer application - precision targeted",
            commercial_name="OMRI Certified Wheat-Tone Organic 6-3-3",
            volume=f"{int(production.parcel.area * 400)} kg",
            concentration="6% N, 3% P2O5, 3% K2O plus micronutrients",
            area=f"{production.parcel.area} hectares",
            way_of_application="Precision banded application with soil testing guidance",
            time_period="Early morning application before rain",
            observation="Applied based on soil analysis and plant nutritional needs. Organic certification maintained.",
            extra_data={
                "n_content_kg": production.parcel.area * 24,  # 6% of 400kg/ha
                "p2o5_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "k2o_content_kg": production.parcel.area * 12,  # 3% of 400kg/ha
                "organic_matter_content": "85%",
                "slow_release": True,
                "soil_test_based": True,
            },
        )
        self.events_created += 1

        # Create carbon entries for organic fertilizer (much lower emissions than synthetic)
        self.create_accurate_carbon_entry(
            production,
            user,
            spring_fert,
            "Organic Compost",
            production.parcel.area * 400,  # kg of fertilizer
            production.parcel.area * 400 * 0.28,  # kg CO2e
            f"Organic fertilizer application - {spring_fert.commercial_name}",
        )

        # 3. SOLAR-POWERED IRRIGATION (March-October)
        irrigation_event = GeneralEvent.objects.create(
            history=production,
            created_by=user,
            name="AI-Optimized Solar Irrigation System",
            date=production.start_date + timezone.timedelta(days=75),
            observation=f"Precision irrigation with {int(production.parcel.area * 4)} soil moisture sensors. 65% water reduction vs industry average. 100% solar powered with battery backup.",
            extra_data={
                "sensor_count": int(production.parcel.area * 4),
                "water_savings_percentage": 65,
                "energy_source": "100% solar",
                "irrigation_efficiency": "95%",
                "total_water_m3": int(production.parcel.area * 3200),  # Reduced water usage
                "energy_consumption_kwh": int(production.parcel.area * 180),  # Annual irrigation energy
                "solar_generation_kwh": int(production.parcel.area * 220),  # Excess solar generation
            },
        )
        self.events_created += 1

        # Solar energy generates NEGATIVE emissions (offset)
        self.create_accurate_carbon_entry(
            production,
            user,
            irrigation_event,
            "Solar Panel Generation",
            production.parcel.area * 220,  # kWh generated
            -production.parcel.area * 220 * 0.388,  # negative CO2e (grid offset)
            "Solar-powered irrigation system with grid tie-in",
        )

        # 4. HARVEST OPERATIONS (June-October of following year)
        if production.finish_date:  # Only for completed productions
            harvest_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=30),
                type="HA",
                description="Premium Hand Harvest",
                observation=f"Hand-picked at optimal ripeness. {production.production_amount:,} kg harvested. Premium pricing achieved.",
                extra_data={
                    "name": "Premium Hand Harvest",
                    "amount": production.production_amount,
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium markets + Direct-to-consumer",
                    "harvest_method": "selective hand picking",
                    "crew_size": 24,
                    "harvest_duration_days": 21,
                    "quality_rejection_rate": "2.1%",
                    "brix_levels": "12.8-14.5",
                    "premium_market_percentage": 85,
                },
            )
            self.events_created += 1

            # 8. PROCESSING & COLD STORAGE
            processing_event = ProductionEvent.objects.create(
                history=production,
                created_by=user,
                date=production.finish_date - timezone.timedelta(days=15),
                type="PR",
                description="Solar-Powered Processing & Cold Storage",
                observation="Solar-powered washing, grading, and cold storage. Blockchain verification applied.",
                extra_data={
                    "name": "Solar-Powered Processing & Cold Storage",
                    "amount": float(production.production_amount) * 0.98,  # After quality sorting
                    "unit": "kg",
                    "quality_grade": "Premium Export",
                    "destination": "Premium retail + Export markets",
                    "processing_energy_kwh": production.production_amount * 0.08,
                    "cold_storage_days": 14,
                    "packaging_materials_kg": production.production_amount * 0.05,
                    "solar_energy_percentage": 100,
                    "blockchain_hash": f"0x{uuid.uuid4().hex[:16]}",
                    "traceability_score": "100%",
                },
            )
            self.events_created += 1

            # Processing energy (solar-powered = net negative)
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Solar Panel Generation",
                float(production.production_amount) * 0.08,  # kWh
                -float(production.production_amount) * 0.08 * 0.388,  # negative CO2e
                "Solar-powered post-harvest processing",
            )

            # Packaging materials
            self.create_accurate_carbon_entry(
                production,
                user,
                processing_event,
                "Cardboard Packaging",
                float(production.production_amount) * 0.05,  # kg packaging
                float(production.production_amount) * 0.05 * 1.05,  # CO2e
                "Recyclable cardboard packaging materials",
            )

    # ADVANCED TECHNOLOGY & CONSUMER EXPERIENCE METHODS

    def create_advanced_iot_infrastructure(self, establishment1, establishment2, establishment3, user):
        """Create IoT infrastructure showcasing technology integration"""
        self.stdout.write("   📡 Creating IoT infrastructure...")

        # Create IoT devices for each establishment
        iot_created = 0

        # ESTABLISHMENT 1: Premium Citrus Ranch IoT devices
        devices_citrus = [
            ("Soil Sensor Network", "soil_moisture", "Real-time soil moisture, pH, and nutrient monitoring"),
            ("Weather Station Pro", "weather_station", "Comprehensive weather monitoring with AI predictions"),
            (
                "Tree Health Camera System",
                "equipment_monitor",
                "AI-powered tree health analysis with disease detection",
            ),
            ("Smart Irrigation Controller", "irrigation", "Automated irrigation with water optimization"),
            ("Energy Management System", "equipment_monitor", "Solar panel efficiency and energy consumption tracking"),
        ]

        for name, device_type, description in devices_citrus:
            device = IoTDevice.objects.create(
                establishment=establishment1,
                device_id=f"{device_type}_{random.randint(10000, 99999)}",
                name=name,
                device_type=device_type,
                manufacturer="TrazoTech",
                model=f"TZ-{device_type.upper()}-2024",
                notes=description,
                status="online",
                last_seen=timezone.now() - timezone.timedelta(minutes=random.randint(1, 30)),
                battery_level=random.randint(85, 100) if "sensor" in name.lower() else None,
                latitude=Decimal("36.7378") + Decimal(str(random.uniform(-0.01, 0.01))),
                longitude=Decimal("-119.7871") + Decimal(str(random.uniform(-0.01, 0.01))),
                configuration={
                    "firmware_version": f"v{random.randint(1,3)}.{random.randint(0,9)}.{random.randint(0,9)}",
                    "location_metadata": {
                        "establishment": "Premium Citrus Ranch",
                        "focus_area": "Premium citrus production",
                        "coverage_area": "950 hectares",
                        "installation_date": "2023-01-15",
                    },
                    "sampling_rate": "5 minutes",
                    "calibration_date": "2024-01-15",
                    "data_encryption": True,
                },
            )
            iot_created += 1

            # Create sample data points
            self.create_iot_data_points(device, user)

        # ESTABLISHMENT 2: Organic Innovation Center IoT devices
        devices_organic = [
            (
                "Organic Certification Monitoring System",
                "equipment_monitor",
                "Real-time monitoring of organic compliance parameters and inputs",
            ),
            (
                "AI Crop Analytics Platform",
                "equipment_monitor",
                "Machine learning-powered crop health analysis and yield prediction",
            ),
            ("Hydroponic System Controller", "irrigation", "Automated hydroponic nutrient and pH management system"),
            (
                "Biodiversity Sensor Network",
                "soil_moisture",
                "Multi-sensor array monitoring soil biology and beneficial microorganisms",
            ),
            (
                "Research Weather Station",
                "weather_station",
                "High-precision weather monitoring for research applications",
            ),
            (
                "Smart Greenhouse Controller",
                "equipment_monitor",
                "Climate-controlled greenhouse automation and monitoring",
            ),
        ]

        for name, device_type, description in devices_organic:
            device = IoTDevice.objects.create(
                establishment=establishment2,
                device_id=f"{device_type}_{random.randint(10000, 99999)}",
                name=name,
                device_type=device_type,
                manufacturer="TrazoTech Organic",
                model=f"TZ-ORG-{device_type.upper()}-2024",
                notes=description,
                status="online",
                last_seen=timezone.now() - timezone.timedelta(minutes=random.randint(1, 30)),
                battery_level=random.randint(85, 100) if "sensor" in name.lower() else None,
                latitude=Decimal("36.6777") + Decimal(str(random.uniform(-0.01, 0.01))),
                longitude=Decimal("-121.6555") + Decimal(str(random.uniform(-0.01, 0.01))),
                configuration={
                    "firmware_version": f"v{random.randint(1,3)}.{random.randint(0,9)}.{random.randint(0,9)}",
                    "location_metadata": {
                        "establishment": "Organic Innovation Center",
                        "focus_area": "Organic research and innovation",
                        "coverage_area": "450 hectares",
                        "installation_date": "2023-03-15",
                    },
                    "sampling_rate": "2 minutes",
                    "calibration_date": "2024-02-15",
                    "data_encryption": True,
                    "organic_certified": True,
                    "research_mode": True,
                },
            )
            iot_created += 1

            # Create sample data points
            self.create_iot_data_points(device, user)

        # ESTABLISHMENT 3: Regenerative Grain Ranch IoT devices
        devices_regenerative = [
            (
                "Carbon Sequestration Monitor",
                "soil_moisture",
                "Advanced soil carbon monitoring and sequestration tracking",
            ),
            ("Precision Agriculture Hub", "equipment_monitor", "GPS-guided precision farming equipment coordination"),
            (
                "Regenerative Weather Station",
                "weather_station",
                "Climate monitoring optimized for regenerative agriculture",
            ),
            (
                "Cover Crop Sensor Array",
                "equipment_monitor",
                "Multi-species cover crop health and carbon capture monitoring",
            ),
            (
                "No-Till Equipment Monitor",
                "equipment_monitor",
                "Zero-tillage equipment efficiency and soil impact tracking",
            ),
            (
                "Carbon Credit Verification System",
                "equipment_monitor",
                "Automated carbon credit generation and verification monitoring",
            ),
        ]

        for name, device_type, description in devices_regenerative:
            device = IoTDevice.objects.create(
                establishment=establishment3,
                device_id=f"{device_type}_{random.randint(10000, 99999)}",
                name=name,
                device_type=device_type,
                manufacturer="TrazoTech Regenerative",
                model=f"TZ-REG-{device_type.upper()}-2024",
                notes=description,
                status="online",
                last_seen=timezone.now() - timezone.timedelta(minutes=random.randint(1, 30)),
                battery_level=random.randint(85, 100) if "sensor" in name.lower() else None,
                latitude=Decimal("35.3733") + Decimal(str(random.uniform(-0.01, 0.01))),
                longitude=Decimal("-119.0187") + Decimal(str(random.uniform(-0.01, 0.01))),
                configuration={
                    "firmware_version": f"v{random.randint(1,3)}.{random.randint(0,9)}.{random.randint(0,9)}",
                    "location_metadata": {
                        "establishment": "Regenerative Grain Ranch",
                        "focus_area": "Carbon farming and regenerative agriculture",
                        "coverage_area": "875 hectares",
                        "installation_date": "2023-05-15",
                    },
                    "sampling_rate": "10 minutes",
                    "calibration_date": "2024-03-15",
                    "data_encryption": True,
                    "carbon_monitoring": True,
                    "regenerative_certified": True,
                },
            )
            iot_created += 1

            # Create sample data points
            self.create_iot_data_points(device, user)

        self.stdout.write(f"   ✅ IoT infrastructure: {iot_created} devices across all establishments")

    def create_iot_data_points(self, device, user):
        """Create realistic IoT data points"""
        # Create 30 days of data points
        for days_ago in range(30):
            timestamp = timezone.now() - timezone.timedelta(days=days_ago, hours=random.randint(0, 23))

            if device.device_type == "soil_moisture":
                # Different data based on establishment type
                if "Organic" in device.establishment.name:
                    # Organic Innovation Center - focus on biological activity
                    data = {
                        "soil_moisture": round(random.uniform(35, 75), 1),
                        "soil_ph": round(random.uniform(6.0, 7.2), 1),
                        "soil_temperature": round(random.uniform(16, 26), 1),
                        "organic_matter": round(random.uniform(4.5, 8.2), 1),
                        "microbial_activity": round(random.uniform(75, 95), 1),
                        "beneficial_microorganisms": round(random.uniform(850, 1200), 0),
                    }
                elif "Regenerative" in device.establishment.name:
                    # Regenerative Grain Ranch - focus on carbon sequestration
                    data = {
                        "soil_moisture": round(random.uniform(25, 65), 1),
                        "soil_ph": round(random.uniform(6.5, 7.8), 1),
                        "soil_temperature": round(random.uniform(12, 25), 1),
                        "soil_carbon_ppm": round(random.uniform(2800, 4200), 0),
                        "carbon_sequestration_rate": round(random.uniform(4.2, 7.8), 1),
                        "organic_matter_percentage": round(random.uniform(3.5, 6.2), 1),
                    }
                else:
                    # Premium Citrus Ranch - standard soil monitoring
                    data = {
                        "soil_moisture": round(random.uniform(25, 85), 1),
                        "soil_ph": round(random.uniform(6.2, 7.4), 1),
                        "soil_temperature": round(random.uniform(15, 28), 1),
                        "nitrogen_ppm": round(random.uniform(180, 250), 1),
                        "phosphorus_ppm": round(random.uniform(25, 65), 1),
                        "potassium_ppm": round(random.uniform(140, 220), 1),
                    }
            elif device.device_type == "weather_station":
                # Specialized weather data based on establishment
                if "Organic" in device.establishment.name:
                    # Research-grade weather station
                    data = {
                        "temperature": round(random.uniform(14, 28), 1),
                        "humidity": round(random.uniform(45, 85), 1),
                        "wind_speed": round(random.uniform(0, 12), 1),
                        "rainfall": round(random.uniform(0, 15), 1),
                        "uv_index": random.randint(2, 9),
                        "barometric_pressure": round(random.uniform(1000, 1020), 1),
                        "research_grade": True,
                    }
                elif "Regenerative" in device.establishment.name:
                    # Climate monitoring for grain farming
                    data = {
                        "temperature": round(random.uniform(8, 32), 1),
                        "humidity": round(random.uniform(25, 75), 1),
                        "wind_speed": round(random.uniform(0, 18), 1),
                        "rainfall": round(random.uniform(0, 35), 1),
                        "uv_index": random.randint(1, 12),
                        "barometric_pressure": round(random.uniform(990, 1030), 1),
                        "growing_degree_days": round(random.uniform(0, 25), 1),
                    }
                else:
                    # Standard weather monitoring for citrus
                    data = {
                        "temperature": round(random.uniform(12, 32), 1),
                        "humidity": round(random.uniform(35, 85), 1),
                        "wind_speed": round(random.uniform(0, 15), 1),
                        "rainfall": round(random.uniform(0, 25), 1),
                        "uv_index": random.randint(1, 11),
                        "barometric_pressure": round(random.uniform(995, 1025), 1),
                    }
            elif device.device_type == "irrigation":
                if "Hydroponic" in device.name:
                    # Hydroponic system controller data
                    data = {
                        "nutrient_ph": round(random.uniform(5.8, 6.5), 1),
                        "ec_level": round(random.uniform(1.2, 2.0), 2),
                        "water_temperature": round(random.uniform(18, 24), 1),
                        "flow_rate": round(random.uniform(15, 35), 1),
                        "system_efficiency": round(random.uniform(0.92, 0.98), 3),
                        "organic_compliance": True,
                    }
                else:
                    # Standard irrigation controller data
                    data = {
                        "water_flow_rate": round(random.uniform(10, 45), 1),
                        "pressure": round(random.uniform(2.1, 3.8), 1),
                        "system_efficiency": round(random.uniform(0.88, 0.96), 3),
                        "energy_consumption": round(random.uniform(0.5, 2.2), 2),
                        "water_savings": round(random.uniform(35, 70), 1),
                    }
            elif device.device_type == "equipment_monitor":
                # Specialized equipment monitoring based on device name
                if "AI" in device.name or "Analytics" in device.name:
                    data = {
                        "system_status": "optimal",
                        "ai_confidence": round(random.uniform(0.85, 0.98), 3),
                        "processing_speed": round(random.uniform(120, 280), 1),
                        "data_quality": "high",
                        "model_accuracy": round(random.uniform(0.92, 0.98), 3),
                    }
                elif "Carbon" in device.name:
                    data = {
                        "system_status": "operational",
                        "carbon_capture_rate": round(random.uniform(4.5, 8.2), 1),
                        "verification_score": round(random.uniform(0.95, 1.0), 3),
                        "credits_generated": round(random.uniform(0.8, 2.1), 2),
                        "monitoring_accuracy": round(random.uniform(0.94, 0.99), 3),
                    }
                elif "Organic" in device.name:
                    data = {
                        "system_status": "compliant",
                        "organic_compliance_score": round(random.uniform(0.95, 1.0), 3),
                        "certification_status": "active",
                        "audit_readiness": round(random.uniform(0.88, 0.98), 3),
                        "input_verification": True,
                    }
                else:
                    # Standard equipment monitoring
                    data = {
                        "system_status": "normal",
                        "efficiency": round(random.uniform(0.85, 0.96), 3),
                        "operating_hours": round(random.uniform(2, 12), 1),
                        "maintenance_score": round(random.uniform(0.88, 0.96), 3),
                        "energy_consumption": round(random.uniform(15, 85), 1),
                    }
            elif device.device_type == "fuel_sensor":
                data = {
                    "fuel_level": round(random.uniform(10, 95), 1),
                    "fuel_consumption_rate": round(random.uniform(5, 25), 2),
                    "engine_hours": round(random.uniform(0.5, 8.0), 1),
                    "efficiency_rating": round(random.uniform(0.85, 0.98), 3),
                }
            else:
                data = {"status": "normal", "value": round(random.uniform(20, 90), 1)}

            IoTDataPoint.objects.create(device=device, timestamp=timestamp, data=data)

    def create_automated_carbon_monitoring(self, productions, user):
        """Create automated carbon monitoring rules"""
        self.stdout.write("   🤖 Setting up automated carbon monitoring...")

        # Create automation rules that would trigger carbon calculations
        rules_created = 0

        for production in productions[:5]:  # Sample for first few productions
            rule = AutomationRule.objects.create(
                name=f"Auto Carbon Tracking - {production.name}",
                establishment=production.parcel.establishment,
                description=f"Automatically track carbon emissions and sequestration for {production.name}",
                device_type="fuel_sensor",
                trigger_type="threshold",
                trigger_config={
                    "fuel_consumption": {"operator": "greater_than", "value": 20},
                    "production_id": production.id,
                    "event_types": ["fertilizer", "fuel", "equipment", "processing"],
                    "auto_calculate": True,
                },
                action_type="create_event",
                action_config={
                    "create_carbon_entry": True,
                    "verify_calculations": True,
                    "send_notifications": True,
                    "update_dashboard": True,
                    "event_type": "equipment",
                    "auto_approve": False,
                },
                is_active=True,
                created_by=user,
            )
            rules_created += 1

        self.stdout.write(f"   ✅ Automation rules: {rules_created} carbon monitoring rules")

    def create_carbon_offset_marketplace(self, establishments, user):
        """Create carbon offset marketplace integration"""
        self.stdout.write("   💰 Creating carbon offset marketplace...")

        # Create offset projects
        projects_created = 0

        for establishment in establishments:
            project = CarbonOffsetProject.objects.create(
                name=f"Carbon Sequestration Program - {establishment.name}",
                description=f"Verified carbon sequestration through regenerative agriculture practices at {establishment.name}. Annual sequestration rate: {(establishment.total_acreage or 100.0) * 4.2} tons CO2e. Verified by SCS Global Services with quarterly monitoring and blockchain registry.",
                project_type="agriculture_sequestration",
                certification_standard="VCS + Gold Standard",
                location=f"{establishment.city}, {establishment.state}",
                price_per_ton=Decimal("25.50"),
                available_capacity=Decimal(
                    str(int((establishment.total_acreage or 100.0) * 4.2))
                ),  # tons CO2e per year
            )
            projects_created += 1

            # Create offset purchases showing market activity
            purchase = CarbonOffsetPurchase.objects.create(
                project=project,
                user=user,
                amount=Decimal("50.0"),
                price_per_ton=project.price_per_ton,
                total_price=Decimal("50.0") * project.price_per_ton,
                status="completed",
                is_verified=True,
            )

        self.stdout.write(f"   ✅ Carbon marketplace: {projects_created} offset projects, active trading")

    def create_carbon_credit_generation(self, productions, user):
        """Generate carbon credits from production data"""
        self.stdout.write("   💰 Generating carbon credits from sequestration...")

        credits_generated = 0

        for production in productions:
            if production.finish_date:  # Only for completed productions
                # Calculate net carbon sequestration
                carbon_entries = CarbonEntry.objects.filter(production=production)
                net_sequestration = sum(
                    [float(entry.co2e_amount) for entry in carbon_entries if entry.type == "offset"]
                )

                if net_sequestration > 1.0:  # Minimum 1 ton for credit eligibility
                    # Create carbon credit entries
                    CarbonEntry.objects.create(
                        establishment=production.parcel.establishment,
                        production=production,
                        created_by=user,
                        source=CarbonSource.objects.get(name="Cover Crop Sequestration"),
                        type="offset",
                        year=2025,  # Use 2025 as the demo year for all carbon entries
                        amount=abs(net_sequestration),
                        co2e_amount=-abs(net_sequestration),
                        description=f"Carbon credits generated from {production.name}",
                        verification_status="credit_eligible",
                        extra_data={
                            "credit_type": "agricultural_sequestration",
                            "credit_standard": "VCS + Gold Standard",
                            "market_value": f"${abs(net_sequestration) * 25.50:.2f}",
                            "registry": "American Carbon Registry",
                        },
                    )
                    credits_generated += abs(net_sequestration)

        self.stdout.write(f"   ✅ Carbon credits: {credits_generated:.1f} tons CO2e generated")

    def create_comprehensive_certifications(self, productions):
        """Create comprehensive certifications for productions"""
        self.stdout.write("   🏆 Creating sustainability certifications...")

        certifications_created = 0

        for production in productions[:10]:  # Sample for first 10 productions
            cert = CarbonCertification.objects.create(
                establishment=production.parcel.establishment,
                production=production,
                certifier="Carbon Trust Standard",
                certificate_id=f"CTS-{production.id}-{uuid.uuid4().hex[:8].upper()}",
                issue_date=timezone.now().date(),
                expiry_date=timezone.now().date() + timezone.timedelta(days=365),
                document="certifications/carbon_certificate.pdf",  # Placeholder path
                is_usda_soe_verified=True,
                verification_date=timezone.now().date(),
                verification_details=f"Third-party verified carbon neutral certification for {production.name}. Methodology: PAS 2050:2011. Carbon footprint: 0.25 kg CO2e per kg product (58% below industry average). Certifications include: Carbon Neutral Product, Regenerative Organic Certified, USDA Organic, Fair Trade Certified, Rainforest Alliance, Non-GMO Project Verified. Environmental benefits: Carbon negative production, Soil health improvement, Biodiversity enhancement, Water conservation, Renewable energy use.",
            )
            certifications_created += 1

        self.stdout.write(f"   ✅ Certifications: {certifications_created} comprehensive certifications")

    def create_sustainability_achievement_badges(self, productions):
        """Create sustainability achievement badges"""
        self.stdout.write("   🎖️ Creating sustainability badges...")

        badges_created = 0

        # Create or get the sustainability badges
        badge_data = [
            {
                "name": "Carbon Negative Champion",
                "description": "Achieved verified carbon negative production, sequestering more CO2 than emitted through regenerative practices, biodiversity enhancement, water conservation, and renewable energy use.",
                "criteria": {
                    "carbon_sequestration": True,
                    "usda_verification": True,
                    "third_party_audit": True,
                    "carbon_sequestered_per_acre": 4.2,
                    "premium_pricing": 45,
                    "water_savings": 65,
                    "biodiversity_increase": 180,
                    "soil_health_score": 96,
                    "renewable_energy": True,
                    "regenerative_practices": True,
                },
                "minimum_score": 90,
                "is_automatic": True,
                "icon": "badges/carbon_negative_gold.png",
                "usda_factors_used": True,
            },
            {
                "name": "Regenerative Agriculture Leader",
                "description": "Leading in regenerative agricultural practices that improve soil health and biodiversity.",
                "criteria": {
                    "regenerative_practices": True,
                    "soil_health_improvement": True,
                    "biodiversity_enhancement": True,
                },
                "minimum_score": 85,
                "is_automatic": True,
                "usda_factors_used": True,
            },
            {
                "name": "Premium Market Access",
                "description": "Achieving premium pricing through sustainable and transparent production practices.",
                "criteria": {"premium_pricing": True, "market_access": True, "quality_certification": True},
                "minimum_score": 80,
                "is_automatic": True,
                "usda_factors_used": True,
            },
        ]

        for badge_info in badge_data:
            badge, created = SustainabilityBadge.objects.get_or_create(name=badge_info["name"], defaults=badge_info)

            if created:
                badges_created += 1

            # Associate badge with top performing productions
            for production in productions[:15]:  # Top 15 productions
                badge.productions.add(production)

        self.stdout.write(f"   ✅ Badges: {badges_created} sustainability achievement badges")

    def create_carbon_reports_with_trends(self, productions, establishments):
        """Create carbon reports showing trends over time"""
        self.stdout.write("   📊 Creating carbon trend reports...")

        reports_created = 0

        for establishment in establishments:
            # Create annual carbon report
            report = CarbonReport.objects.create(
                establishment=establishment,
                period_start=timezone.now().date().replace(month=1, day=1),
                period_end=timezone.now().date().replace(month=12, day=31),
                total_emissions=1247.5,
                total_offsets=2856.8,
                net_footprint=-1609.3,  # Negative = net sequestration
                carbon_score=92,  # High score for carbon negative operations
                generated_at=timezone.now(),
                usda_factors_used=True,
                # Enhanced transparency fields from migration 0028
                detailed_breakdown={
                    "fertilizer_emissions": 438.2,
                    "equipment_emissions": 312.1,
                    "transportation_emissions": 134.8,
                    "energy_emissions": 362.4,
                    "cover_crop_sequestration": -1285.5,
                    "no_till_sequestration": -394.2,
                    "tree_sequestration": -1177.1,
                },
                trend_analysis={
                    "yearly_improvement": 15.3,
                    "carbon_reduction_rate": 0.18,
                    "efficiency_trends": ["increasing", "stable", "improving"],
                    "projection_2026": -2100.0,
                },
                improvement_tracking={
                    "initiatives": ["cover_crops", "precision_fertilizer", "renewable_energy"],
                    "implementation_status": {"cover_crops": "completed", "precision_fertilizer": "in_progress"},
                    "expected_impact": 450.2,
                },
                stakeholder_insights={
                    "farmer_benefits": "25% cost reduction through efficiency gains",
                    "consumer_impact": "Carbon negative produce available year-round",
                    "regulator_compliance": "Exceeds all carbon offset standards",
                },
            )
            reports_created += 1

        self.stdout.write(f"   ✅ Reports: {reports_created} comprehensive carbon trend reports")

    def create_consumer_users(self):
        """Create consumer users for scan activity"""
        self.stdout.write("   👥 Creating consumer users...")

        consumer_users = []
        consumer_profiles = [
            ("Emily Chen", "emily.chen@email.com", "San Francisco", "CA", "Sustainability enthusiast"),
            ("Michael Rodriguez", "michael.r@email.com", "Los Angeles", "CA", "Organic food advocate"),
            ("Sarah Johnson", "sarah.j@email.com", "Seattle", "WA", "Environmental scientist"),
            ("David Kim", "david.kim@email.com", "Portland", "OR", "Climate action supporter"),
            ("Lisa Thompson", "lisa.t@email.com", "Denver", "CO", "Health-conscious consumer"),
            ("James Wilson", "james.w@email.com", "Austin", "TX", "Regenerative agriculture advocate"),
            ("Anna Garcia", "anna.g@email.com", "Phoenix", "AZ", "Sustainable living blogger"),
            ("Robert Davis", "robert.d@email.com", "San Diego", "CA", "Carbon footprint tracker"),
            ("Jennifer Lee", "jennifer.l@email.com", "Sacramento", "CA", "Organic farmer"),
            ("Christopher Martinez", "chris.m@email.com", "Fresno", "CA", "Local food supporter"),
        ]

        for first_name, email, city, state, bio in consumer_profiles:
            last_name = first_name.split()[1] if len(first_name.split()) > 1 else "Consumer"
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": first_name.split()[0],
                    "last_name": last_name,
                    "is_active": True,
                },
            )
            if created:
                user.set_password("ConsumerDemo2024!")
                user.save()

            consumer_users.append(user)

        self.stdout.write(f"   ✅ Consumer users: {len(consumer_users)} engaged consumers")
        return consumer_users

    def create_extensive_scan_activity(self, productions):
        """Create extensive QR code scan activity"""
        self.stdout.write("   📱 Creating consumer scan activity...")

        consumer_users = self.create_consumer_users()
        scans_created = 0

        for production in productions:
            if production.published:
                # Create 15-45 scans per production
                scan_count = random.randint(15, 45)

                for _ in range(scan_count):
                    user = random.choice(consumer_users)
                    scan_date = production.finish_date + timezone.timedelta(days=random.randint(1, 90))

                    scan = HistoryScan.objects.create(
                        history=production,
                        user=user,
                        ip_address=f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}",
                        city=random.choice(["San Francisco", "Los Angeles", "Seattle", "Portland"]),
                        country="USA",
                        comment=f"Scanned from {random.choice(['iPhone', 'Android', 'iPad'])} device. "
                        f"Source: {random.choice(['organic', 'social_media', 'retailer', 'direct'])}. "
                        f"Context: {random.choice(['grocery_store', 'farmers_market', 'restaurant', 'home'])}. "
                        f"Engagement: {random.randint(15, 180)}s. "
                        f"Viewed: {', '.join(random.choice([['carbon_footprint', 'sustainability'], ['farm_story', 'certifications'], ['carbon_footprint', 'farm_story', 'reviews']]))}. "
                        f"Actions: {', '.join(random.choice([['view_carbon_data'], ['view_farm_story', 'share_product'], ['leave_review', 'view_certifications']]))}",
                    )
                    scans_created += 1

        self.stdout.write(f"   ✅ Scan activity: {scans_created:,} consumer scans generated")

    def create_compelling_reviews_and_stories(self, productions):
        """Create compelling consumer reviews and stories"""
        self.stdout.write("   ⭐ Creating consumer reviews and stories...")

        reviews_created = 0

        # Get consumer users
        consumer_users = User.objects.filter(email__endswith="@email.com")

        review_templates = [
            {
                "rating": 5,
                "title": "Amazing transparency!",
                "content": "Love seeing exactly how my food is grown and the positive impact on the environment. The carbon-negative certification gives me confidence in my choices.",
                "highlights": ["transparency", "environmental_impact", "carbon_negative"],
            },
            {
                "rating": 5,
                "title": "Best quality and taste",
                "content": "The flavor is incredible - you can taste the difference when food is grown with care for the soil and environment. Supporting regenerative agriculture!",
                "highlights": ["quality", "taste", "regenerative_agriculture"],
            },
            {
                "rating": 5,
                "title": "Climate action through food",
                "content": "Every purchase helps fight climate change. The detailed carbon data and blockchain verification make me trust this is real impact.",
                "highlights": ["climate_action", "carbon_data", "blockchain_verification"],
            },
            {
                "rating": 4,
                "title": "Worth the premium price",
                "content": "More expensive than conventional, but worth it for the environmental benefits and superior quality. My family loves the taste!",
                "highlights": ["premium_quality", "environmental_benefits", "family_approved"],
            },
            {
                "rating": 5,
                "title": "Future of farming",
                "content": "This is how all food should be grown - sustainable, transparent, and beneficial for the planet. The farm story is inspiring!",
                "highlights": ["sustainability", "transparency", "inspiring_story"],
            },
        ]

        for production in productions:
            if production.published:
                # Create 3-8 reviews per production
                review_count = random.randint(3, 8)

                for _ in range(review_count):
                    if consumer_users:
                        user = random.choice(consumer_users)
                        template = random.choice(review_templates)

                        review = Review.objects.create(
                            production=production,
                            user=user,
                            rating=template["rating"],
                            headline=template["title"],
                            written_review=template["content"]
                            + f"\n\nPurchase context: {random.choice(['farmers_market', 'grocery_store', 'online_order', 'restaurant'])}. "
                            f"Highlights: {', '.join(template['highlights'])}. "
                            f"Would recommend: Yes. "
                            f"Sustainability interest: {random.choice(['carbon_footprint', 'organic_farming', 'regenerative_agriculture', 'biodiversity', 'water_conservation'])}",
                        )
                        reviews_created += 1

        self.stdout.write(f"   ✅ Reviews: {reviews_created} authentic consumer reviews")

    def calculate_and_apply_premium_pricing(self, productions):
        """Calculate and apply premium pricing based on sustainability"""
        self.stdout.write("   💰 Calculating premium pricing achievements...")

        pricing_applied = 0

        for production in productions:
            if production.earning:
                # Calculate premium based on sustainability score
                sustainability_score = production.extra_data.get("sustainability_score", 85)
                base_premium = 25  # Base 25% premium

                # Additional premium for high sustainability
                if sustainability_score >= 95:
                    premium_percentage = 45
                elif sustainability_score >= 90:
                    premium_percentage = 38
                elif sustainability_score >= 85:
                    premium_percentage = 32
                else:
                    premium_percentage = 25

                # Calculate market pricing
                conventional_price = production.earning / (1 + (premium_percentage / 100))
                premium_amount = production.earning - conventional_price

                # Update production with pricing details
                production.extra_data.update(
                    {
                        "conventional_market_price": f"${conventional_price:.2f}",
                        "premium_price": f"${production.earning:.2f}",
                        "premium_amount": f"${premium_amount:.2f}",
                        "premium_percentage": f"{premium_percentage}%",
                        "premium_justification": [
                            "Carbon negative certification",
                            "Regenerative farming practices",
                            "Complete supply chain transparency",
                            "Third-party sustainability verification",
                            "Superior quality and taste",
                            "Environmental and social impact",
                        ],
                    }
                )
                production.save()
                pricing_applied += 1

        self.stdout.write(f"   ✅ Premium pricing: {pricing_applied} productions with sustainability premiums")

    def create_roi_analysis(self, productions, establishments):
        """Create ROI analysis for sustainability investments"""
        self.stdout.write("   📈 Creating ROI analysis...")

        # Revenue estimates based on establishment size and crop types
        revenue_estimates = {
            "GreenHarvest Premium Citrus Ranch": 18200000,  # $18.2M
            "GreenHarvest Organic Innovation Center": 8900000,  # $8.9M
            "GreenHarvest Regenerative Grain Ranch": 3800000,  # $3.8M
        }

        for establishment in establishments:
            # Calculate sustainability ROI
            annual_revenue = revenue_estimates.get(establishment.name, 0)
            sustainability_investment = annual_revenue * 0.15  # 15% of revenue invested in sustainability

            # Premium revenue from sustainability
            premium_revenue = annual_revenue * 0.35  # 35% of revenue from premium pricing

            # Calculate ROI
            roi_percentage = ((premium_revenue - sustainability_investment) / sustainability_investment) * 100

            # Store ROI data in location_highlights field for now
            roi_data = f"Annual Revenue: ${annual_revenue:,.0f}, Sustainability Investment: ${sustainability_investment:,.0f}, Premium Revenue: ${premium_revenue:,.0f}, ROI: {roi_percentage:.1f}%"

            # Update establishment with ROI data in location_highlights
            establishment.location_highlights = f"{establishment.location_highlights}, ROI Analysis: {roi_data}"
            establishment.save()

        self.stdout.write(f"   ✅ ROI analysis: {len(establishments)} establishments with sustainability ROI")

    def create_blockchain_verification_network(self, productions):
        """Create blockchain verification network"""
        self.stdout.write("   ⛓️ Creating blockchain verification network...")

        verified_count = 0

        for production in productions:
            if production.published:
                # Create blockchain verification entry
                blockchain_data = {
                    "transaction_hash": f"0x{uuid.uuid4().hex}",
                    "block_number": random.randint(18000000, 19000000),
                    "network": "Ethereum",
                    "contract_address": "0x1234567890abcdef1234567890abcdef12345678",
                    "verification_timestamp": timezone.now().isoformat(),
                    "data_hash": f"0x{uuid.uuid4().hex}",
                    "verified_data": {
                        "production_id": production.id,
                        "carbon_footprint": "0.25 kg CO2e per kg",
                        "sustainability_score": production.extra_data.get("sustainability_score", 85),
                        "certifications": production.extra_data.get("certifications", []),
                        "carbon_negative": production.extra_data.get("carbon_negative_certified", False),
                        "verification_authority": "USDA Agricultural Research Service",
                    },
                }

                # Update production with blockchain data
                production.extra_data.update(
                    {
                        "blockchain_verified": True,
                        "blockchain_data": blockchain_data,
                        "verification_url": f'https://etherscan.io/tx/{blockchain_data["transaction_hash"]}',
                        "immutable_record": True,
                    }
                )
                production.save()
                verified_count += 1

        self.stdout.write(f"   ✅ Blockchain: {verified_count} productions verified on blockchain")

    def publish_productions_with_qr_codes(self, productions):
        """Publish productions with QR codes for consumer access"""
        self.stdout.write("   📱 Publishing productions with QR codes...")

        published_count = 0

        for production in productions:
            if production.finish_date and not production.published:
                # Generate QR code URL
                qr_url = f"https://app.trazo.io/scan/{production.id}"

                # Update production with QR code and publishing data
                production.extra_data.update(
                    {
                        "qr_code_url": qr_url,
                        "published_date": timezone.now().isoformat(),
                        "consumer_access": True,
                        "transparency_score": "99.7%",
                        "scan_enabled": True,
                        "public_visibility": True,
                    }
                )

                # Publish the production
                production.published = True
                production.save()
                published_count += 1

        self.stdout.write(f"   ✅ Publishing: {published_count} productions published with QR codes")

    def fix_parcel_current_history(self, company):
        """Fix current_history field for all parcels to ensure API works properly"""
        self.stdout.write("   🔧 Fixing parcel current_history fields...")

        from history.models import History
        from product.models import Parcel

        parcels = Parcel.objects.filter(establishment__company=company)
        fixed_count = 0

        for parcel in parcels:
            # Check if parcel has current_history set
            if parcel.current_history is None:
                # Look for unfinished productions
                unfinished_productions = History.objects.filter(
                    parcel=parcel, finish_date__isnull=True, published=False
                )

                if unfinished_productions.exists():
                    first_unfinished = unfinished_productions.first()
                    parcel.current_history = first_unfinished
                    parcel.save()
                    fixed_count += 1

        self.stdout.write(f"   ✅ Fixed current_history for {fixed_count} parcels")
        return fixed_count

    def create_ultimate_demo_summary(self, company, user, productions, establishments):
        """Create ultimate demo summary and key metrics"""
        self.stdout.write(self.style.SUCCESS("\n🎯 ULTIMATE DEMO SUMMARY & KEY METRICS"))

        # Fix parcel current_history fields to ensure API works properly
        self.fix_parcel_current_history(company)

        # Calculate comprehensive metrics
        total_area = sum([(est.total_acreage or 100.0) for est in establishments])
        total_productions = len(productions)
        completed_productions = len([p for p in productions if p.finish_date])

        # Carbon metrics
        total_emissions = sum(
            [
                float(entry.co2e_amount)
                for entry in CarbonEntry.objects.filter(establishment__company=company, type="emission")
            ]
        )
        total_sequestration = abs(
            sum(
                [
                    float(entry.co2e_amount)
                    for entry in CarbonEntry.objects.filter(establishment__company=company, type="offset")
                ]
            )
        )
        net_carbon_impact = total_sequestration - total_emissions

        # Financial metrics
        total_revenue = sum([p.earning for p in productions if p.earning])
        avg_premium = 42  # Average premium percentage

        # Print impressive summary
        self.stdout.write(self.style.SUCCESS("🌟 TRAZO ULTIMATE DEMO - SUCCESS METRICS 🌟"))
        self.stdout.write("")
        self.stdout.write(f"🏢 Company: {company.name}")
        self.stdout.write(f"📍 Operations: {len(establishments)} establishments, {total_area} hectares")
        self.stdout.write(f"💰 Revenue: ${total_revenue:,.2f} (${total_revenue * 0.25:,.2f} sustainability premium)")
        self.stdout.write("")
        self.stdout.write(f"🌍 Carbon Impact: {round(net_carbon_impact / 1000, 1)} tons CO2e SEQUESTERED")
        self.stdout.write(f"💚 Carbon Credits: {int(net_carbon_impact / 1000)} tons generated")
        self.stdout.write(f"💎 Credit Revenue: ${int(net_carbon_impact / 1000) * 25.50:,.2f}")
        self.stdout.write("")
        self.stdout.write(f"📱 Productions: {total_productions} total, {completed_productions} completed")
        self.stdout.write(f"⚡ Events: {self.events_created} agricultural events")
        self.stdout.write(f"🔢 Carbon Entries: {self.carbon_entries_created} USDA-verified calculations")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("✅ ULTIMATE DEMO DATA CREATION COMPLETE!"))
        self.stdout.write("")
        self.stdout.write("🎯 **Demo Login Credentials:**")
        self.stdout.write(f"   Email: {user.email}")
        self.stdout.write("   Password: TrazoDemo2025!")
        self.stdout.write("")
        self.stdout.write("🚀 **This demo showcases:**")
        self.stdout.write("   ✓ Complete carbon transparency with USDA-verified calculations")
        self.stdout.write("   ✓ Multi-year production trends showing continuous improvement")
        self.stdout.write("   ✓ Premium pricing achievement through sustainability")
        self.stdout.write("   ✓ Advanced IoT and AI integration")
        self.stdout.write("   ✓ Blockchain verification and complete traceability")
        self.stdout.write("   ✓ Carbon offset marketplace and credit generation")
        self.stdout.write("   ✓ Comprehensive certifications and compliance")
        self.stdout.write("   ✓ Authentic consumer engagement and reviews")
        self.stdout.write("   ✓ Clear ROI and competitive advantages")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Ready to impress potential Trazo users! 🌟"))
