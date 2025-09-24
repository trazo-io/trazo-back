#!/usr/bin/env python3
"""
STANDALONE SMART PRODUCT VALIDATOR TESTING
Test the validation system without Django dependencies
"""

import sys
import os
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Duplicate SmartProductMatch and SmartProductValidator for standalone testing
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

class StandaloneSmartProductValidator:
    """Standalone version for testing without Django"""
    
    # Copy the exact database from the Django version
    SMART_PRODUCT_DATABASE = {
        # FERTILIZERS (FE) - 10 most common
        "miracle-gro": {
            "type": "FE",
            "display_name": "Miracle-Gro All Purpose",
            "variants": [
                "miracle-gro all purpose plant food",
                "miracle-gro potting mix",
                "miracle-gro lawn fertilizer", 
                "miracle gro",
                "miracle grow",
                "miracle-gro water soluble"
            ],
            "npk": "24-8-16",
            "manufacturer": "Scotts",
            "active_ingredient": "N-P-K Fertilizer",
            "application_rate": "1 tablespoon per gallon of water",
            "common_mistakes": ["FU", "PE"],
            "educational_tips": [
                "High nitrogen content promotes leafy growth",
                "Best applied during growing season every 2 weeks",
                "Water well after application to activate nutrients"
            ]
        },
        "urea": {
            "type": "FE",
            "display_name": "Urea Fertilizer",
            "variants": ["urea fertilizer", "46-0-0", "carbamide", "nitrogen fertilizer"],
            "npk": "46-0-0", 
            "manufacturer": "Various",
            "active_ingredient": "Urea (Nitrogen)",
            "application_rate": "1-2 pounds per 1000 sq ft",
            "common_mistakes": [],
            "educational_tips": [
                "Pure nitrogen source - highest N content available",
                "Requires soil moisture for conversion to plant-available form",
                "Best for quick green-up and growth boost"
            ]
        },
        "10-10-10": {
            "type": "FE",
            "display_name": "Balanced Fertilizer",
            "variants": ["balanced fertilizer", "triple 10", "all purpose fertilizer"],
            "npk": "10-10-10",
            "manufacturer": "Various",
            "active_ingredient": "Balanced N-P-K",
            "application_rate": "2-4 lbs per 100 sq ft",
            "common_mistakes": [],
            "educational_tips": [
                "Equal nutrients good for general feeding",
                "Safe starter fertilizer for most crops",
                "Lower analysis means gentler on plants"
            ]
        },
        
        # HERBICIDES (HE) - 3 most common
        "roundup": {
            "type": "HE",
            "display_name": "Roundup WeatherMAX",
            "variants": [
                "roundup ready-to-use",
                "roundup concentrate",
                "roundup weed killer", 
                "glyphosate",
                "round up",
                "roundup weathermax"
            ],
            "manufacturer": "Bayer",
            "active_ingredient": "Glyphosate",
            "application_rate": "1-2 fl oz per gallon water", 
            "common_mistakes": ["PE", "FU"],
            "educational_tips": [
                "Non-selective - kills all plants it contacts",
                "Systemic action - moves through entire plant",
                "Best results on actively growing weeds"
            ]
        },
        "2-4-d": {
            "type": "HE",
            "display_name": "2,4-D Broadleaf Herbicide",
            "variants": ["2,4-d", "broadleaf herbicide", "weed-b-gon", "2-4-d amine"],
            "manufacturer": "Various",
            "active_ingredient": "2,4-Dichlorophenoxyacetic acid",
            "application_rate": "1-3 fl oz per gallon water",
            "common_mistakes": ["PE"],
            "educational_tips": [
                "Selective - kills broadleaf weeds, spares grasses",
                "Hormone-type herbicide disrupts plant growth",
                "Temperature sensitive - avoid hot weather application"
            ]
        },
        
        # PESTICIDES (PE) - 2 most common
        "sevin": {
            "type": "PE",
            "display_name": "Sevin (Carbaryl)",
            "variants": ["sevin", "carbamate insecticide", "carbaryl dust"],
            "manufacturer": "Bayer",
            "active_ingredient": "Carbaryl",
            "application_rate": "2-4 tablespoons per gallon water", 
            "common_mistakes": ["FU"],
            "educational_tips": [
                "Carbamate insecticide effective on many pests",
                "Available as dust, liquid, or granules",
                "Broad spectrum but hard on beneficial insects"
            ]
        },
        "bt": {
            "type": "PE",
            "display_name": "Bt (Bacillus thuringiensis)",
            "variants": ["bacillus thuringiensis", "organic insecticide", "dipel", "bt spray"],
            "manufacturer": "Various",
            "active_ingredient": "Bacillus thuringiensis",
            "application_rate": "1-2 teaspoons per gallon water", 
            "common_mistakes": ["FU", "FE"],
            "educational_tips": [
                "Organic bacterial insecticide for caterpillars",
                "Must be eaten by pest to be effective",
                "Safe for beneficial insects and mammals"
            ]
        },
        
        # FUNGICIDES (FU) - 2 most common
        "copper-sulfate": {
            "type": "FU",
            "display_name": "Copper Sulfate Fungicide",
            "variants": [
                "bordeaux mixture", 
                "copper fungicide",
                "organic fungicide",
                "copper sulphate",
                "bluestone",
                "copper sulfate pentahydrate"
            ],
            "manufacturer": "Various",
            "active_ingredient": "Copper sulfate",
            "application_rate": "1-3 tablespoons per gallon water", 
            "common_mistakes": ["FE", "PE"],
            "educational_tips": [
                "Organic-approved fungicide and bactericide",
                "Preventive treatment - apply before disease appears",
                "Can cause phytotoxicity if overused"
            ]
        },
        "neem-oil": {
            "type": "FU",
            "display_name": "Neem Oil Fungicide",
            "variants": [
                "organic fungicide",
                "neem extract", 
                "horticultural oil",
                "organic neem",
                "neem oil concentrate"
            ],
            "manufacturer": "Various",
            "active_ingredient": "Azadirachtin",
            "application_rate": "2-4 tablespoons per gallon water",
            "common_mistakes": ["PE", "FE"],
            "educational_tips": [
                "Organic oil with fungicidal and insecticidal properties",
                "Works by disrupting pest life cycles", 
                "Also helps with powdery mildew and rust"
            ]
        }
    }
    
    def __init__(self):
        """Initialize the enhanced validator with preprocessed product index"""
        self._build_enhanced_search_index()
    
    def _build_enhanced_search_index(self):
        """Build comprehensive search index for fast product lookup"""
        self.search_index = {}
        self.manufacturer_index = {}
        self.type_index = {}
        
        for product_key, product_data in self.SMART_PRODUCT_DATABASE.items():
            # Add main product name
            normalized = self._normalize_name(product_key)
            self.search_index[normalized] = product_key
            
            # Add display name
            display_normalized = self._normalize_name(product_data.get("display_name", ""))
            if display_normalized:
                self.search_index[display_normalized] = product_key
            
            # Add all variants
            for variant in product_data.get("variants", []):
                normalized_variant = self._normalize_name(variant)
                self.search_index[normalized_variant] = product_key
            
            # Build manufacturer index
            manufacturer = product_data.get("manufacturer", "").lower()
            if manufacturer and manufacturer != "various":
                if manufacturer not in self.manufacturer_index:
                    self.manufacturer_index[manufacturer] = []
                self.manufacturer_index[manufacturer].append(product_key)
            
            # Build type index
            product_type = product_data.get("type")
            if product_type not in self.type_index:
                self.type_index[product_type] = []
            self.type_index[product_type].append(product_key)
    
    def _normalize_name(self, name: str) -> str:
        """Enhanced normalization for better matching"""
        if not name:
            return ""
        
        # Convert to lowercase, remove special chars, normalize spaces
        normalized = re.sub(r'[^\w\s-]', ' ', name.lower())
        normalized = re.sub(r'[-_\s]+', ' ', normalized)
        normalized = normalized.strip()
        
        # Handle common abbreviations and variations
        abbreviations = {
            'fert': 'fertilizer',
            'herb': 'herbicide',
            'pest': 'pesticide', 
            'insect': 'insecticide',
            'fung': 'fungicide',
            'org': 'organic',
            'conc': 'concentrate'
        }
        
        for abbrev, full in abbreviations.items():
            normalized = re.sub(r'\b' + abbrev + r'\b', full, normalized)
        
        return normalized
    
    def _contains_agricultural_terms(self, query: str) -> bool:
        """Check if query contains agricultural terms to validate relevance"""
        agricultural_terms = {
            # Product types
            'fertilizer', 'fert', 'herbicide', 'herb', 'pesticide', 'pest', 
            'insecticide', 'insect', 'fungicide', 'fung', 'chemical',
            
            # Common brands/products
            'miracle', 'roundup', 'urea', 'nitrogen', 'phosphorus', 'potassium',
            'organic', 'spray', 'granular', 'liquid', 'powder', 'concentrate',
            
            # NPK and nutrients
            'npk', '10-10-10', '46-0-0', '24-8-16', '15-9-12', '0-46-0', '0-0-60',
            
            # Agricultural context
            'crop', 'plant', 'garden', 'lawn', 'farm', 'agriculture', 'agri',
            'weed', 'bug', 'insect', 'disease', 'growth', 'feed', 'food'
        }
        
        query_words = set(query.lower().split())
        return bool(agricultural_terms & query_words)
    
    def smart_product_search(self, query: str, max_suggestions: int = 8) -> List[Dict]:
        """Intelligent product search with ranking and educational context"""
        if not query or len(query.strip()) < 3:
            return []
        
        normalized_query = self._normalize_name(query)
        suggestions = []
        query_words = set(normalized_query.split())
        
        # SECURITY: Validate query contains agricultural terms for meaningful matches
        if not self._contains_agricultural_terms(normalized_query):
            strict_threshold = 0.8  # Much higher threshold for non-agricultural
        else:
            strict_threshold = 0.4  # Standard threshold for agricultural terms
        
        # Score and rank all products
        product_scores = []
        
        for indexed_name, product_key in self.search_index.items():
            score = self._calculate_match_score(normalized_query, query_words, indexed_name, product_key)
            if score > strict_threshold:
                product_scores.append((product_key, score, indexed_name))
        
        # Sort by score and remove duplicates
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
                    "manufacturer": product_data.get("manufacturer", "Various"),
                    "npk": product_data.get("npk"),
                    "active_ingredient": product_data.get("active_ingredient"),
                    "application_rate": product_data.get("application_rate"),
                    "confidence": min(score * 0.9, 0.95) if score < 0.7 else min(score, 0.98),
                    "matched_text": matched_name,
                    "why_matched": self._explain_match(query, matched_name, score),
                    "educational_tip": product_data.get("educational_tips", [None])[0]
                }
                suggestions.append(suggestion)
                seen_products.add(product_key)
        
        return suggestions
    
    def _calculate_match_score(self, query: str, query_words: set, indexed_name: str, product_key: str) -> float:
        """Calculate match score with multiple factors - ENHANCED SECURITY"""
        product_data = self.SMART_PRODUCT_DATABASE[product_key]
        score = 0.0
        
        # SECURITY: Prevent scoring for very short queries
        if len(query) < 3:
            return 0.0
        
        # Exact match (highest priority)
        if query == indexed_name:
            score += 1.0
        
        # Word overlap scoring - ENHANCED
        indexed_words = set(indexed_name.split())
        if indexed_words:
            overlap = len(query_words & indexed_words)
            
            # FIXED: Require substantial overlap for scoring
            if len(query_words) == 1 and len(indexed_words) > 2:
                # Single word queries need exact word match, not partial
                if overlap > 0 and list(query_words)[0] in indexed_words:
                    word_score = 0.6  # Lower score for single word matches
                else:
                    word_score = 0.0
            else:
                word_score = overlap / len(indexed_words)
            
            score += word_score * 0.7  # Reduced from 0.8
            
            # Boost for key product terms
            key_terms = {"fertilizer", "herbicide", "pesticide", "insecticide", "fungicide"}
            if any(term in indexed_name for term in key_terms):
                score += 0.1
        
        # FIXED: Substring matching - much more restrictive
        if len(query) >= 4:  # Only for queries 4+ characters
            if query in indexed_name:
                score += 0.25  # Reduced from 0.3
            elif indexed_name in query and len(indexed_name) >= 4:
                score += 0.2
        
        # Manufacturer bonus
        manufacturer = product_data.get("manufacturer", "").lower()
        if manufacturer != "various" and len(manufacturer) > 3 and manufacturer in query:
            score += 0.2
        
        # Popular product bonus (but only for substantial matches)
        popular_products = {"miracle-gro", "roundup", "sevin"}
        if product_key in popular_products and score > 0.3:
            score += 0.1
        
        # NPK pattern matching for fertilizers
        if product_data["type"] == "FE" and re.search(r'\d+-\d+-\d+', query):
            npk = product_data.get("npk", "")
            if npk and npk in query.replace(" ", ""):
                score += 0.4
        
        return min(score, 1.0)  # Cap at 1.0
    
    def _explain_match(self, query: str, matched_name: str, score: float) -> str:
        """Provide explanation for why product was matched"""
        if score >= 0.9:
            return "Exact match"
        elif score >= 0.7:
            return f"Strong match with '{matched_name}'"
        elif score >= 0.5:
            return f"Good match - similar to '{matched_name}'"
        else:
            return f"Partial match - contains '{query}'"
    
    def validate_smart_product(self, commercial_name: str, user_selected_type: str, confidence_threshold: float = 0.7) -> SmartProductMatch:
        """Enhanced product validation with educational features"""
        if not commercial_name or not commercial_name.strip():
            return SmartProductMatch(
                commercial_name=commercial_name or "",
                correct_type=user_selected_type,
                confidence=0.0,
                warnings=["No product name provided - using selected type"],
                educational_tips=["Enter a product name for better accuracy and recommendations"]
            )
        
        # Find best product match
        normalized_input = self._normalize_name(commercial_name)
        best_match = self._find_enhanced_match(normalized_input)
        
        if not best_match:
            return SmartProductMatch(
                commercial_name=commercial_name,
                correct_type=user_selected_type, 
                confidence=0.3,
                warnings=[
                    f"Product '{commercial_name}' not in database",
                    "Using your selected type - please verify accuracy"
                ],
                educational_tips=[
                    "Check product label for exact name and active ingredients",
                    "Consider using a more specific product name"
                ]
            )
        
        product_key, confidence = best_match
        product_data = self.SMART_PRODUCT_DATABASE[product_key]
        correct_type = product_data["type"]
        
        # Build comprehensive match result
        warnings = []
        educational_tips = list(product_data.get("educational_tips", []))
        
        # Check for type mismatch with enhanced messaging
        if correct_type != user_selected_type:
            if user_selected_type in product_data.get("common_mistakes", []):
                warnings.append(
                    f"⚠️  COMMON MISTAKE: '{commercial_name}' is a {self._type_name(correct_type)}, "
                    f"not a {self._type_name(user_selected_type)}. This is a frequent confusion!"
                )
            else:
                warnings.append(
                    f"TYPE MISMATCH: '{commercial_name}' should be {self._type_name(correct_type)}, "
                    f"not {self._type_name(user_selected_type)}"
                )
        
        # Add product-specific information
        if correct_type == "FE" and product_data.get("npk"):
            warnings.append(f"ℹ️  NPK Ratio: {product_data['npk']}")
        
        if product_data.get("active_ingredient"):
            warnings.append(f"ℹ️  Active Ingredient: {product_data['active_ingredient']}")
        
        return SmartProductMatch(
            commercial_name=commercial_name,
            correct_type=correct_type,
            npk_ratio=product_data.get("npk"),
            confidence=confidence,
            warnings=warnings,
            educational_tips=educational_tips,
            manufacturer=product_data.get("manufacturer"),
            active_ingredient=product_data.get("active_ingredient"),
            application_rate=product_data.get("application_rate")
        )
    
    def _find_enhanced_match(self, normalized_input: str) -> Optional[Tuple[str, float]]:
        """Enhanced matching with fuzzy logic and context awareness"""
        # SECURITY: Block very short inputs
        if len(normalized_input.strip()) < 3:
            return None
        
        # Direct exact match first
        if normalized_input in self.search_index:
            return self.search_index[normalized_input], 1.0
        
        # Enhanced fuzzy matching with stricter thresholds
        input_words = set(normalized_input.split())
        best_match = None
        best_score = 0.0
        
        # SECURITY: Higher threshold for validation to prevent false positives
        min_threshold = 0.6 if self._contains_agricultural_terms(normalized_input) else 0.8
        
        for indexed_name, product_key in self.search_index.items():
            score = self._calculate_match_score(normalized_input, input_words, indexed_name, product_key)
            
            if score > best_score and score >= min_threshold:
                best_score = score
                best_match = product_key
        
        return (best_match, min(best_score, 0.95)) if best_match else None
    
    def _type_name(self, type_code: str) -> str:
        """Convert type code to human-readable name"""
        type_names = {
            "FE": "Fertilizer",
            "PE": "Pesticide",
            "FU": "Fungicide", 
            "HE": "Herbicide"
        }
        return type_names.get(type_code, type_code)

