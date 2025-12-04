#!/usr/bin/env python3
"""
CRITICAL VALIDATION: Test carbon calculation with form values to identify 99.9% underestimation issue
"""

import os
import sys

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors


def validate_fertilizer_calculation():
    """Validate the exact calculation using our form values"""

    print("=== CRITICAL VALIDATION: Chemical Event Carbon Calculation ===")
    print("Form Values from Browser Test:")
    print("- Chemical Type: FE (Fertilizer)")
    print("- Commercial Name: Miracle-Gro All Purpose Plant Food")
    print("- NPK Content: 24-8-16")
    print("- Volume: 500 Liters")
    print("- Area: 2.5 acres → 1.01 hectares")
    print("- Application Method: Broadcast")
    print()

    # Test values from our form
    chemical_type = "FE"
    volume_liters = 500.0
    area_hectares = 2.5 * 0.404686  # Convert acres to hectares = ~1.01 ha
    npk_content = {"N": 24, "P": 8, "K": 16}  # From NPK 24-8-16
    application_method = "broadcast"

    print(f"Converted area: {area_hectares:.3f} hectares")
    print()

    # Call the verified emission factors service
    result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type=chemical_type,
        volume_liters=volume_liters,
        area_hectares=area_hectares,
        npk_content=npk_content,
        application_method=application_method,
    )

    print("=== CALCULATION RESULTS ===")
    print(f"Total CO2e: {result['co2e_kg']:.3f} kg")
    print(f"Calculation Method: {result['calculation_method']}")
    print()

    breakdown = result["breakdown"]
    print("=== DETAILED BREAKDOWN ===")
    print(f"Fertilizer Mass: {breakdown['fertilizer_mass_kg']:.1f} kg")
    print(f"Nitrogen Content: {breakdown['nitrogen_kg']:.1f} kg N")
    print(f"Phosphorus Content: {breakdown['phosphorus_kg']:.1f} kg P")
    print(f"Potassium Content: {breakdown['potassium_kg']:.1f} kg K")
    print()
    print(f"Manufacturing Emissions: {breakdown['manufacturing_emissions_kg_co2e']:.3f} kg CO2e")
    print(f"Application Fuel: {breakdown['application_fuel_gallons']:.3f} gallons")
    print(f"Application Emissions: {breakdown['application_emissions_kg_co2e']:.3f} kg CO2e")
    print()
    print(f"EPA Nitrogen Factor: {breakdown['epa_nitrogen_factor_kg_co2_per_kg_n']:.2f} kg CO2e/kg N")
    print(f"EPA Phosphorus Factor: {breakdown['epa_phosphorus_factor_kg_co2_per_kg_p']:.2f} kg CO2e/kg P")
    print(f"EPA Potassium Factor: {breakdown['epa_potassium_factor_kg_co2_per_kg_k']:.2f} kg CO2e/kg K")
    print(f"EPA Diesel Factor: {breakdown['epa_diesel_factor_kg_co2_per_gallon']:.2f} kg CO2e/gallon")
    print()

    # Compare with frontend result (2.2 kg CO2e)
    frontend_result = 2.2
    backend_result = result["co2e_kg"]

    print("=== COMPARISON WITH FRONTEND ===")
    print(f"Frontend Result: {frontend_result:.1f} kg CO2e")
    print(f"Backend Result: {backend_result:.1f} kg CO2e")

    if backend_result > frontend_result:
        ratio = backend_result / frontend_result
        underestimation = ((backend_result - frontend_result) / backend_result) * 100
        print(f"Backend is {ratio:.1f}x higher than frontend")
        print(f"Frontend underestimates by {underestimation:.1f}%")
    else:
        ratio = frontend_result / backend_result
        overestimation = ((frontend_result - backend_result) / frontend_result) * 100
        print(f"Frontend is {ratio:.1f}x higher than backend")
        print(f"Frontend overestimates by {overestimation:.1f}%")

    print()
    print("=== EXPECTED vs ACTUAL ===")
    expected_by_agents = 1738  # From agent validation
    print(f"Agent Expected: {expected_by_agents:.0f} kg CO2e")
    print(f"Actual Result: {backend_result:.1f} kg CO2e")

    if expected_by_agents > backend_result:
        ratio = expected_by_agents / backend_result
        underestimation = ((expected_by_agents - backend_result) / expected_by_agents) * 100
        print(f"Current calculation underestimates by {underestimation:.1f}%")
        print(f"Should be {ratio:.1f}x higher")

    print()
    print("=== CONCLUSION ===")
    if backend_result < 100:
        print("🚨 CRITICAL ISSUE CONFIRMED: Calculation severely underestimated")
        print("   Manufacturing emissions appear to be missing or incorrectly scaled")
        print("   Need to investigate EPA factor application and density conversion")
    else:
        print("✅ Calculation appears reasonable for commercial fertilizer application")

    return result


if __name__ == "__main__":
    validate_fertilizer_calculation()
