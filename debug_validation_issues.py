#!/usr/bin/env python3
"""
DEBUG VALIDATION ISSUES
Identify specific problems with the Smart Product validation
"""

import re
from standalone_smart_product_test import StandaloneSmartProductValidator

def debug_validation_issues():
    """Debug the specific validation problems"""
    print("🔍 DEBUGGING SMART PRODUCT VALIDATION ISSUES")
    print("="*60)
    
    validator = StandaloneSmartProductValidator()
    
    # Issue 1: 30% confidence for unknown products
    print("\n📊 ISSUE 1: Unknown product confidence")
    print("-" * 40)
    
    unknown_products = ["ads", "xyz", "randomstuff"]
    
    for product in unknown_products:
        print(f"\nTesting unknown product: '{product}'")
        
        # Check search results
        search_results = validator.smart_product_search(product)
        print(f"  Search results: {len(search_results)}")
        
        # Check validation
        validation = validator.validate_smart_product(product, "FE")
        print(f"  Validation confidence: {validation.confidence:.1%}")
        print(f"  Validation type: {validation.correct_type}")
        print(f"  Warnings: {len(validation.warnings)}")
        
        # This is the key issue: validation returns 30% confidence for unknown products
        # This is actually CORRECT behavior - it's saying "I don't know this product, 
        # so I'm using your selected type with low confidence"
        
        if validation.confidence == 0.3:
            print("  ✅ EXPECTED: 30% confidence indicates unknown product using user selection")
        elif validation.confidence > 0.5:
            print("  ❌ PROBLEM: High confidence for unknown product")
        else:
            print(f"  ℹ️  UNUSUAL: {validation.confidence:.1%} confidence (not the typical 30%)")
    
    # Issue 2: "herb" and "fung" matching
    print("\n📊 ISSUE 2: Partial word matching")
    print("-" * 40)
    
    partial_words = ["herb", "fung", "pest", "fer"]
    
    for word in partial_words:
        print(f"\nTesting partial word: '{word}'")
        
        # Check search results
        search_results = validator.smart_product_search(word)
        print(f"  Search results: {len(search_results)}")
        
        for result in search_results:
            confidence = result.get('confidence', 0)
            name = result.get('name', 'Unknown')
            matched_text = result.get('matched_text', '')
            why_matched = result.get('why_matched', '')
            
            print(f"    - {name}: {confidence:.1%} confidence")
            print(f"      Matched: '{matched_text}' - {why_matched}")
            
            # Analyze why it's matching
            if word in matched_text:
                print(f"      🔍 REASON: '{word}' found in '{matched_text}'")
                
                # Check if this is agricultural term matching
                if validator._contains_agricultural_terms(word):
                    print(f"      ⚠️  '{word}' detected as agricultural term")
                else:
                    print(f"      ✅ '{word}' not detected as agricultural term")
        
        # Check validation
        validation = validator.validate_smart_product(word, "FE")
        print(f"  Validation confidence: {validation.confidence:.1%}")
        
        if validation.confidence > 0.6:
            print("  ❌ PROBLEM: High confidence for partial word")
        elif validation.confidence > 0.3:
            print("  ⚠️  WARNING: Medium confidence for partial word")
        else:
            print("  ✅ OK: Low confidence for partial word")
    
    # Issue 3: Agricultural term detection
    print("\n📊 ISSUE 3: Agricultural term detection analysis")
    print("-" * 40)
    
    test_queries = [
        "ads", "xyz", "herb", "fung", "fertilizer", "miracle-gro",
        "pesticide", "herbicide", "random", "car", "house"
    ]
    
    for query in test_queries:
        is_agricultural = validator._contains_agricultural_terms(query)
        print(f"  '{query}': {'AGRICULTURAL' if is_agricultural else 'NON-AGRICULTURAL'}")
    
    # Issue 4: Scoring algorithm analysis
    print("\n📊 ISSUE 4: Scoring algorithm deep dive")
    print("-" * 40)
    
    # Test specific problematic case: "herb" matching "2,4-D Broadleaf Herbicide"
    query = "herb"
    indexed_name = "2 4 d broadleaf herbicide" 
    product_key = "2-4-d"
    
    print(f"\nAnalyzing why '{query}' matches '{indexed_name}':")
    
    # Simulate the scoring
    query_words = set(query.split())
    indexed_words = set(indexed_name.split())
    
    print(f"  Query words: {query_words}")
    print(f"  Indexed words: {indexed_words}")
    print(f"  Overlap: {query_words & indexed_words}")
    print(f"  Overlap count: {len(query_words & indexed_words)}")
    print(f"  Overlap ratio: {len(query_words & indexed_words) / len(indexed_words) if indexed_words else 0}")
    
    # Check if "herbicide" contains "herb"
    if "herbicide" in indexed_name and query in "herbicide":
        print(f"  🔍 SUBSTRING MATCH: '{query}' is substring of 'herbicide'")
        print(f"  📝 EXPLANATION: This is why it's matching with high confidence")
    
    # The issue is that "herb" is matching "herbicide" as a substring
    # and the algorithm gives high score for this match

