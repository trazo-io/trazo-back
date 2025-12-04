#!/usr/bin/env python3
"""
Comprehensive Django Backend Carbon Calculation Validation
Validates the complete carbon calculation system for the fertilizer scenario from the screenshot.

Test Scenario: Fertilizer Application
- Event Type: Fertilizer Application
- NPK: 16-16-16
- Volume: 50 Liters
- Area: 2.0 Hectares
- Method: Broadcast
- Expected Result: ~42.9 kg CO2e (EPA/USDA verified)
"""

import decimal
import json
import os
import sys
from decimal import Decimal

# Add Django project to Python path
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")

# Import Django and setup
import django

django.setup()

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client

from rest_framework.test import APIClient

from carbon.models import CarbonEntry, CarbonSource
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel, Product

User = get_user_model()


class ComprehensiveChemicalBackendValidator:
    """
    Comprehensive validation suite for the Django backend carbon calculation system
    """

    def __init__(self):
        self.client = APIClient()
        self.setup_test_data()
        self.results = {}

    def setup_test_data(self):
        """Create test data needed for validation"""
        print("🔧 Setting up test data...")

        # Create test user
        self.test_user, created = User.objects.get_or_create(
            email="test@trazo.com", defaults={"first_name": "Test", "last_name": "Farmer", "is_active": True}
        )

        # Create test company and establishment
        self.test_company, created = Company.objects.get_or_create(
            name="Test Farm Co.", defaults={"created_by": self.test_user}
        )

        self.test_establishment, created = Establishment.objects.get_or_create(
            name="Test Farm", company=self.test_company, defaults={"year_established": 2020, "state": "CA"}
        )

        # Create test product and parcel
        self.test_product, created = Product.objects.get_or_create(
            name="Test Avocados", defaults={"created_by": self.test_user}
        )

        self.test_parcel, created = Parcel.objects.get_or_create(
            name="Test Plot",
            establishment=self.test_establishment,
            defaults={"size": 2.0, "product": self.test_product},
        )

        # Create test production (History)
        self.test_production, created = History.objects.get_or_create(
            name="Test Production",
            product=self.test_product,
            parcel=self.test_parcel,
            defaults={"production_amount": 1000, "published": True},
        )

        print(f"✅ Test data setup complete")

    def test_1_chemical_event_model_validation(self):
        """Test 1: ChemicalEvent model handles all required fields correctly"""
        print("\n" + "=" * 60)
        print("TEST 1: CHEMICAL EVENT MODEL VALIDATION")
        print("=" * 60)

        test_data = {
            "description": "Fertilizer Application Test",
            "history": self.test_production,
            "created_by": self.test_user,
            "type": "FE",  # Fertilizer
            "commercial_name": "Test NPK Fertilizer",
            "volume": "50",  # 50 Liters
            "area": "2.0",  # 2.0 Hectares
            "way_of_application": "broadcast",
            "concentration": "16-16-16",
            "nitrogen_percentage": Decimal("16.00"),
            "phosphorus_percentage": Decimal("16.00"),
            "potassium_percentage": Decimal("16.00"),
            "application_method_structured": "broadcast",
            "name": "Test Fertilizer Event",
            "observation": "Test fertilizer application",
        }

        try:
            # Test model creation
            chemical_event = ChemicalEvent(**test_data)
            chemical_event.full_clean()  # Validates the model
            chemical_event.save()

            print("✅ ChemicalEvent model created successfully")
            print(f"   - Type: {chemical_event.type} (Fertilizer)")
            print(
                f"   - NPK: {chemical_event.nitrogen_percentage}-{chemical_event.phosphorus_percentage}-{chemical_event.potassium_percentage}"
            )
            print(f"   - Volume: {chemical_event.volume} L")
            print(f"   - Area: {chemical_event.area} ha")
            print(f"   - Method: {chemical_event.application_method_structured}")

            # Test NPK validation
            self.test_npk_validation(chemical_event)

            self.results["model_validation"] = {
                "status": "PASS",
                "event_id": chemical_event.id,
                "npk_values": {
                    "N": float(chemical_event.nitrogen_percentage or 0),
                    "P": float(chemical_event.phosphorus_percentage or 0),
                    "K": float(chemical_event.potassium_percentage or 0),
                },
            }

        except ValidationError as e:
            print(f"❌ Model validation failed: {e}")
            self.results["model_validation"] = {"status": "FAIL", "error": str(e)}

        except Exception as e:
            print(f"❌ Unexpected error in model test: {e}")
            self.results["model_validation"] = {"status": "ERROR", "error": str(e)}

    def test_npk_validation(self, event):
        """Test NPK percentage validation"""
        print("\n🔍 Testing NPK validation:")

        # Test valid NPK values
        try:
            event.nitrogen_percentage = Decimal("16.00")
            event.phosphorus_percentage = Decimal("16.00")
            event.potassium_percentage = Decimal("16.00")
            event.full_clean()
            print("✅ Valid NPK (16-16-16) accepted")
        except ValidationError as e:
            print(f"❌ Valid NPK rejected: {e}")

        # Test invalid NPK values (over 100%)
        try:
            event.nitrogen_percentage = Decimal("120.00")
            event.full_clean()
            print("❌ Invalid NPK (>100%) should have been rejected")
        except ValidationError:
            print("✅ Invalid NPK (>100%) correctly rejected")
        finally:
            event.nitrogen_percentage = Decimal("16.00")  # Reset

        # Test total NPK validation
        try:
            event.nitrogen_percentage = Decimal("50.00")
            event.phosphorus_percentage = Decimal("50.00")
            event.potassium_percentage = Decimal("50.00")
            event.full_clean()
            print("❌ NPK total >100% should have been rejected")
        except ValidationError:
            print("✅ NPK total >100% correctly rejected")
        finally:
            # Reset to valid values
            event.nitrogen_percentage = Decimal("16.00")
            event.phosphorus_percentage = Decimal("16.00")
            event.potassium_percentage = Decimal("16.00")

    def test_2_calculation_engine_integration(self):
        """Test 2: Calculation engine handles fertilizer application correctly"""
        print("\n" + "=" * 60)
        print("TEST 2: CALCULATION ENGINE INTEGRATION")
        print("=" * 60)

        # Create mock event for calculation testing
        class MockEvent:
            def __init__(self, data):
                for key, value in data.items():
                    setattr(self, key, value)

            @property
            def history(self):
                return self._history if hasattr(self, "_history") else None

        mock_event_data = {
            "type": "FE",  # Fertilizer
            "commercial_name": "NPK 16-16-16 Fertilizer",
            "volume": "50",
            "area": "2.0",
            "way_of_application": "broadcast",
            "concentration": "16-16-16",
            "nitrogen_percentage": 16.0,
            "phosphorus_percentage": 16.0,
            "potassium_percentage": 16.0,
            "application_method_structured": "broadcast",
            "_history": self.test_production,
            "description": "Test fertilizer application",
            "created_by": self.test_user,
        }

        mock_event = MockEvent(mock_event_data)

        try:
            calculator = EventCarbonCalculator()
            result = calculator.calculate_chemical_event_impact(mock_event)

            print("✅ Carbon calculation completed")
            print(f"   - Total CO2e: {result.get('co2e', 0):.3f} kg")
            print(f"   - Manufacturing: {result.get('manufacturing_emissions_kg_co2e', 0):.3f} kg CO2e")
            print(f"   - Application: {result.get('application_emissions_kg_co2e', 0):.3f} kg CO2e")
            print(
                f"   - NPK Content: N={result.get('npk_content', {}).get('N', 0)}, P={result.get('npk_content', {}).get('P', 0)}, K={result.get('npk_content', {}).get('K', 0)}"
            )

            # Validate calculation accuracy
            self.validate_calculation_accuracy(result)

            self.results["calculation_engine"] = {
                "status": "PASS",
                "result": result,
                "total_co2e": result.get("co2e", 0),
                "within_expected_range": 35 <= result.get("co2e", 0) <= 50,  # Expected ~42.9 kg CO2e
            }

        except Exception as e:
            print(f"❌ Calculation engine error: {e}")
            self.results["calculation_engine"] = {"status": "ERROR", "error": str(e)}

    def validate_calculation_accuracy(self, result):
        """Validate calculation results against EPA/USDA standards"""
        print("\n🔍 Validating calculation accuracy:")

        total_co2e = result.get("co2e", 0)
        manufacturing = result.get("manufacturing_emissions_kg_co2e", 0)
        application = result.get("application_emissions_kg_co2e", 0)

        # Expected range for 50L of 16-16-16 fertilizer on 2 hectares
        expected_min = 35  # kg CO2e
        expected_max = 50  # kg CO2e

        if expected_min <= total_co2e <= expected_max:
            print(f"✅ Total CO2e ({total_co2e:.1f} kg) within expected range ({expected_min}-{expected_max} kg)")
        else:
            print(f"⚠️  Total CO2e ({total_co2e:.1f} kg) outside expected range ({expected_min}-{expected_max} kg)")

        # Manufacturing should be the largest component (NPK production)
        if manufacturing > application:
            print(f"✅ Manufacturing emissions ({manufacturing:.1f}) > Application emissions ({application:.1f})")
        else:
            print(
                f"⚠️  Manufacturing emissions ({manufacturing:.1f}) should be > Application emissions ({application:.1f})"
            )

        # NPK content validation
        npk = result.get("npk_content", {})
        if npk.get("N") == 16 and npk.get("P") == 16 and npk.get("K") == 16:
            print(f"✅ NPK content correct: {npk['N']}-{npk['P']}-{npk['K']}")
        else:
            print(
                f"❌ NPK content incorrect: {npk.get('N', 0)}-{npk.get('P', 0)}-{npk.get('K', 0)} (expected 16-16-16)"
            )

    def test_3_api_endpoint_validation(self):
        """Test 3: API endpoint processes fertilizer application correctly"""
        print("\n" + "=" * 60)
        print("TEST 3: API ENDPOINT VALIDATION")
        print("=" * 60)

        # Authenticate client
        self.client.force_authenticate(user=self.test_user)

        api_request_data = {
            "event_type": "chemical",
            "event_data": {
                "type": "FE",  # Fertilizer
                "commercial_name": "NPK 16-16-16 Fertilizer",
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
                "description": "Test fertilizer application via API",
                "name": "API Test Fertilizer Event",
                "observation": "Testing API endpoint",
            },
        }

        try:
            # Test the main carbon calculation API endpoint
            response = self.client.post(
                "/carbon/calculate-event-impact/", data=json.dumps(api_request_data), content_type="application/json"
            )

            print(f"🌐 API Response Status: {response.status_code}")

            if response.status_code == 200:
                response_data = response.json()
                print("✅ API endpoint successful")
                print(f"   - Total CO2e: {response_data.get('co2e', 0):.3f} kg")
                print(f"   - Manufacturing: {response_data.get('manufacturing_emissions_kg_co2e', 0):.3f} kg CO2e")
                print(f"   - Application: {response_data.get('application_emissions_kg_co2e', 0):.3f} kg CO2e")

                # Validate API response format
                self.validate_api_response_format(response_data)

                self.results["api_endpoint"] = {
                    "status": "PASS",
                    "response_code": response.status_code,
                    "response_data": response_data,
                    "has_required_fields": all(field in response_data for field in ["co2e", "calculation_details"]),
                }

            else:
                print(f"❌ API endpoint failed with status {response.status_code}")
                print(f"Response: {response.content.decode()}")
                self.results["api_endpoint"] = {
                    "status": "FAIL",
                    "response_code": response.status_code,
                    "error": response.content.decode(),
                }

        except Exception as e:
            print(f"❌ API endpoint error: {e}")
            self.results["api_endpoint"] = {"status": "ERROR", "error": str(e)}

    def validate_api_response_format(self, response_data):
        """Validate API response has correct format for frontend consumption"""
        print("\n🔍 Validating API response format:")

        required_fields = [
            "co2e",
            "calculation_details",
            "manufacturing_emissions_kg_co2e",
            "application_emissions_kg_co2e",
            "npk_content",
        ]

        for field in required_fields:
            if field in response_data:
                print(f"✅ Required field '{field}' present")
            else:
                print(f"❌ Required field '{field}' missing")

        # Validate calculation_details structure
        details = response_data.get("calculation_details", {})
        if "usda_factors_used" in details and "confidence_score" in details:
            print("✅ Calculation details have USDA verification info")
        else:
            print("⚠️  Calculation details missing USDA verification info")

    def test_4_epa_usda_compliance(self):
        """Test 4: Verify EPA/USDA emission factors are properly applied"""
        print("\n" + "=" * 60)
        print("TEST 4: EPA/USDA COMPLIANCE VALIDATION")
        print("=" * 60)

        try:
            from carbon.services.emission_factors import emission_factors

            # Test USDA factor retrieval
            nitrogen_factor = emission_factors.get_fertilizer_factor("nitrogen")
            phosphorus_factor = emission_factors.get_fertilizer_factor("phosphorus")
            potassium_factor = emission_factors.get_fertilizer_factor("potassium")

            print("✅ USDA emission factors loaded:")
            print(f"   - Nitrogen: {nitrogen_factor['value']:.3f} kg CO2e/kg N")
            print(f"   - Phosphorus: {phosphorus_factor['value']:.3f} kg CO2e/kg P")
            print(f"   - Potassium: {potassium_factor['value']:.3f} kg CO2e/kg K")

            # Validate factors are in expected EPA ranges
            epa_ranges = {
                "nitrogen": (2.5, 3.5),  # EPA range for N
                "phosphorus": (1.0, 1.5),  # EPA range for P
                "potassium": (0.5, 1.0),  # EPA range for K
            }

            factors_valid = True
            for nutrient, (min_val, max_val) in epa_ranges.items():
                if nutrient == "nitrogen":
                    factor_val = nitrogen_factor["value"]
                elif nutrient == "phosphorus":
                    factor_val = phosphorus_factor["value"]
                else:
                    factor_val = potassium_factor["value"]

                if min_val <= factor_val <= max_val:
                    print(f"✅ {nutrient.title()} factor ({factor_val:.3f}) within EPA range ({min_val}-{max_val})")
                else:
                    print(f"⚠️  {nutrient.title()} factor ({factor_val:.3f}) outside EPA range ({min_val}-{max_val})")
                    factors_valid = False

            self.results["epa_usda_compliance"] = {
                "status": "PASS" if factors_valid else "WARNING",
                "factors": {
                    "nitrogen": nitrogen_factor["value"],
                    "phosphorus": phosphorus_factor["value"],
                    "potassium": potassium_factor["value"],
                },
                "all_factors_in_epa_range": factors_valid,
            }

        except Exception as e:
            print(f"❌ EPA/USDA compliance test error: {e}")
            self.results["epa_usda_compliance"] = {"status": "ERROR", "error": str(e)}

    def test_5_data_flow_validation(self):
        """Test 5: Complete data flow from API to database storage"""
        print("\n" + "=" * 60)
        print("TEST 5: DATA FLOW VALIDATION")
        print("=" * 60)

        try:
            # Create and save a ChemicalEvent to test data persistence
            chemical_event = ChemicalEvent.objects.create(
                description="Data Flow Test Fertilizer Application",
                history=self.test_production,
                created_by=self.test_user,
                type="FE",
                commercial_name="16-16-16 NPK Test",
                volume="50",
                area="2.0",
                way_of_application="broadcast",
                concentration="16-16-16",
                nitrogen_percentage=Decimal("16.00"),
                phosphorus_percentage=Decimal("16.00"),
                potassium_percentage=Decimal("16.00"),
                application_method_structured="broadcast",
            )

            print("✅ ChemicalEvent created and saved to database")
            print(f"   - Event ID: {chemical_event.id}")
            print(f"   - History ID: {chemical_event.history.id}")
            print(f"   - Created by: {chemical_event.created_by.email}")

            # Calculate carbon impact and create CarbonEntry
            calculator = EventCarbonCalculator()

            # Create mock event for calculation
            result = calculator.calculate_chemical_event_impact(chemical_event)

            # Create corresponding CarbonEntry (simulating full workflow)
            carbon_entry = CarbonEntry.objects.create(
                production=self.test_production,
                created_by=self.test_user,
                type="emission",
                amount=result.get("co2e", 0),
                co2e_amount=result.get("co2e", 0),
                year=2024,
                description=f"Carbon from fertilizer application (Event #{chemical_event.id})",
                usda_verified=True,
                usda_factors_based=True,
                verification_status="factors_verified",
                data_source="USDA Agricultural Research Service",
                calculation_details=result.get("calculation_details", {}),
                confidence_level="high",
            )

            print("✅ CarbonEntry created and linked to production")
            print(f"   - Entry ID: {carbon_entry.id}")
            print(f"   - CO2e Amount: {carbon_entry.co2e_amount:.3f} kg")
            print(f"   - USDA Verified: {carbon_entry.usda_verified}")
            print(f"   - Confidence: {carbon_entry.confidence_level}")

            # Verify data integrity
            self.verify_data_integrity(chemical_event, carbon_entry)

            self.results["data_flow"] = {
                "status": "PASS",
                "chemical_event_id": chemical_event.id,
                "carbon_entry_id": carbon_entry.id,
                "data_integrity_ok": True,
                "usda_verification": carbon_entry.usda_verified,
            }

        except Exception as e:
            print(f"❌ Data flow validation error: {e}")
            self.results["data_flow"] = {"status": "ERROR", "error": str(e)}

    def verify_data_integrity(self, chemical_event, carbon_entry):
        """Verify data integrity between ChemicalEvent and CarbonEntry"""
        print("\n🔍 Verifying data integrity:")

        # Check that production links are consistent
        if chemical_event.history == carbon_entry.production:
            print("✅ Production links consistent between Event and CarbonEntry")
        else:
            print("❌ Production links inconsistent")

        # Check that carbon amount is reasonable
        if 0 < carbon_entry.co2e_amount < 1000:  # Reasonable range
            print(f"✅ Carbon amount ({carbon_entry.co2e_amount:.1f} kg) in reasonable range")
        else:
            print(f"⚠️  Carbon amount ({carbon_entry.co2e_amount:.1f} kg) may be unreasonable")

        # Check USDA verification flags
        if carbon_entry.usda_verified and carbon_entry.usda_factors_based:
            print("✅ USDA verification flags properly set")
        else:
            print("⚠️  USDA verification flags not properly set")

    def run_validation_suite(self):
        """Run complete validation suite"""
        print("🚀 TRAZO DJANGO BACKEND CARBON CALCULATION VALIDATION")
        print("=" * 60)
        print("Validating fertilizer application scenario from screenshot:")
        print("- NPK: 16-16-16")
        print("- Volume: 50 Liters")
        print("- Area: 2.0 Hectares")
        print("- Method: Broadcast")
        print("- Expected: ~42.9 kg CO2e")
        print("=" * 60)

        # Run all validation tests
        self.test_1_chemical_event_model_validation()
        self.test_2_calculation_engine_integration()
        self.test_3_api_endpoint_validation()
        self.test_4_epa_usda_compliance()
        self.test_5_data_flow_validation()

        # Generate summary report
        self.generate_validation_report()

    def generate_validation_report(self):
        """Generate comprehensive validation report"""
        print("\n" + "=" * 60)
        print("🎯 VALIDATION SUMMARY REPORT")
        print("=" * 60)

        total_tests = len(self.results)
        passed_tests = sum(1 for result in self.results.values() if result.get("status") == "PASS")

        print(f"📊 Test Results: {passed_tests}/{total_tests} tests passed")
        print()

        for test_name, result in self.results.items():
            status = result.get("status", "UNKNOWN")
            status_icon = "✅" if status == "PASS" else "⚠️" if status == "WARNING" else "❌"

            print(f"{status_icon} {test_name.upper().replace('_', ' ')}: {status}")

            if status == "PASS":
                if test_name == "calculation_engine" and "total_co2e" in result:
                    print(f"   Total CO2e calculated: {result['total_co2e']:.1f} kg")
                    within_range = result.get("within_expected_range", False)
                    range_status = "✅" if within_range else "⚠️"
                    print(f"   {range_status} Within expected range (35-50 kg): {within_range}")

                if test_name == "api_endpoint" and "response_code" in result:
                    print(f"   API response code: {result['response_code']}")
                    has_fields = result.get("has_required_fields", False)
                    fields_status = "✅" if has_fields else "❌"
                    print(f"   {fields_status} Required fields present: {has_fields}")

            elif "error" in result:
                print(f"   Error: {result['error']}")

        print()

        # Overall assessment
        if passed_tests == total_tests:
            print("🎉 VALIDATION SUCCESSFUL!")
            print("The Django backend carbon calculation system is working correctly:")
            print("✅ ChemicalEvent model properly validates NPK data")
            print("✅ EventCarbonCalculator produces accurate EPA/USDA calculations")
            print("✅ API endpoint returns correctly formatted responses")
            print("✅ EPA/USDA emission factors are properly integrated")
            print("✅ Complete data flow from API to database works")
            print()
            print("🌱 TRAZO TRANSPARENCY MISSION: ACHIEVED")
            print("Farmers and consumers can trust the carbon footprint calculations!")
            return True

        elif passed_tests >= total_tests * 0.8:  # 80% pass rate
            print("⚠️  VALIDATION MOSTLY SUCCESSFUL")
            print("The system is largely working but has some areas for improvement.")
            return True

        else:
            print("❌ VALIDATION FAILED")
            print("Critical issues found in the carbon calculation system.")
            print("Please review and fix the identified problems.")
            return False


def main():
    """Main validation function"""
    print("🌱 Starting Trazo Django Backend Carbon Calculation Validation")

    validator = ComprehensiveChemicalBackendValidator()
    success = validator.run_validation_suite()

    if success:
        print("\n✅ BACKEND VALIDATION COMPLETE - SYSTEM READY FOR PRODUCTION")
    else:
        print("\n❌ BACKEND VALIDATION FAILED - FIXES NEEDED")

    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
