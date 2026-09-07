"""
Test Suite for Carbon Calculations
Ensures carbon footprint calculations are accurate and production-ready
"""

import unittest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from carbon.models import CarbonBenchmark, CarbonEntry, CropType
from carbon.services.calculator import CarbonFootprintCalculator
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel

User = get_user_model()


class TestCarbonFootprintCalculator(TransactionTestCase):
    """Test the main carbon footprint calculation engine"""

    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            email="test@example.com", password="testpass123", first_name="Test", last_name="User"
        )

        # Create test company and establishment
        self.company = Company.objects.create(name="Test Farm Co", country="USA", created_by=self.user)

        self.establishment = Establishment.objects.create(
            company=self.company,
            name="Test Farm",
            address="123 Farm Road",
            country="USA",
            latitude=40.7128,
            longitude=-74.0060,
            created_by=self.user,
        )

        # Create test parcel
        self.parcel = Parcel.objects.create(
            establishment=self.establishment,
            name="North Field",
            area=100.0,  # hectares
            polygon={
                "type": "Polygon",
                "coordinates": [
                    [
                        [-74.0060, 40.7128],
                        [-74.0050, 40.7128],
                        [-74.0050, 40.7138],
                        [-74.0060, 40.7138],
                        [-74.0060, 40.7128],
                    ]
                ],
            },
        )

        # Create test crop type
        self.crop_type = CropType.objects.create(
            name="Citrus (Oranges)",
            slug="citrus_oranges",
            category="tree_fruit",
            description="Orange production",
            typical_farm_size="20-100 hectares",
            growing_season="12 months",
            harvest_season="November - April",
            emissions_per_hectare=1200.0,
            industry_average=1500.0,
            best_practice=900.0,
            carbon_credit_potential=0.5,
            typical_cost_per_hectare=5000.0,
            usda_factors_used=True,
        )

        # Create test production
        self.production = History.objects.create(
            establishment=self.establishment,
            parcel=self.parcel,
            product="Oranges",
            variety="Valencia",
            start_date=timezone.now().date() - timedelta(days=365),
            created_by=self.user,
            crop_type=self.crop_type,
        )

        # Initialize calculator
        self.calculator = CarbonFootprintCalculator()

    def test_fertilizer_emissions_calculation(self):
        """Test fertilizer emissions are calculated correctly with current factors"""
        inputs = {"fertilizer": {"nitrogen": 200.0, "phosphorus": 50.0, "potassium": 30.0}}  # kg N  # kg P2O5  # kg K2O

        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        # Expected emissions with corrected factors:
        # Nitrogen: 200 * 11.0 = 2200 kg CO2e
        # Phosphorus: 50 * 1.19 = 59.5 kg CO2e
        # Potassium: 30 * 0.65 = 19.5 kg CO2e
        # Total: 2280.5 kg CO2e
        expected_total = (200.0 * 11.0) + (50.0 * 1.25) + (30.0 * 0.60)

        self.assertAlmostEqual(result["total_emissions"], expected_total, delta=0.1)
        self.assertEqual(result["emissions_per_acre"], expected_total / 100.0)
        self.assertTrue(result["usda_factors_used"])
        self.assertIn("fertilizer", result["breakdown"])

    def test_fuel_emissions_calculation(self):
        """Test fuel emissions are calculated correctly"""
        inputs = {"fuel": {"diesel": 100.0, "gasoline": 20.0}}  # liters  # liters

        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        # Expected emissions:
        # Diesel: 100 * 2.70 = 270 kg CO2e
        # Gasoline: 20 * 2.32 = 46.4 kg CO2e
        # Total: 316.4 kg CO2e
        expected_total = (100.0 * 2.70) + (20.0 * 2.32)

        self.assertAlmostEqual(result["total_emissions"], expected_total, delta=0.1)
        self.assertIn("fuel", result["breakdown"])

    def test_electricity_emissions_calculation(self):
        """Test electricity emissions calculation"""
        inputs = {"electricity": {"grid": 500.0, "solar": 200.0}}  # kWh  # kWh (should be 0 emissions)

        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        # Expected emissions:
        # Grid: 500 * 0.365 = 182.5 kg CO2e
        # Solar: 200 * 0.00 = 0 kg CO2e
        # Total: 200 kg CO2e
        expected_total = 500.0 * 0.40

        self.assertEqual(result["total_emissions"], expected_total)
        self.assertIn("electricity", result["breakdown"])

    def test_water_emissions_calculation(self):
        """Test water-related emissions calculation"""
        inputs = {"water": {"irrigation": 1000.0, "pumping": 500.0}}  # m³  # m³

        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        # Expected emissions:
        # Irrigation: 1000 * 0.30 = 300 kg CO2e
        # Pumping: 500 * 0.20 = 100 kg CO2e
        # Total: 400 kg CO2e
        expected_total = (1000.0 * 0.30) + (500.0 * 0.20)

        self.assertEqual(result["total_emissions"], expected_total)
        self.assertIn("water", result["breakdown"])

    def test_comprehensive_calculation(self):
        """Test calculation with all emission sources"""
        inputs = {
            "fertilizer": {"nitrogen": 200.0, "phosphorus": 50.0, "potassium": 30.0},  # kg N  # kg P2O5  # kg K2O
            "fuel": {"diesel": 100.0, "gasoline": 20.0},  # liters  # liters
            "electricity": {"grid": 500.0},  # kWh
            "water": {"irrigation": 1000.0},  # m³
        }

        result = self.calculator.calculate_farm_footprint(
            inputs=inputs, crop_type="citrus", area=100.0, region="California"
        )

        # Calculate expected emissions
        expected_fertilizer = (200.0 * 11.0) + (50.0 * 1.25) + (30.0 * 0.60)
        expected_fuel = (100.0 * 2.70) + (20.0 * 2.32)
        expected_electricity = 500.0 * 0.365
        expected_water = 1000.0 * 0.30
        expected_total = expected_fertilizer + expected_fuel + expected_electricity + expected_water

        self.assertAlmostEqual(result["total_emissions"], expected_total, delta=0.1)
        self.assertIn("fertilizer", result["breakdown"])
        self.assertIn("fuel", result["breakdown"])
        self.assertIn("electricity", result["breakdown"])
        self.assertIn("water", result["breakdown"])
        self.assertIn("efficiency_score", result)
        self.assertIn("recommendations", result)

    def test_efficiency_score_calculation(self):
        """Test efficiency score is calculated properly"""
        inputs = {"fertilizer": {"nitrogen": 100.0}}  # Moderate nitrogen use

        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        self.assertIn("efficiency_score", result)
        self.assertIsInstance(result["efficiency_score"], (int, float))
        self.assertGreaterEqual(result["efficiency_score"], 0)
        self.assertLessEqual(result["efficiency_score"], 100)

    def test_benchmark_comparison(self):
        """Test benchmark comparison functionality"""
        # Create a benchmark
        CarbonBenchmark.objects.create(
            industry="citrus",
            year=2024,
            average_emissions=1500.0,
            min_emissions=800.0,
            max_emissions=2500.0,
            unit="kg CO2e per hectare",
            source="USDA Test Data",
            usda_factors_used=True,
            crop_type="citrus",
        )

        inputs = {"fertilizer": {"nitrogen": 100.0}}  # 1100 kg CO2e

        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        self.assertIn("benchmark", result)
        if result["benchmark"]:
            self.assertEqual(result["benchmark"]["industry"], "citrus")
            self.assertEqual(result["benchmark"]["average_emissions"], 1500.0)


