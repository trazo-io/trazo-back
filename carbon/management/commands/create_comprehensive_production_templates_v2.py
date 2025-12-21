"""
V2 Production Template Seed Command

Creates comprehensive production templates with COMPLETE backend_event_fields for ALL event types.
Every form field has smart defaults - no empty fields.

Event Types:
- 0: Weather (WeatherEvent)
- 1: Chemical (ChemicalEvent) - Fertilizers, Pesticides, Herbicides, Fungicides
- 2: Production (ProductionEvent) - Planting, Harvest, Irrigation, Pruning, etc.
- 3: General (GeneralEvent)
- 4: Equipment (EquipmentEvent) - Legacy, merged to Production EM
- 5: Soil (SoilManagementEvent)
- 6: Pest (PestManagementEvent)
- 7: Business (BusinessEvent)

Usage:
    python manage.py create_comprehensive_production_templates_v2 --dry-run
    python manage.py create_comprehensive_production_templates_v2 --crop=avocados
    python manage.py create_comprehensive_production_templates_v2 --force
    python manage.py create_comprehensive_production_templates_v2
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from carbon.models import CropType, EventTemplate, ProductionTemplate


# =============================================================================
# SECTION 1: CROP-SPECIFIC CUSTOMIZATIONS (16 Crops - California Focus)
# =============================================================================

CROP_CUSTOMIZATIONS = {
    # TREE CROPS - California Central Valley Focus
    "avocados": {
        "npk": "8-3-9",
        "nitrogen_pct": 8.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 9.0,
        "commercial_name": "Avocado Special NPK 8-3-9 + 2MgO",
        "common_pests": "Avocado thrips, Persea mite, Avocado lace bug, Phytophthora",
        "beneficial_insects": "Predatory mites, Lacewings, Ladybugs",
        "irrigation_method": "drip",
        "typical_area": 8.0,
        "region": "California",
        "timing_soil": "February - March",
        "timing_plant": "Spring or Fall",
        "timing_fertilize": "March - April",
        "timing_irrigate": "April - October",
        "timing_pest": "May - September",
        "timing_harvest": "April - November",
        "yield_per_ha": 12.0,
        "yield_unit": "tons",
    },
    "citrus_oranges": {
        "npk": "13-7-13",
        "nitrogen_pct": 13.0,
        "phosphorus_pct": 7.0,
        "potassium_pct": 13.0,
        "commercial_name": "Citrus Special NPK 13-7-13",
        "common_pests": "Citrus psyllid, Red scale, Citrus leafminer, Thrips",
        "beneficial_insects": "Parasitic wasps, Ladybugs, Lacewings",
        "irrigation_method": "drip",
        "typical_area": 10.0,
        "region": "California",
        "timing_soil": "January - February",
        "timing_plant": "March - April",
        "timing_fertilize": "February - March",
        "timing_irrigate": "March - October",
        "timing_pest": "April - September",
        "timing_harvest": "November - June",
        "yield_per_ha": 30.0,
        "yield_unit": "tons",
    },
    "apples": {
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Apple Orchard NPK 10-10-10",
        "common_pests": "Codling moth, Apple maggot, Aphids, Spider mites",
        "beneficial_insects": "Trichogramma wasps, Lacewings, Predatory mites",
        "irrigation_method": "drip",
        "typical_area": 8.0,
        "region": "California",
        "timing_soil": "February - March",
        "timing_plant": "Dormant Season",
        "timing_fertilize": "March - April",
        "timing_irrigate": "April - September",
        "timing_pest": "April - August",
        "timing_harvest": "August - October",
        "yield_per_ha": 35.0,
        "yield_unit": "tons",
    },
    "grapes": {
        "npk": "8-8-16",
        "nitrogen_pct": 8.0,
        "phosphorus_pct": 8.0,
        "potassium_pct": 16.0,
        "commercial_name": "Vineyard Special NPK 8-8-16",
        "common_pests": "Grape leafhopper, Spider mites, Powdery mildew, Botrytis",
        "beneficial_insects": "Anagrus wasps, Predatory mites, Lacewings",
        "irrigation_method": "drip",
        "typical_area": 12.0,
        "region": "California",
        "timing_soil": "January - February",
        "timing_plant": "Dormant Season",
        "timing_fertilize": "March - April",
        "timing_irrigate": "April - September",
        "timing_pest": "May - August",
        "timing_harvest": "August - October",
        "yield_per_ha": 15.0,
        "yield_unit": "tons",
    },
    "almonds": {
        "npk": "12-12-17",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 12.0,
        "potassium_pct": 17.0,
        "commercial_name": "Almond Orchard NPK 12-12-17",
        "common_pests": "Navel orangeworm, Peach twig borer, Spider mites, Aphids",
        "beneficial_insects": "Parasitic wasps, Lacewings, Ground beetles",
        "irrigation_method": "micro_sprinkler",
        "typical_area": 15.0,
        "region": "California",
        "timing_soil": "January - February",
        "timing_plant": "Dormant Season",
        "timing_fertilize": "February - March",
        "timing_irrigate": "March - September",
        "timing_pest": "April - August",
        "timing_harvest": "August - September",
        "yield_per_ha": 3.0,
        "yield_unit": "tons",
    },
    # BERRY CROPS
    "strawberries": {
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Strawberry Fertigation NPK 10-10-10",
        "common_pests": "Spider mites, Lygus bugs, Aphids, Whiteflies",
        "beneficial_insects": "Predatory mites, Minute pirate bugs, Ladybugs",
        "irrigation_method": "drip",
        "typical_area": 3.0,
        "region": "California",
        "timing_soil": "August - September",
        "timing_plant": "September - October",
        "timing_fertilize": "October - August",
        "timing_irrigate": "Year-round",
        "timing_pest": "November - July",
        "timing_harvest": "January - July",
        "yield_per_ha": 50.0,
        "yield_unit": "tons",
    },
    # GRAIN CROPS
    "corn_field": {
        "npk": "20-10-10",
        "nitrogen_pct": 20.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Corn Starter NPK 20-10-10",
        "common_pests": "Corn borers, Corn rootworm, Aphids, Armyworms",
        "beneficial_insects": "Trichogramma wasps, Ground beetles, Ladybugs",
        "irrigation_method": "center_pivot",
        "typical_area": 50.0,
        "region": "Midwest",
        "timing_soil": "March - April",
        "timing_plant": "April - May",
        "timing_fertilize": "May - June",
        "timing_irrigate": "June - August",
        "timing_pest": "June - July",
        "timing_harvest": "September - October",
        "yield_per_ha": 10.0,
        "yield_unit": "tons",
    },
    "wheat": {
        "npk": "15-15-15",
        "nitrogen_pct": 15.0,
        "phosphorus_pct": 15.0,
        "potassium_pct": 15.0,
        "commercial_name": "Wheat Balanced NPK 15-15-15",
        "common_pests": "Aphids, Hessian fly, Wheat stem sawfly, Armyworms",
        "beneficial_insects": "Parasitic wasps, Lady beetles, Ground beetles",
        "irrigation_method": "flood",
        "typical_area": 40.0,
        "region": "Midwest",
        "timing_soil": "September - October",
        "timing_plant": "October - November",
        "timing_fertilize": "February - March",
        "timing_irrigate": "March - May",
        "timing_pest": "April - May",
        "timing_harvest": "June - July",
        "yield_per_ha": 5.5,
        "yield_unit": "tons",
    },
    "soybeans": {
        "npk": "0-20-20",
        "nitrogen_pct": 0.0,
        "phosphorus_pct": 20.0,
        "potassium_pct": 20.0,
        "commercial_name": "Soybean PK Blend 0-20-20",
        "common_pests": "Soybean aphid, Bean leaf beetle, Spider mites, Stink bugs",
        "beneficial_insects": "Asian lady beetle, Parasitic wasps, Ground beetles",
        "irrigation_method": "center_pivot",
        "typical_area": 45.0,
        "region": "Midwest",
        "timing_soil": "April - May",
        "timing_plant": "May - June",
        "timing_fertilize": "At planting",
        "timing_irrigate": "July - August",
        "timing_pest": "June - August",
        "timing_harvest": "September - October",
        "yield_per_ha": 3.0,
        "yield_unit": "tons",
    },
    "rice": {
        "npk": "16-16-16",
        "nitrogen_pct": 16.0,
        "phosphorus_pct": 16.0,
        "potassium_pct": 16.0,
        "commercial_name": "Rice Paddy NPK 16-16-16",
        "common_pests": "Rice water weevil, Rice stink bug, Armyworms, Stem borers",
        "beneficial_insects": "Spiders, Dragonflies, Parasitic wasps",
        "irrigation_method": "flood",
        "typical_area": 30.0,
        "region": "California",
        "timing_soil": "March - April",
        "timing_plant": "April - May",
        "timing_fertilize": "May - June",
        "timing_irrigate": "May - August",
        "timing_pest": "June - August",
        "timing_harvest": "September - October",
        "yield_per_ha": 9.0,
        "yield_unit": "tons",
    },
    # VEGETABLE CROPS
    "tomatoes": {
        "npk": "8-24-24",
        "nitrogen_pct": 8.0,
        "phosphorus_pct": 24.0,
        "potassium_pct": 24.0,
        "commercial_name": "Tomato Special NPK 8-24-24",
        "common_pests": "Tomato hornworm, Whiteflies, Aphids, Spider mites",
        "beneficial_insects": "Parasitic wasps, Ladybugs, Minute pirate bugs",
        "irrigation_method": "drip",
        "typical_area": 5.0,
        "region": "California",
        "timing_soil": "February - March",
        "timing_plant": "April - May",
        "timing_fertilize": "May - August",
        "timing_irrigate": "May - September",
        "timing_pest": "June - September",
        "timing_harvest": "July - October",
        "yield_per_ha": 80.0,
        "yield_unit": "tons",
    },
    "potatoes": {
        "npk": "10-20-20",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 20.0,
        "potassium_pct": 20.0,
        "commercial_name": "Potato Tuber NPK 10-20-20",
        "common_pests": "Colorado potato beetle, Aphids, Wireworms, Flea beetles",
        "beneficial_insects": "Lady beetles, Ground beetles, Parasitic wasps",
        "irrigation_method": "drip",
        "typical_area": 8.0,
        "region": "California",
        "timing_soil": "February - March",
        "timing_plant": "March - April",
        "timing_fertilize": "April - June",
        "timing_irrigate": "April - August",
        "timing_pest": "May - July",
        "timing_harvest": "July - September",
        "yield_per_ha": 45.0,
        "yield_unit": "tons",
    },
    "lettuce": {
        "npk": "15-10-10",
        "nitrogen_pct": 15.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Lettuce Nitrogen NPK 15-10-10",
        "common_pests": "Aphids, Loopers, Armyworms, Thrips",
        "beneficial_insects": "Parasitic wasps, Ladybugs, Lacewings",
        "irrigation_method": "drip",
        "typical_area": 4.0,
        "region": "California",
        "timing_soil": "Year-round",
        "timing_plant": "Year-round",
        "timing_fertilize": "At planting + sidedress",
        "timing_irrigate": "Continuous",
        "timing_pest": "Throughout season",
        "timing_harvest": "50-70 days after planting",
        "yield_per_ha": 35.0,
        "yield_unit": "tons",
    },
    "carrots": {
        "npk": "5-10-10",
        "nitrogen_pct": 5.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Carrot Root NPK 5-10-10",
        "common_pests": "Carrot rust fly, Aphids, Wireworms, Nematodes",
        "beneficial_insects": "Parasitic wasps, Ground beetles, Rove beetles",
        "irrigation_method": "drip",
        "typical_area": 5.0,
        "region": "California",
        "timing_soil": "January - February",
        "timing_plant": "February - September",
        "timing_fertilize": "At planting + 30 days",
        "timing_irrigate": "Continuous",
        "timing_pest": "Throughout season",
        "timing_harvest": "70-80 days after planting",
        "yield_per_ha": 50.0,
        "yield_unit": "tons",
    },
    "onions": {
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Onion Balanced NPK 10-10-10",
        "common_pests": "Onion thrips, Onion maggot, Aphids, Nematodes",
        "beneficial_insects": "Minute pirate bugs, Parasitic wasps, Ladybugs",
        "irrigation_method": "drip",
        "typical_area": 6.0,
        "region": "California",
        "timing_soil": "September - October",
        "timing_plant": "October - January",
        "timing_fertilize": "November - March",
        "timing_irrigate": "November - May",
        "timing_pest": "December - April",
        "timing_harvest": "May - July",
        "yield_per_ha": 55.0,
        "yield_unit": "tons",
    },
    # FORAGE CROPS
    "hay_alfalfa": {
        "npk": "0-20-20",
        "nitrogen_pct": 0.0,  # Legume - fixes own nitrogen
        "phosphorus_pct": 20.0,
        "potassium_pct": 20.0,
        "commercial_name": "Alfalfa PK Blend 0-20-20",
        "common_pests": "Alfalfa weevil, Aphids, Spider mites, Armyworms",
        "beneficial_insects": "Parasitic wasps, Lady beetles, Lacewings",
        "irrigation_method": "flood",
        "typical_area": 25.0,
        "region": "California",
        "timing_soil": "August - September",
        "timing_plant": "September - October",
        "timing_fertilize": "At planting + annually",
        "timing_irrigate": "Year-round",
        "timing_pest": "March - October",
        "timing_harvest": "Multiple (4-8 cuttings)",
        "yield_per_ha": 20.0,
        "yield_unit": "tons",
    },
    # LEGUME CROPS
    "peanuts": {
        "npk": "0-10-30",
        "nitrogen_pct": 0.0,  # Legume - fixes own nitrogen
        "phosphorus_pct": 10.0,
        "potassium_pct": 30.0,
        "commercial_name": "Peanut PK Blend 0-10-30",
        "common_pests": "Thrips, Spider mites, Corn earworm, Lesser cornstalk borer",
        "beneficial_insects": "Ground beetles, Parasitic wasps, Spiders",
        "irrigation_method": "center_pivot",
        "typical_area": 20.0,
        "region": "Southeast",
        "timing_soil": "March - April",
        "timing_plant": "April - May",
        "timing_fertilize": "At planting",
        "timing_irrigate": "June - September",
        "timing_pest": "May - August",
        "timing_harvest": "September - October",
        "yield_per_ha": 4.5,
        "yield_unit": "tons",
    },
    # OILSEED CROPS
    "sunflowers": {
        "npk": "10-20-20",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 20.0,
        "potassium_pct": 20.0,
        "commercial_name": "Sunflower Blend NPK 10-20-20",
        "common_pests": "Sunflower moth, Aphids, Stem weevil, Birds",
        "beneficial_insects": "Parasitic wasps, Lady beetles, Lacewings",
        "irrigation_method": "drip",
        "typical_area": 30.0,
        "region": "Midwest",
        "timing_soil": "April - May",
        "timing_plant": "May - June",
        "timing_fertilize": "At planting",
        "timing_irrigate": "July - August",
        "timing_pest": "June - August",
        "timing_harvest": "September - October",
        "yield_per_ha": 2.5,
        "yield_unit": "tons",
    },
    # FIBER CROPS
    "cotton": {
        "npk": "12-6-6",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 6.0,
        "potassium_pct": 6.0,
        "commercial_name": "Cotton Special NPK 12-6-6",
        "common_pests": "Boll weevil, Bollworm, Aphids, Spider mites, Whiteflies",
        "beneficial_insects": "Parasitic wasps, Lacewings, Big-eyed bugs",
        "irrigation_method": "furrow",
        "typical_area": 30.0,
        "region": "California",
        "timing_soil": "February - March",
        "timing_plant": "April - May",
        "timing_fertilize": "May - July",
        "timing_irrigate": "May - September",
        "timing_pest": "June - September",
        "timing_harvest": "September - November",
        "yield_per_ha": 2.0,
        "yield_unit": "bales",
    },
}


# =============================================================================
# SECTION 2: EVENT TYPE BUILDER FUNCTIONS
# =============================================================================


def build_soil_event_fields(
    subtype="ST",
    area=10.0,
    area_unit="ha",
    working_depth=20.0,
    depth_unit="cm",
    soil_texture="loam",
    soil_moisture="moderate",
    fuel_consumed=15.0,
    fuel_unit="L",
    fuel_type="diesel",
    equipment_hours=3.0,
    efficiency="normal",
    observation="Soil preparation and conditioning",
    soil_ph=None,
    organic_matter_pct=None,
):
    """
    Build complete backend_event_fields for SoilManagementEvent (backend_event_type=5)

    Subtypes: ST (Soil Testing), PA (Soil Preparation/Amendment), OM (Organic Matter),
              CC (Cover Crop), TI (Tillage), CO (Compaction)
    """
    return {
        "type": subtype,
        "observation": observation,
        "area_covered": area,
        "area_unit": area_unit,
        "working_depth": working_depth,
        "depth_unit": depth_unit,
        "soil_texture": soil_texture,
        "soil_moisture": soil_moisture,
        "soil_ph": soil_ph,
        "organic_matter_percentage": organic_matter_pct,
        "fuel_consumed": fuel_consumed,
        "fuel_unit": fuel_unit,
        "fuel_type": fuel_type,
        "equipment_hours": equipment_hours,
        "production_efficiency": efficiency,
        "equipment_used": "tractor_cultivator",
    }


def build_production_event_fields(
    subtype="PL",
    area=10.0,
    area_unit="ha",
    yield_quantity=None,
    yield_unit="tons",
    fuel_consumed=8.0,
    fuel_unit="L",
    fuel_type="diesel",
    equipment_hours=4.0,
    efficiency="normal",
    observation="Production operation",
    seeds_source="commercial",
    water_source="well_groundwater",
    irrigation_method="drip",
    irrigation_depth=2.0,
    irrigation_depth_unit="inches",
    transportation_distance=None,
    transportation_unit="km",
    equipment_type=None,
    equipment_operation_type=None,
):
    """
    Build complete backend_event_fields for ProductionEvent (backend_event_type=1)

    CORRECT backend constants from history/constants.py:
    WEATHER=0, PRODUCTION=1, CHEMICAL=2, GENERAL=3, EQUIPMENT=4, SOIL=5, PEST=6, BUSINESS=7

    Subtypes: PL (Planting), HA (Harvest), IR (Irrigation), PR (Pruning),
              TR (Transplanting), CU (Cultivation), TH (Thinning), EM (Equipment/Maintenance)
    """
    fields = {
        "type": subtype,
        "observation": observation,
        "area_covered": area,
        "area_unit": area_unit,
        "fuel_consumed": fuel_consumed,
        "fuel_unit": fuel_unit,
        "fuel_type": fuel_type,
        "equipment_hours": equipment_hours,
        "production_efficiency": efficiency,
    }

    # Subtype-specific fields
    if subtype == "PL":
        fields["seeds_source"] = seeds_source
    elif subtype == "HA":
        fields["yield_quantity"] = yield_quantity
        fields["yield_unit"] = yield_unit
        fields["transportation_distance"] = transportation_distance
        fields["transportation_unit"] = transportation_unit
    elif subtype == "IR":
        fields["water_source"] = water_source
        fields["irrigation_method"] = irrigation_method
        fields["irrigation_depth"] = irrigation_depth
        fields["irrigation_depth_unit"] = irrigation_depth_unit
    elif subtype == "EM":
        fields["equipment_type"] = equipment_type or "tractor"
        fields["equipment_operation_type"] = equipment_operation_type or "routine_maintenance"

    return fields


def build_chemical_event_fields(
    subtype="FE",
    chemical_subtype="synthetic_fertilizer",
    commercial_name="NPK Fertilizer 10-10-10",
    concentration="10-10-10",
    volume=200.0,
    volume_unit="kg",
    area=10.0,
    area_unit="ha",
    application_method="broadcast",
    nitrogen_pct=10.0,
    phosphorus_pct=10.0,
    potassium_pct=10.0,
    fuel_type="diesel",
    fuel_consumed=6.0,
    fuel_unit="L",
    organic_approved="not_organic",
    weather_conditions="calm_dry",
    application_timing="spring",
    target_pest_disease=None,
    observation="Chemical application",
    restricted_use_pesticide=False,
    applicator_name=None,
    rei_hours=None,
    phi_days=None,
):
    """
    Build complete backend_event_fields for ChemicalEvent (backend_event_type=2)

    CORRECT backend constants from history/constants.py:
    WEATHER=0, PRODUCTION=1, CHEMICAL=2, GENERAL=3, EQUIPMENT=4, SOIL=5, PEST=6, BUSINESS=7

    Subtypes: FE (Fertilizer), PE (Pesticide), HE (Herbicide), FU (Fungicide)
    """
    fields = {
        "type": subtype,
        "chemical_subtype": chemical_subtype,
        "commercial_name": commercial_name,
        "concentration": concentration,
        "volume": volume,
        "volume_unit": volume_unit,
        "area": area,
        "area_unit": area_unit,
        "way_of_application": application_method,
        "application_method_structured": application_method,
        "application_fuel_type": fuel_type,
        "application_fuel_consumed": fuel_consumed,
        "application_fuel_unit": fuel_unit,
        "organic_approved": organic_approved,
        "weather_conditions": weather_conditions,
        "application_timing": application_timing,
        "time_period": application_timing,
        "observation": observation,
    }

    # Fertilizer-specific fields
    if subtype == "FE":
        fields["nitrogen_percentage"] = nitrogen_pct
        fields["phosphorus_percentage"] = phosphorus_pct
        fields["potassium_percentage"] = potassium_pct

    # Pesticide/Herbicide/Fungicide-specific fields
    if subtype in ["PE", "HE", "FU"]:
        fields["target_pest_disease"] = target_pest_disease
        fields["restricted_use_pesticide"] = restricted_use_pesticide
        fields["applicator_name"] = applicator_name
        fields["rei_hours"] = rei_hours
        fields["phi_days"] = phi_days

    return fields


def build_pest_event_fields(
    subtype="SC",
    pest_species="General pests",
    pest_pressure_level="low",
    beneficial_species=None,
    release_quantity=None,
    ipm_strategy="Integrated pest management program",
    beneficial_insects_used="no",
    chemical_free_period_days=None,
    action_threshold_met=False,
    trap_count=None,
    damage_percentage=None,
    economic_threshold_met=False,
    weather_conditions="calm_dry",
    action_recommended=None,
    observation="Pest management activity",
    field_area=5.0,
    travel_distance=1.5,
    time_spent=2.0,
    crop_growth_stage="vegetative",
):
    """
    Build complete backend_event_fields for PestManagementEvent (backend_event_type=6)

    Subtypes: SC (Scouting), BR (Beneficial Release), TM (Trap Monitoring),
              PI (Physical Intervention), TA (Threshold Assessment), IP (IPM Implementation)
    """
    return {
        "type": subtype,
        "pest_species": pest_species,
        "pest_pressure_level": pest_pressure_level,
        "beneficial_species": beneficial_species,
        "release_quantity": release_quantity,
        "ipm_strategy": ipm_strategy,
        "beneficial_insects_used": beneficial_insects_used,
        "chemical_free_period_days": chemical_free_period_days,
        "action_threshold_met": action_threshold_met,
        "trap_count": trap_count,
        "damage_percentage": damage_percentage,
        "economic_threshold_met": economic_threshold_met,
        "weather_conditions": weather_conditions,
        "action_recommended": action_recommended,
        "observation": observation,
        "extra_data": {
            "field_area_hectares": field_area,
            "travel_distance_km": travel_distance,
            "time_spent_hours": time_spent,
            "crop_growth_stage": crop_growth_stage,
        },
    }


def build_business_event_fields(
    subtype="CE",
    name="Certification",
    business_type="certification",
    certification_type="organic_usda",
    carbon_credits_earned=None,
    carbon_credits_unit="tCO2e",
    verification_status="verified",
    sustainability_practice=None,
    verified_certifier_name=None,
    observation="Business activity",
):
    """
    Build complete backend_event_fields for BusinessEvent (backend_event_type=7)

    Subtypes: CE (Certification), CM (Compliance), IN (Inspection)
    """
    return {
        "type": subtype,
        "name": name,
        "business_type": business_type,
        "certification_type": certification_type,
        "carbon_credits_earned": carbon_credits_earned,
        "carbon_credits_unit": carbon_credits_unit,
        "verification_status": verification_status,
        "sustainability_practice": sustainability_practice,
        "verified_certifier_name": verified_certifier_name,
        "observation": observation,
    }


def build_weather_event_fields(
    subtype="FR",
    observation="Weather event recorded",
):
    """
    Build complete backend_event_fields for WeatherEvent (backend_event_type=0)

    Subtypes: FR (Frost), DR (Drought), HL (Hail), HT (Heat),
              TS (Storm), HW (High Wind), HH (High Humidity), LH (Low Humidity)
    """
    return {
        "type": subtype,
        "observation": observation,
        "extra_data": {},
    }


def build_general_event_fields(
    subtype="inspection",
    name="General Activity",
    duration_hours=2.0,
    participants=1,
    observation="General farm activity",
):
    """
    Build complete backend_event_fields for GeneralEvent (backend_event_type=3)

    Subtypes: maintenance, planning, training, documentation, inspection,
              meeting, community, other
    """
    return {
        "type": subtype,
        "name": name,
        "duration_hours": duration_hours,
        "participants": participants,
        "observation": observation,
    }


def build_equipment_event_fields(
    subtype="MN",
    equipment_name="Tractor",
    equipment_type="tractor",
    operation_type="routine_maintenance",
    fuel_consumed=5.0,
    fuel_unit="L",
    fuel_type="diesel",
    equipment_hours=2.0,
    observation="Equipment operation",
):
    """
    Build complete backend_event_fields for EquipmentEvent (backend_event_type=4)
    NOTE: Legacy - most equipment operations now use Production type EM

    Subtypes: MN (Maintenance), RE (Repair), CA (Calibration),
              FC (Fuel Consumption), BD (Breakdown), EI (Equipment Installation)
    """
    return {
        "type": subtype,
        "equipment_name": equipment_name,
        "equipment_type": equipment_type,
        "equipment_operation_type": operation_type,
        "fuel_consumed": fuel_consumed,
        "fuel_unit": fuel_unit,
        "fuel_type": fuel_type,
        "equipment_hours": equipment_hours,
        "observation": observation,
    }


# =============================================================================
# SECTION 3: EVENT TEMPLATE GENERATORS BY CROP CATEGORY
# =============================================================================


def get_tree_crop_events(crop_slug, crop_data):
    """Generate events for tree crops (citrus, apples, grapes, avocados, almonds)"""
    return [
        # 1. Winter Pruning
        {
            "name": "Winter Pruning",
            "event_type": "pruning",
            "description": "Dormant season pruning for tree structure and health",
            "timing": "December - February",
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 180.0,
            "carbon_impact": 45.0,
            "labor_hours": 6.0,
            "typical_duration": "3-5 days",
            "efficiency_tips": "Proper pruning increases fruit quality and reduces disease",
            "sustainability_score": 9,
            "qr_visibility": "low",
            "consumer_message": "Expert tree care for healthy fruit",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 1,
            "backend_event_fields": build_production_event_fields(
                subtype="PR",
                area=crop_data["typical_area"],
                fuel_consumed=10.0,
                equipment_hours=6.0,
                observation=f"Winter pruning for {crop_slug} tree structure",
            ),
        },
        # 2. Soil Preparation
        {
            "name": "Soil Preparation",
            "event_type": "soil_management",
            "description": "Pre-season soil preparation and amendment",
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 120.0,
            "carbon_impact": 35.0,
            "labor_hours": 4.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Cover crops improve soil health naturally",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Sustainable soil management practices",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 2,
            "backend_event_fields": build_soil_event_fields(
                subtype="PA",
                area=crop_data["typical_area"],
                working_depth=25.0,
                fuel_consumed=12.0,
                equipment_hours=4.0,
                observation=f"Soil preparation for {crop_slug} orchard",
            ),
        },
        # 3. Spring Fertilization
        {
            "name": "Spring Fertilization",
            "event_type": "fertilization",
            "description": f"{crop_slug.title()}-specific nutrition for spring growth",
            "timing": crop_data["timing_fertilize"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 220.0,
            "carbon_impact": 125.0,
            "labor_hours": 2.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Soil testing optimizes nutrient application",
            "sustainability_score": 7,
            "qr_visibility": "medium",
            "consumer_message": f"Specialized {crop_slug} nutrition for quality fruit",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 3,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                chemical_subtype="synthetic_fertilizer",
                commercial_name=crop_data["commercial_name"],
                concentration=crop_data["npk"],
                volume=300.0,
                area=crop_data["typical_area"],
                nitrogen_pct=crop_data["nitrogen_pct"],
                phosphorus_pct=crop_data["phosphorus_pct"],
                potassium_pct=crop_data["potassium_pct"],
                application_method="broadcast",
                application_timing="spring",
                observation=f"Spring fertilization for {crop_slug}",
            ),
        },
        # 4. Irrigation Management
        {
            "name": "Irrigation Management",
            "event_type": "irrigation",
            "description": "Precision irrigation based on tree water needs",
            "timing": crop_data["timing_irrigate"],
            "frequency": "weekly",
            "carbon_category": "medium",
            "cost_estimate": 180.0,
            "carbon_impact": 78.0,
            "labor_hours": 2.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Micro-irrigation reduces water use by 30%",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Efficient water management",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 4,
            "backend_event_fields": build_production_event_fields(
                subtype="IR",
                area=crop_data["typical_area"],
                fuel_consumed=12.0,
                irrigation_method=crop_data["irrigation_method"],
                irrigation_depth=2.0,
                observation=f"Drip irrigation for {crop_slug} orchard",
            ),
        },
        # 5. Pest and Disease Management
        {
            "name": "Pest and Disease Management",
            "event_type": "pest_control",
            "description": f"Integrated approach for {crop_slug} pest control",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 160.0,
            "carbon_impact": 55.0,
            "labor_hours": 3.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "IPM reduces chemical treatments by 50%",
            "sustainability_score": 8,
            "qr_visibility": "high",
            "consumer_message": "Responsible crop protection using beneficial insects",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 5,
            "backend_event_fields": build_pest_event_fields(
                subtype="IP",
                pest_species=crop_data["common_pests"],
                pest_pressure_level="low",
                beneficial_species=crop_data["beneficial_insects"],
                release_quantity="500 per hectare",
                ipm_strategy=f"Integrated pest management targeting {crop_slug} pests with beneficial insects",
                beneficial_insects_used="yes",
                chemical_free_period_days=30,
                field_area=crop_data["typical_area"],
                observation=f"IPM implementation for {crop_slug}",
            ),
        },
        # 6. Harvest
        {
            "name": "Harvest",
            "event_type": "harvest",
            "description": "Careful harvest to maintain fruit quality",
            "timing": crop_data["timing_harvest"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 320.0,
            "carbon_impact": 95.0,
            "labor_hours": 12.0,
            "typical_duration": "5-10 days",
            "efficiency_tips": "Optimal timing preserves fruit quality and shelf life",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Carefully harvested premium fruit",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 6,
            "backend_event_fields": build_production_event_fields(
                subtype="HA",
                area=crop_data["typical_area"],
                yield_quantity=crop_data["yield_per_ha"],
                yield_unit=crop_data["yield_unit"],
                fuel_consumed=8.0,
                equipment_hours=12.0,
                transportation_distance=15.0,
                observation=f"Careful {crop_slug} harvest for premium quality",
            ),
        },
    ]


def get_grain_events(crop_slug, crop_data):
    """Generate events for grain crops (corn, wheat, soybeans, rice)"""
    return [
        # 1. Land Preparation
        {
            "name": "Land Preparation",
            "event_type": "soil_management",
            "description": "Field preparation including tillage and soil conditioning",
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 85.0,
            "carbon_impact": 35.0,
            "labor_hours": 3.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Consider no-till practices to reduce fuel consumption by 35%",
            "sustainability_score": 6,
            "qr_visibility": "medium",
            "consumer_message": "Sustainable soil preparation practices",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 1,
            "backend_event_fields": build_soil_event_fields(
                subtype="TI",
                area=crop_data["typical_area"],
                working_depth=20.0,
                fuel_consumed=25.0,
                equipment_hours=5.0,
                observation=f"Land preparation for {crop_slug} planting",
            ),
        },
        # 2. Planting
        {
            "name": "Planting",
            "event_type": "planting",
            "description": "Seed planting with appropriate spacing and depth",
            "timing": crop_data["timing_plant"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 120.0,
            "carbon_impact": 65.0,
            "labor_hours": 2.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Use precision planting for optimal seed placement",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Precision planting for optimal growth",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 2,
            "backend_event_fields": build_production_event_fields(
                subtype="PL",
                area=crop_data["typical_area"],
                fuel_consumed=15.0,
                equipment_hours=4.0,
                seeds_source="commercial",
                observation=f"Precision {crop_slug} planting operation",
            ),
        },
        # 3. Fertilizer Application
        {
            "name": "Fertilizer Application",
            "event_type": "fertilization",
            "description": "Application of nitrogen, phosphorus, and potassium fertilizers",
            "timing": crop_data["timing_fertilize"],
            "frequency": "seasonal",
            "carbon_category": "high",
            "cost_estimate": 250.0,
            "carbon_impact": 125.0,
            "labor_hours": 2.5,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Soil testing can reduce fertilizer needs by 20-30%",
            "sustainability_score": 6,
            "qr_visibility": "high",
            "consumer_message": "Precision nutrient management for sustainable growth",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 3,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                chemical_subtype="synthetic_fertilizer",
                commercial_name=crop_data["commercial_name"],
                concentration=crop_data["npk"],
                volume=250.0,
                area=crop_data["typical_area"],
                nitrogen_pct=crop_data["nitrogen_pct"],
                phosphorus_pct=crop_data["phosphorus_pct"],
                potassium_pct=crop_data["potassium_pct"],
                application_method="broadcast",
                application_timing="spring",
                observation=f"Fertilizer application for {crop_slug}",
            ),
        },
        # 4. Pest Management
        {
            "name": "Pest Management",
            "event_type": "pest_control",
            "description": f"Integrated pest management for {crop_slug}",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 95.0,
            "carbon_impact": 55.0,
            "labor_hours": 2.0,
            "typical_duration": "3-4 hours",
            "efficiency_tips": "IPM practices can reduce pesticide use by 40%",
            "sustainability_score": 7,
            "qr_visibility": "high",
            "consumer_message": "Responsible pest management practices",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 4,
            "backend_event_fields": build_pest_event_fields(
                subtype="SC",
                pest_species=crop_data["common_pests"],
                pest_pressure_level="medium",
                beneficial_species=crop_data["beneficial_insects"],
                ipm_strategy=f"Integrated pest management with scouting for {crop_slug}",
                beneficial_insects_used="no",
                field_area=crop_data["typical_area"],
                crop_growth_stage="vegetative",
                observation=f"Pest scouting for {crop_slug}",
            ),
        },
        # 5. Irrigation Management
        {
            "name": "Irrigation Management",
            "event_type": "irrigation",
            "description": "Water application based on crop needs and soil moisture",
            "timing": crop_data["timing_irrigate"],
            "frequency": "weekly",
            "carbon_category": "medium",
            "cost_estimate": 120.0,
            "carbon_impact": 78.0,
            "labor_hours": 1.5,
            "typical_duration": "2-3 hours setup",
            "efficiency_tips": "Smart irrigation controllers can save 25% energy",
            "sustainability_score": 8,
            "qr_visibility": "medium",
            "consumer_message": "Efficient water management systems",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 5,
            "backend_event_fields": build_production_event_fields(
                subtype="IR",
                area=crop_data["typical_area"],
                fuel_consumed=20.0,
                irrigation_method=crop_data["irrigation_method"],
                irrigation_depth=2.5,
                observation=f"Field irrigation for {crop_slug}",
            ),
        },
        # 6. Harvest
        {
            "name": "Harvest",
            "event_type": "harvest",
            "description": "Mechanical harvest and grain handling",
            "timing": crop_data["timing_harvest"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 180.0,
            "carbon_impact": 95.0,
            "labor_hours": 4.0,
            "typical_duration": "2-3 days",
            "efficiency_tips": "Optimize harvest timing for maximum yield and quality",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Efficient harvest practices",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 6,
            "backend_event_fields": build_production_event_fields(
                subtype="HA",
                area=crop_data["typical_area"],
                yield_quantity=crop_data["yield_per_ha"] * crop_data["typical_area"],
                yield_unit=crop_data["yield_unit"],
                fuel_consumed=25.0,
                equipment_hours=8.0,
                transportation_distance=20.0,
                observation=f"Mechanical {crop_slug} harvest",
            ),
        },
    ]


def get_vegetable_events(crop_slug, crop_data):
    """Generate events for vegetable crops (tomatoes, potatoes, lettuce, carrots, onions)"""
    return [
        # 1. Soil Preparation
        {
            "name": "Soil Preparation",
            "event_type": "soil_management",
            "description": "Intensive soil preparation including bed formation",
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 120.0,
            "carbon_impact": 35.0,
            "labor_hours": 4.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Cover crops can improve soil structure naturally",
            "sustainability_score": 7,
            "qr_visibility": "low",
            "consumer_message": "Sustainable soil management",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 1,
            "backend_event_fields": build_soil_event_fields(
                subtype="PA",
                area=crop_data["typical_area"],
                working_depth=25.0,
                fuel_consumed=15.0,
                equipment_hours=4.0,
                observation=f"Intensive soil preparation for {crop_slug}",
            ),
        },
        # 2. Transplanting/Seeding
        {
            "name": "Transplanting/Seeding",
            "event_type": "planting",
            "description": "Transplanting seedlings or direct seeding",
            "timing": crop_data["timing_plant"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 180.0,
            "carbon_impact": 65.0,
            "labor_hours": 6.0,
            "typical_duration": "2-3 days",
            "efficiency_tips": "Precision spacing optimizes plant development",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Careful planting for optimal growth",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 2,
            "backend_event_fields": build_production_event_fields(
                subtype="PL",
                area=crop_data["typical_area"],
                fuel_consumed=6.0,
                equipment_hours=6.0,
                seeds_source="commercial",
                observation=f"Transplanting/seeding {crop_slug}",
            ),
        },
        # 3. Drip Irrigation Setup
        {
            "name": "Drip Irrigation Setup",
            "event_type": "irrigation",
            "description": "Installation and management of drip irrigation systems",
            "timing": crop_data["timing_plant"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 200.0,
            "carbon_impact": 78.0,
            "labor_hours": 3.0,
            "typical_duration": "1 day",
            "efficiency_tips": "Drip systems can reduce water use by 40%",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Water-efficient irrigation technology",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 3,
            "backend_event_fields": build_production_event_fields(
                subtype="IR",
                area=crop_data["typical_area"],
                fuel_consumed=5.0,
                irrigation_method="drip",
                irrigation_depth=1.5,
                observation=f"Drip irrigation setup for {crop_slug}",
            ),
        },
        # 4. Fertilizer Program
        {
            "name": "Fertilizer Program",
            "event_type": "fertilization",
            "description": "Precision fertigation through drip system",
            "timing": crop_data["timing_fertilize"],
            "frequency": "weekly",
            "carbon_category": "high",
            "cost_estimate": 320.0,
            "carbon_impact": 125.0,
            "labor_hours": 2.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Fertigation reduces nutrient runoff by 50%",
            "sustainability_score": 8,
            "qr_visibility": "high",
            "consumer_message": "Precision nutrition management",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 4,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                chemical_subtype="synthetic_fertilizer",
                commercial_name=crop_data["commercial_name"],
                concentration=crop_data["npk"],
                volume=150.0,
                area=crop_data["typical_area"],
                nitrogen_pct=crop_data["nitrogen_pct"],
                phosphorus_pct=crop_data["phosphorus_pct"],
                potassium_pct=crop_data["potassium_pct"],
                application_method="fertigation",
                fuel_type="none",
                fuel_consumed=0.0,
                application_timing="growing_season",
                observation=f"Fertigation for {crop_slug}",
            ),
        },
        # 5. Integrated Pest Management
        {
            "name": "Integrated Pest Management",
            "event_type": "pest_control",
            "description": "IPM including beneficial insects and targeted treatments",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 150.0,
            "carbon_impact": 55.0,
            "labor_hours": 2.5,
            "typical_duration": "3-4 hours",
            "efficiency_tips": "Beneficial insects reduce pesticide needs by 60%",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "Natural pest control methods",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 5,
            "backend_event_fields": build_pest_event_fields(
                subtype="BR",
                pest_species=crop_data["common_pests"],
                pest_pressure_level="low",
                beneficial_species=crop_data["beneficial_insects"],
                release_quantity="1000 per hectare",
                ipm_strategy=f"Organic IPM with beneficial insect releases for {crop_slug}",
                beneficial_insects_used="yes",
                chemical_free_period_days=30,
                field_area=crop_data["typical_area"],
                crop_growth_stage="flowering",
                observation=f"Beneficial insect release for {crop_slug}",
            ),
        },
        # 6. Harvest
        {
            "name": "Harvest",
            "event_type": "harvest",
            "description": "Hand or mechanical harvest depending on crop",
            "timing": crop_data["timing_harvest"],
            "frequency": "seasonal",
            "carbon_category": "low",
            "cost_estimate": 280.0,
            "carbon_impact": 95.0,
            "labor_hours": 8.0,
            "typical_duration": "3-5 days",
            "efficiency_tips": "Optimal timing maximizes quality and shelf life",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Fresh, quality harvest",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 6,
            "backend_event_fields": build_production_event_fields(
                subtype="HA",
                area=crop_data["typical_area"],
                yield_quantity=crop_data["yield_per_ha"] * crop_data["typical_area"],
                yield_unit=crop_data["yield_unit"],
                fuel_consumed=8.0,
                equipment_hours=8.0,
                transportation_distance=10.0,
                observation=f"{crop_slug.title()} harvest operation",
            ),
        },
    ]


def get_berry_events(crop_slug, crop_data):
    """Generate events for berry crops (strawberries)"""
    return [
        # 1. Bed Preparation
        {
            "name": "Bed Preparation",
            "event_type": "soil_management",
            "description": "Raised bed formation and soil conditioning",
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 180.0,
            "carbon_impact": 35.0,
            "labor_hours": 5.0,
            "typical_duration": "2-3 days",
            "efficiency_tips": "Proper bed formation improves drainage and root health",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Optimal growing conditions",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 1,
            "backend_event_fields": build_soil_event_fields(
                subtype="PA",
                area=crop_data["typical_area"],
                working_depth=30.0,
                fuel_consumed=12.0,
                equipment_hours=5.0,
                observation=f"Raised bed formation for {crop_slug}",
            ),
        },
        # 2. Plant Installation
        {
            "name": "Plant Installation",
            "event_type": "planting",
            "description": f"Transplanting {crop_slug} plants with precise spacing",
            "timing": crop_data["timing_plant"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 320.0,
            "carbon_impact": 65.0,
            "labor_hours": 12.0,
            "typical_duration": "3-5 days",
            "efficiency_tips": "Proper spacing ensures optimal plant development",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Expert planting for premium berries",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 2,
            "backend_event_fields": build_production_event_fields(
                subtype="PL",
                area=crop_data["typical_area"],
                fuel_consumed=4.0,
                equipment_hours=12.0,
                seeds_source="certified_organic",
                observation=f"Transplanting {crop_slug} plants",
            ),
        },
        # 3. Fertigation System
        {
            "name": "Fertigation System",
            "event_type": "fertilization",
            "description": "Precision nutrition through drip irrigation",
            "timing": crop_data["timing_fertilize"],
            "frequency": "weekly",
            "carbon_category": "high",
            "cost_estimate": 280.0,
            "carbon_impact": 125.0,
            "labor_hours": 1.5,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Continuous fertigation optimizes plant nutrition",
            "sustainability_score": 8,
            "qr_visibility": "medium",
            "consumer_message": "Precision nutrition for quality berries",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 3,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                chemical_subtype="synthetic_fertilizer",
                commercial_name=crop_data["commercial_name"],
                concentration=crop_data["npk"],
                volume=100.0,
                area=crop_data["typical_area"],
                nitrogen_pct=crop_data["nitrogen_pct"],
                phosphorus_pct=crop_data["phosphorus_pct"],
                potassium_pct=crop_data["potassium_pct"],
                application_method="fertigation",
                fuel_type="none",
                fuel_consumed=0.0,
                application_timing="growing_season",
                observation=f"Fertigation for {crop_slug}",
            ),
        },
        # 4. Pest Management
        {
            "name": "Pest Management",
            "event_type": "pest_control",
            "description": "Integrated pest management for berry production",
            "timing": crop_data["timing_pest"],
            "frequency": "weekly",
            "carbon_category": "medium",
            "cost_estimate": 140.0,
            "carbon_impact": 55.0,
            "labor_hours": 2.0,
            "typical_duration": "3-4 hours",
            "efficiency_tips": "Predatory mites reduce spider mite damage by 80%",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "Natural pest control for healthier berries",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 4,
            "backend_event_fields": build_pest_event_fields(
                subtype="BR",
                pest_species=crop_data["common_pests"],
                pest_pressure_level="low",
                beneficial_species=crop_data["beneficial_insects"],
                release_quantity="2000 per hectare",
                ipm_strategy=f"Biological control for {crop_slug} with predatory mites",
                beneficial_insects_used="yes",
                chemical_free_period_days=21,
                field_area=crop_data["typical_area"],
                crop_growth_stage="fruiting",
                observation=f"Beneficial release for {crop_slug}",
            ),
        },
        # 5. Irrigation Management
        {
            "name": "Irrigation Management",
            "event_type": "irrigation",
            "description": "Daily drip irrigation management",
            "timing": crop_data["timing_irrigate"],
            "frequency": "daily",
            "carbon_category": "low",
            "cost_estimate": 150.0,
            "carbon_impact": 78.0,
            "labor_hours": 1.0,
            "typical_duration": "1-2 hours",
            "efficiency_tips": "Soil moisture sensors optimize water use",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Precision water management",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 5,
            "backend_event_fields": build_production_event_fields(
                subtype="IR",
                area=crop_data["typical_area"],
                fuel_consumed=3.0,
                irrigation_method="drip",
                irrigation_depth=0.5,
                observation=f"Precision irrigation for {crop_slug}",
            ),
        },
        # 6. Harvest
        {
            "name": "Harvest",
            "event_type": "harvest",
            "description": "Hand harvest for premium quality",
            "timing": crop_data["timing_harvest"],
            "frequency": "continuous",
            "carbon_category": "low",
            "cost_estimate": 450.0,
            "carbon_impact": 95.0,
            "labor_hours": 20.0,
            "typical_duration": "6-8 months",
            "efficiency_tips": "Multiple harvests throughout the season",
            "sustainability_score": 9,
            "qr_visibility": "low",
            "consumer_message": "Hand-picked premium berries",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 6,
            "backend_event_fields": build_production_event_fields(
                subtype="HA",
                area=crop_data["typical_area"],
                yield_quantity=crop_data["yield_per_ha"] * crop_data["typical_area"],
                yield_unit=crop_data["yield_unit"],
                fuel_consumed=5.0,
                equipment_hours=20.0,
                transportation_distance=5.0,
                observation=f"Hand harvest of premium {crop_slug}",
            ),
        },
    ]


def get_fiber_events(crop_slug, crop_data):
    """Generate events for fiber crops (cotton)"""
    return [
        # 1. Land Preparation
        {
            "name": "Land Preparation",
            "event_type": "soil_management",
            "description": "Deep tillage and field preparation",
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 100.0,
            "carbon_impact": 35.0,
            "labor_hours": 4.0,
            "typical_duration": "2-3 days",
            "efficiency_tips": "Conservation tillage reduces erosion",
            "sustainability_score": 7,
            "qr_visibility": "low",
            "consumer_message": "Sustainable land management",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 1,
            "backend_event_fields": build_soil_event_fields(
                subtype="TI",
                area=crop_data["typical_area"],
                working_depth=25.0,
                fuel_consumed=30.0,
                equipment_hours=6.0,
                observation=f"Deep tillage for {crop_slug}",
            ),
        },
        # 2. Planting
        {
            "name": "Planting",
            "event_type": "planting",
            "description": "Precision planting of cotton seeds",
            "timing": crop_data["timing_plant"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 140.0,
            "carbon_impact": 65.0,
            "labor_hours": 3.0,
            "typical_duration": "2-3 days",
            "efficiency_tips": "Optimal plant population improves yields",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Precision planting",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 2,
            "backend_event_fields": build_production_event_fields(
                subtype="PL",
                area=crop_data["typical_area"],
                fuel_consumed=20.0,
                equipment_hours=5.0,
                seeds_source="commercial",
                observation=f"Precision {crop_slug} planting",
            ),
        },
        # 3. Fertilizer Application
        {
            "name": "Fertilizer Application",
            "event_type": "fertilization",
            "description": "Nitrogen-focused fertilization program",
            "timing": crop_data["timing_fertilize"],
            "frequency": "seasonal",
            "carbon_category": "high",
            "cost_estimate": 220.0,
            "carbon_impact": 125.0,
            "labor_hours": 2.5,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Split applications improve nitrogen efficiency",
            "sustainability_score": 6,
            "qr_visibility": "medium",
            "consumer_message": "Optimized nutrient management",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 3,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                chemical_subtype="synthetic_fertilizer",
                commercial_name=crop_data["commercial_name"],
                concentration=crop_data["npk"],
                volume=200.0,
                area=crop_data["typical_area"],
                nitrogen_pct=crop_data["nitrogen_pct"],
                phosphorus_pct=crop_data["phosphorus_pct"],
                potassium_pct=crop_data["potassium_pct"],
                application_method="broadcast",
                application_timing="spring",
                observation=f"Fertilizer application for {crop_slug}",
            ),
        },
        # 4. Pest Management
        {
            "name": "Pest Management",
            "event_type": "pest_control",
            "description": f"IPM program for {crop_slug}",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 180.0,
            "carbon_impact": 55.0,
            "labor_hours": 3.0,
            "typical_duration": "4-5 hours",
            "efficiency_tips": "Bt cotton reduces insecticide needs",
            "sustainability_score": 7,
            "qr_visibility": "high",
            "consumer_message": "Responsible pest management",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 4,
            "backend_event_fields": build_pest_event_fields(
                subtype="SC",
                pest_species=crop_data["common_pests"],
                pest_pressure_level="medium",
                beneficial_species=crop_data["beneficial_insects"],
                ipm_strategy=f"Integrated pest management for {crop_slug} with scouting",
                beneficial_insects_used="no",
                field_area=crop_data["typical_area"],
                crop_growth_stage="flowering",
                observation=f"Pest scouting for {crop_slug}",
            ),
        },
        # 5. Irrigation
        {
            "name": "Irrigation",
            "event_type": "irrigation",
            "description": "Furrow irrigation management",
            "timing": crop_data["timing_irrigate"],
            "frequency": "bi-weekly",
            "carbon_category": "medium",
            "cost_estimate": 160.0,
            "carbon_impact": 78.0,
            "labor_hours": 2.0,
            "typical_duration": "3-4 hours",
            "efficiency_tips": "Deficit irrigation during maturation improves fiber quality",
            "sustainability_score": 7,
            "qr_visibility": "medium",
            "consumer_message": "Efficient water use",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 5,
            "backend_event_fields": build_production_event_fields(
                subtype="IR",
                area=crop_data["typical_area"],
                fuel_consumed=25.0,
                irrigation_method="furrow",
                irrigation_depth=3.0,
                observation=f"Furrow irrigation for {crop_slug}",
            ),
        },
        # 6. Harvest
        {
            "name": "Harvest",
            "event_type": "harvest",
            "description": "Mechanical cotton harvest",
            "timing": crop_data["timing_harvest"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 250.0,
            "carbon_impact": 95.0,
            "labor_hours": 6.0,
            "typical_duration": "3-5 days",
            "efficiency_tips": "Proper defoliation timing improves harvest efficiency",
            "sustainability_score": 7,
            "qr_visibility": "low",
            "consumer_message": "Efficient harvest",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 6,
            "backend_event_fields": build_production_event_fields(
                subtype="HA",
                area=crop_data["typical_area"],
                yield_quantity=crop_data["yield_per_ha"] * crop_data["typical_area"],
                yield_unit=crop_data["yield_unit"],
                fuel_consumed=35.0,
                equipment_hours=10.0,
                transportation_distance=30.0,
                observation=f"Mechanical {crop_slug} harvest",
            ),
        },
    ]


# =============================================================================
# SECTION 4: COMMAND CLASS
# =============================================================================


class Command(BaseCommand):
    help = "Create comprehensive production templates V2 with complete backend_event_fields for ALL event types"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate without creating records",
        )
        parser.add_argument(
            "--crop",
            type=str,
            help="Create for specific crop only (e.g., avocados, corn)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Delete existing templates and recreate",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        specific_crop = options.get("crop")
        force = options.get("force", False)

        self.stdout.write(
            self.style.NOTICE(
                f"\n{'='*60}\n" f"Production Templates V2 - Complete Field Specifications\n" f"{'='*60}\n"
            )
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No records will be created\n"))

        if force:
            self.stdout.write(self.style.WARNING("FORCE MODE - Existing templates will be deleted\n"))

        # Get crop types
        crop_types = CropType.objects.filter(is_active=True)

        if specific_crop:
            crop_types = crop_types.filter(slug=specific_crop)
            if not crop_types.exists():
                self.stdout.write(self.style.ERROR(f"Crop type '{specific_crop}' not found"))
                return

        if not crop_types.exists():
            self.stdout.write(self.style.ERROR("No crop types found. Run populate_usda_crop_types first."))
            return

        created_templates = 0
        created_events = 0
        skipped_templates = 0

        with transaction.atomic():
            for crop_type in crop_types:
                crop_slug = crop_type.slug

                # Check if we have customization data for this crop
                if crop_slug not in CROP_CUSTOMIZATIONS:
                    self.stdout.write(self.style.WARNING(f"  No customization data for {crop_slug}, using defaults"))
                    crop_data = CROP_CUSTOMIZATIONS.get("corn")  # Use corn as fallback
                else:
                    crop_data = CROP_CUSTOMIZATIONS[crop_slug]

                template_slug = f"{crop_slug}_conventional_v2"

                # Handle force mode
                if force:
                    existing = ProductionTemplate.objects.filter(slug=template_slug)
                    if existing.exists():
                        if not dry_run:
                            existing.delete()
                            self.stdout.write(f"  Deleted existing template: {template_slug}")

                # Create template
                template_data = {
                    "name": f"{crop_type.name} - Conventional Production V2",
                    "farming_approach": "conventional",
                    "description": (
                        f"Comprehensive production practices for {crop_type.name.lower()} "
                        f"with complete event field specifications. California-focused defaults."
                    ),
                    "complexity_level": "intermediate",
                    "estimated_setup_time": 8,
                    "projected_emissions_reduction": 15.0,
                    "projected_cost_change": -5.0,
                    "projected_yield_impact": 0.0,
                    "premium_pricing_potential": crop_type.sustainable_premium,
                    "market_demand": "high",
                    "usage_count": 0,
                    "success_rate": 85.0,
                    "usda_reviewed": True,
                    "compliance_notes": (
                        f"V2 template with complete backend_event_fields. "
                        f"Based on USDA best practices for {crop_type.name.lower()}. "
                        f"Region: {crop_data.get('region', 'California')}"
                    ),
                    "is_active": True,
                }

                if dry_run:
                    self.stdout.write(f"\n  [DRY RUN] Would create template: {template_data['name']}")
                    created_templates += 1
                else:
                    template, created = ProductionTemplate.objects.get_or_create(
                        crop_type=crop_type,
                        slug=template_slug,
                        defaults=template_data,
                    )

                    if created:
                        created_templates += 1
                        self.stdout.write(self.style.SUCCESS(f"\n  Created template: {template.name}"))
                    else:
                        skipped_templates += 1
                        self.stdout.write(f"\n  Template exists: {template.name}")
                        continue

                # Get events based on crop category
                if crop_type.category in ["tree_fruit", "tree_nut"]:
                    events_data = get_tree_crop_events(crop_slug, crop_data)
                elif crop_type.category in ["grain", "oilseed", "legume"]:
                    events_data = get_grain_events(crop_slug, crop_data)
                elif crop_type.category == "vegetable":
                    events_data = get_vegetable_events(crop_slug, crop_data)
                elif crop_type.category == "berry":
                    events_data = get_berry_events(crop_slug, crop_data)
                elif crop_type.category == "forage":
                    events_data = get_fiber_events(crop_slug, crop_data)  # Similar pattern
                else:  # fiber (cotton), other
                    events_data = get_fiber_events(crop_slug, crop_data)

                # Create event templates
                for event_data in events_data:
                    if dry_run:
                        self.stdout.write(
                            f"    [DRY RUN] Would create event: {event_data['name']} "
                            f"(type={event_data['backend_event_type']}, "
                            f"subtype={event_data['backend_event_fields'].get('type', 'N/A')})"
                        )
                        created_events += 1
                    else:
                        event_data["production_template"] = template
                        event, event_created = EventTemplate.objects.get_or_create(
                            production_template=template,
                            name=event_data["name"],
                            defaults=event_data,
                        )
                        if event_created:
                            created_events += 1
                            self.stdout.write(
                                f"    Event: {event.name} "
                                f"(type={event.backend_event_type}, "
                                f"fields={len(event.backend_event_fields or {})})"
                            )

        # Summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*60}\n"
                f"V2 Production Templates Creation Complete!\n"
                f"{'='*60}\n"
                f"Created: {created_templates} production templates\n"
                f"Created: {created_events} event templates\n"
                f"Skipped: {skipped_templates} existing templates\n"
            )
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN COMPLETE - Run without --dry-run to create records"))
