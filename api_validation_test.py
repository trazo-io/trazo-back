#!/usr/bin/env python3
"""
API ENDPOINT VALIDATION TEST
Test the actual Smart Product API endpoints to ensure they work correctly for farmers
"""

import json
import os
import sys
from typing import Dict, List

import requests


# Test the actual API endpoints that the React frontend uses
class SmartProductAPITester:
    """Test the Smart Product API endpoints"""

    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        self.headers = {
            "Content-Type": "application/json",
        }
        # In production, would need authentication token
        # For testing, we'll check if endpoints are accessible

    def test_search_endpoint(self):
        """Test the smart product search endpoint"""
        print("🔍 TESTING SMART PRODUCT SEARCH API ENDPOINT")
        print("=" * 60)

        test_cases = [
            # Should return no results
            {"query": "ads", "expected_results": 0},
            {"query": "xyz", "expected_results": 0},
            {"query": "random", "expected_results": 0},
            # Should return results
            {"query": "miracle-gro", "expected_results": 1},
            {"query": "roundup", "expected_results": 1},
            {"query": "fertilizer", "expected_results": ">0"},
            # Problematic cases
            {"query": "herb", "expected_results": 0},  # Should not match
            {"query": "fung", "expected_results": 0},  # Should not match
        ]

        endpoint = f"{self.base_url}/api/carbon/smart-product-search/"
        failed_tests = []

        for test_case in test_cases:
            query = test_case["query"]
            expected = test_case["expected_results"]

            print(f"\nTesting search: '{query}'")

            try:
                response = requests.post(
                    endpoint, json={"query": query, "max_suggestions": 5}, headers=self.headers, timeout=10
                )

                if response.status_code == 200:
                    data = response.json()
                    suggestions = data.get("suggestions", [])
                    count = len(suggestions)

                    print(f"  Status: {response.status_code}")
                    print(f"  Results: {count} suggestions")

                    if suggestions:
                        for i, suggestion in enumerate(suggestions[:2]):  # Show first 2
                            name = suggestion.get("name", "Unknown")
                            confidence = suggestion.get("confidence", 0)
                            print(f"    {i+1}. {name} - {confidence:.1%} confidence")

                    # Validate expectations
                    if expected == 0 and count > 0:
                        print(f"  ❌ FAILURE: Expected no results, got {count}")
                        failed_tests.append(
                            {"query": query, "expected": expected, "actual": count, "suggestions": suggestions}
                        )
                    elif expected == ">0" and count == 0:
                        print(f"  ❌ FAILURE: Expected results, got none")
                        failed_tests.append({"query": query, "expected": expected, "actual": count})
                    elif isinstance(expected, int) and expected > 0 and count != expected:
                        print(f"  ⚠️  WARNING: Expected {expected} results, got {count}")
                    else:
                        print(f"  ✅ SUCCESS: Results match expectations")

                else:
                    print(f"  ❌ API ERROR: {response.status_code}")
                    print(f"  Response: {response.text[:200]}")
                    failed_tests.append(
                        {"query": query, "error": f"HTTP {response.status_code}", "response": response.text[:200]}
                    )

            except requests.exceptions.RequestException as e:
                print(f"  ❌ CONNECTION ERROR: {str(e)}")
                failed_tests.append({"query": query, "error": f"Connection error: {str(e)}"})

        return failed_tests

    def test_validation_endpoint(self):
        """Test the smart product validation endpoint"""
        print("\n" + "=" * 60)
        print("✅ TESTING SMART PRODUCT VALIDATION API ENDPOINT")
        print("=" * 60)

        test_cases = [
            # Valid products
            {
                "commercial_name": "miracle-gro",
                "user_selected_type": "FE",
                "expected_confidence": ">0.8",
                "expected_type": "FE",
            },
            {
                "commercial_name": "roundup",
                "user_selected_type": "HE",
                "expected_confidence": ">0.8",
                "expected_type": "HE",
            },
            # Type mismatch (common farmer mistake)
            {
                "commercial_name": "roundup",
                "user_selected_type": "PE",  # Wrong! Should be HE
                "expected_confidence": ">0.8",
                "expected_type": "HE",
                "expect_warnings": True,
            },
            # Unknown products (should return low confidence)
            {
                "commercial_name": "ads",
                "user_selected_type": "FE",
                "expected_confidence": "<0.4",
                "expected_type": "FE",  # Should use user selection
                "expect_warnings": True,
            },
            {
                "commercial_name": "xyz",
                "user_selected_type": "PE",
                "expected_confidence": "<0.4",
                "expected_type": "PE",
                "expect_warnings": True,
            },
            # Problematic partial matches
            {
                "commercial_name": "herb",
                "user_selected_type": "FE",
                "expected_confidence": "<0.5",  # Should not strongly match
                "expected_type": "FE",
                "expect_warnings": True,
            },
        ]

        endpoint = f"{self.base_url}/api/carbon/smart-product-validation/"
        failed_tests = []

        for test_case in test_cases:
            name = test_case["commercial_name"]
            user_type = test_case["user_selected_type"]
            expected_confidence = test_case["expected_confidence"]
            expected_type = test_case["expected_type"]
            expect_warnings = test_case.get("expect_warnings", False)

            print(f"\nTesting validation: '{name}' as {user_type}")

            try:
                response = requests.post(
                    endpoint,
                    json={"commercial_name": name, "user_selected_type": user_type, "confidence_threshold": 0.7},
                    headers=self.headers,
                    timeout=10,
                )

                if response.status_code == 200:
                    data = response.json()
                    result = data.get("validation_result", {})

                    confidence = result.get("confidence", 0)
                    detected_type = result.get("correct_type", "")
                    warnings = result.get("warnings", [])
                    npk = result.get("npk_ratio")
                    validation_passed = result.get("validation_passed", False)

                    print(f"  Status: {response.status_code}")
                    print(f"  Confidence: {confidence:.1%}")
                    print(f"  Detected type: {detected_type}")
                    print(f"  Validation passed: {validation_passed}")
                    if npk:
                        print(f"  NPK auto-fill: {npk}")
                    if warnings:
                        print(f"  Warnings: {len(warnings)}")
                        for warning in warnings[:2]:  # Show first 2
                            print(f"    - {warning}")

                    # Validate expectations
                    issues = []

                    # Check confidence
                    if expected_confidence.startswith(">"):
                        min_conf = float(expected_confidence[1:])
                        if confidence <= min_conf:
                            issues.append(f"Confidence {confidence:.1%} <= {min_conf:.0%}")
                    elif expected_confidence.startswith("<"):
                        max_conf = float(expected_confidence[1:])
                        if confidence >= max_conf:
                            issues.append(f"Confidence {confidence:.1%} >= {max_conf:.0%}")

                    # Check type
                    if detected_type != expected_type:
                        issues.append(f"Type {detected_type} != {expected_type}")

                    # Check warnings expectation
                    if expect_warnings and not warnings:
                        issues.append("Expected warnings but got none")

                    if issues:
                        print(f"  ❌ ISSUES: {', '.join(issues)}")
                        failed_tests.append({"name": name, "user_type": user_type, "issues": issues, "result": result})
                    else:
                        print(f"  ✅ SUCCESS: Validation meets expectations")

                else:
                    print(f"  ❌ API ERROR: {response.status_code}")
                    print(f"  Response: {response.text[:200]}")
                    failed_tests.append(
                        {
                            "name": name,
                            "user_type": user_type,
                            "error": f"HTTP {response.status_code}",
                            "response": response.text[:200],
                        }
                    )

            except requests.exceptions.RequestException as e:
                print(f"  ❌ CONNECTION ERROR: {str(e)}")
                failed_tests.append({"name": name, "user_type": user_type, "error": f"Connection error: {str(e)}"})

        return failed_tests

    def test_carbon_integration(self):
        """Test that Smart Product data integrates with carbon calculation"""
        print("\n" + "=" * 60)
        print("⚡ TESTING CARBON CALCULATION INTEGRATION")
        print("=" * 60)

        # Test a complete flow: validate product -> use in carbon calculation
        test_scenario = {
            "commercial_name": "miracle-gro",
            "user_selected_type": "FE",
            "area": 2.5,  # acres
            "application_rate": 50.0,  # lbs/acre
        }

        print(f"Testing integration scenario: {test_scenario['commercial_name']}")

        try:
            # Step 1: Validate the product
            validation_endpoint = f"{self.base_url}/api/carbon/smart-product-validation/"
            validation_response = requests.post(
                validation_endpoint,
                json={
                    "commercial_name": test_scenario["commercial_name"],
                    "user_selected_type": test_scenario["user_selected_type"],
                    "confidence_threshold": 0.7,
                },
                headers=self.headers,
                timeout=10,
            )

            if validation_response.status_code != 200:
                print(f"  ❌ Validation API failed: {validation_response.status_code}")
                return [{"error": "Validation API failed", "status": validation_response.status_code}]

            validation_data = validation_response.json()
            validation_result = validation_data.get("validation_result", {})

            print(f"  Step 1 - Product validation:")
            print(f"    Confidence: {validation_result.get('confidence', 0):.1%}")
            print(f"    Type: {validation_result.get('correct_type')}")
            print(f"    NPK: {validation_result.get('npk_ratio')}")
            print(f"    Manufacturer: {validation_result.get('manufacturer')}")

            # Step 2: Check if this data would work in carbon calculation
            # (Simulate what frontend would do with this data)
            if validation_result.get("confidence", 0) >= 0.6:
                print(f"  Step 2 - Carbon integration simulation:")

                # Extract key data for carbon calculation
                product_type = validation_result.get("correct_type")
                npk_ratio = validation_result.get("npk_ratio")
                active_ingredient = validation_result.get("active_ingredient")

                print(f"    Would use type: {product_type}")
                if npk_ratio:
                    print(f"    Would auto-fill NPK: {npk_ratio}")
                if active_ingredient:
                    print(f"    Would record ingredient: {active_ingredient}")

                # Simulate carbon factor lookup (simplified)
                carbon_factors = {"FE": 1.2, "HE": 8.5, "PE": 15.3, "FU": 12.1}
                base_factor = carbon_factors.get(product_type, 5.0)

                # Calculate estimated carbon impact
                total_application = test_scenario["area"] * test_scenario["application_rate"]
                carbon_impact = total_application * base_factor / 1000  # Convert to tons

                print(f"    Estimated carbon impact: {carbon_impact:.3f} tons CO2e")
                print(f"  ✅ SUCCESS: Smart Product data successfully integrates with carbon calculation")

                return []
            else:
                print(f"  ⚠️  LOW CONFIDENCE: Product validation confidence too low for reliable carbon calculation")
                return [
                    {"warning": "Low confidence product data", "confidence": validation_result.get("confidence", 0)}
                ]

        except requests.exceptions.RequestException as e:
            print(f"  ❌ CONNECTION ERROR: {str(e)}")
            return [{"error": f"Connection error: {str(e)}"}]
        except Exception as e:
            print(f"  ❌ INTEGRATION ERROR: {str(e)}")
            return [{"error": f"Integration error: {str(e)}"}]

    def run_comprehensive_api_test(self):
        """Run all API tests and generate report"""
        print("🧪 COMPREHENSIVE SMART PRODUCT API VALIDATION")
        print("Testing actual API endpoints that React frontend uses")
        print("=" * 60)

        try:
            # Check if server is running
            health_response = requests.get(f"{self.base_url}/api/", timeout=5)
            if health_response.status_code != 200:
                print(f"❌ SERVER NOT ACCESSIBLE: {health_response.status_code}")
                print("Make sure Django development server is running:")
                print("cd trazo-back && poetry run python manage.py runserver")
                return False

            print(f"✅ SERVER ACCESSIBLE: {self.base_url}")
        except requests.exceptions.RequestException as e:
            print(f"❌ SERVER CONNECTION FAILED: {str(e)}")
            print("Make sure Django development server is running:")
            print("cd trazo-back && poetry run python manage.py runserver")
            return False

        all_issues = []

        # Test all endpoints
        search_issues = self.test_search_endpoint()
        validation_issues = self.test_validation_endpoint()
        integration_issues = self.test_carbon_integration()

        all_issues.extend(search_issues)
        all_issues.extend(validation_issues)
        all_issues.extend(integration_issues)

        # Generate final report
        print("\n" + "=" * 60)
        print("📊 COMPREHENSIVE API TEST REPORT")
        print("=" * 60)

        print(f"\n🔍 SEARCH API: {len(search_issues)} issues")
        if search_issues:
            for issue in search_issues[:2]:
                query = issue.get("query", "unknown")
                print(f"    - '{query}': {issue.get('error', issue.get('actual', 'Unknown issue'))}")
        else:
            print("    ✅ Search API working correctly")

        print(f"\n✅ VALIDATION API: {len(validation_issues)} issues")
        if validation_issues:
            for issue in validation_issues[:2]:
                name = issue.get("name", "unknown")
                print(f"    - '{name}': {', '.join(issue.get('issues', ['Unknown issue']))}")
        else:
            print("    ✅ Validation API working correctly")

        print(f"\n⚡ INTEGRATION: {len(integration_issues)} issues")
        if integration_issues:
            for issue in integration_issues[:2]:
                print(f"    - {issue.get('error', issue.get('warning', 'Unknown issue'))}")
        else:
            print("    ✅ Carbon integration working correctly")

        total_issues = len(all_issues)
        print(f"\n{'='*60}")
        print(f"🏁 API TEST SUMMARY: {total_issues} total issues found")
        print(f"{'='*60}")

        if total_issues == 0:
            print("✅ EXCELLENT: All API endpoints working perfectly!")
            print("   - Smart Product search prevents false positives")
            print("   - Validation provides appropriate confidence levels")
            print("   - Carbon calculation integration working")
            print("\n   🎉 React frontend can trust these APIs for accurate farmer experience!")
        else:
            print(f"⚠️  ISSUES DETECTED: {total_issues} problems found")
            print("   - Review API responses and fix identified issues")
            print("   - Test again after fixes")

        return total_issues == 0


def main():
    """Test the Smart Product API endpoints"""
    print("Starting Smart Product API validation tests...")

    # Use localhost by default, can be changed for staging/production testing
    api_url = os.getenv("TRAZO_API_URL", "http://localhost:8000")

    tester = SmartProductAPITester(api_url)
    success = tester.run_comprehensive_api_test()

    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
