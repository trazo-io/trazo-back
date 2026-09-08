"""
Comprehensive tests for validating emission factors against authoritative sources.

This test suite validates Trazo's emission factors against IPCC guidelines, EPA standards,
and peer-reviewed research to ensure production-ready accuracy.
"""

import unittest

from django.test import TestCase

from carbon.services.emission_factors import EmissionFactorsRegistry


class EmissionFactorValidationTest(TestCase):
    """Test emission factors against authoritative standards"""

    def setUp(self):
        self.registry = EmissionFactorsRegistry()

    def test_nitrogen_factor_against_ipcc_standards(self):
        """Validate nitrogen emission factor against IPCC 2019 guidelines"""
        nitrogen_factor_data = self.registry.get_fertilizer_factor("nitrogen")
        nitrogen_factor = nitrogen_factor_data["value"]

        # Current factor: 10.5 kg CO2e/kg N (EPA + IPCC AR6)
        # Includes manufacturing (2.6) + field N2O direct + indirect (7.9)
        # Literature range: 4-12 kg CO2e/kg N depending on methodology
        expected_min = 4.65  # Conservative: field (2.65) + production (2.0)
        expected_max = 12.0  # High-end: includes all indirect effects

        self.assertGreaterEqual(
            nitrogen_factor, expected_min, f"Nitrogen factor {nitrogen_factor} below IPCC minimum {expected_min}"
        )
        self.assertLessEqual(
            nitrogen_factor, expected_max, f"Nitrogen factor {nitrogen_factor} above IPCC maximum {expected_max}"
        )

    def test_nitrogen_factor_components_breakdown(self):
        """Validate nitrogen factor component breakdown"""
        factor_data = self.registry.FERTILIZER_FACTORS["nitrogen"]

        production_component = factor_data.get("production_component", 0)
        field_component = factor_data.get("field_component", 0)
        total_value = factor_data["value"]

        # Components should add up to total
        self.assertEqual(
            production_component + field_component,
            total_value,
            "Production and field components don't sum to total value",
        )

        # Field component validation against IPCC
        # Includes direct N2O (1% EF1 × 265 GWP) + indirect N2O effects
        # Range: 4-10 kg CO2e/kg N when all field effects included
        self.assertGreaterEqual(
            field_component, 4.0, f"Field component {field_component} too low for total N2O emissions"
        )
        self.assertLessEqual(field_component, 10.0, f"Field component {field_component} too high for N2O emissions")

        # Production component validation (manufacturing + transport)
        # Research shows 1-5 kg CO2e/kg N for production alone
        self.assertGreaterEqual(production_component, 1.0, f"Production component {production_component} too low")
        self.assertLessEqual(production_component, 5.0, f"Production component {production_component} too high")

    def test_phosphorus_factor_validation(self):
        """Validate phosphorus emission factor"""
        phosphorus_factor_data = self.registry.get_fertilizer_factor("phosphorus")
        phosphorus_factor = phosphorus_factor_data["value"]

        # Typical P2O5 production emissions: 0.1-1.5 kg CO2e/kg P2O5
        # Source: Peer-reviewed LCA studies
        expected_min = 0.1
        expected_max = 2.0  # Allow for supply chain variations

        self.assertGreaterEqual(
            phosphorus_factor, expected_min, f"Phosphorus factor {phosphorus_factor} below expected minimum"
        )
        self.assertLessEqual(
            phosphorus_factor, expected_max, f"Phosphorus factor {phosphorus_factor} above expected maximum"
        )

    def test_potassium_factor_validation(self):
        """Validate potassium emission factor"""
        potassium_factor_data = self.registry.get_fertilizer_factor("potassium")
        potassium_factor = potassium_factor_data["value"]

        # Typical K2O production emissions: 0.1-0.8 kg CO2e/kg K2O
        # Source: Peer-reviewed LCA studies
        expected_min = 0.1
        expected_max = 1.0  # Allow for supply chain variations

        self.assertGreaterEqual(
            potassium_factor, expected_min, f"Potassium factor {potassium_factor} below expected minimum"
        )
        self.assertLessEqual(
            potassium_factor, expected_max, f"Potassium factor {potassium_factor} above expected maximum"
        )

    def test_factor_metadata_completeness(self):
        """Ensure all factors have required metadata"""
        for nutrient in ["nitrogen", "phosphorus", "potassium"]:
            factor_data = self.registry.FERTILIZER_FACTORS[nutrient]

            required_fields = ["value", "unit", "source", "confidence", "last_verified"]
            for field in required_fields:
                self.assertIn(field, factor_data, f"Factor {nutrient} missing required field {field}")
                self.assertIsNotNone(factor_data[field], f"Factor {nutrient} has None value for {field}")

    def test_factor_versioning_consistency(self):
        """Test that factor versions are consistent and documented"""
        version = self.registry.VERSION
        last_updated = self.registry.LAST_UPDATED
        data_source = self.registry.DATA_SOURCE

        self.assertIsNotNone(version, "Registry version is missing")
        self.assertIsNotNone(last_updated, "Last updated date is missing")
        self.assertIsNotNone(data_source, "Data source is missing")

        # Version should follow semantic versioning
        version_parts = version.split(".")
        self.assertEqual(len(version_parts), 3, f"Version {version} not in semantic format")

        for part in version_parts:
            self.assertTrue(part.isdigit(), f"Version part {part} not numeric")


