#!/usr/bin/env python
"""
Debug realistic chemical application volumes vs test parameters
"""

import os
import sys
from decimal import Decimal

import django

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors


def debug_realistic_volumes():
    """Debug realistic chemical application volumes"""

    print("🔍 DEBUGGING REALISTIC APPLICATION VOLUMES")
    print("=" * 60)
    print()

    # Current test volume
    test_volume_gallons = 50
    test_volume_liters = 189.3

    print(f"🧪 CURRENT TEST PARAMETERS")
    print(f"Volume: {test_volume_gallons} gallons ({test_volume_liters:.1f} L) per acre")
    print()

    # Realistic application volumes for different chemicals
    print("📊 REALISTIC APPLICATION VOLUMES (per acre)")
    print("-" * 50)

    realistic_volumes = {
        "pesticide": {
            "gallons_per_acre": [5, 10, 15, 20],  # Typical pesticide applications
            "description": "Pesticides (insecticides) - typically low volume, high concentration",
        },
        "herbicide": {
            "gallons_per_acre": [10, 15, 20, 25],  # Typical herbicide applications
            "description": "Herbicides - moderate volume applications",
        },
        "fungicide": {
            "gallons_per_acre": [3, 5, 8, 12],  # Typical fungicide applications
            "description": "Fungicides - often very low volume, preventive applications",
        },
        "fertilizer": {
            "gallons_per_acre": [20, 30, 40, 50],  # Liquid fertilizer applications
            "description": "Liquid fertilizers - higher volumes for nutrient delivery",
        },
    }

    for chemical_type, data in realistic_volumes.items():
        print(f"\n🌱 {chemical_type.upper()}")
        print(f"   {data['description']}")

        for volume_gal in data["gallons_per_acre"]:
            volume_liters = volume_gal * 3.78541  # Convert to liters
            print(f"   • {volume_gal} gal/acre ({volume_liters:.1f} L/acre)")

    print(f"\n❗ ANALYSIS")
    print(f"Current test volume: {test_volume_gallons} gal/acre")
    print(f"This is:")
    print(f"  • 2.5-10x higher than typical pesticide applications (5-20 gal/acre)")
    print(f"  • 2-5x higher than typical herbicide applications (10-25 gal/acre)")
    print(f"  • 4-16x higher than typical fungicide applications (3-12 gal/acre)")
    print(f"  • Appropriate for liquid fertilizer applications (20-50 gal/acre)")
    print()

    # Test with realistic pesticide volume
    print("🧪 TESTING WITH REALISTIC PESTICIDE VOLUME")
    print("-" * 50)

    realistic_pesticide_volume = 10  # gallons per acre
    realistic_pesticide_liters = realistic_pesticide_volume * 3.78541

    result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type="pesticide",
        volume_liters=realistic_pesticide_liters,  # 37.9 L instead of 189.3 L
        area_hectares=0.404686,  # 1 acre
        npk_content={"N": 0, "P": 0, "K": 0},
        application_method="spray",
    )

    print(f"📊 Realistic pesticide application:")
    print(f"   Volume: {realistic_pesticide_volume} gal/acre ({realistic_pesticide_liters:.1f} L/acre)")
    print(f"   ⚡ Trazo Calculation: {result['co2e_kg']:.1f} kg CO2e")
    print(f"   📈 Research Benchmark: 180-220 kg CO2e")

    if 180 <= result["co2e_kg"] <= 220:
        print(f"   ✅ WITHIN RANGE!")
    else:
        deviation = abs(result["co2e_kg"] - 200) / 200 * 100
        print(f"   ❌ Deviation: {deviation:.1f}%")

    print()

    # Test with realistic herbicide volume
    print("🧪 TESTING WITH REALISTIC HERBICIDE VOLUME")
    print("-" * 50)

    realistic_herbicide_volume = 15  # gallons per acre
    realistic_herbicide_liters = realistic_herbicide_volume * 3.78541

    result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type="herbicide",
        volume_liters=realistic_herbicide_liters,  # 56.8 L instead of 189.3 L
        area_hectares=0.404686,  # 1 acre
        npk_content={"N": 0, "P": 0, "K": 0},
        application_method="spray",
    )

    print(f"📊 Realistic herbicide application:")
    print(f"   Volume: {realistic_herbicide_volume} gal/acre ({realistic_herbicide_liters:.1f} L/acre)")
    print(f"   ⚡ Trazo Calculation: {result['co2e_kg']:.1f} kg CO2e")
    print(f"   📈 Research Benchmark: 155-195 kg CO2e")

    if 155 <= result["co2e_kg"] <= 195:
        print(f"   ✅ WITHIN RANGE!")
    else:
        deviation = abs(result["co2e_kg"] - 175) / 175 * 100
        print(f"   ❌ Deviation: {deviation:.1f}%")

    print()

    # Test with realistic fungicide volume
    print("🧪 TESTING WITH REALISTIC FUNGICIDE VOLUME")
    print("-" * 50)

    realistic_fungicide_volume = 5  # gallons per acre
    realistic_fungicide_liters = realistic_fungicide_volume * 3.78541

    result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type="fungicide",
        volume_liters=realistic_fungicide_liters,  # 18.9 L instead of 189.3 L
        area_hectares=0.404686,  # 1 acre
        npk_content={"N": 0, "P": 0, "K": 0},
        application_method="spray",
    )

    print(f"📊 Realistic fungicide application:")
    print(f"   Volume: {realistic_fungicide_volume} gal/acre ({realistic_fungicide_liters:.1f} L/acre)")
    print(f"   ⚡ Trazo Calculation: {result['co2e_kg']:.1f} kg CO2e")
    print(f"   📈 Research Benchmark: 95-125 kg CO2e")

    if 95 <= result["co2e_kg"] <= 125:
        print(f"   ✅ WITHIN RANGE!")
    else:
        deviation = abs(result["co2e_kg"] - 110) / 110 * 100
        print(f"   ❌ Deviation: {deviation:.1f}%")

    print()
    print("💡 CONCLUSION")
    print("-" * 50)
    print("The 50 gallon/acre test volume was unrealistic for pesticides/herbicides/fungicides.")
    print("Using realistic application volumes should bring calculations within benchmark ranges.")


if __name__ == "__main__":
    debug_realistic_volumes()
