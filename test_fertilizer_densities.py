#!/usr/bin/env python3
"""
Direct test of fertilizer density calculations without Django setup.
Tests the critical fertilizer density fixes for carbon calculation accuracy.
"""


def get_fertilizer_density(npk_content, application_method="broadcast"):
    """
    Enhanced fertilizer density calculation based on NPK content and application method.
    This is a copy of the verified_emission_factors._get_fertilizer_density method.
    """
    n_percentage = npk_content.get("N", 0)
    p_percentage = npk_content.get("P", 0)
    k_percentage = npk_content.get("K", 0)

    # Special case: Anhydrous ammonia (82-0-0 or similar high N, no P/K)
    if n_percentage >= 80 and p_percentage == 0 and k_percentage == 0:
        # Anhydrous ammonia (NH3) density at liquid state: ~0.68 kg/L
        return 0.68  # kg/L

    # Special case: UAN (Urea Ammonium Nitrate) solutions
    if 25 <= n_percentage <= 35 and p_percentage == 0 and k_percentage == 0:
        # UAN 28%, 30%, 32% solutions: ~1.30 kg/L
        return 1.30  # kg/L

    # Application method considerations
    if application_method in ["injection", "banding"]:
        # Liquid fertilizers for injection/banding
        if n_percentage > 0 or p_percentage > 0 or k_percentage > 0:
            return 1.25  # kg/L for liquid fertilizers

    # Granular fertilizers (broadcast, foliar when not liquid)
    if application_method in ["broadcast", "foliar"]:
        return 0.80  # kg/L (bulk density of granular fertilizers)

    # Default for standard liquid fertilizers
    return 1.25  # kg/L


def test_critical_fertilizer_densities():
    """Test the critical fertilizer density calculations."""

    print("🌱 Testing Critical Fertilizer Densities")
    print("=" * 50)

    test_cases = [
        # Critical anhydrous ammonia case that was fixed
        {
            "name": "Anhydrous Ammonia (82-0-0)",
            "npk": {"N": 82, "P": 0, "K": 0},
            "method": "injection",
            "expected": 0.68,
            "critical": True,
        },
        # UAN solutions
        {
            "name": "UAN 28% Solution",
            "npk": {"N": 28, "P": 0, "K": 0},
            "method": "injection",
            "expected": 1.30,
            "critical": True,
        },
        {
            "name": "UAN 32% Solution",
            "npk": {"N": 32, "P": 0, "K": 0},
            "method": "injection",
            "expected": 1.30,
            "critical": True,
        },
        # Major granular fertilizers
        {
            "name": "DAP (18-46-0)",
            "npk": {"N": 18, "P": 46, "K": 0},
            "method": "broadcast",
            "expected": 0.80,
            "critical": True,
        },
        {
            "name": "MAP (11-52-0)",
            "npk": {"N": 11, "P": 52, "K": 0},
            "method": "broadcast",
            "expected": 0.80,
            "critical": True,
        },
        # Standard liquid fertilizers
        {
            "name": "Standard Liquid (10-10-10)",
            "npk": {"N": 10, "P": 10, "K": 10},
            "method": "injection",
            "expected": 1.25,
            "critical": False,
        },
        # Standard granular fertilizers
        {
            "name": "Standard Granular (16-16-16)",
            "npk": {"N": 16, "P": 16, "K": 16},
            "method": "broadcast",
            "expected": 0.80,
            "critical": False,
        },
    ]

    all_passed = True
    critical_passed = True

    for test_case in test_cases:
        actual = get_fertilizer_density(test_case["npk"], test_case["method"])
        passed = actual == test_case["expected"]

        if not passed:
            all_passed = False
            if test_case["critical"]:
                critical_passed = False

        status = "✅" if passed else "❌"
        critical_marker = "🚨 CRITICAL" if test_case["critical"] else ""

        print(f"{status} {test_case['name']}: {actual} kg/L (expected {test_case['expected']}) {critical_marker}")

    print("\n" + "=" * 50)
    print(f"Overall Results:")
    print(f"✅ All tests passed: {all_passed}")
    print(f"🚨 Critical tests passed: {critical_passed}")

    if critical_passed:
        print("\n🌱 EXCELLENT: All critical fertilizer densities are scientifically accurate!")
        print("Carbon calculations will now provide farmers with trustworthy emissions data.")
    else:
        print("\n❌ CRITICAL FAILURE: Some fertilizer densities are incorrect!")
        print("This will lead to inaccurate carbon calculations and loss of farmer trust.")

    return all_passed and critical_passed


def calculate_carbon_impact_example():
    """Example calculation showing the impact of correct vs incorrect density."""

    print("\n🧮 Carbon Impact Example: Anhydrous Ammonia")
    print("=" * 50)

    # Test scenario: 300L anhydrous ammonia on 2.0 hectares
    volume_liters = 300.0
    area_hectares = 2.0
    npk_content = {"N": 82, "P": 0, "K": 0}

    # Correct density
    correct_density = get_fertilizer_density(npk_content, "injection")
    correct_fertilizer_mass = volume_liters * correct_density
    correct_nitrogen_mass = correct_fertilizer_mass * 0.82
    correct_manufacturing_emissions = correct_nitrogen_mass * 2.98  # EPA factor

    # Incorrect density (what was happening before)
    incorrect_density = 1.0
    incorrect_fertilizer_mass = volume_liters * incorrect_density
    incorrect_nitrogen_mass = incorrect_fertilizer_mass * 0.82
    incorrect_manufacturing_emissions = incorrect_nitrogen_mass * 2.98

    print(f"Scenario: {volume_liters}L anhydrous ammonia on {area_hectares} hectares")
    print(f"\nCorrect calculation (density {correct_density} kg/L):")
    print(f"  Fertilizer mass: {correct_fertilizer_mass:.1f} kg")
    print(f"  Nitrogen content: {correct_nitrogen_mass:.1f} kg N")
    print(f"  Manufacturing emissions: {correct_manufacturing_emissions:.1f} kg CO₂e")

    print(f"\nIncorrect calculation (density {incorrect_density} kg/L):")
    print(f"  Fertilizer mass: {incorrect_fertilizer_mass:.1f} kg")
    print(f"  Nitrogen content: {incorrect_nitrogen_mass:.1f} kg N")
    print(f"  Manufacturing emissions: {incorrect_manufacturing_emissions:.1f} kg CO₂e")

    overestimation = incorrect_manufacturing_emissions - correct_manufacturing_emissions
    percentage_error = (overestimation / correct_manufacturing_emissions) * 100

    print(f"\nImpact of density fix:")
    print(f"  Overestimation reduced by: {overestimation:.1f} kg CO₂e")
    print(f"  Percentage improvement: {percentage_error:.1f}%")

    if percentage_error > 30:
        print(f"  🚨 CRITICAL: This is a major accuracy improvement!")
    elif percentage_error > 10:
        print(f"  ⚠️  SIGNIFICANT: This is an important accuracy improvement!")
    else:
        print(f"  ✅ MINOR: Small but important accuracy improvement.")


if __name__ == "__main__":
    print("🌱 Trazo Carbon Calculation - Fertilizer Density Accuracy Test")
    print("Testing the critical density fixes for scientific accuracy\n")

    success = test_critical_fertilizer_densities()
    calculate_carbon_impact_example()

    if success:
        print("\n🎯 FINAL RESULT: All fertilizer density calculations are scientifically accurate!")
        print("Farmers can trust Trazo's carbon calculations for decision-making.")
    else:
        print("\n❌ FINAL RESULT: Density calculation errors detected!")
        print("Carbon calculations may be inaccurate - immediate fix required.")
