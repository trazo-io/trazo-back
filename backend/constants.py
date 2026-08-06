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


# REMOVED 2026-08-04 — `USDAGrading` and `get_carbon_score_from_co2e()`.
#
# They turned a production's kg CO₂e/kg into a letter grade, A+ through F, from thresholds
# hardcoded here (0.5 / 1.0 / 2.0 / 3.0 / 5.0) and served it to shoppers on the consumer
# dashboard, favorites list and product comparison.
#
# Two separate problems, either one disqualifying:
#
# 1. THE NAME WAS THE CLAIM. A class called `USDAGrading`, documented as a "USDA-based carbon
#    footprint grading system", attributes the scheme to a federal agency. There is no USDA
#    carbon letter-grade programme; these five numbers were chosen in this repository. That is
#    the "USDA Verified / USDA Certified" wording `compliance.md` forbids outright, and an
#    unsourced attribution under FTC 16 CFR 260.6.
#
# 2. A GRADE IS A LABEL. Trazo assigning a farm an "A" or a "D" and showing it to a consumer is
#    the self-created sustainability label banned by EU ECGT 2024/825 (live 2026-09-27) — the
#    same artefact removed from the QR page in June 2026 and from the producer dashboard on
#    2026-08-04. It survived here because the consumer *dashboard* is authenticated, so it sat
#    outside the anonymous-endpoint sweep that polices the public surfaces.
#
# What consumers get instead is what they got alongside the grade all along: the measured figure,
# `carbon_footprint` ("1.23 kg CO₂e"), which is a fact and needs no defence. Comparison now ranks
# on that number rather than on the alphabet. See `format_carbon_amount` below for the unit
# correction that came with it — the "/kg" this used to carry was never true.
#
# Do not reintroduce a grade, band, tier or letter for a consumer surface. If a number needs a
# verdict attached, it belongs on the producer dashboard, where the farmer can act on it.


# User engagement milestones for achievements
class EngagementMilestones:
    """User achievement milestones for sustainable engagement"""

    SCAN_MILESTONES = {
        "EXPLORER": 10,  # First engagement milestone
        "COMMITTED": 25,  # Regular user milestone
        "ADVOCATE": 50,  # Power user milestone
        "CHAMPION": 100,  # Expert user milestone
    }


def format_carbon_amount(co2e_value):
    """Format a recorded CO₂e amount for display. A measurement, not a verdict.

    Replaces `get_carbon_score_from_co2e()` (see the note above): same input, but it returns the
    figure rather than a letter grade Trazo invented and attributed to the USDA.

    UNITS (corrected 2026-08-04): the value comes from `CarbonEntry.amount`, whose own help_text
    is "Amount in kg CO2e" — a TOTAL for that entry. The consumer surfaces rendered it as
    "kg CO₂e/kg", i.e. an intensity per kilogram of product, which it has never been; there is no
    yield denominator anywhere in that code path.

    That mislabel also silently broke the grade this replaces: its thresholds (0.5 / 1.0 / 2.0 /
    3.0 / 5.0 kg CO₂e per kg) were compared against totals in the hundreds or thousands, so every
    production fell through to the final branch. Shoppers were being shown an "F" for every farm
    on the platform. A wrong unit is not cosmetic.
    """
    if co2e_value is None:
        return None
    return f"{float(co2e_value):.2f} kg CO₂e"


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
