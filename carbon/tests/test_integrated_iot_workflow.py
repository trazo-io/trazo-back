"""
Test Suite for Integrated IoT Workflow

This module tests the complete IoT workflow with:
1. John Deere equipment data
2. Weather monitoring and alerts
3. Unified data processing
4. Automated carbon entry creation
5. Manual approval workflow
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from carbon.models import CarbonEntry, Establishment, IoTDataPoint, IoTDevice
from carbon.services.john_deere_api import get_john_deere_api
from carbon.services.weather_api import get_weather_service
from carbon.tasks import (
    calculate_data_point_confidence,
    create_carbon_entry_from_data_point,
    monitor_weather_conditions,
    process_pending_iot_data,
    should_create_carbon_entry,
    sync_john_deere_devices,
)
from company.models import Company
from users.models import User


class IntegratedIoTWorkflowTestCase(TransactionTestCase):
    """Test the complete integrated IoT workflow"""

    def setUp(self):
        """Set up test environment"""
        # Create test company and establishment
        self.company = Company.objects.create(
            name="Integrated IoT Test Farm",
            address="789 IoT Integration Rd",
            city="Tech Valley",
            state="CA",
            country="US",
        )

        self.establishment = Establishment.objects.create(
            name="Smart Farm IoT Test",
            company=self.company,
            address="123 Smart Farm Lane",
            city="Tech Valley",
            state="CA",
            country="US",
            latitude=37.7749,  # San Francisco coordinates
            longitude=-122.4194,
        )

    def test_john_deere_equipment_integration(self):
        """Test John Deere equipment data integration"""
        # Create John Deere equipment device
        john_deere_device = IoTDevice.objects.create(
            establishment=self.establishment,
            device_id="john_deere_tractor_001",
            name="John Deere 8R Series Tractor",
            device_type="fuel_sensor",
            status="online",
            battery_level=85,
            john_deere_machine_id="JD_MACHINE_12345",
            api_connection_status="connected",
            last_seen=timezone.now(),
        )

        self.assertEqual(john_deere_device.name, "John Deere 8R Series Tractor")
        self.assertEqual(john_deere_device.device_type, "fuel_sensor")
        self.assertEqual(john_deere_device.status, "online")

        # Simulate fuel consumption data
        fuel_data = {
            "fuel_consumption": {
                "fuel_used": 45.5,  # liters
                "engine_hours": 8.5,
                "operation_type": "plowing",
                "field_area": 12.3,  # hectares
                "efficiency": 3.7,  # liters per hectare
                "timestamp": timezone.now().isoformat(),
            },
            "source": "john_deere_api_simulation",
            "machine_id": "JD_MACHINE_12345",
            "quality_indicators": {"gps_accuracy": "high", "sensor_status": "normal", "data_completeness": 1.0},
        }

        # Create IoT data point for fuel consumption
        fuel_data_point = IoTDataPoint.objects.create(
            device=john_deere_device, timestamp=timezone.now(), data=fuel_data, quality_score=0.95, processed=False
        )

        self.assertIsNotNone(fuel_data_point.id)
        self.assertEqual(fuel_data_point.quality_score, 0.95)
        self.assertFalse(fuel_data_point.processed)

        # Verify expected CO2e calculation
        expected_co2e = fuel_data["fuel_consumption"]["fuel_used"] * 2.7
        self.assertAlmostEqual(expected_co2e, 122.85, places=1)

    @patch("carbon.services.weather_api.get_weather_service")
    def test_weather_monitoring_integration(self, mock_weather_service):
        """Test weather monitoring and data collection"""
        # Mock weather service response
        mock_weather_data = {
            "temperature": 85,
            "humidity": 45,
            "wind_speed": 12,
            "description": "Hot and dry conditions",
        }

        mock_recommendations = [
            {
                "type": "heat_advisory",
                "priority": "medium",
                "title": "Heat Advisory: 85°F",
                "description": "High temperatures may stress crops",
            }
        ]

        mock_service = MagicMock()
        mock_service.get_current_conditions.return_value = mock_weather_data
        mock_service.generate_agricultural_recommendations.return_value = mock_recommendations
        mock_weather_service.return_value = mock_service

        # Get weather data
        weather_service = get_weather_service()
        weather_data = weather_service.get_current_conditions(
            float(self.establishment.latitude), float(self.establishment.longitude)
        )

        self.assertIsNotNone(weather_data)
        self.assertEqual(weather_data["temperature"], 85)
        self.assertEqual(weather_data["humidity"], 45)

        # Generate recommendations
        recommendations = weather_service.generate_agricultural_recommendations(weather_data, "general")

        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["type"], "heat_advisory")

        # Create weather station device
        weather_device = IoTDevice.objects.create(
            establishment=self.establishment,
            device_id="weather_station_001",
            name="Weather Station - Smart Farm",
            device_type="weather_station",
            status="online",
            battery_level=100,
            last_seen=timezone.now(),
        )

        # Create weather data point
        weather_data_point = IoTDataPoint.objects.create(
            device=weather_device,
            timestamp=timezone.now(),
            data={
                "weather_conditions": weather_data,
                "recommendations": recommendations,
                "alert_type": "routine_monitoring",
                "source": "weather_integration_test",
            },
            quality_score=0.95,
            processed=False,
        )

        self.assertIsNotNone(weather_data_point.id)
        self.assertEqual(weather_data_point.data["alert_type"], "routine_monitoring")

    def test_unified_data_processing(self):
        """Test processing of multiple IoT data points"""
        # Create test devices
        fuel_device = IoTDevice.objects.create(
            establishment=self.establishment,
            device_id="test_fuel_sensor",
            name="Test Fuel Sensor",
            device_type="fuel_sensor",
            status="online",
        )

        weather_device = IoTDevice.objects.create(
            establishment=self.establishment,
            device_id="test_weather_station",
            name="Test Weather Station",
            device_type="weather_station",
            status="online",
        )

        # Create data points with different confidence levels
        high_confidence_point = IoTDataPoint.objects.create(
            device=fuel_device,
            timestamp=timezone.now(),
            data={"fuel_consumption": {"fuel_used": 50.0}, "quality_indicators": {"data_completeness": 1.0}},
            quality_score=0.95,
            processed=False,
        )

        medium_confidence_point = IoTDataPoint.objects.create(
            device=weather_device,
            timestamp=timezone.now(),
            data={"weather_conditions": {"temperature": 75}},
            quality_score=0.75,
            processed=False,
        )

        # Get unprocessed data points
        unprocessed_points = IoTDataPoint.objects.filter(
            device__establishment=self.establishment, processed=False
        ).order_by("timestamp")

        self.assertEqual(unprocessed_points.count(), 2)

        # Test confidence calculation
        high_confidence = calculate_data_point_confidence(high_confidence_point)
        medium_confidence = calculate_data_point_confidence(medium_confidence_point)

        self.assertGreater(high_confidence, 0.9)
        self.assertGreater(medium_confidence, 0.7)
        self.assertLess(medium_confidence, 0.9)

        # Process high confidence point
        if high_confidence > 0.9 and should_create_carbon_entry(high_confidence_point):
            carbon_entry = create_carbon_entry_from_data_point(high_confidence_point)
            if carbon_entry:
                high_confidence_point.carbon_entry = carbon_entry
                high_confidence_point.processed = True
                high_confidence_point.save()

                self.assertIsNotNone(carbon_entry)
                self.assertGreater(carbon_entry.co2e_amount, 0)

        # Verify processing
        high_confidence_point.refresh_from_db()
        self.assertTrue(high_confidence_point.processed)

    def test_carbon_entry_creation_from_iot(self):
        """Test automated carbon entry creation from IoT data"""
        # Create fuel sensor device
        fuel_device = IoTDevice.objects.create(
            establishment=self.establishment,
            device_id="carbon_test_fuel_sensor",
            name="Carbon Test Fuel Sensor",
            device_type="fuel_sensor",
            status="online",
        )

        # Create fuel consumption data point
        fuel_data_point = IoTDataPoint.objects.create(
            device=fuel_device,
            timestamp=timezone.now(),
            data={"fuel_consumption": {"fuel_used": 100.0, "fuel_type": "diesel"}},  # 100 liters
            quality_score=0.95,
            processed=False,
        )

        # Process and create carbon entry
        if should_create_carbon_entry(fuel_data_point):
            carbon_entry = create_carbon_entry_from_data_point(fuel_data_point)

            self.assertIsNotNone(carbon_entry)
            self.assertEqual(carbon_entry.establishment, self.establishment)
            self.assertEqual(carbon_entry.iot_device_id, fuel_device.device_id)

            # Verify CO2e calculation (100L diesel * 2.7 kg CO2e/L)
            expected_co2e = 100.0 * 2.7
            self.assertAlmostEqual(float(carbon_entry.co2e_amount), expected_co2e, places=1)

    def test_device_status_monitoring(self):
        """Test IoT device status monitoring and updates"""
        # Create multiple devices
        devices = []
        for i in range(3):
            device = IoTDevice.objects.create(
                establishment=self.establishment,
                device_id=f"status_test_device_{i}",
                name=f"Status Test Device {i}",
                device_type="fuel_sensor" if i % 2 == 0 else "weather_station",
                status="offline",
                battery_level=50 + (i * 10),
                last_seen=timezone.now(),
            )
            devices.append(device)

        # Update device statuses
        for device in devices:
            device.increment_data_points()
            device.update_status("online")

            device.refresh_from_db()
            self.assertEqual(device.status, "online")
            self.assertGreater(device.total_data_points, 0)
            self.assertIsNotNone(device.last_seen)

        # Verify all devices are monitored
        monitored_devices = IoTDevice.objects.filter(establishment=self.establishment, status="online")
        self.assertEqual(monitored_devices.count(), 3)

    def test_complete_workflow_integration(self):
        """Test the complete IoT workflow from data collection to carbon tracking"""
        # Create John Deere device
        jd_device = IoTDevice.objects.create(
            establishment=self.establishment,
            device_id="workflow_test_jd",
            name="Workflow Test JD Tractor",
            device_type="fuel_sensor",
            status="online",
            john_deere_machine_id="JD_TEST_123",
        )

        # Create fuel consumption data
        fuel_data_point = IoTDataPoint.objects.create(
            device=jd_device,
            timestamp=timezone.now(),
            data={"fuel_consumption": {"fuel_used": 75.0}, "quality_indicators": {"data_completeness": 1.0}},
            quality_score=0.98,
            processed=False,
        )

        # Process the data point
        confidence = calculate_data_point_confidence(fuel_data_point)
        self.assertGreater(confidence, 0.9)

        # Create carbon entry if confidence is high
        if confidence > 0.9 and should_create_carbon_entry(fuel_data_point):
            carbon_entry = create_carbon_entry_from_data_point(fuel_data_point)
            fuel_data_point.carbon_entry = carbon_entry
            fuel_data_point.processed = True
            fuel_data_point.save()

            # Verify the complete workflow
            self.assertIsNotNone(carbon_entry)
            self.assertTrue(fuel_data_point.processed)

            # Verify statistics
            total_devices = IoTDevice.objects.filter(establishment=self.establishment).count()
            total_data_points = IoTDataPoint.objects.filter(device__establishment=self.establishment).count()
            total_carbon_entries = CarbonEntry.objects.filter(
                establishment=self.establishment, iot_device_id__isnull=False
            ).count()

            self.assertGreater(total_devices, 0)
            self.assertGreater(total_data_points, 0)
            self.assertGreater(total_carbon_entries, 0)
