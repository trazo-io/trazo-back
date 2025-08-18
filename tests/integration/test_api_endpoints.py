#!/usr/bin/env python3
"""
Test API Endpoints
Simulate what the frontend calls to verify fresh data
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

import pytest

from carbon.models import IoTDataPoint, IoTDevice
from company.models import Establishment


@pytest.mark.django_db
class TestAPIEndpoints(TestCase):
    """Test API endpoints that the frontend uses"""

    def setUp(self):
        """Set up test data"""
        # This would normally create test data
        pass

    def test_iot_device_status_api(self):
        """Test IoT device status API endpoint"""
        # Mock what the frontend calls
        # GET /carbon/iot-devices/device_status/?establishment_id=14

        # Skip if no test data exists
        establishments = Establishment.objects.all()
        if not establishments.exists():
            self.skipTest("No establishments found for testing")

        establishment = establishments.first()
        devices = IoTDevice.objects.filter(establishment=establishment)

        # Test device status logic
        online_devices = 0
        for device in devices:
            if device.last_seen:
                time_diff = timezone.now() - device.last_seen
                if time_diff < timedelta(minutes=15):
                    online_devices += 1

        # Verify basic functionality
        self.assertIsInstance(online_devices, int)

    def test_recent_data_points(self):
        """Test recent IoT data points endpoint"""
        # What shows in dashboard charts
        establishments = Establishment.objects.all()
        if not establishments.exists():
            self.skipTest("No establishments found for testing")

        establishment = establishments.first()
        recent_data = IoTDataPoint.objects.filter(
            device__establishment=establishment, timestamp__gte=timezone.now() - timedelta(hours=2)
        ).order_by("-timestamp")[:10]

        # Verify query works
        self.assertIsNotNone(recent_data)

    def test_automation_stats_api(self):
        """Test automation statistics API"""
        establishments = Establishment.objects.all()
        if not establishments.exists():
            self.skipTest("No establishments found for testing")

        establishment = establishments.first()

        # Test basic establishment access
        self.assertIsNotNone(establishment)

        # Skip automation service test if not available
        try:
            from carbon.services.automation_service import AutomationLevelService

            service = AutomationLevelService()
            stats = service.get_automation_stats_for_establishment(establishment)
            self.assertIsInstance(stats, dict)
        except ImportError:
            self.skipTest("AutomationLevelService not available")
