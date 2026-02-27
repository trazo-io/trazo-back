"""
Comprehensive Test Suite for Carbon Calculations
Ensures all carbon calculation logic is production-ready and accurate
"""

import unittest
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from carbon.models import CarbonEntry, CarbonReport, CarbonSource, CropType
from carbon.services.calculator import CarbonFootprintCalculator
from carbon.services.emission_factors import emission_factors
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from company.models import Company, Establishment
from history.models import ChemicalEvent, EquipmentEvent, History
from product.models import Parcel

User = get_user_model()


class TestEmissionFactorConsistency(TestCase):
    """Test emission factors are consistent with scientific data"""

    def test_nitrogen_emission_factor_accuracy(self):
        """Verify nitrogen emission factor matches scientific research"""
        nitrogen_factor = emission_factors.get_fertilizer_factor("nitrogen")

        # According to recent Nature research, global average is 10.48 kg CO2e/kg N
        # Current value of 10.5 is within acceptable range (EPA + IPCC AR6)
        self.assertEqual(nitrogen_factor["value"], 10.5)
        self.assertEqual(nitrogen_factor["unit"], "kg CO2e per kg N")
        self.assertIn("EPA", nitrogen_factor["source"])

        # Check components match research findings
        self.assertAlmostEqual(nitrogen_factor["production_component"], 2.6, delta=0.5)
        self.assertAlmostEqual(nitrogen_factor["field_component"], 7.9, delta=0.5)

    def test_phosphorus_emission_factor(self):
        """Verify phosphorus emission factor"""
        phosphorus_factor = emission_factors.get_fertilizer_factor("phosphorus")

        # Corrected value includes mining and processing
        self.assertEqual(phosphorus_factor["value"], 1.25)
        self.assertEqual(phosphorus_factor["unit"], "kg CO2e per kg P2O5")

    def test_fuel_emission_factors(self):
        """Verify fuel emission factors match EPA standards"""
        diesel_factor = emission_factors.get_fuel_factor("diesel")
        gasoline_factor = emission_factors.get_fuel_factor("gasoline")

        # EPA standard values
        self.assertEqual(diesel_factor["value"], 2.70)  # kg CO2e per liter
        self.assertEqual(gasoline_factor["value"], 2.32)  # kg CO2e per liter


