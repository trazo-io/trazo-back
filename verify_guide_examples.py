#!/usr/bin/env python3
"""
Verification script for TRAZO_COMPREHENSIVE_EVENT_AUDIT_GUIDE.md examples
Tests real-world cases against current enhanced carbon calculation system
"""

import os
import sys
import django
from decimal import Decimal

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.services.verified_emission_factors import VerifiedEmissionFactors

def test_california_avocado_case():
    """
    Test case from guide: California Avocado Farm
    - Chemical: "Citrus Special 15-5-10" (Fertilizer)
    - Volume: 520 L
    - Area: 2.1 ha
    - Application method: "broadcast"
    - Expected: 309 kg CO2e
    """
    print("🥑 Testing California Avocado Farm Case")
    print("=" * 50)
    
    # Extract NPK from concentration
    npk_content = {"N": 15, "P": 5, "K": 10}
    volume_applied = 520  # L
    area_treated = 2.1   # ha
    application_method = "broadcast"
    expected_carbon = 309  # kg CO2e
    
    try:
        # Test with our enhanced backend logic
        result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type="FE",  # Fertilizer
            volume_liters=volume_applied,
            area_hectares=area_treated,
            npk_content=npk_content,
            application_method=application_method
        )
        
        calculated_carbon = result['co2e_kg']
        density_used = result.get('fertilizer_density_kg_per_l', 'N/A')
        
        print(f"NPK Content: {npk_content}")
        print(f"Volume Applied: {volume_applied} L")
        print(f"Area Treated: {area_treated} ha")
        print(f"Application Method: {application_method}")
        print(f"Density Used: {density_used} kg/L")
        print(f"Expected Carbon: {expected_carbon} kg CO2e")
        print(f"Calculated Carbon: {calculated_carbon} kg CO2e")
        
        difference = abs(calculated_carbon - expected_carbon)
        percentage_diff = (difference / expected_carbon) * 100
        
        print(f"Difference: {difference:.2f} kg CO2e ({percentage_diff:.1f}%)")
        
        if percentage_diff <= 5:
            print("✅ RESULT: Numbers align perfectly (≤5% difference)")
        elif percentage_diff <= 15:
            print("⚠️ RESULT: Minor alignment issue (5-15% difference)")
        else:
            print("❌ RESULT: Significant misalignment (>15% difference)")
            
        return {
            'test_name': 'California Avocado',
            'expected': expected_carbon,
            'calculated': calculated_carbon,
            'difference': difference,
            'percentage_diff': percentage_diff,
            'density_used': density_used,
            'status': 'pass' if percentage_diff <= 5 else 'review' if percentage_diff <= 15 else 'fail'
        }
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return {
            'test_name': 'California Avocado',
            'error': str(e),
            'status': 'error'
        }

def test_iowa_corn_anhydrous_case():
    """
    Test case from guide: Iowa Corn Farm
    - Chemical: "82-0-0" (Anhydrous Ammonia)
    - Volume: 3320 kg (needs conversion to L using 0.68 kg/L density)
    - Area: 40.5 ha
    - Application method: "injection"
    - Expected: 28,755.5 kg CO2e
    """
    print("\n🌽 Testing Iowa Corn Farm Anhydrous Ammonia Case")
    print("=" * 50)
    
    # Extract NPK from concentration
    npk_content = {"N": 82, "P": 0, "K": 0}
    volume_kg = 3320  # kg
    # Convert to L using anhydrous ammonia density (0.68 kg/L)
    volume_applied = volume_kg / 0.68  # L
    area_treated = 40.5   # ha
    application_method = "injection"
    expected_carbon = 28755.5  # kg CO2e
    
    try:
        # Test with our enhanced backend logic
        result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type="FE",  # Fertilizer
            volume_liters=volume_applied,
            area_hectares=area_treated,
            npk_content=npk_content,
            application_method=application_method
        )
        
        calculated_carbon = result['co2e_kg']
        density_used = result.get('fertilizer_density_kg_per_l', 'N/A')
        
        print(f"NPK Content: {npk_content}")
        print(f"Volume Applied: {volume_kg} kg = {volume_applied:.1f} L")
        print(f"Area Treated: {area_treated} ha")
        print(f"Application Method: {application_method}")
        print(f"Density Used: {density_used} kg/L")
        print(f"Expected Carbon: {expected_carbon} kg CO2e")
        print(f"Calculated Carbon: {calculated_carbon} kg CO2e")
        
        difference = abs(calculated_carbon - expected_carbon)
        percentage_diff = (difference / expected_carbon) * 100
        
        print(f"Difference: {difference:.2f} kg CO2e ({percentage_diff:.1f}%)")
        
        if percentage_diff <= 5:
            print("✅ RESULT: Numbers align perfectly (≤5% difference)")
        elif percentage_diff <= 15:
            print("⚠️ RESULT: Minor alignment issue (5-15% difference)")
        else:
            print("❌ RESULT: Significant misalignment (>15% difference)")
            
        return {
            'test_name': 'Iowa Corn Anhydrous',
            'expected': expected_carbon,
            'calculated': calculated_carbon,
            'difference': difference,
            'percentage_diff': percentage_diff,
            'density_used': density_used,
            'status': 'pass' if percentage_diff <= 5 else 'review' if percentage_diff <= 15 else 'fail'
        }
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return {
            'test_name': 'Iowa Corn Anhydrous',
            'error': str(e),
            'status': 'error'
        }

