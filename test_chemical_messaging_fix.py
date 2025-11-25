#!/usr/bin/env python3
"""
Test script to verify that the chemical messaging fix works
Tests the actual endpoints that the user is experiencing issues with
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

import requests
import json

def test_transparency_endpoints():
    """Test the actual endpoints mentioned by the user"""
    print("🧪 Testing Chemical Type Fix on Actual Endpoints")
    print("=" * 60)
    
    # Test endpoints from user's examples
    endpoints = [
        "http://localhost:8000/api/carbon/public/productions/232/complete/",
        "http://localhost:8000/api/transparency/232/"
    ]
    
    for endpoint in endpoints:
        print(f"\n📍 Testing: {endpoint}")
        try:
            response = requests.get(endpoint, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                # Look for chemical events in the response
                events = data.get('events', [])
                chemical_events = [e for e in events if e.get('type') == 'chemical']
                
                print(f"  📊 Found {len(chemical_events)} chemical events")
                
                if chemical_events:
                    for i, event in enumerate(chemical_events[:3]):  # Show first 3
                        print(f"  🔬 Event #{i+1}:")
                        print(f"    id: {event.get('id')}")
                        print(f"    type: {repr(event.get('type'))}")
                        print(f"    chemical_type: {repr(event.get('chemical_type'))}")
                        print(f"    commercial_name: {repr(event.get('commercial_name'))}")
                        
                        # Test frontend logic simulation
                        chemical_type = event.get('chemical_type')
                        if chemical_type:
                            type_mapping = {
                                'FE': 'fertilizer application',
                                'PE': 'pesticide application', 
                                'FU': 'fungicide application',
                                'HE': 'herbicide application'
                            }
                            expected_message = type_mapping.get(chemical_type, 'chemical application')
                            print(f"    ✅ Frontend should show: '{expected_message}'")
                        else:
                            print(f"    ❌ No chemical_type field - will show generic 'chemical application'")
                        print()
                else:
                    print("  ℹ️  No chemical events found in this response")
                    
            else:
                print(f"  ❌ HTTP {response.status_code}: {response.text[:200]}")
                
        except requests.exceptions.RequestException as e:
            print(f"  ❌ Request failed: {e}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("💡 Fix Summary:")
    print("✅ Added chemical_type field to PublicHistorySerializer")
    print("✅ Frontend already checks for chemical_type field first")
    print("✅ Should resolve the fungicide → 'chemical application' issue")

def test_direct_database():
    """Test data directly from database to verify fix"""
    print("\n🔧 Direct Database Test")
    print("-" * 30)
    
    from history.models import ChemicalEvent, History
    from history.serializers import PublicHistorySerializer
    
    # Find a production with chemical events
    history = History.objects.filter(history_chemicalevent_events__isnull=False).first()
    
    if history:
        print(f"Testing History ID: {history.id}")
        
        # Test the serializer directly
        serializer = PublicHistorySerializer(history)
        serialized_data = serializer.data
        
        events = serialized_data.get('events', [])
        chemical_events = [e for e in events if e.get('type') == 'chemical']
        
        print(f"Chemical events found: {len(chemical_events)}")
        
        for event in chemical_events[:2]:  # Show first 2
            print(f"  Event {event.get('id')}:")
            print(f"    type: {repr(event.get('type'))}")
            print(f"    chemical_type: {repr(event.get('chemical_type'))}")
            
            # Verify the fix
            if 'chemical_type' in event and event['chemical_type']:
                print("    ✅ chemical_type field is now present!")
            else:
                print("    ❌ chemical_type field is missing")
    else:
        print("❌ No history with chemical events found")

if __name__ == "__main__":
    test_direct_database()
    test_transparency_endpoints()