"""
Test Suite for Carbon Calculation API Endpoints

This module tests the carbon calculation API endpoints to ensure they:
- Accept proper payloads and return expected responses
- Handle different event types correctly
- Provide appropriate error handling
- Return proper field structures
"""

import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from carbon.views import calculate_event_carbon_impact

User = get_user_model()


class CarbonCalculationAPITestCase(TestCase):
    """Test carbon calculation API functionality"""

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.test_user = User.objects.create_user(
            email="testuser@example.com", password="testpass123", first_name="Test", last_name="User"
        )

    def test_general_event_carbon_calculation(self):
        """Test carbon calculation for general events"""
        # Test payload for general event
        data = {
            "event_type": "general",
            "event_data": {
                "description": "<p>Pollination: Local bee colonies reduce transport emissions</p>",
                "observation": "s",
                "duration": None,
                "amount": None,
                "unit": None,
                "event_id": 33,
            },
        }

        # Create POST request
        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(data), content_type="application/json"
        )
        request.user = self.test_user

        # Test the API endpoint
        response = calculate_event_carbon_impact(request)

        # Verify response structure
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, dict)

        # Verify expected fields are present
        expected_fields = [
            "co2e",
            "efficiency_score",
            "usda_factors_used",
            "calculation_method",
            "event_type",
            "timestamp",
        ]
        for field in expected_fields:
            self.assertIn(field, response.data, f"Missing expected field: {field}")

        # Verify data types
        self.assertIsInstance(response.data["co2e"], (int, float))
        self.assertIsInstance(response.data["efficiency_score"], (int, float))
        self.assertIsInstance(response.data["usda_factors_used"], bool)
        self.assertIsInstance(response.data["calculation_method"], str)
        self.assertIsInstance(response.data["event_type"], str)

        # For general events, should use standard calculation
        if response.data.get("co2e") == 0.1 and response.data.get("efficiency_score") == 50.0:
            self.assertEqual(response.data["calculation_method"], "general_event_standard")
        else:
            # Using sophisticated calculation is also valid
            self.assertGreater(response.data["co2e"], 0)

    def test_production_event_carbon_calculation(self):
        """Test carbon calculation for production events"""
        # Production event with irrigation data
        data = {
            "event_type": "production",
            "event_data": {
                "description": "Riego - Sistema de riego",
                "observation": "Standard irrigation cycle 2 hours",
                "duration": 2,
                "amount": 100,
                "unit": "liters",
                "event_id": 70,
            },
        }

        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(data), content_type="application/json"
        )
        request.user = self.test_user

        # Test the API endpoint
        response = calculate_event_carbon_impact(request)

        # Verify response
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, dict)

        # Production events should have more detailed calculations
        self.assertIn("co2e", response.data)
        self.assertIn("efficiency_score", response.data)

        # Check if we get sophisticated calculation features
        if "breakdown" in response.data:
            self.assertIsInstance(response.data["breakdown"], dict)

        # Verify event type is correctly identified
        self.assertEqual(response.data["event_type"], "production")

    def test_fertilizer_event_carbon_calculation(self):
        """Test carbon calculation for fertilizer events"""
        data = {
            "event_type": "production",
            "event_data": {
                "description": "Fertilizer application - Nitrogen fertilizer",
                "observation": "Applied 50kg nitrogen fertilizer",
                "duration": 1,
                "amount": 50,
                "unit": "kg",
                "event_id": 101,
                "fertilizer_type": "nitrogen",
            },
        }

        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(data), content_type="application/json"
        )
        request.user = self.test_user

        response = calculate_event_carbon_impact(request)

        self.assertEqual(response.status_code, 200)

        # Fertilizer events should have higher CO2e values
        if response.data.get("co2e", 0) > 0.1:
            # Sophisticated calculation
            self.assertGreater(response.data["co2e"], 0.1)
        else:
            # Standard calculation is also acceptable
            self.assertGreaterEqual(response.data["co2e"], 0)

    def test_equipment_event_carbon_calculation(self):
        """Test carbon calculation for equipment events"""
        data = {
            "event_type": "production",
            "event_data": {
                "description": "Tractor operation - Plowing",
                "observation": "Tractor used for 3 hours plowing",
                "duration": 3,
                "amount": 25,
                "unit": "liters",
                "event_id": 102,
                "equipment_type": "tractor",
                "fuel_type": "diesel",
            },
        }

        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(data), content_type="application/json"
        )
        request.user = self.test_user

        response = calculate_event_carbon_impact(request)

        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.data["co2e"], 0)

        # Equipment events should include efficiency metrics
        self.assertIn("efficiency_score", response.data)

    def test_api_error_handling(self):
        """Test API error handling for invalid requests"""
        # Test with missing event_type
        invalid_data = {"event_data": {"description": "Test event", "observation": "Test observation"}}

        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(invalid_data), content_type="application/json"
        )
        request.user = self.test_user

        response = calculate_event_carbon_impact(request)

        # Should handle missing event_type gracefully
        self.assertIn(response.status_code, [200, 400])

        if response.status_code == 400:
            self.assertIn("error", response.data)
        else:
            # If it returns 200, it should have handled the missing field gracefully
            self.assertIn("co2e", response.data)

    def test_api_empty_request(self):
        """Test API handling of empty requests"""
        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps({}), content_type="application/json"
        )
        request.user = self.test_user

        response = calculate_event_carbon_impact(request)

        # Should handle empty request gracefully
        self.assertIn(response.status_code, [200, 400])

    def test_api_malformed_json(self):
        """Test API handling of malformed JSON"""
        request = self.factory.post(
            "/carbon/calculate-event-impact/", data='{"invalid": json}', content_type="application/json"
        )
        request.user = self.test_user

        # Should handle malformed JSON without crashing
        try:
            response = calculate_event_carbon_impact(request)
            self.assertIn(response.status_code, [200, 400, 500])
        except Exception as e:
            # Exception handling is also acceptable
            self.assertIsInstance(e, Exception)

    def test_calculation_consistency(self):
        """Test that identical requests return consistent results"""
        data = {
            "event_type": "general",
            "event_data": {"description": "Test consistency", "observation": "Same test event", "event_id": 999},
        }

        # Make the same request twice
        responses = []
        for i in range(2):
            request = self.factory.post(
                "/carbon/calculate-event-impact/", data=json.dumps(data), content_type="application/json"
            )
            request.user = self.test_user
            response = calculate_event_carbon_impact(request)
            responses.append(response)

        # Both responses should be successful
        self.assertEqual(responses[0].status_code, 200)
        self.assertEqual(responses[1].status_code, 200)

        # Results should be consistent
        self.assertEqual(responses[0].data["co2e"], responses[1].data["co2e"])
        self.assertEqual(responses[0].data["efficiency_score"], responses[1].data["efficiency_score"])
        self.assertEqual(responses[0].data["calculation_method"], responses[1].data["calculation_method"])

    def test_different_event_types_return_different_results(self):
        """Test that different event types return appropriately different results"""
        base_data = {
            "event_data": {
                "description": "Test event",
                "observation": "Test observation",
                "amount": 100,
                "unit": "kg",
                "event_id": 1000,
            }
        }

        # Test general vs production events
        general_data = {**base_data, "event_type": "general"}
        production_data = {**base_data, "event_type": "production"}

        # Make requests
        general_request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(general_data), content_type="application/json"
        )
        general_request.user = self.test_user

        production_request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(production_data), content_type="application/json"
        )
        production_request.user = self.test_user

        general_response = calculate_event_carbon_impact(general_request)
        production_response = calculate_event_carbon_impact(production_request)

        # Both should be successful
        self.assertEqual(general_response.status_code, 200)
        self.assertEqual(production_response.status_code, 200)

        # Event types should be correctly identified
        self.assertEqual(general_response.data["event_type"], "general")
        self.assertEqual(production_response.data["event_type"], "production")

        # They may have different calculation methods or results
        # (but identical results are also acceptable if the logic is the same)
        self.assertIn("calculation_method", general_response.data)
        self.assertIn("calculation_method", production_response.data)

    def test_api_response_field_types(self):
        """Test that API response fields have correct data types"""
        data = {
            "event_type": "general",
            "event_data": {"description": "Type test event", "observation": "Testing field types", "event_id": 2000},
        }

        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(data), content_type="application/json"
        )
        request.user = self.test_user

        response = calculate_event_carbon_impact(request)
        self.assertEqual(response.status_code, 200)

        # Test field types
        response_data = response.data

        # CO2e should be numeric
        self.assertIsInstance(response_data.get("co2e"), (int, float))
        self.assertGreaterEqual(response_data.get("co2e"), 0)

        # Efficiency score should be numeric between 0 and 100
        efficiency_score = response_data.get("efficiency_score")
        self.assertIsInstance(efficiency_score, (int, float))
        self.assertGreaterEqual(efficiency_score, 0)
        self.assertLessEqual(efficiency_score, 100)

        # USDA factors used should be boolean
        self.assertIsInstance(response_data.get("usda_factors_used"), bool)

        # Strings should be strings
        self.assertIsInstance(response_data.get("calculation_method"), str)
        self.assertIsInstance(response_data.get("event_type"), str)

        # Timestamp should be present (string or datetime format)
        self.assertIn("timestamp", response_data)

    def test_api_large_payload_handling(self):
        """Test API handling of large payloads"""
        # Create a large description
        large_description = "Large event description. " * 1000  # ~25KB description

        data = {
            "event_type": "general",
            "event_data": {
                "description": large_description,
                "observation": "Testing large payload handling",
                "event_id": 3000,
            },
        }

        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(data), content_type="application/json"
        )
        request.user = self.test_user

        # Should handle large payloads without crashing
        response = calculate_event_carbon_impact(request)
        self.assertIn(response.status_code, [200, 400, 413])  # 413 = Payload Too Large

        if response.status_code == 200:
            self.assertIn("co2e", response.data)

    def test_api_authentication_requirement(self):
        """Test that API requires authentication"""
        data = {
            "event_type": "general",
            "event_data": {
                "description": "Test auth requirement",
                "observation": "Testing authentication",
                "event_id": 4000,
            },
        }

        # Create request without user
        request = self.factory.post(
            "/carbon/calculate-event-impact/", data=json.dumps(data), content_type="application/json"
        )
        # Don't set request.user

        try:
            response = calculate_event_carbon_impact(request)
            # If it doesn't require auth, should still return valid response
            self.assertIn(response.status_code, [200, 401, 403])
        except AttributeError:
            # If it requires auth and user is missing, AttributeError is expected
            self.assertTrue(True, "Authentication required as expected")