class TestCarbonCalculations(TransactionTestCase):
    """Test carbon footprint calculations"""

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

        # Create test production
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

        self.production = History.objects.create(
            establishment=self.establishment,
            parcel=self.parcel,
            product="Oranges",
            variety="Valencia",
            start_date=timezone.now().date() - timedelta(days=365),
            created_by=self.user,
            crop_type=self.crop_type,
        )

        # Create carbon sources
        self.nitrogen_source = CarbonSource.objects.create(
            name="Nitrogen Fertilizer",
            unit="kg N",
            category="Fertilizer",
            default_emission_factor=10.5,
            usda_factors_based=True,
            verification_status="factors_verified",
            data_source="USDA Agricultural Research Service",
        )

        self.diesel_source = CarbonSource.objects.create(
            name="Diesel Fuel",
            unit="liters",
            category="Fuel",
            default_emission_factor=2.70,
            usda_factors_based=True,
            verification_status="factors_verified",
            data_source="EPA Emission Factors 2023",
        )

        # Initialize calculator
        self.calculator = CarbonFootprintCalculator()

    def test_fertilizer_emissions_calculation(self):
        """Test fertilizer emissions are calculated correctly"""
        # Create fertilizer application event
        fertilizer_event = ChemicalEvent.objects.create(
            history=self.production,
            date=timezone.now().date() - timedelta(days=180),
            chemical_name="Nitrogen Fertilizer",
            quantity=200.0,  # kg N
            unit="kg",
            area=100.0,  # hectares
            created_by=self.user,
        )

        # Calculate emissions
        inputs = {"fertilizer": {"nitrogen": 200.0}}  # kg N

        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        # Expected: 200 kg N * 10.5 kg CO2e/kg N = 2100 kg CO2e
        self.assertEqual(result["total_emissions"], 2100.0)
        self.assertEqual(result["emissions_per_acre"], 21.0)  # 2100/100
        self.assertTrue(result["usda_factors_used"])

    def test_fuel_emissions_calculation(self):
        """Test fuel emissions are calculated correctly"""
        # Create equipment use event
        equipment_event = EquipmentEvent.objects.create(
            history=self.production,
            date=timezone.now().date() - timedelta(days=90),
            equipment_type=0,  # Tractor
            hours_used=10.0,
            fuel_consumed=50.0,  # liters diesel
            created_by=self.user,
        )

        # Calculate emissions
        inputs = {"fuel": {"diesel": 50.0}}  # liters

        result = self.calculator.calculate_farm_footprint(inputs=inputs, crop_type="citrus", area=100.0)

        # Expected: 50 liters * 2.70 kg CO2e/liter = 135 kg CO2e
        self.assertEqual(result["total_emissions"], 135.0)
        self.assertEqual(result["emissions_per_acre"], 1.35)

    def test_combined_emissions_calculation(self):
        """Test calculation with multiple emission sources"""
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
        expected_fertilizer = (200.0 * 10.5) + (50.0 * 1.25) + (30.0 * 0.60)
        expected_fuel = (100.0 * 2.70) + (20.0 * 2.32)
        expected_electricity = 500.0 * 0.40
        expected_water = 1000.0 * 0.30
        expected_total = expected_fertilizer + expected_fuel + expected_electricity + expected_water

        self.assertAlmostEqual(result["total_emissions"], expected_total, delta=0.1)
        self.assertIn("fertilizer", result["breakdown"])
        self.assertIn("fuel", result["breakdown"])
        self.assertIn("electricity", result["breakdown"])
        self.assertIn("water", result["breakdown"])


class TestCarbonScoreCalculation(TestCase):
    """Test carbon score calculation logic"""

    def test_carbon_neutral_score(self):
        """Test score when emissions equal offsets"""
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=1000.0)
        self.assertEqual(score, 50)  # Neutral score

    def test_carbon_negative_score(self):
        """Test score when offsets exceed emissions"""
        # More offsets than emissions
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=2000.0)
        self.assertEqual(score, 100)  # Maximum score

        # Partial offset excess
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=1500.0)
        self.assertEqual(score, 75)  # 50 + (0.5 * 50)

    def test_carbon_positive_score(self):
        """Test score when emissions exceed offsets"""
        # No offsets
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=0.0)
        self.assertEqual(score, 1)  # Minimum positive score

        # Partial offsets
        score = CarbonEntry.calculate_carbon_score(total_emissions=1000.0, total_offsets=500.0)
        self.assertEqual(score, 25)  # 0.5 * 50

    def test_score_with_industry_benchmark(self):
        """Test score calculation with industry benchmark"""
        # Better than industry average
        score = CarbonEntry.calculate_carbon_score(total_emissions=800.0, total_offsets=0.0, industry_benchmark=1000.0)
        self.assertGreater(score, 25)
        self.assertLess(score, 50)

        # Worse than industry average
        score = CarbonEntry.calculate_carbon_score(total_emissions=1500.0, total_offsets=0.0, industry_benchmark=1000.0)
        self.assertLess(score, 25)
        self.assertGreaterEqual(score, 1)


