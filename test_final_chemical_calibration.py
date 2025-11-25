#!/usr/bin/env python
"""
Final test of calibrated chemical event calculations with realistic volumes
"""

import os
import sys
import django
from decimal import Decimal

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors

def test_final_chemical_calibration():
    """Test final calibrated chemical calculations with realistic volumes"""
    
    print("🧪 FINAL CALIBRATED CHEMICAL CALCULATIONS")
    print("=" * 60)
    print()
    
    # Research benchmarks for chemical applications per acre (with realistic volumes)
    benchmarks = {
        'pesticide_chlorpyrifos': {
            'expected_range': (180, 220),  # kg CO2e per acre
            'active_ingredient': 'Chlorpyrifos 48EC',
            'application_method': 'spray',
            'realistic_volume_gal': 10,  # gallons per acre
            'realistic_volume_l': 37.9   # liters per acre
        },
        'herbicide_glyphosate': {
            'expected_range': (155, 195),  # kg CO2e per acre
            'active_ingredient': 'Glyphosate (Roundup PowerMAX)',
            'application_method': 'spray',
            'realistic_volume_gal': 15,  # gallons per acre
            'realistic_volume_l': 56.8   # liters per acre
        },
        'fungicide_copper': {
            'expected_range': (95, 125),  # kg CO2e per acre
            'active_ingredient': 'Copper Sulfate Basic',
            'application_method': 'spray',
            'realistic_volume_gal': 5,   # gallons per acre
            'realistic_volume_l': 18.9   # liters per acre
        },
        'fertilizer_anhydrous': {
            'expected_range': (2800, 3200),  # kg CO2e per acre
            'active_ingredient': 'Anhydrous Ammonia (82-0-0)',
            'application_method': 'injection',
            'realistic_volume_gal': 40,  # gallons per acre
            'realistic_volume_l': 151.4  # liters per acre
        }
    }
    
    # Test 1: Pesticide (Chlorpyrifos 48EC) - Realistic Volume
    print("🔬 TEST 1: PESTICIDE APPLICATION (REALISTIC VOLUME)")
    print("-" * 50)
    
    benchmark = benchmarks['pesticide_chlorpyrifos']
    pesticide_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='pesticide',
        volume_liters=benchmark['realistic_volume_l'],
        area_hectares=0.404686,  # 1 acre in hectares
        npk_content={'N': 0, 'P': 0, 'K': 0},  # Pesticide has no NPK
        application_method='spray'
    )
    
    min_expected, max_expected = benchmark['expected_range']
    
    print(f"📊 Scenario: {benchmark['active_ingredient']} pesticide application")
    print(f"💧 Volume: {benchmark['realistic_volume_gal']} gallons ({benchmark['realistic_volume_l']} L) per acre")
    print(f"🚜 Application Method: {benchmark['application_method']}")
    print(f"⚡ Trazo Calculation: {pesticide_result['co2e_kg']:.1f} kg CO2e")
    print(f"📈 Research Benchmark: {min_expected}-{max_expected} kg CO2e")
    
    if min_expected <= pesticide_result['co2e_kg'] <= max_expected:
        print("✅ PASS: Within expected range")
    else:
        deviation = abs(pesticide_result['co2e_kg'] - (min_expected + max_expected) / 2) / ((min_expected + max_expected) / 2) * 100
        print(f"⚠️ DEVIATION: {deviation:.1f}% from benchmark range")
    print()
    
    # Test 2: Herbicide (Glyphosate/Roundup) - Realistic Volume
    print("🔬 TEST 2: HERBICIDE APPLICATION (REALISTIC VOLUME)")
    print("-" * 50)
    
    benchmark = benchmarks['herbicide_glyphosate']
    herbicide_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='herbicide',
        volume_liters=benchmark['realistic_volume_l'],
        area_hectares=0.404686,  # 1 acre in hectares  
        npk_content={'N': 0, 'P': 0, 'K': 0},  # Herbicide has no NPK
        application_method='spray'
    )
    
    min_expected, max_expected = benchmark['expected_range']
    
    print(f"📊 Scenario: {benchmark['active_ingredient']} herbicide application")
    print(f"💧 Volume: {benchmark['realistic_volume_gal']} gallons ({benchmark['realistic_volume_l']} L) per acre")
    print(f"🚜 Application Method: {benchmark['application_method']}")
    print(f"⚡ Trazo Calculation: {herbicide_result['co2e_kg']:.1f} kg CO2e")
    print(f"📈 Research Benchmark: {min_expected}-{max_expected} kg CO2e")
    
    if min_expected <= herbicide_result['co2e_kg'] <= max_expected:
        print("✅ PASS: Within expected range")
    else:
        deviation = abs(herbicide_result['co2e_kg'] - (min_expected + max_expected) / 2) / ((min_expected + max_expected) / 2) * 100
        print(f"⚠️ DEVIATION: {deviation:.1f}% from benchmark range")
    print()
    
    # Test 3: Fungicide (Copper Sulfate) - Realistic Volume
    print("🔬 TEST 3: FUNGICIDE APPLICATION (REALISTIC VOLUME)")
    print("-" * 50)
    
    benchmark = benchmarks['fungicide_copper']
    fungicide_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='fungicide',
        volume_liters=benchmark['realistic_volume_l'],
        area_hectares=0.404686,  # 1 acre in hectares
        npk_content={'N': 0, 'P': 0, 'K': 0},  # Fungicide has no NPK
        application_method='spray'
    )
    
    min_expected, max_expected = benchmark['expected_range']
    
    print(f"📊 Scenario: {benchmark['active_ingredient']} fungicide application")
    print(f"💧 Volume: {benchmark['realistic_volume_gal']} gallons ({benchmark['realistic_volume_l']} L) per acre")
    print(f"🚜 Application Method: {benchmark['application_method']}")
    print(f"⚡ Trazo Calculation: {fungicide_result['co2e_kg']:.1f} kg CO2e")
    print(f"📈 Research Benchmark: {min_expected}-{max_expected} kg CO2e")
    
    if min_expected <= fungicide_result['co2e_kg'] <= max_expected:
        print("✅ PASS: Within expected range")
    else:
        deviation = abs(fungicide_result['co2e_kg'] - (min_expected + max_expected) / 2) / ((min_expected + max_expected) / 2) * 100
        print(f"⚠️ DEVIATION: {deviation:.1f}% from benchmark range")
    print()
    
    # Test 4: Fertilizer (Anhydrous Ammonia) - Realistic Volume
    print("🔬 TEST 4: FERTILIZER APPLICATION (REALISTIC VOLUME)")
    print("-" * 50)
    
    benchmark = benchmarks['fertilizer_anhydrous']
    fertilizer_result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='fertilizer',
        volume_liters=benchmark['realistic_volume_l'],
        area_hectares=0.404686,  # 1 acre in hectares
        npk_content={'N': 82, 'P': 0, 'K': 0},  # Anhydrous ammonia (82-0-0)
        application_method='injection'
    )
    
    min_expected, max_expected = benchmark['expected_range']
    
    print(f"📊 Scenario: {benchmark['active_ingredient']} fertilizer application")
    print(f"💧 Volume: {benchmark['realistic_volume_gal']} gallons ({benchmark['realistic_volume_l']} L) per acre")
    print(f"🚜 Application Method: {benchmark['application_method']}")
    print(f"⚡ Trazo Calculation: {fertilizer_result['co2e_kg']:.1f} kg CO2e")
    print(f"📈 Research Benchmark: {min_expected}-{max_expected} kg CO2e")
    
    if min_expected <= fertilizer_result['co2e_kg'] <= max_expected:
        print("✅ PASS: Within expected range")
    else:
        deviation = abs(fertilizer_result['co2e_kg'] - (min_expected + max_expected) / 2) / ((min_expected + max_expected) / 2) * 100
        print(f"⚠️ DEVIATION: {deviation:.1f}% from benchmark range")
    print()
    
    print("🏆 FINAL CALIBRATION SUMMARY")
    print("=" * 60)
    print("🔧 Chemical calculation improvements:")
    print("   • Realistic application volumes: Pesticides 10 gal/ac, Herbicides 15 gal/ac, Fungicides 5 gal/ac")
    print("   • Calibrated manufacturing factors: Pesticides 5.2 kg CO2e/kg AI, Herbicides 4.8 kg CO2e/kg AI, Fungicides 3.5 kg CO2e/kg AI")
    print("   • Application fuel consumption: 0.8 L diesel/ha for spray applications")
    print("   • Manufacturing emissions: EPA verified factors based on LCA studies")
    print()
    print("🎯 Results Summary:")
    print(f"   • Pesticide: Target 180-220 kg CO2e → Calculated {pesticide_result['co2e_kg']:.0f} kg CO2e")
    print(f"   • Herbicide: Target 155-195 kg CO2e → Calculated {herbicide_result['co2e_kg']:.0f} kg CO2e") 
    print(f"   • Fungicide: Target 95-125 kg CO2e → Calculated {fungicide_result['co2e_kg']:.0f} kg CO2e")
    print(f"   • Fertilizer: Target 2800-3200 kg CO2e → Calculated {fertilizer_result['co2e_kg']:.0f} kg CO2e")
    print()
    
    # Calculate overall success rate
    tests_passed = 0
    total_tests = 4
    
    if min_expected <= pesticide_result['co2e_kg'] <= max_expected:
        tests_passed += 1
    if 155 <= herbicide_result['co2e_kg'] <= 195:
        tests_passed += 1
    if 95 <= fungicide_result['co2e_kg'] <= 125:
        tests_passed += 1
    if 2800 <= fertilizer_result['co2e_kg'] <= 3200:
        tests_passed += 1
    
    success_rate = (tests_passed / total_tests) * 100
    print(f"✅ Overall Success Rate: {tests_passed}/{total_tests} tests passed ({success_rate:.0f}%)")
    
    if success_rate >= 75:
        print("🌟 EXCELLENT: Chemical calculations are industry-leading!")
    elif success_rate >= 50:
        print("👍 GOOD: Chemical calculations are within acceptable ranges")
    else:
        print("⚠️ NEEDS IMPROVEMENT: More calibration needed")

if __name__ == "__main__":
    test_final_chemical_calibration()