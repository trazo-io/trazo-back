"""
Trazo Shared Field Registry — Backend Single Source of Truth for Enum Choices.

This module centralizes all enum choices used across event types to:
1. Eliminate duplicate definitions (e.g., FUEL_TYPES was defined in 4+ places)
2. Provide consistent values across ChemicalEvent, ProductionEvent, SoilManagementEvent,
   PestManagementEvent, EquipmentEvent, WeatherEvent, BusinessEvent, GeneralEvent
3. Serve as the backend source of truth that drf-spectacular exports to OpenAPI schema
4. Enable the frontend to generate matching TypeScript types via openapi-typescript

All choice lists follow Django's (value, label) tuple pattern.

When adding new enum values:
- Add the value here FIRST
- Then reference from models via `choices=UNIT_AREA` etc.
- NEVER define inline choices in model files (creates drift)

Source: EPA 40 CFR Part 98, EPA eGRID 2023, USDA NASS 2023, USDA NRCS, OMRI
Last Updated: 2026-04-05 (Phase 1: Event Field SSOT Migration)
"""

# ============================================================================
# FUEL TYPES (already centralized in carbon/choices.py — re-exported here)
# ============================================================================
# Used in: ChemicalEvent.application_fuel_type, ProductionEvent.fuel_type,
#          SoilManagementEvent.fuel_type, PestManagementEvent.fuel_type, EquipmentEvent.fuel_type
from carbon.choices import FUEL_TYPE_FACTORS, FUEL_TYPES  # noqa: F401

# ============================================================================
# UNIT ENUMS — Physical units for quantitative fields
# ============================================================================

# Area units (most common: acres for US farms, ha for international)
# Used in: ChemicalEvent.area_unit, ProductionEvent.area_unit, SoilManagementEvent.area_unit,
#          PestManagementEvent.area_unit, EquipmentEvent.area_unit
UNIT_AREA = [
    ("ha", "Hectares"),
    ("acres", "Acres"),
    ("m2", "Square Meters"),
    ("km2", "Square Kilometers"),
]

# Volume units (liquid/solid chemicals, fertilizers)
# Used in: ChemicalEvent.volume_unit
UNIT_VOLUME = [
    ("L", "Liters"),
    ("gal", "Gallons"),
    ("mL", "Milliliters"),
    ("oz", "Ounces"),
    ("kg", "Kilograms"),
    ("lbs", "Pounds"),
]

# Fuel units (diesel, gasoline, electricity)
# Used in: ChemicalEvent.application_fuel_unit, ProductionEvent.fuel_unit,
#          SoilManagementEvent.fuel_unit, PestManagementEvent.fuel_unit, EquipmentEvent.fuel_unit
UNIT_FUEL = [
    ("L", "Liters"),
    ("gal", "Gallons"),
    ("kg", "Kilograms"),
    ("kWh", "Kilowatt-hours"),
]

# Yield/harvest units
# Used in: ProductionEvent.yield_unit
UNIT_YIELD = [
    ("kg", "Kilograms"),
    ("tons", "Tonnes"),
    ("lbs", "Pounds"),
    ("boxes", "Boxes"),
    ("plants", "Plants"),
    ("seeds", "Seeds"),
]

# Distance units (transportation, depth)
# Used in: ProductionEvent.transportation_unit
UNIT_DISTANCE = [
    ("km", "Kilometers"),
    ("miles", "Miles"),
    ("m", "Meters"),
]

# Depth units (irrigation, tillage)
# Used in: ProductionEvent.irrigation_depth_unit
UNIT_DEPTH = [
    ("inches", "Inches"),
    ("cm", "Centimeters"),
]


# ============================================================================
# APPLICATION METHODS
# ============================================================================

# Chemical application method (how chemical is delivered to the crop)
# Used in: ChemicalEvent.application_method_structured
APPLICATION_METHOD = [
    ("broadcast", "Broadcast"),
    ("injection", "Soil Injection"),
    ("foliar", "Foliar Application"),
    ("drip", "Drip/Fertigation"),
    ("banding", "Band Application"),
    # F20 (2026-06): DPR-PML-017C box 21 application-method categories + the
    # orchard-standard air-blast. Fumigation additionally requires ffm_code.
    ("ground_spray", "Ground Spray"),
    ("air_blast", "Air-Blast (orchard sprayer)"),
    ("aerial", "Aerial"),
    ("fumigation", "Fumigation"),
    ("chemigation", "Chemigation"),
    ("soil_incorporation", "Soil Incorporation"),
]

