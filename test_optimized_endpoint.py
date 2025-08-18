#!/usr/bin/env python3
"""
Test script for optimized carbon calculation endpoint performance.
"""
import json
import os
import sys
import time

import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from django.contrib.auth import get_user_model
from django.test import Client

from users.models import Company

User = get_user_model()


def test_optimized_endpoint():
    """Test the optimized carbon calculation endpoint."""
    client = Client()

    # Create test user and company for authentication
    try:
        test_user = User.objects.create_user(
            email="test@example.com", password="testpass123", first_name="Test", last_name="User"
        )

        test_company = Company.objects.create(name="Test Company", email="test@company.com")

        # Associate user with company
        test_user.company = test_company
        test_user.save()

        # Login the test user
        client.force_login(test_user)
        print("✅ Test user authenticated successfully")

    except Exception as e:
        print(f"⚠️  Using existing test user or skipping auth: {e}")

    test_data = {"event_type": "chemical", "event_data": {"type": "FE", "volume": "10", "area": "1.0"}}

    print("🧪 Testing optimized carbon calculation endpoint...")
    print(f"📤 Request data: {json.dumps(test_data, indent=2)}")

    # Measure response time
    start = time.time()
    response = client.post(
        "/api/carbon/calculate-event-impact-optimized/", data=json.dumps(test_data), content_type="application/json"
    )
    elapsed = (time.time() - start) * 1000

    print(f"\n⏱️  Response time: {elapsed:.1f}ms")
    print(f"📊 Status code: {response.status_code}")

    if response.status_code == 200:
        print("✅ Endpoint responding successfully!")
        try:
            response_data = response.json()
            print(f"📄 Response data: {json.dumps(response_data, indent=2)}")
        except json.JSONDecodeError:
            print("⚠️  Response not JSON format")
            print(f"📄 Raw response: {response.content.decode()}")
    else:
        print("❌ Endpoint error!")
        print(f"📄 Error details: {response.content.decode()}")

    return response.status_code == 200, elapsed


def test_cache_functionality():
    """Test Redis cache functionality."""
    print("\n🔄 Testing cache functionality...")

    try:
        from django.core.cache import cache

        # Test cache set/get
        cache.set("test_key", "test_value", 60)
        cached_value = cache.get("test_key")

        if cached_value == "test_value":
            print("✅ Cache working correctly!")
            return True
        else:
            print("❌ Cache not working - value mismatch")
            return False

    except Exception as e:
        print(f"❌ Cache error: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Carbon API Optimization - Performance Test")
    print("=" * 50)

    # Test cache first
    cache_working = test_cache_functionality()

    # Test optimized endpoint
    endpoint_working, response_time = test_optimized_endpoint()

    print("\n" + "=" * 50)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 50)
    print(f"🔄 Cache Status: {'✅ Working' if cache_working else '❌ Failed'}")
    print(f"🚀 Endpoint Status: {'✅ Working' if endpoint_working else '❌ Failed'}")
    print(f"⏱️  Response Time: {response_time:.1f}ms")

    # Performance evaluation
    if endpoint_working:
        if response_time < 200:
            print("🎯 EXCELLENT: Response time < 200ms (target achieved)")
        elif response_time < 500:
            print("✅ GOOD: Response time < 500ms (improvement achieved)")
        elif response_time < 1000:
            print("⚠️  OK: Response time < 1s (some improvement)")
        else:
            print("❌ POOR: Response time > 1s (optimization may not be working)")

    print("\n🎉 Optimization deployment test completed!")
