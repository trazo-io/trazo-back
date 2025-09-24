#!/usr/bin/env python3
"""
Debug Production Zero Emissions Issue
Test the exact scenario from the screenshot that's returning 0 kg CO₂e
"""

def debug_production_zero():
    print("🔍 Debug Production Zero Emissions Issue")
    print("=" * 50)
    
    # Exact data from screenshot
    form_data = {
        "type": "PL",  # Planting/Seeding dropdown value
        "area_covered": "140.00",
        "area_unit": "ha",
        "fuel_consumed": "150.0",  
        "fuel_unit": "L",
        "equipment_hours": "2.0",
        "yield_quantity": "13.0",
        "yield_unit": "kg"
    }
    
    print("📝 Input Data from Screenshot:")
    for key, value in form_data.items():
        print(f"  {key}: {value}")
    
    print("\n🧮 Manual EPA Calculation:")
    
    # Step 1: Area conversion
    area_ha = float(form_data["area_covered"])
    area_acres = area_ha * 2.47105
    print(f"  Area: {area_ha} ha = {area_acres:.1f} acres")
    
    # Step 2: Fuel conversion  
    fuel_l = float(form_data["fuel_consumed"])
    fuel_gal = fuel_l / 3.78541
    print(f"  Fuel: {fuel_l} L = {fuel_gal:.2f} gallons")
    
    # Step 3: EPA calculation
    EPA_DIESEL = 10.21  # kg CO2 per gallon
    co2e_expected = fuel_gal * EPA_DIESEL
    print(f"  CO2e: {fuel_gal:.2f} gal × {EPA_DIESEL} kg/gal = {co2e_expected:.1f} kg CO₂e")
    
    # Step 4: Production type routing
    production_type = form_data["type"]
    print(f"\n🔀 Production Type Routing:")
    print(f"  Frontend type: '{production_type}' (should be 'PL')")
    
    if production_type == "PL":
        print(f"  ✅ Should route to planting calculations")
        print(f"  ✅ Should be in ['HA', 'PL', 'GE'] condition")
    else:
        print(f"  ❌ Unknown type routing")
    
    # Step 5: Expected vs Actual
    print(f"\n📊 Expected vs Actual:")
    print(f"  Expected: {co2e_expected:.1f} kg CO₂e")
    print(f"  Actual from screenshot: 0 kg CO₂e")
    print(f"  Difference: {co2e_expected:.1f} kg CO₂e missing!")
    
    print(f"\n🚨 POTENTIAL ISSUES:")
    issues = []
    
    # Check if fuel data could be lost
    if fuel_gal > 0:
        issues.append("✅ Fuel data present and valid")
    else:
        issues.append("❌ Fuel data missing or zero")
    
    # Check area
    if area_acres > 0:
        issues.append("✅ Area data present and valid")
    else:
        issues.append("❌ Area data missing or zero")
    
    # Check type
    if production_type == "PL":
        issues.append("✅ Production type should route correctly")
    else:
        issues.append("❌ Production type not recognized")
    
    for issue in issues:
        print(f"  {issue}")
    
    print(f"\n🔧 DEBUGGING STEPS NEEDED:")
    debug_steps = [
        "1. Check if MockEvent.fuel_consumed is actually 150.0",
        "2. Check if MockEvent.fuel_unit is 'L'", 
        "3. Verify fuel conversion: 150L / 3.78541 = 39.6 gallons",
        "4. Check if exception is being caught and returning 0.0",
        "5. Verify event.type == 'PL' reaches the right calculation branch",
        "6. Check if structured_data extraction is working correctly"
    ]
    
    for step in debug_steps:
        print(f"  {step}")
    
    print(f"\n💡 LIKELY ROOT CAUSE:")
    print(f"  The MockEvent may not be properly setting fuel_consumed or")
    print(f"  an exception is being caught in calculate_production_event_impact()")
    print(f"  that's returning the fallback value of 0.0")

if __name__ == "__main__":
    debug_production_zero()