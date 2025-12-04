"""
SMART PRODUCT VALIDATOR SERVICE
Enhanced agricultural product validation with intelligent recognition and NPK auto-fill.
Implements the "Smart Bag" UX approach for optimal farmer experience.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


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


class SmartProductValidator:
    """
    Enhanced agricultural product validator with educational features.

    Implements the "Smart Bag" UX approach:
    1. START with what farmer has (product container)
    2. RECOGNIZE product automatically (search/name matching)
    3. AUTO-FILL technical details (NPK, type, rates)
    4. FOCUS farmer input on application specifics (area, method, date)
    5. VALIDATE gently with educational warnings
    6. LEARN from farmer corrections to improve suggestions
    """

    # ENHANCED TOP 25 AGRICULTURAL PRODUCTS DATABASE
    # Based on real farming usage patterns and Trazo farmer personas
    SMART_PRODUCT_DATABASE = {
        # FERTILIZERS (FE) - Critical US products added
        "anhydrous-ammonia": {
            "type": "FE",
            "display_name": "Anhydrous Ammonia",
            "variants": [
                "anhydrous ammonia",
                "82-0-0",
                "liquid nitrogen",
                "NH3",
                "ammonia",
                "anhydrous",
                "liquid ammonia",
            ],
            "npk": "82-0-0",
            "manufacturer": "CF Industries, Nutrien, Yara",
            "active_ingredient": "Anhydrous Ammonia (NH3)",
            "application_rate": "100-200 lbs N per acre (150-300 L/Ha)",
            "common_mistakes": [],
            "educational_tips": [
                "Highest nitrogen concentration available (82%)",
                "Most cost-effective nitrogen source for large operations",
                "Requires specialized injection equipment",
                "Best for pre-plant or sidedress applications",
            ],
            "best_practices": [
                "Inject 6-8 inches deep for retention",
                "Require adequate soil moisture for conversion",
                "Use only certified equipment and safety gear",
                "Apply when soil temperature is below 50°F for best retention",
            ],
        },
        "uan-28": {
            "type": "FE",
            "display_name": "UAN Solution 28%",
            "variants": ["uan 28", "28-0-0", "liquid nitrogen", "urea ammonium nitrate", "nitrogen solution"],
            "npk": "28-0-0",
            "manufacturer": "CF Industries, Nutrien, Koch",
            "active_ingredient": "Urea Ammonium Nitrate Solution",
            "application_rate": "25-40 gallons per acre",
            "common_mistakes": [],
            "educational_tips": [
                "Liquid nitrogen - easy to handle and apply",
                "Contains both quick and slow-release nitrogen",
                "Compatible with most application equipment",
            ],
            "best_practices": [
                "Apply with adequate water for foliar applications",
                "Avoid application during hot, humid conditions",
                "Store in corrosion-resistant tanks",
            ],
        },
        "dap": {
            "type": "FE",
            "display_name": "DAP Fertilizer",
            "variants": ["dap", "18-46-0", "diammonium phosphate", "phosphorus fertilizer"],
            "npk": "18-46-0",
            "manufacturer": "Mosaic, Nutrien, OCP",
            "active_ingredient": "Diammonium Phosphate",
            "application_rate": "100-200 lbs per acre",
            "common_mistakes": [],
            "educational_tips": [
                "High phosphorus for root development and early growth",
                "Excellent starter fertilizer for corn and soybeans",
                "Provides both nitrogen and phosphorus",
            ],
            "best_practices": [
                "Apply at planting for maximum benefit",
                "Ideal for cold soils where phosphorus is less available",
                "Avoid direct seed contact in high rates",
            ],
        },
        "map": {
            "type": "FE",
            "display_name": "MAP Fertilizer",
            "variants": ["map", "11-52-0", "monoammonium phosphate", "starter fertilizer"],
            "npk": "11-52-0",
            "manufacturer": "Mosaic, Nutrien, ICL",
            "active_ingredient": "Monoammonium Phosphate",
            "application_rate": "50-150 lbs per acre",
            "common_mistakes": [],
            "educational_tips": [
                "Highest phosphorus concentration available",
                "Acidifies soil slightly - good for alkaline soils",
                "Excellent seed-safe starter fertilizer",
            ],
            "best_practices": [
                "Safe for direct seed contact",
                "Ideal for corn, wheat, and soybean planting",
                "Works well in no-till systems",
            ],
        },
        "miracle-gro": {
            "type": "FE",
            "display_name": "Miracle-Gro All Purpose",
            "variants": [
                "miracle-gro all purpose plant food",
                "miracle-gro potting mix",
                "miracle-gro lawn fertilizer",
                "miracle gro",
                "miracle grow",
                "miracle-gro water soluble",
            ],
            "npk": "24-8-16",
            "manufacturer": "Scotts",
            "active_ingredient": "N-P-K Fertilizer",
            "application_rate": "1 tablespoon per gallon of water",
            "common_mistakes": ["FU", "PE"],  # Users think it's fungicide/pesticide
            "educational_tips": [
                "High nitrogen content promotes leafy growth",
                "Best applied during growing season every 2 weeks",
                "Water well after application to activate nutrients",
            ],
            "best_practices": [
                "Apply in morning or evening to avoid leaf burn",
                "Don't apply to wet foliage",
                "Store in cool, dry place away from moisture",
            ],
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
                "Best for quick green-up and growth boost",
            ],
            "best_practices": [
                "Apply before rain or irrigate immediately after",
                "Avoid application during drought conditions",
                "Split applications prevent burning",
            ],
        },
        "ammonium-nitrate": {
            "type": "FE",
            "display_name": "Ammonium Nitrate",
            "variants": ["34-0-0", "ammonium nitrate", "nitrogen fertilizer", "AN"],
            "npk": "34-0-0",
            "manufacturer": "Various",
            "active_ingredient": "Ammonium Nitrate",
            "application_rate": "100-200 lbs per acre",
            "common_mistakes": [],
            "educational_tips": [
                "Fast-acting nitrogen source",
                "Works well in cool weather",
                "Acidifies soil over time",
            ],
            "best_practices": [
                "Handle with care - explosive when mixed with fuel",
                "Store in dry, secure location",
                "Monitor soil pH with regular use",
            ],
        },
        "triple-superphosphate": {
            "type": "FE",
            "display_name": "Triple Superphosphate",
            "variants": ["0-46-0", "tsp fertilizer", "phosphorus fertilizer", "TSP"],
            "npk": "0-46-0",
            "manufacturer": "Various",
            "active_ingredient": "Phosphorus Pentoxide",
            "application_rate": "50-100 lbs per acre",
            "common_mistakes": [],
            "educational_tips": [
                "High phosphorus for root development",
                "Essential for flowering and fruiting",
                "Works slowly - apply before planting",
            ],
            "best_practices": [
                "Incorporate into soil 4-6 inches deep",
                "Best applied in fall or early spring",
                "Avoid surface application in high-erosion areas",
            ],
        },
        "muriate-of-potash": {
            "type": "FE",
            "display_name": "Muriate of Potash",
            "variants": ["0-0-60", "kcl", "potassium chloride", "MOP"],
            "npk": "0-0-60",
            "manufacturer": "Various",
            "active_ingredient": "Potassium Chloride",
            "application_rate": "100-200 lbs per acre",
            "common_mistakes": [],
            "educational_tips": [
                "High potassium for disease resistance",
                "Improves fruit quality and winter hardiness",
                "Salt index - use carefully on sensitive crops",
            ],
            "best_practices": [
                "Apply well before planting on salt-sensitive crops",
                "Incorporate into soil to prevent surface crusting",
                "Monitor chloride levels in soil tests",
            ],
        },
        "osmocote": {
            "type": "FE",
            "display_name": "Osmocote Plus",
            "variants": ["osmocote plus", "slow release fertilizer", "controlled release"],
            "npk": "15-9-12",
            "manufacturer": "Scotts",
            "active_ingredient": "Coated Fertilizer",
            "application_rate": "1-2 tablespoons per plant",
            "common_mistakes": ["PE"],
            "educational_tips": [
                "Temperature-controlled release lasts 3-4 months",
                "Prevents over-fertilization and burning",
                "Includes micronutrients for complete nutrition",
            ],
            "best_practices": [
                "Mix into potting soil or apply to soil surface",
                "One application per season typically sufficient",
                "Store in original container to preserve coating",
            ],
        },
        "bone-meal": {
            "type": "FE",
            "display_name": "Bone Meal Fertilizer",
            "variants": ["organic bone meal", "bone meal fertilizer", "steamed bone meal"],
            "npk": "3-15-0",
            "manufacturer": "Various",
            "active_ingredient": "Processed Animal Bones",
            "application_rate": "5-10 lbs per 100 sq ft",
            "common_mistakes": [],
            "educational_tips": [
                "Organic slow-release phosphorus source",
                "Ideal for bulbs and flowering plants",
                "Works best in acidic to neutral soils",
            ],
            "best_practices": [
                "Apply in fall for spring benefit",
                "Work into soil - don't leave on surface",
                "Safe around pets when incorporated",
            ],
        },
        "fish-emulsion": {
            "type": "FE",
            "display_name": "Fish Emulsion Fertilizer",
            "variants": ["organic fish fertilizer", "liquid fish", "fish fertilizer"],
            "npk": "5-1-1",
            "manufacturer": "Various",
            "active_ingredient": "Processed Fish",
            "application_rate": "1-2 tablespoons per gallon water",
            "common_mistakes": [],
            "educational_tips": [
                "Organic liquid fertilizer with micronutrients",
                "Quick-acting but gentle on plants",
                "Excellent for seedlings and transplants",
            ],
            "best_practices": [
                "Dilute according to label - too strong burns plants",
                "Apply in evening to reduce odor issues",
                "Rinse equipment thoroughly after use",
            ],
        },
        "compost": {
            "type": "FE",
            "display_name": "Compost",
            "variants": ["organic compost", "composted manure", "garden compost"],
            "npk": "1-1-1",
            "manufacturer": "Various",
            "active_ingredient": "Organic Matter",
            "application_rate": "2-4 inches layer",
            "common_mistakes": [],
            "educational_tips": [
                "Improves soil structure and water retention",
                "Feeds beneficial microorganisms",
                "Slow nutrient release over entire season",
            ],
            "best_practices": [
                "Apply 2-4 inch layer, work into top 6 inches",
                "Use only fully composted material to avoid burning",
                "Best applied in spring or fall",
            ],
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
                "Lower analysis means gentler on plants",
            ],
            "best_practices": [
                "Apply every 6-8 weeks during growing season",
                "Water in thoroughly after application",
                "Good choice for new gardeners",
            ],
        },
        # HERBICIDES (HE) - 5 most common
        "roundup": {
            "type": "HE",
            "display_name": "Roundup WeatherMAX",
            "variants": [
                "roundup ready-to-use",
                "roundup concentrate",
                "roundup weed killer",
                "glyphosate",
                "round up",
                "roundup weathermax",
            ],
            "manufacturer": "Bayer",
            "active_ingredient": "Glyphosate",
            "application_rate": "1-2 fl oz per gallon water",
            "common_mistakes": ["PE", "FU"],  # Users confuse herbicide/pesticide
            "educational_tips": [
                "Non-selective - kills all plants it contacts",
                "Systemic action - moves through entire plant",
                "Best results on actively growing weeds",
            ],
            "best_practices": [
                "Apply on calm, sunny days for best results",
                "Use shield or foam applicator near desirable plants",
                "Wait 7 days before replanting treated areas",
            ],
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
                "Temperature sensitive - avoid hot weather application",
            ],
            "best_practices": [
                "Apply when temperature below 85°F",
                "Avoid drift to sensitive plants like tomatoes",
                "Don't mow for 2 days before or after application",
            ],
        },
        "atrazine": {
            "type": "HE",
            "display_name": "Atrazine Herbicide",
            "variants": ["corn herbicide", "pre-emergent herbicide", "atrazine 4L"],
            "manufacturer": "Various",
            "active_ingredient": "Atrazine",
            "application_rate": "1-2 pints per acre",
            "common_mistakes": ["PE"],
            "educational_tips": [
                "Pre and post-emergent control of annual weeds",
                "Restricted use pesticide - license required",
                "Primarily for corn and sorghum crops",
            ],
            "best_practices": [
                "Apply only to labeled crops",
                "Follow groundwater protection guidelines",
                "Check local restrictions before use",
            ],
        },
        "dicamba": {
            "type": "HE",
            "display_name": "Dicamba Herbicide",
            "variants": ["drift control herbicide", "banvel", "clarity", "dicamba dga"],
            "manufacturer": "Various",
            "active_ingredient": "Dicamba",
            "application_rate": "0.5-1 pint per acre",
            "common_mistakes": ["PE"],
            "educational_tips": [
                "Broadleaf herbicide with potential for volatility",
                "Restricted use - special training required",
                "Highly regulated due to off-target movement",
            ],
            "best_practices": [
                "Use only approved formulations and tank mixes",
                "Apply during specific temperature and wind conditions",
                "Maintain detailed application records",
            ],
        },
        "paraquat": {
            "type": "HE",
            "display_name": "Paraquat Concentrate",
            "variants": ["gramoxone", "contact herbicide", "paraquat dichloride"],
            "manufacturer": "Various",
            "active_ingredient": "Paraquat dichloride",
            "application_rate": "2.5-4 pints per acre",
            "common_mistakes": ["PE", "FU"],
            "educational_tips": [
                "Restricted use pesticide - license required",
                "Contact herbicide - kills only contacted tissue",
                "Extremely toxic - handle with extreme care",
            ],
            "best_practices": [
                "Use only with required safety equipment",
                "Complete EPA-required training annually",
                "Never transfer to food or beverage containers",
            ],
        },
        # HERBICIDES (HE) - Critical US products
        "roundup": {
            "type": "HE",
            "display_name": "Roundup (Glyphosate)",
            "variants": ["roundup", "glyphosate", "roundup ready", "roundup weathermax", "roundup powermax"],
            "manufacturer": "Bayer (formerly Monsanto)",
            "active_ingredient": "Glyphosate",
            "application_rate": "22-32 fl oz per acre",
            "common_mistakes": ["PE", "FU"],
            "educational_tips": [
                "Non-selective systemic herbicide",
                "Controls most grasses and broadleaf weeds",
                "Best on actively growing weeds",
                "Rainfast in 30 minutes to 6 hours",
            ],
            "best_practices": [
                "Add surfactant for better coverage",
                "Avoid drift to desirable plants",
                "Apply when weeds are 2-6 inches tall",
                "Don't apply before rain within label timeframe",
            ],
        },
        "dual-magnum": {
            "type": "HE",
            "display_name": "Dual Magnum (S-Metolachlor)",
            "variants": ["dual magnum", "s-metolachlor", "dual ii", "pre-emergence herbicide"],
            "manufacturer": "Syngenta",
            "active_ingredient": "S-Metolachlor",
            "application_rate": "1.0-2.0 pints per acre",
            "common_mistakes": ["PE"],
            "educational_tips": [
                "Pre-emergence herbicide for corn and soybeans",
                "Controls grasses and small-seeded broadleaf weeds",
                "Must be applied before weed emergence",
                "Long residual control (3-4 months)",
            ],
            "best_practices": [
                "Apply to weed-free, firm seedbed",
                "Activate with 0.5 inch rainfall or irrigation",
                "Tank mix with other herbicides for broad spectrum",
                "Observe plant-back restrictions",
            ],
        },
        # PESTICIDES (PE) - Critical US products added
        "malathion": {
            "type": "PE",
            "display_name": "Malathion Insecticide",
            "variants": ["organophosphate insecticide", "broad spectrum insecticide"],
            "manufacturer": "Various",
            "active_ingredient": "Malathion",
            "application_rate": "1-2 fl oz per gallon water",
            "common_mistakes": ["FU"],
            "educational_tips": [
                "Broad-spectrum organophosphate insecticide",
                "Controls aphids, scales, and many other pests",
                "Short residual period - frequent applications may be needed",
            ],
            "best_practices": [
                "Apply in evening to protect beneficial insects",
                "Wear protective equipment including respirator",
                "Don't apply to plants in bloom",
            ],
        },
        "carbaryl": {
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
                "Broad spectrum but hard on beneficial insects",
            ],
            "best_practices": [
                "Don't apply during bloom period",
                "Apply in evening to reduce bee exposure",
                "Follow pre-harvest interval strictly",
            ],
        },
        "permethrin": {
            "type": "PE",
            "display_name": "Permethrin Insecticide",
            "variants": ["pyrethroid insecticide", "broad spectrum", "permethrin 10%"],
            "manufacturer": "Various",
            "active_ingredient": "Permethrin",
            "application_rate": "1-2 fl oz per gallon water",
            "common_mistakes": ["HE", "FU"],
            "educational_tips": [
                "Synthetic pyrethroid with quick knockdown",
                "Effective against wide range of insects",
                "Low mammalian toxicity but toxic to fish",
            ],
            "best_practices": [
                "Don't apply near water sources",
                "Rotate with different mode-of-action insecticides",
                "Apply when beneficial insects are less active",
            ],
        },
        "imidacloprid": {
            "type": "PE",
            "display_name": "Imidacloprid Systemic",
            "variants": ["systemic insecticide", "neonicotinoid", "merit", "provado"],
            "manufacturer": "Bayer",
            "active_ingredient": "Imidacloprid",
            "application_rate": "0.5-1 fl oz per gallon water",
            "common_mistakes": ["FU"],
            "educational_tips": [
                "Systemic neonicotinoid - moves through plant tissue",
                "Excellent for aphids and other sucking insects",
                "Long residual control with single application",
            ],
            "best_practices": [
                "Avoid application during bloom on bee-attractive crops",
                "Apply as soil drench for systemic uptake",
                "Follow pollinator protection guidelines",
            ],
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
                "Safe for beneficial insects and mammals",
            ],
            "best_practices": [
                "Apply in evening - UV light breaks down Bt",
                "Reapply after rain or heavy dew",
                "Target young caterpillars for best results",
            ],
        },
        # FUNGICIDES (FU) - 5 most common
        "copper-sulfate": {
            "type": "FU",
            "display_name": "Copper Sulfate Fungicide",
            "variants": [
                "bordeaux mixture",
                "copper fungicide",
                "organic fungicide",
                "copper sulphate",
                "bluestone",
                "copper sulfate pentahydrate",
            ],
            "manufacturer": "Various",
            "active_ingredient": "Copper sulfate",
            "application_rate": "1-3 tablespoons per gallon water",
            "common_mistakes": ["FE", "PE"],  # Users think copper = fertilizer
            "educational_tips": [
                "Organic-approved fungicide and bactericide",
                "Preventive treatment - apply before disease appears",
                "Can cause phytotoxicity if overused",
            ],
            "best_practices": [
                "Don't apply in hot weather or to stressed plants",
                "Mix fresh solution for each application",
                "Avoid spraying flowers or fruit near harvest",
            ],
        },
        "chlorothalonil": {
            "type": "FU",
            "display_name": "Chlorothalonil Fungicide",
            "variants": ["broad spectrum fungicide", "daconil", "bravo"],
            "manufacturer": "Various",
            "active_ingredient": "Chlorothalonil",
            "application_rate": "1-2 fl oz per gallon water",
            "common_mistakes": ["PE"],
            "educational_tips": [
                "Broad-spectrum protectant fungicide",
                "Excellent for leaf spot and blight diseases",
                "Must be applied before disease infection occurs",
            ],
            "best_practices": [
                "Apply on 7-14 day schedule during disease season",
                "Good spray coverage essential for effectiveness",
                "Rotate with systemic fungicides to prevent resistance",
            ],
        },
        "mancozeb": {
            "type": "FU",
            "display_name": "Mancozeb Fungicide",
            "variants": ["contact fungicide", "preventive fungicide", "dithane"],
            "manufacturer": "Various",
            "active_ingredient": "Mancozeb",
            "application_rate": "2-3 tablespoons per gallon water",
            "common_mistakes": ["PE"],
            "educational_tips": [
                "Multi-site contact fungicide with low resistance risk",
                "Excellent mixing partner with systemic fungicides",
                "Provides broad-spectrum disease control",
            ],
            "best_practices": [
                "Apply before disease pressure builds",
                "Ensure thorough coverage of all plant surfaces",
                "Don't apply within specified pre-harvest interval",
            ],
        },
        "neem-oil": {
            "type": "FU",
            "display_name": "Neem Oil Fungicide",
            "variants": [
                "organic fungicide",
                "neem extract",
                "horticultural oil",
                "organic neem",
                "neem oil concentrate",
            ],
            "manufacturer": "Various",
            "active_ingredient": "Azadirachtin",
            "application_rate": "2-4 tablespoons per gallon water",
            "common_mistakes": ["PE", "FE"],  # Multi-purpose confusion
            "educational_tips": [
                "Organic oil with fungicidal and insecticidal properties",
                "Works by disrupting pest life cycles",
                "Also helps with powdery mildew and rust",
            ],
            "best_practices": [
                "Apply in evening or early morning to prevent leaf burn",
                "Test on small area first - can cause phytotoxicity",
                "Don't apply during bloom period",
            ],
        },
        "sulfur": {
            "type": "FU",
            "display_name": "Sulfur Fungicide",
            "variants": [
                "wettable sulfur",
                "organic sulfur fungicide",
                "elemental sulfur",
                "sulfur dust",
                "lime sulfur",
            ],
            "manufacturer": "Various",
            "active_ingredient": "Sulfur",
            "application_rate": "2-8 tablespoons per gallon water",
            "common_mistakes": ["FE"],  # Users think sulfur = fertilizer
            "educational_tips": [
                "Oldest known fungicide - organic approved",
                "Excellent for powdery mildew and rust diseases",
                "Also provides some mite control",
            ],
            "best_practices": [
                "Don't apply when temperatures above 90°F",
                "Avoid use within 30 days of oil applications",
                "Can lower soil pH over time with repeated use",
            ],
        },
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
        normalized = re.sub(r"[^\w\s-]", " ", name.lower())
        normalized = re.sub(r"[-_\s]+", " ", normalized)
        normalized = normalized.strip()

        # Handle common abbreviations and variations
        abbreviations = {
            "fert": "fertilizer",
            "herb": "herbicide",
            "pest": "pesticide",
            "insect": "insecticide",
            "fung": "fungicide",
            "org": "organic",
            "conc": "concentrate",
            "rtu": "ready to use",
            "wp": "wettable powder",
            "ec": "emulsifiable concentrate",
            "sc": "suspension concentrate",
            "df": "dry flowable",
        }

        for abbrev, full in abbreviations.items():
            normalized = re.sub(r"\b" + abbrev + r"\b", full, normalized)

        return normalized

    def _contains_agricultural_terms(self, query: str) -> bool:
        """
        Check if query contains agricultural terms to validate relevance.

        SECURITY: Prevents non-agricultural queries from matching products.
        ENHANCED: Requires full words only, no partial matches to prevent false positives.
        """
        agricultural_terms = {
            # Full product type words only - no partial matches
            "fertilizer",
            "herbicide",
            "pesticide",
            "insecticide",
            "fungicide",
            "chemical",
            # Common brands/products (full names)
            "miracle-gro",
            "roundup",
            "urea",
            "nitrogen",
            "phosphorus",
            "potassium",
            "organic",
            "spray",
            "granular",
            "liquid",
            "powder",
            "concentrate",
            # NPK and nutrients (complete patterns)
            "npk",
            "10-10-10",
            "46-0-0",
            "24-8-16",
            "15-9-12",
            "0-46-0",
            "0-0-60",
            # Application terms (full words)
            "application",
            "apply",
            "spray",
            "spread",
            "broadcast",
            "foliar",
            # Agricultural context (complete terms)
            "crop",
            "plant",
            "garden",
            "lawn",
            "farm",
            "agriculture",
            "agricultural",
            "weed",
            "weeds",
            "growth",
            "feed",
            "food",
            "cultivation",
            # REMOVED: Partial terms like 'fert', 'herb', 'pest', 'fung', 'insect'
            # These cause false positives by matching legitimate partial inputs
        }

        # Require exact word matches, not substrings
        query_words = set(word.lower().strip() for word in query.split())
        return bool(agricultural_terms & query_words)

    def smart_product_search(
        self, query: str, max_suggestions: int = 8, include_type_filter: bool = True
    ) -> List[Dict]:
        """
        Intelligent product search with ranking and educational context.

        Implements Smart Bag UX Step 2: Smart Recognition & Validation

        SECURITY: Enhanced validation to prevent false positive matches
        """
        if not query or len(query.strip()) < 3:  # FIXED: Minimum 3 characters
            # Return popular products by type for empty queries
            return self._get_popular_products(max_suggestions)

        normalized_query = self._normalize_name(query)
        suggestions = []
        query_words = set(normalized_query.split())

        # SECURITY: Validate query contains agricultural terms for meaningful matches
        if not self._contains_agricultural_terms(normalized_query):
            # For non-agricultural queries, use very strict matching
            strict_threshold = 0.8
        else:
            # ENHANCED: Higher threshold for agricultural terms to prevent partial matches
            if len(normalized_query) <= 4:
                strict_threshold = 0.7  # Much higher for short agricultural terms
            else:
                strict_threshold = 0.5  # Moderate threshold for longer terms

        # Score and rank all products
        product_scores = []

        for indexed_name, product_key in self.search_index.items():
            score = self._calculate_match_score(normalized_query, query_words, indexed_name, product_key)
            if score > strict_threshold:  # FIXED: Much higher threshold
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
                    "confidence": (
                        min(score * 0.9, 0.95) if score < 0.7 else min(score, 0.98)
                    ),  # FIXED: Reduce confidence for partial matches
                    "matched_text": matched_name,
                    "why_matched": self._explain_match(query, matched_name, score),
                    "educational_tip": product_data.get("educational_tips", [None])[0],  # First tip only for search
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

        # CRITICAL FIX: Prevent partial word matches for short queries
        if len(query) <= 4:
            # For short queries, require exact word match only - no substring matching
            if query in indexed_words:
                score += 0.3  # Only if it's a complete word in the indexed name
        else:
            # FIXED: Substring matching - much more restrictive, only for longer queries
            if len(query) >= 5:  # Only for queries 5+ characters
                if query in indexed_name:
                    score += 0.20  # Reduced from 0.25
                elif indexed_name in query and len(indexed_name) >= 5:
                    score += 0.15  # Reduced from 0.2

        # Manufacturer bonus
        manufacturer = product_data.get("manufacturer", "").lower()
        if manufacturer != "various" and len(manufacturer) > 3 and manufacturer in query:
            score += 0.2

        # Popular product bonus (but only for substantial matches)
        popular_products = {"miracle-gro", "roundup", "osmocote", "sevin"}
        if product_key in popular_products and score > 0.3:
            score += 0.1

        # NPK pattern matching for fertilizers
        if product_data["type"] == "FE" and re.search(r"\d+-\d+-\d+", query):
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

    def _get_popular_products(self, max_count: int = 6) -> List[Dict]:
        """Return most popular products for empty search"""
        popular_keys = ["miracle-gro", "roundup", "10-10-10", "urea", "copper-sulfate", "sevin", "osmocote", "bt"]

        suggestions = []
        for product_key in popular_keys[:max_count]:
            if product_key in self.SMART_PRODUCT_DATABASE:
                product_data = self.SMART_PRODUCT_DATABASE[product_key]
                suggestions.append(
                    {
                        "id": product_key,
                        "name": product_data.get("display_name", product_key.replace("-", " ").title()),
                        "type": self._type_name(product_data["type"]),
                        "type_code": product_data["type"],
                        "manufacturer": product_data.get("manufacturer", "Various"),
                        "npk": product_data.get("npk"),
                        "confidence": 0.8,
                        "why_matched": "Popular agricultural product",
                        "educational_tip": "Commonly used by farmers",
                    }
                )

        return suggestions

    def validate_smart_product(
        self, commercial_name: str, user_selected_type: str, confidence_threshold: float = 0.7
    ) -> SmartProductMatch:
        """
        Enhanced product validation with educational features.

        Implements Smart Bag UX Step 4: Smart Validation
        """
        if not commercial_name or not commercial_name.strip():
            return SmartProductMatch(
                commercial_name=commercial_name or "",
                correct_type=user_selected_type,
                confidence=0.0,
                warnings=["No product name provided - using selected type"],
                educational_tips=["Enter a product name for better accuracy and recommendations"],
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
                    "Using your selected type - please verify accuracy",
                ],
                educational_tips=[
                    "Check product label for exact name and active ingredients",
                    "Consider using a more specific product name",
                ],
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
                educational_tips.append(
                    f"Many farmers confuse {correct_type} and {user_selected_type} products. "
                    f"Check the product label for 'Active Ingredients' to confirm."
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

        if product_data.get("application_rate"):
            educational_tips.append(f"Typical application rate: {product_data['application_rate']}")

        return SmartProductMatch(
            commercial_name=commercial_name,
            correct_type=correct_type,
            npk_ratio=product_data.get("npk"),
            confidence=confidence,
            warnings=warnings,
            educational_tips=educational_tips,
            manufacturer=product_data.get("manufacturer"),
            active_ingredient=product_data.get("active_ingredient"),
            application_rate=product_data.get("application_rate"),
            best_practices=product_data.get("best_practices", []),
        )

    def _find_enhanced_match(self, normalized_input: str) -> Optional[Tuple[str, float]]:
        """Enhanced matching with fuzzy logic and context awareness - SECURITY ENHANCED"""
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
        if self._contains_agricultural_terms(normalized_input):
            if len(normalized_input) <= 4:
                min_threshold = 0.75  # Very high threshold for short agricultural terms
            else:
                min_threshold = 0.6  # Standard threshold for longer terms
        else:
            min_threshold = 0.8  # Very high threshold for non-agricultural

        for indexed_name, product_key in self.search_index.items():
            score = self._calculate_match_score(normalized_input, input_words, indexed_name, product_key)

            if score > best_score and score >= min_threshold:  # FIXED: Much higher threshold
                best_score = score
                best_match = product_key

        return (best_match, min(best_score, 0.95)) if best_match else None

    def _type_name(self, type_code: str) -> str:
        """Convert type code to human-readable name"""
        type_names = {"FE": "Fertilizer", "PE": "Pesticide", "FU": "Fungicide", "HE": "Herbicide"}
        return type_names.get(type_code, type_code)

    def get_smart_suggestions_by_type(self, chemical_type: str, max_suggestions: int = 5) -> List[Dict]:
        """Get product suggestions filtered by chemical type"""
        suggestions = []

        if chemical_type in self.type_index:
            product_keys = self.type_index[chemical_type][:max_suggestions]

            for product_key in product_keys:
                product_data = self.SMART_PRODUCT_DATABASE[product_key]
                suggestions.append(
                    {
                        "id": product_key,
                        "name": product_data.get("display_name", product_key.replace("-", " ").title()),
                        "type": self._type_name(product_data["type"]),
                        "type_code": product_data["type"],
                        "manufacturer": product_data.get("manufacturer", "Various"),
                        "npk": product_data.get("npk"),
                        "active_ingredient": product_data.get("active_ingredient"),
                        "confidence": 0.8,
                        "educational_tip": product_data.get("educational_tips", [None])[0],
                    }
                )

        return suggestions

    def get_validation_stats(self) -> Dict:
        """Get enhanced validation statistics"""
        total_products = len(self.SMART_PRODUCT_DATABASE)
        type_counts = {"FE": 0, "PE": 0, "FU": 0, "HE": 0}
        manufacturers = set()

        for product_data in self.SMART_PRODUCT_DATABASE.values():
            type_counts[product_data["type"]] += 1
            manufacturer = product_data.get("manufacturer")
            if manufacturer and manufacturer != "Various":
                manufacturers.add(manufacturer)

        return {
            "total_products": total_products,
            "fertilizers": type_counts["FE"],
            "pesticides": type_counts["PE"],
            "fungicides": type_counts["FU"],
            "herbicides": type_counts["HE"],
            "manufacturers": len(manufacturers),
            "coverage": "Top 25 agricultural products with enhanced farmer education",
            "features": [
                "Smart product search and recognition",
                "Educational tips and best practices",
                "Application rate recommendations",
                "Common mistake detection",
                "NPK auto-fill for fertilizers",
            ],
        }


# Singleton instance for global use
smart_product_validator = SmartProductValidator()
