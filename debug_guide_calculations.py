#!/usr/bin/env python3
"""
Debug script to understand why guide numbers differ from current calculations
"""

import os
import sys
from decimal import Decimal

import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors


def debug_california_avocado():
    """Debug the California Avocado case in detail"""
    print("🔍 DEBUG: California Avocado Farm Case")
    print("=" * 50)

    npk_content = {"N": 15, "P": 5, "K": 10}
    volume_applied = 520  # L
    area_treated = 2.1  # ha
    application_method = "broadcast"
    expected_carbon = 309  # kg CO2e from guide

    result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type="FE",
        volume_liters=volume_applied,
        area_hectares=area_treated,
        npk_content=npk_content,
        application_method=application_method,
    )

    print(f"INPUT:")
    print(f"  NPK: {npk_content}")
    print(f"  Volume: {volume_applied} L")
    print(f"  Area: {area_treated} ha")
    print(f"  Method: {application_method}")

    print(f"\nRESULT BREAKDOWN:")
    for key, value in result.items():
        print(f"  {key}: {value}")

    # Get density manually to verify
    density = VerifiedEmissionFactors._get_fertilizer_density(npk_content, application_method)
    total_fertilizer_kg = volume_applied * density

    print(f"\nMANUAL CALCULATIONS:")
    print(f"  Density used: {density} kg/L")
    print(f"  Total fertilizer: {volume_applied} L × {density} kg/L = {total_fertilizer_kg} kg")
    print(f"  N content: {total_fertilizer_kg} kg × 15% = {total_fertilizer_kg * 0.15} kg N")
    print(f"  P content: {total_fertilizer_kg} kg × 5% = {total_fertilizer_kg * 0.05} kg P")
    print(f"  K content: {total_fertilizer_kg} kg × 10% = {total_fertilizer_kg * 0.10} kg K")

    # Get EPA factors
    n_factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["nitrogen_fertilizer"].value
    p_factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["phosphorus_fertilizer"].value
    k_factor = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS["potassium_fertilizer"].value

    print(f"\nEPA EMISSION FACTORS:")
    print(f"  Nitrogen: {n_factor} kg CO2e per kg N")
    print(f"  Phosphorus: {p_factor} kg CO2e per kg P")
    print(f"  Potassium: {k_factor} kg CO2e per kg K")

    n_emissions = total_fertilizer_kg * 0.15 * n_factor
    p_emissions = total_fertilizer_kg * 0.05 * p_factor
    k_emissions = total_fertilizer_kg * 0.10 * k_factor
    manufacturing_total = n_emissions + p_emissions + k_emissions

    print(f"\nMANUFACTURING EMISSIONS:")
    print(f"  N emissions: {total_fertilizer_kg * 0.15:.2f} kg N × {n_factor} = {n_emissions:.2f} kg CO2e")
    print(f"  P emissions: {total_fertilizer_kg * 0.05:.2f} kg P × {p_factor} = {p_emissions:.2f} kg CO2e")
    print(f"  K emissions: {total_fertilizer_kg * 0.10:.2f} kg K × {k_factor} = {k_emissions:.2f} kg CO2e")
    print(f"  Manufacturing total: {manufacturing_total:.2f} kg CO2e")

    print(f"\nEXPECTED vs CALCULATED:")
    print(f"  Guide expected: {expected_carbon} kg CO2e")
    print(f"  Current system: {result['co2e_kg']:.2f} kg CO2e")
    print(f"  Difference: {abs(result['co2e_kg'] - expected_carbon):.2f} kg CO2e")

    # Reverse engineer what density would give expected result
    # If manufacturing is the main component, work backwards
    if "breakdown" in result:
        print(f"\nBREAKDOWN ANALYSIS:")
        for key, value in result["breakdown"].items():
            print(f"  {key}: {value}")


def debug_iowa_corn():
    """Debug the Iowa Corn case - this one matched well"""
    print("\n🔍 DEBUG: Iowa Corn Farm Case (Good Match)")
    print("=" * 50)

    npk_content = {"N": 82, "P": 0, "K": 0}
    volume_kg = 3320  # kg
    volume_applied = volume_kg / 0.68  # Convert using anhydrous ammonia density
    area_treated = 40.5  # ha
    application_method = "injection"
    expected_carbon = 28755.5  # kg CO2e from guide

    result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type="FE",
        volume_liters=volume_applied,
        area_hectares=area_treated,
        npk_content=npk_content,
        application_method=application_method,
    )

    print(f"INPUT:")
    print(f"  NPK: {npk_content}")
    print(f"  Volume: {volume_kg} kg = {volume_applied:.1f} L")
    print(f"  Area: {area_treated} ha")
    print(f"  Method: {application_method}")

    print(f"\nRESULT:")
    print(f"  Guide expected: {expected_carbon} kg CO2e")
    print(f"  Current system: {result['co2e_kg']:.2f} kg CO2e")
    print(
        f"  Difference: {abs(result['co2e_kg'] - expected_carbon):.2f} kg CO2e ({abs(result['co2e_kg'] - expected_carbon)/expected_carbon*100:.1f}%)"
    )

    print(f"\nWHY THIS WORKS WELL:")
    print(f"  - High N content (82%) dominates emissions")
    print(f"  - Anhydrous ammonia density (0.68 kg/L) correctly applied")
    print(f"  - Manufacturing emissions are main component")


def analyze_emission_factors():
    """Analyze the current EPA emission factors"""
    print("\n📊 EPA EMISSION FACTORS ANALYSIS")
    print("=" * 50)

    factors = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS

    for name, factor in factors.items():
        print(f"{name}:")
        print(f"  Value: {factor.value} {factor.unit}")
        print(f"  Source: {factor.source}")
        print(f"  Confidence: {factor.confidence_level}")
        print(f"  Updated: {factor.last_updated}")
        if factor.notes:
            print(f"  Notes: {factor.notes}")
        print()


def main():
    debug_california_avocado()
    debug_iowa_corn()
    analyze_emission_factors()


if __name__ == "__main__":
    main()
