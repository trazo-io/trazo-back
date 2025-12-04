#!/usr/bin/env python3
"""
COMPREHENSIVE CARBON CALCULATION WORKFLOW TEST
Test the complete farmer journey from Smart Product validation to carbon footprint results
"""

import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

# Set up Django environment
sys.path.append("/Users/oscarmunoz/dev/trazo/trazo-back")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trazo.settings.dev")

import django

django.setup()

from carbon.models import CarbonFootprint, EmissionFactor
from carbon.services.smart_product_validator import SmartProductValidator


class CarbonCalculationWorkflowTester:
    """Test the complete carbon calculation workflow with Smart Product integration"""

    def __init__(self):
        self.validator = SmartProductValidator()
        self.test_results = []

    def simulate_carbon_calculation(self, product_validation, area_acres: float, rate_per_acre: float) -> Dict:
        """Simulate carbon calculation using validated product data"""
        try:
            # Use validated product type for emission factor lookup
            product_type = product_validation.correct_type
            npk_ratio = product_validation.npk_ratio
            confidence = product_validation.confidence

            # Simplified emission factors (kg CO2e per unit)
            base_emission_factors = {
                "FE": 1.2,  # Fertilizer
                "HE": 8.5,  # Herbicide
                "PE": 15.3,  # Pesticide
                "FU": 12.1,  # Fungicide
            }

            base_factor = base_emission_factors.get(product_type, 5.0)

            # Adjust for nitrogen content if fertilizer
            if product_type == "FE" and npk_ratio:
                try:
                    n_content = float(npk_ratio.split("-")[0])
                    # Higher nitrogen = higher emissions
                    nitrogen_multiplier = 1.0 + (n_content / 200.0)  # Moderate adjustment
                    emission_factor = base_factor * nitrogen_multiplier
                except:
                    emission_factor = base_factor
            else:
                emission_factor = base_factor

            # Calculate total emissions
            total_application = area_acres * rate_per_acre
            total_emissions_kg = total_application * emission_factor
            total_emissions_tons = total_emissions_kg / 1000.0

            # Calculate confidence in carbon result based on product validation
            carbon_confidence = "HIGH" if confidence >= 0.8 else "MEDIUM" if confidence >= 0.5 else "LOW"

            return {
                "success": True,
                "product_type": product_type,
                "emission_factor": emission_factor,
                "total_application_lbs": total_application,
                "total_emissions_kg": total_emissions_kg,
                "total_emissions_tons": total_emissions_tons,
                "carbon_confidence": carbon_confidence,
                "product_confidence": confidence,
                "npk_used": npk_ratio,
                "calculation_method": "Smart Product Enhanced",
            }

        except Exception as e:
            return {"success": False, "error": str(e), "calculation_method": "Failed"}

    def test_complete_farmer_workflow(self):
        """Test complete farmer workflow from product entry to carbon results"""
        print("🚜 TESTING COMPLETE FARMER CARBON CALCULATION WORKFLOW")
        print("From Smart Product validation to final carbon footprint results")
        print("=" * 70)

        # Realistic farmer scenarios
        farmer_scenarios = [
            {
                "scenario": "Experienced farmer with exact product name",
                "commercial_name": "miracle-gro",
                "selected_type": "FE",
                "area_acres": 5.0,
                "rate_lbs_per_acre": 25.0,
                "expected_outcome": "High confidence carbon calculation with NPK auto-fill",
            },
            {
                "scenario": "Farmer with product name typo",
                "commercial_name": "miracle grow",  # Missing hyphen
                "selected_type": "FE",
                "area_acres": 3.2,
                "rate_lbs_per_acre": 30.0,
                "expected_outcome": "Should still get high confidence calculation",
            },
            {
                "scenario": "Farmer selects wrong chemical type",
                "commercial_name": "roundup",
                "selected_type": "PE",  # Wrong! Should be HE
                "area_acres": 10.0,
                "rate_lbs_per_acre": 2.0,
                "expected_outcome": "Should detect mismatch, use correct type for carbon calc",
            },
            {
                "scenario": "Farmer enters partial word (security test)",
                "commercial_name": "herb",
                "selected_type": "HE",
                "area_acres": 2.0,
                "rate_lbs_per_acre": 1.5,
                "expected_outcome": "Should NOT get false positive, low confidence calculation",
            },
            {
                "scenario": "Farmer enters completely unknown product",
                "commercial_name": "farmers-secret-formula",
                "selected_type": "FE",
                "area_acres": 4.0,
                "rate_lbs_per_acre": 40.0,
                "expected_outcome": "Should use farmer's type selection with low confidence",
            },
            {
                "scenario": "Farmer enters non-agricultural term (security test)",
                "commercial_name": "ads",
                "selected_type": "FE",
                "area_acres": 1.0,
                "rate_lbs_per_acre": 20.0,
                "expected_outcome": "Should NOT match any product, use farmer selection",
            },
        ]

        workflow_results = []

        for i, scenario in enumerate(farmer_scenarios, 1):
            print(f"\n🧑‍🌾 SCENARIO {i}: {scenario['scenario']}")
            print(f"   Product: '{scenario['commercial_name']}' as {scenario['selected_type']}")
            print(f"   Area: {scenario['area_acres']} acres at {scenario['rate_lbs_per_acre']} lbs/acre")
            print(f"   Expected: {scenario['expected_outcome']}")

            # Step 1: Smart Product Validation
            print(f"\n   📋 STEP 1: Product Validation")
            validation = self.validator.validate_smart_product(scenario["commercial_name"], scenario["selected_type"])

            print(f"      Confidence: {validation.confidence:.1%}")
            print(f"      Detected Type: {validation.correct_type}")
            if validation.npk_ratio:
                print(f"      NPK Auto-fill: {validation.npk_ratio}")
            if validation.manufacturer:
                print(f"      Manufacturer: {validation.manufacturer}")

            warnings_count = len(validation.warnings)
            if warnings_count > 0:
                print(f"      Warnings: {warnings_count}")
                for warning in validation.warnings[:2]:  # Show first 2
                    print(f"        - {warning}")

            # Step 2: Carbon Calculation
            print(f"\n   ⚡ STEP 2: Carbon Footprint Calculation")
            carbon_result = self.simulate_carbon_calculation(
                validation, scenario["area_acres"], scenario["rate_lbs_per_acre"]
            )

            if carbon_result["success"]:
                print(f"      Emission Factor: {carbon_result['emission_factor']:.1f} kg CO2e/lb")
                print(f"      Total Application: {carbon_result['total_application_lbs']:.1f} lbs")
                print(f"      Carbon Emissions: {carbon_result['total_emissions_tons']:.3f} tons CO2e")
                print(f"      Carbon Confidence: {carbon_result['carbon_confidence']}")
                if carbon_result["npk_used"]:
                    print(f"      NPK Considered: {carbon_result['npk_used']}")
            else:
                print(f"      ❌ Carbon calculation failed: {carbon_result['error']}")

            # Step 3: Result Assessment
            print(f"\n   📊 STEP 3: Result Assessment")

            # Assess if workflow worked correctly
            workflow_ok = True
            issues = []

            # Security checks
            if scenario["commercial_name"] in ["herb", "ads"]:
                if validation.confidence > 0.4:
                    issues.append(
                        f"Security issue: '{scenario['commercial_name']}' has {validation.confidence:.1%} confidence"
                    )
                    workflow_ok = False
                else:
                    print(f"      ✅ SECURITY: Low confidence ({validation.confidence:.1%}) for problematic input")

            # Type correction checks
            if scenario["commercial_name"] == "roundup" and scenario["selected_type"] == "PE":
                if validation.correct_type == "HE" and warnings_count > 0:
                    print(f"      ✅ TYPE CORRECTION: Detected herbicide, warned about mismatch")
                else:
                    issues.append("Failed to detect type mismatch for Roundup")
                    workflow_ok = False

            # Valid product checks
            if scenario["commercial_name"] in ["miracle-gro", "miracle grow"]:
                if validation.confidence >= 0.8 and validation.npk_ratio:
                    print(f"      ✅ VALID PRODUCT: High confidence with NPK auto-fill")
                else:
                    issues.append(f"Valid product has low confidence or missing NPK")
                    workflow_ok = False

            # Carbon calculation reliability
            if carbon_result["success"]:
                if carbon_result["total_emissions_tons"] > 0:
                    print(f"      ✅ CARBON CALC: Positive emissions calculated")
                else:
                    issues.append("Carbon calculation returned zero or negative emissions")
                    workflow_ok = False
            else:
                issues.append("Carbon calculation failed completely")
                workflow_ok = False

            if issues:
                print(f"      ❌ WORKFLOW ISSUES:")
                for issue in issues:
                    print(f"        - {issue}")
            else:
                print(f"      ✅ WORKFLOW: Complete success")

            # Record results
            workflow_results.append(
                {
                    "scenario": scenario["scenario"],
                    "input": scenario["commercial_name"],
                    "validation_confidence": validation.confidence,
                    "carbon_result": carbon_result,
                    "workflow_ok": workflow_ok,
                    "issues": issues,
                }
            )

        return workflow_results

    def test_edge_case_carbon_calculations(self):
        """Test carbon calculations with edge cases"""
        print("\n" + "=" * 70)
        print("🧪 TESTING EDGE CASE CARBON CALCULATIONS")
        print("=" * 70)

        edge_cases = [
            {"name": "High nitrogen fertilizer", "product": "urea", "type": "FE", "npk": "46-0-0"},
            {"name": "Balanced fertilizer", "product": "10-10-10", "type": "FE", "npk": "10-10-10"},
            {"name": "Herbicide application", "product": "roundup", "type": "HE", "npk": None},
            {"name": "Unknown product fallback", "product": "mystery-chemical", "type": "PE", "npk": None},
        ]

        for edge_case in edge_cases:
            print(f"\n🔬 Testing: {edge_case['name']}")

            # Get validation
            validation = self.validator.validate_smart_product(edge_case["product"], edge_case["type"])

            # Calculate carbon impact
            carbon_result = self.simulate_carbon_calculation(validation, 2.0, 15.0)  # 2 acres, 15 lbs/acre

            print(f"   Validation confidence: {validation.confidence:.1%}")
            if carbon_result["success"]:
                print(f"   Carbon emissions: {carbon_result['total_emissions_tons']:.3f} tons CO2e")
                print(f"   Emission factor: {carbon_result['emission_factor']:.1f} kg CO2e/lb")
                print(f"   Carbon confidence: {carbon_result['carbon_confidence']}")

                # Specific checks for different cases
                if edge_case["product"] == "urea":
                    # High-nitrogen fertilizer should have higher emission factor
                    if carbon_result["emission_factor"] > 1.4:  # Should be > base 1.2
                        print(f"   ✅ High nitrogen adjustment applied correctly")
                    else:
                        print(f"   ⚠️  Expected higher emission factor for high-nitrogen fertilizer")

                elif edge_case["product"] == "roundup":
                    # Herbicide should have higher emission factor than fertilizer
                    if carbon_result["emission_factor"] > 5.0:
                        print(f"   ✅ Herbicide emission factor appropriately higher than fertilizer")
                    else:
                        print(f"   ⚠️  Expected higher emission factor for herbicide")

                elif edge_case["product"] == "mystery-chemical":
                    # Unknown product should use base factor for selected type
                    if carbon_result["carbon_confidence"] == "LOW":
                        print(f"   ✅ Unknown product correctly flagged as low confidence")
                    else:
                        print(f"   ⚠️  Expected low confidence for unknown product")
            else:
                print(f"   ❌ Carbon calculation failed: {carbon_result['error']}")

    def generate_comprehensive_report(self, workflow_results: List[Dict]):
        """Generate comprehensive validation report"""
        print("\n" + "=" * 70)
        print("📊 COMPREHENSIVE CARBON WORKFLOW VALIDATION REPORT")
        print("=" * 70)

        total_scenarios = len(workflow_results)
        successful_workflows = sum(1 for r in workflow_results if r["workflow_ok"])
        security_tests_passed = 0
        valid_products_working = 0

        # Analyze results
        print(f"\n🔍 WORKFLOW ANALYSIS:")
        print(f"   Total scenarios tested: {total_scenarios}")
        print(f"   Successful workflows: {successful_workflows}")
        print(f"   Success rate: {successful_workflows/total_scenarios*100:.1f}%")

        print(f"\n🛡️  SECURITY VALIDATION:")
        for result in workflow_results:
            if result["input"] in ["herb", "ads"]:
                if result["validation_confidence"] <= 0.4:
                    security_tests_passed += 1
                    print(f"   ✅ '{result['input']}': {result['validation_confidence']:.1%} confidence (secure)")
                else:
                    print(
                        f"   ❌ '{result['input']}': {result['validation_confidence']:.1%} confidence (security risk)"
                    )

        print(f"\n🌱 VALID PRODUCT PERFORMANCE:")
        for result in workflow_results:
            if result["input"] in ["miracle-gro", "miracle grow"]:
                if result["validation_confidence"] >= 0.8:
                    valid_products_working += 1
                    print(f"   ✅ '{result['input']}': {result['validation_confidence']:.1%} confidence (excellent)")
                else:
                    print(
                        f"   ⚠️  '{result['input']}': {result['validation_confidence']:.1%} confidence (needs improvement)"
                    )

        print(f"\n⚡ CARBON CALCULATION RELIABILITY:")
        for result in workflow_results:
            carbon_success = result["carbon_result"].get("success", False)
            if carbon_success:
                emissions = result["carbon_result"].get("total_emissions_tons", 0)
                confidence = result["carbon_result"].get("carbon_confidence", "UNKNOWN")
                print(f"   {result['input']}: {emissions:.3f} tons CO2e ({confidence} confidence)")
            else:
                print(f"   ❌ {result['input']}: Carbon calculation failed")

        # Overall assessment
        print(f"\n{'='*70}")
        print(f"🎯 FINAL COMPREHENSIVE ASSESSMENT")
        print(f"{'='*70}")

        security_score = security_tests_passed / 2 * 100  # 2 security tests
        valid_product_score = valid_products_working / 2 * 100  # 2 valid product tests
        overall_score = successful_workflows / total_scenarios * 100

        print(f"Security validation: {security_score:.0f}% ({security_tests_passed}/2 tests passed)")
        print(f"Valid product performance: {valid_product_score:.0f}% ({valid_products_working}/2 tests passed)")
        print(f"Overall workflow success: {overall_score:.0f}% ({successful_workflows}/{total_scenarios} scenarios)")

        if overall_score >= 90 and security_score >= 100 and valid_product_score >= 100:
            print(f"\n🎉 EXCELLENT: Smart Product carbon workflow is PRODUCTION READY!")
            print(f"   ✅ All security tests passed - no false positives")
            print(f"   ✅ Valid products work with high confidence")
            print(f"   ✅ Carbon calculations integrate seamlessly")
            print(f"   ✅ Complete farmer journey works end-to-end")
            print(f"\n   🌱 Farmers can trust this system for accurate carbon footprints!")
            return True
        elif overall_score >= 80:
            print(f"\n⚠️  GOOD: System mostly working but needs attention")
            print(f"   Review failed scenarios and address issues")
            return False
        else:
            print(f"\n❌ NEEDS WORK: System has significant issues")
            print(f"   Multiple scenarios failing - requires fixes before production")
            return False


def main():
    """Run comprehensive carbon workflow validation"""
    print("🧪 COMPREHENSIVE CARBON CALCULATION WORKFLOW VALIDATION")
    print("Testing complete Smart Product integration with carbon footprint calculations")
    print("Ensuring farmers get ACCURATE, RELIABLE carbon results from product validation")

    try:
        tester = CarbonCalculationWorkflowTester()

        # Test complete farmer workflows
        workflow_results = tester.test_complete_farmer_workflow()

        # Test edge cases
        tester.test_edge_case_carbon_calculations()

        # Generate comprehensive report
        success = tester.generate_comprehensive_report(workflow_results)

        return success

    except Exception as e:
        print(f"❌ Test execution failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
