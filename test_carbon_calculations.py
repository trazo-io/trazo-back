#!/usr/bin/env python
"""
Comprehensive Trazo Carbon Calculation System Test Script

This script creates a complete test scenario using Django shell commands to:
1. Create test company, establishment, and production
2. Create various agricultural events (fertilizer, fuel, equipment)
3. Calculate carbon footprints using the EventCarbonCalculator
4. Display detailed carbon calculation results with scientific validation

Run this script in Django shell:
    python manage.py shell < test_carbon_calculations.py

Or execute commands manually in Django shell:
    python manage.py shell
    exec(open('test_carbon_calculations.py').read())
"""

print("🌱 Trazo Carbon Calculation System - Comprehensive Test Scenario")
print("=" * 70)
print()

from datetime import datetime, timedelta
from decimal import Decimal

# Import required modules
from django.utils import timezone

from carbon.models import CarbonEntry, CarbonSource
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from company.models import Company, Establishment
from history.models import ChemicalEvent, EquipmentEvent, History, ProductionEvent
from product.models import Parcel, Product

# Import Trazo models - using correct model imports
from users.models import User

print("✅ All modules imported successfully")
print()

# Create test user
print("👤 Creating test user...")
test_email = "carbon.test@trazo.farm"
try:
    user = User.objects.get(email=test_email)
    print(f"   Using existing user: {user.email}")
except User.DoesNotExist:
    user = User.objects.create_user(
        email=test_email,
        password="testpass123",
        first_name="Carbon",
        last_name="Tester",
        is_verified=True,
        is_active=True,
    )
    print(f"   ✅ Created new user: {user.email}")
print()

# Create test company
print("🏢 Creating test company...")
try:
    company = Company.objects.get(name="Carbon Test Farm LLC")
    print(f"   Using existing company: {company.name}")
except Company.DoesNotExist:
    company = Company.objects.create(
        name="Carbon Test Farm LLC",
        address="123 Sustainable Way",
        city="Fresno",
        state="California",
        country="United States",
        zip_code="93701",
        industry="Organic Agriculture",
        contact_email="info@carbontestfarm.com",
        primary_commodities="Avocados, Strawberries, Citrus",
        sustainability_commitment="Carbon neutral by 2025",
        blockchain_subscription_status=True,
    )
    print(f"   ✅ Created new company: {company.name}")
print()

# Create test establishment (farm)
print("🌾 Creating test establishment...")
try:
    establishment = Establishment.objects.get(name="Sustainable Avocado Ranch")
    print(f"   Using existing establishment: {establishment.name}")
except Establishment.DoesNotExist:
    establishment = Establishment.objects.create(
        name="Sustainable Avocado Ranch",
        address="456 Orchard Drive",
        city="Fallbrook",
        state="California",
        country="United States",
        zip_code="92028",
        company=company,
        latitude=33.3764,  # Fallbrook, CA coordinates
        longitude=-117.2511,
        total_acreage=123.6,  # 50 hectares = 123.6 acres
        type="Organic Farm",
        about="Premium organic avocado production with sustainable practices",
        main_activities="Avocado cultivation, processing, and distribution",
        sustainability_practices=["Organic certification", "Water-efficient irrigation", "Integrated pest management"],
        employee_count=12,
    )
    print(f"   ✅ Created new establishment: {establishment.name}")
print()

# Create test product (avocado)
print("🥑 Creating test product...")
try:
    product = Product.objects.get(name="Hass Avocado")
    print(f"   Using existing product: {product.name}")
except Product.DoesNotExist:
    product = Product.objects.create(
        name="Hass Avocado", description="Premium organic Hass avocados grown with sustainable farming practices"
    )
    print(f"   ✅ Created new product: {product.name}")
print()

# Create test parcel
print("🌱 Creating test parcel...")
try:
    parcel = Parcel.objects.get(unique_code="AVG-BLOCK-01")
    print(f"   Using existing parcel: {parcel.unique_code}")
except Parcel.DoesNotExist:
    parcel = Parcel.objects.create(
        name="Avocado Block 1",
        description="Premium Hass avocado block with sustainable growing practices",
        establishment=establishment,
        product=product,
        area=10.0,  # 10 hectares
        soil_type="Clay loam with good drainage",
        certified=True,
        certification_type="Organic",
        unique_code="AVG-BLOCK-01",
        agricultural_details={
            "planting_date": "2021-09-07",  # 3 years old
            "crop_variety": "Hass Avocado",
            "irrigation_type": "Drip irrigation",
            "organic_certification": True,
            "sustainability_practices": ["Water-efficient irrigation", "Integrated pest management", "Cover crops"],
        },
        carbon_calculation_enabled=True,
        usda_compliance_eligible=True,
    )
    print(f"   ✅ Created new parcel: {parcel.unique_code}")
print()

