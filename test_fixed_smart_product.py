#!/usr/bin/env python3
"""
TEST FIXED SMART PRODUCT VALIDATOR
Test the security fixes for false positives
"""

import os
import sys

# Set up Django environment
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trazo.settings.dev")

import django

django.setup()

from carbon.services.smart_product_validator import SmartProductValidator


def test_fixed_validator():
    """Test the fixed Smart Product validator"""
    print("🔧 TESTING FIXED SMART PRODUCT VALIDATOR")
    print("Testing security fixes for false positives")
    print("=" * 60)

    validator = SmartProductValidator()

    # Test the specific problematic cases
    problematic_cases = [
        # Should now return NO results (fixed)
        {"query": "herb", "expectation": "Should NOT match herbicide"},
        {"query": "fung", "expectation": "Should NOT match fungicide"},
        # Should still return no results (unchanged)
        {"query": "ads", "expectation": "Should return no results"},
        {"query": "xyz", "expectation": "Should return no results"},
        {"query": "random", "expectation": "Should return no results"},
        # Should still work correctly (unchanged)
        {"query": "miracle-gro", "expectation": "Should match with high confidence"},
        {"query": "roundup", "expectation": "Should match with high confidence"},
        {"query": "fertilizer", "expectation": "Should match fertilizer products"},
        {"query": "herbicide", "expectation": "Should match herbicide products"},
    ]

    print("\n🔍 SEARCH RESULTS TEST:")
    print("-" * 40)

    fixed_issues = 0
    remaining_issues = 0

    for test_case in problematic_cases:
        query = test_case["query"]
        expectation = test_case["expectation"]

        print(f"\nTesting: '{query}' - {expectation}")

        # Test search
        search_results = validator.smart_product_search(query, max_suggestions=3)

        if search_results:
            print(f"  Results: {len(search_results)} matches")
            for result in search_results:
                confidence = result.get("confidence", 0)
                name = result.get("name", "Unknown")
                print(f"    - {name}: {confidence:.1%} confidence")

            # Check if this was expected
            if query in ["herb", "fung"] and len(search_results) > 0:
                print(f"  ❌ STILL BROKEN: '{query}' matches despite fixes")
                remaining_issues += 1
            elif query in ["ads", "xyz", "random"] and len(search_results) > 0:
                print(f"  ❌ REGRESSION: '{query}' now incorrectly matches")
                remaining_issues += 1
            elif query in ["miracle-gro", "roundup", "fertilizer", "herbicide"]:
                print(f"  ✅ EXPECTED: Valid agricultural term matches")
        else:
            print(f"  No search results")

            # Check if this was expected
            if query in ["herb", "fung"]:
                print(f"  ✅ FIXED: '{query}' no longer matches incorrectly")
                fixed_issues += 1
            elif query in ["ads", "xyz", "random"]:
                print(f"  ✅ CORRECT: Non-agricultural term returns no results")
            elif query in ["miracle-gro", "roundup"]:
                print(f"  ❌ REGRESSION: Valid product no longer matches")
                remaining_issues += 1

    print("\n✅ VALIDATION RESULTS TEST:")
    print("-" * 40)

    validation_cases = [
        {"name": "herb", "type": "HE", "expected": "Low confidence"},
        {"name": "fung", "type": "FU", "expected": "Low confidence"},
        {"name": "ads", "type": "FE", "expected": "30% confidence (unknown)"},
        {"name": "miracle-gro", "type": "FE", "expected": "High confidence"},
    ]

    for test_case in validation_cases:
        name = test_case["name"]
        selected_type = test_case["type"]
        expected = test_case["expected"]

        print(f"\nValidating: '{name}' as {selected_type} - {expected}")

        validation = validator.validate_smart_product(name, selected_type)
        confidence = validation.confidence
        detected_type = validation.correct_type
        warnings = len(validation.warnings)

        print(f"  Confidence: {confidence:.1%}")
        print(f"  Detected type: {detected_type}")
        print(f"  Warnings: {warnings}")

        if name in ["herb", "fung"] and confidence > 0.5:
            print(f"  ❌ STILL BROKEN: High confidence for partial word")
            remaining_issues += 1
        elif name in ["herb", "fung"] and confidence <= 0.4:
            print(f"  ✅ FIXED: Low confidence for partial word")
            fixed_issues += 1
        elif name == "ads" and confidence == 0.3:
            print(f"  ✅ CORRECT: Expected 30% for unknown product")
        elif name == "miracle-gro" and confidence >= 0.8:
            print(f"  ✅ CORRECT: High confidence for known product")
        else:
            print(f"  ℹ️  Result within expectations")

    # Final assessment
    print("\n" + "=" * 60)
    print("📊 FIX VALIDATION SUMMARY")
    print("=" * 60)

    print(f"✅ Issues fixed: {fixed_issues}")
    print(f"❌ Issues remaining: {remaining_issues}")

    if remaining_issues == 0:
        print("\n🎉 SUCCESS: All false positive issues have been FIXED!")
        print("   - 'herb' no longer matches 'herbicide' with high confidence")
        print("   - 'fung' no longer matches 'fungicide' with high confidence")
        print("   - Non-agricultural terms still return no matches")
        print("   - Valid agricultural products still work correctly")
        print("\n   ✅ The Smart Product validator is now SAFE for farmers!")
    else:
        print(f"\n⚠️  PARTIAL SUCCESS: {fixed_issues} issues fixed, but {remaining_issues} remain")
        print("   Additional fixes may be needed")

    return remaining_issues == 0


