#!/usr/bin/env python3
"""
Debug what data is actually being sent to the frontend
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

import json
from history.models import History
from history.serializers import PublicHistorySerializer

def debug_api_response():
    print("🔍 DEBUGGING EXACT API RESPONSE SENT TO FRONTEND")
    print("=" * 60)
    
    # Get production 232
    history = History.objects.get(id=232)
    serializer = PublicHistorySerializer(history)
    serialized_data = serializer.data
    
    # Extract chemical events
    events = serialized_data.get('events', [])
    chemical_events = [e for e in events if e.get('type') == 'chemical']
    
    print(f"Production: {history.name}")
    print(f"Chemical events found: {len(chemical_events)}\n")
    
    for i, event in enumerate(chemical_events):
        print(f"Event {i+1}: {event.get('commercial_name', 'Unknown')}")
        print(f"  id: {event.get('id')}")
        print(f"  type: {repr(event.get('type'))}")
        print(f"  chemical_type: {repr(event.get('chemical_type'))}")
        
        # Show what the JSON would look like
        event_json = {
            'id': event.get('id'),
            'type': event.get('type'),
            'chemical_type': event.get('chemical_type'),
            'commercial_name': event.get('commercial_name'),
            'description': event.get('description'),
        }
        
        print(f"  JSON snippet:")
        print(f"    {json.dumps(event_json, indent=4)}")
        print()
    
    # Show the complete API structure
    print("📡 Complete API Response Structure:")
    print("=" * 40)
    
    response_structure = {
        'events': [
            {
                'id': event.get('id'),
                'type': event.get('type'),
                'chemical_type': event.get('chemical_type'),
                'commercial_name': event.get('commercial_name')
            }
            for event in chemical_events
        ]
    }
    
    print(json.dumps(response_structure, indent=2))
    
    # Verification check
    print("\n🔍 VERIFICATION:")
    print("=" * 20)
    
    for event in chemical_events:
        chemical_type = event.get('chemical_type')
        if chemical_type == 'chemical':
            print(f"❌ Event {event.get('id')}: chemical_type is still 'chemical'!")
        elif chemical_type in ['FE', 'PE', 'FU', 'HE']:
            print(f"✅ Event {event.get('id')}: chemical_type is correctly '{chemical_type}'")
        else:
            print(f"⚠️  Event {event.get('id')}: chemical_type is {repr(chemical_type)}")

if __name__ == "__main__":
    debug_api_response()