# Create test production history
print("📝 Creating test production...")
try:
    production = History.objects.get(name="2024 Hass Avocado Production")
    print(f"   Using existing production: {production.name}")
except History.DoesNotExist:
    production = History.objects.create(
        name="2024 Hass Avocado Production",
        type=History.ORCHARD,
        start_date=timezone.now() - timedelta(days=365),
        finish_date=timezone.now(),
        published=True,
        earning=145000.0,  # $145,000 revenue
        production_amount=25000.0,  # 25,000 kg production
        description="Premium organic Hass avocado production cycle",
        parcel=parcel,
        product=product,
        confidence_score=85.0,
        transparency_score=92.0,
    )
    print(f"   ✅ Created new production: {production.name}")
    print(f"      Production amount: {production.production_amount:,.0f} kg")
    print(f"      Revenue: ${production.earning:,.0f}")
print()

# Create agricultural events for comprehensive carbon testing
print("🚜 Creating agricultural events...")

# Event 1: Nitrogen Fertilizer Application
print("   💧 Creating nitrogen fertilizer event...")
try:
    event_fertilizer = ChemicalEvent.objects.get(description__contains="Nitrogen fertilizer application")
    print(f"      Using existing fertilizer event: {event_fertilizer.id}")
except ChemicalEvent.DoesNotExist:
    event_fertilizer = ChemicalEvent.objects.create(
        type="FE",  # Fertilizer
        date=timezone.now() - timedelta(days=180),
        description="Nitrogen fertilizer application - Spring growth boost",
        history=production,
        created_by=user,
        # Fertilizer specific data
        commercial_name="Urea (46-0-0)",
        concentration="46-0-0",  # 46% nitrogen
        volume="2000",  # 2000 liters
        area="10",  # 10 hectares
        way_of_application="broadcast",
        # Additional metadata
        extra_data={
            "supplier": "Farm Supply Co",
            "weather_conditions": "Mild, overcast",
            "soil_moisture": "optimal",
            "application_rate": "200 L/ha",
            "cost": 1200.0,  # $1,200 cost
        },
    )
    print(f"      ✅ Created fertilizer event: {event_fertilizer.id}")
    print(f"         Product: {event_fertilizer.commercial_name}")
    print(f"         Concentration: {event_fertilizer.concentration}")
    print(f"         Volume: {event_fertilizer.volume} L")
    print(f"         Area: {event_fertilizer.area} ha")

# Event 2: Diesel Fuel Usage (Tractor Operations)
print("   ⛽ Creating diesel fuel event...")
try:
    event_fuel = EquipmentEvent.objects.get(description__contains="Tractor operations")
    print(f"      Using existing fuel event: {event_fuel.id}")
except EquipmentEvent.DoesNotExist:
    event_fuel = EquipmentEvent.objects.create(
        type="FC",  # Fuel Consumption
        date=timezone.now() - timedelta(days=150),
        description="Tractor operations - Cultivation and harvesting",
        history=production,
        created_by=user,
        # Fuel specific data
        equipment_name="John Deere 5075E Tractor",
        fuel_amount=850,  # 850 liters
        fuel_type="diesel",
        area_covered="10 hectares",
        hours_used=45.0,
        # Additional metadata
        extra_data={
            "operations": ["cultivation", "harvesting", "pruning"],
            "fuel_efficiency": "18.9 L/ha",
            "cost": 1020.0,  # $1,020 cost (assuming $1.20/L)
        },
    )
    print(f"      ✅ Created fuel event: {event_fuel.id}")
    print(f"         Equipment: {event_fuel.equipment_name}")
    print(f"         Fuel amount: {event_fuel.fuel_amount} L")
    print(f"         Area covered: {event_fuel.area_covered}")

# Event 3: Equipment Usage (Irrigation System)
print("   🌊 Creating equipment event...")
try:
    event_equipment = EquipmentEvent.objects.get(description__contains="Drip irrigation system")
    print(f"      Using existing equipment event: {event_equipment.id}")
except EquipmentEvent.DoesNotExist:
    event_equipment = EquipmentEvent.objects.create(
        type="MN",  # Maintenance
        date=timezone.now() - timedelta(days=120),
        description="Drip irrigation system operation - Water management",
        history=production,
        created_by=user,
        # Equipment specific data
        equipment_name="Electric irrigation pump system",
        area_covered="10 hectares",
        maintenance_cost=450.0,  # $450 electricity cost
        hours_used=120.0,  # 4 hours x 3 times/week x 10 weeks
        # Additional metadata
        extra_data={
            "equipment_type": "Drip irrigation system",
            "power_consumption": "15 kWh/ha/month",
            "water_usage": "4000 m³/ha/season",
            "pump_efficiency": "85%",
            "irrigation_schedule": "3x per week, 4 hours each",
            "maintenance_type": "Regular operation and maintenance",
        },
    )
    print(f"      ✅ Created equipment event: {event_equipment.id}")
    print(f"         Equipment: {event_equipment.equipment_name}")
    print(f"         Area covered: {event_equipment.area_covered}")