class TestCarbonEntryModel(TransactionTestCase):
    """Test CarbonEntry model functionality"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Establishment", address="123 Test St", country="USA", created_by=self.user
        )

        self.carbon_source = CarbonSource.objects.create(
            name="Test Source", unit="kg CO2e", category="Test", default_emission_factor=1.0
        )

    def test_carbon_entry_creation(self):
        """Test creating carbon entries"""
        # Create emission entry
        emission = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=self.carbon_source,
            amount=1000.0,
            year=2024,
            description="Test emission",
        )

        self.assertEqual(emission.amount, 1000.0)
        self.assertEqual(emission.effective_amount, 1000.0)
        self.assertEqual(emission.type, "emission")

    def test_offset_entry_trust_score(self):
        """Test offset entries with trust scores"""
        # Self-reported offset
        offset_self = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            amount=500.0,
            year=2024,
            verification_level="self_reported",
        )

        self.assertEqual(offset_self.trust_score, 0.5)
        self.assertEqual(offset_self.effective_amount, 250.0)  # 500 * 0.5

        # Certified project offset
        offset_certified = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            amount=500.0,
            year=2024,
            verification_level="certified_project",
        )

        self.assertEqual(offset_certified.trust_score, 1.0)
        self.assertEqual(offset_certified.effective_amount, 500.0)  # 500 * 1.0


class TestCarbonReportGeneration(TransactionTestCase):
    """Test carbon report generation"""

    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(email="test@example.com", password="testpass123")

        self.company = Company.objects.create(name="Test Company", country="USA", created_by=self.user)

        self.establishment = Establishment.objects.create(
            company=self.company, name="Test Establishment", address="123 Test St", country="USA", created_by=self.user
        )

        # Create carbon entries
        self.carbon_source = CarbonSource.objects.create(
            name="Test Emissions", unit="kg CO2e", category="Test", default_emission_factor=1.0
        )

        # Create emissions
        CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=self.carbon_source,
            amount=1000.0,
            year=2024,
        )

        CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="emission",
            source=self.carbon_source,
            amount=500.0,
            year=2024,
        )

        # Create offsets
        CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type="offset",
            amount=300.0,
            year=2024,
            verification_level="certified_project",
        )

    def test_report_calculations(self):
        """Test report calculations are accurate"""
        report = CarbonReport.objects.create(
            establishment=self.establishment,
            period_start=datetime(2024, 1, 1).date(),
            period_end=datetime(2024, 12, 31).date(),
        )

        # Calculate totals
        emissions = (
            CarbonEntry.objects.filter(establishment=self.establishment, type="emission", year=2024).aggregate(
                total=models.Sum("co2e_amount")
            )["total"]
            or 0
        )

        offsets = (
            CarbonEntry.objects.filter(establishment=self.establishment, type="offset", year=2024).aggregate(
                total=models.Sum("effective_amount")
            )["total"]
            or 0
        )

        report.total_emissions = emissions
        report.total_offsets = offsets
        report.net_footprint = emissions - offsets
        report.carbon_score = CarbonEntry.calculate_carbon_score(emissions, offsets)
        report.save()

        self.assertEqual(report.total_emissions, 1500.0)
        self.assertEqual(report.total_offsets, 300.0)
        self.assertEqual(report.net_footprint, 1200.0)
        self.assertGreater(report.carbon_score, 0)
        self.assertLess(report.carbon_score, 50)


class TestEventCarbonCalculator(TestCase):
    """Test event-based carbon calculations"""

    def setUp(self):
        """Set up test data"""
        self.calculator = EventCarbonCalculator()

    def test_fertilizer_event_calculation(self):
        """Test carbon calculation for fertilizer events"""
        event_data = {
            "type": "fertilizer",
            "nitrogen_amount": 100.0,
            "phosphorus_amount": 50.0,
            "potassium_amount": 30.0,
            "application_method": "broadcast",
        }

        result = self.calculator.calculate_event_carbon(event_data)

        # Expected: (100 * 10.5) + (50 * 1.25) + (30 * 0.60) = 1130.5
        self.assertAlmostEqual(result["total_emissions"], 1130.5, delta=0.1)
        self.assertIn("breakdown", result)
        self.assertTrue(result["usda_factors_used"])

    def test_equipment_event_calculation(self):
        """Test carbon calculation for equipment events"""
        event_data = {"type": "equipment", "fuel_type": "diesel", "fuel_consumed": 25.0, "hours_used": 5.0}  # liters

        result = self.calculator.calculate_event_carbon(event_data)

        # Expected: 25 * 2.70 = 67.5
        self.assertEqual(result["total_emissions"], 67.5)
        self.assertEqual(result["emission_source"], "fuel_combustion")


if __name__ == "__main__":
    unittest.main()
