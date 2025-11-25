#!/usr/bin/env python
"""
Debug chemical manufacturing emission calculations to understand overestimation
"""

import os
import sys
import django
from decimal import Decimal

# Django setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors

def debug_chemical_manufacturing():
    """Debug chemical manufacturing calculations step by step"""
    
    print("🔍 DEBUGGING CHEMICAL MANUFACTURING CALCULATIONS")
    print("=" * 60)
    print()
    
    # Test parameters - same as calibration test
    test_params = {
        'volume_liters': 189.3,  # 50 gallons
        'area_hectares': 0.404686,  # 1 acre
        'npk_content': {'N': 0, 'P': 0, 'K': 0},  # Non-fertilizer chemicals
        'application_method': 'spray'
    }
    
    # Test pesticide calculation step by step
    print("🧪 PESTICIDE (Chlorpyrifos 48EC) STEP-BY-STEP")
    print("-" * 50)
    print(f"Input volume: {test_params['volume_liters']} L")
    print(f"Input area: {test_params['area_hectares']} ha")
    print(f"NPK content: {test_params['npk_content']}")
    print()
    
    # Call the function and capture result
    result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
        chemical_type='pesticide',
        **test_params
    )
    
    print(f"✅ TOTAL RESULT: {result['co2e_kg']:.1f} kg CO2e")
    print(f"📊 Breakdown available: {len(result.get('breakdown', []))} components")
    print()
    
    # Show breakdown details
    if 'breakdown' in result:
        print("📋 EMISSION BREAKDOWN:")
        for i, component in enumerate(result['breakdown'], 1):
            print(f"  {i}. {component['component']}: {component['co2e_kg']:.1f} kg CO2e")
            print(f"     Source: {component.get('source', 'N/A')}")
            print(f"     Details: {component.get('calculation_details', 'N/A')}")
            print()
    
    # Let's also check what the manufacturing factor should be
    print("🔍 MANUFACTURING FACTOR ANALYSIS")
    print("-" * 40)
    
    # Check current factors
    factors = VerifiedEmissionFactors.EPA_CHEMICAL_FACTORS
    pesticide_factor = factors.get('pesticide_manufacturing')
    if pesticide_factor:
        print(f"Current pesticide manufacturing factor: {pesticide_factor.value} {pesticide_factor.unit}")
        print(f"Source: {pesticide_factor.source}")
        print()
    
    # Calculate what reasonable active ingredient amount would be
    print("💡 REASONABLE CALCULATION ANALYSIS")
    print("-" * 40)
    
    # For 50 gallons of pesticide solution:
    # - Typical active ingredient concentration: 2-10%
    # - Volume: 189.3 L
    # - If 5% active ingredient: 189.3 * 0.05 = 9.47 L = ~9.47 kg active ingredient
    # - If manufacturing factor is 95 kg CO2/kg: 9.47 * 95 = 900 kg CO2e (still too high)
    
    typical_concentrations = [0.02, 0.05, 0.10]  # 2%, 5%, 10%
    volume_kg = test_params['volume_liters']  # Assume 1 L ≈ 1 kg for chemical solutions
    
    print(f"Volume applied: {volume_kg} kg solution")
    for conc in typical_concentrations:
        active_kg = volume_kg * conc
        current_emissions = active_kg * 95  # Current factor
        target_emissions = 200  # Target around 180-220 kg CO2e
        needed_factor = target_emissions / active_kg
        
        print(f"At {conc*100}% concentration:")
        print(f"  Active ingredient: {active_kg:.2f} kg")
        print(f"  Current emissions: {current_emissions:.0f} kg CO2e")
        print(f"  Needed factor: {needed_factor:.1f} kg CO2e/kg active ingredient")
        print()

if __name__ == "__main__":
    debug_chemical_manufacturing()