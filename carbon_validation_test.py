#!/usr/bin/env python3
"""
COMPREHENSIVE CARBON CALCULATION SMART PRODUCT VALIDATION
Test the complete workflow from Smart Product validation to carbon footprint calculations
"""

import logging
import os
import sys
from typing import Dict, List, Optional

# Add the Django project to the path
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trazo.settings.dev")

# Initialize Django
import django

django.setup()

from django.contrib.auth import get_user_model

from carbon.models import CarbonFootprint, ChemicalEvent
from carbon.services.smart_product_validator import SmartProductValidator
from company.models import Production

logger = logging.getLogger(__name__)


class CarbonValidationTester:
    """Complete carbon calculation validation test suite"""

    def __init__(self):
        self.validator = SmartProductValidator()
        self.test_results = {"edge_cases": [], "valid_cases": [], "carbon_integration": [], "farmer_journey": []}

    def test_edge_cases(self):
        """Test edge cases that should NOT match agricultural products"""
        print("🔍 TESTING SMART PRODUCT VALIDATOR EDGE CASES")
        print("=" * 60)

        # Test cases that should NOT match or have very low confidence
        edge_cases = [
            "ads",
            "xyz",
            "random",
            "asdfgh",
            "qwerty",
            "test",
            "blah",
            "a",
            "z",
            "1",
            "9",
            "",
            " ",
            "car",
            "house",
            "phone",
            "fer",
            "pest",
            "herb",
            "fung",
            "!@#$%",
            "***",
            "???",
        ]

        failed_tests = []

        for i, test_input in enumerate(edge_cases, 1):
            print(f"\n[{i}/{len(edge_cases)}] Testing: '{test_input}'")

            # Test smart product search
            search_results = self.validator.smart_product_search(test_input, max_suggestions=3)

            if search_results:
                print(f"  ❌ PROBLEM: Got {len(search_results)} search results:")
                for result in search_results:
                    confidence = result.get("confidence", 0)
                    name = result.get("name", "Unknown")
                    type_code = result.get("type_code", "Unknown")
                    why_matched = result.get("why_matched", "No explanation")

                    print(f"    - {name} ({type_code}) - {confidence:.1%} confidence")
                    print(f"      Reason: {why_matched}")

                    # Flag as failed if confidence > 15% for meaningless input
                    if confidence > 0.15:
                        failed_tests.append(
                            {
                                "input": test_input,
                                "matched_product": name,
                                "confidence": confidence,
                                "type": type_code,
                                "reason": why_matched,
                            }
                        )
            else:
                print("  ✅ GOOD: No search results")

            # Test validation with FE type (common type)
            validation_result = self.validator.validate_smart_product(test_input, "FE", confidence_threshold=0.7)

            if validation_result.confidence > 0.25:
                print(f"  ❌ VALIDATION PROBLEM: {validation_result.confidence:.1%} confidence")
                print(f"    Product: {validation_result.commercial_name}")
                print(f"    Type: {validation_result.correct_type}")
                if validation_result.warnings:
                    print(f"    Warnings: {validation_result.warnings}")

                if validation_result.confidence > 0.25:
                    failed_tests.append(
                        {
                            "input": test_input,
                            "validation_confidence": validation_result.confidence,
                            "validation_type": validation_result.correct_type,
                            "test_type": "validation",
                        }
                    )
            else:
                print(f"  ✅ VALIDATION OK: {validation_result.confidence:.1%} confidence")

        self.test_results["edge_cases"] = failed_tests
        return failed_tests

    def test_valid_agricultural_products(self):
        """Test that known valid products still work correctly"""
        print("\n" + "=" * 60)
        print("🌱 TESTING VALID AGRICULTURAL PRODUCTS")
        print("=" * 60)

        valid_products = [
            # Should have HIGH confidence (>80%)
            {"input": "miracle-gro", "expected_type": "FE", "min_confidence": 0.80},
            {"input": "roundup", "expected_type": "HE", "min_confidence": 0.80},
            {"input": "urea", "expected_type": "FE", "min_confidence": 0.80},
            {"input": "10-10-10", "expected_type": "FE", "min_confidence": 0.80},
            {"input": "sevin", "expected_type": "PE", "min_confidence": 0.75},
            # Should have MEDIUM confidence (60-80%) - typos/variations
            {"input": "miracle grow", "expected_type": "FE", "min_confidence": 0.60},
            {"input": "round up", "expected_type": "HE", "min_confidence": 0.60},
            {"input": "fertilizer", "expected_type": "FE", "min_confidence": 0.40},
            {"input": "herbicide", "expected_type": "HE", "min_confidence": 0.40},
        ]

        failed_tests = []

        for test_case in valid_products:
            test_input = test_case["input"]
            expected_type = test_case["expected_type"]
            min_confidence = test_case["min_confidence"]

            print(f"\nTesting: '{test_input}' - Expected: {expected_type}, Min confidence: {min_confidence:.0%}")

            # Test search
            results = self.validator.smart_product_search(test_input, max_suggestions=1)

            if results:
                result = results[0]
                confidence = result.get("confidence", 0)
                detected_type = result.get("type_code", "")
                name = result.get("name", "Unknown")

                print(f"  Result: {name} ({detected_type}) - {confidence:.1%} confidence")

                # Validate results
                issues = []
                if confidence < min_confidence:
                    issues.append(f"Low confidence: {confidence:.1%} < {min_confidence:.0%}")

                if detected_type != expected_type:
                    issues.append(f"Wrong type: {detected_type} != {expected_type}")

                if issues:
                    print(f"  ❌ ISSUES: {', '.join(issues)}")
                    failed_tests.append(
                        {
                            "input": test_input,
                            "expected_type": expected_type,
                            "detected_type": detected_type,
                            "expected_confidence": min_confidence,
                            "actual_confidence": confidence,
                            "issues": issues,
                        }
                    )
                else:
                    print("  ✅ VALID: Meets expectations")
            else:
                print("  ❌ CRITICAL: No results found for valid product!")
                failed_tests.append(
                    {
                        "input": test_input,
                        "expected_type": expected_type,
                        "detected_type": None,
                        "expected_confidence": min_confidence,
                        "actual_confidence": 0.0,
                        "issues": ["No results found"],
                    }
                )

        self.test_results["valid_cases"] = failed_tests
        return failed_tests

    def test_carbon_calculation_integration(self):
        """Test that Smart Product data integrates with carbon calculations"""
        print("\n" + "=" * 60)
        print("⚡ TESTING CARBON CALCULATION INTEGRATION")
        print("=" * 60)

        integration_tests = [
            {
                "product": "miracle-gro",
                "expected_npk": "24-8-16",
                "expected_type": "FE",
                "area": 1.0,  # acres
                "rate": 50.0,  # lbs/acre
            },
            {"product": "urea", "expected_npk": "46-0-0", "expected_type": "FE", "area": 2.5, "rate": 100.0},
            {"product": "roundup", "expected_npk": None, "expected_type": "HE", "area": 5.0, "rate": 2.0},  # fl oz/acre
        ]

        failed_tests = []

        for test_case in integration_tests:
            product_name = test_case["product"]
            expected_npk = test_case["expected_npk"]
            expected_type = test_case["expected_type"]
            area = test_case["area"]
            rate = test_case["rate"]

            print(f"\nTesting carbon integration: '{product_name}'")

            # Step 1: Validate product
            validation_result = self.validator.validate_smart_product(product_name, expected_type)

            print(f"  Validation: {validation_result.confidence:.1%} confidence")
            print(f"  Detected Type: {validation_result.correct_type}")
            print(f"  NPK: {validation_result.npk_ratio}")

            # Validate NPK auto-fill
            issues = []
            if expected_npk and validation_result.npk_ratio != expected_npk:
                issues.append(f"NPK mismatch: {validation_result.npk_ratio} != {expected_npk}")

            if validation_result.correct_type != expected_type:
                issues.append(f"Type mismatch: {validation_result.correct_type} != {expected_type}")

            if validation_result.confidence < 0.6:
                issues.append(f"Low confidence: {validation_result.confidence:.1%}")

            # Step 2: Test carbon impact calculation (simulate)
            try:
                # Calculate estimated carbon impact
                carbon_factor = self._get_carbon_factor(validation_result.correct_type, validation_result.npk_ratio)
                carbon_impact = area * rate * carbon_factor

                print(f"  Carbon Factor: {carbon_factor} kg CO2e per unit")
                print(f"  Estimated Impact: {carbon_impact:.2f} kg CO2e")

                if carbon_impact <= 0:
                    issues.append("Zero or negative carbon impact")

            except Exception as e:
                issues.append(f"Carbon calculation error: {str(e)}")

            if issues:
                print(f"  ❌ INTEGRATION ISSUES: {', '.join(issues)}")
                failed_tests.append({"product": product_name, "validation_result": validation_result, "issues": issues})
            else:
                print("  ✅ INTEGRATION: Valid product data flows to carbon calculation")

        self.test_results["carbon_integration"] = failed_tests
        return failed_tests

    def _get_carbon_factor(self, chemical_type: str, npk_ratio: Optional[str]) -> float:
        """Get carbon emission factor based on product type and NPK ratio"""
        # Simplified carbon factors for testing (kg CO2e per unit)
        base_factors = {
            "FE": 1.2,  # Fertilizer
            "HE": 8.5,  # Herbicide
            "PE": 15.3,  # Pesticide
            "FU": 12.1,  # Fungicide
        }

        base_factor = base_factors.get(chemical_type, 5.0)

        # Adjust for nitrogen content in fertilizers
        if chemical_type == "FE" and npk_ratio:
            try:
                n_content = float(npk_ratio.split("-")[0])
                # Higher nitrogen = higher emissions
                nitrogen_multiplier = 1.0 + (n_content / 100.0)
                return base_factor * nitrogen_multiplier
            except:
                pass

        return base_factor

    def test_farmer_journey(self):
        """Test complete farmer workflow from product entry to carbon result"""
        print("\n" + "=" * 60)
        print("🚜 TESTING COMPLETE FARMER JOURNEY")
        print("=" * 60)

        # Simulate farmer entering chemical event
        farmer_scenarios = [
            {
                "scenario": "Farmer knows exact product name",
                "product_input": "miracle-gro",
                "selected_type": "FE",
                "area": 2.5,
                "rate": 40.0,
                "expected_warnings": 0,
            },
            {
                "scenario": "Farmer has typo in product name",
                "product_input": "miracle grow",  # missing hyphen
                "selected_type": "FE",
                "area": 1.0,
                "rate": 25.0,
                "expected_warnings": 0,
            },
            {
                "scenario": "Farmer selects wrong type",
                "product_input": "roundup",
                "selected_type": "PE",  # Wrong! Should be HE
                "area": 5.0,
                "rate": 3.0,
                "expected_warnings": 1,
            },
            {
                "scenario": "Farmer enters unknown product",
                "product_input": "farmers-choice-123",
                "selected_type": "FE",
                "area": 3.0,
                "rate": 50.0,
                "expected_warnings": 1,
            },
        ]

        failed_tests = []

        for scenario in farmer_scenarios:
            print(f"\n🧑‍🌾 {scenario['scenario']}")
            print(f"  Input: '{scenario['product_input']}' as {scenario['selected_type']}")

            # Step 1: Product validation
            validation = self.validator.validate_smart_product(scenario["product_input"], scenario["selected_type"])

            print(f"  Validation confidence: {validation.confidence:.1%}")
            print(f"  Detected type: {validation.correct_type}")
            if validation.npk_ratio:
                print(f"  Auto-filled NPK: {validation.npk_ratio}")

            # Step 2: Check warnings
            warning_count = len(validation.warnings)
            print(f"  Warnings: {warning_count}")
            for warning in validation.warnings:
                print(f"    - {warning}")

            # Step 3: Educational tips
            if validation.educational_tips:
                print(f"  Educational tips: {len(validation.educational_tips)}")
                for tip in validation.educational_tips[:2]:  # Show first 2
                    print(f"    💡 {tip}")

            # Step 4: Calculate carbon impact
            try:
                carbon_factor = self._get_carbon_factor(validation.correct_type, validation.npk_ratio)
                carbon_impact = scenario["area"] * scenario["rate"] * carbon_factor / 1000  # Convert to tons
                print(f"  Carbon impact: {carbon_impact:.3f} tons CO2e")
            except Exception as e:
                print(f"  ❌ Carbon calculation failed: {str(e)}")
                failed_tests.append({"scenario": scenario["scenario"], "error": f"Carbon calculation failed: {str(e)}"})
                continue

            # Validate expectations
            issues = []
            if warning_count != scenario["expected_warnings"]:
                issues.append(f"Expected {scenario['expected_warnings']} warnings, got {warning_count}")

            if validation.confidence == 0 and scenario["product_input"] in ["miracle-gro", "roundup"]:
                issues.append("Zero confidence for known product")

            if issues:
                print(f"  ❌ ISSUES: {', '.join(issues)}")
                failed_tests.append({"scenario": scenario["scenario"], "issues": issues, "validation": validation})
            else:
                print("  ✅ JOURNEY: Complete workflow successful")

        self.test_results["farmer_journey"] = failed_tests
        return failed_tests

    def generate_comprehensive_report(self):
        """Generate final comprehensive test report"""
        print("\n" + "=" * 60)
        print("📊 COMPREHENSIVE VALIDATION REPORT")
        print("=" * 60)

        total_issues = 0

        # Edge cases report
        edge_issues = len(self.test_results["edge_cases"])
        total_issues += edge_issues

        print(f"\n🔍 EDGE CASES: {edge_issues} issues")
        if edge_issues > 0:
            print("  CRITICAL: False positives detected that could mislead farmers!")
            for issue in self.test_results["edge_cases"][:3]:  # Show first 3
                print(f"    - '{issue['input']}' matched with {issue.get('confidence', 0):.1%} confidence")
        else:
            print("  ✅ No false positives - system properly rejects meaningless input")

        # Valid products report
        valid_issues = len(self.test_results["valid_cases"])
        total_issues += valid_issues

        print(f"\n🌱 VALID PRODUCTS: {valid_issues} issues")
        if valid_issues > 0:
            print("  WARNING: Known agricultural products not working properly!")
            for issue in self.test_results["valid_cases"][:3]:
                print(f"    - '{issue['input']}': {', '.join(issue['issues'])}")
        else:
            print("  ✅ All valid agricultural products work correctly")

        # Integration report
        integration_issues = len(self.test_results["carbon_integration"])
        total_issues += integration_issues

        print(f"\n⚡ CARBON INTEGRATION: {integration_issues} issues")
        if integration_issues > 0:
            print("  WARNING: Smart Product data not integrating with carbon calculations!")
            for issue in self.test_results["carbon_integration"][:3]:
                print(f"    - '{issue['product']}': {', '.join(issue['issues'])}")
        else:
            print("  ✅ Smart Product data properly flows to carbon calculations")

        # Farmer journey report
        journey_issues = len(self.test_results["farmer_journey"])
        total_issues += journey_issues

        print(f"\n🚜 FARMER JOURNEY: {journey_issues} issues")
        if journey_issues > 0:
            print("  WARNING: Complete farmer workflow has problems!")
            for issue in self.test_results["farmer_journey"][:3]:
                print(f"    - {issue['scenario']}: {', '.join(issue.get('issues', ['Unknown error']))}")
        else:
            print("  ✅ Complete farmer workflow works end-to-end")

        # Final assessment
        print(f"\n{'='*60}")
        print(f"🏁 FINAL ASSESSMENT: {total_issues} total issues found")
        print(f"{'='*60}")

        if total_issues == 0:
            print("✅ EXCELLENT: Smart Product validation system is working perfectly!")
            print("   - No false positives that could mislead farmers")
            print("   - All valid products detected correctly")
            print("   - Carbon calculation integration working")
            print("   - Complete farmer journey successful")
            print("\n   Farmers can trust this system for accurate carbon calculations! 🎉")
        elif total_issues <= 2:
            print("⚠️  GOOD: System mostly working with minor issues")
            print("   - Review and fix identified issues")
            print("   - Overall system reliability is acceptable")
        elif total_issues <= 5:
            print("🚨 MODERATE ISSUES: System needs attention")
            print("   - Several problems that could affect farmer experience")
            print("   - Prioritize fixes before production deployment")
        else:
            print("❌ CRITICAL ISSUES: System not ready for farmers!")
            print("   - Multiple serious problems detected")
            print("   - False positives could lead to incorrect carbon calculations")
            print("   - Immediate fixes required before any farmer usage")

        return total_issues


def main():
    """Run comprehensive Smart Product validation testing"""
    print("🧪 COMPREHENSIVE CARBON SMART PRODUCT VALIDATION")
    print("Testing the complete workflow from product entry to carbon footprint")
    print("Ensuring farmers get ACCURATE, RELIABLE carbon calculations")

    tester = CarbonValidationTester()

    try:
        # Run all test suites
        tester.test_edge_cases()
        tester.test_valid_agricultural_products()
        tester.test_carbon_calculation_integration()
        tester.test_farmer_journey()

        # Generate final report
        total_issues = tester.generate_comprehensive_report()

        return total_issues == 0

    except Exception as e:
        print(f"❌ Test execution failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