class TestEventCarbonCalculator(TestCase):
    """Test event-based carbon calculations"""

    def setUp(self):
        """Set up test data"""
        self.calculator = EventCarbonCalculator()

    def test_fertilizer_event_calculation(self):
        """Test carbon calculation for fertilizer application events"""
        event_data = {
            "type": "fertilization",
            "nitrogen_amount": 100.0,
            "phosphorus_amount": 50.0,
            "potassium_amount": 30.0,
            "application_method": "broadcast",
            "area": 10.0,  # hectares
        }

        result = self.calculator.calculate_event_carbon(event_data)

        # Expected: (100 * 11.0) + (50 * 1.25) + (30 * 0.60) = 1180.5 kg CO2e
        expected_emissions = (100.0 * 11.0) + (50.0 * 1.25) + (30.0 * 0.60)

        self.assertAlmostEqual(result["total_emissions"], expected_emissions, delta=0.1)
        self.assertIn("breakdown", result)
        self.assertTrue(result["usda_factors_used"])
        self.assertEqual(result["emission_source"], "fertilizer_application")

    def test_equipment_event_calculation(self):
        """Test carbon calculation for equipment operation events"""
        event_data = {
            "type": "equipment",
            "fuel_type": "diesel",
            "fuel_consumed": 25.0,  # liters
            "hours_used": 5.0,
            "equipment_type": "tractor",
        }

        result = self.calculator.calculate_event_carbon(event_data)

        # Expected: 25 * 2.70 = 67.5 kg CO2e
        expected_emissions = 25.0 * 2.70

        self.assertEqual(result["total_emissions"], expected_emissions)
        self.assertEqual(result["emission_source"], "fuel_combustion")
        self.assertIn("equipment_efficiency", result)

    def test_irrigation_event_calculation(self):
        """Test carbon calculation for irrigation events"""
        event_data = {
            "type": "irrigation",
            "water_volume": 500.0,  # m³
            "energy_source": "grid_electricity",
            "pumping_required": True,
            "area_irrigated": 5.0,  # hectares
        }

        result = self.calculator.calculate_event_carbon(event_data)

        # Expected: 500 * 0.30 = 150 kg CO2e (irrigation energy)
        expected_emissions = 500.0 * 0.30

        self.assertEqual(result["total_emissions"], expected_emissions)
        self.assertEqual(result["emission_source"], "irrigation_energy")

    def test_application_method_efficiency(self):
        """Test application method efficiency adjustments"""
        base_event = {"type": "fertilization", "nitrogen_amount": 100.0, "area": 10.0}

        # Broadcast application (baseline)
        broadcast_event = {**base_event, "application_method": "broadcast"}
        broadcast_result = self.calculator.calculate_event_carbon(broadcast_event)

        # Precision application (should have 18% reduction)
        precision_event = {**base_event, "application_method": "precision"}
        precision_result = self.calculator.calculate_event_carbon(precision_event)

        # Precision should have lower emissions due to efficiency
        expected_reduction = 0.18  # 18% reduction
        expected_precision_emissions = broadcast_result["total_emissions"] * (1 - expected_reduction)

        self.assertAlmostEqual(precision_result["total_emissions"], expected_precision_emissions, delta=1.0)

    def test_organic_practice_adjustments(self):
        """Test organic practice carbon benefits"""
        organic_event = {
            "type": "fertilization",
            "nitrogen_amount": 80.0,  # 20% less due to organic efficiency
            "organic_certified": True,
            "cover_crops": True,
            "compost_application": True,
            "area": 10.0,
        }

        result = self.calculator.calculate_event_carbon(organic_event)

        # Should have organic benefits applied
        self.assertIn("organic_benefits", result)
        self.assertTrue(result.get("organic_certified", False))

        # Check carbon sequestration benefit is included
        if "carbon_sequestration_benefit" in result:
            self.assertGreater(result["carbon_sequestration_benefit"], 0)


