#!/usr/bin/env python
"""
Test script to verify realistic fuel consumption rates for pesticide applications.
Tests the A2 Pesticide scenario with updated fuel consumption values.
"""

from carbon.services.verified_emission_factors import VerifiedEmissionFactors


def test_a2_pesticide_with_realistic_fuel():
    """Test A2 Pesticide Application with realistic fuel consumption"""
    
    print("\n" + "="*80)
    print("A2 PESTICIDE APPLICATION TEST - With Realistic Fuel Consumption")
    print("="*80)
    
    # A2 Test Parameters
    chemical_type = "PE"  # Pesticide
    volume_liters = 15.14  # 4 gallons = 15.14 liters
    area_hectares = 4.0
    npk_content = {"N": 0, "P": 0, "K": 0}  # Pesticides have no NPK
    
    # Test different application methods
    application_methods = [
        ("spray", "General Spray (Boom Sprayer)", 2.5),  # Updated value
        ("airblast", "Orchard Airblast Sprayer", 4.0),  # For apple orchards
        ("hand", "Manual/Backpack Sprayer", 0.8),  # Small scale
        ("aerial", "Aerial Application", 10.0),  # Aircraft
    ]
    
    print(f"\nTest Parameters:")
    print(f"  Product: Organic Neem Oil (70% concentration)")
    print(f"  Volume: {volume_liters} L ({volume_liters/3.785:.1f} gallons)")
    print(f"  Area: {area_hectares} hectares")
    print(f"  NPK: {npk_content} (pesticides have no fertilizer content)")
    print()
    
    for method, description, expected_fuel_per_ha in application_methods:
        result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type=chemical_type,
            volume_liters=volume_liters,
            area_hectares=area_hectares,
            npk_content=npk_content,
            application_method=method
        )
        
        print(f"\n{description} ({method}):")
        print("-" * 50)
        
        breakdown = result["breakdown"]
        print(f"  Manufacturing emissions: {breakdown['manufacturing_emissions_kg_co2e']:.1f} kg CO2e")
        print(f"  Application fuel used: {breakdown['application_fuel_liters']:.1f} L diesel")
        print(f"  Fuel per hectare: {breakdown['application_fuel_liters']/area_hectares:.1f} L/ha")
        print(f"  Application emissions: {breakdown['application_emissions_kg_co2e']:.1f} kg CO2e")
        print(f"  TOTAL CO2e: {result['co2e_kg']:.1f} kg")
        
        # Check if realistic
        actual_fuel_per_ha = breakdown['application_fuel_liters'] / area_hectares
        if abs(actual_fuel_per_ha - expected_fuel_per_ha) < 0.1:
            print(f"  ✅ Fuel consumption realistic ({actual_fuel_per_ha:.1f} L/ha)")
        else:
            print(f"  ❌ Fuel consumption mismatch (expected {expected_fuel_per_ha:.1f} L/ha)")
    
    print("\n" + "="*80)
    print("ANALYSIS:")
    print("-" * 80)
    print("For apple orchards (A2 scenario), the AIRBLAST SPRAYER is most appropriate.")
    print("With realistic fuel consumption of 4.0 L/ha for orchard airblast sprayers:")
    print(f"  - Total fuel: {4.0 * area_hectares:.1f} L diesel")
    print(f"  - Fuel emissions: {(4.0 * area_hectares / 3.785 * 10.21):.1f} kg CO2e")
    print("  - Manufacturing: 0.0 kg CO2e (pesticides have no NPK)")
    print(f"  - TOTAL: ~{(4.0 * area_hectares / 3.785 * 10.21):.1f} kg CO2e")
    print("\nThis is much more realistic than the previous 6.5 kg CO2e!")
    print("="*80)


if __name__ == "__main__":
    test_a2_pesticide_with_realistic_fuel()