# USDA NASS 2023 irrigation methods
# Used in: ProductionEvent.irrigation_method
IRRIGATION_METHOD = [
    ("flood", "Flood Irrigation"),
    ("furrow", "Furrow Irrigation"),
    ("drip", "Drip Irrigation"),
    ("sprinkler", "Sprinkler System"),
    ("center_pivot", "Center Pivot"),
    ("sub_irrigation", "Sub-surface Irrigation"),
    ("micro_sprinkler", "Micro-sprinkler"),
    ("hand_watering", "Hand Watering"),
    ("rain_fed", "Rain-fed Only"),
]


# ============================================================================
# SOURCE ENUMS — Provenance/origin of inputs
# ============================================================================

# Seed/seedling source — WHERE the seed came from (transparency field; does NOT affect carbon)
# Used in: ProductionEvent.seeds_source
# Note: "certified_organic" is intentionally NOT a source — use seed_certification_status for that.
# Historical records with seeds_source="certified_organic" are migrated by 0152_nop_seed_traceability.
SEEDS_SOURCE = [
    ("farm_saved", "Farm-Saved Seeds"),
    ("local", "Local Nursery/Supplier"),
    ("cooperative", "Farmer Cooperative"),
    ("commercial", "Commercial Supplier"),
    ("other", "Other"),
]

# Seed regulatory classification — WHAT the seed is, per NOP 7 CFR 205.204
# Used in: ProductionEvent.seed_certification_status
# "non_organic_treated" with prohibited substances disqualifies the crop from organic sale.
SEED_CERTIFICATION_STATUS = [
    ("certified_organic", "Certified Organic"),
    ("transitional", "Transitional"),
    ("non_organic_untreated", "Non-organic (Untreated)"),
    ("non_organic_treated", "Non-organic (Treated)"),
]

# Water source (affects pump energy factor — USDA NRCS)
# Used in: ProductionEvent.water_source
WATER_SOURCE = [
    ("well_groundwater", "Well/Groundwater"),
    ("municipal", "Municipal Water Supply"),
    ("rainwater_harvesting", "Rainwater Harvesting"),
    ("irrigation_canal", "Irrigation Canal/District"),
    ("river_stream", "River/Stream"),
    ("pond_reservoir", "Pond/Reservoir"),
    ("recycled_water", "Recycled/Reclaimed Water"),
    ("other", "Other"),
]

# Electricity source for irrigation pumps (affects CO2 emission factor)
# Used in: ProductionEvent.electricity_source
ELECTRICITY_SOURCE = [
    ("grid", "Grid Electricity"),
    ("solar", "Solar"),
    ("wind", "Wind"),
    ("diesel_generator", "Diesel Generator"),
    ("mixed", "Mixed Sources"),
]


# ============================================================================
# EFFICIENCY/GRADE ENUMS
# ============================================================================

# Production efficiency rating (carbon scoring modifier)
# Used in: ProductionEvent.production_efficiency, SoilManagementEvent.production_efficiency,
#          PestManagementEvent.production_efficiency
PRODUCTION_EFFICIENCY = [
    ("high", "High Efficiency"),
    ("normal", "Normal Efficiency"),
    ("low", "Low Efficiency"),
]

# Harvest quality grade (premium fruit operations — CA citrus, UY exports)
# Used in: ProductionEvent.harvest_quality_grade
HARVEST_QUALITY_GRADE = [
    ("export_quality", "Export Quality"),
    ("grade_a", "Grade A"),
    ("grade_b", "Grade B"),
    ("grade_c", "Grade C"),
    ("domestic", "Domestic Market"),
    ("processing", "Processing/Juice"),
]


# ============================================================================
# EQUIPMENT ENUMS
# ============================================================================

# Equipment type (for carbon calculation accuracy)
# Used in: ProductionEvent.equipment_type
EQUIPMENT_TYPE = [
    ("tractor", "Tractor"),
    ("harvester", "Harvester/Combine"),
    ("sprayer", "Sprayer"),
    ("truck", "Truck/Transport"),
    ("generator", "Generator"),
    ("pump", "Irrigation Pump"),
    ("other", "Other Equipment"),
]

# Equipment operation type (for Equipment Maintenance events within ProductionEvent)
# Used in: ProductionEvent.equipment_operation_type
EQUIPMENT_OPERATION_TYPE = [
    ("FC", "Fuel Consumption"),
    ("MN", "Maintenance"),
    ("RE", "Repair"),
    ("CA", "Calibration"),
    ("BD", "Breakdown"),
    ("EI", "Inspection"),
    ("CL", "Cleaning"),
]


# ============================================================================
# AGRONOMIC/CROP ENUMS
# ============================================================================

