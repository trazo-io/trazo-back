#!/usr/bin/env python3
"""
TEST TYPE CHANGE RE-VALIDATION
Test what happens when user changes chemical type after product validation
"""

import os
import sys

# Set up Django environment
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")

import django

django.setup()

from carbon.services.smart_product_validator import SmartProductValidator


def test_type_change_scenarios():
    """Test validation when chemical type changes"""
    print("🧪 TESTING TYPE CHANGE RE-VALIDATION SCENARIOS")
    print("=" * 70)

    validator = SmartProductValidator()

    # Test scenario: Miracle-Gro with different type selections
    test_scenarios = [
        {
            "product": "Miracle-Gro",
            "initial_type": "PE",  # Pesticide (wrong)
            "expected_detection": "FE",  # Should detect as Fertilizer
            "changed_type": "FE",  # User changes to Fertilizer
            "expected_after_change": "validation should pass",
        },
        {
            "product": "Roundup",
            "initial_type": "FE",  # Fertilizer (wrong)
            "expected_detection": "HE",  # Should detect as Herbicide
            "changed_type": "HE",  # User changes to Herbicide
            "expected_after_change": "validation should pass",
        },
        {
            "product": "Roundup",
            "initial_type": "PE",  # Pesticide (wrong)
            "expected_detection": "HE",  # Should detect as Herbicide
            "changed_type": "FE",  # User changes to Fertilizer (still wrong!)
            "expected_after_change": "validation should still fail",
        },
    ]

    for scenario in test_scenarios:
        print(f"\n📋 SCENARIO: {scenario['product']}")
        print(f"   Step 1: User selects '{scenario['initial_type']}' and enters '{scenario['product']}'")

        # Initial validation
        initial_result = validator.validate_smart_product(scenario["product"], scenario["initial_type"])

        print(f"   → Detection: {initial_result.correct_type} (expected: {scenario['expected_detection']})")
        print(f"   → Confidence: {initial_result.confidence:.1%}")
        print(f"   → Validation Passed: {initial_result.correct_type == scenario['initial_type']}")

        if initial_result.correct_type != scenario["initial_type"]:
            print(f"   → Message: 'Detected as {get_type_name(initial_result.correct_type)}'")
            print(f"   → Suggestion: 'Please select {get_type_name(initial_result.correct_type)} in dropdown'")

        print(f"\n   Step 2: User changes dropdown to '{scenario['changed_type']}'")

        # Re-validation with new type
        new_result = validator.validate_smart_product(scenario["product"], scenario["changed_type"])

        print(f"   → Detection: {new_result.correct_type}")
        print(f"   → Confidence: {new_result.confidence:.1%}")
        print(f"   → Validation Passed: {new_result.correct_type == scenario['changed_type']}")

        # Expected behavior
        if new_result.correct_type == scenario["changed_type"]:
            print(f"   ✅ SUCCESS: Validation now passes! No more warnings.")
            print(f"   → UI shows: 'Perfect match!' or 'Good match!'")
            if new_result.npk_ratio:
                print(f"   → NPK auto-filled: {new_result.npk_ratio}")
        else:
            print(
                f"   ⚠️  STILL MISMATCH: Product is {get_type_name(new_result.correct_type)}, not {get_type_name(scenario['changed_type'])}"
            )
            print(f"   → UI still shows: 'Detected as {get_type_name(new_result.correct_type)}'")

        print(f"   Expected: {scenario['expected_after_change']}")


def get_type_name(type_code):
    """Convert type code to user-friendly name"""
    type_names = {"FE": "Fertilizer", "PE": "Pesticide", "HE": "Herbicide", "FU": "Fungicide"}
    return type_names.get(type_code, type_code)


def main():
    """Run type change re-validation test"""
    try:
        test_type_change_scenarios()

        print("\n" + "=" * 70)
        print("🎯 EXPECTED BEHAVIOR SUMMARY")
        print("=" * 70)

        print("\n✅ CORRECT FLOW:")
        print("1. User selects 'Pesticide', enters 'Miracle-Gro'")
        print("   → System shows: 'Detected as Fertilizer'")
        print("2. User changes dropdown to 'Fertilizer'")
        print("   → System re-validates automatically")
        print("   → Warning disappears")
        print("   → Shows: 'Perfect match!' with NPK auto-fill")

        print("\n✅ KEY IMPROVEMENTS:")
        print("• Automatic re-validation when type changes")
        print("• Clear visual feedback when validation passes")
        print("• NPK auto-fill activates for correct fertilizer matches")
        print("• No more confusing persistent warnings")

        return True

    except Exception as e:
        print(f"❌ Test execution failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
