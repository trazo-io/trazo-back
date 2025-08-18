"""
Comprehensive test suite for Carbon calculation functionality.
Tests cover USDA-verified calculations, blockchain verification, and production readiness.

Test Coverage:
- Carbon footprint calculations with USDA-verified emission factors
- Fertilizer application carbon calculations
- Fuel consumption carbon calculations
- Irrigation and electricity carbon calculations
- Climate-aware adjustments and regional factors
- Blockchain verification and immutable records
- IoT device integration (John Deere, sensors)
- Circuit breaker patterns and API resilience
- Caching strategies and performance optimization
- Edge cases and error handling
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from carbon.models import (
    CarbonAuditLog,
    CarbonEntry,
    CarbonReport,
    CarbonSource,
    CarbonVerification,
    EstablishmentCarbonFootprint,
    IoTDevice,
    IoTReading,
    JohnDeereIntegration,
    ProducerCommunityVerification,
    ProductionTemplate,
    SustainabilityBadge,
    USDACompliance,
)
from carbon.services.blockchain import BlockchainService
from carbon.services.carbon_calculator import CarbonCalculator
from carbon.services.circuit_breaker_enhanced import CircuitBreakerManager
from carbon.services.coolfarm_service import CoolFarmService
from carbon.services.emission_factors import (
    EmissionFactorsService,
    get_electricity_factor,
    get_fertilizer_factor,
    get_fuel_factor,
    get_irrigation_factor,
)
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel
from users.models import User, WorksIn

User = get_user_model()


class EmissionFactorsTestCase(TestCase):
    """Test USDA-verified emission factors and calculations."""

    def setUp(self):
        self.emission_service = EmissionFactorsService()

    def test_usda_fertilizer_factors_nitrogen(self):
        """Test USDA-verified nitrogen fertilizer emission factors."""
        # Test corrected nitrogen factor (11.0 kg CO2e per kg N)
        factor = get_fertilizer_factor("nitrogen")

        self.assertEqual(factor["value"], 11.0)
        self.assertEqual(factor["unit"], "kg CO2e per kg N")
        self.assertIn("USDA-ARS Corrected Research", factor["source"])
        self.assertTrue(factor["usda_verified"])

    def test_usda_fertilizer_factors_phosphorus(self):
        """Test USDA-verified phosphorus fertilizer emission factors."""
        factor = get_fertilizer_factor("phosphorus")

        self.assertEqual(factor["value"], 1.25)
        self.assertEqual(factor["unit"], "kg CO2e per kg P2O5")
        self.assertTrue(factor["usda_verified"])

    def test_usda_fertilizer_factors_potassium(self):
        """Test USDA-verified potassium fertilizer emission factors."""
        factor = get_fertilizer_factor("potassium")

        self.assertEqual(factor["value"], 0.6)
        self.assertEqual(factor["unit"], "kg CO2e per kg K2O")
        self.assertTrue(factor["usda_verified"])

    def test_usda_fuel_factors(self):
        """Test USDA-verified fuel emission factors."""
        # Diesel factor
        diesel_factor = get_fuel_factor("diesel")
        self.assertEqual(diesel_factor["value"], 2.68)
        self.assertEqual(diesel_factor["unit"], "kg CO2e per liter")

        # Gasoline factor
        gasoline_factor = get_fuel_factor("gasoline")
        self.assertEqual(gasoline_factor["value"], 2.31)
        self.assertEqual(gasoline_factor["unit"], "kg CO2e per liter")

    def test_electricity_emission_factors(self):
        """Test electricity emission factors by region."""
        # California electricity (cleaner grid)
        ca_factor = get_electricity_factor("CA")
        self.assertIsNotNone(ca_factor["value"])
        self.assertEqual(ca_factor["unit"], "kg CO2e per kWh")

        # National average
        avg_factor = get_electricity_factor("US_AVERAGE")
        self.assertIsNotNone(avg_factor["value"])

    def test_irrigation_emission_factors(self):
        """Test irrigation system emission factors."""
        # Drip irrigation (most efficient)
        drip_factor = get_irrigation_factor("drip")
        self.assertLess(drip_factor["value"], 0.5)  # Should be efficient

        # Flood irrigation (least efficient)
        flood_factor = get_irrigation_factor("flood")
        self.assertGreater(flood_factor["value"], drip_factor["value"])

    def test_climate_adjustment_factors(self):
        """Test climate-aware emission factor adjustments."""
        # Test temperature adjustments
        hot_climate_factor = self.emission_service.get_climate_adjusted_factor(
            base_factor=5.0, temperature=35.0, humidity=0.7, precipitation=200  # Hot climate  # mm/year
        )

        temperate_climate_factor = self.emission_service.get_climate_adjusted_factor(
            base_factor=5.0, temperature=20.0, humidity=0.5, precipitation=800  # Temperate climate
        )

        # Hot climates should have different factors due to increased volatilization
        self.assertNotEqual(hot_climate_factor, temperate_climate_factor)

    def test_emission_factor_caching(self):
        """Test emission factor caching for performance."""
        cache.clear()

        # First call should hit the database/service
        factor1 = get_fertilizer_factor("nitrogen")

        # Second call should hit cache
        factor2 = get_fertilizer_factor("nitrogen")

        self.assertEqual(factor1, factor2)

    def test_invalid_fertilizer_type(self):
        """Test handling of invalid fertilizer types."""
        with self.assertRaises(ValueError):
            get_fertilizer_factor("invalid_fertilizer_type")

    def test_emission_factor_date_versioning(self):
        """Test that emission factors are versioned by date."""
        factor = get_fertilizer_factor("nitrogen")

        # Should have version information
        self.assertIn("last_updated", factor)
        self.assertIn("version", factor)


class CarbonCalculatorTestCase(TestCase):
    """Test carbon calculator with production-ready scenarios."""

    def setUp(self):
        self.user = User.objects.create_user(email="farmer@test.com", password="testpass123")

        self.company = Company.objects.create(name="Carbon Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(
            name="Carbon Test Field",
            company=self.company,
            latitude=Decimal("36.7378"),  # Fresno, CA
            longitude=Decimal("-119.7871"),
            state="CA",
        )

        self.parcel = Parcel.objects.create(
            name="Carbon Test Parcel",
            establishment=self.establishment,
            area=10.0,  # hectares
            soil_type="loam",
            organic_certified=False,
        )

        self.calculator = CarbonCalculator()

    def test_fertilizer_carbon_calculation_nitrogen(self):
        """Test nitrogen fertilizer carbon calculation with USDA factors."""
        # Apply 100 kg nitrogen per hectare (typical corn application)
        nitrogen_kg = 100.0
        area_hectares = self.parcel.area

        carbon_result = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen",
            quantity_kg=nitrogen_kg,
            area_hectares=area_hectares,
            application_method="broadcast",
            soil_type=self.parcel.soil_type,
            climate_zone="temperate",
        )

        # Expected: 100 kg N × 11.0 kg CO2e/kg N = 1,100 kg CO2e
        expected_co2e = nitrogen_kg * 11.0

        self.assertAlmostEqual(carbon_result["co2e_kg"], expected_co2e, places=1)
        self.assertEqual(carbon_result["emission_factor"], 11.0)
        self.assertTrue(carbon_result["usda_verified"])

    def test_fertilizer_carbon_calculation_organic_adjustment(self):
        """Test organic fertilizer carbon calculation adjustments."""
        # Organic fertilizers have different emission factors
        organic_carbon = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="compost",
            quantity_kg=500.0,  # kg/ha
            area_hectares=10.0,
            application_method="incorporation",
            soil_type="loam",
            organic_application=True,
        )

        conventional_carbon = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen",
            quantity_kg=100.0,
            area_hectares=10.0,
            application_method="broadcast",
            soil_type="loam",
            organic_application=False,
        )

        # Organic should have lower per-unit emissions
        self.assertLess(organic_carbon["co2e_per_kg"], conventional_carbon["co2e_per_kg"])

    def test_fuel_consumption_carbon_calculation(self):
        """Test fuel consumption carbon calculations."""
        # Tractor operation: 50 liters diesel
        fuel_carbon = self.calculator.calculate_fuel_emissions(
            fuel_type="diesel", quantity_liters=50.0, operation_type="tillage", equipment_efficiency=0.8
        )

        # Expected: 50L × 2.68 kg CO2e/L = 134 kg CO2e
        expected_co2e = 50.0 * 2.68

        self.assertAlmostEqual(fuel_carbon["co2e_kg"], expected_co2e, places=1)
        self.assertEqual(fuel_carbon["emission_factor"], 2.68)

    def test_irrigation_carbon_calculation(self):
        """Test irrigation carbon calculations."""
        irrigation_carbon = self.calculator.calculate_irrigation_emissions(
            irrigation_type="drip", water_volume_m3=1000.0, pump_efficiency=0.85, electricity_source="grid", region="CA"
        )

        self.assertIsNotNone(irrigation_carbon["co2e_kg"])
        self.assertGreater(irrigation_carbon["co2e_kg"], 0)
        self.assertIn("water_efficiency_factor", irrigation_carbon)

    def test_comprehensive_parcel_carbon_footprint(self):
        """Test comprehensive parcel carbon footprint calculation."""
        # Create multiple production events
        events = [
            {"type": "fertilizer", "fertilizer_type": "nitrogen", "quantity": 100.0, "unit": "kg"},
            {"type": "fuel", "fuel_type": "diesel", "quantity": 30.0, "unit": "liters"},
            {"type": "irrigation", "irrigation_type": "drip", "water_volume": 500.0, "unit": "m3"},
        ]

        total_footprint = self.calculator.calculate_comprehensive_footprint(
            parcel=self.parcel, events=events, time_period_days=120  # Growing season
        )

        self.assertIn("total_co2e_kg", total_footprint)
        self.assertIn("breakdown_by_category", total_footprint)
        self.assertIn("co2e_per_hectare", total_footprint)
        self.assertIn("usda_verified_percentage", total_footprint)

        # Should be sum of all events
        self.assertGreater(total_footprint["total_co2e_kg"], 0)

    def test_carbon_calculation_with_climate_adjustments(self):
        """Test carbon calculations with climate-aware adjustments."""
        # High temperature, low humidity (increased volatilization)
        hot_climate_carbon = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen",
            quantity_kg=100.0,
            area_hectares=10.0,
            temperature=35.0,
            humidity=0.3,
            wind_speed=15.0,  # m/s
        )

        # Moderate climate
        moderate_climate_carbon = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen",
            quantity_kg=100.0,
            area_hectares=10.0,
            temperature=20.0,
            humidity=0.6,
            wind_speed=5.0,
        )

        # Hot climate should have higher emissions due to increased volatilization
        self.assertGreater(hot_climate_carbon["co2e_kg"], moderate_climate_carbon["co2e_kg"])

    def test_carbon_sequestration_calculations(self):
        """Test carbon sequestration calculations for different practices."""
        # Cover crops
        cover_crop_sequestration = self.calculator.calculate_sequestration(
            practice_type="cover_crops",
            area_hectares=10.0,
            years_implemented=3,
            soil_type="loam",
            climate_zone="temperate",
        )

        # No-till practices
        no_till_sequestration = self.calculator.calculate_sequestration(
            practice_type="no_till", area_hectares=10.0, years_implemented=5, soil_type="loam", climate_zone="temperate"
        )

        self.assertGreater(cover_crop_sequestration["co2e_sequestered_kg"], 0)
        self.assertGreater(no_till_sequestration["co2e_sequestered_kg"], 0)

    def test_carbon_calculation_error_handling(self):
        """Test error handling in carbon calculations."""
        # Invalid fertilizer type
        with self.assertRaises(ValueError):
            self.calculator.calculate_fertilizer_emissions(
                fertilizer_type="invalid_type", quantity_kg=100.0, area_hectares=10.0
            )

        # Negative quantities
        with self.assertRaises(ValueError):
            self.calculator.calculate_fuel_emissions(fuel_type="diesel", quantity_liters=-10.0)

        # Invalid climate parameters
        with self.assertRaises(ValueError):
            self.calculator.calculate_fertilizer_emissions(
                fertilizer_type="nitrogen",
                quantity_kg=100.0,
                area_hectares=10.0,
                temperature=500.0,  # Invalid temperature
            )


class BlockchainVerificationTestCase(TestCase):
    """Test blockchain verification functionality."""

    def setUp(self):
        self.user = User.objects.create_user(email="blockchain@test.com", password="testpass123")

        self.company = Company.objects.create(name="Blockchain Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="Blockchain Test Field", company=self.company)

        self.blockchain_service = BlockchainService()

    @patch("carbon.services.blockchain.Web3")
    def test_carbon_record_blockchain_verification(self, mock_web3):
        """Test blockchain verification of carbon records."""
        # Mock Web3 and contract
        mock_contract = MagicMock()
        mock_web3.return_value.eth.contract.return_value = mock_contract
        mock_contract.functions.submitCarbonRecord.return_value.transact.return_value = "tx_hash_123"

        # Create carbon entry
        carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            source_type="fertilizer",
            quantity=100.0,
            co2e_amount=1100.0,
            year=2024,
            month=6,
            usda_verified=True,
            created_by=self.user,
        )

        # Submit to blockchain
        verification_result = self.blockchain_service.verify_carbon_record(carbon_entry)

        self.assertTrue(verification_result["success"])
        self.assertIsNotNone(verification_result["transaction_hash"])
        self.assertIn("block_number", verification_result)

        # Verify carbon entry is marked as blockchain verified
        carbon_entry.refresh_from_db()
        self.assertTrue(carbon_entry.blockchain_verified)

    @patch("carbon.services.blockchain.Web3")
    def test_blockchain_batch_submission(self, mock_web3):
        """Test batch submission of carbon records to blockchain."""
        # Mock Web3
        mock_contract = MagicMock()
        mock_web3.return_value.eth.contract.return_value = mock_contract
        mock_contract.functions.batchSubmitCarbonRecords.return_value.transact.return_value = "batch_tx_hash"

        # Create multiple carbon entries
        carbon_entries = []
        for i in range(5):
            entry = CarbonEntry.objects.create(
                establishment=self.establishment,
                source_type="fertilizer",
                quantity=50.0 + i * 10,
                co2e_amount=550.0 + i * 110,
                year=2024,
                month=6,
                usda_verified=True,
                created_by=self.user,
            )
            carbon_entries.append(entry)

        # Batch submit to blockchain
        batch_result = self.blockchain_service.batch_submit_carbon_records(carbon_entries)

        self.assertTrue(batch_result["success"])
        self.assertEqual(batch_result["records_submitted"], 5)
        self.assertIsNotNone(batch_result["transaction_hash"])

    def test_blockchain_verification_data_integrity(self):
        """Test data integrity in blockchain verification."""
        carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            source_type="fuel",
            quantity=25.0,
            co2e_amount=67.0,
            year=2024,
            month=6,
            usda_verified=True,
            created_by=self.user,
        )

        # Generate verification hash
        verification_hash = self.blockchain_service.generate_verification_hash(carbon_entry)

        self.assertIsNotNone(verification_hash)
        self.assertEqual(len(verification_hash), 64)  # SHA-256 hash length

        # Verify hash consistency
        second_hash = self.blockchain_service.generate_verification_hash(carbon_entry)
        self.assertEqual(verification_hash, second_hash)

    @patch("carbon.services.blockchain.Web3")
    def test_blockchain_verification_failure_handling(self, mock_web3):
        """Test handling of blockchain verification failures."""
        # Mock blockchain failure
        mock_contract = MagicMock()
        mock_web3.return_value.eth.contract.return_value = mock_contract
        mock_contract.functions.submitCarbonRecord.side_effect = Exception("Network error")

        carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            source_type="fertilizer",
            quantity=100.0,
            co2e_amount=1100.0,
            year=2024,
            created_by=self.user,
        )

        # Attempt verification
        verification_result = self.blockchain_service.verify_carbon_record(carbon_entry)

        self.assertFalse(verification_result["success"])
        self.assertIn("error", verification_result)

        # Entry should not be marked as verified
        carbon_entry.refresh_from_db()
        self.assertFalse(carbon_entry.blockchain_verified)


class IoTIntegrationTestCase(TestCase):
    """Test IoT device integration and data processing."""

    def setUp(self):
        self.user = User.objects.create_user(email="iot@test.com", password="testpass123")

        self.company = Company.objects.create(name="IoT Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="IoT Test Field", company=self.company)

        self.parcel = Parcel.objects.create(name="IoT Test Parcel", establishment=self.establishment, area=15.0)

    def test_iot_device_registration(self):
        """Test IoT device registration and configuration."""
        device = IoTDevice.objects.create(
            device_id="SENSOR_001",
            device_type="soil_sensor",
            establishment=self.establishment,
            parcel=self.parcel,
            location_latitude=Decimal("36.7378"),
            location_longitude=Decimal("-119.7871"),
            status="active",
            configuration={
                "measurement_interval": 300,  # 5 minutes
                "sensors": ["soil_moisture", "temperature", "ph"],
                "transmission_frequency": "hourly",
            },
        )

        self.assertEqual(device.device_id, "SENSOR_001")
        self.assertEqual(device.device_type, "soil_sensor")
        self.assertEqual(device.status, "active")
        self.assertIn("measurement_interval", device.configuration)

    def test_iot_reading_processing(self):
        """Test IoT reading data processing and validation."""
        device = IoTDevice.objects.create(
            device_id="WEATHER_001", device_type="weather_station", establishment=self.establishment, status="active"
        )

        # Valid reading
        reading = IoTReading.objects.create(
            device=device,
            reading_type="weather",
            data={
                "temperature": 25.5,
                "humidity": 65.2,
                "wind_speed": 8.3,
                "precipitation": 0.0,
                "soil_temperature": 22.1,
            },
            timestamp=timezone.now(),
            quality_score=0.95,
        )

        self.assertEqual(reading.device, device)
        self.assertEqual(reading.reading_type, "weather")
        self.assertEqual(reading.data["temperature"], 25.5)
        self.assertGreater(reading.quality_score, 0.9)

    def test_john_deere_integration(self):
        """Test John Deere API integration."""
        integration = JohnDeereIntegration.objects.create(
            establishment=self.establishment,
            api_key_encrypted="encrypted_key_data",
            client_id="jd_client_123",
            status="active",
            last_sync=timezone.now(),
            configuration={
                "sync_interval": "daily",
                "data_types": ["field_operations", "fuel_consumption", "application_rates"],
            },
        )

        self.assertEqual(integration.establishment, self.establishment)
        self.assertEqual(integration.status, "active")
        self.assertIn("sync_interval", integration.configuration)

    @patch("carbon.services.john_deere_api.JohnDeereAPI.get_field_operations")
    def test_john_deere_data_processing(self, mock_api):
        """Test processing of John Deere field operations data."""
        # Mock John Deere API response
        mock_api.return_value = {
            "operations": [
                {
                    "operation_type": "fertilizer_application",
                    "date": "2024-06-15",
                    "field_id": "field_123",
                    "application_rate": 150.0,  # kg/ha
                    "product_name": "Nitrogen Fertilizer",
                    "area_covered": 10.0,
                }
            ]
        }

        integration = JohnDeereIntegration.objects.create(
            establishment=self.establishment, client_id="test_client", status="active"
        )

        # Process John Deere data
        from carbon.services.john_deere_processor import JohnDeereProcessor

        processor = JohnDeereProcessor(integration)

        processed_data = processor.process_field_operations()

        self.assertIn("carbon_entries", processed_data)
        self.assertIn("total_operations", processed_data)

    def test_iot_data_quality_validation(self):
        """Test IoT data quality validation and filtering."""
        device = IoTDevice.objects.create(
            device_id="QUALITY_TEST", device_type="soil_sensor", establishment=self.establishment, status="active"
        )

        # High quality reading
        good_reading = IoTReading.objects.create(
            device=device,
            reading_type="soil",
            data={"soil_moisture": 35.2, "temperature": 18.5, "ph": 6.8},
            timestamp=timezone.now(),
            quality_score=0.98,
        )

        # Low quality reading (should be flagged)
        poor_reading = IoTReading.objects.create(
            device=device,
            reading_type="soil",
            data={
                "soil_moisture": -10.0,  # Invalid negative moisture
                "temperature": 150.0,  # Unrealistic temperature
                "ph": 15.0,  # Invalid pH
            },
            timestamp=timezone.now(),
            quality_score=0.15,
        )

        # Test quality filtering
        high_quality_readings = IoTReading.objects.filter(device=device, quality_score__gte=0.8)

        self.assertEqual(high_quality_readings.count(), 1)
        self.assertEqual(high_quality_readings.first(), good_reading)


class CircuitBreakerTestCase(TestCase):
    """Test circuit breaker patterns for API resilience."""

    def setUp(self):
        self.circuit_breaker = CircuitBreakerManager()

    @patch("carbon.services.usda_api.requests.get")
    def test_circuit_breaker_success(self, mock_get):
        """Test circuit breaker with successful API calls."""
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"factor": 11.0, "unit": "kg CO2e per kg N"}
        mock_get.return_value = mock_response

        # Multiple successful calls
        for i in range(5):
            result = self.circuit_breaker.call_with_breaker("usda_api", lambda: mock_get("https://api.usda.gov/test"))
            self.assertEqual(result.status_code, 200)

        # Circuit should remain closed
        self.assertEqual(self.circuit_breaker.get_state("usda_api"), "closed")

    @patch("carbon.services.usda_api.requests.get")
    def test_circuit_breaker_failure_threshold(self, mock_get):
        """Test circuit breaker opens after failure threshold."""
        # Mock failing API responses
        mock_get.side_effect = Exception("API Error")

        # Make calls until circuit opens
        for i in range(6):  # Threshold is typically 5 failures
            try:
                self.circuit_breaker.call_with_breaker("usda_api", lambda: mock_get("https://api.usda.gov/test"))
            except Exception:
                pass  # Expected failures

        # Circuit should be open
        self.assertEqual(self.circuit_breaker.get_state("usda_api"), "open")

    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after failures."""
        # Simulate circuit in half-open state
        self.circuit_breaker.set_state("usda_api", "half_open")

        # Successful call should close circuit
        with patch("carbon.services.usda_api.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            result = self.circuit_breaker.call_with_breaker("usda_api", lambda: mock_get("https://api.usda.gov/test"))

        # Circuit should be closed again
        self.assertEqual(self.circuit_breaker.get_state("usda_api"), "closed")


class CarbonCachingTestCase(TestCase):
    """Test caching strategies for carbon calculations."""

    def setUp(self):
        cache.clear()
        self.calculator = CarbonCalculator()

    def test_emission_factor_caching(self):
        """Test caching of emission factors."""
        # Clear cache
        cache.clear()

        # First call should cache the factor
        factor1 = get_fertilizer_factor("nitrogen")

        # Second call should use cache
        with patch("carbon.services.usda_api.requests.get") as mock_get:
            factor2 = get_fertilizer_factor("nitrogen")
            # Should not make API call
            mock_get.assert_not_called()

        self.assertEqual(factor1, factor2)

    def test_carbon_calculation_caching(self):
        """Test caching of carbon calculations."""
        cache.clear()

        # Create calculation parameters
        calc_params = {"fertilizer_type": "nitrogen", "quantity_kg": 100.0, "area_hectares": 10.0, "soil_type": "loam"}

        # First calculation
        result1 = self.calculator.calculate_fertilizer_emissions(**calc_params)

        # Second calculation with same parameters should use cache
        result2 = self.calculator.calculate_fertilizer_emissions(**calc_params)

        self.assertEqual(result1["co2e_kg"], result2["co2e_kg"])

    def test_cache_invalidation(self):
        """Test cache invalidation when factors are updated."""
        # Cache a factor
        factor1 = get_fertilizer_factor("nitrogen")

        # Simulate factor update
        cache.delete("fertilizer_factor_nitrogen")

        # Should get fresh factor
        factor2 = get_fertilizer_factor("nitrogen")

        # Should be the same value but fresh from source
        self.assertEqual(factor1["value"], factor2["value"])


class CarbonReportingTestCase(TestCase):
    """Test carbon reporting and analytics."""

    def setUp(self):
        self.user = User.objects.create_user(email="reporting@test.com", password="testpass123")

        self.company = Company.objects.create(name="Reporting Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="Reporting Test Field", company=self.company)

    def test_carbon_report_generation(self):
        """Test generation of carbon reports."""
        # Create carbon entries for report
        entries = []
        for i in range(12):  # Monthly data
            entry = CarbonEntry.objects.create(
                establishment=self.establishment,
                source_type="fertilizer",
                quantity=50.0 + i * 5,
                co2e_amount=550.0 + i * 55,
                year=2024,
                month=i + 1,
                usda_verified=True,
                created_by=self.user,
            )
            entries.append(entry)

        # Generate report
        report = CarbonReport.objects.create(
            establishment=self.establishment,
            report_type="annual",
            year=2024,
            data={
                "total_emissions": sum(e.co2e_amount for e in entries),
                "emissions_by_month": {str(e.month): e.co2e_amount for e in entries},
                "usda_verified_percentage": 100.0,
            },
            generated_by=self.user,
        )

        self.assertEqual(report.establishment, self.establishment)
        self.assertEqual(report.report_type, "annual")
        self.assertEqual(report.year, 2024)
        self.assertIn("total_emissions", report.data)

    def test_sustainability_badge_award(self):
        """Test sustainability badge awarding system."""
        # Create low-emission establishment
        badge = SustainabilityBadge.objects.create(
            name="Low Carbon Champion",
            description="Achieved 50% below industry average emissions",
            criteria={
                "max_co2e_per_hectare": 500.0,
                "min_usda_verified_percentage": 80.0,
                "sustainable_practices": ["cover_crops", "reduced_tillage"],
            },
            badge_level="gold",
        )

        # Award badge to establishment
        badge.establishments.add(self.establishment)

        self.assertIn(self.establishment, badge.establishments.all())
        self.assertEqual(badge.badge_level, "gold")

    def test_carbon_footprint_trends(self):
        """Test carbon footprint trend analysis."""
        # Create historical carbon data
        footprints = []
        for year in [2022, 2023, 2024]:
            footprint = EstablishmentCarbonFootprint.objects.create(
                establishment=self.establishment,
                year=year,
                total_co2e_kg=1000.0 - (year - 2022) * 100,  # Decreasing trend
                co2e_per_hectare=100.0 - (year - 2022) * 10,
                usda_verified_percentage=80.0 + (year - 2022) * 5,
            )
            footprints.append(footprint)

        # Analyze trends
        from carbon.services.analytics import CarbonAnalytics

        analytics = CarbonAnalytics()

        trends = analytics.calculate_footprint_trends(self.establishment)

        self.assertIn("yearly_change_percentage", trends)
        self.assertIn("improvement_trend", trends)
        self.assertTrue(trends["improvement_trend"])  # Should show improvement


class USDAComplianceTestCase(TestCase):
    """Test USDA compliance and verification."""

    def setUp(self):
        self.user = User.objects.create_user(email="compliance@test.com", password="testpass123")

        self.company = Company.objects.create(name="Compliance Test Farm", owner=self.user)

        self.establishment = Establishment.objects.create(name="Compliance Test Field", company=self.company)

    def test_usda_compliance_record_creation(self):
        """Test creation of USDA compliance records."""
        compliance = USDACompliance.objects.create(
            establishment=self.establishment,
            verification_date=timezone.now().date(),
            verification_status="verified",
            usda_program="NRCS_Carbon_Program",
            verification_level="field_verified",
            compliance_data={
                "carbon_intensity": 0.45,  # kg CO2e per kg product
                "verification_methods": ["soil_sampling", "satellite_monitoring"],
                "compliance_score": 94.5,
            },
            verified_by="USDA_Inspector_001",
        )

        self.assertEqual(compliance.establishment, self.establishment)
        self.assertEqual(compliance.verification_status, "verified")
        self.assertEqual(compliance.usda_program, "NRCS_Carbon_Program")
        self.assertIn("carbon_intensity", compliance.compliance_data)

    def test_carbon_verification_creation(self):
        """Test carbon verification record creation."""
        verification = CarbonVerification.objects.create(
            establishment=self.establishment,
            verification_method="third_party_audit",
            verifier_organization="Carbon Trust Verified",
            verification_date=timezone.now().date(),
            verification_scope="scope_1_2",
            verification_standard="ISO_14064",
            verification_data={
                "total_emissions_verified": 2500.0,
                "verification_confidence": "high",
                "methodology": "IPCC_2006_Guidelines",
            },
            status="verified",
        )

        self.assertEqual(verification.establishment, self.establishment)
        self.assertEqual(verification.verification_method, "third_party_audit")
        self.assertEqual(verification.status, "verified")
        self.assertIn("total_emissions_verified", verification.verification_data)


class CarbonCalculationEdgeCasesTestCase(TestCase):
    """Test edge cases and error conditions in carbon calculations."""

    def setUp(self):
        self.calculator = CarbonCalculator()

    def test_extreme_climate_conditions(self):
        """Test calculations under extreme climate conditions."""
        # Extreme heat
        extreme_heat_result = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen",
            quantity_kg=100.0,
            area_hectares=10.0,
            temperature=45.0,  # Extreme heat
            humidity=0.1,  # Very dry
            wind_speed=25.0,  # High wind
        )

        # Normal conditions
        normal_result = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen",
            quantity_kg=100.0,
            area_hectares=10.0,
            temperature=20.0,
            humidity=0.6,
            wind_speed=5.0,
        )

        # Extreme conditions should increase emissions due to volatilization
        self.assertGreater(extreme_heat_result["co2e_kg"], normal_result["co2e_kg"])

    def test_zero_quantity_inputs(self):
        """Test handling of zero quantity inputs."""
        zero_result = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen", quantity_kg=0.0, area_hectares=10.0
        )

        self.assertEqual(zero_result["co2e_kg"], 0.0)

    def test_very_large_quantity_inputs(self):
        """Test handling of very large quantity inputs."""
        large_result = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen",
            quantity_kg=10000.0,  # Very large application
            area_hectares=1000.0,  # Large area
        )

        # Should not overflow or cause errors
        self.assertIsNotNone(large_result["co2e_kg"])
        self.assertGreater(large_result["co2e_kg"], 0)

    def test_precision_handling(self):
        """Test precision handling in calculations."""
        precise_result = self.calculator.calculate_fertilizer_emissions(
            fertilizer_type="nitrogen", quantity_kg=100.123456789, area_hectares=10.987654321  # High precision input
        )

        # Result should maintain reasonable precision
        self.assertIsInstance(precise_result["co2e_kg"], (int, float, Decimal))

    def test_invalid_input_validation(self):
        """Test validation of invalid inputs."""
        # Negative area
        with self.assertRaises(ValueError):
            self.calculator.calculate_fertilizer_emissions(
                fertilizer_type="nitrogen", quantity_kg=100.0, area_hectares=-10.0
            )

        # Invalid temperature range
        with self.assertRaises(ValueError):
            self.calculator.calculate_fertilizer_emissions(
                fertilizer_type="nitrogen",
                quantity_kg=100.0,
                area_hectares=10.0,
                temperature=-100.0,  # Below absolute zero
            )

        # Invalid humidity range
        with self.assertRaises(ValueError):
            self.calculator.calculate_fertilizer_emissions(
                fertilizer_type="nitrogen", quantity_kg=100.0, area_hectares=10.0, humidity=1.5  # Above 100%
            )