# Crop growth stage (agronomic context — used on all event types via CommonEvent)
# Used in: CommonEvent.growth_stage (abstract base class, inherited by all events)
GROWTH_STAGE = [
    ("dormant", "Dormant"),
    ("budbreak", "Bud Break"),
    ("bloom", "Bloom/Flowering"),
    ("fruit_set", "Fruit Set"),
    ("vegetative", "Vegetative Growth"),
    ("maturation", "Maturation"),
    ("harvest_ready", "Harvest Ready"),
    ("post_harvest", "Post-Harvest"),
]


# ============================================================================
# COMPLIANCE/CERTIFICATION ENUMS
# ============================================================================

# Organic approval status (transparency + consumer trust)
# NOTE: Legacy values (yes/no/not_applicable) kept for backward compatibility with existing data.
# New entries should use the detailed values (omri_listed, usda_nop_approved, etc.)
# Used in: ChemicalEvent.organic_approved
ORGANIC_APPROVED = [
    # Legacy choices (kept for backward compatibility with pre-2025-11 data)
    ("yes", "Yes - Organic Approved"),
    ("no", "No - Not Organic"),
    ("not_applicable", "Not Applicable"),
    # Detailed organic certification options (Sprint 6, 2025-11)
    ("omri_listed", "OMRI Listed - Organic certified"),
    ("usda_nop_approved", "USDA NOP Approved - National Organic Program"),
    ("organic_equivalent", "Organic Equivalent - Meets organic standards"),
    ("not_organic", "Not Organic Approved - Conventional use only"),
    ("transitional", "Transitional - In certification process"),
]


# ============================================================================
# CHEMICAL SUBTYPE ENUMS — For accurate carbon emission factor selection
# ============================================================================

# Combined chemical subtype (what's stored in DB)
# Used in: ChemicalEvent.chemical_subtype
CHEMICAL_SUBTYPE = [
    # Herbicide subtypes
    ("synthetic_herbicide", "Synthetic Herbicide"),
    ("organic_herbicide", "Organic/Natural Herbicide"),
    # Fungicide subtypes
    ("synthetic_fungicide", "Synthetic Fungicide"),
    ("organic_fungicide", "Organic/Natural Fungicide"),
    ("copper_fungicide", "Copper-Based Fungicide"),
    ("sulfur_fungicide", "Sulfur-Based Fungicide"),
    ("biological_fungicide", "Biological Fungicide"),
    # Pesticide subtypes
    ("synthetic_pesticide", "Synthetic Pesticide"),
    ("organic_pesticide", "Organic/Natural Pesticide"),
    ("biological_pesticide", "Biological Pesticide"),
    # Fertilizer subtypes
    ("synthetic_fertilizer", "Synthetic/Chemical Fertilizer"),
    ("organic_fertilizer", "Organic Fertilizer"),
    ("slow_release_fertilizer", "Slow-Release Fertilizer"),
]

# Sub-options filtered by chemical main type (for frontend UI rendering)
# The structured subtype UI shows only relevant options based on main type (FE/PE/FU/HE)
CHEMICAL_SUBTYPE_BY_MAIN_TYPE = {
    "FE": [
        ("synthetic_fertilizer", "Synthetic/Chemical Fertilizer"),
        ("organic_fertilizer", "Organic Fertilizer"),
        ("slow_release_fertilizer", "Slow-Release Fertilizer"),
    ],
    "PE": [
        ("synthetic_pesticide", "Synthetic Pesticide"),
        ("organic_pesticide", "Organic/Natural Pesticide"),
        ("biological_pesticide", "Biological Pesticide"),
    ],
    "FU": [
        ("synthetic_fungicide", "Synthetic Fungicide"),
        ("organic_fungicide", "Organic/Natural Fungicide"),
        ("copper_fungicide", "Copper-Based Fungicide"),
        ("sulfur_fungicide", "Sulfur-Based Fungicide"),
        ("biological_fungicide", "Biological Fungicide"),
    ],
    "HE": [
        ("synthetic_herbicide", "Synthetic Herbicide"),
        ("organic_herbicide", "Organic/Natural Herbicide"),
    ],
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_choice_values(choices):
    """Return list of valid values (first element of each tuple) from a choices list."""
    return [choice[0] for choice in choices]


def get_choice_label(choices, value):
    """Return the human label for a given value in a choices list."""
    for choice_value, choice_label in choices:
        if choice_value == value:
            return choice_label
    return None


def is_valid_choice(choices, value):
    """Check if a value exists in a choices list."""
    return value in get_choice_values(choices)