def propose_fixes():
    """Propose fixes for the identified issues"""
    print("\n" + "="*60)
    print("🔧 PROPOSED FIXES")
    print("="*60)
    
    print("\n1. 📊 ISSUE 1 ANALYSIS: 30% confidence for unknown products")
    print("   STATUS: ✅ THIS IS CORRECT BEHAVIOR")
    print("   EXPLANATION: 30% confidence means 'unknown product, using your selection'")
    print("   ACTION: Update test expectations - this is not a bug")
    
    print("\n2. 🔧 ISSUE 2 FIX: Prevent partial word matching")
    print("   PROBLEM: 'herb' matches 'herbicide' with 77% confidence")
    print("   SOLUTION: Implement minimum word length requirements")
    print("   CHANGE: Require 4+ characters for substring matching")
    print("   CHANGE: Require exact word boundaries for agricultural terms")
    
    print("\n3. 🔧 ISSUE 3 FIX: Improve agricultural term detection")
    print("   PROBLEM: Generic terms like 'herb', 'fung' triggering matches")
    print("   SOLUTION: Require full words, not partial matches")
    print("   CHANGE: Update agricultural terms list to full words only")
    
    print("\n4. 🎯 CONFIDENCE THRESHOLD ADJUSTMENT")
    print("   CURRENT: Non-agricultural queries use 0.8 threshold")
    print("   CURRENT: Agricultural queries use 0.4 threshold")
    print("   PROPOSAL: Increase agricultural threshold to 0.6 for partial words")
    
    print("\n5. ✅ VALIDATION BEHAVIOR CLARIFICATION")
    print("   The validation function SHOULD return 30% confidence for unknown products")
    print("   This tells farmers: 'I don't recognize this, but I'll use what you selected'")
    print("   This is SAFER than returning 0% (which might cause errors)")
    
    fix_code = '''
# PROPOSED CODE FIXES for smart_product_validator.py:

def _contains_agricultural_terms(self, query: str) -> bool:
    """Enhanced agricultural term detection - require full words only"""
    agricultural_terms = {
        # Full words only - no partial matches
        'fertilizer', 'herbicide', 'pesticide', 'insecticide', 'fungicide',
        'miracle-gro', 'roundup', 'urea', 'nitrogen', 'phosphorus', 'potassium',
        'organic', 'spray', 'granular', 'liquid', 'powder', 'concentrate',
        # Remove partial terms like 'herb', 'fung', 'pest' to prevent false matches
    }
    
    # Require exact word matches, not substrings
    query_words = set(word.lower() for word in query.split())
    return bool(agricultural_terms & query_words)

def _calculate_match_score(self, query: str, query_words: set, indexed_name: str, product_key: str) -> float:
    """Enhanced matching with stricter partial word requirements"""
    
    # CRITICAL FIX: Prevent partial word matches for short queries
    if len(query) <= 4:
        # For short queries, require exact word match only
        if query not in indexed_name.split():
            return 0.0  # No partial matches for short words
    
    # CRITICAL FIX: Substring matching only for longer, meaningful terms
    if len(query) >= 5:  # Increased from 4
        if query in indexed_name:
            score += 0.20  # Reduced from 0.25
        elif indexed_name in query and len(indexed_name) >= 5:
            score += 0.15  # Reduced from 0.20
    
    return min(score, 1.0)
'''
    
    print("\n🔧 PROPOSED CODE CHANGES:")
    print(fix_code)

def main():
    """Debug validation issues and propose fixes"""
    debug_validation_issues()
    propose_fixes()
    
    print("\n" + "="*60)
    print("🎯 SUMMARY:")
    print("✅ 30% confidence for unknown products is CORRECT behavior")
    print("🔧 Need to fix partial word matching ('herb' → 'herbicide')")
    print("🔧 Need to strengthen agricultural term detection")
    print("📝 Test expectations need updating for unknown product behavior")

if __name__ == "__main__":
    main()