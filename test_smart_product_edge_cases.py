#!/usr/bin/env python3
"""
SMART PRODUCT VALIDATOR EDGE CASE TESTING
Test the validation system with problematic inputs that should NOT match agricultural products.
"""

import sys
import os

# Add the Django project to the path
sys.path.append('/Users/oscarmunoz/dev/trazo/trazo-back')

# Import the validator directly without Django setup
from carbon.services.smart_product_validator import SmartProductValidator, smart_product_validator

def test_edge_cases():
    """Test the validator with various edge cases that should NOT produce meaningful matches"""
    
    print("🔍 TESTING SMART PRODUCT VALIDATOR EDGE CASES")
    print("="*60)
    
    # Test cases that should NOT match or have very low confidence
    edge_cases = [
        # Completely meaningless strings
        "ads",
        "xyz",
        "random", 
        "asdfgh",
        "qwerty",
        "123456",
        "test",
        "blah",
        "nonsense",
        "garbage",
        
        # Single letters/numbers
        "a",
        "z",
        "1",
        "9",
        
        # Common words that aren't products
        "car",
        "house",
        "phone",
        "computer",
        "water",
        "food",
        "book",
        
        # Partial agricultural terms but not products
        "fer",  # partial "fertilizer"
        "pest", # partial "pesticide" 
        "herb", # partial "herbicide"
        "fung", # partial "fungicide"
        
        # Empty/minimal strings
        "",
        " ",
        "  ",
        "-",
        "_",
        
        # Special characters
        "!@#$%",
        "***",
        "???",
        "---",
    ]
    
    validator = SmartProductValidator()
    total_tests = len(edge_cases)
    failed_tests = []
    
    for i, test_input in enumerate(edge_cases, 1):
        print(f"\n[{i}/{total_tests}] Testing: '{test_input}'")
        
        # Test smart product search
        search_results = validator.smart_product_search(test_input, max_suggestions=3)
        
        if search_results:
            print(f"  ❌ PROBLEM: Got {len(search_results)} search results:")
            for result in search_results:
                confidence = result.get('confidence', 0)
                name = result.get('name', 'Unknown')
                type_code = result.get('type_code', 'Unknown')
                why_matched = result.get('why_matched', 'No explanation')
                
                print(f"    - {name} ({type_code}) - {confidence:.1%} confidence")
                print(f"      Reason: {why_matched}")
                
                # Flag as failed if confidence > 10% for meaningless input
                if confidence > 0.10:
                    failed_tests.append({
                        'input': test_input,
                        'matched_product': name,
                        'confidence': confidence,
                        'type': type_code,
                        'reason': why_matched
                    })
        else:
            print("  ✅ GOOD: No search results")
        
        # Test validation with FE type (common type)
        validation_result = validator.validate_smart_product(test_input, "FE", confidence_threshold=0.7)
        
        if validation_result.confidence > 0.20:
            print(f"  ❌ VALIDATION PROBLEM: {validation_result.confidence:.1%} confidence")
            print(f"    Product: {validation_result.commercial_name}")
            print(f"    Type: {validation_result.correct_type}")
            if validation_result.warnings:
                print(f"    Warnings: {validation_result.warnings}")
            
            if validation_result.confidence > 0.20:
                failed_tests.append({
                    'input': test_input,
                    'validation_confidence': validation_result.confidence,
                    'validation_type': validation_result.correct_type,
                    'test_type': 'validation'
                })
        else:
            print(f"  ✅ VALIDATION OK: {validation_result.confidence:.1%} confidence")
    
    # Summary report
    print("\n" + "="*60)
    print("🚨 EDGE CASE TESTING SUMMARY")
    print("="*60)
    
    if failed_tests:
        print(f"❌ FAILED: {len(failed_tests)} of {total_tests} tests failed")
        print("\nPROBLEMATIC RESULTS:")
        
        for failure in failed_tests:
            print(f"\n  Input: '{failure['input']}'")
            if 'matched_product' in failure:
                print(f"  → Matched: {failure['matched_product']} ({failure['type']})")
                print(f"  → Confidence: {failure['confidence']:.1%}")
                print(f"  → Reason: {failure['reason']}")
            elif 'validation_confidence' in failure:
                print(f"  → Validation confidence: {failure['validation_confidence']:.1%}")
                print(f"  → Detected type: {failure['validation_type']}")
    else:
        print(f"✅ SUCCESS: All {total_tests} edge case tests passed!")
    
    return failed_tests

