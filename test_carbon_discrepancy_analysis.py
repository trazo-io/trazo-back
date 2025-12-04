#!/usr/bin/env python3
"""
Carbon Calculation Discrepancy Analysis
Iowa Corn Farm Fertilizer Event Test

Current Issue: Form shows 5,604 kg CO2e but audit guide expects 28,755.5 kg CO2e
This test analyzes the calculation discrepancy and identifies the root cause.
"""

import os
import sys
from decimal import Decimal

import django

# Setup Django
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.emission_factors import emission_factors
from carbon.services.verified_emission_factors import VerifiedEmissionFactors


def test_iowa_corn_farm_calculation():
    """Test the actual fertilizer calculation vs expected audit values"""

    print("🧮 IOWA CORN FARM FERTILIZER DISCREPANCY ANALYSIS")
    print("=" * 60)

    # Event details from screenshot
    event_data = {
        "commercial_name": "Anhydrous Ammonia 82-0-0",
        "npk_ratio": "82-0-0",
        "volume_kg": 3320,  # Volume Applied: 3320 kg
        "area_hectares": 16.2,  # Area Treated: 16.2 ha
        "application_method": "injection",  # Soil injection - Liquid fertilizer
    }

    print(f"📋 Event Details:")
    print(f"   Commercial Name: {event_data['commercial_name']}")
    print(f"   NPK Ratio: {event_data['npk_ratio']}")
    print(f"   Volume Applied: {event_data['volume_kg']} kg")
    print(f"   Area Treated: {event_data['area_hectares']} ha")
    print(f"   Application Method: {event_data['application_method']}")
    print()

    # Calculate nitrogen content
    n_percentage = 82 / 100.0  # 82% nitrogen
    total_nitrogen_kg = event_data["volume_kg"] * n_percentage

    print(f"🧪 Nitrogen Analysis:")
    print(f"   N Content: {n_percentage * 100}%")
    print(f"   Total Nitrogen: {total_nitrogen_kg} kg N")
    print()

    # Expected values from audit guide
    expected_breakdown = {
        "total_co2e": 28755.5,
        "direct_n2o_emissions": 28649.0,  # 2,722kg N × 10.5 kg CO2e/kg N
        "manufacturing_emissions": 81.8,
        "application_fuel": 24.7,
    }

    print(f"📊 Expected Values (Audit Guide):")
    print(f"   Total CO2e: {expected_breakdown['total_co2e']} kg")
    print(f"   Direct N2O emissions: {expected_breakdown['direct_n2o_emissions']} kg CO2e")
    print(f"   Manufacturing emissions: {expected_breakdown['manufacturing_emissions']} kg CO2e")
    print(f"   Application fuel: {expected_breakdown['application_fuel']} kg CO2e")
    print()

    # Check what factors are being used
    print("🔍 Current Emission Factors Analysis:")

    # Get verified factors (what's currently used)
    verified_n_factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["nitrogen_fertilizer"]
    print(f"   Verified N Factor: {verified_n_factor.value} kg CO2e/kg N")
    print(f"   Source: {verified_n_factor.source}")
    print(f"   Notes: {verified_n_factor.notes}")
    print()

    # Get centralized factors (what should be used)
    centralized_n_factor = emission_factors.get_fertilizer_factor("nitrogen")
    print(f"   Centralized N Factor: {centralized_n_factor['value']} kg CO2e/kg N")
    print(f"   Source: {centralized_n_factor['source']}")
    print(f"   Production Component: {centralized_n_factor.get('production_component', 'N/A')} kg CO2e/kg N")
    print(f"   Field Component (N2O): {centralized_n_factor.get('field_component', 'N/A')} kg CO2e/kg N")
    print()

    # Current calculation (what the form shows)
    print("⚙️ Current Calculation (Form Result):")

    # Assume volume_liters - need to convert kg to liters using density
    # Anhydrous ammonia density ≈ 0.682 kg/L
    ammonia_density = 0.682
    volume_liters = event_data["volume_kg"] / ammonia_density

    npk_content = {"N": 82, "P": 0, "K": 0}

    current_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type="FE",  # Fertilizer
        volume_liters=volume_liters,
        area_hectares=event_data["area_hectares"],
        npk_content=npk_content,
        application_method=event_data["application_method"],
    )

    print(f"   Current Total CO2e: {current_result['co2e_kg']} kg")
    print(f"   Manufacturing: {current_result['breakdown']['manufacturing_emissions_kg_co2e']} kg CO2e")
    print(f"   Application Fuel: {current_result['breakdown']['application_emissions_kg_co2e']} kg CO2e")
    print()

    # Expected calculation (what it should be)
    print("✅ Expected Calculation (Correct Method):")

    # Using the full 10.5 kg CO2e/kg N factor
    correct_n_factor = 10.5  # From centralized emission factors
    correct_manufacturing = total_nitrogen_kg * 2.6  # Production component only
    correct_n2o_emissions = total_nitrogen_kg * 7.9  # Field N2O component
    correct_total_n = total_nitrogen_kg * correct_n_factor  # All nitrogen emissions

    # Application fuel (estimate)
    fuel_per_ha = 3.0  # L diesel/ha for injection method
    total_fuel_liters = event_data["area_hectares"] * fuel_per_ha
    total_fuel_gallons = total_fuel_liters / 3.78541
    fuel_factor = 10.21  # kg CO2/gallon
    correct_application_fuel = total_fuel_gallons * fuel_factor

    correct_total = correct_total_n + correct_application_fuel

    print(
        f"   Nitrogen (Total): {correct_total_n:.1f} kg CO2e ({total_nitrogen_kg} kg N × {correct_n_factor} kg CO2e/kg N)"
    )
    print(f"     - Manufacturing: {correct_manufacturing:.1f} kg CO2e ({total_nitrogen_kg} kg N × 2.6)")
    print(f"     - Direct N2O: {correct_n2o_emissions:.1f} kg CO2e ({total_nitrogen_kg} kg N × 7.9)")
    print(f"   Application Fuel: {correct_application_fuel:.1f} kg CO2e")
    print(f"   Total CO2e: {correct_total:.1f} kg")
    print()

    # Analysis
    print("🔍 DISCREPANCY ANALYSIS:")
    print("=" * 40)

    discrepancy = expected_breakdown["total_co2e"] - current_result["co2e_kg"]
    percentage_diff = (discrepancy / expected_breakdown["total_co2e"]) * 100

    print(f"❌ Current Form Result: {current_result['co2e_kg']} kg CO2e")
    print(f"✅ Expected (Audit): {expected_breakdown['total_co2e']} kg CO2e")
    print(f"📉 Discrepancy: {discrepancy:.1f} kg CO2e ({percentage_diff:.1f}% difference)")
    print()

    print("🔎 ROOT CAUSE ANALYSIS:")
    print(f"   1. MISSING N2O EMISSIONS: The current calculation only includes manufacturing")
    print(f"      emissions ({verified_n_factor.value} kg CO2e/kg N) but misses direct N2O emissions")
    print(f"      from soil application (7.9 kg CO2e/kg N).")
    print()
    print(f"   2. FACTOR MISMATCH: ")
    print(f"      - Current: {verified_n_factor.value} kg CO2e/kg N (manufacturing only)")
    print(f"      - Should be: {correct_n_factor} kg CO2e/kg N (total emissions)")
    print(f"      - Missing: {correct_n_factor - verified_n_factor.value} kg CO2e/kg N (N2O emissions)")
    print()
    print(f"   3. CALCULATION IMPACT:")
    print(f"      - Missing N2O: {total_nitrogen_kg} kg N × 7.9 = {correct_n2o_emissions:.1f} kg CO2e")
    print(
        f"      - This accounts for {(correct_n2o_emissions/expected_breakdown['total_co2e'])*100:.1f}% of total emissions"
    )
    print()

    # Verification
    print("✅ VERIFICATION:")
    expected_n_factor = expected_breakdown["direct_n2o_emissions"] / total_nitrogen_kg
    print(
        f"   Expected N factor: {expected_breakdown['direct_n2o_emissions']} ÷ {total_nitrogen_kg} = {expected_n_factor:.1f} kg CO2e/kg N"
    )
    print(f"   Matches centralized factor: {abs(expected_n_factor - correct_n_factor) < 0.1}")
    print()

    return {
        "current_result": current_result["co2e_kg"],
        "expected_result": expected_breakdown["total_co2e"],
        "discrepancy": discrepancy,
        "percentage_diff": percentage_diff,
        "root_cause": "Missing direct N2O emissions (7.9 kg CO2e/kg N)",
        "fix_needed": f"Use full 10.5 kg CO2e/kg N factor instead of 2.98 kg CO2e/kg N",
    }


if __name__ == "__main__":
    result = test_iowa_corn_farm_calculation()

    print("🎯 SUMMARY:")
    print("=" * 40)
    print(f"✅ Analysis complete!")
    print(f"📋 Root cause identified: {result['root_cause']}")
    print(f"🔧 Fix needed: {result['fix_needed']}")
    print(f"📊 Impact: {result['percentage_diff']:.1f}% underestimation of emissions")
