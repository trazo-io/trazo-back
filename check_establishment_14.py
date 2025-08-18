#!/usr/bin/env python3
"""Check establishment 14 data specifically"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.base")

import django

django.setup()

from datetime import timedelta

from django.utils import timezone

from carbon.models import CarbonEntry, IoTDataPoint, IoTDevice
from company.models import Establishment

# Get establishment 14 specifically
est = Establishment.objects.get(id=14)
print(f"🏢 Establishment {est.id}: {est.name}")

# Check devices
devices = IoTDevice.objects.filter(establishment=est)
print(f"📱 IoT Devices: {devices.count()}")
for device in devices:
    print(f"   - {device.name} (ID: {device.id}, Type: {device.device_type})")

# Check recent IoT data points (last 2 hours)
recent_time = timezone.now() - timedelta(hours=2)
recent_data = IoTDataPoint.objects.filter(device__establishment=est, created_at__gte=recent_time).order_by(
    "-created_at"
)

print(f"\n📊 Recent IoT Data (last 2 hours): {recent_data.count()} points")
for i, dp in enumerate(recent_data[:10]):
    batch_info = dp.data.get("batch_id", "unknown") if hasattr(dp.data, "get") else "old"
    status = "PROCESSED" if dp.processed else "PENDING"
    print(
        f'   {i+1}. {dp.device.name}: conf={dp.quality_score:.2f}, time={dp.created_at.strftime("%H:%M:%S")}, batch={batch_info}, status={status}'
    )

# Check fresh test data specifically
fresh_data = IoTDataPoint.objects.filter(device__establishment=est, data__reading_type="test_fresh_data").order_by(
    "-created_at"
)

print(f"\n🆕 Fresh Test Data: {fresh_data.count()} points")
for dp in fresh_data:
    batch_info = dp.data.get("batch_id", "unknown") if hasattr(dp.data, "get") else "old"
    status = "PROCESSED" if dp.processed else "PENDING"
    print(
        f'   - {dp.device.name}: conf={dp.quality_score:.2f}, time={dp.created_at.strftime("%H:%M:%S")}, batch={batch_info}, status={status}'
    )

print(f"\n💨 Recent Carbon Entries:")
recent_carbon = CarbonEntry.objects.filter(establishment=est, created_at__gte=recent_time).order_by("-created_at")[:5]

for entry in recent_carbon:
    source = entry.iot_device_id or "Manual"
    desc = entry.description[:50] + "..." if len(entry.description) > 50 else entry.description
    print(f'   - {entry.amount}kg CO2e from {source} @ {entry.created_at.strftime("%H:%M:%S")} - {desc}')

# Check what frontend API should return
print(f"\n🔄 What frontend should see:")
print(f"   Total devices: {devices.count()}")
print(f"   Recent data points: {recent_data.count()}")
print(f"   Fresh test data: {fresh_data.count()}")

# Check if data is from today
today_data = IoTDataPoint.objects.filter(device__establishment=est, created_at__date=timezone.now().date()).count()
print(f"   Today's data points: {today_data}")

# Check API endpoint data format
from carbon.services.automation_service import AutomationLevelService

service = AutomationLevelService()
stats = service.get_automation_stats_for_establishment(est)
print(f"\n📈 Automation Stats (API would return):")
for key, value in stats.items():
    print(f"   {key}: {value}")
