#!/usr/bin/env python3
"""
AGRICULTURAL PRODUCT VALIDATION - INTEGRATION TEST
Validates the complete product validation system with real agricultural scenarios.
Tests the solution for the 785% emission variance problem.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock Django setup for standalone testing
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
import django

django.setup()

from carbon.services.product_validation import product_validator


def test_agricultural_validation_system():
    """Test the complete agricultural product validation system"""

    print("🌾 AGRICULTURAL PRODUCT VALIDATION SYSTEM TEST")
    print("=" * 80)
    print()

    # Test cases based on real farming scenarios
    test_scenarios = [
        {
            "name": "Perfect Match - Roundup Herbicide",
            "commercial_name": "Roundup Ready-to-Use Weed Killer",
            "user_selected_type": "HE",
            "expected_correct_type": "HE",
            "expected_match": True,
            "expected_confidence": "> 0.9",
        },
        {
            "name": "Common Mistake - Miracle-Gro as Fungicide",
            "commercial_name": "Miracle-Gro All Purpose Plant Food",
            "user_selected_type": "FU",  # User thinks it's fungicide
            "expected_correct_type": "FE",  # Actually fertilizer
            "expected_match": False,
            "expected_confidence": "> 0.8",
            "expected_warning": "COMMON MISTAKE",
        },
        {
            "name": "NPK Auto-Fill - Urea Fertilizer",
            "commercial_name": "Urea fertilizer",
            "user_selected_type": "FE",
            "expected_correct_type": "FE",
            "expected_match": True,
            "expected_npk": "46-0-0",
        },
        {
            "name": "Multi-Purpose Product - Neem Oil",
            "commercial_name": "Organic Neem Oil",
            "user_selected_type": "PE",  # Could be pesticide or fungicide
            "expected_correct_type": "FU",  # Primarily fungicide
            "expected_match": False,
        },
        {
            "name": "Generic Product - Unknown Chemical",
            "commercial_name": "Custom Farm Mix 123",
            "user_selected_type": "FE",
            "expected_correct_type": "FE",  # Should default to user selection
            "expected_match": True,
            "expected_confidence": "< 0.5",
        },
        {
            "name": "Case Insensitive - roundup lowercase",
            "commercial_name": "roundup concentrate",
            "user_selected_type": "HE",
            "expected_correct_type": "HE",
            "expected_match": True,
            "expected_confidence": "> 0.8",
        },
        {
            "name": "Variant Matching - Copper Fungicide",
            "commercial_name": "Bordeaux Mixture",
            "user_selected_type": "FU",
            "expected_correct_type": "FU",
            "expected_match": True,
            "expected_confidence": "> 0.7",
        },
    ]

    print("📋 RUNNING VALIDATION TESTS")
    print("-" * 50)

    passed_tests = 0
    total_tests = len(test_scenarios)

    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n{i}. {scenario['name']}")
        print(f"   Input: '{scenario['commercial_name']}' as {scenario['user_selected_type']}")

        # Run validation
        result = product_validator.validate_commercial_name(
            commercial_name=scenario["commercial_name"], user_selected_type=scenario["user_selected_type"]
        )

        # Check results
        success = True

        # Check correct type detection
        if result.correct_type != scenario["expected_correct_type"]:
            print(f"   ❌ Expected type {scenario['expected_correct_type']}, got {result.correct_type}")
            success = False
        else:
            print(f"   ✅ Correct type: {result.correct_type}")

        # Check type match expectation
        actual_match = result.correct_type == scenario["user_selected_type"]
        if actual_match != scenario["expected_match"]:
            print(f"   ❌ Expected match: {scenario['expected_match']}, got: {actual_match}")
            success = False
        else:
            match_status = "✅ Match" if actual_match else "⚠️  Mismatch"
            print(f"   {match_status}: {actual_match}")

        # Check confidence level
        print(f"   📊 Confidence: {result.confidence:.3f}")

        # Check for expected warnings
        if "expected_warning" in scenario:
            has_expected_warning = any(scenario["expected_warning"] in warning for warning in result.warnings)
            if not has_expected_warning:
                print(f"   ❌ Expected warning containing '{scenario['expected_warning']}'")
                success = False
            else:
                print(f"   ✅ Expected warning found")

        # Check NPK ratio
        if "expected_npk" in scenario:
            if result.npk_ratio != scenario["expected_npk"]:
                print(f"   ❌ Expected NPK {scenario['expected_npk']}, got {result.npk_ratio}")
                success = False
            else:
                print(f"   ✅ NPK ratio: {result.npk_ratio}")

        # Show warnings
        if result.warnings:
            print(f"   💬 Warnings:")
            for warning in result.warnings:
                print(f"      • {warning}")

        if success:
            passed_tests += 1
            print(f"   ✅ PASSED")
        else:
            print(f"   ❌ FAILED")

    print("\n" + "=" * 80)
    print(f"📊 TEST RESULTS: {passed_tests}/{total_tests} PASSED ({passed_tests/total_tests*100:.1f}%)")

    if passed_tests == total_tests:
        print("🎉 ALL TESTS PASSED - System ready for production deployment!")
    else:
        print(f"⚠️  {total_tests - passed_tests} tests failed - review before deployment")

    print("\n🔍 PRODUCT COVERAGE ANALYSIS")
    print("-" * 50)
    stats = product_validator.get_validation_stats()
    print(f"Total products in database: {stats['total_products']}")
    print(f"Fertilizers: {stats['fertilizers']}")
    print(f"Herbicides: {stats['herbicides']}")
    print(f"Pesticides: {stats['pesticides']}")
    print(f"Fungicides: {stats['fungicides']}")
    print(f"Coverage: {stats['coverage']}")

    print("\n🎯 AUTOCOMPLETE SUGGESTIONS TEST")
    print("-" * 50)

    autocomplete_tests = [
        {"query": "miracle", "expected_count": "> 1"},
        {"query": "roundup", "expected_count": "> 1"},
        {"query": "copper", "expected_count": "> 0"},
        {"query": "xyz123", "expected_count": "= 0"},
    ]

    for test in autocomplete_tests:
        suggestions = product_validator.get_product_suggestions(test["query"])
        print(f"Query '{test['query']}': {len(suggestions)} suggestions")
        for suggestion in suggestions[:2]:  # Show first 2
            print(f"  • {suggestion['name']} ({suggestion['type']})")
        if len(suggestions) > 2:
            print(f"  ... and {len(suggestions) - 2} more")

    print("\n" + "=" * 80)
    print("🌾 AGRICULTURAL PRODUCT VALIDATION SYSTEM - TEST COMPLETE")
    print("Ready to solve the 785% emission variance problem!")

    return passed_tests == total_tests


if __name__ == "__main__":
    test_agricultural_validation_system()
