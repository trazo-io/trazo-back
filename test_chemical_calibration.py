#!/usr/bin/env python
"""
Test calibrated chemical event calculations against research benchmarks
"""

import os
import sys
import django
from decimal import Decimal

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors

def test_calibrated_chemical_calculations():
    """Test calibrated chemical calculations against research benchmarks"""
    
    print("🧪 TESTING CALIBRATED CHEMICAL CALCULATIONS")
    print("=" * 60)
    print()
    
    # Research benchmarks for chemical applications per acre
    benchmarks = {
        'pesticide_chlorpyrifos': {
            'expected_range': (180, 220),  # kg CO2e per acre
            'active_ingredient': 'Chlorpyrifos 48EC',
            'application_method': 'spray'
        },
        'herbicide_glyphosate': {
            'expected_range': (155, 195),  # kg CO2e per acre
            'active_ingredient': 'Glyphosate (Roundup PowerMAX)',
            'application_method': 'spray'
        },
        'fungicide_copper': {
            'expected_range': (95, 125),  # kg CO2e per acre
            'active_ingredient': 'Copper Sulfate Basic',
            'application_method': 'spray'
        },
        'fertilizer_anhydrous': {
            'expected_range': (2800, 3200),  # kg CO2e per acre
            'active_ingredient': 'Anhydrous Ammonia (82-0-0)',
            'application_method': 'injection'
        }
    }
    
    # Test 1: Pesticide (Chlorpyrifos 48EC)
    print("🔬 TEST 1: PESTICIDE APPLICATION (CALIBRATED)")
    print("-" * 45)
    
    pesticide_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='pesticide',
        volume_liters=189.3,  # 50 gallons converted to liters
        area_hectares=0.404686,  # 1 acre in hectares
        npk_content={'N': 0, 'P': 0, 'K': 0},  # Pesticide has no NPK
        application_method='spray'
    )
    
    benchmark = benchmarks['pesticide_chlorpyrifos']
    min_expected, max_expected = benchmark['expected_range']
    
    print(f"📊 Scenario: Chlorpyrifos 48EC pesticide application")
    print(f"💧 Volume: 50 gallons (189.3 L) per acre")
    print(f"🚜 Application Method: {benchmark['application_method']}")
    print(f"⚡ Trazo Calculation: {pesticide_result['co2e_kg']:.1f} kg CO2e")
    print(f"📈 Research Benchmark: {min_expected}-{max_expected} kg CO2e")
    
    if min_expected <= pesticide_result['co2e_kg'] <= max_expected:
        print("✅ PASS: Within expected range")
    else:
        deviation = abs(pesticide_result['co2e_kg'] - (min_expected + max_expected) / 2) / ((min_expected + max_expected) / 2) * 100
        print(f"❌ DEVIATION: {deviation:.1f}% from benchmark range")
    print()
    
    # Test 2: Herbicide (Glyphosate/Roundup)
    print("🔬 TEST 2: HERBICIDE APPLICATION (CALIBRATED)")
    print("-" * 45)
    
    herbicide_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='herbicide',
        volume_liters=189.3,  # 50 gallons converted to liters
        area_hectares=0.404686,  # 1 acre in hectares  
        npk_content={'N': 0, 'P': 0, 'K': 0},  # Herbicide has no NPK
        application_method='spray'
    )
    
    benchmark = benchmarks['herbicide_glyphosate']
    min_expected, max_expected = benchmark['expected_range']
    
    print(f"📊 Scenario: Glyphosate (Roundup PowerMAX) herbicide application")
    print(f"💧 Volume: 50 gallons (189.3 L) per acre")
    print(f"🚜 Application Method: {benchmark['application_method']}")
    print(f"⚡ Trazo Calculation: {herbicide_result['co2e_kg']:.1f} kg CO2e")
    print(f"📈 Research Benchmark: {min_expected}-{max_expected} kg CO2e")
    
    if min_expected <= herbicide_result['co2e_kg'] <= max_expected:
        print("✅ PASS: Within expected range")
    else:
        deviation = abs(herbicide_result['co2e_kg'] - (min_expected + max_expected) / 2) / ((min_expected + max_expected) / 2) * 100
        print(f"❌ DEVIATION: {deviation:.1f}% from benchmark range")
    print()
    
    # Test 3: Fungicide (Copper Sulfate)
    print("🔬 TEST 3: FUNGICIDE APPLICATION (CALIBRATED)")
    print("-" * 45)
    
    fungicide_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='fungicide',
        volume_liters=189.3,  # 50 gallons converted to liters
        area_hectares=0.404686,  # 1 acre in hectares
        npk_content={'N': 0, 'P': 0, 'K': 0},  # Fungicide has no NPK
        application_method='spray'
    )
    
    benchmark = benchmarks['fungicide_copper']
    min_expected, max_expected = benchmark['expected_range']
    
    print(f"📊 Scenario: Copper Sulfate Basic fungicide application")
    print(f"💧 Volume: 50 gallons (189.3 L) per acre")
    print(f"🚜 Application Method: {benchmark['application_method']}")
    print(f"⚡ Trazo Calculation: {fungicide_result['co2e_kg']:.1f} kg CO2e")
    print(f"📈 Research Benchmark: {min_expected}-{max_expected} kg CO2e")
    
    if min_expected <= fungicide_result['co2e_kg'] <= max_expected:
        print("✅ PASS: Within expected range")
    else:
        deviation = abs(fungicide_result['co2e_kg'] - (min_expected + max_expected) / 2) / ((min_expected + max_expected) / 2) * 100
        print(f"❌ DEVIATION: {deviation:.1f}% from benchmark range")
    print()
    
    # Test 4: Fertilizer (should remain accurate)
    print("🔬 TEST 4: FERTILIZER APPLICATION (VERIFICATION)")
    print("-" * 45)
    
    fertilizer_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='fertilizer',
        volume_liters=189.3,  # 50 gallons converted to liters
        area_hectares=0.404686,  # 1 acre in hectares
        npk_content={'N': 82, 'P': 0, 'K': 0},  # Anhydrous ammonia (82-0-0)
        application_method='injection'
    )
    
    benchmark = benchmarks['fertilizer_anhydrous']
    min_expected, max_expected = benchmark['expected_range']
    
    print(f"📊 Scenario: Anhydrous Ammonia (82-0-0) fertilizer application")
    print(f"💧 Volume: 50 gallons (189.3 L) per acre")
    print(f"🚜 Application Method: {benchmark['application_method']}")
    print(f"⚡ Trazo Calculation: {fertilizer_result['co2e_kg']:.1f} kg CO2e")
    print(f"📈 Research Benchmark: {min_expected}-{max_expected} kg CO2e")
    
    if min_expected <= fertilizer_result['co2e_kg'] <= max_expected:
        print("✅ PASS: Within expected range")
    else:
        deviation = abs(fertilizer_result['co2e_kg'] - (min_expected + max_expected) / 2) / ((min_expected + max_expected) / 2) * 100
        print(f"❌ DEVIATION: {deviation:.1f}% from benchmark range")
    print()
    
    print("🏆 CALIBRATION SUMMARY")
    print("=" * 60)
    print("🔧 Fixed chemical application fuel consumption rates:")
    print("   • Pesticides/Herbicides/Fungicides: 0.8 L diesel/ha (CALIBRATED)")
    print("   • Fertilizer injection: 3.0 L diesel/ha (realistic)")
    print("   • Manufacturing emissions: EPA verified factors (unchanged)")
    print()
    print("🎯 Expected Results:")
    print(f"   • Pesticide: Target 180-220 kg CO2e → Calculated {pesticide_result['co2e_kg']:.0f} kg CO2e")
    print(f"   • Herbicide: Target 155-195 kg CO2e → Calculated {herbicide_result['co2e_kg']:.0f} kg CO2e") 
    print(f"   • Fungicide: Target 95-125 kg CO2e → Calculated {fungicide_result['co2e_kg']:.0f} kg CO2e")
    print(f"   • Fertilizer: Target 2800-3200 kg CO2e → Calculated {fertilizer_result['co2e_kg']:.0f} kg CO2e")

if __name__ == "__main__":
    test_calibrated_chemical_calculations()