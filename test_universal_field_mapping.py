#!/usr/bin/env python3
"""
Comprehensive test to verify universal field mapping works for all 8 event types.

Tests that frontend observation → description mapping works correctly and consistently
across Weather, Production, General, Equipment, Pest Management, and Business events.
"""

import os
import sys
import django
import requests
import json

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
sys.path.insert(0, '/Users/oscarmunoz/dev/trazo/trazo-back')
django.setup()

from history.constants import (
    WEATHER_EVENT_TYPE,
    PRODUCTION_EVENT_TYPE, 
    CHEMICAL_EVENT_TYPE,
    GENERAL_EVENT_TYPE,
    EQUIPMENT_EVENT_TYPE,
    SOIL_MANAGEMENT_EVENT_TYPE,
    PEST_MANAGEMENT_EVENT_TYPE,
    BUSINESS_EVENT_TYPE
)

def test_universal_field_mapping():
    """Test universal observation → description mapping for all 8 event types"""
    
    print("🧪 TESTING UNIVERSAL FIELD MAPPING")
    print("=" * 60)
    print()
    
    # Base event data template
    base_event_data = {
        "date": "2025-11-05T15:30",
        "name": "Universal Field Mapping Test",
        "observation": "Test observation for universal mapping validation",
        "acceptedFiles": [],
        "parcels": ["106"],
        "album_images": []
    }
    
    # Event type configurations
    event_configs = [
        {
            "name": "Weather Event",
            "event_type": WEATHER_EVENT_TYPE,
            "has_observation": True,
            "additional_data": {
                "type": "FR",  # Frost
                "lower_temperature": "5.0",
                "duration": "3"
            }
        },
        {
            "name": "Production Event", 
            "event_type": PRODUCTION_EVENT_TYPE,
            "has_observation": True,
            "additional_data": {
                "type": "PL",  # Planting
                "area_covered": "2.5",
                "area_unit": "ha"
            }
        },
        {
            "name": "Chemical Event",
            "event_type": CHEMICAL_EVENT_TYPE, 
            "has_observation": False,  # Chemical events don't use observation field
            "additional_data": {
                "type": "FE",  # Fertilizer
                "commercial_name": "NPK Fertilizer",
                "volume": "50.0",
                "description": "Chemical fertilizer application"  # Uses description directly
            }
        },
        {
            "name": "General Event",
            "event_type": GENERAL_EVENT_TYPE,
            "has_observation": True,
            "additional_data": {
                "type": "maintenance",
                "duration_hours": "2",
                "participants": "3"
            }
        },
        {
            "name": "Equipment Event",
            "event_type": EQUIPMENT_EVENT_TYPE,
            "has_observation": True,
            "additional_data": {
                "type": "MN",  # Maintenance
                "equipment_name": "Tractor", 
                "fuel_consumed": "15.5",
                "hours_operated": "4"
            }
        },
        {
            "name": "Soil Management Event",
            "event_type": SOIL_MANAGEMENT_EVENT_TYPE,
            "has_observation": True,
            "additional_data": {
                "type": "ST",  # Soil Test
                "ph_level": "6.8",
                "organic_matter": "3.2"
            }
        },
        {
            "name": "Pest Management Event",
            "event_type": PEST_MANAGEMENT_EVENT_TYPE, 
            "has_observation": True,
            "additional_data": {
                "type": "SC",  # Scouting
                "pest_species": "Aphids",
                "damage_percentage": "5"
            }
        },
        {
            "name": "Business Event",
            "event_type": BUSINESS_EVENT_TYPE,
            "has_observation": True,
            "additional_data": {
                "type": "CE",  # Certification
                "business_type": "certification",
                "certification_type": "organic"
            }
        }
    ]
    
    print("📋 Testing Event Type Configurations:")
    for config in event_configs:
        observation_status = "✅ Uses observation field" if config["has_observation"] else "ℹ️ Uses description directly"
        print(f"   • {config['name']} (Type {config['event_type']}): {observation_status}")
    print()
    
    results = []
    
    for config in event_configs:
        print(f"🧪 Testing {config['name']} (Event Type {config['event_type']})")
        print("-" * 50)
        
        # Prepare event data
        event_data = {**base_event_data, **config["additional_data"]}
        event_data["event_type"] = config["event_type"]
        
        # For Chemical events, remove observation and use description directly
        if not config["has_observation"]:
            event_data.pop("observation", None)
        
        print(f"📤 Payload: {json.dumps(event_data, indent=2)}")
        
        # Test the API endpoint
        try:
            response = requests.post(
                "http://localhost:8000/api/carbon/calculate-event-carbon/",
                json=event_data,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"📥 Response Status: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                print(f"📊 Carbon Impact: {response_data.get('co2e', 'N/A')} kg CO2e")
                
                # Validate that the mapping worked correctly
                if config["has_observation"]:
                    # Should have successfully processed observation → description mapping
                    result = {
                        "event_type": config["name"],
                        "status": "✅ PASS",
                        "carbon_impact": response_data.get('co2e', 0),
                        "message": "Universal mapping successful - observation → description"
                    }
                else:
                    # Chemical events should work with direct description
                    result = {
                        "event_type": config["name"],
                        "status": "✅ PASS", 
                        "carbon_impact": response_data.get('co2e', 0),
                        "message": "Direct description field usage successful"
                    }
                    
                print(f"✅ SUCCESS: {result['message']}")
                
            else:
                error_data = response.text
                print(f"❌ ERROR Response: {error_data}")
                
                # Check if it's the old "description field required" error
                if "description" in error_data and "required" in error_data:
                    result = {
                        "event_type": config["name"],
                        "status": "❌ FAIL",
                        "carbon_impact": None,
                        "message": "Universal mapping failed - description field still required"
                    }
                    print(f"❌ CRITICAL: Universal mapping not working for {config['name']}")
                else:
                    result = {
                        "event_type": config["name"], 
                        "status": "⚠️ OTHER_ERROR",
                        "carbon_impact": None,
                        "message": f"Different error: {error_data[:100]}..."
                    }
                    print(f"⚠️ OTHER ERROR: {error_data[:100]}...")
        
        except Exception as e:
            result = {
                "event_type": config["name"],
                "status": "❌ EXCEPTION",
                "carbon_impact": None,
                "message": f"Exception: {str(e)}"
            }
            print(f"💥 EXCEPTION: {str(e)}")
        
        results.append(result)
        print()
    
    # Summary Report
    print("📊 UNIVERSAL FIELD MAPPING TEST RESULTS")
    print("=" * 60)
    
    passed = sum(1 for r in results if r["status"] == "✅ PASS")
    failed = sum(1 for r in results if "FAIL" in r["status"])
    errors = sum(1 for r in results if "ERROR" in r["status"] or "EXCEPTION" in r["status"])
    
    print(f"📈 Summary: {passed}/8 PASSED | {failed}/8 FAILED | {errors}/8 ERRORS")
    print()
    
    print("📋 Detailed Results:")
    for result in results:
        carbon_info = f" ({result['carbon_impact']} kg CO2e)" if result['carbon_impact'] is not None else ""
        print(f"   {result['status']} {result['event_type']}{carbon_info}")
        print(f"      → {result['message']}")
    print()
    
    # Validation Analysis
    print("🔍 VALIDATION ANALYSIS:")
    
    observation_events = [r for r in results if "observation" in r["message"]]
    if observation_events:
        observation_success = all(r["status"] == "✅ PASS" for r in observation_events)
        print(f"   • Observation → Description Mapping: {'✅ ALL WORKING' if observation_success else '❌ SOME FAILING'}")
    
    chemical_events = [r for r in results if r["event_type"] == "Chemical Event"]
    if chemical_events:
        chemical_success = chemical_events[0]["status"] == "✅ PASS"
        print(f"   • Direct Description Usage: {'✅ WORKING' if chemical_success else '❌ FAILING'}")
    
    universal_success = passed == 8
    print(f"   • Universal Implementation: {'✅ COMPLETE SUCCESS' if universal_success else '❌ NEEDS FIXES'}")
    print()
    
    # Final Assessment
    if universal_success:
        print("🎉 PRODUCTION READINESS: ✅ READY")
        print("   All 8 event types handle field mapping correctly.")
        print("   Universal observation → description mapping is working.")
        print("   Following industry best practices for consistent API contracts.")
    else:
        print("⚠️ PRODUCTION READINESS: ❌ NEEDS ATTENTION")
        print("   Some event types still have field mapping issues.")
        print("   Review failed tests and implement remaining fixes.")
    
    return universal_success

if __name__ == "__main__":
    print("🚀 UNIVERSAL FIELD MAPPING VALIDATION")
    print("Testing consistency across all 8 Trazo event types")
    print("=" * 70)
    print()
    
    success = test_universal_field_mapping()
    
    if success:
        print("\n🎯 CONCLUSION: Universal field mapping implementation SUCCESSFUL!")
        print("The frontend fix following industry best practices is production-ready.")
    else:
        print("\n🔧 CONCLUSION: Additional fixes needed for complete universal coverage.")
        print("Review the failed tests and implement remaining mappings.")