"""
Comprehensive demo data seeder v2 - Simulates real-world agricultural operation
with proper event-to-carbon-entry flow, diverse carbon sources, and production-ready data
"""

import json
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, models, transaction
from django.utils import timezone

from carbon.models import (
    CarbonCertification,
    CarbonEntry,
    CarbonOffsetProject,
    CarbonOffsetPurchase,
    CarbonSource,
    IoTDataPoint,
    IoTDevice,
    SustainabilityBadge,
)
from carbon.services.event_carbon_calculator import EventCarbonCalculator
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
    help = "Create comprehensive demo data v2 with real-world event-to-carbon flow"

    def __init__(self):
        super().__init__()
        self.carbon_calculator = EventCarbonCalculator()
        self.carbon_entries_created = 0
        self.events_created = 0

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("🌱 Creating comprehensive Trazo demo data V2..."))

        with transaction.atomic():
            # 1. Setup base entities
            user = self.create_demo_user()
            company = self.create_demo_company()
            self.create_work_relationship(user, company)
            subscription = self.create_subscription(company)

            # 2. Create carbon sources with proper categories
            self.create_comprehensive_carbon_sources()

            # 3. Create establishments
            establishment1 = self.create_establishment_1(company)
            establishment2 = self.create_establishment_2(company)

            # 4. Create parcels
            parcels_1 = self.create_parcels_establishment_1(establishment1)
            parcels_2 = self.create_parcels_establishment_2(establishment2)

            # 5. Create products
            products = self.create_products()

            # 6. Create productions with comprehensive events
            all_productions = []

            # Establishment 1 productions
            self.stdout.write("📦 Creating Establishment 1 productions...")
            all_productions.extend(
                self.create_citrus_production_with_events(
                    parcels_1[0], products["valencia_orange"], user, "Valencia Orange 2024-2025"
                )
            )
            all_productions.extend(
                self.create_citrus_production_with_events(
                    parcels_1[1], products["navel_orange"], user, "Navel Orange 2024-2025"
                )
            )
            all_productions.extend(
                self.create_almond_production_with_events(
                    parcels_1[2], products["nonpareil_almond"], user, "Nonpareil Almond 2024-2025"
                )
            )

            # Establishment 2 productions
            self.stdout.write("📦 Creating Establishment 2 productions...")
            all_productions.extend(
                self.create_avocado_production_with_events(
                    parcels_2[0], products["hass_avocado"], user, "Hass Avocado 2024-2025"
                )
            )
            all_productions.extend(
                self.create_strawberry_production_with_events(
                    parcels_2[1], products["strawberry"], user, "Organic Strawberry 2024-2025"
                )
            )
            all_productions.extend(
                self.create_lettuce_production_with_events(
                    parcels_2[2], products["butter_lettuce"], user, "Butter Lettuce Cycle 2024-2025"
                )
            )

            # 7. Create IoT devices and automated carbon entries
            self.create_iot_infrastructure_with_carbon(establishment1, establishment2, user)

            # 8. Create carbon offset purchases with proper entries
            self.create_carbon_offset_projects_and_purchases([establishment1, establishment2], user)

            # 9. Create certifications and badges
            self.create_certifications_and_badges(all_productions)

            # 10. Create recent scans and reviews
            self.create_recent_activity(all_productions, user)

            # 11. Publish all finished productions
            self.publish_finished_productions(all_productions)

            # 12. Final verification and summary
            self.verify_and_summarize(company, user, all_productions)

    def create_demo_user(self):
        """Create demo user"""
        user, created = User.objects.get_or_create(
            email="demo@trazo.io",
            defaults={
                "first_name": "Sarah",
                "last_name": "Martinez",
                "is_active": True,
            },
        )
        if created:
            user.set_password("TrazoDemo2025!")
            user.save()
            self.stdout.write(f"✅ Created demo user: {user.email}")
        return user

    def create_demo_company(self):
        """Create demo company"""
        company, _ = Company.objects.get_or_create(
            name="GreenHarvest Agricultural Enterprises",
            defaults={
                "tradename": "GreenHarvest Farms",
                "description": "Leading sustainable agriculture operation specializing in premium citrus, tree nuts, and organic vegetables. Pioneer in carbon-neutral farming practices and blockchain-verified supply chain transparency.",
                "address": "15847 Sustainable Agriculture Boulevard",
                "city": "Fresno",
                "state": "California",
                "zip_code": "93711",
                "country": "USA",
                "contact_phone": "+1-559-555-0987",
                "contact_email": "info@greenharvest.com",
                "website": "https://greenharvest.com",
                "employee_count": 85,
                "industry": "Diversified Premium Agriculture",
                "legal_structure": "LLC",
                "blockchain_subscription_status": True,
            },
        )
        self.stdout.write(f"✅ Created demo company: {company.name}")
        return company

    def create_work_relationship(self, user, company):
        """Create work relationship"""
        WorksIn.objects.get_or_create(user=user, company=company, defaults={"role": "CA"})  # Company Admin

    def create_subscription(self, company):
        """Create subscription"""
        plan, _ = Plan.objects.get_or_create(
            name="Professional",
            defaults={
                "slug": "professional",
                "description": "Professional tier for agricultural operations",
                "price": 199.00,
                "interval": "monthly",
                "features": {
                    "carbon_tracking": True,
                    "blockchain_verification": True,
                    "iot_integration": True,
                    "usda_verification": True,
                    "carbon_offset_marketplace": True,
                },
            },
        )

        subscription, _ = Subscription.objects.get_or_create(
            company=company,
            defaults={
                "plan": plan,
                "status": "active",
                "current_period_start": timezone.now(),
                "current_period_end": timezone.now() + timezone.timedelta(days=30),
            },
        )
        return subscription

    def create_comprehensive_carbon_sources(self):
        """Create all necessary carbon sources with proper categories"""
        self.stdout.write("🔧 Creating comprehensive carbon sources...")

        sources_data = [
            # Emissions sources
            ("Nitrogen Fertilizer", "fertilizer", "kg", 11.0, "Synthetic nitrogen fertilizer emissions"),
            ("Phosphorus Fertilizer", "fertilizer", "kg", 1.25, "Phosphate fertilizer emissions"),
            ("Potassium Fertilizer", "fertilizer", "kg", 0.6, "Potash fertilizer emissions"),
            ("Organic Fertilizer", "fertilizer", "kg", 0.45, "Organic compost and manure emissions"),
            ("Diesel Fuel", "fuel", "liters", 2.68, "Agricultural machinery diesel consumption"),
            ("Gasoline", "fuel", "liters", 2.31, "Small equipment gasoline consumption"),
            ("Grid Electricity", "electricity", "kWh", 0.35, "Grid electricity consumption"),
            ("Natural Gas", "electricity", "m³", 2.03, "Natural gas for heating and processing"),
            ("Tractor Operations", "equipment", "hours", 8.5, "Tractor field operations"),
            ("Harvesting Equipment", "equipment", "hours", 12.3, "Harvesting machinery operations"),
            ("Irrigation Equipment", "irrigation", "hours", 3.2, "Irrigation system operations"),
            ("Product Transportation", "transport", "km", 0.12, "Product transportation to market"),
            ("Input Transportation", "transport", "km", 0.15, "Transportation of inputs to farm"),
            ("Post-Harvest Processing", "processing", "kg", 0.25, "Post-harvest processing activities"),
            ("Cold Storage", "processing", "kWh", 0.45, "Refrigeration and cold storage energy"),
            ("Packaging Materials", "materials", "kg", 1.8, "Packaging and container materials"),
            # Offset/Sequestration sources
            ("Cover Crop Sequestration", "sequestration", "hectare", -2.5, "Carbon sequestration from cover crops"),
            ("Solar Energy Generation", "renewable_energy", "kWh", -0.35, "On-farm solar energy generation"),
            ("Purchased Carbon Offsets", "purchased_offsets", "tons_co2e", -1.0, "Purchased carbon offset credits"),
        ]

        for name, category, unit, factor, description in sources_data:
            source, created = CarbonSource.objects.get_or_create(
                name=name,
                defaults={
                    "category": category,
                    "unit": unit,
                    "default_emission_factor": factor,
                    "description": description,
                    "usda_verified": factor > 0,
                    "usda_factors_based": factor > 0,
                },
            )
            if created:
                self.stdout.write(f"   ✅ Created source: {name} ({category})")

    def create_establishment_1(self, company):
        """Create first establishment"""
        establishment, _ = Establishment.objects.get_or_create(
            company=company,
            name="GreenHarvest Premium Citrus Ranch",
            defaults={
                "description": "Premium citrus and tree nut operation featuring state-of-the-art irrigation, solar-powered facilities, and regenerative farming practices",
                "address": "15847 Sustainable Agriculture Boulevard",
                "city": "Fresno",
                "state": "California",
                "zip_code": "93711",
                "country": "USA",
                "contact_phone": "+1-559-555-0987",
                "contact_email": "citrus@greenharvest.com",
                "total_acreage": 485.5,
                "crops_grown": ["Valencia Oranges", "Navel Oranges", "Nonpareil Almonds"],
                "sustainability_practices": [
                    "Solar power",
                    "precision irrigation",
                    "cover crops",
                    "beneficial insects",
                ],
                "water_sources": ["Drip irrigation with moisture sensors", "40% water reduction vs traditional"],
                "soil_types": ["Sandy loam", "Clay loam"],
                "conservation_practices": ["Annual soil testing", "compost application", "minimal tillage"],
                "irrigation_methods": ["Drip irrigation", "Micro sprinklers"],
                "about": "Award-winning citrus ranch combining 75 years of farming tradition with cutting-edge sustainable practices.",
                "custom_message": "Every orange tells a story of sustainable farming and environmental stewardship.",
                "certifications": "GlobalGAP, SQF Level 2, California Sustainable Winegrowing",
                "employee_count": 85,
                "establishment_type": "Mixed Conventional/Organic",
                "farming_method": "Sustainable Agriculture",
                "climate_zone": "Mediterranean",
                "year_established": 1949,
            },
        )
        self.stdout.write(f"✅ Created establishment: {establishment.name}")
        return establishment

    def create_establishment_2(self, company):
        """Create second establishment"""
        establishment, _ = Establishment.objects.get_or_create(
            company=company,
            name="GreenHarvest Sustainable Farm",
            defaults={
                "description": "Certified organic mixed vegetable operation specializing in premium avocados, strawberries, and leafy greens for direct-to-consumer markets",
                "address": "8932 Organic Valley Road",
                "city": "Salinas",
                "state": "California",
                "zip_code": "93901",
                "country": "USA",
                "contact_phone": "+1-831-555-0654",
                "contact_email": "organic@greenharvest.com",
                "total_acreage": 156.8,
                "crops_grown": ["Hass Avocados", "Organic Strawberries", "Butter Lettuce", "Mixed Greens"],
                "sustainability_practices": [
                    "Organic certified",
                    "renewable energy",
                    "water conservation",
                    "biodiversity",
                ],
                "water_sources": ["Rainwater harvesting", "recycled water system", "micro-sprinklers"],
                "soil_types": ["Loam", "Sandy loam"],
                "conservation_practices": ["Cover crops", "crop rotation", "organic amendments only"],
                "irrigation_methods": ["Micro-sprinklers", "Drip irrigation"],
                "about": "Family-owned organic farm dedicated to producing the healthiest, most sustainable produce while nurturing the land for future generations.",
                "custom_message": "From our family farm to your table - grown with love and respect for nature.",
                "certifications": "USDA Organic, CCOF, Demeter Biodynamic, ROC",
                "employee_count": 35,
                "establishment_type": "Certified Organic",
                "farming_method": "Organic Agriculture",
                "climate_zone": "Coastal Mediterranean",
                "year_established": 1995,
            },
        )
        self.stdout.write(f"✅ Created establishment: {establishment.name}")
        return establishment

    def create_parcels_establishment_1(self, establishment):
        """Create parcels for establishment 1"""
        parcels = []

        parcel_data = [
            {
                "name": "Valencia Heritage Grove",
                "identifier": "VHG-2024-01",
                "area": 125.5,
                "soil_type": "Sandy Loam",
                "location": {"lat": 36.7783, "lng": -119.7179},
                "planted_year": 2018,
                "tree_density": "120 trees/hectare",
                "irrigation_type": "Micro-sprinkler with moisture sensors",
                "slope": "Gentle (2-5%)",
                "aspect": "South-facing",
                "elevation": "102m",
                "description": "Premium Valencia orange grove with mature trees, optimal sun exposure, and advanced irrigation",
            },
            {
                "name": "Navel Premium Block",
                "identifier": "NPB-2024-02",
                "area": 98.5,
                "soil_type": "Clay Loam",
                "location": {"lat": 36.7790, "lng": -119.7195},
                "planted_year": 2019,
                "tree_density": "130 trees/hectare",
                "irrigation_type": "Drip irrigation with fertigation",
                "slope": "Level (0-2%)",
                "aspect": "Southwest-facing",
                "elevation": "98m",
                "description": "High-density navel orange plantation with precision agriculture technology",
            },
            {
                "name": "Almond Innovation Field",
                "identifier": "AIF-2024-03",
                "area": 201.0,
                "soil_type": "Loamy Sand",
                "location": {"lat": 36.7805, "lng": -119.7210},
                "planted_year": 2017,
                "tree_density": "170 trees/hectare",
                "irrigation_type": "Subsurface drip with automation",
                "slope": "Gentle (3-6%)",
                "aspect": "East-facing",
                "elevation": "110m",
                "description": "State-of-the-art almond orchard with bee-friendly practices and water conservation",
            },
        ]

        for data in parcel_data:
            parcel, _ = Parcel.objects.get_or_create(
                establishment=establishment,
                name=data["name"],
                defaults={
                    "unique_code": data["identifier"],
                    "area": data["area"],
                    "soil_type": data["soil_type"],
                    "polygon": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [data["location"]["lng"] - 0.01, data["location"]["lat"] - 0.01],
                                [data["location"]["lng"] + 0.01, data["location"]["lat"] - 0.01],
                                [data["location"]["lng"] + 0.01, data["location"]["lat"] + 0.01],
                                [data["location"]["lng"] - 0.01, data["location"]["lat"] + 0.01],
                                [data["location"]["lng"] - 0.01, data["location"]["lat"] - 0.01],
                            ]
                        ],
                    },
                    "map_metadata": {
                        "center": data["location"],
                        "zoom": 15,
                        "planted_year": data["planted_year"],
                        "tree_density": data["tree_density"],
                        "irrigation_type": data["irrigation_type"],
                        "slope": data["slope"],
                        "aspect": data["aspect"],
                        "elevation": data["elevation"],
                        "description": data["description"],
                    },
                },
            )
            parcels.append(parcel)

        return parcels

    def create_parcels_establishment_2(self, establishment):
        """Create parcels for establishment 2"""
        parcels = []

        parcel_data = [
            {
                "name": "Avocado Hillside",
                "identifier": "AVH-2024-01",
                "area": 65.5,
                "soil_type": "Well-drained Loam",
                "location": {"lat": 36.6772, "lng": -121.6555},
                "planted_year": 2020,
                "tree_density": "100 trees/hectare",
                "irrigation_type": "Micro-sprinkler with smart controllers",
                "description": "Premium Hass avocado grove with optimal drainage and climate",
            },
            {
                "name": "Strawberry Fields",
                "identifier": "STF-2024-02",
                "area": 45.0,
                "soil_type": "Sandy Loam",
                "location": {"lat": 36.6785, "lng": -121.6570},
                "planted_year": 2023,
                "plant_density": "65,000 plants/hectare",
                "irrigation_type": "Drip tape with plasticulture",
                "description": "Organic strawberry production with integrated pest management",
            },
            {
                "name": "Lettuce Valley",
                "identifier": "LTV-2024-03",
                "area": 31.5,
                "soil_type": "Rich Organic Loam",
                "location": {"lat": 36.6798, "lng": -121.6585},
                "planting_cycles": "6 per year",
                "irrigation_type": "Overhead sprinklers with timers",
                "description": "High-rotation organic lettuce and leafy greens production",
            },
        ]

        for data in parcel_data:
            parcel, _ = Parcel.objects.get_or_create(
                establishment=establishment,
                name=data["name"],
                defaults={
                    "unique_code": data["identifier"],
                    "area": data["area"],
                    "soil_type": data["soil_type"],
                    "polygon": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [data["location"]["lng"] - 0.005, data["location"]["lat"] - 0.005],
                                [data["location"]["lng"] + 0.005, data["location"]["lat"] - 0.005],
                                [data["location"]["lng"] + 0.005, data["location"]["lat"] + 0.005],
                                [data["location"]["lng"] - 0.005, data["location"]["lat"] + 0.005],
                                [data["location"]["lng"] - 0.005, data["location"]["lat"] - 0.005],
                            ]
                        ],
                    },
                    "map_metadata": {
                        "center": data["location"],
                        "zoom": 16,
                        "description": data["description"],
                        **{
                            k: v
                            for k, v in data.items()
                            if k not in ["name", "identifier", "area", "soil_type", "location", "description"]
                        },
                    },
                },
            )
            parcels.append(parcel)

        return parcels

    def create_products(self):
        """Create product catalog"""
        self.stdout.write("📦 Creating product catalog...")

        products = {}
        product_data = [
            ("valencia_orange", "Valencia Orange", "Premium late-season oranges perfect for juicing", "tons"),
            ("navel_orange", "Navel Orange", "Sweet seedless oranges ideal for fresh consumption", "tons"),
            ("nonpareil_almond", "Nonpareil Almond", "Premium blanched almonds with excellent flavor", "tons"),
            ("hass_avocado", "Hass Avocado", "Creamy organic avocados at perfect ripeness", "tons"),
            ("strawberry", "Organic Strawberry", "Sweet, juicy strawberries grown without pesticides", "tons"),
            ("butter_lettuce", "Butter Lettuce", "Tender butterhead lettuce for gourmet salads", "tons"),
        ]

        for key, name, description, unit in product_data:
            product, _ = Product.objects.get_or_create(name=name, defaults={"description": description})
            products[key] = product
            self.stdout.write(f"   ✅ Created product: {name}")

        return products

    def create_citrus_production_with_events(self, parcel, product, user, name):
        """Create citrus production with realistic event sequence"""
        self.stdout.write(f"   🍊 Creating {name} with comprehensive events...")

        # Create production
        history = History.objects.create(
            name=name,
            parcel=parcel,
            product=product,
            type="OR",  # Orchard
            start_date=timezone.now() - timezone.timedelta(days=365),
            finish_date=timezone.now() + timezone.timedelta(days=90),
            published=False,  # Will publish after events
            production_amount=125.5,
            description=f"Premium {product.name} production using sustainable practices",
            is_outdoor=True,
            age_of_plants=5,
            number_of_plants=int(parcel.area * 120),  # trees per hectare
            soil_ph=6.5,
            extra_data={
                "variety": product.name,
                "harvest_window": "March-May",
                "quality_grade": "Premium Export",
                "certifications": ["GlobalGAP", "SQF Level 2"],
            },
        )

        # Create comprehensive event sequence
        self.create_citrus_event_sequence(history, user)

        return [history]

    def create_citrus_event_sequence(self, history, user):
        """Create realistic citrus production event sequence with carbon calculations"""

        # 1. Soil preparation (beginning of season)
        soil_prep = SoilManagementEvent.objects.create(
            history=history,
            created_by=user,
            date=history.start_date,
            type="TI",  # Tillage
            description="Minimal tillage soil preparation with organic matter incorporation",
            soil_ph=Decimal("6.8"),
            organic_matter_percentage=Decimal("3.2"),
            amendment_type="Organic Compost",
            amendment_amount="5 tons/ha",
            carbon_sequestration_potential=Decimal("2.5"),
            extra_data={
                "equipment_used": "Low-impact cultivator",
                "depth_cm": 15,
                "carbon_benefit": "minimal_disturbance",
            },
        )
        self.events_created += 1
        self.simulate_carbon_calculation_from_event(soil_prep)

        # 2. Fertilizer applications (quarterly)
        fertilizer_schedule = [
            ("Spring Fertilization", 30, 200, 100, 80),
            ("Summer Fertilization", 120, 150, 75, 60),
            ("Fall Fertilization", 210, 180, 90, 70),
            ("Winter Fertilization", 300, 120, 60, 50),
        ]

        for fert_name, days_offset, n_amount, p_amount, k_amount in fertilizer_schedule:
            fert_event = ChemicalEvent.objects.create(
                history=history,
                created_by=user,
                description=f"{fert_name} - NPK {n_amount}-{p_amount}-{k_amount}",
                type="FE",  # Fertilizer
                date=history.start_date + timezone.timedelta(days=days_offset),
                commercial_name=f"NPK {n_amount}-{p_amount}-{k_amount}",
                volume=f"{n_amount + p_amount + k_amount} kg",
                concentration=f"N:{n_amount} P:{p_amount} K:{k_amount}",
                area=f"{history.parcel.area} hectares",
                way_of_application="broadcast spreader",
                time_period="seasonal application",
                observation="Optimal weather conditions - no rain forecast 48h",
                extra_data={
                    "n_content": n_amount,
                    "p_content": p_amount,
                    "k_content": k_amount,
                    "application_efficiency": 0.85,
                    "target": "Citrus nutrition",
                },
            )
            self.events_created += 1
            self.simulate_carbon_calculation_from_event(fert_event)

        # 3. Irrigation events (monthly during growing season)
        for month in range(12):
            irrigation_event = GeneralEvent.objects.create(
                history=history,
                created_by=user,
                name=f"Monthly Irrigation - Month {month + 1}",
                date=history.start_date + timezone.timedelta(days=month * 30),
                type="IR",  # Irrigation
                observation=f"Precision irrigation based on soil moisture sensors. Water applied: {random.uniform(800, 1200):.1f} cubic meters",
                extra_data={
                    "water_amount_m3": random.uniform(800, 1200),
                    "irrigation_hours": random.uniform(8, 12),
                    "energy_source": "solar_powered",
                },
            )
            self.events_created += 1
            # Note: Irrigation might have minimal carbon impact due to solar power

        # 4. Pest management (integrated approach)
        pest_events = [
            ("Spring IPM Assessment", 60, "monitoring", "Beneficial insect release"),
            ("Summer Pest Control", 150, "biological", "Predatory mite introduction"),
            ("Fall Disease Prevention", 240, "organic", "Neem oil application"),
        ]

        for pest_name, days_offset, pest_type, method in pest_events:
            pest_event = PestManagementEvent.objects.create(
                history=history,
                created_by=user,
                name=pest_name,
                date=history.start_date + timezone.timedelta(days=days_offset),
                pest_type="mixed",
                treatment_type=pest_type,
                product_used=method,
                area_treated=history.parcel.area,
                effectiveness="high",
                environmental_impact="minimal",
                extra_data={"approach": "integrated_pest_management"},
            )
            self.events_created += 1
            self.simulate_carbon_calculation_from_event(pest_event)

        # 5. Equipment operations (throughout season)
        equipment_events = [
            ("Spring Pruning", 45, "pruning_equipment", 8, 30),
            ("Mid-season Mowing", 180, "mower", 6, 25),
            ("Pre-harvest Preparation", 330, "various", 10, 40),
        ]

        for equip_name, days_offset, equip_type, hours, fuel in equipment_events:
            equip_event = EquipmentEvent.objects.create(
                history=history,
                created_by=user,
                name=equip_name,
                date=history.start_date + timezone.timedelta(days=days_offset),
                equipment_type=equip_type,
                hours_used=hours,
                fuel_consumed=fuel,
                maintenance_performed="Regular maintenance check",
                operators=2,
                extra_data={"equipment_efficiency": "high", "fuel_type": "diesel"},
            )
            self.events_created += 1
            self.simulate_carbon_calculation_from_event(equip_event)

        # 6. Harvest events
        harvest_date = history.start_date + timezone.timedelta(days=350)
        harvest_event = ProductionEvent.objects.create(
            history=history,
            created_by=user,
            name="Main Harvest",
            type="HA",  # Harvest
            date=harvest_date,
            amount=history.production_amount,
            unit="tons",
            quality_grade="Premium",
            destination="Packing house",
            notes="Excellent quality harvest with minimal waste",
            extra_data={"harvest_method": "hand_picked", "crew_size": 25, "duration_days": 5, "waste_percentage": 2.5},
        )
        self.events_created += 1
        self.simulate_carbon_calculation_from_event(harvest_event)

        # 7. Post-harvest processing
        processing_event = ProductionEvent.objects.create(
            history=history,
            created_by=user,
            name="Post-Harvest Processing",
            type="PR",  # Processing
            date=harvest_date + timezone.timedelta(days=1),
            amount=history.production_amount * 0.975,  # After waste removal
            unit="tons",
            quality_grade="Premium Export",
            destination="Distribution center",
            notes="Washing, grading, packing for premium markets",
            extra_data={
                "processing_energy_kwh": history.production_amount * 15,
                "packaging_materials_kg": history.production_amount * 8,
                "cold_storage_days": 3,
            },
        )
        self.events_created += 1
        self.simulate_carbon_calculation_from_event(processing_event)

    def create_almond_production_with_events(self, parcel, product, user, name):
        """Create almond production with events"""
        self.stdout.write(f"   🌰 Creating {name} with comprehensive events...")

        history = History.objects.create(
            name=name,
            parcel=parcel,
            product=product,
            type="OR",  # Orchard
            start_date=timezone.now() - timezone.timedelta(days=400),
            finish_date=timezone.now() - timezone.timedelta(days=50),
            published=False,
            production_amount=4.2,  # tons per hectare typical
            description="Premium Nonpareil almonds with bee-friendly practices",
            is_outdoor=True,
            age_of_plants=7,
            number_of_plants=int(parcel.area * 170),
            soil_ph=7.0,
            extra_data={
                "variety": "Nonpareil",
                "pollinator_varieties": ["Monterey", "Carmel"],
                "bee_hives_per_hectare": 5,
            },
        )

        # Similar comprehensive event creation for almonds
        self.create_almond_event_sequence(history, user)

        return [history]

    def create_almond_event_sequence(self, history, user):
        """Create almond production events"""
        # Similar to citrus but with almond-specific events
        # Including: dormant spray, bloom, hull split, harvest, etc.

        # Simplified for brevity - in real implementation would be as detailed as citrus
        events = [
            ("Dormant Spray", "chemical", 30),
            ("Bloom Nutrition", "fertilizer", 60),
            ("Summer Irrigation", "irrigation", 150),
            ("Hull Split Treatment", "production", 240),
            ("Harvest", "harvest", 300),
        ]

        for event_name, event_type, days_offset in events:
            if event_type == "fertilizer":
                event = ChemicalEvent.objects.create(
                    history=history,
                    created_by=user,
                    name=event_name,
                    type="FE",
                    date=history.start_date + timezone.timedelta(days=days_offset),
                    product_name="Almond Special NPK",
                    amount="300 kg",
                    area=history.parcel.area,
                    extra_data={"application_type": "fertigation"},
                )
                self.simulate_carbon_calculation_from_event(event)
            elif event_type == "harvest":
                event = ProductionEvent.objects.create(
                    history=history,
                    created_by=user,
                    name=event_name,
                    type="HA",
                    date=history.start_date + timezone.timedelta(days=days_offset),
                    amount=history.production_amount,
                    unit="tons",
                    quality_grade="Premium",
                    extra_data={"method": "mechanical_shaker"},
                )
                self.simulate_carbon_calculation_from_event(event)

            self.events_created += 1

    def create_avocado_production_with_events(self, parcel, product, user, name):
        """Create avocado production with events"""
        self.stdout.write(f"   🥑 Creating {name} with comprehensive events...")

        history = History.objects.create(
            name=name,
            parcel=parcel,
            product=product,
            type="GA",  # Garden
            start_date=timezone.now() - timezone.timedelta(days=365),
            finish_date=timezone.now() + timezone.timedelta(days=120),
            published=False,
            production_amount=12.5,
            description="Premium organic Hass avocados",
            is_outdoor=True,
            age_of_plants=4,
            number_of_plants=int(parcel.area * 100),
            soil_ph=6.0,
            extra_data={"variety": "Hass", "organic_certified": True, "water_conservation": "micro-sprinkler"},
        )

        self.create_organic_event_sequence(history, user, "avocado")

        return [history]

    def create_strawberry_production_with_events(self, parcel, product, user, name):
        """Create strawberry production with events"""
        self.stdout.write(f"   🍓 Creating {name} with comprehensive events...")

        history = History.objects.create(
            name=name,
            parcel=parcel,
            product=product,
            type="GA",  # Garden
            start_date=timezone.now() - timezone.timedelta(days=180),
            finish_date=timezone.now() + timezone.timedelta(days=30),
            published=False,
            production_amount=35.0,
            description="Certified organic strawberries",
            is_outdoor=True,
            age_of_plants=0,  # Annual crop
            number_of_plants=int(parcel.area * 65000),
            soil_ph=6.2,
            extra_data={"variety": "Albion", "organic_certified": True, "plasticulture": True},
        )

        self.create_organic_event_sequence(history, user, "strawberry")

        return [history]

    def create_lettuce_production_with_events(self, parcel, product, user, name):
        """Create lettuce production with events"""
        self.stdout.write(f"   🥬 Creating {name} with comprehensive events...")

        # Lettuce has multiple cycles per year
        productions = []

        for cycle in range(3):  # 3 cycles for demo
            history = History.objects.create(
                name=f"{name} - Cycle {cycle + 1}",
                parcel=parcel,
                product=product,
                type="GA",  # Garden
                start_date=timezone.now() - timezone.timedelta(days=180 - (cycle * 60)),
                finish_date=timezone.now() - timezone.timedelta(days=120 - (cycle * 60)),
                published=False,
                production_amount=25.0,
                description=f"Organic butter lettuce cycle {cycle + 1}",
                is_outdoor=True,
                age_of_plants=0,
                number_of_plants=int(parcel.area * 80000),
                soil_ph=6.5,
                extra_data={"variety": "Buttercrunch", "cycle_number": cycle + 1, "organic_certified": True},
            )

            self.create_organic_event_sequence(history, user, "lettuce")
            productions.append(history)

        return productions

    def create_organic_event_sequence(self, history, user, crop_type):
        """Create organic production event sequence"""

        # Organic fertilization
        organic_fert = ChemicalEvent.objects.create(
            history=history,
            created_by=user,
            name="Organic Compost Application",
            type="FE",
            date=history.start_date + timezone.timedelta(days=7),
            product_name="OMRI Certified Compost",
            amount="5000 kg",
            area=history.parcel.area,
            application_method="broadcast",
            target="Soil enrichment",
            extra_data={"organic_certified": True, "carbon_content": 0.30},
        )
        self.simulate_carbon_calculation_from_event(organic_fert)

        # Biological pest control
        if crop_type in ["strawberry", "lettuce"]:
            bio_control = PestManagementEvent.objects.create(
                history=history,
                created_by=user,
                name="Beneficial Insect Release",
                date=history.start_date + timezone.timedelta(days=30),
                pest_type="aphids",
                treatment_type="biological",
                product_used="Ladybugs and lacewings",
                area_treated=history.parcel.area,
                effectiveness="high",
                environmental_impact="positive",
                extra_data={"organic_certified": True},
            )
            self.simulate_carbon_calculation_from_event(bio_control)

        # Organic harvest
        harvest = ProductionEvent.objects.create(
            history=history,
            created_by=user,
            name="Organic Harvest",
            type="HA",
            date=history.finish_date - timezone.timedelta(days=7),
            amount=history.production_amount,
            unit="tons",
            quality_grade="Organic Premium",
            destination="Organic packing facility",
            extra_data={"certification": "USDA Organic"},
        )
        self.simulate_carbon_calculation_from_event(harvest)

        self.events_created += 3

    def simulate_carbon_calculation_from_event(self, event):
        """Simulate the real-world carbon calculation that would happen via signals"""
        try:
            # In production, this happens via Django signals
            # Here we'll manually trigger the calculation

            if hasattr(event, "__class__"):
                event_type = event.__class__.__name__

                # Map event types to calculator methods
                calculator_methods = {
                    "ChemicalEvent": "calculate_chemical_event_impact",
                    "ProductionEvent": "calculate_production_event_impact",
                    "EquipmentEvent": "calculate_equipment_event_impact",
                    "SoilManagementEvent": "calculate_soil_management_event_impact",
                    "PestManagementEvent": "calculate_pest_management_event_impact",
                    "WeatherEvent": "calculate_weather_event_impact",
                    "GeneralEvent": "calculate_general_event_impact",
                }

                method_name = calculator_methods.get(event_type)
                if method_name and hasattr(self.carbon_calculator, method_name):
                    calculation_method = getattr(self.carbon_calculator, method_name)
                    calculation_result = calculation_method(event)

                    if calculation_result and calculation_result.get("co2e", 0) != 0:
                        # Create carbon entry
                        carbon_entry = self.create_carbon_entry_from_calculation(event, calculation_result)
                        if carbon_entry:
                            self.carbon_entries_created += 1

                            # Update event's extra_data to track calculation
                            if not hasattr(event, "extra_data") or event.extra_data is None:
                                event.extra_data = {}
                            event.extra_data["carbon_calculation"] = {
                                "co2e": calculation_result["co2e"],
                                "carbon_entry_id": carbon_entry.id,
                                "calculation_date": timezone.now().isoformat(),
                            }
                            event.__class__.objects.filter(id=event.id).update(extra_data=event.extra_data)

        except Exception as e:
            self.stdout.write(f"      ⚠️  Carbon calculation failed for {event.__class__.__name__}: {e}")

    def create_carbon_entry_from_calculation(self, event, calculation_result):
        """Create carbon entry from calculation result"""
        try:
            # Get appropriate carbon source
            source = self.get_carbon_source_for_event(event, calculation_result)

            # Determine entry type
            co2e = calculation_result.get("co2e", 0)
            entry_type = "emission" if co2e > 0 else "offset"

            # Get establishment and production info
            establishment = event.history.parcel.establishment
            production = event.history
            year = event.date.year if hasattr(event, "date") else timezone.now().year

            # Create entry using raw SQL to handle all required fields
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO carbon_carbonentry (
                        year, type, amount, description, created_by_id, establishment_id, production_id, source_id,
                        timestamp, created_at, iot_device_id, updated_at, usda_verified, co2e_amount, data_source,
                        usda_factors_based, verification_status, additionality_evidence, additionality_verified,
                        audit_scheduled_date, baseline_data, documentation_complete, evidence_requirements_met,
                        methodology_template, permanence_plan, registry_verification_id, third_party_verification_url,
                        external_verification_id, gps_coordinates, verification_notes, baseline_scenario,
                        detected_patterns, financial_analysis, methodology_id, monitoring_plan, registry_name,
                        registry_submission_id, verification_report_url, audit_status, effective_amount,
                        evidence_documents, evidence_photos, trust_score, verification_level
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) RETURNING id
                """,
                    [
                        year,
                        entry_type,
                        abs(co2e),
                        f'Auto-calculated from {event.__class__.__name__}: {calculation_result.get("calculation_method", "standard")}',
                        event.created_by_id,
                        establishment.id,
                        production.id,
                        source.id,
                        event.date if hasattr(event, "date") else timezone.now(),
                        timezone.now(),
                        "",
                        timezone.now(),
                        calculation_result.get("usda_factors_based", True),
                        co2e,
                        calculation_result.get("data_source", "USDA Agricultural Research Service"),
                        calculation_result.get("usda_factors_based", True),
                        calculation_result.get("verification_status", "factors_verified"),
                        f"Calculated from verified {event.__class__.__name__} data",
                        True,
                        None,
                        json.dumps(calculation_result.get("breakdown", {})),
                        True,
                        True,
                        f"USDA_{event.__class__.__name__.upper()}",
                        "Event-based carbon tracking with USDA factors",
                        f"REG-{event.id}-{year}",
                        "",
                        f"EXT-{event.id}-{year}",
                        json.dumps({"establishment": establishment.name}),
                        f"Auto-calculated from farm event data",
                        json.dumps({"event_type": event.__class__.__name__}),
                        json.dumps(calculation_result.get("recommendations", [])),
                        json.dumps(calculation_result.get("cost_analysis", {})),
                        f"USDA_{source.category.upper()}",
                        json.dumps({"monitoring": "event_based", "frequency": "per_event"}),
                        "USDA Event Registry",
                        f"SUB-{event.id}",
                        "https://usda.gov/verify",
                        "passed",
                        abs(co2e) * calculation_result.get("confidence_score", 0.9),
                        json.dumps([]),
                        json.dumps([]),
                        calculation_result.get("confidence_score", 0.9),
                        "certified_project",
                    ],
                )

                entry_id = cursor.fetchone()[0]
                return CarbonEntry.objects.get(id=entry_id)

        except Exception as e:
            self.stdout.write(f"         ❌ Failed to create carbon entry: {e}")
            return None

    def get_carbon_source_for_event(self, event, calculation_result):
        """Get appropriate carbon source for the event type"""
        event_type = event.__class__.__name__

        # Map event types to carbon sources
        if event_type == "ChemicalEvent" and hasattr(event, "type"):
            if event.type == "FE":  # Fertilizer
                return CarbonSource.objects.get(name="Nitrogen Fertilizer")
            elif event.type == "PE":  # Pesticide
                return CarbonSource.objects.get(name="Packaging Materials")  # Placeholder

        elif event_type == "EquipmentEvent":
            return CarbonSource.objects.get(name="Tractor Operations")

        elif event_type == "ProductionEvent":
            if hasattr(event, "type") and event.type == "HA":  # Harvest
                return CarbonSource.objects.get(name="Harvesting Equipment")
            else:
                return CarbonSource.objects.get(name="Post-Harvest Processing")

        elif event_type == "SoilManagementEvent":
            if calculation_result.get("co2e", 0) < 0:  # Sequestration
                return CarbonSource.objects.get(name="Cover Crop Sequestration")
            else:
                return CarbonSource.objects.get(name="Tractor Operations")

        elif event_type == "GeneralEvent":
            return CarbonSource.objects.get(name="Product Transportation")

        # Default
        return CarbonSource.objects.get(name="Tractor Operations")

    def create_iot_infrastructure_with_carbon(self, establishment1, establishment2, user):
        """Create IoT devices and automated carbon entries"""
        self.stdout.write("📱 Creating IoT infrastructure with automated carbon tracking...")

        # Establishment 1 IoT devices
        devices_est1 = [
            ("FUEL-001", "fuel_sensor", "Main Tractor Fuel Monitor", establishment1),
            ("FUEL-002", "fuel_sensor", "Harvester Fuel Monitor", establishment1),
            ("ELEC-001", "equipment_monitor", "Packing House Energy Monitor", establishment1),
            ("IRRI-001", "irrigation", "Smart Irrigation Controller Block A", establishment1),
            ("SOIL-001", "soil_moisture", "Citrus Grove Moisture Network", establishment1),
        ]

        # Establishment 2 IoT devices
        devices_est2 = [
            ("FUEL-003", "fuel_sensor", "Organic Tractor Monitor", establishment2),
            ("ELEC-002", "equipment_monitor", "Cold Storage Energy Monitor", establishment2),
            ("IRRI-002", "irrigation", "Strawberry Field Controller", establishment2),
            ("WEATHER-001", "weather_station", "Microclimate Station", establishment2),
        ]

        all_devices = devices_est1 + devices_est2

        for device_id, device_type, name, establishment in all_devices:
            device, _ = IoTDevice.objects.get_or_create(
                device_id=device_id,
                defaults={
                    "device_type": device_type,
                    "establishment": establishment,
                    "name": name,
                    "manufacturer": "AgriTech Solutions",
                    "model": "AT-2024-Pro",
                    "status": "online",
                    "last_seen": timezone.now(),
                    "battery_level": random.randint(70, 100),
                    "signal_strength": "Strong",
                    "configuration": {"reporting_interval": "15min", "alerts_enabled": True, "carbon_tracking": True},
                },
            )

            # Create IoT data points with carbon implications
            if device_type == "fuel_sensor":
                self.create_fuel_sensor_data_with_carbon(device, user)
            elif device_type == "equipment_monitor":
                self.create_energy_monitor_data_with_carbon(device, user)

    def create_fuel_sensor_data_with_carbon(self, device, user):
        """Create fuel consumption data that triggers carbon entries"""
        # Create 30 days of fuel consumption data
        for day in range(30):
            timestamp = timezone.now() - timezone.timedelta(days=day)
            fuel_consumed = random.uniform(20, 80)  # liters per day

            data_point = IoTDataPoint.objects.create(
                device=device,
                timestamp=timestamp,
                data={
                    "fuel_consumption": fuel_consumed,
                    "fuel_type": "diesel",
                    "engine_hours": random.uniform(2, 8),
                    "efficiency": random.uniform(0.85, 0.95),
                },
                quality_score=random.uniform(0.90, 1.0),
            )

            # Create corresponding carbon entry
            if fuel_consumed > 0:
                diesel_source = CarbonSource.objects.get(name="Diesel Fuel")
                co2e = fuel_consumed * diesel_source.default_emission_factor

                self.create_iot_carbon_entry(device, data_point, fuel_consumed, co2e, user)

    def create_energy_monitor_data_with_carbon(self, device, user):
        """Create energy consumption data that triggers carbon entries"""
        # Create 30 days of energy data
        for day in range(30):
            timestamp = timezone.now() - timezone.timedelta(days=day)

            # Check if solar generation device (negative emissions)
            if "Cold Storage" in device.name:
                energy_consumed = random.uniform(500, 1500)  # kWh per day
                source = CarbonSource.objects.get(name="Grid Electricity")
                co2e = energy_consumed * source.default_emission_factor
            else:
                # Regular energy consumption
                energy_consumed = random.uniform(200, 800)
                source = CarbonSource.objects.get(name="Grid Electricity")
                co2e = energy_consumed * source.default_emission_factor

            data_point = IoTDataPoint.objects.create(
                device=device,
                timestamp=timestamp,
                data={
                    "energy_consumption_kwh": energy_consumed,
                    "power_source": "grid",
                    "peak_demand_kw": energy_consumed / 24 * 1.5,
                    "efficiency_rating": random.uniform(0.88, 0.95),
                },
                quality_score=random.uniform(0.92, 1.0),
            )

            self.create_iot_carbon_entry(device, data_point, energy_consumed, co2e, user)

    def create_iot_carbon_entry(self, device, data_point, amount, co2e, user):
        """Create carbon entry from IoT data"""
        try:
            # Determine source based on device type
            if device.device_type == "fuel_sensor":
                source = CarbonSource.objects.get(name="Diesel Fuel")
            else:
                source = CarbonSource.objects.get(name="Grid Electricity")

            year = data_point.timestamp.year

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO carbon_carbonentry (
                        year, type, amount, description, created_by_id, establishment_id, production_id, source_id,
                        timestamp, created_at, iot_device_id, updated_at, usda_verified, co2e_amount, data_source,
                        usda_factors_based, verification_status, additionality_evidence, additionality_verified,
                        audit_scheduled_date, baseline_data, documentation_complete, evidence_requirements_met,
                        methodology_template, permanence_plan, registry_verification_id, third_party_verification_url,
                        external_verification_id, gps_coordinates, verification_notes, baseline_scenario,
                        detected_patterns, financial_analysis, methodology_id, monitoring_plan, registry_name,
                        registry_submission_id, verification_report_url, audit_status, effective_amount,
                        evidence_documents, evidence_photos, trust_score, verification_level
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """,
                    [
                        year,
                        "emission",
                        amount,
                        f"IoT-monitored {source.name} from {device.name}",
                        user.id,
                        device.establishment_id,
                        None,
                        source.id,
                        data_point.timestamp,
                        timezone.now(),
                        device.device_id,
                        timezone.now(),
                        True,
                        co2e,
                        "IoT Real-time Monitoring",
                        True,
                        "iot_verified",
                        f"Automated monitoring from IoT device {device.device_id}",
                        True,
                        None,
                        json.dumps(data_point.data),
                        True,
                        True,
                        "IOT_AUTOMATED",
                        "Continuous IoT monitoring",
                        f"REG-IOT-{device.id}-{data_point.id}",
                        "",
                        f"EXT-IOT-{device.id}-{data_point.id}",
                        json.dumps({"device_location": device.establishment.name}),
                        f"Real-time IoT data from {device.name}",
                        json.dumps({"source": "iot_device", "device_type": device.device_type}),
                        json.dumps([]),
                        json.dumps({"data_quality": data_point.quality_score}),
                        "IOT_MONITORING",
                        json.dumps({"device": device.device_id, "frequency": "real_time"}),
                        "IoT Registry",
                        f"SUB-IOT-{data_point.id}",
                        "https://iot.trazo.io/verify",
                        "automated",
                        co2e * 0.95,
                        json.dumps([]),
                        json.dumps([]),
                        data_point.quality_score,
                        "automated_monitoring",
                    ],
                )

            self.carbon_entries_created += 1

        except Exception as e:
            self.stdout.write(f"      ⚠️  Failed to create IoT carbon entry: {e}")

    def create_carbon_offset_projects_and_purchases(self, establishments, user):
        """Create carbon offset projects and purchases with proper carbon entries"""
        self.stdout.write("💰 Creating carbon offset marketplace with purchases...")

        # Create offset projects
        projects_data = [
            {
                "name": "California Forest Carbon Project",
                "description": "Forest conservation and reforestation in Northern California",
                "project_type": "Forest Conservation",
                "certification_standard": "VCS (Verified Carbon Standard)",
                "location": "Northern California, USA",
                "price_per_ton": Decimal("25.50"),
                "available_capacity": Decimal("10000.00"),
            },
            {
                "name": "Agricultural Soil Carbon Initiative",
                "description": "Soil carbon sequestration through regenerative farming",
                "project_type": "Soil Sequestration",
                "certification_standard": "Climate Action Reserve",
                "location": "Central Valley, California",
                "price_per_ton": Decimal("18.75"),
                "available_capacity": Decimal("5000.00"),
            },
            {
                "name": "Renewable Energy Biomass Project",
                "description": "Agricultural waste to renewable energy conversion",
                "project_type": "Renewable Energy",
                "certification_standard": "Gold Standard",
                "location": "California",
                "price_per_ton": Decimal("32.00"),
                "available_capacity": Decimal("7500.00"),
            },
        ]

        projects = []
        for project_data in projects_data:
            project, _ = CarbonOffsetProject.objects.get_or_create(name=project_data["name"], defaults=project_data)
            projects.append(project)

        # Create purchases for each establishment
        offset_source = CarbonSource.objects.get(name="Purchased Carbon Offsets")

        for establishment in establishments:
            # Purchase from 2 projects per establishment
            for project in projects[:2]:
                amount = Decimal(str(random.uniform(25, 75)))

                purchase = CarbonOffsetPurchase.objects.create(
                    project=project,
                    user=user,
                    amount=amount,
                    price_per_ton=project.price_per_ton,
                    total_price=amount * project.price_per_ton,
                    status="completed",
                    is_verified=True,
                )

                # Create corresponding carbon entry (offset)
                self.create_offset_carbon_entry(establishment, user, offset_source, amount, project, purchase)

    def create_offset_carbon_entry(self, establishment, user, source, amount, project, purchase):
        """Create carbon entry for offset purchase"""
        try:
            year = timezone.now().year
            co2e = -float(amount)  # Negative for offsets

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO carbon_carbonentry (
                        year, type, amount, description, created_by_id, establishment_id, production_id, source_id,
                        timestamp, created_at, iot_device_id, updated_at, usda_verified, co2e_amount, data_source,
                        usda_factors_based, verification_status, additionality_evidence, additionality_verified,
                        audit_scheduled_date, baseline_data, documentation_complete, evidence_requirements_met,
                        methodology_template, permanence_plan, registry_verification_id, third_party_verification_url,
                        external_verification_id, gps_coordinates, verification_notes, baseline_scenario,
                        detected_patterns, financial_analysis, methodology_id, monitoring_plan, registry_name,
                        registry_submission_id, verification_report_url, audit_status, effective_amount,
                        evidence_documents, evidence_photos, trust_score, verification_level
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """,
                    [
                        year,
                        "offset",
                        float(amount),
                        f"Carbon offset purchase: {project.name} - {amount} tons CO2e",
                        user.id,
                        establishment.id,
                        None,
                        source.id,
                        timezone.now(),
                        timezone.now(),
                        "",
                        timezone.now(),
                        False,
                        co2e,
                        "Carbon Offset Registry",
                        False,
                        "third_party_verified",
                        f"{project.certification_standard} verified project",
                        True,
                        None,
                        json.dumps(
                            {
                                "project": project.name,
                                "amount": float(amount),
                                "purchase_id": purchase.id,
                                "certificate_id": str(purchase.certificate_id),
                            }
                        ),
                        True,
                        True,
                        project.certification_standard.split()[0],
                        f"{project.project_type} permanence guarantee",
                        f"REG-OFFSET-{establishment.id}-{purchase.id}",
                        "https://registry.verra.org",
                        f"EXT-{purchase.certificate_id}",
                        json.dumps({"project_location": project.location}),
                        f"Third-party verified carbon offset purchase",
                        json.dumps({"type": "offset", "project_type": project.project_type}),
                        json.dumps([]),
                        json.dumps({"total_cost": float(purchase.total_price)}),
                        f"{project.certification_standard}_STANDARD",
                        json.dumps({"monitoring": "third_party", "frequency": "annual"}),
                        project.certification_standard,
                        f"SUB-{purchase.certificate_id}",
                        "https://registry.verra.org/report",
                        "third_party_verified",
                        abs(co2e),
                        json.dumps([]),
                        json.dumps([]),
                        0.98,
                        "certified_project",
                    ],
                )

            self.carbon_entries_created += 1

        except Exception as e:
            self.stdout.write(f"      ⚠️  Failed to create offset carbon entry: {e}")

    def create_certifications_and_badges(self, productions):
        """Create certifications and sustainability badges"""
        self.stdout.write("🏆 Creating certifications and sustainability badges...")

        # Create certifications
        for production in productions:
            if production.type == "organic":
                cert, _ = CarbonCertification.objects.get_or_create(
                    production=production,
                    certifier="USDA Organic",
                    defaults={
                        "certificate_id": f"USDA-ORG-{production.id}-2024",
                        "issue_date": timezone.now().date() - timezone.timedelta(days=180),
                        "expiry_date": timezone.now().date() + timezone.timedelta(days=185),
                        "is_usda_soe_verified": True,
                        "verification_date": timezone.now().date() - timezone.timedelta(days=180),
                        "verification_details": "Annual organic inspection passed with no issues",
                    },
                )

        # Create sustainability badges
        badges_data = [
            ("Carbon Neutral Progress", "Working towards carbon neutrality", 50),
            ("Water Conservation Leader", "Reduced water usage by 40%", 60),
            ("Renewable Energy User", "Solar powered operations", 70),
            ("Soil Health Champion", "Regenerative farming practices", 80),
        ]

        for name, description, min_score in badges_data:
            badge, _ = SustainabilityBadge.objects.get_or_create(
                name=name,
                defaults={
                    "description": description,
                    "minimum_score": min_score,
                    "is_automatic": True,
                    "criteria": {"carbon_score_min": min_score},
                },
            )

            # Award badges to qualifying productions
            for production in productions:
                if production.parcel.establishment.id == 1:  # Premium operation gets more badges
                    badge.productions.add(production)

    def create_recent_activity(self, productions, user):
        """Create recent scans and reviews"""
        self.stdout.write("👁️ Creating recent consumer activity...")

        # Create scans
        for production in productions[:10]:  # First 10 productions get scans
            for i in range(random.randint(5, 15)):
                days_ago = random.randint(1, 30)
                scan = HistoryScan.objects.create(
                    history=production,
                    user=None,  # Anonymous scans
                    ip_address=f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}",
                    city=["Los Angeles", "San Francisco", "San Diego", "Sacramento"][random.randint(0, 3)],
                    country="United States",
                    created_at=timezone.now() - timezone.timedelta(days=days_ago),
                )

        # Create reviews
        review_texts = [
            "Amazing quality! The carbon transparency really makes a difference.",
            "Best organic produce I've ever had. Love knowing the environmental impact.",
            "Incredible freshness and the QR code showed me the whole journey!",
            "Supporting sustainable farming has never been easier. Great job!",
            "The blockchain verification gives me confidence in my purchase.",
        ]

        for production in productions[:8]:  # First 8 productions get reviews
            for i in range(random.randint(1, 3)):
                review = Review.objects.create(
                    production=production,
                    user=user,
                    rating=random.randint(4, 5),
                    comment=random.choice(review_texts),
                    verified_purchase=True,
                    helpful_count=random.randint(5, 50),
                )

    def publish_finished_productions(self, productions):
        """Publish all finished productions for QR code access"""
        self.stdout.write("📢 Publishing finished productions...")

        published_count = 0
        for production in productions:
            # Generate QR code filename
            qr_filename = f"{production.product.name.replace(' ', '_')}_{production.name.replace(' ', '_')}-{production.start_date.strftime('%Y-%m-%d_%H%M%S.%f')}.png"
            production.qr_code = f"qr_codes/{qr_filename}"

            # Publish if it has events and carbon entries
            if production.events.exists():
                production.published = True
                production.save()
                published_count += 1

        self.stdout.write(f"   ✅ Published {published_count} productions")

    def verify_and_summarize(self, company, user, productions):
        """Final verification and summary"""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("🎉 COMPREHENSIVE DEMO DATA CREATION COMPLETE!"))
        self.stdout.write("=" * 60)

        # Summary statistics
        self.stdout.write("\n📊 SUMMARY STATISTICS:")
        self.stdout.write(f"   Company: {company.name}")
        self.stdout.write(f"   Demo User: {user.email} (password: TrazoDemo2025!)")
        self.stdout.write(f"   Establishments: {Establishment.objects.filter(company=company).count()}")
        self.stdout.write(f"   Parcels: {Parcel.objects.filter(establishment__company=company).count()}")
        self.stdout.write(f"   Productions: {len(productions)}")
        self.stdout.write(f"   Events Created: {self.events_created}")
        self.stdout.write(f"   Carbon Entries: {self.carbon_entries_created}")

        # Carbon breakdown
        self.stdout.write("\n🌍 CARBON FOOTPRINT ANALYSIS:")
        establishments = Establishment.objects.filter(company=company)
        for est in establishments:
            total_emissions = (
                CarbonEntry.objects.filter(establishment=est, type="emission").aggregate(
                    total=models.Sum("co2e_amount")
                )["total"]
                or 0
            )

            total_offsets = (
                CarbonEntry.objects.filter(establishment=est, type__in=["offset", "sequestration"]).aggregate(
                    total=models.Sum("co2e_amount")
                )["total"]
                or 0
            )

            net = total_emissions + total_offsets  # offsets are negative

            self.stdout.write(f"\n   {est.name}:")
            self.stdout.write(f"      Emissions: {total_emissions:,.2f} kg CO2e")
            self.stdout.write(f"      Offsets: {abs(total_offsets):,.2f} kg CO2e")
            self.stdout.write(f"      Net: {net:,.2f} kg CO2e")

        # Data completeness check
        self.stdout.write("\n✅ DATA COMPLETENESS CHECK:")
        checks = [
            ("Productions have events", all(p.events.exists() for p in productions)),
            ("Carbon entries created", CarbonEntry.objects.exists()),
            ("Multiple carbon entry types", CarbonEntry.objects.values("type").distinct().count() > 1),
            ("Diverse carbon sources", CarbonSource.objects.filter(carbonentry__isnull=False).count() > 5),
            ("IoT devices active", IoTDevice.objects.filter(status="online").exists()),
            ("Offset purchases made", CarbonOffsetPurchase.objects.exists()),
            ("Reviews created", Review.objects.exists()),
            ("Scans recorded", HistoryScan.objects.exists()),
            ("Productions published", History.objects.filter(published=True).exists()),
        ]

        all_passed = True
        for check_name, passed in checks:
            status = "✅" if passed else "❌"
            if not passed:
                all_passed = False
            self.stdout.write(f"   {status} {check_name}")

        if all_passed:
            self.stdout.write(self.style.SUCCESS("\n🎯 All checks passed! Demo data is production-ready."))

        # API endpoints
        self.stdout.write("\n🔗 KEY API ENDPOINTS:")
        self.stdout.write("   Public History (QR): /api/histories/{id}/public_history/")
        self.stdout.write("   Carbon Entries: /api/carbon/entries/?establishment={id}&year={year}")
        self.stdout.write("   Productions: /api/histories/")

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Demo environment ready for showcasing Trazo's capabilities!")
        self.stdout.write("=" * 60 + "\n")
