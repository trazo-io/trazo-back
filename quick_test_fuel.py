#!/usr/bin/env python
"""Quick test of fuel consumption rates"""


# Calculate A2 scenario with different fuel rates
def test_fuel():
    area_hectares = 4.0

    print("\n" + "=" * 80)
    print("A2 PESTICIDE TEST - FUEL CONSUMPTION COMPARISON")
    print("=" * 80)

    # Old rate (unrealistic)
    old_fuel_per_ha = 0.6  # L/ha (was spray=0.8, precision=0.6)
    old_total_fuel = area_hectares * old_fuel_per_ha
    old_emissions = (old_total_fuel / 3.785) * 10.21  # Convert L to gallons, multiply by EPA factor

    print(f"\nOLD CALCULATION (Unrealistic):")
    print(f"  Fuel consumption: {old_fuel_per_ha} L/ha")
    print(f"  Total fuel: {old_total_fuel} L")
    print(f"  Emissions: {old_emissions:.1f} kg CO2e")

    # New rates for different equipment
    equipment_rates = [
        ("General Spray (Boom)", 2.5),
        ("Orchard Airblast", 4.0),  # Most appropriate for apples
        ("Manual Backpack", 0.8),
    ]

    print(f"\nNEW CALCULATIONS (Realistic):")
    print("-" * 50)
    for equipment, fuel_per_ha in equipment_rates:
        total_fuel = area_hectares * fuel_per_ha
        emissions = (total_fuel / 3.785) * 10.21
        print(f"\n{equipment}:")
        print(f"  Fuel consumption: {fuel_per_ha} L/ha")
        print(f"  Total fuel: {total_fuel} L")
        print(f"  Emissions: {emissions:.1f} kg CO2e")

    print("\n" + "=" * 80)
    print("CONCLUSION:")
    print("For apple orchards (A2 scenario), AIRBLAST SPRAYER is appropriate:")
    print(f"  Old: 6.5 kg CO2e (unrealistic 0.6 L/ha)")
    print(f"  New: {(4.0 * 4 / 3.785 * 10.21):.1f} kg CO2e (realistic 4.0 L/ha)")
    print("This matches agricultural reality much better!")
    print("=" * 80)


if __name__ == "__main__":
    test_fuel()
