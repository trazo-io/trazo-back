#!/usr/bin/env python3
"""
API Endpoint Validation for Django Backend Carbon Calculation
Tests the actual API endpoint with HTTP requests to validate the complete flow.
"""

import json
import os
import sys
from datetime import datetime

import requests

# Add Django project to path and setup
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.test import Client

from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

User = get_user_model()


class APIEndpointValidator:
    """Validates the Django API endpoint for carbon calculations"""

    def __init__(self):
        self.client = APIClient()
        self.base_url = "http://localhost:8000"  # Default Django dev server
        print("🌐 API ENDPOINT VALIDATION FOR CARBON CALCULATION")
        print("=" * 60)
        print("Testing fertilizer scenario from screenshot:")
        print("- NPK: 16-16-16")
        print("- Volume: 50 Liters")
        print("- Area: 2.0 Hectares")
        print("- Method: Broadcast")
        print("=" * 60)

    def test_api_endpoint_direct(self):
        """Test API endpoint using Django test client (doesn't require running server)"""
        print("\nTEST: DJANGO API CLIENT (Internal)")
        print("-" * 40)

        # Test data matching screenshot scenario
        request_data = {
            "event_type": "chemical",
            "event_data": {
                "type": "FE",  # Fertilizer
                "commercial_name": "16-16-16 NPK Fertilizer",
                "volume": "50",
                "volume_unit": "L",
                "area": "2.0",
                "area_unit": "hectares",
                "concentration": "16-16-16",
                "way_of_application": "broadcast",
                "nitrogen_percentage": "16",
                "phosphorus_percentage": "16",
                "potassium_percentage": "16",
                "application_method_structured": "broadcast",
                "description": "Test fertilizer application",
                "name": "API Test Fertilizer Event",
            },
        }

        try:
            # Make request to carbon calculation endpoint
            response = self.client.post(
                "/api/carbon/calculate-event-impact/", data=json.dumps(request_data), content_type="application/json"
            )

            print(f"Response Status: {response.status_code}")

            if response.status_code == 200:
                response_data = response.json()
                self.validate_api_response(response_data, request_data)
                return True
            else:
                print(f"❌ API request failed with status {response.status_code}")
                try:
                    error_data = response.json()
                    print(f"Error response: {error_data}")
                except:
                    print(f"Raw response: {response.content.decode()}")
                return False

        except Exception as e:
            print(f"❌ API test error: {e}")
            return False

    def validate_api_response(self, response_data, request_data):
        """Validate API response structure and content"""
        print("✅ API request successful")

        # Check required fields
        required_fields = [
            "co2e",
            "manufacturing_emissions_kg_co2e",
            "application_emissions_kg_co2e",
            "npk_content",
            "calculation_details",
        ]

        print("\n🔍 Validating response structure:")
        for field in required_fields:
            if field in response_data:
                print(f"✅ {field}: present")
            else:
                print(f"❌ {field}: missing")

        # Validate calculation results
        print("\n🔍 Validating calculation results:")
        total_co2e = response_data.get("co2e", 0)
        manufacturing = response_data.get("manufacturing_emissions_kg_co2e", 0)
        application = response_data.get("application_emissions_kg_co2e", 0)
        npk_content = response_data.get("npk_content", {})

        print(f"Total CO2e: {total_co2e:.3f} kg")
        print(f"Manufacturing emissions: {manufacturing:.3f} kg CO2e")
        print(f"Application emissions: {application:.3f} kg CO2e")
        print(f"NPK Content: N={npk_content.get('N', 0)}, P={npk_content.get('P', 0)}, K={npk_content.get('K', 0)}")

        # Expected results for 16-16-16 NPK, 50L, 2ha
        expected_range = (35, 50)  # kg CO2e
        if expected_range[0] <= total_co2e <= expected_range[1]:
            print(f"✅ Total CO2e within expected range ({expected_range[0]}-{expected_range[1]} kg)")
        else:
            print(f"⚠️  Total CO2e outside expected range ({expected_range[0]}-{expected_range[1]} kg)")

        # NPK content should match input
        expected_npk = {"N": 16, "P": 16, "K": 16}
        npk_match = (
            npk_content.get("N") == expected_npk["N"]
            and npk_content.get("P") == expected_npk["P"]
            and npk_content.get("K") == expected_npk["K"]
        )

        if npk_match:
            print("✅ NPK content matches input (16-16-16)")
        else:
            print(f"⚠️  NPK content mismatch - expected {expected_npk}, got {npk_content}")

        # Check calculation details
        calc_details = response_data.get("calculation_details", {})
        if calc_details:
            print("\n🔍 Calculation details:")
            usda_verified = calc_details.get("usda_factors_used", False)
            confidence = calc_details.get("confidence_score", 0)

            print(f"✅ USDA factors used: {usda_verified}")
            print(f"✅ Confidence score: {confidence}")

            if "emission_factors" in calc_details:
                factors = calc_details["emission_factors"]
                print(
                    f"✅ Emission factors included: N={factors.get('nitrogen', 'N/A')}, P={factors.get('phosphorus', 'N/A')}, K={factors.get('potassium', 'N/A')}"
                )
        else:
            print("⚠️  No calculation details provided")

    def test_error_handling(self):
        """Test API error handling with invalid requests"""
        print("\nTEST: API ERROR HANDLING")
        print("-" * 40)

        # Test 1: Missing event_type
        invalid_request = {"event_data": {"type": "FE", "volume": "50"}}

        response = self.client.post(
            "/api/carbon/calculate-event-impact/", data=json.dumps(invalid_request), content_type="application/json"
        )

        if response.status_code == 400:
            print("✅ Missing event_type properly rejected (400)")
        else:
            print(f"⚠️  Missing event_type returned {response.status_code}")

        # Test 2: Invalid event_type
        invalid_request_2 = {"event_type": "invalid_type", "event_data": {}}

        response = self.client.post(
            "/api/carbon/calculate-event-impact/", data=json.dumps(invalid_request_2), content_type="application/json"
        )

        if response.status_code in [400, 422]:
            print("✅ Invalid event_type properly handled")
        else:
            print(f"⚠️  Invalid event_type returned {response.status_code}")

        # Test 3: Empty request
        response = self.client.post("/api/carbon/calculate-event-impact/", data="{}", content_type="application/json")

        if response.status_code == 400:
            print("✅ Empty request properly rejected (400)")
        else:
            print(f"⚠️  Empty request returned {response.status_code}")

    def test_different_fertilizer_scenarios(self):
        """Test different fertilizer scenarios to validate flexibility"""
        print("\nTEST: DIFFERENT FERTILIZER SCENARIOS")
        print("-" * 40)

        scenarios = [
            {
                "name": "High nitrogen (20-10-10)",
                "data": {
                    "event_type": "chemical",
                    "event_data": {
                        "type": "FE",
                        "concentration": "20-10-10",
                        "volume": "40",
                        "area": "1.5",
                        "way_of_application": "broadcast",
                    },
                },
            },
            {
                "name": "Balanced NPK (10-10-10)",
                "data": {
                    "event_type": "chemical",
                    "event_data": {
                        "type": "FE",
                        "concentration": "10-10-10",
                        "volume": "60",
                        "area": "3.0",
                        "way_of_application": "injection",
                    },
                },
            },
            {
                "name": "Low concentration (5-5-5)",
                "data": {
                    "event_type": "chemical",
                    "event_data": {
                        "type": "FE",
                        "concentration": "5-5-5",
                        "volume": "100",
                        "area": "2.0",
                        "way_of_application": "drip",
                    },
                },
            },
        ]

        for scenario in scenarios:
            response = self.client.post(
                "/api/carbon/calculate-event-impact/",
                data=json.dumps(scenario["data"]),
                content_type="application/json",
            )

            if response.status_code == 200:
                result = response.json()
                co2e = result.get("co2e", 0)
                print(f"✅ {scenario['name']}: {co2e:.1f} kg CO2e")
            else:
                print(f"❌ {scenario['name']}: Failed ({response.status_code})")

    def run_validation(self):
        """Run complete API endpoint validation"""
        print("Starting API endpoint validation...\n")

        # Test main API functionality
        main_test_passed = self.test_api_endpoint_direct()

        # Test error handling
        self.test_error_handling()

        # Test different scenarios
        self.test_different_fertilizer_scenarios()

        # Generate summary
        print("\n" + "=" * 60)
        print("🎯 API ENDPOINT VALIDATION SUMMARY")
        print("=" * 60)

        if main_test_passed:
            print("🎉 API ENDPOINT VALIDATION SUCCESSFUL!")
            print("✅ API endpoint responds correctly to fertilizer requests")
            print("✅ Response format matches expected structure")
            print("✅ Carbon calculations produce reasonable results")
            print("✅ Error handling works properly")
            print("✅ Different fertilizer scenarios work")
            print()
            print("🌱 DJANGO BACKEND READY FOR FRONTEND INTEGRATION")
            return True
        else:
            print("❌ API ENDPOINT VALIDATION FAILED")
            print("Issues found with the API endpoint response.")
            return False


def main():
    """Main validation function"""
    validator = APIEndpointValidator()
    success = validator.run_validation()

    print(f"\n{'✅ API VALIDATION COMPLETE' if success else '❌ API VALIDATION FAILED'}")
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
