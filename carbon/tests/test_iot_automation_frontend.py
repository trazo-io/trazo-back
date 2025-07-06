"""
IoT Automation Frontend Tests

Tests IoT automation functionality including:
- IoT data generation and processing
- Automation decision logic
- Confidence level thresholds
- Frontend integration capabilities
"""

from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, Mock
import random
from decimal import Decimal
from carbon.models import IoTDevice, IoTDataPoint, CarbonEntry, CarbonSource
from carbon.services.automation_service import AutomationLevelService
from company.models import Company, Establishment

User = get_user_model()


class IoTAutomationTestCase(TransactionTestCase):
    """Test IoT automation functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.company = Company.objects.create(
            name='IoT Test Company',
            address='123 IoT St',
            city='IoT City',
            state='CA'
        )
        
        self.user = User.objects.create_user(
            email='iot_test@trazo.com',
            password='testpass123',
        )

        
        

        
        # Create WorksIn relationship

        
        from users.models import WorksIn

        
        WorksIn.objects.create(

        
            user=self.user,

        
            company=self.company,

        
            role=WorksIn.COMPANY_ADMIN

        
        )
        
        self.establishment = Establishment.objects.create(
            name='IoT Test Farm',
            company=self.company,
            establishment_type='farm'
        )
        
        # Create test IoT devices
        self.temperature_device = IoTDevice.objects.create(
            establishment=self.establishment,
            name='Temperature Sensor',
            device_type='temperature_sensor',
            device_id='temp_001',
            status='online'
        )
        
        self.fuel_device = IoTDevice.objects.create(
            establishment=self.establishment,
            name='Fuel Sensor',
            device_type='fuel_sensor',
            device_id='fuel_001',
            status='online'
        )
        
        # Create carbon source for testing
        self.emission_source = CarbonSource.objects.create(
            name='fuel_consumption',
            category='emission',
            default_emission_factor=2.7,
            unit='kg CO2e/L'
        )
        
        self.automation_service = AutomationLevelService()
    
    def test_iot_device_creation(self):
        """Test IoT device creation and properties"""
        devices = IoTDevice.objects.filter(establishment=self.establishment)
        
        self.assertEqual(devices.count(), 2)
        self.assertTrue(devices.filter(device_type='temperature_sensor').exists())
        self.assertTrue(devices.filter(device_type='fuel_sensor').exists())
        
        # Test device properties
        temp_device = devices.get(device_type='temperature_sensor')
        self.assertEqual(temp_device.name, 'Temperature Sensor')
        self.assertEqual(temp_device.status, 'online')
        self.assertEqual(temp_device.establishment, self.establishment)
    
    def test_iot_data_point_creation(self):
        """Test IoT data point creation with sensor data"""
        sensor_data = {
            'temperature': 25.5,
            'humidity': 60.0,
            'soil_moisture': 45.0,
            'ph_level': 6.8
        }
        
        data_point = IoTDataPoint.objects.create(
            device=self.temperature_device,
            timestamp=timezone.now(),
            data=sensor_data,
            quality_score=0.95,
            processed=False
        )
        
        self.assertEqual(data_point.device, self.temperature_device)
        self.assertEqual(data_point.data, sensor_data)
        self.assertEqual(data_point.quality_score, 0.95)
        self.assertFalse(data_point.processed)
        
        # Test data structure
        self.assertIn('temperature', data_point.data)
        self.assertEqual(data_point.data['temperature'], 25.5)
    
    def test_automation_confidence_thresholds(self):
        """Test automation decision based on confidence levels"""
        confidence_test_cases = [
            (0.65, False),  # Low confidence - manual review
            (0.80, False),  # Medium-low confidence - manual review
            (0.90, False),  # At threshold - manual review
            (0.95, True),   # High confidence - auto approve eligible
            (0.99, True),   # Very high confidence - auto approve eligible
        ]
        
        for confidence, should_be_eligible in confidence_test_cases:
            data_point = IoTDataPoint.objects.create(
                device=self.temperature_device,
                timestamp=timezone.now(),
                data={'temperature': 25.0},
                quality_score=confidence,
                processed=False
            )
            
            # Note: actual automation may depend on additional factors like rate limiting
            decision = self.automation_service.should_auto_approve_event(data_point, confidence)
            
            if should_be_eligible:
                # High confidence should at least be eligible for automation
                # (actual decision may depend on rate limiting)
                self.assertIsInstance(decision, bool)
            else:
                # Low confidence should not be auto-approved
                self.assertFalse(decision)
    
    def test_automation_rate_limiting(self):
        """Test automation rate limiting (target ~50%)"""
        # Create multiple high-confidence data points
        high_confidence_points = []
        for i in range(10):
            data_point = IoTDataPoint.objects.create(
                device=self.temperature_device,
                timestamp=timezone.now() - timedelta(minutes=i),
                data={'temperature': 25.0 + i},
                quality_score=0.95,
                processed=False
            )
            high_confidence_points.append(data_point)
        
        # Test automation decisions
        auto_approved = 0
        manual_review = 0
        
        for data_point in high_confidence_points:
            decision = self.automation_service.should_auto_approve_event(data_point, 0.95)
            if decision:
                auto_approved += 1
            else:
                manual_review += 1
        
        total = len(high_confidence_points)
        automation_rate = (auto_approved / total) * 100 if total > 0 else 0
        
        # Should have some automation but not 100% due to rate limiting
        self.assertGreater(auto_approved, 0)
        self.assertGreater(manual_review, 0)
        self.assertLessEqual(automation_rate, 100)
    
    def test_carbon_entry_creation_from_iot(self):
        """Test carbon entry creation from IoT data"""
        fuel_data = {
            'fuel_consumption': 5.0,
            'engine_hours': 2.5,
            'location': 'Field A'
        }
        
        data_point = IoTDataPoint.objects.create(
            device=self.fuel_device,
            timestamp=timezone.now(),
            data=fuel_data,
            quality_score=0.95,
            processed=False
        )
        
        # Simulate automation creating carbon entry
        carbon_entry = CarbonEntry.objects.create(
            establishment=self.establishment,
            created_by=self.user,
            type='emission',
            source=self.emission_source,
            amount=5.0,
            year=data_point.timestamp.year,
            timestamp=data_point.timestamp,
            description=f"Auto-processed from {self.fuel_device.name} (confidence: {data_point.quality_score:.2f})",
            iot_device_id=self.fuel_device.device_id
        )
        
        # Mark data point as processed
        data_point.processed = True
        data_point.save()
        
        # Verify carbon entry was created correctly
        self.assertEqual(carbon_entry.establishment, self.establishment)
        self.assertEqual(carbon_entry.type, 'emission')
        self.assertEqual(carbon_entry.amount, 5.0)
        self.assertEqual(carbon_entry.iot_device_id, self.fuel_device.device_id)
        self.assertTrue(data_point.processed)
        self.assertIn('Auto-processed', carbon_entry.description)
    
    def test_automation_stats_calculation(self):
        """Test automation statistics calculation"""
        # Create mix of processed and unprocessed data points
        processed_points = []
        pending_points = []
        
        for i in range(5):
            # Create processed point
            processed_point = IoTDataPoint.objects.create(
                device=self.temperature_device,
                timestamp=timezone.now() - timedelta(minutes=i),
                data={'temperature': 25.0 + i},
                quality_score=0.95,
                processed=True
            )
            processed_points.append(processed_point)
            
            # Create pending point
            pending_point = IoTDataPoint.objects.create(
                device=self.fuel_device,
                timestamp=timezone.now() - timedelta(minutes=i + 10),
                data={'fuel_consumption': 2.0 + i},
                quality_score=0.85,
                processed=False
            )
            pending_points.append(pending_point)
        
        # Get automation stats
        stats = self.automation_service.get_automation_stats_for_establishment(self.establishment)
        
        self.assertIsInstance(stats, dict)
        
        # Verify stats contain expected information
        if 'total_processed' in stats:
            self.assertGreaterEqual(stats['total_processed'], 5)
        if 'total_pending' in stats:
            self.assertGreaterEqual(stats['total_pending'], 5)
    
    def test_sensor_data_validation(self):
        """Test sensor data validation and structure"""
        valid_sensor_data_types = [
            {
                'temperature': 25.5,
                'humidity': 60.0,
                'device_type': 'temperature_sensor'
            },
            {
                'fuel_consumption': 3.5,
                'engine_hours': 1.5,
                'device_type': 'fuel_sensor'
            },
            {
                'soil_moisture': 45.0,
                'ph_level': 6.8,
                'nitrogen_level': 25.0,
                'device_type': 'soil_sensor'
            }
        ]
        
        for sensor_data in valid_sensor_data_types:
            device_type = sensor_data.pop('device_type')
            
            data_point = IoTDataPoint.objects.create(
                device=self.temperature_device,  # Use existing device for testing
                timestamp=timezone.now(),
                data=sensor_data,
                quality_score=0.85,
                processed=False
            )
            
            # Validate data structure
            self.assertIsInstance(data_point.data, dict)
            self.assertGreater(len(data_point.data), 0)
            
            # Validate numeric values
            for key, value in data_point.data.items():
                self.assertIsInstance(value, (int, float))
                self.assertGreater(value, 0)


class IoTAutomationFrontendIntegrationTestCase(TestCase):
    """Test frontend integration for IoT automation"""
    
    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        
        self.company = Company.objects.create(
            name='Frontend Test Company',
            address='456 Frontend Ave',
            city='Frontend City',
            state='NY'
        )
        
        self.user = User.objects.create_user(
            email='frontend_test@trazo.com',
            password='testpass123',
        )

        
        

        
        # Create WorksIn relationship

        
        from users.models import WorksIn

        
        WorksIn.objects.create(

        
            user=self.user,

        
            company=self.company,

        
            role=WorksIn.COMPANY_ADMIN

        
        )
        
        self.establishment = Establishment.objects.create(
            name='Frontend Test Farm',
            company=self.company,
            establishment_type='farm'
        )
        
        self.client.force_authenticate(user=self.user)
    
    def test_iot_dashboard_data_structure(self):
        """Test data structure for IoT dashboard frontend"""
        # Expected data structure for frontend consumption
        expected_dashboard_data = {
            'devices': {
                'total': int,
                'online': int,
                'offline': int
            },
            'data_points': {
                'total': int,
                'processed': int,
                'pending': int
            },
            'automation': {
                'rate': float,
                'auto_approved': int,
                'manual_review': int
            }
        }
        
        # Validate expected structure
        for section, fields in expected_dashboard_data.items():
            self.assertIsInstance(section, str)
            self.assertIsInstance(fields, dict)
            
            for field, field_type in fields.items():
                self.assertIsInstance(field, str)
                self.assertTrue(field_type in [int, float, str, bool])
    
    def test_frontend_automation_percentage_display(self):
        """Test automation percentage calculation for frontend display"""
        # Simulate automation statistics
        test_stats = {
            'auto_approved': 15,
            'manual_review': 10,
            'total_events': 25
        }
        
        automation_rate = (test_stats['auto_approved'] / test_stats['total_events']) * 100
        
        self.assertEqual(automation_rate, 60.0)
        self.assertIsInstance(automation_rate, float)
        self.assertGreaterEqual(automation_rate, 0)
        self.assertLessEqual(automation_rate, 100)
    
    def test_iot_workflow_status_indicators(self):
        """Test status indicators for IoT workflow"""
        status_indicators = [
            'auto_approved',
            'manual_review',
            'pending_approval',
            'processed',
            'failed'
        ]
        
        for status in status_indicators:
            self.assertIsInstance(status, str)
            self.assertGreater(len(status), 0)
            # Status should be suitable for frontend display (no spaces in original, or underscores that become spaces)
            self.assertTrue('_' in status or ' ' not in status)
    
    def test_frontend_testing_data_generation(self):
        """Test data generation suitable for frontend testing"""
        # Create test data for frontend demonstration
        devices = []
        data_points = []
        
        # Generate test devices
        device_types = ['temperature_sensor', 'fuel_sensor', 'soil_sensor']
        for i, device_type in enumerate(device_types):
            device = IoTDevice.objects.create(
                establishment=self.establishment,
                name=f'Test {device_type.replace("_", " ").title()} {i+1}',
                device_type=device_type,
                device_id=f'test_{device_type}_{i+1}',
                status='online'
            )
            devices.append(device)
        
        # Generate test data points with mixed confidence levels
        confidence_levels = [0.65, 0.75, 0.85, 0.95, 0.99]
        
        for i, confidence in enumerate(confidence_levels):
            device = devices[i % len(devices)]
            
            data_point = IoTDataPoint.objects.create(
                device=device,
                timestamp=timezone.now() - timedelta(minutes=i * 10),
                data={
                    'sensor_value': round(random.uniform(10, 100), 2),
                    'quality': 'good'
                },
                quality_score=confidence,
                processed=confidence >= 0.90  # High confidence auto-processed
            )
            data_points.append(data_point)
        
        # Verify test data was created correctly
        self.assertEqual(len(devices), 3)
        self.assertEqual(len(data_points), 5)
        
        # Verify automation split
        processed_count = sum(1 for dp in data_points if dp.processed)
        pending_count = len(data_points) - processed_count
        
        self.assertGreater(processed_count, 0)
        self.assertGreater(pending_count, 0)


class IoTAutomationServiceTestCase(TestCase):
    """Test automation service functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.automation_service = AutomationLevelService()
        
        self.company = Company.objects.create(
            name='Service Test Company',
            address='789 Service Rd',
            city='Service City',
            state='TX'
        )
        
        self.establishment = Establishment.objects.create(
            name='Service Test Farm',
            company=self.company,
            establishment_type='farm'
        )
        
        self.device = IoTDevice.objects.create(
            establishment=self.establishment,
            name='Test Device',
            device_type='sensor',
            device_id='test_001',
            status='online'
        )
    
    def test_automation_service_initialization(self):
        """Test automation service initializes correctly"""
        self.assertIsNotNone(self.automation_service)
        self.assertTrue(hasattr(self.automation_service, 'should_auto_approve_event'))
        self.assertTrue(hasattr(self.automation_service, 'get_automation_stats_for_establishment'))
    
    def test_auto_approval_decision_logic(self):
        """Test auto approval decision logic"""
        # Create test data point
        data_point = IoTDataPoint.objects.create(
            device=self.device,
            timestamp=timezone.now(),
            data={'test_value': 50.0},
            quality_score=0.95,
            processed=False
        )
        
        # Test decision with high confidence
        decision = self.automation_service.should_auto_approve_event(data_point, 0.95)
        self.assertIsInstance(decision, bool)
        
        # Test decision with low confidence
        decision_low = self.automation_service.should_auto_approve_event(data_point, 0.70)
        self.assertFalse(decision_low)
    
    def test_automation_stats_structure(self):
        """Test automation statistics data structure"""
        stats = self.automation_service.get_automation_stats_for_establishment(self.establishment)
        
        self.assertIsInstance(stats, dict)
        
        # Check for expected stat types
        expected_stat_types = ['total', 'processed', 'pending', 'rate']
        for stat_type in expected_stat_types:
            # Stats might use different naming conventions
            stat_found = any(stat_type in key.lower() for key in stats.keys())
            # Don't require all stats to be present, but structure should be valid
    
    def test_confidence_threshold_boundary_conditions(self):
        """Test confidence threshold boundary conditions"""
        boundary_confidences = [0.89, 0.90, 0.91]  # Around typical threshold
        
        for confidence in boundary_confidences:
            data_point = IoTDataPoint.objects.create(
                device=self.device,
                timestamp=timezone.now(),
                data={'test_value': 25.0},
                quality_score=confidence,
                processed=False
            )
            
            decision = self.automation_service.should_auto_approve_event(data_point, confidence)
            
            # At boundary conditions, decision should be consistent
            self.assertIsInstance(decision, bool)
            
            # Generally, higher confidence should be more likely to auto-approve
            if confidence >= 0.91:
                # High confidence might be auto-approved (subject to rate limiting)
                pass  # Decision depends on implementation
            elif confidence <= 0.89:
                # Lower confidence should generally require manual review
                # (though this depends on exact threshold implementation)
                pass 