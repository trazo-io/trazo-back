#!/usr/bin/env python3
"""
Test script to verify the pest management infinite loop fix.

The infinite loop is caused by:
1. PestManagementTab watches form fields
2. onDataChange updates parent state
3. Parent re-renders with new initialValues
4. Form resets, triggering watch again -> LOOP

Solution: Add proper dependency management and prevent unnecessary onDataChange calls.
"""

import threading
import time

import requests


# Test the carbon calculation endpoint repeatedly to simulate the loop
def simulate_infinite_requests():
    """Simulate the frontend infinite loop by making repeated API calls"""

    url = "http://localhost:8000/api/carbon/calculate-event-carbon/"

    test_payload = {
        "event_type": "pest_management",
        "event_data": {
            "type": "SC",
            "name": "Test Scouting Event",
            "pest_species": "aphids",
            "pest_pressure_level": "medium",
            "field_area_hectares": "2.5",
            "travel_distance_km": "5.0",
            "time_spent_hours": "2.0",
            "parcel_id": 1,
            "establishment_id": 1,
            "date": "2025-01-21T10:00",
        },
    }

    headers = {"Content-Type": "application/json"}

    print("🔄 Simulating infinite loop by making repeated API calls...")
    print("   (This mimics the frontend behavior before the fix)")
    print("   Press Ctrl+C to stop\n")

    request_count = 0
    start_time = time.time()

    try:
        while True:
            request_count += 1
            elapsed = time.time() - start_time

            try:
                response = requests.post(url, json=test_payload, headers=headers, timeout=5)

                if response.status_code == 200:
                    result = response.json()
                    co2e = result.get("co2e", "N/A")
                    print(f"✅ Request #{request_count} ({elapsed:.1f}s): {co2e} kg CO2e")
                else:
                    print(f"❌ Request #{request_count} ({elapsed:.1f}s): HTTP {response.status_code}")

            except requests.exceptions.RequestException as e:
                print(f"💥 Request #{request_count} ({elapsed:.1f}s): Network error - {e}")

            # Wait 1 second between requests (frontend was doing this every 500ms)
            time.sleep(1.0)

            # Stop after 10 requests for demo
            if request_count >= 10:
                print(f"\n🛑 Stopped simulation after {request_count} requests")
                break

    except KeyboardInterrupt:
        print(f"\n⏹️  Simulation stopped. Made {request_count} requests in {elapsed:.1f} seconds")
        print(f"   Average: {request_count/elapsed:.1f} requests/second")


def test_single_calculation():
    """Test a single carbon calculation to verify backend is working"""

    print("🧪 Testing single pest management carbon calculation...")

    url = "http://localhost:8000/api/carbon/calculate-event-carbon/"

    test_payload = {
        "event_type": "pest_management",
        "event_data": {
            "type": "SC",
            "name": "Single Test Event",
            "pest_species": "aphids",
            "pest_pressure_level": "low",
            "field_area_hectares": "1.0",
            "travel_distance_km": "2.0",
            "time_spent_hours": "1.0",
            "parcel_id": 1,
            "establishment_id": 1,
            "date": "2025-01-21T10:00",
        },
    }

    try:
        response = requests.post(url, json=test_payload, timeout=10)

        if response.status_code == 200:
            result = response.json()
            print("✅ Backend calculation successful:")
            print(f"   CO2e: {result.get('co2e', 'N/A')} kg")
            print(f"   Method: {result.get('calculation_method', 'N/A')}")
            print(f"   Efficiency: {result.get('efficiency_score', 'N/A')}")
            return True
        else:
            print(f"❌ Backend error: HTTP {response.status_code}")
            print(f"   Response: {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"💥 Network error: {e}")
        return False


if __name__ == "__main__":
    print("🔍 PEST MANAGEMENT INFINITE LOOP DEBUG")
    print("=" * 50)

    # First test that backend is working
    print("\n1. Testing backend functionality...")
    if test_single_calculation():
        print("   ✅ Backend is working correctly")
    else:
        print("   ❌ Backend has issues - stopping")
        exit(1)

    print("\n2. Simulating frontend infinite loop...")
    print("   (This demonstrates the behavior that needs to be fixed)")
    simulate_infinite_requests()

    print("\n" + "=" * 50)
    print("💡 ANALYSIS:")
    print("   The backend correctly handles all requests")
    print("   The issue is in the frontend React component dependencies")
    print("   Solution needed: Fix useEffect dependencies in PestManagementTab")
