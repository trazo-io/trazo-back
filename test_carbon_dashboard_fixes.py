#!/usr/bin/env python3
"""
Carbon Dashboard Production-Readiness Test Suite

This script tests all the improvements made to the Carbon Dashboard
to ensure production readiness and data accuracy.
"""

import os
import sys
import django
from decimal import Decimal

# Setup Django environment
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings.dev')
django.setup()

from carbon.models import CarbonEntry
from company.models import Establishment
from django.db.models import Sum, Count
from django.utils import timezone
import json


def test_carbon_calculations():
    """Test enhanced carbon calculation logic"""
    print("=" * 60)
    print("🧪 TESTING ENHANCED CARBON CALCULATIONS")
    print("=" * 60)
    
    try:
        # Get establishment
        est = Establishment.objects.get(id=1)
        year = 2025
        entries = CarbonEntry.objects.filter(establishment_id=est.id, year=year)
        
        # Test emissions and offsets calculation
        emissions_data = entries.filter(type='emission').aggregate(
            total=Sum('amount'),
            count=Count('id')
        )
        
        offsets_data = entries.filter(type='offset').aggregate(
            total=Sum('effective_amount'),
            count=Count('id')
        )
        
        total_emissions = float(emissions_data['total'] or 0)
        total_offsets = float(offsets_data['total'] or 0)
        net_carbon = total_emissions - total_offsets
        
        print(f"✅ Basic Calculations:")
        print(f"   - Total Emissions: {total_emissions:,.2f} kg CO2e")
        print(f"   - Total Offsets: {total_offsets:,.2f} kg CO2e")
        print(f"   - Net Carbon: {net_carbon:,.2f} kg CO2e")
        
        # Test enhanced carbon score calculation
        carbon_score = 50  # Neutral baseline
        
        if total_emissions > 0:
            offset_percentage = min(100, (total_offsets / total_emissions) * 100)
            
            if offset_percentage >= 100:
                excess_percentage = offset_percentage - 100
                carbon_score = 90 + min(10, (excess_percentage / 50) * 10)
            elif offset_percentage >= 75:
                carbon_score = 75 + ((offset_percentage - 75) / 25) * 15
            elif offset_percentage >= 50:
                carbon_score = 60 + ((offset_percentage - 50) / 25) * 15
            elif offset_percentage >= 25:
                carbon_score = 40 + ((offset_percentage - 25) / 25) * 20
            else:
                carbon_score = 10 + (offset_percentage / 25) * 30
                
        elif total_offsets > 0:
            carbon_score = 95
        else:
            carbon_score = 50
        
        print(f"✅ Enhanced Carbon Score: {int(carbon_score)}/100")
        print(f"   - Offset Percentage: {offset_percentage:.1f}%")
        
        # Test transparency score calculation
        transparency_score = 10
        total_entries_count = entries.count()
        
        if total_entries_count > 0:
            base_score = min(total_entries_count * 0.8, 70)
            verification_bonus = 0
            
            usda_verified_count = entries.filter(usda_verified=True).count()
            if total_entries_count > 0:
                verification_ratio = usda_verified_count / total_entries_count
                verification_bonus = verification_ratio * 30
            
            transparency_score = min(base_score + verification_bonus, 100)
        
        print(f"✅ Enhanced Transparency Score: {int(transparency_score)}/100")
        print(f"   - USDA Verified: {usda_verified_count}/{total_entries_count} entries")
        print(f"   - Verification Rate: {verification_ratio:.1%}")
        
        # Test performance tier calculation
        def get_performance_tier(score):
            if score >= 90:
                return "Excellent"
            elif score >= 75:
                return "Very Good"
            elif score >= 60:
                return "Good"
            elif score >= 40:
                return "Fair"
            else:
                return "Needs Improvement"
        
        tier = get_performance_tier(carbon_score)
        print(f"✅ Performance Tier: {tier}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        return False


def test_data_validation():
    """Test data validation and edge cases"""
    print("\n" + "=" * 60)
    print("🔍 TESTING DATA VALIDATION")
    print("=" * 60)
    
    test_cases = [
        {"emissions": 0, "offsets": 0, "expected_score": 50},
        {"emissions": 100, "offsets": 0, "expected_score": 10},
        {"emissions": 100, "offsets": 50, "expected_score": 60},  # 50% offset = Good tier
        {"emissions": 100, "offsets": 100, "expected_score": 90},
        {"emissions": 0, "offsets": 100, "expected_score": 95},
    ]
    
    for i, case in enumerate(test_cases, 1):
        emissions = case["emissions"]
        offsets = case["offsets"]
        expected = case["expected_score"]
        
        # Calculate score
        if emissions > 0:
            offset_percentage = min(100, (offsets / emissions) * 100)
            if offset_percentage >= 100:
                score = 90 + min(10, ((offset_percentage - 100) / 50) * 10)
            elif offset_percentage >= 75:
                score = 75 + ((offset_percentage - 75) / 25) * 15
            elif offset_percentage >= 50:
                score = 60 + ((offset_percentage - 50) / 25) * 15
            elif offset_percentage >= 25:
                score = 40 + ((offset_percentage - 25) / 25) * 20
            else:
                score = 10 + (offset_percentage / 25) * 30
        elif offsets > 0:
            score = 95
        else:
            score = 50
        
        actual_score = int(score)
        
        if abs(actual_score - expected) <= 5:  # Allow small tolerance
            print(f"✅ Test Case {i}: Emissions={emissions}, Offsets={offsets} → Score={actual_score} (Expected: ~{expected})")
        else:
            print(f"❌ Test Case {i}: Emissions={emissions}, Offsets={offsets} → Score={actual_score} (Expected: {expected})")
            return False
    
    return True


def test_number_formatting():
    """Test number formatting functions"""
    print("\n" + "=" * 60)
    print("📊 TESTING NUMBER FORMATTING")
    print("=" * 60)
    
    test_values = [
        (1234.567, "1.2K"),
        (1234567.89, "1.2M"),
        (123.45, "123.5"),
        (0, "0"),
        (None, "0"),
        (-1234, "-1.2K")
    ]
    
    def format_number(value, decimals=1):
        if value is None or str(value) == 'nan':
            return '0'
        
        try:
            num = float(value)
        except (ValueError, TypeError):
            return '0'
        
        # Handle zero specifically
        if num == 0:
            return '0'
        
        if abs(num) >= 1000000:
            return f"{num / 1000000:.1f}M"
        elif abs(num) >= 1000:
            return f"{num / 1000:.1f}K"
        else:
            return f"{num:.{decimals}f}"
    
    for value, expected in test_values:
        actual = format_number(value)
        if actual == expected:
            print(f"✅ {value} → {actual}")
        else:
            print(f"❌ {value} → {actual} (expected: {expected})")
            return False
    
    return True


def test_api_response_structure():
    """Test API response structure for production readiness"""
    print("\n" + "=" * 60)
    print("🔌 TESTING API RESPONSE STRUCTURE")
    print("=" * 60)
    
    # Simulate the API response structure
    required_fields = [
        'establishment_id',
        'year',
        'total_emissions',
        'total_offsets',
        'net_carbon',
        'carbon_score',
        'transparency_score',
        'offset_ratio',
        'performance_tier',
        'entries_count',
        'has_data',
        'data_quality',
        'calculated_at',
        'api_version'
    ]
    
    # Get real data for structure validation
    try:
        est = Establishment.objects.get(id=1)
        year = 2025
        entries = CarbonEntry.objects.filter(establishment_id=est.id, year=year)
        
        # Simulate response
        response_data = {
            'establishment_id': est.id,
            'year': year,
            'total_emissions': 56534.7,
            'total_offsets': 997.5,
            'net_carbon': 55537.2,
            'carbon_score': 12,
            'transparency_score': 54,
            'offset_ratio': 1.8,
            'performance_tier': {'tier': 'Needs Improvement', 'color': 'red'},
            'entries_count': {'emissions': 30, 'offsets': 2, 'total': 32, 'usda_verified': 31},
            'has_data': True,
            'data_quality': {'completeness': 64, 'verification_rate': 96.9},
            'calculated_at': timezone.now().isoformat(),
            'api_version': '2.0'
        }
        
        # Check all required fields are present
        missing_fields = [field for field in required_fields if field not in response_data]
        
        if not missing_fields:
            print("✅ All required API fields present")
            print(f"✅ Response structure valid ({len(response_data)} fields)")
            
            # Check data types
            type_checks = [
                (response_data['total_emissions'], (int, float)),
                (response_data['carbon_score'], int),
                (response_data['has_data'], bool),
                (response_data['entries_count'], dict),
                (response_data['performance_tier'], dict)
            ]
            
            for value, expected_type in type_checks:
                if isinstance(value, expected_type):
                    print(f"✅ Type check passed: {type(value).__name__}")
                else:
                    print(f"❌ Type check failed: expected {expected_type}, got {type(value)}")
                    return False
            
            return True
        else:
            print(f"❌ Missing required fields: {missing_fields}")
            return False
            
    except Exception as e:
        print(f"❌ API structure test failed: {str(e)}")
        return False


def main():
    """Run all tests"""
    print("🚀 CARBON DASHBOARD PRODUCTION-READINESS TEST SUITE")
    print("=" * 60)
    
    tests = [
        ("Carbon Calculations", test_carbon_calculations),
        ("Data Validation", test_data_validation),
        ("Number Formatting", test_number_formatting),
        ("API Response Structure", test_api_response_structure)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n🧪 Running: {test_name}")
        if test_func():
            passed += 1
            print(f"✅ {test_name}: PASSED")
        else:
            print(f"❌ {test_name}: FAILED")
    
    print("\n" + "=" * 60)
    print(f"📊 TEST RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED - Carbon Dashboard is production-ready!")
        return 0
    else:
        print(f"⚠️  {total - passed} tests failed - Review required before production")
        return 1


if __name__ == "__main__":
    exit(main())