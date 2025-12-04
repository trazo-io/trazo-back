#!/usr/bin/env python3
"""
STANDALONE SMART PRODUCT VALIDATOR TESTING
Test the core matching logic without Django dependencies.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class SmartProductMatch:
    """Enhanced product match with educational features"""

    commercial_name: str
    correct_type: str  # FE/PE/FU/HE
    npk_ratio: Optional[str] = None  # For fertilizers
    confidence: float = 0.0  # 0.0-1.0
    warnings: List[str] = None
    educational_tips: List[str] = None
    manufacturer: Optional[str] = None
    active_ingredient: Optional[str] = None
    application_rate: Optional[str] = None
    best_practices: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.educational_tips is None:
            self.educational_tips = []
        if self.best_practices is None:
            self.best_practices = []


class SmartProductValidatorTest:
    """Standalone version for testing without Django"""

    # Simplified database for testing - focus on key products that could cause false matches
    SMART_PRODUCT_DATABASE = {
        "miracle-gro": {
            "type": "FE",
            "display_name": "Miracle-Gro All Purpose",
            "variants": ["miracle-gro all purpose plant food", "miracle gro", "miracle grow"],
            "npk": "24-8-16",
            "manufacturer": "Scotts",
            "active_ingredient": "N-P-K Fertilizer",
        },
        "roundup": {
            "type": "HE",
            "display_name": "Roundup WeatherMAX",
            "variants": ["roundup ready-to-use", "round up", "glyphosate"],
            "manufacturer": "Bayer",
            "active_ingredient": "Glyphosate",
        },
        "urea": {
            "type": "FE",
            "display_name": "Urea Fertilizer",
            "variants": ["urea fertilizer", "46-0-0", "nitrogen fertilizer"],
            "npk": "46-0-0",
            "manufacturer": "Various",
            "active_ingredient": "Urea (Nitrogen)",
        },
    }

    def __init__(self):
        self._build_search_index()

    def _build_search_index(self):
        """Build search index"""
        self.search_index = {}

        for product_key, product_data in self.SMART_PRODUCT_DATABASE.items():
            # Add main name
            normalized = self._normalize_name(product_key)
            self.search_index[normalized] = product_key

            # Add display name
            display_normalized = self._normalize_name(product_data.get("display_name", ""))
            if display_normalized:
                self.search_index[display_normalized] = product_key

            # Add variants
            for variant in product_data.get("variants", []):
                normalized_variant = self._normalize_name(variant)
                self.search_index[normalized_variant] = product_key

    def _normalize_name(self, name: str) -> str:
        """Normalize names for matching"""
        if not name:
            return ""

        # Convert to lowercase, remove special chars, normalize spaces
        normalized = re.sub(r"[^\w\s-]", " ", name.lower())
        normalized = re.sub(r"[-_\s]+", " ", normalized)
        normalized = normalized.strip()

        return normalized

    def _calculate_match_score(self, query: str, query_words: set, indexed_name: str, product_key: str) -> float:
        """Calculate match score - THIS IS THE CRITICAL FUNCTION"""
        product_data = self.SMART_PRODUCT_DATABASE[product_key]
        score = 0.0

        # PROBLEM: This logic is too permissive!

        # Exact match (highest priority)
        if query == indexed_name:
            score += 1.0

        # Word overlap scoring - PROBLEMATIC for short queries
        indexed_words = set(indexed_name.split())
        if indexed_words:
            overlap = len(query_words & indexed_words)
            word_score = overlap / len(indexed_words)
            score += word_score * 0.8

            # ISSUE: Single letter matches get scored!
            print(f"    DEBUG: Query '{query}' vs Indexed '{indexed_name}'")
            print(f"           Query words: {query_words}")
            print(f"           Indexed words: {indexed_words}")
            print(f"           Overlap: {overlap}, Word score: {word_score:.3f}")

        # Substring matching - VERY PROBLEMATIC
        if query in indexed_name or indexed_name in query:
            score += 0.3
            print(f"           Substring bonus: +0.3")

        print(f"           Total score: {score:.3f}")

        return min(score, 1.0)

    def smart_product_search(self, query: str, max_suggestions: int = 8) -> List[Dict]:
        """Search for products - MAIN FUNCTION TO TEST"""
        if not query or len(query.strip()) < 2:
            return []

        normalized_query = self._normalize_name(query)
        suggestions = []
        query_words = set(normalized_query.split())

        print(f"\n🔍 SEARCHING for '{query}' (normalized: '{normalized_query}')")
        print(f"Query words: {query_words}")

        # Score all products
        product_scores = []

        for indexed_name, product_key in self.search_index.items():
            score = self._calculate_match_score(normalized_query, query_words, indexed_name, product_key)

            # CRITICAL ISSUE: The threshold is too low!
            if score > 0.1:  # This is the problem - 0.1 is way too permissive
                product_scores.append((product_key, score, indexed_name))
                print(f"  → MATCHED: {product_key} (score: {score:.3f}, indexed: '{indexed_name}')")

        # Sort and format results
        product_scores.sort(key=lambda x: x[1], reverse=True)
        seen_products = set()

        for product_key, score, matched_name in product_scores:
            if product_key not in seen_products and len(suggestions) < max_suggestions:
                product_data = self.SMART_PRODUCT_DATABASE[product_key]

                suggestion = {
                    "id": product_key,
                    "name": product_data.get("display_name", product_key.replace("-", " ").title()),
                    "type": self._type_name(product_data["type"]),
                    "type_code": product_data["type"],
                    "confidence": min(score, 0.98),
                    "matched_text": matched_name,
                }
                suggestions.append(suggestion)
                seen_products.add(product_key)

        return suggestions

    def _type_name(self, type_code: str) -> str:
        """Convert type code to name"""
        type_names = {"FE": "Fertilizer", "PE": "Pesticide", "FU": "Fungicide", "HE": "Herbicide"}
        return type_names.get(type_code, type_code)


def test_problematic_cases():
    """Test the exact cases causing problems"""

    print("🚨 TESTING PROBLEMATIC CASES")
    print("=" * 60)

    validator = SmartProductValidatorTest()

    # The reported problem case
    test_cases = [
        "ads",  # The original problem
        "xyz",  # Another meaningless string
        "a",  # Single letter
        "s",  # Single letter
        "go",  # Short word
        "up",  # Short word (part of "round up")
        "gro",  # Part of "miracle-gro"
        "round",  # Part of "roundup"
    ]

    for test_input in test_cases:
        print(f"\n" + "-" * 40)
        print(f"🧪 TESTING: '{test_input}'")
        print("-" * 40)

        results = validator.smart_product_search(test_input)

        if results:
            print(f"❌ PROBLEM: Got {len(results)} results for '{test_input}':")
            for result in results:
                confidence = result.get("confidence", 0)
                name = result.get("name", "Unknown")
                type_code = result.get("type_code", "Unknown")
                matched_text = result.get("matched_text", "Unknown")

                print(f"  → {name} ({type_code})")
                print(f"    Confidence: {confidence:.1%}")
                print(f"    Matched on: '{matched_text}'")

                if confidence > 0.20:  # 20% confidence for meaningless input is BAD
                    print(f"    🚨 CRITICAL: {confidence:.1%} confidence is too high!")
        else:
            print(f"✅ GOOD: No results for '{test_input}'")


def analyze_scoring_problems():
    """Analyze the specific scoring issues"""

    print(f"\n" + "=" * 60)
    print("📊 ANALYZING SCORING ALGORITHM PROBLEMS")
    print("=" * 60)

    validator = SmartProductValidatorTest()

    # Test specific problematic scenarios
    print(f"\n1. SINGLE LETTER MATCHING:")
    print(f"   Query 'a' vs 'miracle gro all purpose plant food'")
    print(f"   Should match? NO - completely unrelated")

    # Manual test of the scoring logic
    query = "a"
    indexed_name = "miracle gro all purpose plant food"
    query_words = {"a"}
    indexed_words = {"miracle", "gro", "all", "purpose", "plant", "food"}

    overlap = len(query_words & indexed_words)
    word_score = overlap / len(indexed_words) if indexed_words else 0

    print(f"   Query words: {query_words}")
    print(f"   Indexed words: {indexed_words}")
    print(f"   Overlap: {overlap}")
    print(f"   Word score: {word_score:.3f}")
    print(f"   → This should be 0, but gets scored due to word matching logic")

    print(f"\n2. SUBSTRING MATCHING PROBLEMS:")
    print(f"   Query 'ads' contains NO agricultural terms")
    print(f"   But substring logic might match partial terms")

    print(f"\n3. THRESHOLD ANALYSIS:")
    print(f"   Current threshold: 0.1 (10%)")
    print(f"   Problem: Any tiny match gets through")
    print(f"   Recommendation: Increase to 0.4+ (40%+) for meaningful matches")


def recommend_fixes():
    """Recommend specific fixes for the validation system"""

    print(f"\n" + "=" * 60)
    print("🔧 RECOMMENDED FIXES")
    print("=" * 60)

    fixes = [
        {
            "issue": "Minimum relevance threshold too low (0.1)",
            "fix": "Increase threshold to 0.4+ for search, 0.6+ for validation",
            "code": "if score > 0.4:  # Was 0.1",
            "impact": "Eliminates most false positives",
        },
        {
            "issue": "Single/short word matches get scored",
            "fix": "Add minimum query length check (3+ characters)",
            "code": "if len(query.strip()) < 3: return []",
            "impact": "Blocks meaningless short inputs",
        },
        {
            "issue": "Substring matching too aggressive",
            "fix": "Only allow substring matches for longer queries (5+ chars)",
            "code": "if len(query) >= 5 and (query in indexed_name or indexed_name in query):",
            "impact": "Reduces false substring matches",
        },
        {
            "issue": "No confidence cap for poor matches",
            "fix": "Cap confidence at 30% for partial matches",
            "code": "confidence = min(score, 0.3 if score < 0.6 else 0.98)",
            "impact": "Prevents overconfident poor matches",
        },
        {
            "issue": "No agricultural term validation",
            "fix": "Require at least one agricultural keyword for matches",
            "code": "agricultural_terms = {'fertilizer', 'herbicide', 'pesticide', 'fungicide', ...}",
            "impact": "Ensures matches are agriculture-related",
        },
    ]

    for i, fix in enumerate(fixes, 1):
        print(f"\n{i}. {fix['issue']}")
        print(f"   Fix: {fix['fix']}")
        print(f"   Code: {fix['code']}")
        print(f"   Impact: {fix['impact']}")


def main():
    """Run the analysis"""
    print("🔍 SMART PRODUCT VALIDATOR CRITICAL ANALYSIS")
    print("Investigating why 'ads' matches 'Fertilizer (FE)' with 30% confidence")

    # Test the problematic cases
    test_problematic_cases()

    # Analyze the scoring problems
    analyze_scoring_problems()

    # Recommend fixes
    recommend_fixes()

    print(f"\n" + "=" * 60)
    print("🏁 ANALYSIS COMPLETE")
    print("=" * 60)
    print("CONCLUSION: The validation system has multiple critical flaws:")
    print("1. Threshold too low (0.1) allows meaningless matches")
    print("2. Single-letter word matching creates false positives")
    print("3. Substring matching is overly aggressive")
    print("4. No agricultural term validation")
    print("5. Confidence scoring doesn't reflect match quality")
    print("\n❌ SYSTEM IS BROKEN - Will mislead farmers with false matches!")
    print("🔧 Immediate fixes needed before production use.")


if __name__ == "__main__":
    main()