def test_confidence_scoring_accuracy():
    """Test confidence scoring with known good and bad matches"""
    
    print("\n" + "="*60)
    print("🎯 TESTING CONFIDENCE SCORING ACCURACY")
    print("="*60)
    
    validator = SmartProductValidator()
    
    # Test cases with expected confidence ranges
    test_cases = [
        # Should have HIGH confidence (>80%)
        ("miracle-gro", "Expected: HIGH confidence"),
        ("roundup", "Expected: HIGH confidence"),
        ("urea", "Expected: HIGH confidence"),
        ("10-10-10", "Expected: HIGH confidence"),
        
        # Should have MEDIUM confidence (40-80%)
        ("miracle grow", "Expected: MEDIUM confidence (typo)"),
        ("round up", "Expected: MEDIUM confidence (space)"),
        ("fertilizer", "Expected: MEDIUM confidence (generic)"),
        ("herbicide", "Expected: MEDIUM confidence (generic)"),
        
        # Should have LOW/NO confidence (<40%)
        ("miracle", "Expected: LOW confidence (partial)"),
        ("gro", "Expected: LOW confidence (partial)"),
        ("ads", "Expected: NO confidence (meaningless)"),
        ("xyz", "Expected: NO confidence (meaningless)"),
    ]
    
    for test_input, expectation in test_cases:
        print(f"\nTesting: '{test_input}' - {expectation}")
        
        results = validator.smart_product_search(test_input, max_suggestions=1)
        
        if results:
            confidence = results[0].get('confidence', 0)
            name = results[0].get('name', 'Unknown')
            print(f"  Result: {name} - {confidence:.1%} confidence")
            
            # Analyze if confidence makes sense
            if test_input in ['ads', 'xyz'] and confidence > 0.10:
                print(f"  ❌ PROBLEM: Meaningless input '{test_input}' has {confidence:.1%} confidence!")
            elif test_input in ['miracle-gro', 'roundup', 'urea'] and confidence < 0.80:
                print(f"  ⚠️  WARNING: Exact match '{test_input}' has only {confidence:.1%} confidence")
            else:
                print(f"  ✅ Confidence level seems appropriate")
        else:
            print(f"  No results found")

def analyze_database_quality():
    """Analyze the SMART_PRODUCT_DATABASE for completeness and accuracy"""
    
    print("\n" + "="*60) 
    print("📊 ANALYZING SMART_PRODUCT_DATABASE QUALITY")
    print("="*60)
    
    validator = SmartProductValidator()
    db = validator.SMART_PRODUCT_DATABASE
    
    stats = validator.get_validation_stats()
    print(f"Total products: {stats['total_products']}")
    print(f"Fertilizers (FE): {stats['fertilizers']}")
    print(f"Pesticides (PE): {stats['pesticides']}")
    print(f"Fungicides (FU): {stats['fungicides']}")
    print(f"Herbicides (HE): {stats['herbicides']}")
    print(f"Manufacturers: {stats['manufacturers']}")
    
    # Check data quality
    print(f"\n🔍 DATA QUALITY ANALYSIS:")
    
    missing_fields = []
    products_with_variants = 0
    total_variants = 0
    
    for product_key, product_data in db.items():
        # Check required fields
        required_fields = ['type', 'display_name', 'manufacturer', 'active_ingredient']
        for field in required_fields:
            if not product_data.get(field):
                missing_fields.append(f"{product_key}: missing {field}")
        
        # Count variants
        variants = product_data.get('variants', [])
        if variants:
            products_with_variants += 1
            total_variants += len(variants)
    
    print(f"Products with variants: {products_with_variants}/{len(db)} ({products_with_variants/len(db)*100:.1f}%)")
    print(f"Average variants per product: {total_variants/len(db):.1f}")
    
    if missing_fields:
        print(f"\n⚠️  MISSING FIELDS ({len(missing_fields)} issues):")
        for issue in missing_fields[:10]:  # Show first 10
            print(f"  - {issue}")
        if len(missing_fields) > 10:
            print(f"  ... and {len(missing_fields) - 10} more")
    else:
        print("✅ All products have required fields")
    
    # Test search index building
    print(f"\n🔍 SEARCH INDEX ANALYSIS:")
    print(f"Total search terms: {len(validator.search_index)}")
    print(f"Manufacturer index entries: {len(validator.manufacturer_index)}")
    print(f"Type index entries: {len(validator.type_index)}")

def main():
    """Run all tests"""
    try:
        print("🧪 STARTING COMPREHENSIVE SMART PRODUCT VALIDATOR TESTING")
        print("This will identify issues with false positive matches for farmers")
        
        # Run edge case tests
        failed_tests = test_edge_cases()
        
        # Run confidence scoring tests
        test_confidence_scoring_accuracy()
        
        # Analyze database quality
        analyze_database_quality()
        
        print("\n" + "="*60)
        print("🏁 TESTING COMPLETE")
        print("="*60)
        
        if failed_tests:
            print(f"❌ CRITICAL ISSUES FOUND: {len(failed_tests)} problematic matches")
            print("The system is giving false positives that will mislead farmers!")
            print("Immediate fixes needed in confidence thresholds and matching logic.")
        else:
            print("✅ All tests passed - system appears robust against false positives")
        
        return len(failed_tests) == 0
        
    except Exception as e:
        print(f"❌ Test execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)