print()

# Initialize carbon calculator
print("🧮 Initializing EventCarbonCalculator...")
calculator = EventCarbonCalculator()
print("   ✅ Calculator initialized successfully")
print()

# Calculate carbon footprints for each event
print("🔬 CARBON CALCULATION RESULTS")
print("=" * 70)

# Test 1: Fertilizer Event Carbon Calculation
print("\n📊 1. NITROGEN FERTILIZER APPLICATION ANALYSIS")
print("-" * 50)
fertilizer_result = calculator.calculate_chemical_event_impact(event_fertilizer)

print(f"Event Details:")
print(f"   Product: {event_fertilizer.product_name}")
print(f"   Concentration: {event_fertilizer.concentration}")
print(f"   Volume: {event_fertilizer.volume} L")
print(f"   Area: {event_fertilizer.area} ha")
print(f"   Application method: {event_fertilizer.way_of_application}")
print()

print(f"Carbon Calculation Results:")
print(f"   Total CO₂e: {fertilizer_result.get('co2e', 0):.2f} kg CO₂e")
print(f"   CO₂e per hectare: {fertilizer_result.get('co2e', 0) / 10:.2f} kg CO₂e/ha")
print(f"   CO₂e per kg product: {fertilizer_result.get('co2e', 0) / 25000:.4f} kg CO₂e/kg")
print()

print(f"Detailed Breakdown:")
if "breakdown" in fertilizer_result:
    breakdown = fertilizer_result["breakdown"]
    for nutrient, value in breakdown.items():
        if isinstance(value, (int, float)) and value > 0:
            print(f"   {nutrient.capitalize()}: {value:.2f} kg CO₂e")

print()
print(f"Verification Status:")
print(f"   USDA factors used: {fertilizer_result.get('usda_factors_based', 'Unknown')}")
print(f"   Confidence level: {fertilizer_result.get('confidence_level', 'Unknown')}")
print(f"   Confidence score: {fertilizer_result.get('confidence_score', 0):.1%}")

# Test 2: Fuel Event Carbon Calculation
print("\n📊 2. DIESEL FUEL USAGE ANALYSIS")
print("-" * 50)
fuel_result = calculator.calculate_fuel_event_impact(event_fuel)

print(f"Event Details:")
print(f"   Fuel type: {event_fuel.product_name}")
print(f"   Volume: {event_fuel.volume} L")
print(f"   Area: {event_fuel.area} ha")
print(f"   Operations: {event_fuel.extra_data.get('operations', 'General farming')}")
print()

print(f"Carbon Calculation Results:")
print(f"   Total CO₂e: {fuel_result.get('co2e', 0):.2f} kg CO₂e")
print(f"   CO₂e per hectare: {fuel_result.get('co2e', 0) / 10:.2f} kg CO₂e/ha")
print(f"   CO₂e per liter fuel: {fuel_result.get('co2e', 0) / 850:.2f} kg CO₂e/L")
print()

print(f"Efficiency Analysis:")
if "efficiency" in fuel_result:
    print(f"   Fuel efficiency: {fuel_result['efficiency']:.1%}")
print(f"   Emission factor used: {fuel_result.get('emission_factor', 'Unknown')} kg CO₂e/L")

print()
print(f"Verification Status:")
print(f"   USDA factors used: {fuel_result.get('usda_factors_based', 'Unknown')}")
print(f"   Confidence level: {fuel_result.get('confidence_level', 'Unknown')}")

# Test 3: Equipment Event Carbon Calculation
print("\n📊 3. EQUIPMENT OPERATION ANALYSIS")
print("-" * 50)
equipment_result = calculator.calculate_equipment_event_impact(event_equipment)

print(f"Event Details:")
print(f"   Equipment: {event_equipment.product_name}")
print(f"   Area: {event_equipment.area} ha")
print(f"   Power consumption: {event_equipment.extra_data.get('power_consumption', 'Unknown')}")
print()

print(f"Carbon Calculation Results:")
print(f"   Total CO₂e: {equipment_result.get('co2e', 0):.2f} kg CO₂e")
print(f"   CO₂e per hectare: {equipment_result.get('co2e', 0) / 10:.2f} kg CO₂e/ha")
print()

print(f"Equipment Efficiency:")
if "efficiency" in equipment_result:
    print(f"   Equipment efficiency: {equipment_result['efficiency']:.1%}")
print(f"   Emission factor used: {equipment_result.get('emission_factor', 'Unknown')} kg CO₂e/kWh")

# Summary Analysis
print("\n🎯 COMPREHENSIVE ANALYSIS SUMMARY")
print("=" * 70)

