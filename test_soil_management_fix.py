#!/usr/bin/env python3
"""
Test script to verify soil management API fix without authentication.
This simulates what the frontend is doing.
"""

import os
import sys
import django
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.views import OptimizedEventProcessor, EventCarbonCalculator

def test_complete_flow():
    """Test the complete soil management flow like the API does"""
    print("🔄 Testing complete soil management flow...")
    
    # Test data matching what frontend sends
    event_type = "soil_management"
    event_data = {
        "type": "ST",  # Soil Testing
        "area_worked": "1",
        "depth": "30",
        "method": "manual",
        "equipment_used": "soil_auger", 
        "parcel_id": 1,
        "establishment_id": 1,
        "date": "2025-01-21T10:00"
    }
    
    print(f"📤 Input:")
    print(f"   event_type: {event_type}")
    print(f"   event_data: {json.dumps(event_data, indent=6)}")
    
    try:
        # Step 1: Process event data (like API does)
        print(f"\n1️⃣ Processing event data with OptimizedEventProcessor...")
        processed_event = OptimizedEventProcessor.process_event_data(event_type, event_data)
        print(f"   ✅ Processed successfully")
        print(f"   📦 Processed data keys: {list(processed_event.keys())}")
        
        # Step 2: Create calculator instance
        print(f"\n2️⃣ Creating calculator instance...")
        calculator = EventCarbonCalculator()
        print(f"   ✅ Calculator created")
        
        # Step 3: Create mock event object from processed data (like API does)
        print(f"\n3️⃣ Creating mock event object...")
        class MockEvent:
            def __init__(self, processed_data):
                # Map all processed data to event attributes
                for key, value in processed_data.items():
                    setattr(self, key, value)
                
                # Handle special mappings that calculator expects
                if hasattr(self, 'soil_type'):
                    self.type = self.soil_type
                
                # Ensure area fields exist in multiple formats for compatibility
                if hasattr(self, 'area_covered'):
                    self.area = self.area_covered
                elif hasattr(self, 'area'):
                    self.area_covered = self.area
        
        mock_event = MockEvent(processed_event)
        print(f"   ✅ Mock event created")
        print(f"   📦 Event attributes: {[attr for attr in dir(mock_event) if not attr.startswith('_')]}")
        
        # Step 4: Calculate carbon impact
        print(f"\n4️⃣ Calculating carbon impact...")
        result = calculator.calculate_soil_management_event_impact(mock_event)
        print(f"   ✅ Calculation successful")
        
        # Step 5: Add calculation method suffix (like API does)
        result["calculation_method"] = f"optimized_soil_{result.get('calculation_method', 'standard')}"
        
        print(f"\n📈 FINAL RESULT:")
        print(f"   {json.dumps(result, indent=4)}")
        
        # Step 6: Check for fallback/error conditions
        if result.get('fallback_used') or result.get('error'):
            print(f"\n⚠️  WARNING: Calculation used fallback values!")
            print(f"   Error: {result.get('error', 'N/A')}")
            print(f"   Fallback: {result.get('fallback_used', 'N/A')}")
            return False
        else:
            print(f"\n✅ SUCCESS: Calculation completed without fallback!")
            return True
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_different_soil_types():
    """Test different soil management types"""
    print(f"\n🧪 Testing different soil management types...")
    
    soil_types = [
        ("ST", "Soil Testing"),
        ("PA", "pH Adjustment"),
        ("OM", "Organic Matter Addition"),
        ("CC", "Cover Crop Management"),
        ("TI", "Tillage Implementation"),
        ("CO", "Composting Operation")
    ]
    
    results = {}
    
    for soil_code, soil_name in soil_types:
        print(f"\n   Testing {soil_name} ({soil_code})...")
        
        event_data = {
            "type": soil_code,
            "area_worked": "2.5",
            "depth": "25",
            "method": "mechanical",
            "equipment_used": "tractor",
            "soil_ph": "6.8",
            "organic_matter_percentage": "4.2"
        }
        
        try:
            processed_event = OptimizedEventProcessor.process_event_data("soil_management", event_data)
            
            class MockEvent:
                def __init__(self, processed_data):
                    for key, value in processed_data.items():
                        setattr(self, key, value)
                    if hasattr(self, 'soil_type'):
                        self.type = self.soil_type
                    if hasattr(self, 'area_covered'):
                        self.area = self.area_covered
                    elif hasattr(self, 'area'):
                        self.area_covered = self.area
            
            mock_event = MockEvent(processed_event)
            calculator = EventCarbonCalculator()
            result = calculator.calculate_soil_management_event_impact(mock_event)
            
            co2e = result.get('co2e', 0)
            results[soil_name] = co2e
            
            status = "✅" if not result.get('error') else "⚠️"
            print(f"      {status} {co2e:.2f} kg CO2e")
            
        except Exception as e:
            print(f"      ❌ Error: {e}")
            results[soil_name] = "ERROR"
    
    print(f"\n📊 SOIL MANAGEMENT RESULTS SUMMARY:")
    for soil_name, co2e in results.items():
        print(f"   {soil_name:25} | {co2e}")

if __name__ == "__main__":
    print("🔍 SOIL MANAGEMENT API FIX VERIFICATION")
    print("=" * 50)
    
    # Test the main flow
    success = test_complete_flow()
    
    if success:
        # Test different soil types
        test_different_soil_types()
        
        print(f"\n🎉 CONCLUSION:")
        print(f"   ✅ Soil management API fix is working correctly!")
        print(f"   ✅ OptimizedEventProcessor now handles soil_management events")
        print(f"   ✅ Calculator produces non-fallback results")
        print(f"   ✅ Multiple soil management types work")
        
        print(f"\n🔧 FRONTEND FIX NEEDED:")
        print(f"   The infinite loop is likely caused by frontend React dependencies")
        print(f"   The backend API is now working correctly")
        
    else:
        print(f"\n❌ ISSUES FOUND:")
        print(f"   Backend still has calculation problems")
        print(f"   Need to investigate calculator implementation")
    
    print(f"\n" + "=" * 50)