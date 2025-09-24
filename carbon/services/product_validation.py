"""
AGRICULTURAL PRODUCT VALIDATION SERVICE
Validates commercial product names against chemical types for accurate carbon calculations.
Addresses the 785% emission variance caused by ignoring commercial_name field.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ProductMatch:
    """Represents a validated agricultural product"""
    commercial_name: str
    correct_type: str  # FE/PE/FU/HE
    npk_ratio: Optional[str]  # For fertilizers
    confidence: float  # 0.0-1.0
    warnings: List[str]
    manufacturer: Optional[str] = None
    active_ingredient: Optional[str] = None

class AgriculturalProductValidator:
    """
    Validates commercial product names against expected chemical types.
    
    Focus: Top 25 most common agricultural products to maximize impact
    with minimal development effort.
    """
    
    # TOP 25 AGRICULTURAL PRODUCTS DATABASE
    # Based on real farming usage patterns and product availability
    PRODUCT_DATABASE = {
        # FERTILIZERS (FE) - 10 most common
        "miracle-gro": {
            "type": "FE",
            "variants": [
                "miracle-gro all purpose plant food",
                "miracle-gro potting mix",
                "miracle-gro lawn fertilizer",
                "miracle gro",
                "miracle grow"
            ],
            "npk": "24-8-16",
            "manufacturer": "Scotts",
            "common_mistakes": ["FU", "PE"]  # Users think it's fungicide/pesticide
        },
        "urea": {
            "type": "FE",
            "variants": ["urea fertilizer", "46-0-0", "carbamide"],
            "npk": "46-0-0",
            "manufacturer": "Various",
            "common_mistakes": []
        },
        "ammonium-nitrate": {
            "type": "FE", 
            "variants": ["34-0-0", "ammonium nitrate", "nitrogen fertilizer"],
            "npk": "34-0-0",
            "manufacturer": "Various",
            "common_mistakes": []
        },
        "triple-superphosphate": {
            "type": "FE",
            "variants": ["0-46-0", "tsp fertilizer", "phosphorus fertilizer"],
            "npk": "0-46-0", 
            "manufacturer": "Various",
            "common_mistakes": []
        },
        "muriate-of-potash": {
            "type": "FE",
            "variants": ["0-0-60", "kcl", "potassium chloride"],
            "npk": "0-0-60",
            "manufacturer": "Various", 
            "common_mistakes": []
        },
        "osmocote": {
            "type": "FE",
            "variants": ["osmocote plus", "slow release fertilizer"],
            "npk": "15-9-12",
            "manufacturer": "Scotts",
            "common_mistakes": ["PE"]
        },
        "bone-meal": {
            "type": "FE",
            "variants": ["organic bone meal", "bone meal fertilizer"],
            "npk": "3-15-0",
            "manufacturer": "Various",
            "common_mistakes": []
        },
        "fish-emulsion": {
            "type": "FE", 
            "variants": ["organic fish fertilizer", "liquid fish"],
            "npk": "5-1-1",
            "manufacturer": "Various",
            "common_mistakes": []
        },
        "compost": {
            "type": "FE",
            "variants": ["organic compost", "composted manure"],
            "npk": "1-1-1",
            "manufacturer": "Various",
            "common_mistakes": []
        },
        "10-10-10": {
            "type": "FE",
            "variants": ["balanced fertilizer", "triple 10"],
            "npk": "10-10-10", 
            "manufacturer": "Various",
            "common_mistakes": []
        },
        
        # HERBICIDES (HE) - 5 most common
        "roundup": {
            "type": "HE",
            "variants": [
                "roundup ready-to-use",
                "roundup concentrate", 
                "roundup weed killer",
                "glyphosate",
                "round up"
            ],
            "active_ingredient": "Glyphosate",
            "manufacturer": "Bayer",
            "common_mistakes": ["PE", "FU"]  # Users confuse herbicide/pesticide
        },
        "2-4-d": {
            "type": "HE",
            "variants": ["2,4-d", "broadleaf herbicide", "weed-b-gon"],
            "active_ingredient": "2,4-Dichlorophenoxyacetic acid",
            "manufacturer": "Various",
            "common_mistakes": ["PE"]
        },
        "atrazine": {
            "type": "HE", 
            "variants": ["corn herbicide", "pre-emergent herbicide"],
            "active_ingredient": "Atrazine",
            "manufacturer": "Various",
            "common_mistakes": ["PE"]
        },
        "dicamba": {
            "type": "HE",
            "variants": ["drift control herbicide", "banvel"],
            "active_ingredient": "Dicamba",
            "manufacturer": "Various",
            "common_mistakes": ["PE"]
        },
        "paraquat": {
            "type": "HE",
            "variants": ["gramoxone", "contact herbicide"],
            "active_ingredient": "Paraquat dichloride", 
            "manufacturer": "Various",
            "common_mistakes": ["PE", "FU"]
        },
        
        # PESTICIDES (PE) - 5 most common
        "malathion": {
            "type": "PE",
            "variants": ["organophosphate insecticide", "broad spectrum insecticide"],
            "active_ingredient": "Malathion",
            "manufacturer": "Various", 
            "common_mistakes": ["FU"]
        },
        "carbaryl": {
            "type": "PE",
            "variants": ["sevin", "carbamate insecticide"],
            "active_ingredient": "Carbaryl",
            "manufacturer": "Bayer",
            "common_mistakes": ["FU"]
        },
        "permethrin": {
            "type": "PE",
            "variants": ["pyrethroid insecticide", "broad spectrum"],
            "active_ingredient": "Permethrin", 
            "manufacturer": "Various",
            "common_mistakes": ["HE", "FU"]
        },
        "imidacloprid": {
            "type": "PE",
            "variants": ["systemic insecticide", "neonicotinoid"],
            "active_ingredient": "Imidacloprid",
            "manufacturer": "Bayer",
            "common_mistakes": ["FU"]
        },
        "bt": {
            "type": "PE", 
            "variants": ["bacillus thuringiensis", "organic insecticide", "dipel"],
            "active_ingredient": "Bacillus thuringiensis",
            "manufacturer": "Various",
            "common_mistakes": ["FU", "FE"]
        },
        
        # FUNGICIDES (FU) - 5 most common  
        "copper-sulfate": {
            "type": "FU",
            "variants": [
                "bordeaux mixture",
                "copper fungicide",
                "organic fungicide", 
                "copper sulphate",
                "bluestone"
            ],
            "active_ingredient": "Copper sulfate",
            "manufacturer": "Various",
            "common_mistakes": ["FE", "PE"]  # Users think copper = fertilizer
        },
        "chlorothalonil": {
            "type": "FU",
            "variants": ["broad spectrum fungicide", "daconil"],
            "active_ingredient": "Chlorothalonil",
            "manufacturer": "Various", 
            "common_mistakes": ["PE"]
        },
        "mancozeb": {
            "type": "FU",
            "variants": ["contact fungicide", "preventive fungicide"],
            "active_ingredient": "Mancozeb",
            "manufacturer": "Various",
            "common_mistakes": ["PE"]
        },
        "neem-oil": {
            "type": "FU",
            "variants": [
                "organic fungicide", 
                "neem extract",
                "horticultural oil",
                "organic neem"
            ],
            "active_ingredient": "Azadirachtin",
            "manufacturer": "Various",
            "common_mistakes": ["PE", "FE"]  # Multi-purpose confusion
        },
        "sulfur": {
            "type": "FU",
            "variants": [
                "wettable sulfur",
                "organic sulfur fungicide", 
                "elemental sulfur",
                "sulfur dust"
            ],
            "active_ingredient": "Sulfur",
            "manufacturer": "Various",
            "common_mistakes": ["FE"]  # Users think sulfur = fertilizer
        }
    }
    
    def __init__(self):
        """Initialize the validator with preprocessed product index"""
        self._build_search_index()
    
    def _build_search_index(self):
        """Build search index for fast product lookup"""
        self.search_index = {}
        
        for product_key, product_data in self.PRODUCT_DATABASE.items():
            # Add main product name
            normalized = self._normalize_name(product_key)
            self.search_index[normalized] = product_key
            
            # Add all variants
            for variant in product_data.get("variants", []):
                normalized_variant = self._normalize_name(variant)
                self.search_index[normalized_variant] = product_key
    
    def _normalize_name(self, name: str) -> str:
        """Normalize product name for matching"""
        if not name:
            return ""
        
        # Convert to lowercase, remove special chars, normalize spaces
        normalized = re.sub(r'[^\w\s-]', ' ', name.lower())
        normalized = re.sub(r'[-_\s]+', ' ', normalized)
        normalized = normalized.strip()
        
        # Handle common abbreviations
        abbreviations = {
            'fert': 'fertilizer',
            'herb': 'herbicide', 
            'pest': 'pesticide',
            'fung': 'fungicide',
            'org': 'organic',
            'conc': 'concentrate',
            'rtu': 'ready to use'
        }
        
        for abbrev, full in abbreviations.items():
            normalized = normalized.replace(abbrev, full)
            
        return normalized
    
    def validate_commercial_name(
        self,
        commercial_name: str,
        user_selected_type: str,
        confidence_threshold: float = 0.7
    ) -> ProductMatch:
        """
        Validate commercial product name against user-selected chemical type.
        
        Args:
            commercial_name: Product name entered by user
            user_selected_type: Chemical type selected by user (FE/PE/FU/HE)
            confidence_threshold: Minimum confidence for suggestions
            
        Returns:
            ProductMatch with validation results and recommendations
        """
        if not commercial_name or not commercial_name.strip():
            return ProductMatch(
                commercial_name=commercial_name or "",
                correct_type=user_selected_type,
                npk_ratio=None,
                confidence=0.0,
                warnings=["Commercial name is empty - using user-selected type"]
            )
        
        # Find best product match
        normalized_input = self._normalize_name(commercial_name)
        best_match = self._find_best_match(normalized_input)
        
        if not best_match:
            return ProductMatch(
                commercial_name=commercial_name,
                correct_type=user_selected_type,
                npk_ratio=None,
                confidence=0.3,
                warnings=[
                    f"Product '{commercial_name}' not found in database",
                    "Using user-selected type - verify accuracy"
                ]
            )
        
        product_key, confidence = best_match
        product_data = self.PRODUCT_DATABASE[product_key]
        correct_type = product_data["type"]
        
        # Check for type mismatch
        warnings = []
        if correct_type != user_selected_type:
            if user_selected_type in product_data.get("common_mistakes", []):
                warnings.append(
                    f"⚠️  COMMON MISTAKE: '{commercial_name}' is a {self._type_name(correct_type)}, "
                    f"not {self._type_name(user_selected_type)}"
                )
            else:
                warnings.append(
                    f"TYPE MISMATCH: '{commercial_name}' should be {self._type_name(correct_type)}, "
                    f"not {self._type_name(user_selected_type)}"
                )
        
        # Add NPK information for fertilizers
        npk_ratio = None
        if correct_type == "FE":
            npk_ratio = product_data.get("npk")
            if npk_ratio:
                warnings.append(f"ℹ️  NPK Ratio: {npk_ratio}")
        
        # Add active ingredient info for pesticides/herbicides/fungicides
        if product_data.get("active_ingredient"):
            warnings.append(f"ℹ️  Active Ingredient: {product_data['active_ingredient']}")
        
        return ProductMatch(
            commercial_name=commercial_name,
            correct_type=correct_type,
            npk_ratio=npk_ratio,
            confidence=confidence,
            warnings=warnings,
            manufacturer=product_data.get("manufacturer"),
            active_ingredient=product_data.get("active_ingredient")
        )
    
    def _find_best_match(self, normalized_input: str) -> Optional[Tuple[str, float]]:
        """Find best matching product from search index"""
        # Exact match
        if normalized_input in self.search_index:
            return self.search_index[normalized_input], 1.0
        
        # Partial word matching
        input_words = set(normalized_input.split())
        best_match = None
        best_score = 0.0
        
        for indexed_name, product_key in self.search_index.items():
            indexed_words = set(indexed_name.split())
            
            # Calculate word overlap score
            if not indexed_words:
                continue
                
            overlap = len(input_words & indexed_words)
            score = overlap / len(indexed_words)  # Favor shorter, more specific matches
            
            # Boost score for key terms
            if any(word in indexed_name for word in ["fertilizer", "herbicide", "pesticide", "fungicide"]):
                score += 0.1
            
            if score > best_score and score >= 0.5:  # Minimum 50% word overlap
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
    
    def get_product_suggestions(self, partial_name: str, max_suggestions: int = 5) -> List[Dict]:
        """Get product suggestions for autocomplete"""
        if not partial_name or len(partial_name) < 2:
            return []
        
        normalized_input = self._normalize_name(partial_name)
        suggestions = []
        
        for indexed_name, product_key in self.search_index.items():
            if normalized_input in indexed_name:
                product_data = self.PRODUCT_DATABASE[product_key]
                suggestions.append({
                    "name": product_key.replace("-", " ").title(),
                    "type": self._type_name(product_data["type"]),
                    "type_code": product_data["type"],
                    "manufacturer": product_data.get("manufacturer"),
                    "npk": product_data.get("npk")
                })
        
        # Remove duplicates and limit results
        seen = set()
        unique_suggestions = []
        for suggestion in suggestions:
            key = (suggestion["name"], suggestion["type_code"])
            if key not in seen:
                seen.add(key)
                unique_suggestions.append(suggestion)
                if len(unique_suggestions) >= max_suggestions:
                    break
        
        return unique_suggestions
    
    def get_validation_stats(self) -> Dict:
        """Get validation statistics for monitoring"""
        total_products = len(self.PRODUCT_DATABASE)
        type_counts = {"FE": 0, "PE": 0, "FU": 0, "HE": 0}
        
        for product_data in self.PRODUCT_DATABASE.values():
            type_counts[product_data["type"]] += 1
        
        return {
            "total_products": total_products,
            "fertilizers": type_counts["FE"],
            "pesticides": type_counts["PE"], 
            "fungicides": type_counts["FU"],
            "herbicides": type_counts["HE"],
            "coverage": "Top 25 most common agricultural products"
        }

# Singleton instance
product_validator = AgriculturalProductValidator()