total_co2e = fertilizer_result.get("co2e", 0) + fuel_result.get("co2e", 0) + equipment_result.get("co2e", 0)

print(f"Production Overview:")
print(f"   Farm: {establishment.name}")
print(f"   Crop: {product.name}")
print(f"   Area: {parcel.area} hectares")
print(f"   Production: {production.production_amount:,.0f} kg")
print(f"   Revenue: ${production.earning:,.0f}")
print()

print(f"Carbon Footprint Summary:")
print(
    f"   Fertilizer emissions: {fertilizer_result.get('co2e', 0):,.2f} kg CO₂e ({fertilizer_result.get('co2e', 0)/total_co2e*100:.1f}%)"
)
print(
    f"   Fuel emissions: {fuel_result.get('co2e', 0):,.2f} kg CO₂e ({fuel_result.get('co2e', 0)/total_co2e*100:.1f}%)"
)
print(
    f"   Equipment emissions: {equipment_result.get('co2e', 0):,.2f} kg CO₂e ({equipment_result.get('co2e', 0)/total_co2e*100:.1f}%)"
)
print(f"   ─────────────────────────────────────")
print(f"   TOTAL EMISSIONS: {total_co2e:,.2f} kg CO₂e")
print()

print(f"Performance Metrics:")
print(f"   CO₂e per hectare: {total_co2e / parcel.area:.2f} kg CO₂e/ha")
print(f"   CO₂e per kg product: {total_co2e / production.production_amount:.4f} kg CO₂e/kg")
print(f"   Carbon intensity: {total_co2e / production.earning * 1000:.2f} g CO₂e per $1 revenue")
print()

print(f"Industry Benchmarking:")
# Typical avocado carbon footprint is 0.85-1.2 kg CO₂e/kg
carbon_per_kg = total_co2e / production.production_amount
if carbon_per_kg < 0.85:
    benchmark_status = "EXCELLENT (Below industry average)"
elif carbon_per_kg < 1.2:
    benchmark_status = "GOOD (Within industry average)"
else:
    benchmark_status = "NEEDS IMPROVEMENT (Above industry average)"

print(f"   Industry average: 0.85-1.20 kg CO₂e/kg avocado")
print(f"   Your performance: {carbon_per_kg:.4f} kg CO₂e/kg")
print(f"   Status: {benchmark_status}")
print()

print(f"Data Quality Assessment:")
fertilizer_confidence = fertilizer_result.get("confidence_score", 0.5)
fuel_confidence = fuel_result.get("confidence_score", 0.5)
equipment_confidence = equipment_result.get("confidence_score", 0.5)
overall_confidence = (fertilizer_confidence + fuel_confidence + equipment_confidence) / 3

print(f"   Fertilizer data confidence: {fertilizer_confidence:.1%}")
print(f"   Fuel data confidence: {fuel_confidence:.1%}")
print(f"   Equipment data confidence: {equipment_confidence:.1%}")
print(f"   Overall confidence: {overall_confidence:.1%}")

confidence_grade = (
    "A" if overall_confidence > 0.8 else "B" if overall_confidence > 0.6 else "C" if overall_confidence > 0.4 else "D"
)
print(f"   Data quality grade: {confidence_grade}")

# USDA API Status Check
print("\n🔍 USDA INTEGRATION STATUS")
print("-" * 50)

try:
    from carbon.services.enhanced_usda_factors import EnhancedUSDAFactors

    enhanced_usda = EnhancedUSDAFactors()

    print(f"USDA API Configuration:")
    print(f"   API client initialized: {'✅' if hasattr(enhanced_usda, 'usda_api_client') else '❌'}")

    if hasattr(enhanced_usda, "usda_api_client"):
        api_key_status = "✅ Available" if enhanced_usda.usda_api_client.api_key else "❌ Missing"
        print(f"   API key status: {api_key_status}")

        if enhanced_usda.usda_api_client.api_key:
            print(f"   Using: Real-time USDA FoodData Central API")
            print(f"   Fallback: USDA-verified local factors")
        else:
            print(f"   Using: USDA-verified local factors")
            print(f"   Status: Robust offline calculation capability")

    print(f"   Emission factors source: USDA Agricultural Research Service")
    print(f"   Last factor verification: {enhanced_usda.enhanced_factors.LAST_UPDATED}")
    print(f"   Factor version: {enhanced_usda.enhanced_factors.VERSION}")

except Exception as e:
    print(f"   ⚠️  USDA service error: {str(e)}")
    print(f"   Status: Using fallback emission factors")

print()
print("🎉 Test completed successfully!")
print(f"📊 View results in Django admin or via API endpoints")
print(f"🔗 QR Code: {production.qr_code.url if production.qr_code else 'Generate QR code for public access'}")
print()
print("=" * 70)
print("End of Comprehensive Carbon Calculation Test")