class TestCarbonScoreCalculation(TestCase):
    """Test carbon score calculation methodology"""

    def test_carbon_neutral_score(self):
        """Test score when emissions equal offsets (should be 50)"""
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=1000.0)
        self.assertEqual(score, 50)  # Neutral score

    def test_carbon_negative_score(self):
        """Test score when offsets exceed emissions (should be > 50)"""
        # Complete offset with excess
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=2000.0)
        self.assertEqual(score, 100)  # Maximum score

        # Partial offset excess (50% more offsets than emissions)
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=1500.0)
        self.assertEqual(score, 75)  # 50 + (0.5 * 50)

    def test_carbon_positive_score(self):
        """Test score when emissions exceed offsets (should be < 50)"""
        # No offsets
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=0.0)
        self.assertEqual(score, 1)  # Minimum positive score

        # 50% offset
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=500.0)
        self.assertEqual(score, 25)  # 0.5 * 50

    def test_score_with_industry_benchmark(self):
        """Test score calculation with industry benchmark"""
        # Better than industry average (80% of benchmark)
        score = CarbonEntry.calculate_carbon_score(total_emissions=800.0, total_offsets=0.0, industry_benchmark=1000.0)
        self.assertGreater(score, 25)
        self.assertLess(score, 50)

        # Exactly at industry average
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=0.0, industry_benchmark=1000.0)
        self.assertEqual(score, 25)

        # Worse than industry average (150% of benchmark)
        score = CarbonEntry.calculate_carbon_score(total_emissions=1500.0, total_offsets=0.0, industry_benchmark=1000.0)
        self.assertLess(score, 25)
        self.assertGreaterEqual(score, 1)

    def test_edge_cases(self):
        """Test edge cases in score calculation"""
        # Zero emissions and offsets
        score = CarbonEntry.calculate_carbon_score(total_emissions=0.0, total_offsets=0.0)
        self.assertEqual(score, 50)  # Neutral

        # Only offsets, no emissions
        score = CarbonEntry.calculate_carbon_score(total_emissions=0.0, total_offsets=100.0)
        self.assertEqual(score, 100)  # Perfect score


class TestCarbonCalculationValidation(TestCase):
    """Test validation and error handling in calculations"""

    def setUp(self):
        self.calculator = CarbonFootprintCalculator()

    def test_negative_input_validation(self):
        """Test handling of negative input values"""
        inputs = {"fertilizer": {"nitrogen": -100.0}}  # Negative value

        with self.assertRaises(ValueError):
            self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

    def test_zero_area_validation(self):
        """Test handling of zero or negative area"""
        inputs = {"fertilizer": {"nitrogen": 100.0}}

        with self.assertRaises(ValueError):
            self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=0.0)  # Zero area

    def test_missing_emission_factor_handling(self):
        """Test handling of missing emission factors"""
        inputs = {"fertilizer": {"invalid_nutrient": 100.0}}

        # Should skip invalid nutrients and log warning
        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        # Should return zero emissions for invalid inputs
        self.assertEqual(result["total_emissions"], 0.0)


if __name__ == "__main__":
    unittest.main()
