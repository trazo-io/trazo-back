#!/usr/bin/env python3
"""
Test the enhanced fallback logic for production 232
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from history.models import History
from history.serializers import PublicHistorySerializer

def test_fallback_logic():
    print("🔧 Testing Enhanced Fallback Logic for Production 232")
    print("=" * 60)
    
    try:
        history = History.objects.get(id=232)
        print(f"✅ Testing History: {history.name}")
        
        # Test the enhanced serializer
        serializer = PublicHistorySerializer(history)
        serialized_data = serializer.data
        
        events = serialized_data.get('events', [])
        chemical_events = [e for e in events if e.get('type') == 'chemical']
        
        print(f"\n📊 Found {len(chemical_events)} chemical events:")
        
        expected_types = {
            'Fertilizer Miracle': ('FE', 'fertilizer application'),
            'Fungicide Miracle': ('FU', 'fungicide application'), 
            'Herbicide Weed': ('HE', 'herbicide application'),
            'Pesticide Roundup': ('PE', 'pesticide application'),
        }
        
        all_correct = True
        
        for event in chemical_events:
            commercial_name = event.get('commercial_name', '')
            chemical_type = event.get('chemical_type')
            event_id = event.get('id')
            
            print(f"\n  🧪 Event {event_id}: {commercial_name}")
            print(f"    chemical_type: {repr(chemical_type)}")
            
            # Find expected type
            expected_type = None
            expected_message = None
            for name_key, (exp_type, exp_msg) in expected_types.items():
                if name_key in commercial_name:
                    expected_type = exp_type
                    expected_message = exp_msg
                    break
            
            if expected_type:
                if chemical_type == expected_type:
                    print(f"    ✅ Correct! Expected '{expected_type}', got '{chemical_type}'")
                    print(f"    ✅ Frontend will show: '{expected_message}'")
                else:
                    print(f"    ❌ Wrong! Expected '{expected_type}', got '{chemical_type}'")
                    all_correct = False
            else:
                print(f"    ⚠️  Unknown product type, chemical_type: {repr(chemical_type)}")
        
        print(f"\n{'='*60}")
        if all_correct and len(chemical_events) > 0:
            print("🎉 ALL CHEMICAL EVENTS CORRECTLY TYPED!")
            print("✅ Fungicides now show 'fungicide application' not 'chemical application'")
            print("✅ All fallback logic working correctly")
        elif len(chemical_events) == 0:
            print("❌ No chemical events found")
        else:
            print("❌ Some events still have incorrect types")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

def test_manual_chemical_type_detection():
    """Test the fallback logic manually on the specific events"""
    print("\n🧪 Manual Fallback Logic Test")
    print("-" * 40)
    
    from history.models import ChemicalEvent
    
    # Get events from production 232
    events = ChemicalEvent.objects.filter(history_id=232)
    
    # Create a serializer instance to test the method
    history = History.objects.get(id=232)
    serializer = PublicHistorySerializer(history)
    
    for event in events:
        print(f"\nEvent {event.id}: {event.commercial_name}")
        print(f"  Database type: {repr(event.type)}")
        
        # Test the fallback method manually
        result = serializer._get_chemical_type_with_fallback(event)
        print(f"  Fallback result: {repr(result)}")
        
        # Show which strategy was used
        if event.type and event.type in ['FE', 'PE', 'FU', 'HE']:
            print(f"  ✅ Used primary: database type")
        elif hasattr(event, 'extra_data') and event.extra_data:
            carbon_data = event.extra_data.get('carbon_calculation', {})
            breakdown = carbon_data.get('breakdown', {})
            carbon_chemical_type = breakdown.get('chemical_type')
            if carbon_chemical_type and carbon_chemical_type in ['FE', 'PE', 'FU', 'HE']:
                print(f"  🔄 Used fallback 1: carbon calculation data ({carbon_chemical_type})")
            else:
                print(f"  🔍 Used fallback 2: commercial name inference")
        else:
            print(f"  ⚠️  Used fallback 2: commercial name inference")

if __name__ == "__main__":
    test_fallback_logic()
    test_manual_chemical_type_detection()