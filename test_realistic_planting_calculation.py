#!/usr/bin/env python3
"""
TEST REALISTIC PLANTING CALCULATION
Test the exact planting event from the UI to validate carbon calculation

Values from screenshot:
- Production Type: Planting/Seeding - Crop establishment
- Area Covered: 10.00 Hectares
- Fuel Consumed: 35.0 Liters
- Equipment Operating Hours: 6.5 hours
- Quantity Planted: 65000.0 Seeds

Expected CO₂e: 94 kg (from Carbon Impact Preview)
"""

import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor


def test_exact_planting_event():
    """Test the exact planting event from the UI screenshot"""

    print("🌽 TESTING EXACT PLANTING EVENT FROM UI")
    print("=" * 70)
    print("Values from screenshot:")
    print("- Production Type: Planting/Seeding - Crop establishment")
    print("- Area Covered: 10.00 Hectares")
    print("- Fuel Consumed: 35.0 Liters")
    print("- Equipment Operating Hours: 6.5 hours")
    print("- Quantity Planted: 65000.0 Seeds")
    print("- Expected CO₂e: 94 kg (from Carbon Impact Preview)")
    print()

    calculator = OptimizedCarbonCalculator()

    # Exact data from the form
    planting_data = {
        "type": "PL",  # Planting type code
        "area_covered": "10.00",
        "area_unit": "hectares",
        "equipment_hours": "6.5",
        "fuel_consumed": "35.0",
        "fuel_unit": "liters",
        "yield_quantity": "65000.0",  # Seeds planted
        "yield_unit": "seeds",
        "product_name": "Sweet Corn",
    }

    try:
        print("🔧 STEP 1: Process event data with unit conversions")
        processed_event = OptimizedEventProcessor._process_production_event(planting_data)

        print(f"   📊 Processed Data:")
        print(f"      Production Type: {processed_event.get('production_type')}")
        print(f"      Area: {processed_event.get('area_covered')} acres")
        print(f"      Fuel: {processed_event.get('fuel_consumed')} gallons")
        print(f"      Equipment Hours: {processed_event.get('equipment_hours')}")
        print(f"      Unit conversions: {processed_event.get('unit_conversions_applied', False)}")

        # Show conversion audit trail
        if "conversion_audit" in processed_event:
            print(f"   📋 Unit Conversion Audit:")
            for audit in processed_event["conversion_audit"]:
                print(f"      - {audit}")

        print()

        print("🔧 STEP 2: Calculate carbon impact using USDA methods")
        result = calculator.calculate_production_impact_optimized(processed_event)

        co2e_calculated = result["co2e"]
        expected_co2e = 94.0  # From UI preview

        print(f"   ✅ Calculated CO₂e: {co2e_calculated} kg")
        print(f"   🎯 Expected CO₂e: {expected_co2e} kg")
        print(f"   📊 Calculation Method: {result['calculation_method']}")
        print(f"   ✅ USDA Verified: {result['usda_factors_used']}")

        # Calculate accuracy
        difference = abs(co2e_calculated - expected_co2e)
        percentage_diff = (difference / expected_co2e) * 100

        print()
        print("🔍 ACCURACY ANALYSIS:")
        print(f"   Difference: {difference:.2f} kg CO₂e")
        print(f"   Percentage difference: {percentage_diff:.1f}%")

        # Determine if it's acceptable
        if percentage_diff <= 5.0:  # Within 5%
            print(f"   ✅ EXCELLENT: Within 5% tolerance")
            print(f"   ✅ UI preview accurately reflects USDA calculations")
        elif percentage_diff <= 10.0:  # Within 10%
            print(f"   ✅ GOOD: Within 10% tolerance")
            print(f"   ✅ UI preview is reasonably accurate")
        elif percentage_diff <= 20.0:  # Within 20%
            print(f"   ⚠️ ACCEPTABLE: Within 20% tolerance")
            print(f"   ⚠️ Minor discrepancy between UI preview and calculation")
        else:
            print(f"   ❌ SIGNIFICANT DISCREPANCY: >20% difference")
            print(f"   ❌ UI preview may not be using same calculation method")

        print()

        print("🔬 PLANTING EVENT BREAKDOWN:")
        print(f"   Area Impact: {processed_event.get('area_covered', 0)} acres × planting factor")
        print(f"   Fuel Impact: {processed_event.get('fuel_consumed', 0)} gallons × EPA emission factor")
        print(f"   Equipment Impact: {processed_event.get('equipment_hours', 0)} hours operational emissions")

        # Detailed fuel analysis
        fuel_gallons = processed_event.get("fuel_consumed", 0)
        if fuel_gallons and fuel_gallons > 0:
            # Standard EPA emission factor for diesel: ~10.15 kg CO₂e/gallon
            fuel_emissions_estimate = fuel_gallons * 10.15
            print(
                f"   Fuel CO₂e estimate: {fuel_gallons:.2f} gallons × 10.15 kg/gal ≈ {fuel_emissions_estimate:.1f} kg"
            )

        print()

        if percentage_diff <= 10:
            print("🎉 VALIDATION SUCCESSFUL!")
            print("✅ UI Carbon Impact Preview aligns with USDA calculations")
            print("✅ Unit conversions working correctly")
            print("✅ Planting event carbon calculation is accurate")
        else:
            print("⚠️ VALIDATION NEEDS REVIEW")
            print("🔧 UI preview calculation may need adjustment")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_exact_planting_event()
