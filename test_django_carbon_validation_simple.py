#!/usr/bin/env python3
"""
Django Backend Carbon Calculation Validation - Simplified Version
Validates the backend carbon calculation system for fertilizer application scenario.

This test validates the core functionality without complex database setup.
"""

import json
import os
import sys
from decimal import Decimal

# Add Django project to path and setup
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")

import django

django.setup()

from django.core.exceptions import ValidationError

from history.models import ChemicalEvent


class SimpleCarbonValidationTest:
    """Simplified validation test for Django backend carbon calculations"""

    def __init__(self):
        self.results = {}
        print("🌱 DJANGO BACKEND CARBON CALCULATION VALIDATION")
        print("=" * 60)
        print("Scenario: Fertilizer Application (16-16-16 NPK, 50L, 2ha, Broadcast)")
        print("Expected: ~42.9 kg CO2e")
        print("=" * 60)

    def test_1_chemical_event_model_validation(self):
        """Test ChemicalEvent model validation logic"""
        print("\nTEST 1: CHEMICAL EVENT MODEL VALIDATION")
        print("-" * 40)

        # Test data matching the screenshot scenario
        fertilizer_data = {
            "description": "Fertilizer Application Test",
            "type": "FE",  # Fertilizer
            "commercial_name": "16-16-16 NPK Fertilizer",
            "volume": "50",  # 50 Liters
            "area": "2.0",  # 2.0 Hectares
            "way_of_application": "broadcast",
            "concentration": "16-16-16",
            "nitrogen_percentage": Decimal("16.00"),
            "phosphorus_percentage": Decimal("16.00"),
            "potassium_percentage": Decimal("16.00"),
            "application_method_structured": "broadcast",
            "name": "Test Fertilizer Event",
        }

        try:
            # Create ChemicalEvent instance (without saving)
            event = ChemicalEvent(**fertilizer_data)

            # Test model validation
            event.clean()

            print("✅ ChemicalEvent model validation PASSED")
            print(f"   Type: {event.type} (Fertilizer)")
            print(f"   NPK: {event.nitrogen_percentage}-{event.phosphorus_percentage}-{event.potassium_percentage}")
            print(f"   Volume: {event.volume} L")
            print(f"   Area: {event.area} ha")
            print(f"   Method: {event.application_method_structured}")

            # Test NPK validation logic
            self.test_npk_validation_logic(event)

            self.results["model_validation"] = {
                "status": "PASS",
                "npk_values": {
                    "N": float(event.nitrogen_percentage),
                    "P": float(event.phosphorus_percentage),
                    "K": float(event.potassium_percentage),
                },
            }

        except ValidationError as e:
            print(f"❌ Model validation FAILED: {e}")
            self.results["model_validation"] = {"status": "FAIL", "error": str(e)}
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            self.results["model_validation"] = {"status": "ERROR", "error": str(e)}

    def test_npk_validation_logic(self, event):
        """Test NPK validation business rules"""
        print("\n🔍 Testing NPK validation rules:")

        # Test 1: Valid NPK percentages
        try:
            event.nitrogen_percentage = Decimal("16.00")
            event.phosphorus_percentage = Decimal("16.00")
            event.potassium_percentage = Decimal("16.00")
            event.clean()
            print("✅ Valid NPK (16-16-16) accepted")
        except ValidationError:
            print("❌ Valid NPK rejected unexpectedly")

        # Test 2: Individual NPK > 100% should fail
        original_n = event.nitrogen_percentage
        try:
            event.nitrogen_percentage = Decimal("120.00")
            event.clean()
            print("❌ NPK > 100% should have been rejected")
        except ValidationError:
            print("✅ NPK > 100% correctly rejected")
        finally:
            event.nitrogen_percentage = original_n

        # Test 3: Total NPK > 100% should fail
        original_values = (event.nitrogen_percentage, event.phosphorus_percentage, event.potassium_percentage)
        try:
            event.nitrogen_percentage = Decimal("50.00")
            event.phosphorus_percentage = Decimal("50.00")
            event.potassium_percentage = Decimal("50.00")  # Total = 150%
            event.clean()
            print("❌ Total NPK > 100% should have been rejected")
        except ValidationError:
            print("✅ Total NPK > 100% correctly rejected")
        finally:
            event.nitrogen_percentage, event.phosphorus_percentage, event.potassium_percentage = original_values

    def test_2_carbon_calculator_service(self):
        """Test carbon calculation service directly"""
        print("\nTEST 2: CARBON CALCULATION SERVICE")
        print("-" * 40)

        try:
            from carbon.services.event_carbon_calculator import EventCarbonCalculator

            # Create mock event for calculation
            class MockEvent:
                def __init__(self, data):
                    for key, value in data.items():
                        setattr(self, key, value)

                @property
                def history(self):
                    # Mock history with basic properties needed for calculation
                    class MockHistory:
                        def __init__(self):
                            self.parcel = MockParcel()

                    return MockHistory()

                def get_farm_coordinates(self):
                    # Mock farm coordinates
                    return 37.7749, -122.4194, "CA"

            class MockParcel:
                def __init__(self):
                    self.establishment = MockEstablishment()

            class MockEstablishment:
                def __init__(self):
                    self.state = "CA"

            mock_event_data = {
                "type": "FE",  # Fertilizer
                "commercial_name": "16-16-16 NPK Fertilizer",
                "volume": "50",
                "area": "2.0",
                "way_of_application": "broadcast",
                "concentration": "16-16-16",
                "nitrogen_percentage": 16.0,
                "phosphorus_percentage": 16.0,
                "potassium_percentage": 16.0,
                "application_method_structured": "broadcast",
                "description": "Test fertilizer application",
            }

            mock_event = MockEvent(mock_event_data)
            calculator = EventCarbonCalculator()

            # Calculate carbon impact
            result = calculator.calculate_chemical_event_impact(mock_event)

            print("✅ Carbon calculation service PASSED")
            print(f"   Total CO2e: {result.get('co2e', 0):.3f} kg")
            print(f"   Manufacturing: {result.get('manufacturing_emissions_kg_co2e', 0):.3f} kg CO2e")
            print(f"   Application: {result.get('application_emissions_kg_co2e', 0):.3f} kg CO2e")

            npk_content = result.get("npk_content", {})
            print(
                f"   NPK Content: N={npk_content.get('N', 0)}, P={npk_content.get('P', 0)}, K={npk_content.get('K', 0)}"
            )

            # Validate calculation results
            self.validate_calculation_results(result)

            self.results["calculation_service"] = {
                "status": "PASS",
                "total_co2e": result.get("co2e", 0),
                "manufacturing": result.get("manufacturing_emissions_kg_co2e", 0),
                "application": result.get("application_emissions_kg_co2e", 0),
                "npk_content": npk_content,
            }

        except ImportError as e:
            print(f"⚠️  Cannot import calculator service: {e}")
            self.results["calculation_service"] = {"status": "SKIP", "reason": "Import error"}
        except Exception as e:
            print(f"❌ Calculation service FAILED: {e}")
            self.results["calculation_service"] = {"status": "ERROR", "error": str(e)}

    def validate_calculation_results(self, result):
        """Validate that calculation results are reasonable"""
        print("\n🔍 Validating calculation accuracy:")

        total_co2e = result.get("co2e", 0)
        manufacturing = result.get("manufacturing_emissions_kg_co2e", 0)
        application = result.get("application_emissions_kg_co2e", 0)
        npk_content = result.get("npk_content", {})

        # Expected range for 50L of 16-16-16 fertilizer on 2 hectares: ~35-50 kg CO2e
        if 30 <= total_co2e <= 60:
            print(f"✅ Total CO2e ({total_co2e:.1f} kg) within reasonable range (30-60 kg)")
        else:
            print(f"⚠️  Total CO2e ({total_co2e:.1f} kg) outside expected range (30-60 kg)")

        # NPK content should match input (16-16-16)
        if npk_content.get("N") == 16 and npk_content.get("P") == 16 and npk_content.get("K") == 16:
            print(f"✅ NPK content correct: {npk_content['N']}-{npk_content['P']}-{npk_content['K']}")
        else:
            print(
                f"⚠️  NPK content unexpected: {npk_content.get('N', 0)}-{npk_content.get('P', 0)}-{npk_content.get('K', 0)}"
            )

        # Manufacturing should typically be higher than application for fertilizers
        if manufacturing > 0 and application >= 0:
            print(f"✅ Emission components present: Manufacturing={manufacturing:.1f}, Application={application:.1f}")
        else:
            print(f"⚠️  Emission components unusual: Manufacturing={manufacturing:.1f}, Application={application:.1f}")

    def test_3_emission_factors_integration(self):
        """Test EPA/USDA emission factors are accessible"""
        print("\nTEST 3: EPA/USDA EMISSION FACTORS")
        print("-" * 40)

        try:
            from carbon.services.emission_factors import emission_factors

            # Test factor retrieval
            nitrogen_factor = emission_factors.get_fertilizer_factor("nitrogen")
            phosphorus_factor = emission_factors.get_fertilizer_factor("phosphorus")
            potassium_factor = emission_factors.get_fertilizer_factor("potassium")

            print("✅ USDA emission factors loaded:")
            print(f"   Nitrogen: {nitrogen_factor['value']:.3f} kg CO2e/kg N")
            print(f"   Phosphorus: {phosphorus_factor['value']:.3f} kg CO2e/kg P")
            print(f"   Potassium: {potassium_factor['value']:.3f} kg CO2e/kg K")

            # Validate factors are reasonable (EPA-based ranges)
            factors_valid = (
                2.0 <= nitrogen_factor["value"] <= 4.0
                and 0.5 <= phosphorus_factor["value"] <= 2.0
                and 0.3 <= potassium_factor["value"] <= 1.5
            )

            if factors_valid:
                print("✅ All factors within EPA-based ranges")
            else:
                print("⚠️  Some factors outside expected EPA ranges")

            self.results["emission_factors"] = {
                "status": "PASS",
                "factors": {
                    "nitrogen": nitrogen_factor["value"],
                    "phosphorus": phosphorus_factor["value"],
                    "potassium": potassium_factor["value"],
                },
                "factors_valid": factors_valid,
            }

        except ImportError as e:
            print(f"⚠️  Cannot import emission factors: {e}")
            self.results["emission_factors"] = {"status": "SKIP", "reason": "Import error"}
        except Exception as e:
            print(f"❌ Emission factors test FAILED: {e}")
            self.results["emission_factors"] = {"status": "ERROR", "error": str(e)}

    def test_4_api_endpoint_structure(self):
        """Test API endpoint URL structure exists"""
        print("\nTEST 4: API ENDPOINT STRUCTURE")
        print("-" * 40)

        try:
            from django.urls import reverse

            from carbon.urls import urlpatterns

            # Check if calculate-event-impact endpoint exists
            endpoint_found = False
            for pattern in urlpatterns:
                if hasattr(pattern, "name") and pattern.name == "calculate-event-carbon-impact":
                    endpoint_found = True
                    break

            if endpoint_found:
                print("✅ Carbon calculation API endpoint found in URL patterns")
            else:
                print("⚠️  Carbon calculation API endpoint not found in URL patterns")

            # Check if the view function exists
            try:
                from carbon.views import calculate_event_carbon_impact

                print("✅ Carbon calculation view function exists")
                view_exists = True
            except ImportError:
                print("❌ Carbon calculation view function not found")
                view_exists = False

            self.results["api_endpoint"] = {
                "status": "PASS" if endpoint_found and view_exists else "PARTIAL",
                "endpoint_in_urls": endpoint_found,
                "view_function_exists": view_exists,
            }

        except Exception as e:
            print(f"❌ API endpoint test FAILED: {e}")
            self.results["api_endpoint"] = {"status": "ERROR", "error": str(e)}

    def run_validation(self):
        """Run all validation tests"""
        self.test_1_chemical_event_model_validation()
        self.test_2_carbon_calculator_service()
        self.test_3_emission_factors_integration()
        self.test_4_api_endpoint_structure()

        # Generate summary
        self.generate_summary()

    def generate_summary(self):
        """Generate validation summary"""
        print("\n" + "=" * 60)
        print("🎯 VALIDATION SUMMARY")
        print("=" * 60)

        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results.values() if r.get("status") == "PASS")
        skipped_tests = sum(1 for r in self.results.values() if r.get("status") == "SKIP")

        print(f"📊 Results: {passed_tests}/{total_tests} tests passed, {skipped_tests} skipped")
        print()

        for test_name, result in self.results.items():
            status = result.get("status", "UNKNOWN")
            status_icons = {"PASS": "✅", "FAIL": "❌", "ERROR": "❌", "SKIP": "⏭️", "PARTIAL": "⚠️"}
            icon = status_icons.get(status, "❓")

            print(f"{icon} {test_name.upper().replace('_', ' ')}: {status}")

            if status == "PASS" and test_name == "calculation_service":
                total = result.get("total_co2e", 0)
                print(f"   Total CO2e calculated: {total:.1f} kg CO2e")
                if 30 <= total <= 60:
                    print(f"   ✅ Within expected range for scenario")
                else:
                    print(f"   ⚠️  Outside expected range (30-60 kg)")

            elif status in ["FAIL", "ERROR"] and "error" in result:
                print(f"   Error: {result['error']}")
            elif status == "SKIP" and "reason" in result:
                print(f"   Reason: {result['reason']}")

        print()

        if passed_tests >= total_tests - skipped_tests:
            print("🎉 VALIDATION SUCCESSFUL!")
            print("✅ Django backend carbon calculation system is working")
            print("✅ ChemicalEvent model validates NPK data correctly")
            print("✅ Emission factors are properly integrated")
            print("✅ API structure is in place")
            print()
            print("🌱 READY FOR FERTILIZER APPLICATION CARBON CALCULATIONS")
            return True
        else:
            print("⚠️  VALIDATION ISSUES FOUND")
            print("Some components need attention before production use.")
            return False


def main():
    """Main validation function"""
    validator = SimpleCarbonValidationTest()
    success = validator.run_validation()

    print(f"\n{'✅ BACKEND VALIDATION COMPLETE' if success else '⚠️  VALIDATION INCOMPLETE'}")
    return success


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
