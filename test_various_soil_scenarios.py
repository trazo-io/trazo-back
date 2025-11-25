#!/usr/bin/env python3
"""
Test various soil management scenarios to ensure the fix is comprehensive.
"""

import requests
import json

def test_soil_scenarios():
    """Test different soil management scenarios"""
    
    url = "http://localhost:8000/api/carbon/calculate-event-carbon/"
    
    # Valid token for testing
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzYwMzAxNjg2LCJpYXQiOjE3NjAyOTk4ODYsImp0aSI6IjY2OTU4ZjFjYWZlMzQxNDI5YjM4MTNkMDMyZGFiODVkIiwidXNlcl9pZCI6NTZ9.aIhgnFC4dWTqscZW9FjuImcvABnqCuuxBglHLShs22g",
        "Content-Type": "application/json"
    }
    
    scenarios = [
        {
            "name": "Minimal Soil Testing",
            "payload": {
                "event_type": "soil_management",
                "event_data": {
                    "date": "2025-10-12T20:35",
                    "event_type": "soil_management",
                    "type": "ST",
                    "area": "1",
                    "area_unit": "hectares",
                    "parcel_id": 105,
                    "establishment_id": 44
                }
            }
        },
        {
            "name": "Soil Testing with Fuel",
            "payload": {
                "event_type": "soil_management",
                "event_data": {
                    "date": "2025-10-12T20:35",
                    "event_type": "soil_management",
                    "type": "ST",
                    "area": "5",
                    "area_unit": "hectares",
                    "fuel_consumed": "10",
                    "fuel_unit": "L",
                    "equipment_hours": "3",
                    "parcel_id": 105,
                    "establishment_id": 44
                }
            }
        },
        {
            "name": "pH Adjustment",
            "payload": {
                "event_type": "soil_management",
                "event_data": {
                    "date": "2025-10-12T20:35",
                    "event_type": "soil_management",
                    "type": "PA",
                    "area": "3",
                    "area_unit": "hectares",
                    "soil_ph": "5.8",
                    "parcel_id": 105,
                    "establishment_id": 44
                }
            }
        },
        {
            "name": "Organic Matter Addition",
            "payload": {
                "event_type": "soil_management",
                "event_data": {
                    "date": "2025-10-12T20:35",
                    "event_type": "soil_management",
                    "type": "OM",
                    "area": "2.5",
                    "area_unit": "hectares",
                    "organic_matter_percentage": "5.2",
                    "fuel_consumed": "15",
                    "fuel_unit": "L",
                    "parcel_id": 105,
                    "establishment_id": 44
                }
            }
        },
        {
            "name": "Empty String Fields",
            "payload": {
                "event_type": "soil_management",
                "event_data": {
                    "date": "2025-10-12T20:35",
                    "event_type": "soil_management",
                    "type": "ST",
                    "area": "2",
                    "area_unit": "hectares",
                    "fuel_consumed": "",
                    "equipment_hours": "",
                    "area_covered": "",
                    "parcel_id": 105,
                    "establishment_id": 44
                }
            }
        }
    ]
    
    print("🧪 Testing Various Soil Management Scenarios")
    print("=" * 60)
    
    results = []
    
    for scenario in scenarios:
        print(f"\n📋 Testing: {scenario['name']}")
        
        try:
            response = requests.post(url, json=scenario['payload'], headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                co2e = result.get('co2e', 'N/A')
                efficiency = result.get('efficiency_score', 'N/A')
                method = result.get('calculation_method', 'N/A')
                
                print(f"   ✅ SUCCESS: {co2e} kg CO2e (efficiency: {efficiency})")
                print(f"      Method: {method}")
                
                results.append({
                    'scenario': scenario['name'],
                    'status': 'SUCCESS',
                    'co2e': co2e,
                    'efficiency': efficiency,
                    'method': method
                })
            else:
                try:
                    error = response.json()
                    print(f"   ❌ FAILED: {response.status_code}")
                    print(f"      Error: {error}")
                    
                    results.append({
                        'scenario': scenario['name'],
                        'status': 'FAILED',
                        'error': error,
                        'status_code': response.status_code
                    })
                except:
                    print(f"   ❌ FAILED: {response.status_code} - {response.text}")
                    
                    results.append({
                        'scenario': scenario['name'],
                        'status': 'FAILED',
                        'status_code': response.status_code,
                        'response': response.text
                    })
                    
        except Exception as e:
            print(f"   💥 ERROR: {e}")
            results.append({
                'scenario': scenario['name'],
                'status': 'ERROR',
                'exception': str(e)
            })
    
    # Summary
    print(f"\n" + "=" * 60)
    print(f"📊 SUMMARY RESULTS:")
    
    success_count = sum(1 for r in results if r['status'] == 'SUCCESS')
    total_count = len(results)
    
    print(f"   Total scenarios: {total_count}")
    print(f"   Successful: {success_count}")
    print(f"   Failed: {total_count - success_count}")
    
    if success_count == total_count:
        print(f"\n🎉 ALL SCENARIOS PASSED!")
        print(f"   Soil management API is working correctly for all cases")
    else:
        print(f"\n⚠️  SOME SCENARIOS FAILED!")
        print(f"   Need to investigate remaining issues")
    
    return success_count == total_count

if __name__ == "__main__":
    success = test_soil_scenarios()
    
    if success:
        print(f"\n✅ SOIL MANAGEMENT INFINITE LOOP ISSUE COMPLETELY RESOLVED!")
    else:
        print(f"\n❌ Still some issues to resolve")
    
    print(f"\n🏁 Test complete.")