class ComprehensiveValidationTester:
    """Complete validation test suite without Django dependencies"""
    
    def __init__(self):
        self.validator = StandaloneSmartProductValidator()
        self.test_results = {
            'edge_cases': [],
            'valid_cases': [],
            'confidence_checks': []
        }
    
    def test_edge_cases(self):
        """Test edge cases that should NOT match agricultural products"""
        print("🔍 TESTING SMART PRODUCT VALIDATOR EDGE CASES")
        print("="*60)
        
        # Test cases that should NOT match or have very low confidence
        edge_cases = [
            "ads", "xyz", "random", "asdfgh", "qwerty", "test", "blah",
            "a", "z", "1", "9", "", " ", "car", "house", "phone",
            "fer", "pest", "herb", "fung", "!@#$%", "***", "???"
        ]
        
        failed_tests = []
        
        for i, test_input in enumerate(edge_cases, 1):
            print(f"\n[{i}/{len(edge_cases)}] Testing: '{test_input}'")
            
            # Test smart product search
            search_results = self.validator.smart_product_search(test_input, max_suggestions=3)
            
            if search_results:
                print(f"  ❌ PROBLEM: Got {len(search_results)} search results:")
                for result in search_results:
                    confidence = result.get('confidence', 0)
                    name = result.get('name', 'Unknown')
                    type_code = result.get('type_code', 'Unknown')
                    why_matched = result.get('why_matched', 'No explanation')
                    
                    print(f"    - {name} ({type_code}) - {confidence:.1%} confidence")
                    print(f"      Reason: {why_matched}")
                    
                    # Flag as failed if confidence > 15% for meaningless input
                    if confidence > 0.15:
                        failed_tests.append({
                            'input': test_input,
                            'matched_product': name,
                            'confidence': confidence,
                            'type': type_code,
                            'reason': why_matched
                        })
            else:
                print("  ✅ GOOD: No search results")
            
            # Test validation 
            validation_result = self.validator.validate_smart_product(test_input, "FE")
            
            if validation_result.confidence > 0.25:
                print(f"  ❌ VALIDATION PROBLEM: {validation_result.confidence:.1%} confidence")
                failed_tests.append({
                    'input': test_input,
                    'validation_confidence': validation_result.confidence,
                    'test_type': 'validation'
                })
            else:
                print(f"  ✅ VALIDATION OK: {validation_result.confidence:.1%} confidence")
        
        self.test_results['edge_cases'] = failed_tests
        return failed_tests
    
    def test_valid_products(self):
        """Test that known valid products still work correctly"""
        print("\n" + "="*60)
        print("🌱 TESTING VALID AGRICULTURAL PRODUCTS")
        print("="*60)
        
        valid_products = [
            {"input": "miracle-gro", "expected_type": "FE", "min_confidence": 0.80},
            {"input": "roundup", "expected_type": "HE", "min_confidence": 0.80},
            {"input": "urea", "expected_type": "FE", "min_confidence": 0.80},
            {"input": "10-10-10", "expected_type": "FE", "min_confidence": 0.80},
            {"input": "sevin", "expected_type": "PE", "min_confidence": 0.75},
            {"input": "miracle grow", "expected_type": "FE", "min_confidence": 0.60},
            {"input": "round up", "expected_type": "HE", "min_confidence": 0.60},
        ]
        
        failed_tests = []
        
        for test_case in valid_products:
            test_input = test_case["input"]
            expected_type = test_case["expected_type"] 
            min_confidence = test_case["min_confidence"]
            
            print(f"\nTesting: '{test_input}' - Expected: {expected_type}, Min confidence: {min_confidence:.0%}")
            
            # Test search
            results = self.validator.smart_product_search(test_input, max_suggestions=1)
            
            if results:
                result = results[0]
                confidence = result.get('confidence', 0)
                detected_type = result.get('type_code', '')
                name = result.get('name', 'Unknown')
                
                print(f"  Result: {name} ({detected_type}) - {confidence:.1%} confidence")
                
                # Validate results
                issues = []
                if confidence < min_confidence:
                    issues.append(f"Low confidence: {confidence:.1%} < {min_confidence:.0%}")
                
                if detected_type != expected_type:
                    issues.append(f"Wrong type: {detected_type} != {expected_type}")
                
                if issues:
                    print(f"  ❌ ISSUES: {', '.join(issues)}")
                    failed_tests.append({
                        'input': test_input,
                        'expected_type': expected_type,
                        'detected_type': detected_type,
                        'expected_confidence': min_confidence,
                        'actual_confidence': confidence,
                        'issues': issues
                    })
                else:
                    print("  ✅ VALID: Meets expectations")
            else:
                print("  ❌ CRITICAL: No results found for valid product!")
                failed_tests.append({
                    'input': test_input,
                    'expected_type': expected_type,
                    'issues': ['No results found']
                })
        
        self.test_results['valid_cases'] = failed_tests
        return failed_tests
    
    def test_confidence_thresholds(self):
        """Test confidence scoring accuracy"""
        print("\n" + "="*60)
        print("🎯 TESTING CONFIDENCE SCORING ACCURACY")
        print("="*60)
        
        # Test cases with expected confidence behavior
        test_cases = [
            ("miracle-gro", "Should have HIGH confidence (>80%)"),
            ("roundup", "Should have HIGH confidence (>80%)"),
            ("urea", "Should have HIGH confidence (>80%)"),
            ("miracle grow", "Should have MEDIUM confidence (60-80%) - typo"),
            ("round up", "Should have MEDIUM confidence (60-80%) - space"),
            ("fertilizer", "Should have MEDIUM confidence (40-60%) - generic"),
            ("miracle", "Should have LOW confidence (<40%) - partial"),
            ("ads", "Should have NO confidence (<15%) - meaningless"),
            ("xyz", "Should have NO confidence (<15%) - meaningless"),
        ]
        
        failed_tests = []
        
        for test_input, expectation in test_cases:
            print(f"\nTesting: '{test_input}' - {expectation}")
            
            results = self.validator.smart_product_search(test_input, max_suggestions=1)
            
            if results:
                confidence = results[0].get('confidence', 0)
                name = results[0].get('name', 'Unknown')
                print(f"  Result: {name} - {confidence:.1%} confidence")
                
                # Analyze if confidence makes sense
                if test_input in ['ads', 'xyz'] and confidence > 0.15:
                    print(f"  ❌ PROBLEM: Meaningless input '{test_input}' has {confidence:.1%} confidence!")
                    failed_tests.append({
                        'input': test_input,
                        'confidence': confidence,
                        'issue': f"False positive: {confidence:.1%} confidence for meaningless input"
                    })
                elif test_input in ['miracle-gro', 'roundup', 'urea'] and confidence < 0.80:
                    print(f"  ⚠️  WARNING: Exact match '{test_input}' has only {confidence:.1%} confidence")
                    failed_tests.append({
                        'input': test_input,
                        'confidence': confidence,
                        'issue': f"Low confidence for exact match: {confidence:.1%}"
                    })
                else:
                    print(f"  ✅ Confidence level seems appropriate")
            else:
                if test_input in ['ads', 'xyz']:
                    print(f"  ✅ EXCELLENT: No results for meaningless input")
                else:
                    print(f"  No results found")
        
        self.test_results['confidence_checks'] = failed_tests
        return failed_tests
    
    def generate_final_report(self):
        """Generate comprehensive test report"""
        print("\n" + "="*60)
        print("📊 COMPREHENSIVE VALIDATION REPORT")
        print("="*60)
        
        total_issues = 0
        
        # Edge cases report
        edge_issues = len(self.test_results['edge_cases'])
        total_issues += edge_issues
        
        print(f"\n🔍 EDGE CASES: {edge_issues} issues")
        if edge_issues > 0:
            print("  CRITICAL: False positives detected that could mislead farmers!")
            for issue in self.test_results['edge_cases'][:3]:
                print(f"    - '{issue['input']}' matched with {issue.get('confidence', 0):.1%} confidence")
        else:
            print("  ✅ No false positives - system properly rejects meaningless input")
        
        # Valid products report
        valid_issues = len(self.test_results['valid_cases'])
        total_issues += valid_issues
        
        print(f"\n🌱 VALID PRODUCTS: {valid_issues} issues")
        if valid_issues > 0:
            print("  WARNING: Known agricultural products not working properly!")
            for issue in self.test_results['valid_cases'][:3]:
                print(f"    - '{issue['input']}': {', '.join(issue['issues'])}")
        else:
            print("  ✅ All valid agricultural products work correctly")
        
        # Confidence checks report
        confidence_issues = len(self.test_results['confidence_checks'])
        total_issues += confidence_issues
        
        print(f"\n🎯 CONFIDENCE SCORING: {confidence_issues} issues")
        if confidence_issues > 0:
            print("  WARNING: Confidence scoring problems detected!")
            for issue in self.test_results['confidence_checks'][:3]:
                print(f"    - '{issue['input']}': {issue['issue']}")
        else:
            print("  ✅ Confidence scoring working appropriately")
        
        # Final assessment
        print(f"\n{'='*60}")
        print(f"🏁 FINAL ASSESSMENT: {total_issues} total issues found")
        print(f"{'='*60}")
        
        if total_issues == 0:
            print("✅ EXCELLENT: Smart Product validation system is working perfectly!")
            print("   - No false positives that could mislead farmers")
            print("   - All valid products detected correctly") 
            print("   - Confidence scoring is appropriate")
            print("\n   🎉 Farmers can trust this system for accurate carbon calculations!")
            
            # Test specific problematic case
            print(f"\n🎯 SPECIFIC TEST: 'ads' input validation")
            ads_results = self.validator.smart_product_search("ads", max_suggestions=1)
            if not ads_results:
                print("   ✅ PERFECT: 'ads' returns no matches - false positive fixed!")
            else:
                print(f"   ❌ PROBLEM: 'ads' still returns {ads_results[0]['confidence']:.1%} confidence")
                
        elif total_issues <= 2:
            print("⚠️  GOOD: System mostly working with minor issues")
        elif total_issues <= 5:
            print("🚨 MODERATE ISSUES: System needs attention")
        else:
            print("❌ CRITICAL ISSUES: System not ready for farmers!")
        
        return total_issues

def main():
    """Run comprehensive Smart Product validation testing"""
    print("🧪 COMPREHENSIVE SMART PRODUCT VALIDATION")
    print("Testing security fixes for false positives in agricultural product detection")
    print("Ensuring 'ads' and similar meaningless input don't match products")
    
    tester = ComprehensiveValidationTester()
    
    try:
        # Run all test suites
        tester.test_edge_cases()
        tester.test_valid_products() 
        tester.test_confidence_thresholds()
        
        # Generate final report
        total_issues = tester.generate_final_report()
        
        return total_issues == 0
        
    except Exception as e:
        print(f"❌ Test execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)