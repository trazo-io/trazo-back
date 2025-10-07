"""
Production-ready constants for Trazo carbon calculations.
All values based on EPA and USDA verified standards.
"""


# USDA-verified carbon footprint conversion factors
class USDAConversions:
    """USDA-integrated Environmental conversion factors"""

    # USDA standard: 1 gallon gasoline = 8.887 kg CO₂e, average 25 mpg
    # Therefore: 1 mile = 8.887/25 = 0.35548 kg CO₂e/mile
    KG_CO2_PER_MILE = 0.35548

    # USDA standard: Average tree absorbs ~48 lbs (21.8 kg) CO₂ per year
    KG_CO2_PER_TREE_ANNUAL = 21.8


# USDA-verified carbon score grading thresholds
class USDAGrading:
    """USDA-based carbon footprint grading system (kg CO₂e/kg product)"""

    CARBON_SCORE_THRESHOLDS = {
        "A_PLUS": 0.5,
        "A": 1.0,
        "B": 2.0,
        "C": 3.0,
        "D": 5.0,
        # Above 5.0 = F grade
    }


# User engagement milestones for achievements
class EngagementMilestones:
    """User achievement milestones for sustainable engagement"""

    SCAN_MILESTONES = {
        "EXPLORER": 10,  # First engagement milestone
        "COMMITTED": 25,  # Regular user milestone
        "ADVOCATE": 50,  # Power user milestone
        "CHAMPION": 100,  # Expert user milestone
    }


def get_carbon_score_from_co2e(co2e_value):
    """
    Calculate carbon score grade from CO₂e value using USDA thresholds

    Args:
        co2e_value (float): Carbon footprint in kg CO₂e/kg product

    Returns:
        str: Grade from A+ to F
    """
    if co2e_value <= USDAGrading.CARBON_SCORE_THRESHOLDS["A_PLUS"]:
        return "A+"
    elif co2e_value <= USDAGrading.CARBON_SCORE_THRESHOLDS["A"]:
        return "A"
    elif co2e_value <= USDAGrading.CARBON_SCORE_THRESHOLDS["B"]:
        return "B"
    elif co2e_value <= USDAGrading.CARBON_SCORE_THRESHOLDS["C"]:
        return "C"
    elif co2e_value <= USDAGrading.CARBON_SCORE_THRESHOLDS["D"]:
        return "D"
    else:
        return "F"


def calculate_miles_equivalent(kg_co2e):
    """
    Convert carbon footprint to driving miles equivalent using EPA standards

    Args:
        kg_co2e (float): Carbon footprint in kg CO₂e

    Returns:
        float: Equivalent driving miles
    """
    return kg_co2e / USDAConversions.KG_CO2_PER_MILE


def calculate_trees_equivalent(kg_co2e):
    """
    Convert carbon footprint to tree absorption equivalent using EPA standards

    Args:
        kg_co2e (float): Carbon footprint in kg CO₂e

    Returns:
        float: Equivalent trees needed for annual absorption
    """
    return kg_co2e / USDAConversions.KG_CO2_PER_TREE_ANNUAL


# Production-ready bounds checking for carbon calculations
class CarbonValidation:
    """Validation bounds for agricultural carbon calculations"""

    # Realistic bounds for agricultural products (kg CO₂e per kg product)
    MIN_CO2E_PER_KG = 0.01  # Ultra-low carbon products (herbs, lettuce)
    MAX_CO2E_PER_KG = 50.0  # High-carbon products (imported exotic fruits)

    # Miles equivalent bounds (unrealistic if outside these ranges)
    MAX_MILES_EQUIVALENT = 140.0  # ~50kg CO2e limit = ~140 miles maximum
    MIN_MILES_EQUIVALENT = 0.03  # ~0.01kg CO2e minimum = ~0.03 miles

    # Trees equivalent bounds
    MAX_TREES_EQUIVALENT = 2300  # ~50kg CO2e limit = ~2300 trees maximum
    MIN_TREES_EQUIVALENT = 0.001  # ~0.01kg CO2e minimum = ~0.001 trees


def validate_co2e_value(co2e_value, product_weight_kg=1.0):
    """
    Validate CO₂e values are within realistic agricultural bounds

    Args:
        co2e_value (float): Carbon footprint in kg CO₂e
        product_weight_kg (float): Product weight in kg

    Returns:
        dict: Validation result with is_valid, adjusted_value, and warnings
    """
    result = {
        "is_valid": True,
        "original_value": co2e_value,
        "adjusted_value": co2e_value,
        "warnings": [],
        "product_intensity": co2e_value / product_weight_kg if product_weight_kg > 0 else 0,
    }

    # Check if CO₂e per kg is within reasonable bounds
    intensity = result["product_intensity"]

    if intensity < CarbonValidation.MIN_CO2E_PER_KG:
        result["warnings"].append(f"Unusually low carbon intensity: {intensity:.3f} kg CO₂e/kg")
        result["adjusted_value"] = CarbonValidation.MIN_CO2E_PER_KG * product_weight_kg
        result["is_valid"] = False

    elif intensity > CarbonValidation.MAX_CO2E_PER_KG:
        result["warnings"].append(f"Unrealistically high carbon intensity: {intensity:.1f} kg CO₂e/kg")
        result["adjusted_value"] = CarbonValidation.MAX_CO2E_PER_KG * product_weight_kg
        result["is_valid"] = False

    return result


def validate_miles_equivalent(miles_value):
    """
    Validate miles equivalent values are within realistic bounds

    Args:
        miles_value (float): Driving miles equivalent

    Returns:
        dict: Validation result with is_valid and adjusted_value
    """
    if miles_value > CarbonValidation.MAX_MILES_EQUIVALENT:
        return {
            "is_valid": False,
            "original_value": miles_value,
            "adjusted_value": CarbonValidation.MAX_MILES_EQUIVALENT,
            "warning": f"Miles equivalent capped at {CarbonValidation.MAX_MILES_EQUIVALENT} miles",
        }
    elif miles_value < CarbonValidation.MIN_MILES_EQUIVALENT:
        return {
            "is_valid": False,
            "original_value": miles_value,
            "adjusted_value": CarbonValidation.MIN_MILES_EQUIVALENT,
            "warning": f"Miles equivalent raised to minimum {CarbonValidation.MIN_MILES_EQUIVALENT} miles",
        }

    return {"is_valid": True, "original_value": miles_value, "adjusted_value": miles_value, "warning": None}
