#!/usr/bin/env python3
"""
COMPREHENSIVE PRODUCTION EVENTS TESTING
Test ALL production sub-events in the Trazo agricultural carbon transparency system
"""

import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor


def test_all_production_events():
    """Test all production event types with carbon calculation"""

    print("🌾 COMPREHENSIVE PRODUCTION EVENTS TESTING")
    print("=" * 80)
    print("Testing ALL production sub-events in Trazo system")
    print()

    calculator = OptimizedCarbonCalculator()

    # Define all production event types found in the system
    production_events = [
        # CORE PRODUCTION EVENTS (Primary lifecycle)
        {
            "name": "B1. PLANTING (PL)",
            "description": "Initial crop planting",
            "data": {
                "type": "PL",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "6",
                "fuel_consumed": None,
                "seed_variety": "Valencia Orange",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "B2. IRRIGATION (IR)",
            "description": "Water management",
            "data": {
                "type": "IR",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "4",
                "fuel_consumed": None,
                "water_volume": "500",
                "water_unit": "gallons",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "B3. HARVESTING (HA)",
            "description": "Crop harvesting",
            "data": {
                "type": "HA",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "8",
                "fuel_consumed": None,
                "yield_quantity": "12.5",
                "yield_unit": "tons",
                "transportation_distance": "2.5",
                "transportation_unit": "km",
            },
        },
        {
            "name": "B4. PRUNING (PR)",
            "description": "Tree/crop maintenance",
            "data": {
                "type": "PR",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "5",
                "fuel_consumed": None,
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "B5. TRANSPLANTING (TR)",
            "description": "Seedling transplanting",
            "data": {
                "type": "TR",
                "area_covered": "2.0",
                "area_unit": "ha",
                "equipment_hours": "3",
                "fuel_consumed": None,
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        # CHEMICAL EVENTS (Fertilizers & Pesticides)
        {
            "name": "C1. FERTILIZER APPLICATION (FE)",
            "description": "Nutrient application",
            "data": {
                "type": "FE",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "2",
                "fuel_consumed": None,
                "chemical_type": "FE",
                "product_name": "Urea 46-0-0",
                "application_rate": "150",
                "rate_unit": "lbs/acre",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "C2. PESTICIDE APPLICATION (PE)",
            "description": "Pest control",
            "data": {
                "type": "PE",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "2",
                "fuel_consumed": None,
                "chemical_type": "PE",
                "product_name": "Organic Neem Oil",
                "application_rate": "2",
                "rate_unit": "gallons/acre",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        # EQUIPMENT EVENTS (Machinery operations)
        {
            "name": "E1. FUEL CONSUMPTION (FC)",
            "description": "Machinery fuel usage",
            "data": {
                "type": "FC",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "8",
                "fuel_consumed": "45",
                "fuel_unit": "gallons",
                "equipment_type": "Tractor",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "E2. CALIBRATION (CA)",
            "description": "Equipment calibration",
            "data": {
                "type": "CA",
                "area_covered": "0",
                "area_unit": "ha",
                "equipment_hours": "1",
                "fuel_consumed": None,
                "equipment_type": "Sprayer",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "E3. MAINTENANCE (MN)",
            "description": "Equipment maintenance",
            "data": {
                "type": "MN",
                "area_covered": "0",
                "area_unit": "ha",
                "equipment_hours": "2",
                "fuel_consumed": None,
                "equipment_type": "Harvester",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        # WEATHER EVENTS (Environmental responses)
        {
            "name": "W1. FROST PROTECTION (FR)",
            "description": "Frost protection measures",
            "data": {
                "type": "FR",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "6",
                "fuel_consumed": None,
                "temperature": "28",
                "temperature_unit": "F",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "W2. HIGH TEMPERATURE (HT)",
            "description": "Heat stress mitigation",
            "data": {
                "type": "HT",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "3",
                "fuel_consumed": None,
                "temperature": "105",
                "temperature_unit": "F",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "W3. DROUGHT RESPONSE (DR)",
            "description": "Drought management",
            "data": {
                "type": "DR",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "8",
                "fuel_consumed": None,
                "water_volume": "1000",
                "water_unit": "gallons",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "W4. HAILSTORM RECOVERY (HL)",
            "description": "Hail damage recovery",
            "data": {
                "type": "HL",
                "area_covered": "2.0",
                "area_unit": "ha",
                "equipment_hours": "4",
                "fuel_consumed": None,
                "damage_percentage": "25",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        # SOIL MANAGEMENT EVENTS (Soil health)
        {
            "name": "S1. COVER CROP (CO)",
            "description": "Cover crop management",
            "data": {
                "type": "CO",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "3",
                "fuel_consumed": None,
                "cover_crop_type": "Crimson Clover",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "S2. TILLAGE (TI)",
            "description": "Soil preparation",
            "data": {
                "type": "TI",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "4",
                "fuel_consumed": None,
                "tillage_depth": "8",
                "tillage_unit": "inches",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "S3. ORGANIC MATTER (OM)",
            "description": "Organic matter addition",
            "data": {
                "type": "OM",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "2",
                "fuel_consumed": None,
                "organic_type": "Compost",
                "application_rate": "2",
                "rate_unit": "tons/acre",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "S4. SOIL TEST (ST)",
            "description": "Soil analysis",
            "data": {
                "type": "ST",
                "area_covered": "1.0",
                "area_unit": "ha",
                "equipment_hours": "1",
                "fuel_consumed": None,
                "soil_ph": "6.5",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        # PEST MANAGEMENT EVENTS (IPM)
        {
            "name": "P1. SCOUTING (SC)",
            "description": "Pest monitoring",
            "data": {
                "type": "SC",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "2",
                "fuel_consumed": None,
                "pest_pressure_level": "Low",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "P2. IPM IMPLEMENTATION (IP)",
            "description": "Integrated pest management",
            "data": {
                "type": "IP",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "3",
                "fuel_consumed": None,
                "ipm_strategy": "Beneficial insects",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "P3. BENEFICIAL RELEASE (BR)",
            "description": "Beneficial organism release",
            "data": {
                "type": "BR",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "1",
                "fuel_consumed": None,
                "beneficial_type": "Ladybugs",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        {
            "name": "P4. TRAP MONITORING (TM)",
            "description": "Pest trap monitoring",
            "data": {
                "type": "TM",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "1",
                "fuel_consumed": None,
                "trap_type": "Pheromone traps",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
        # HARVEST & STORAGE EVENTS
        {
            "name": "H1. HARVEST STORAGE (HS)",
            "description": "Post-harvest storage",
            "data": {
                "type": "HS",
                "area_covered": "0",
                "area_unit": "ha",
                "equipment_hours": "2",
                "fuel_consumed": None,
                "storage_type": "Cold storage",
                "yield_quantity": "12.5",
                "yield_unit": "tons",
            },
        },
        {
            "name": "H2. CERTIFICATION (CE)",
            "description": "Certification process",
            "data": {
                "type": "CE",
                "area_covered": "5.8",
                "area_unit": "ha",
                "equipment_hours": "1",
                "fuel_consumed": None,
                "certification_type": "Organic",
                "yield_quantity": "0",
                "yield_unit": "tons",
            },
        },
    ]

    # Test each event type
    results = []
    total_events = len(production_events)
    successful_events = 0

    for i, event in enumerate(production_events, 1):
        print(f"🔧 TEST {i}/{total_events}: {event['name']}")
        print(f"   Description: {event['description']}")

        try:
            # Process event data
            processed_event = OptimizedEventProcessor._process_production_event(event["data"])
            print(f"   ✅ Data processed: {processed_event['production_type']}")

            # Calculate carbon impact
            result = calculator.calculate_production_impact_optimized(processed_event)

            co2e_value = result["co2e"]
            print(f"   ✅ CO₂e Result: {co2e_value} kg")
            print(f"   ✅ Calculation Method: {result['calculation_method']}")
            print(f"   ✅ USDA Verified: {result['usda_factors_used']}")

            # Validate result is reasonable (not negative, not extremely high)
            if co2e_value < 0:
                print(f"   ⚠️ WARNING: Negative CO₂e value")
            elif co2e_value > 1000:
                print(f"   ⚠️ WARNING: Very high CO₂e value (>1000 kg)")
            else:
                print(f"   ✅ PASS: Realistic CO₂e range")

            results.append(
                {
                    "event": event["name"],
                    "co2e": co2e_value,
                    "status": "SUCCESS",
                    "method": result["calculation_method"],
                    "usda_factors_used": result["usda_factors_used"],
                }
            )
            successful_events += 1

        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            results.append({"event": event["name"], "co2e": None, "status": "FAILED", "error": str(e)})

        print()

    # Summary report
    print("📊 COMPREHENSIVE TEST RESULTS SUMMARY")
    print("=" * 80)
    print(f"Total Events Tested: {total_events}")
    print(f"Successful Calculations: {successful_events}")
    print(f"Failed Calculations: {total_events - successful_events}")
    print(f"Success Rate: {(successful_events/total_events)*100:.1f}%")
    print()

    # Category breakdown
    categories = {
        "Core Production": ["PL", "IR", "HA", "PR", "TR"],
        "Chemical Events": ["FE", "PE"],
        "Equipment Events": ["FC", "CA", "MN"],
        "Weather Events": ["FR", "HT", "DR", "HL"],
        "Soil Management": ["CO", "TI", "OM", "ST"],
        "Pest Management": ["SC", "IP", "BR", "TM"],
        "Harvest & Storage": ["HS", "CE"],
    }

    print("📋 CATEGORY BREAKDOWN:")
    for category, event_types in categories.items():
        category_results = [r for r in results if any(et in r["event"] for et in event_types)]
        category_success = len([r for r in category_results if r["status"] == "SUCCESS"])
        print(f"   {category}: {category_success}/{len(category_results)} successful")

    print()

    # CO2e Range Analysis
    successful_results = [r for r in results if r["status"] == "SUCCESS"]
    if successful_results:
        co2e_values = [r["co2e"] for r in successful_results]
        print("📈 CO₂e EMISSION ANALYSIS:")
        print(f"   Minimum: {min(co2e_values):.2f} kg CO₂e")
        print(f"   Maximum: {max(co2e_values):.2f} kg CO₂e")
        print(f"   Average: {sum(co2e_values)/len(co2e_values):.2f} kg CO₂e")
        print(f"   Range: {max(co2e_values) - min(co2e_values):.2f} kg CO₂e")

    print()

    # EPA/USDA Factors Analysis
    epa_factors_used = len([r for r in successful_results if r.get("usda_factors_used")])
    print("EPA/USDA FACTORS ANALYSIS:")
    print(f"   EPA/USDA Factors Used: {epa_factors_used}/{successful_events} events")
    print(f"   Factors Usage Rate: {(epa_factors_used/successful_events)*100:.1f}%")

    print()
    print("=" * 80)
    if successful_events == total_events:
        print("🎉 ALL PRODUCTION EVENTS SUCCESSFULLY TESTED!")
        print("✅ Carbon calculation system handles complete agricultural lifecycle")
    else:
        print(f"⚠️ {total_events - successful_events} events failed - investigation needed")

    return results


if __name__ == "__main__":
    results = test_all_production_events()