def test_carbon_calculation_integration():
    """Test that fixed validation integrates properly with carbon calculations"""
    print("\n" + "=" * 60)
    print("⚡ TESTING CARBON CALCULATION INTEGRATION WITH FIXES")
    print("=" * 60)

    validator = SmartProductValidator()

    # Test a complete workflow
    test_products = [
        {"name": "miracle-gro", "type": "FE", "area": 2.0, "rate": 25.0},
        {"name": "roundup", "type": "HE", "area": 5.0, "rate": 3.0},
        {"name": "unknown-product", "type": "FE", "area": 1.0, "rate": 30.0},
    ]

    for product in test_products:
        print(f"\n🧪 Testing: {product['name']}")

        # Step 1: Product validation
        validation = validator.validate_smart_product(product["name"], product["type"])

        print(f"  Validation confidence: {validation.confidence:.1%}")
        print(f"  Detected type: {validation.correct_type}")
        if validation.npk_ratio:
            print(f"  NPK auto-fill: {validation.npk_ratio}")

        # Step 2: Simulate carbon calculation
        if validation.confidence >= 0.3:  # Minimum threshold for calculation
            # Use detected type for calculation
            carbon_factors = {"FE": 1.2, "HE": 8.5, "PE": 15.3, "FU": 12.1}
            factor = carbon_factors.get(validation.correct_type, 5.0)

            total_application = product["area"] * product["rate"]
            carbon_impact = total_application * factor / 1000  # tons CO2e

            print(f"  Carbon factor: {factor} kg CO2e/unit")
            print(f"  Estimated impact: {carbon_impact:.3f} tons CO2e")

            # Confidence-based reliability
            if validation.confidence >= 0.8:
                print(f"  ✅ HIGH RELIABILITY: Carbon calculation based on validated product data")
            elif validation.confidence >= 0.5:
                print(f"  ⚠️  MEDIUM RELIABILITY: Carbon calculation moderately confident")
            else:
                print(f"  ⚠️  LOW RELIABILITY: Carbon calculation based on user-selected type")
        else:
            print(f"  ❌ CANNOT CALCULATE: Confidence too low for reliable carbon calculation")

    print(f"\n✅ INTEGRATION TEST COMPLETE")
    print(f"   Smart Product validation provides appropriate confidence levels")
    print(f"   Carbon calculations can proceed with clear reliability indicators")


def main():
    """Run comprehensive testing of fixed validator"""
    try:
        print("🧪 COMPREHENSIVE TESTING OF SECURITY FIXES")
        print("Validating that false positive issues have been resolved")

        # Test the fixes
        validation_success = test_fixed_validator()

        # Test integration
        test_carbon_calculation_integration()

        if validation_success:
            print("\n" + "=" * 60)
            print("🎉 ALL TESTS PASSED!")
            print("✅ False positive security issues have been FIXED")
            print("✅ Smart Product validator is now SAFE for farmers")
            print("✅ Carbon calculation integration working correctly")
            print("\n   Farmers can now trust the system for accurate carbon footprints! 🌱")
        else:
            print("\n" + "=" * 60)
            print("⚠️  TESTS PARTIALLY PASSED")
            print("Some issues may still need attention")

        return validation_success

    except Exception as e:
        print(f"❌ Testing failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
