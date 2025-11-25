#!/usr/bin/env python3
"""
Debug why production 232 shows null chemical_type
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from history.models import History, ChemicalEvent
from history.serializers import PublicHistorySerializer

def debug_production_232():
    print("🔍 DEBUGGING PRODUCTION 232")
    print("=" * 50)
    
    try:
        # Get the specific production
        history = History.objects.get(id=232)
        print(f"✅ Found History ID: {history.id}")
        print(f"   Name: {history.name}")
        print(f"   Start Date: {history.start_date}")
        
        # Check chemical events directly from database
        chemical_events = history.history_chemicalevent_events.all()
        print(f"\n📊 Chemical Events in Database: {chemical_events.count()}")
        
        for event in chemical_events:
            print(f"  Event {event.id}:")
            print(f"    type (raw): {repr(event.type)}")
            print(f"    commercial_name: {repr(event.commercial_name)}")
            print(f"    description: {repr(event.description)}")
            print(f"    date: {event.date}")
            
            # Check if type field has any issues
            if event.type is None:
                print(f"    ❌ ISSUE: type field is None!")
            elif event.type == "":
                print(f"    ❌ ISSUE: type field is empty string!")
            elif event.type not in ['FE', 'PE', 'FU', 'HE']:
                print(f"    ❌ ISSUE: type field has unexpected value: {repr(event.type)}")
            else:
                print(f"    ✅ type field looks correct: {repr(event.type)}")
        
        # Test the serializer
        print(f"\n🧪 Testing PublicHistorySerializer:")
        serializer = PublicHistorySerializer(history)
        serialized_data = serializer.data
        
        events = serialized_data.get('events', [])
        serialized_chemical_events = [e for e in events if e.get('type') == 'chemical']
        
        print(f"   Serialized chemical events: {len(serialized_chemical_events)}")
        
        for event in serialized_chemical_events:
            print(f"  Serialized Event {event.get('id')}:")
            print(f"    type: {repr(event.get('type'))}")
            print(f"    chemical_type: {repr(event.get('chemical_type'))}")
            print(f"    commercial_name: {repr(event.get('commercial_name'))}")
            
            if event.get('chemical_type') is None:
                print(f"    ❌ chemical_type is None!")
                
                # Find the corresponding database object to debug
                db_event = ChemicalEvent.objects.filter(id=event.get('id')).first()
                if db_event:
                    print(f"    🔍 DB event.type: {repr(db_event.type)}")
                    print(f"    🔍 DB event.__dict__: {db_event.__dict__}")
            else:
                print(f"    ✅ chemical_type is properly set")
                
    except History.DoesNotExist:
        print("❌ History with ID 232 does not exist")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def check_all_chemical_events():
    """Check if there are any chemical events with null/empty type fields"""
    print("\n🔍 CHECKING ALL CHEMICAL EVENTS FOR NULL/EMPTY TYPES")
    print("=" * 55)
    
    # Find events with problematic type fields
    null_type_events = ChemicalEvent.objects.filter(type__isnull=True)
    empty_type_events = ChemicalEvent.objects.filter(type="")
    
    print(f"Events with null type: {null_type_events.count()}")
    print(f"Events with empty string type: {empty_type_events.count()}")
    
    if null_type_events.exists():
        print("❌ Found events with null type:")
        for event in null_type_events[:5]:  # Show first 5
            print(f"  Event {event.id}: type={repr(event.type)}, commercial_name={repr(event.commercial_name)}")
    
    if empty_type_events.exists():
        print("❌ Found events with empty string type:")
        for event in empty_type_events[:5]:  # Show first 5
            print(f"  Event {event.id}: type={repr(event.type)}, commercial_name={repr(event.commercial_name)}")

if __name__ == "__main__":
    debug_production_232()
    check_all_chemical_events()