class EmissionFactorConsistencyTest(TestCase):
    """Test consistency of emission factors across the codebase"""

    def test_no_hardcoded_nitrogen_factors(self):
        """Ensure no hardcoded nitrogen factors exist outside registry"""
        # This test would scan codebase for hardcoded values
        # Implementation would check for patterns like "6.7", "5.86", etc.

    def test_calculation_consistency(self):
        """Test that all calculation paths use same emission factors"""
        from carbon.services.emission_factors import emission_factors
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calculator = EventCarbonCalculator()

        # Test that calculator uses registry factors
        registry_nitrogen = emission_factors.get_fertilizer_factor("nitrogen")["value"]

        # Verify the registry nitrogen factor matches expected EPA/IPCC value
        self.assertEqual(registry_nitrogen, 10.5)

        # Verify EventCarbonCalculator pulls from the same registry
        calc_nitrogen = calculator.USDA_FERTILIZER_FACTORS.get("nitrogen", 0)
        self.assertEqual(calc_nitrogen, registry_nitrogen, "Calculator should use registry nitrogen factor")


class EmissionFactorBenchmarkTest(TestCase):
    """Benchmark tests against known reference calculations"""

    def test_urea_application_benchmark(self):
        """100 kg of urea at 46% N must price at the registry's nitrogen factor.

        🔴 2026-09-07 — this asserted `> 0` against a `SimpleNamespace` stand-in and got 0.0 for
        months. `_extract_chemical_data` reads `event.history`, which the stand-in did not have,
        so the extractor raised, the calculator's broad `except` returned its zero defaults, and
        the assertion read `result.get("co2e", 0)` — the default masking the failure a second
        time. A benchmark that cannot tell "we calculated zero" from "we could not read the
        event" is not a benchmark.

        So: a real ChemicalEvent, and an assertion on the arithmetic rather than on the sign.
        """
        from django.utils import timezone

        from carbon.services.event_carbon_calculator import EventCarbonCalculator
        from company.models import Company, Establishment
        from history.models import ChemicalEvent, History
        from product.models import Parcel, Product
        from users.models import User

        user = User.objects.create_user(email="urea-benchmark@test.com", password="x")
        company = Company.objects.create(name="Urea Farm")
        establishment = Establishment.objects.create(name="UREA1", company=company, state="CA")
        parcel = Parcel.objects.create(name="urea-parcel", establishment=establishment, area=1.0)
        product = Product.objects.create(name="Almond")
        history = History.objects.create(
            name="Urea Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        event = ChemicalEvent.objects.create(
            history=history,
            type="FE",
            date=timezone.now(),
            description="Urea broadcast",
            commercial_name="Urea",
            volume="100",
            area=1.0,
            way_of_application="broadcast",
            # The composition goes in `concentration`, the farmer-entered field. Putting it in
            # extra_data instead prices the event at zero NPK — deliberately, per the F03
            # no-phantom rule (2026-06): an unstated composition must not be invented, because
            # a fabricated 10-10-10 manufactures nitrogen emissions the farmer never reported.
            concentration="46-0-0",
            extra_data={"volume_unit": "kg", "area_unit": "ha"},
        )

        result = EventCarbonCalculator().calculate_chemical_event_impact(event)

        # `.get("co2e", 0)` was the second mask. Assert the key exists before reading it.
        self.assertIn("co2e", result)
        calculated_co2e = result["co2e"]

        self.assertGreater(
            calculated_co2e,
            0,
            "Urea priced at zero. If the log shows 'Error extracting chemical data, using zero "
            "defaults', the calculator could not read the event and this is not a real zero.",
        )

        # 100 kg x 46% N = 46 kg N. Manufacturing + field N2O at the registry factor is the
        # dominant term; application fuel is not reported here, so the total should land in the
        # neighbourhood of 46 x the nitrogen factor rather than at some unrelated magnitude.
        nitrogen_factor = EmissionFactorsRegistry().get_fertilizer_factor("nitrogen")["value"]
        expected_nitrogen_term = 46.0 * nitrogen_factor
        self.assertGreater(calculated_co2e, expected_nitrogen_term * 0.5)
        self.assertLess(calculated_co2e, expected_nitrogen_term * 2.0)

    def test_regional_variation_awareness(self):
        """Test that system has regional emission factor data"""
        from carbon.services.emission_factors import EmissionFactorsRegistry

        # Verify regional factors exist in the registry
        regional_factors = EmissionFactorsRegistry.REGIONAL_FACTORS
        self.assertGreater(len(regional_factors), 0, "Regional factors should be defined")

        # Verify climate-specific factors exist
        climate_factors = EmissionFactorsRegistry.CLIMATE_SPECIFIC_FACTORS
        self.assertIn("wet_climate", climate_factors)
        self.assertIn("dry_climate", climate_factors)


if __name__ == "__main__":
    unittest.main()