def test_texas_cotton_liquid_case():
    """
    Test case from guide: Texas Cotton Farm
    - Chemical: "28-0-0" (Liquid UAN)
    - Volume: 760 L
    - Area: 8.1 ha
    - Application method: "fertigation"
    - Expected: ~480-520 kg CO2e (estimate based on guide pattern)
    """
    print("\n🌾 Testing Texas Cotton Farm Liquid UAN Case")
    print("=" * 50)
    
    # Extract NPK from concentration
    npk_content = {"N": 28, "P": 0, "K": 0}
    volume_applied = 760  # L
    area_treated = 8.1   # ha
    application_method = "fertigation"
    expected_carbon = 500  # kg CO2e (estimated from guide)
    
    try:
        # Test with our enhanced backend logic
        result = VerifiedEmissionFactors.calculate_chemical_application_emissions(
            chemical_type="FE",  # Fertilizer
            volume_liters=volume_applied,
            area_hectares=area_treated,
            npk_content=npk_content,
            application_method=application_method
        )
        
        calculated_carbon = result['co2e_kg']
        density_used = result.get('fertilizer_density_kg_per_l', 'N/A')
        
        print(f"NPK Content: {npk_content}")
        print(f"Volume Applied: {volume_applied} L")
        print(f"Area Treated: {area_treated} ha")
        print(f"Application Method: {application_method}")
        print(f"Density Used: {density_used} kg/L")
        print(f"Expected Carbon: ~{expected_carbon} kg CO2e (estimated)")
        print(f"Calculated Carbon: {calculated_carbon} kg CO2e")
        
        difference = abs(calculated_carbon - expected_carbon)
        percentage_diff = (difference / expected_carbon) * 100
        
        print(f"Difference: {difference:.2f} kg CO2e ({percentage_diff:.1f}%)")
        
        # More lenient for estimated value
        if percentage_diff <= 10:
            print("✅ RESULT: Numbers align well (≤10% difference)")
        elif percentage_diff <= 25:
            print("⚠️ RESULT: Reasonable alignment (10-25% difference)")
        else:
            print("❌ RESULT: Significant misalignment (>25% difference)")
            
        return {
            'test_name': 'Texas Cotton Liquid',
            'expected': expected_carbon,
            'calculated': calculated_carbon,
            'difference': difference,
            'percentage_diff': percentage_diff,
            'density_used': density_used,
            'status': 'pass' if percentage_diff <= 10 else 'review' if percentage_diff <= 25 else 'fail'
        }
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return {
            'test_name': 'Texas Cotton Liquid',
            'error': str(e),
            'status': 'error'
        }

def test_application_method_density_mapping():
    """
    Test that our enhanced application method mapping works correctly
    for different methods mentioned in the guide
    """
    print("\n🔧 Testing Application Method Density Mapping")
    print("=" * 50)
    
    test_methods = [
        ("broadcast", 0.80, "Granular"),
        ("broadcast_surface", 0.80, "Granular"), 
        ("fertigation", 1.25, "Liquid irrigation"),
        ("injection", 1.30, "High-N injection"),
        ("soil_injection_liquid", 1.30, "High-N injection"),
        ("foliar_feed", 1.25, "Standard liquid"),
        ("granular_spreader", 0.80, "Granular"),
    ]
    
    try:
        from carbon.services.verified_emission_factors import VerifiedEmissionFactors
        
        for method, expected_density, description in test_methods:
            # Use a standard NPK for testing density selection
            npk_content = {"N": 15, "P": 5, "K": 10}
            
            # Get density using the private method (for testing only)
            actual_density = VerifiedEmissionFactors._get_fertilizer_density(
                npk_content=npk_content,
                application_method=method
            )
            
            status = "✅" if actual_density == expected_density else "❌"
            print(f"{status} {method:<20} → {actual_density} kg/L (expected {expected_density}) - {description}")
            
    except Exception as e:
        print(f"❌ ERROR in density mapping test: {str(e)}")

def main():
    """Run all verification tests"""
    print("🔍 TRAZO COMPREHENSIVE EVENT AUDIT GUIDE VERIFICATION")
    print("=" * 60)
    print("Testing real-world cases against enhanced carbon calculation system")
    print("=" * 60)
    
    results = []
    
    # Test individual cases
    results.append(test_california_avocado_case())
    results.append(test_iowa_corn_anhydrous_case())
    results.append(test_texas_cotton_liquid_case())
    
    # Test application method mapping
    test_application_method_density_mapping()
    
    # Summary
    print("\n📊 VERIFICATION SUMMARY")
    print("=" * 30)
    
    pass_count = sum(1 for r in results if r.get('status') == 'pass')
    review_count = sum(1 for r in results if r.get('status') == 'review')
    fail_count = sum(1 for r in results if r.get('status') == 'fail')
    error_count = sum(1 for r in results if r.get('status') == 'error')
    
    print(f"✅ Perfect Alignment: {pass_count}/{len(results)}")
    print(f"⚠️ Minor Issues: {review_count}/{len(results)}")
    print(f"❌ Major Issues: {fail_count}/{len(results)}")
    print(f"🚨 Errors: {error_count}/{len(results)}")
    
    if pass_count == len(results):
        print("\n🎯 CONCLUSION: All guide numbers perfectly align with current system!")
    elif pass_count + review_count == len(results):
        print("\n📝 CONCLUSION: Guide mostly accurate, minor updates may be needed")
    else:
        print("\n⚠️ CONCLUSION: Guide needs significant updates for current system")
    
    return results

if __name__ == "__main__":
    main()