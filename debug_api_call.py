#!/usr/bin/env python3
"""
Debug script to trigger the complete summary API and see backend debugging output
"""

import os
import sys
import django
import requests
from django.test import RequestFactory

# Add the project directory to Python path
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import CarbonProductionSummaryViewSet

def debug_api_call():
    """Trigger the complete summary API directly"""
    
    print("🔧 DEBUG: Triggering complete summary API for production 232")
    print("=" * 60)
    
    try:
        # Create a request factory to simulate the API call
        factory = RequestFactory()
        request = factory.get('/api/carbon/public/productions/232/complete/')
        
        # Create the view instance
        view = CarbonProductionSummaryViewSet()
        
        # Call the complete_summary method directly
        response = view.complete_summary(request, pk="232")
        
        print(f"✅ API call completed with status: {response.status_code}")
        
        if hasattr(response, 'data'):
            data = response.data
            print(f"📊 Response data type: {type(data)}")
            
            # Check if timeline exists
            if 'timeline' in data:
                print(f"📅 Timeline events count: {len(data['timeline'])}")
                
                # Find event 178
                event_178 = None
                for event in data['timeline']:
                    if str(event.get('id')) == '178' or str(event.get('id')) == 'chemical_178':
                        event_178 = event
                        break
                
                if event_178:
                    print(f"✅ Found event 178 in timeline:")
                    print(f"   id: {event_178.get('id')}")
                    print(f"   area: '{event_178.get('area')}'")
                    print(f"   application_timing: '{event_178.get('application_timing')}'")
                    print(f"   way_of_application: '{event_178.get('way_of_application')}'")
                    print(f"   application_method: '{event_178.get('application_method')}'")
                else:
                    print("❌ Event 178 not found in timeline")
                    print(f"📋 Available event IDs: {[e.get('id') for e in data['timeline']]}")
            else:
                print("❌ No timeline found in response")
        else:
            print("❌ No data in response")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_api_call()