"""
V2 Production Template Seed Command

Creates comprehensive production templates with COMPLETE backend_event_fields for ALL event types.
Every form field has smart defaults - no empty fields.

Event Types (from history/constants.py):
- 0: Weather (WeatherEvent)
- 1: Production (ProductionEvent) - Planting, Harvest, Irrigation, Pruning, Equipment Maintenance, etc.
- 2: Chemical (ChemicalEvent) - Fertilizers, Pesticides, Herbicides, Fungicides
- 3: General (GeneralEvent)
- 4: Equipment (EquipmentEvent) - Legacy, merged to Production EM subtype
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
# SECTION 1: CROP-SPECIFIC CUSTOMIZATIONS (22 Crops - California Focus)
# =============================================================================

CROP_CUSTOMIZATIONS = {
    # TREE CROPS - California Central Valley Focus
    "avocados": {
        # Primary fertilizer - YaraMila Complex (from demo avocado finished #2)
        "npk": "12-11-18",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 11.0,
        "potassium_pct": 18.0,
        "commercial_name": "YaraMila Complex 12-11-18",
        # Secondary fertigation (from demo avocado finished #7)
        "secondary_fertilizer": "Fertiactyl GZ 13-0-5",
        "secondary_npk": "13-0-5",
        "secondary_nitrogen_pct": 13.0,
        "secondary_phosphorus_pct": 0.0,
        "secondary_potassium_pct": 5.0,
        # Slow-release option (from demo avocado current #1)
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "slow_release_npk": "15-9-12",
        # Fungicides (from demo avocado finished #4, current #3, #7)
        "primary_fungicide": "Ridomil Gold SL (mefenoxam)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Phytophthora cinnamomi root rot",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "copper_target": "Anthracnose (Colletotrichum gloeosporioides)",
        # Herbicide (from demo avocado finished #14)
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        # Pest management (from demo)
        "common_pests": "Persea mite (Oligonychus perseae), Avocado thrips (Scirtothrips perseae)",
        "beneficial_insects": "Galendromus helveolus (predatory mite)",
        "primary_pest_species": "Persea mite (Oligonychus perseae), Avocado thrips (Scirtothrips perseae)",
        # Certification (from demo avocado finished #13)
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "certification_type": "global_gap",
        # Farm profile - Ventura County, California
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "sandy_loam",
        "typical_area": 15.0,
        "region": "Ventura County, California",
        "timing_soil": "October - November",
        "timing_plant": "March - April",
        "timing_fertilize": "February - March",
        "timing_irrigate": "Year-round",
        "timing_pest": "March - October",
        "timing_harvest": "February - September",
        "yield_per_ha": 9.0,
        "yield_unit": "tons",
    },
    "citrus_oranges": {
        # Primary fertilizer - Haifa Multi-K (from demo orange finished #2)
        "npk": "13-0-46",
        "nitrogen_pct": 13.0,
        "phosphorus_pct": 0.0,
        "potassium_pct": 46.0,
        "commercial_name": "Haifa Multi-K 13-0-46",
        # Secondary fertilizers (from demo orange current #1, finished #8)
        "secondary_fertilizer": "JR Peters Citrus FeEd 8-24-12",
        "secondary_npk": "8-24-12",
        "secondary_nitrogen_pct": 8.0,
        "secondary_phosphorus_pct": 24.0,
        "secondary_potassium_pct": 12.0,
        "tertiary_fertilizer": "UAN-32 (32-0-0)",
        "tertiary_npk": "32-0-0",
        # Fungicide (from demo orange current #4)
        "primary_fungicide": "Microthiol Disperss (micronized sulfur)",
        "fungicide_subtype": "sulfur_fungicide",
        "fungicide_target": "Citrus rust mite, Powdery mildew",
        # Organic herbicide (from demo orange finished #16)
        "herbicide": "Suppress EC (caprylic/capric acid)",
        "herbicide_subtype": "organic_herbicide",
        # Organic pesticide (from demo orange finished #17)
        "organic_pesticide": "Surround WP (kaolin clay)",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Sunburn protection, Pest barrier",
        # Synthetic pesticide (from demo orange finished #4)
        "synthetic_pesticide": "Delegate WG (spinetoram)",
        "synthetic_pesticide_target": "Citrus leafminer (Phyllocnistis citrella)",
        # Pest management (from demo)
        "common_pests": "Citrus leafminer (Phyllocnistis citrella), California red scale (Aonidiella aurantii)",
        "beneficial_insects": "Aphytis melinus (parasitic wasp)",
        "primary_pest_species": "Citrus leafminer (Phyllocnistis citrella), California red scale (Aonidiella aurantii)",
        "beneficial_release_quantity": "50,000/ha",
        # Certification (from demo orange finished #15)
        "certification_standard": "Primus GFS v4.0",
        "certification_body": "Primus Auditing Ops (Azzule Systems)",
        "certification_type": "sustainable_agriculture",
        # Farm profile - Central Valley, California
        "irrigation_method": "micro_sprinkler",
        "water_source": "irrigation_canal",
        "soil_type": "clay_loam",
        "typical_area": 20.0,
        "region": "Central Valley, California",
        "timing_soil": "January - February",
        "timing_plant": "March - April",
        "timing_fertilize": "February - March",
        "timing_irrigate": "March - October",
        "timing_pest": "April - September",
        "timing_harvest": "November - June",
        "yield_per_ha": 28.0,
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
    # TREE NUTS
    "walnuts": {
        "npk": "14-14-14",
        "nitrogen_pct": 14.0,
        "phosphorus_pct": 14.0,
        "potassium_pct": 14.0,
        "commercial_name": "Walnut Orchard NPK 14-14-14",
        "common_pests": "Codling moth, Walnut husk fly, Aphids, Spider mites, Walnut blight",
        "beneficial_insects": "Trichogramma wasps, Lacewings, Predatory mites",
        "irrigation_method": "micro_sprinkler",
        "typical_area": 20.0,
        "region": "Central Valley, California",
        "timing_soil": "November - December",
        "timing_plant": "January - February",
        "timing_fertilize": "March - May",
        "timing_irrigate": "April - October",
        "timing_pest": "April - September",
        "timing_harvest": "September - November",
        "yield_per_ha": 4.5,
        "yield_unit": "tons",
    },
    # STONE FRUIT
    "stone_fruit": {
        "npk": "12-6-12",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 6.0,
        "potassium_pct": 12.0,
        "commercial_name": "Stone Fruit Special NPK 12-6-12",
        "common_pests": "Oriental fruit moth, Peach twig borer, Brown rot, Aphids, Scale insects",
        "beneficial_insects": "Parasitic wasps, Predatory mites, Lacewings",
        "irrigation_method": "drip",
        "typical_area": 15.0,
        "region": "San Joaquin Valley, California",
        "timing_soil": "November - December",
        "timing_plant": "January - February",
        "timing_fertilize": "February - April",
        "timing_irrigate": "April - September",
        "timing_pest": "March - August",
        "timing_harvest": "May - September",
        "yield_per_ha": 20.0,
        "yield_unit": "tons",
    },
    # MIXED VEGETABLES
    "mixed_vegetables": {
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Vegetable Garden NPK 10-10-10",
        "common_pests": "Aphids, Whiteflies, Flea beetles, Hornworms, Cutworms",
        "beneficial_insects": "Lady beetles, Parasitic wasps, Ground beetles, Lacewings",
        "irrigation_method": "drip",
        "typical_area": 5.0,
        "region": "California",
        "timing_soil": "February - March",
        "timing_plant": "March - May",
        "timing_fertilize": "At planting + monthly",
        "timing_irrigate": "Year-round",
        "timing_pest": "April - October",
        "timing_harvest": "May - November",
        "yield_per_ha": 30.0,
        "yield_unit": "tons",
    },
}

# Alias: DB has both "avocado" (singular) and "avocados" (plural) slugs
CROP_CUSTOMIZATIONS["avocado"] = CROP_CUSTOMIZATIONS["avocados"]


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
    amendment_type=None,
    amendment_amount=None,
    equipment_used="tractor_cultivator",
    extra_data=None,
):
    """
    Build complete backend_event_fields for SoilManagementEvent (backend_event_type=5)

    Subtypes: ST (Soil Testing), PA (pH Adjustment/Amendment), OM (Organic Matter),
              CC (Cover Crop), TI (Tillage), CO (Composting)
    """
    fields = {
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
        "equipment_used": equipment_used,
    }

    if amendment_type:
        fields["amendment_type"] = amendment_type
    if amendment_amount:
        fields["amendment_amount"] = amendment_amount
    if extra_data:
        fields["extra_data"] = extra_data

    return fields


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
    extra_data=None,
):
    """
    Build complete backend_event_fields for ProductionEvent (backend_event_type=1)

    CORRECT backend constants from history/constants.py:
    WEATHER=0, PRODUCTION=1, CHEMICAL=2, GENERAL=3, EQUIPMENT=4, SOIL=5, PEST=6, BUSINESS=7

    Subtypes: PL (Planting), HA (Harvest), IR (Irrigation), PR (Pruning),
              TR (Transplanting), CU (Cultivation), TH (Thinning), EM (Equipment/Maintenance),
              PO (Pollination), PH (Post-Harvest Processing), CM (Canopy Management)
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
        fields["equipment_operation_type"] = equipment_operation_type or "MN"

    if extra_data:
        fields["extra_data"] = extra_data

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
    extra_data=None,
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
        "area": area,
        "way_of_application": application_method,
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

    if extra_data:
        fields["extra_data"] = extra_data

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
    area_covered=5.0,
    area_unit="ha",
    fuel_consumed=None,
    fuel_unit=None,
    fuel_type=None,
    equipment_hours=None,
    observation="Pest management activity",
    crop_growth_stage="vegetative",
    extra_data=None,
):
    """
    Build complete backend_event_fields for PestManagementEvent (backend_event_type=6)

    Subtypes: SC (Scouting), BR (Beneficial Release), TM (Trap Monitoring),
              PI (Physical Intervention), TA (Threshold Assessment), IP (IPM Implementation)
    """
    fields = {
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
        "area_covered": area_covered,
        "area_unit": area_unit,
        "observation": observation,
    }

    if fuel_consumed is not None:
        fields["fuel_consumed"] = fuel_consumed
        fields["fuel_unit"] = fuel_unit or "L"
        fields["fuel_type"] = fuel_type or "diesel"
    if equipment_hours is not None:
        fields["equipment_hours"] = equipment_hours

    base_extra = {"crop_growth_stage": crop_growth_stage}
    if extra_data:
        base_extra.update(extra_data)
    fields["extra_data"] = base_extra

    return fields


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
    certificate_number=None,
    observation="Business activity",
    extra_data=None,
):
    """
    Build complete backend_event_fields for BusinessEvent (backend_event_type=7)

    Subtypes: CE (Certification), CM (Compliance), IN (Inspection)
    """
    fields = {
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

    if certificate_number:
        fields["certificate_number"] = certificate_number
    if extra_data:
        fields["extra_data"] = extra_data

    return fields


def build_weather_event_fields(
    subtype="FR",
    observation="Weather event recorded",
    event_name=None,
    temperature=None,
    wind_speed=None,
    duration=None,
    damage_description=None,
    water_deficit=None,
    humidity_level=None,
    crop_impact=None,
    protection_measures=None,
    precipitation_amount=None,
    start_date=None,
    end_date=None,
    additional_extra_data=None,
):
    """
    Build complete backend_event_fields for WeatherEvent (backend_event_type=0)

    Subtypes: FR (Frost), DR (Drought), HL (Hail), HT (Heat),
              TS (Storm), HW (High Wind), HH (High Humidity), LH (Low Humidity)

    Frontend key names (fieldDisplayUtils.ts getWeatherEventFields):
      FR: lower_temperature, way_of_protection, duration (hours)
      HT: highest_temperature, start_date, end_date, protection_measures
      DR: water_deficit (mm), crop_impact
      HL: duration (minutes!), way_of_protection, damage_assessment
      TS/HW: wind_speed (km/h), precipitation_amount (mm), duration (hours),
             damage_assessment, protection_measures
      HH/LH: humidity_level (%), duration (hours), crop_impact
    """
    extra_data = {}
    if event_name:
        extra_data["event_name"] = event_name

    # Temperature — key depends on subtype
    if temperature is not None:
        if subtype == "FR":
            extra_data["lower_temperature"] = str(temperature)
        else:
            extra_data["highest_temperature"] = str(temperature)

    # Duration — frontend reads "duration" (hours for most, minutes for HL)
    if duration is not None:
        extra_data["duration"] = duration

    # Wind & precipitation (TS/HW)
    if wind_speed is not None:
        extra_data["wind_speed"] = str(wind_speed)
    if precipitation_amount is not None:
        extra_data["precipitation_amount"] = str(precipitation_amount)

    # Drought fields (DR)
    if water_deficit is not None:
        extra_data["water_deficit"] = str(water_deficit)

    # Humidity fields (HH/LH)
    if humidity_level is not None:
        extra_data["humidity_level"] = str(humidity_level)

    # Shared fields
    if crop_impact:
        extra_data["crop_impact"] = crop_impact
    if protection_measures:
        extra_data["protection_measures"] = protection_measures
    if damage_description:
        extra_data["damage_assessment"] = damage_description

    # Date range (HT)
    if start_date:
        extra_data["start_date"] = start_date
    if end_date:
        extra_data["end_date"] = end_date

    if additional_extra_data:
        extra_data.update(additional_extra_data)

    return {
        "type": subtype,
        "observation": observation,
        "extra_data": extra_data,
    }


def build_general_event_fields(
    activity_type="inspection",
    name="General Activity",
    activity_name="General farm activity",
    duration="2",
    people_involved=1,
    observation="General farm activity",
    extra_data=None,
):
    """
    Build complete backend_event_fields for GeneralEvent (backend_event_type=3)

    Activity types: quality_control, maintenance, training, precision_ag,
                    emergency, planning, documentation, inspection, meeting, other
    """
    fields = {
        "activity_type": activity_type,
        "name": name,
        "activity_name": activity_name,
        "duration": str(duration),
        "people_involved": people_involved,
        "observation": observation,
    }
    if extra_data:
        fields["extra_data"] = extra_data
    return fields


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
    DEPRECATED: Equipment type (backend_event_type=4) is no longer supported in frontend.
    Use build_production_event_fields(subtype="EM") instead.
    Kept for backward compatibility only.

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
# SECTION 2B: TYPICAL AMOUNTS & CARBON SOURCES HELPERS
# =============================================================================


def get_typical_amounts(backend_event_type, subtype, area, crop_data):
    """Return realistic quantity ranges per event type for the typical_amounts JSONField."""
    if backend_event_type == 5:  # Soil
        base = {
            "area_ha": area,
            "working_depth_cm": "15-30",
        }
        if subtype == "CC":
            base["seed_rate_kg_ha"] = "20-40"
            base["expected_biomass_tons_ha"] = "3-6"
        elif subtype == "ST":
            base["samples_per_field"] = "20-30"
        elif subtype == "TI":
            base["fuel_L_ha"] = "8-15"
        return base

    if backend_event_type == 1:  # Production
        if subtype == "IR":
            return {
                "water_volume_gal_per_cycle": "50000-200000",
                "kWh_per_cycle": "85-250",
                "cycles_per_season": "10-24",
                "total_kWh_season": "1500-5000",
            }
        if subtype == "HA":
            yld = crop_data.get("yield_per_ha", 10)
            return {
                "yield_per_ha": f"{yld * 0.8:.1f}-{yld * 1.2:.1f}",
                "yield_unit": crop_data.get("yield_unit", "tons"),
                "total_yield": f"{yld * area * 0.8:.0f}-{yld * area * 1.2:.0f}",
            }
        if subtype == "PL":
            return {
                "fuel_L_ha": "1.5-3.0",
                "equipment_hours_ha": "2-5",
            }
        if subtype == "PR":
            return {
                "fuel_gal_ha": "0.5-1.5",
                "labor_hours_ha": "3-8",
            }
        if subtype == "EM":
            return {
                "service_interval_hours": "200-300",
                "typical_cost_usd": "200-600",
            }
        return {"area_ha": area}

    if backend_event_type == 2:  # Chemical
        if subtype == "FE":
            return {
                "rate_kg_ha": "100-250",
                "total_volume_kg": f"{area * 100:.0f}-{area * 250:.0f}",
                "application_fuel_L": "5-15",
            }
        if subtype == "FU":
            return {
                "rate_L_ha": "1-5",
                "water_volume_L_ha": "400-800",
                "applications_per_season": "2-4",
            }
        if subtype == "HE":
            return {
                "rate_L_ha": "2-6",
                "water_volume_L_ha": "150-300",
            }
        if subtype == "PE":
            return {
                "rate_L_ha": "0.5-3",
                "water_volume_L_ha": "400-1000",
            }
        return {"area_ha": area}

    if backend_event_type == 6:  # Pest
        if subtype == "SC":
            return {
                "area_ha": area,
                "visits_per_season": "12-24",
                "hours_per_visit": "2-3",
            }
        if subtype == "TM":
            return {
                "traps_per_ha": "3-5",
                "total_traps": f"{int(area * 3)}-{int(area * 5)}",
                "check_interval_days": "7-14",
            }
        if subtype == "BR":
            return {
                "release_rate_per_ha": "500-2000",
                "releases_per_season": "2-4",
            }
        return {"area_ha": area}

    if backend_event_type == 7:  # Business
        return {
            "audit_duration_days": "1-2",
            "preparation_hours": "8-16",
        }

    if backend_event_type == 3:  # General
        return {
            "duration_hours": "2-6",
            "participants": "2-10",
        }

    if backend_event_type == 0:  # Weather
        return {
            "monitoring_frequency": "continuous",
        }

    return {}


def get_carbon_sources(backend_event_type, subtype):
    """Return list of emission source strings with EPA/USDA factors."""
    if backend_event_type == 5:  # Soil
        sources = ["Diesel combustion (EPA: 10.21 kg CO2/gal)"]
        if subtype == "CC":
            sources.append("Carbon sequestration from cover crop biomass (negative)")
        return sources

    if backend_event_type == 1:  # Production
        if subtype == "IR":
            return [
                "Electricity for pumping (EPA eGRID: 0.39 kg CO2/kWh)",
                "Pump operation energy consumption",
            ]
        if subtype == "HA":
            return [
                "Equipment diesel (EPA: 10.21 kg CO2/gal)",
                "Transportation fuel if applicable",
            ]
        if subtype == "PL":
            return ["Equipment diesel (EPA: 10.21 kg CO2/gal)"]
        if subtype == "PR":
            return [
                "Chainsaw/equipment fuel (EPA: 10.21 kg CO2/gal diesel)",
            ]
        if subtype == "EM":
            return ["Equipment operation fuel (EPA: 10.21 kg CO2/gal)"]
        return ["Direct fuel combustion (EPA: 10.21 kg CO2/gal)"]

    if backend_event_type == 2:  # Chemical
        if subtype == "FE":
            return [
                "Nitrogen manufacturing (10.5 kg CO2/kg N)",
                "Phosphorus manufacturing (1.19 kg CO2/kg P2O5)",
                "Potassium manufacturing (0.65 kg CO2/kg K2O)",
                "Application fuel (EPA: 10.21 kg CO2/gal diesel)",
            ]
        if subtype == "FU":
            return [
                "Fungicide manufacturing (4.5 kg CO2/kg AI synthetic)",
                "Application fuel (EPA: 10.21 kg CO2/gal diesel)",
            ]
        if subtype == "HE":
            return [
                "Herbicide manufacturing (5.5 kg CO2/kg AI)",
                "Application fuel (EPA: 10.21 kg CO2/gal diesel)",
            ]
        if subtype == "PE":
            return [
                "Pesticide manufacturing (8.8 kg CO2/kg AI)",
                "Application fuel (EPA: 10.21 kg CO2/gal diesel)",
            ]
        return ["Chemical manufacturing + application fuel"]

    if backend_event_type == 6:  # Pest
        return ["Zero direct emissions (observation/monitoring activity)"]

    if backend_event_type == 7:  # Business
        return ["Zero direct emissions (administrative activity)"]

    if backend_event_type == 3:  # General
        return ["Zero direct emissions (documentation/training)"]

    if backend_event_type == 0:  # Weather
        return ["No emissions (natural event recording)"]

    return []


# =============================================================================
# SECTION 3: EVENT TEMPLATE GENERATORS BY CROP CATEGORY
# =============================================================================


def get_tree_crop_events(crop_slug, crop_data):
    """Generate comprehensive events for tree crops (avocados, citrus, apples, grapes, almonds)"""
    area = crop_data["typical_area"]
    return [
        # === SOIL MANAGEMENT (backend_event_type=5) ===
        # 1. Annual Soil Analysis
        {
            "name": "Annual Soil Analysis",
            "event_type": "soil_management",
            "description": f"Annual soil testing for pH, organic matter, and nutrient levels in {crop_slug} orchard",
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 85.0,
            "carbon_impact": 5.0,
            "labor_hours": 3.0,
            "typical_duration": "1 day",
            "efficiency_tips": "Take 20-30 soil samples per block for accurate results",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Soil health monitoring for quality produce",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 1,
            "backend_event_fields": build_soil_event_fields(
                subtype="ST",
                area=area,
                soil_ph=6.5,
                organic_matter_pct=3.0,
                soil_texture=crop_data.get("soil_type", "loam"),
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Annual soil analysis for {crop_slug} orchard",
            ),
        },
        # 2. Cover Crop / Compost Application
        {
            "name": "Cover Crop / Compost Application",
            "event_type": "soil_management",
            "description": "Soil enrichment through cover crop planting or compost application",
            "timing": "October - November",
            "frequency": "annual",
            "carbon_category": "negative",
            "cost_estimate": 150.0,
            "carbon_impact": -25.0,
            "labor_hours": 5.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Cover crops fix nitrogen naturally and prevent erosion",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Building healthy soil through natural methods",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 2,
            "backend_event_fields": build_soil_event_fields(
                subtype="CC",
                area=area,
                fuel_consumed=8.0,
                fuel_unit="gal",
                equipment_hours=6.0,
                amendment_type="Crimson Clover + White Mustard seed mix",
                observation=f"Cover crop planting for {crop_slug} orchard soil health",
                extra_data={
                    "seed_mix": {
                        "crimson_clover_pct": 60,
                        "white_mustard_pct": 40,
                    },
                    "expected_biomass_tons_ha": 4.5,
                },
            ),
        },
        # === CHEMICAL EVENTS (backend_event_type=2) ===
        # 3. Base Fertilization
        {
            "name": "Base Fertilization",
            "event_type": "fertilization",
            "description": f"Primary NPK fertilization for {crop_slug} growth and production",
            "timing": crop_data["timing_fertilize"],
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 220.0,
            "carbon_impact": 125.0,
            "labor_hours": 2.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Soil testing optimizes nutrient application and reduces waste",
            "sustainability_score": 7,
            "qr_visibility": "medium",
            "consumer_message": f"Precision nutrition for quality {crop_slug}",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 3,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                chemical_subtype="synthetic_fertilizer",
                commercial_name=crop_data["commercial_name"],
                concentration=crop_data["npk"],
                volume=area * 150,
                area=area,
                nitrogen_pct=crop_data["nitrogen_pct"],
                phosphorus_pct=crop_data["phosphorus_pct"],
                potassium_pct=crop_data["potassium_pct"],
                application_method="banded",
                fuel_consumed=round(area * 0.88, 1),
                fuel_unit="L",
                application_timing="fall",
                observation=f"Base fertilization for {crop_slug}",
                extra_data={
                    "rate_kg_ha": 150,
                    "volume_unit": "kg",
                },
            ),
        },
        # 4. Secondary Fertigation
        {
            "name": "Secondary Fertigation",
            "event_type": "fertilization",
            "description": "In-season fertigation through irrigation system for micronutrient support",
            "timing": "June - August",
            "frequency": "seasonal",
            "carbon_category": "medium",
            "cost_estimate": 180.0,
            "carbon_impact": 85.0,
            "labor_hours": 1.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Fertigation delivers nutrients directly to root zone with minimal waste",
            "sustainability_score": 8,
            "qr_visibility": "medium",
            "consumer_message": "Targeted nutrition through efficient irrigation",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 4,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                chemical_subtype="synthetic_fertilizer",
                commercial_name=crop_data.get("secondary_fertilizer", crop_data["commercial_name"]),
                concentration=crop_data.get("secondary_npk", crop_data["npk"]),
                volume=area * 100,
                area=area,
                nitrogen_pct=crop_data.get("secondary_nitrogen_pct", crop_data["nitrogen_pct"]),
                phosphorus_pct=crop_data.get("secondary_phosphorus_pct", crop_data["phosphorus_pct"]),
                potassium_pct=crop_data.get("secondary_potassium_pct", crop_data["potassium_pct"]),
                application_method="drip",
                fuel_type="electric",
                fuel_consumed=2.5,
                fuel_unit="kWh",
                application_timing="summer",
                observation=f"Summer fertigation for {crop_slug}",
            ),
        },
        # 5. Fungicide Prevention
        {
            "name": "Fungicide Prevention Treatment",
            "event_type": "fertilization",
            "description": "Preventive fungicide application targeting primary disease threats",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 140.0,
            "carbon_impact": 50.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Preventive applications are more effective and use less product",
            "sustainability_score": 6,
            "qr_visibility": "high",
            "consumer_message": "Disease prevention for healthy trees",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 5,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FU",
                chemical_subtype=crop_data.get("fungicide_subtype", "synthetic_fungicide"),
                commercial_name=crop_data.get("primary_fungicide", "Copper hydroxide fungicide"),
                concentration="45",
                volume=15.0,
                area=area,
                target_pest_disease=crop_data.get("fungicide_target", "Root rot, Anthracnose"),
                fuel_consumed=4.5,
                fuel_unit="L",
                application_method="trunk_drench",
                observation=f"Fungicide prevention for {crop_slug}",
                extra_data={
                    "dilution_rate": "2.5 pt/acre",
                    "water_volume_L": int(area * 500),
                },
            ),
        },
        # 6. Organic/Copper Fungicide Spray
        {
            "name": "Organic Fungicide Spray",
            "event_type": "fertilization",
            "description": "Organic-approved copper or sulfur fungicide for preventive disease control",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 120.0,
            "carbon_impact": 45.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Apply before rain for best coverage; OMRI-listed products available",
            "sustainability_score": 8,
            "qr_visibility": "high",
            "consumer_message": "Organic-approved disease protection",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 6,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FU",
                chemical_subtype="copper_fungicide",
                commercial_name=crop_data.get("copper_fungicide", "Copper hydroxide fungicide"),
                concentration="46",
                volume=area * 2.24,
                area=area,
                target_pest_disease=crop_data.get("copper_target", "Anthracnose, Canker"),
                fuel_consumed=7.0,
                fuel_unit="gal",
                organic_approved="organic",
                application_method="airblast",
                observation=f"Organic fungicide spray for {crop_slug}",
            ),
        },
        # 7. Herbicide Application
        {
            "name": "Herbicide Application",
            "event_type": "fertilization",
            "description": "Targeted weed control in row middles and around tree bases",
            "timing": "Post-harvest",
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 95.0,
            "carbon_impact": 40.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Shielded sprayers prevent drift and protect trees",
            "sustainability_score": 5,
            "qr_visibility": "high",
            "consumer_message": "Responsible weed management practices",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 7,
            "backend_event_fields": build_chemical_event_fields(
                subtype="HE",
                chemical_subtype=crop_data.get("herbicide_subtype", "synthetic_herbicide"),
                commercial_name=crop_data.get("herbicide", "Post-emergent herbicide"),
                concentration="48",
                volume=area * 4.7,
                area=area,
                target_pest_disease="Broadleaf weeds, Annual grasses",
                fuel_consumed=6.0,
                fuel_unit="gal",
                application_method="shielded_boom",
                observation=f"Herbicide application for {crop_slug} orchard",
                extra_data={
                    "rate_L_ha": 4.7,
                    "spray_equipment": "shielded boom sprayer",
                    "water_volume_L_ha": 200,
                },
            ),
        },
        # 8. Pesticide Treatment
        {
            "name": "Pesticide Treatment",
            "event_type": "fertilization",
            "description": "Targeted pesticide application when pest thresholds are exceeded",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 160.0,
            "carbon_impact": 55.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Only apply when scouting confirms threshold exceeded",
            "sustainability_score": 5,
            "qr_visibility": "high",
            "consumer_message": "Targeted treatment only when necessary",
            "backend_event_type": 2,
            "is_default_enabled": False,
            "is_required": False,
            "order_sequence": 8,
            "backend_event_fields": build_chemical_event_fields(
                subtype="PE",
                chemical_subtype=crop_data.get("pesticide_subtype", "synthetic_pesticide"),
                commercial_name=crop_data.get("synthetic_pesticide", "Targeted insecticide"),
                concentration="25",
                volume=3.0,
                area=area,
                target_pest_disease=crop_data.get("synthetic_pesticide_target", crop_data["common_pests"]),
                fuel_consumed=8.0,
                fuel_unit="gal",
                application_method="airblast",
                observation=f"Pesticide treatment for {crop_slug}",
            ),
        },
        # === PRODUCTION EVENTS (backend_event_type=1) ===
        # 9. Season Irrigation
        {
            "name": "Season Irrigation Program",
            "event_type": "irrigation",
            "description": f"Season-long irrigation management using {crop_data['irrigation_method']} system",
            "timing": crop_data["timing_irrigate"],
            "frequency": "weekly",
            "carbon_category": "medium",
            "cost_estimate": 180.0,
            "carbon_impact": 78.0,
            "labor_hours": 2.0,
            "typical_duration": "Ongoing",
            "efficiency_tips": "Soil moisture sensors optimize water use and reduce energy",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Efficient water management",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 9,
            "backend_event_fields": build_production_event_fields(
                subtype="IR",
                area=area,
                fuel_consumed=3060.0,
                fuel_unit="kWh",
                fuel_type="electric",
                irrigation_method=crop_data["irrigation_method"],
                water_source=crop_data.get("water_source", "well_groundwater"),
                irrigation_depth=2.5,
                observation=f"Season irrigation for {crop_slug} orchard",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 18,
                    "water_volume_total": 3600000,
                    "water_volume_unit": "gallons",
                },
            ),
        },
        # 10. Annual Pruning
        {
            "name": "Annual Structural Pruning",
            "event_type": "pruning",
            "description": "Structural pruning for canopy management, light penetration, and tree health",
            "timing": "December - February",
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 180.0,
            "carbon_impact": 45.0,
            "labor_hours": 6.0,
            "typical_duration": "3-5 days",
            "efficiency_tips": "Proper pruning increases fruit quality and airflow",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Expert tree care for healthy fruit",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 10,
            "backend_event_fields": build_production_event_fields(
                subtype="PR",
                area=area,
                fuel_consumed=12.0,
                fuel_unit="gal",
                equipment_hours=24.0,
                observation=f"Annual structural pruning for {crop_slug}",
            ),
        },
        # 11. Harvest
        {
            "name": "Harvest",
            "event_type": "harvest",
            "description": "Careful harvest to maintain fruit quality and maximize grade",
            "timing": crop_data["timing_harvest"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 320.0,
            "carbon_impact": 25.0,
            "labor_hours": 12.0,
            "typical_duration": "5-10 days per pass",
            "efficiency_tips": "Multiple harvest passes optimize fruit maturity and quality",
            "sustainability_score": 8,
            "qr_visibility": "medium",
            "consumer_message": "Carefully harvested at peak quality",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 11,
            "backend_event_fields": build_production_event_fields(
                subtype="HA",
                area=area,
                yield_quantity=crop_data["yield_per_ha"] * area,
                yield_unit="kg",
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Manual {crop_slug} harvest for premium quality",
                extra_data={
                    "crew_size": 12,
                    "bins_filled": int(crop_data["yield_per_ha"] * area / 18),
                    "kg_per_bin": 18,
                },
            ),
        },
        # 12. Planting / Replanting
        {
            "name": "Planting / Replanting",
            "event_type": "planting",
            "description": "New tree planting or replanting in blocks with declining production",
            "timing": crop_data["timing_plant"],
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 250.0,
            "carbon_impact": 35.0,
            "labor_hours": 10.0,
            "typical_duration": "2-3 days",
            "efficiency_tips": "Select disease-resistant rootstock for long-term productivity",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Investing in orchard renewal for future harvests",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 12,
            "backend_event_fields": build_production_event_fields(
                subtype="PL",
                area=2.5,
                fuel_consumed=18.0,
                fuel_unit="L",
                fuel_type="biodiesel",
                equipment_hours=10.0,
                seeds_source="certified_organic",
                observation=f"Replanting {crop_slug} in declining blocks",
                extra_data={
                    "trees_planted": 625,
                    "rootstock": "Dusa clonal",
                    "nursery": "Brokaw Nursery",
                    "spacing_m": "6x4",
                },
            ),
        },
        # 13. Cultivation / Weed Management
        {
            "name": "Mechanical Weed Management",
            "event_type": "other",
            "description": "Mechanical cultivation or flame weeding between tree rows",
            "timing": "Spring - Summer",
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 85.0,
            "carbon_impact": 30.0,
            "labor_hours": 4.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Reduces herbicide use while controlling weeds",
            "sustainability_score": 8,
            "qr_visibility": "medium",
            "consumer_message": "Mechanical weed control reduces chemical use",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 13,
            "backend_event_fields": build_production_event_fields(
                subtype="CU",
                area=area,
                fuel_consumed=45.0,
                fuel_unit="gal",
                fuel_type="propane",
                equipment_hours=12.0,
                observation=f"Mechanical weed management for {crop_slug} orchard",
            ),
        },
        # 14. Fruit Thinning
        {
            "name": "Fruit Thinning",
            "event_type": "other",
            "description": "Hand or mechanical thinning to optimize fruit size and quality",
            "timing": "May - June",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 200.0,
            "carbon_impact": 0.0,
            "labor_hours": 8.0,
            "typical_duration": "3-5 days",
            "efficiency_tips": "Removing 15% of fruitlets improves remaining fruit size",
            "sustainability_score": 8,
            "qr_visibility": "low",
            "consumer_message": "Quality selection for premium fruit",
            "backend_event_type": 1,
            "is_default_enabled": False,
            "is_required": False,
            "order_sequence": 14,
            "backend_event_fields": build_production_event_fields(
                subtype="TH",
                area=area,
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Hand thinning for {crop_slug} quality optimization",
            ),
        },
        # 15. Equipment Maintenance
        {
            "name": "Equipment Maintenance",
            "event_type": "equipment",
            "description": "Scheduled maintenance on primary farm equipment (tractor, sprayer, pump)",
            "timing": "Post-harvest",
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 85.0,
            "carbon_impact": 15.0,
            "labor_hours": 8.0,
            "typical_duration": "1 day",
            "efficiency_tips": "Regular maintenance improves fuel efficiency by 10-15%",
            "sustainability_score": 7,
            "qr_visibility": "low",
            "consumer_message": "Well-maintained equipment for efficient farming",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 15,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                area=0.0,
                fuel_consumed=5.0,
                fuel_unit="gal",
                equipment_hours=8.0,
                equipment_type="tractor",
                equipment_operation_type="MN",
                observation="Annual tractor service - oil change, filter, hydraulic check",
                extra_data={
                    "equipment_name": "John Deere 5075E",
                    "maintenance_cost": 450,
                    "odometer_hours": 1200,
                    "next_service_hours": 1450,
                },
            ),
        },
        # 16. Sprayer Calibration
        {
            "name": "Sprayer Calibration",
            "event_type": "equipment",
            "description": "Annual calibration of spray equipment for accurate chemical application",
            "timing": "Pre-season",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 45.0,
            "carbon_impact": 10.0,
            "labor_hours": 3.0,
            "typical_duration": "3-4 hours",
            "efficiency_tips": "Proper calibration reduces chemical waste by 20%",
            "sustainability_score": 9,
            "qr_visibility": "low",
            "consumer_message": "Precise equipment calibration minimizes chemical use",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 16,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                area=0.0,
                fuel_consumed=4.5,
                fuel_unit="gal",
                fuel_type="gasoline",
                equipment_hours=3.0,
                equipment_type="sprayer",
                equipment_operation_type="CA",
                observation="Airblast sprayer nozzle calibration and coverage verification",
                extra_data={
                    "equipment_name": "Rears Pul-Blast 500",
                    "nozzles_tested": 24,
                    "nozzles_replaced": 4,
                },
            ),
        },
        # === PEST MANAGEMENT (backend_event_type=6) ===
        # 17. Pest Scouting
        {
            "name": "Pest Scouting",
            "event_type": "pest_control",
            "description": f"Bi-weekly visual inspection for {crop_slug} pests and diseases",
            "timing": crop_data["timing_pest"],
            "frequency": "bi-weekly",
            "carbon_category": "neutral",
            "cost_estimate": 45.0,
            "carbon_impact": 0.0,
            "labor_hours": 2.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Systematic scouting prevents costly outbreaks",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Regular monitoring keeps crops healthy naturally",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 17,
            "backend_event_fields": build_pest_event_fields(
                subtype="SC",
                pest_species=crop_data.get("primary_pest_species", crop_data["common_pests"]),
                pest_pressure_level="low",
                beneficial_insects_used="yes",
                action_threshold_met=False,
                area_covered=area,
                observation=f"Bi-weekly pest scouting for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 12,
                    "pest_species_observed": crop_data.get("primary_pest_species", crop_data["common_pests"]),
                    "average_pest_pressure": "low",
                    "area_covered_total": area,
                    "area_unit": "ha",
                    "carbon_impact": "zero",
                },
            ),
        },
        # 18. Trap Monitoring
        {
            "name": "Pest Trap Monitoring",
            "event_type": "pest_control",
            "description": "Sticky trap and pheromone trap monitoring for pest population tracking",
            "timing": crop_data["timing_pest"],
            "frequency": "bi-weekly",
            "carbon_category": "neutral",
            "cost_estimate": 35.0,
            "carbon_impact": 0.0,
            "labor_hours": 1.5,
            "typical_duration": "1-2 hours",
            "efficiency_tips": "4 traps per hectare provides reliable population data",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Advanced monitoring tracks pest populations",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 18,
            "backend_event_fields": build_pest_event_fields(
                subtype="TM",
                pest_species=crop_data.get("primary_pest_species", crop_data["common_pests"]),
                pest_pressure_level="low",
                action_threshold_met=False,
                trap_count=int(area * 4),
                area_covered=area,
                observation=f"Sticky trap monitoring for {crop_slug}",
                extra_data={
                    "traps_per_ha": 4,
                    "avg_pests_per_trap": 2.5,
                    "trap_type": "yellow sticky + pheromone",
                    "treatment_threshold": 10,
                },
            ),
        },
        # 19. Beneficial Insect Release
        {
            "name": "Beneficial Insect Release",
            "event_type": "pest_control",
            "description": "Release of beneficial insects for biological pest control",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "neutral",
            "cost_estimate": 200.0,
            "carbon_impact": 0.0,
            "labor_hours": 2.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Biological control reduces pesticide needs by 60%",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Natural pest control with beneficial insects",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 19,
            "backend_event_fields": build_pest_event_fields(
                subtype="BR",
                pest_species=crop_data.get("primary_pest_species", crop_data["common_pests"]),
                pest_pressure_level="low",
                beneficial_species=crop_data["beneficial_insects"],
                release_quantity=crop_data.get("beneficial_release_quantity", "500 per hectare"),
                beneficial_insects_used="yes",
                area_covered=area,
                observation=f"Beneficial insect release for {crop_slug}",
            ),
        },
        # === WEATHER (backend_event_type=0) ===
        # 20. Weather Event - Tree crops: heat stress and frost are primary concerns
        {
            "name": f"Heat Stress Alert - {crop_slug.replace('_', ' ').title()}",
            "event_type": "weather_protection",
            "description": f"High temperature event documentation for {crop_slug} orchard health monitoring",
            "timing": "June - September",
            "frequency": "natural",
            "carbon_category": "neutral",
            "cost_estimate": 0.0,
            "carbon_impact": 0.0,
            "labor_hours": 0.5,
            "typical_duration": "Variable",
            "efficiency_tips": "Early documentation helps insurance claims and loss assessment",
            "sustainability_score": 5,
            "qr_visibility": "medium",
            "consumer_message": "Weather transparency for informed consumers",
            "backend_event_type": 0,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 20,
            "backend_event_fields": build_weather_event_fields(
                subtype="HT",
                event_name=f"Heat stress event in {crop_slug} orchard",
                temperature=42,
                duration=72,
                start_date="",
                end_date="",
                protection_measures="Increased irrigation frequency, overhead mist activation",
                observation=f"High temperature event affecting {crop_slug} orchard — monitoring tree stress and irrigation needs",
            ),
        },
        # === BUSINESS (backend_event_type=7) ===
        # 21. Certification Audit
        {
            "name": "Certification Audit",
            "event_type": "certification",
            "description": "Third-party certification audit for food safety and sustainability standards",
            "timing": "Annual",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 500.0,
            "carbon_impact": 0.0,
            "labor_hours": 8.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Maintain documentation year-round for smooth audits",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "Third-party verified farming practices",
            "backend_event_type": 7,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 21,
            "backend_event_fields": build_business_event_fields(
                subtype="CE",
                name=crop_data.get("certification_standard", "Food Safety Certification"),
                business_type="certification",
                certification_type=crop_data.get("certification_type", "global_gap"),
                verification_status="verified",
                verified_certifier_name=crop_data.get("certification_body", "Third-party auditor"),
                observation=f"Annual certification audit for {crop_slug} operation",
                extra_data={
                    "audit_date": "",
                    "auditor": crop_data.get("certification_body", "Third-party auditor"),
                    "standard": crop_data.get("certification_standard", "Food Safety"),
                    "control_points": 218,
                    "major_nc": 0,
                    "minor_nc": 3,
                    "valid_until": "",
                },
            ),
        },
        # === GENERAL (backend_event_type=3) ===
        # 22. Quality Control / Worker Training
        {
            "name": "Quality Control & Training",
            "event_type": "monitoring",
            "description": "Water quality testing, worker safety training, and general farm quality activities",
            "timing": "Quarterly / Annual",
            "frequency": "quarterly",
            "carbon_category": "neutral",
            "cost_estimate": 65.0,
            "carbon_impact": 0.0,
            "labor_hours": 4.0,
            "typical_duration": "2-6 hours",
            "efficiency_tips": "Regular quality checks prevent costly problems",
            "sustainability_score": 8,
            "qr_visibility": "medium",
            "consumer_message": "Quality assurance and worker safety programs",
            "backend_event_type": 3,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 22,
            "backend_event_fields": build_general_event_fields(
                activity_type="quality_control",
                name="Quality Control & Training",
                activity_name="Water quality testing and worker safety certification",
                duration="4",
                people_involved=2,
                observation=f"Quality control and training for {crop_slug} operation",
            ),
        },
        # === PHASE 2: NEW PRODUCTION SUBTYPES ===
        # 23. Pollination Management (PO) — relevant for almonds, stone fruit, apples
        {
            "name": "Pollination Management",
            "event_type": "production",
            "description": (
                f"Managed pollination for {crop_slug} — bee hive placement, "
                "pollinator monitoring, and bloom period management"
            ),
            "timing": "Bloom period (crop-specific)",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 180.0,
            "carbon_impact": 0.0,
            "labor_hours": 4.0,
            "typical_duration": "2-4 weeks",
            "efficiency_tips": (
                "Place hives at 1-2 per acre at 10-20% bloom for optimal pollination. "
                "Almonds require 2 hives/acre minimum."
            ),
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": (
                "Managed bee pollination — bees pollinate the flowers that become fruit. "
                "Zero emissions from this natural process."
            ),
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 23,
            "backend_event_fields": build_production_event_fields(
                subtype="PO",
                area=area,
                area_unit="ha",
                fuel_consumed=0.0,
                fuel_unit="gal",
                fuel_type="none",
                equipment_hours=0.0,
                efficiency="high",
                observation=f"Pollination management for {crop_slug} — bee hive placement at bloom",
                extra_data={
                    "pollinator_type": "honey_bee",
                    "hive_count": max(1, int(area * 2)),  # 2 hives/ha default
                    "hive_density_per_hectare": 2,
                    "bloom_percentage_at_placement": "10-20%",
                    "hive_source": "local_beekeeper",
                    "carbon_impact": "zero",
                    "carbon_notes": (
                        "Pollination is a biological service with zero direct emissions. "
                        "Hive transportation emissions excluded per Trazo direct operational methodology."
                    ),
                },
            ),
        },
        # 24. Post-Harvest Processing (PH) — hulling, shelling, washing, sorting, packing
        {
            "name": "Post-Harvest Processing",
            "event_type": "production",
            "description": (
                f"Post-harvest processing for {crop_slug} — "
                "hulling/shelling, washing, sorting, grading, and packing operations"
            ),
            "timing": "After harvest",
            "frequency": "annual",
            "carbon_category": "medium",
            "cost_estimate": 250.0,
            "carbon_impact": 45.0,
            "labor_hours": 12.0,
            "typical_duration": "1-4 weeks",
            "efficiency_tips": (
                "Modern optical sorters reduce waste by 15-30%. "
                "Electric equipment significantly reduces emissions vs diesel."
            ),
            "sustainability_score": 7,
            "qr_visibility": "high",
            "consumer_message": (
                "Post-harvest processing — washing, sorting, and packing " f"to bring quality {crop_slug} to market."
            ),
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 24,
            "backend_event_fields": build_production_event_fields(
                subtype="PH",
                area=area,
                area_unit="ha",
                fuel_consumed=round(area * 3.5, 1),  # ~3.5 gal/ha for processing equipment
                fuel_unit="gal",
                fuel_type="diesel",
                equipment_hours=round(area * 2.0, 1),
                efficiency="normal",
                observation=f"Post-harvest processing for {crop_slug} — hulling, sorting, packing",
                extra_data={
                    "processing_steps": ["washing", "sorting", "grading", "packing"],
                    "equipment_used": "sorting_line",
                    "packaging_type": "standard_carton",
                    "cold_storage": False,
                },
            ),
        },
        # 25. Canopy Management (CM) — leaf pulling, hedging, shoot positioning (grapes/vines)
        {
            "name": "Canopy Management",
            "event_type": "production",
            "description": (
                f"Canopy management for {crop_slug} — leaf pulling, hedging, "
                "shoot positioning, and cluster thinning for air circulation and light penetration"
            ),
            "timing": "Post-bloom through veraison",
            "frequency": "seasonal",
            "carbon_category": "low",
            "cost_estimate": 120.0,
            "carbon_impact": 25.0,
            "labor_hours": 8.0,
            "typical_duration": "2-4 weeks",
            "efficiency_tips": (
                "Leaf removal at fruit zone improves color, reduces disease, "
                "and enhances fruit quality without heavy equipment."
            ),
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": (
                f"Canopy management — careful hand work opening up the {crop_slug} canopy "
                "for better sunlight and air flow, improving fruit quality naturally."
            ),
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 25,
            "backend_event_fields": build_production_event_fields(
                subtype="CM",
                area=area,
                area_unit="ha",
                fuel_consumed=round(area * 1.5, 1),  # Light tractor/equipment use
                fuel_unit="gal",
                fuel_type="diesel",
                equipment_hours=round(area * 1.0, 1),
                efficiency="normal",
                observation=f"Canopy management for {crop_slug} — leaf pulling and shoot positioning",
                extra_data={
                    "canopy_operations": ["leaf_pulling", "shoot_positioning", "hedging"],
                    "target_zone": "fruit_zone",
                    "timing_relative_to_bloom": "post_bloom",
                    "labor_intensive": True,
                    "equipment_notes": "Primarily hand labor with light mechanical hedging",
                },
            ),
        },
    ]


def _build_shared_weather_event(crop_slug, crop_category, order):
    """Build a crop-category-appropriate weather event template."""
    crop_label = crop_slug.replace("_", " ").title()

    if crop_category == "grain":
        # Grains: drought and hailstorms are primary threats
        return {
            "name": f"Drought Monitoring - {crop_label}",
            "event_type": "weather_protection",
            "description": f"Drought conditions monitoring and documentation for {crop_slug} production",
            "timing": "June - August",
            "frequency": "natural",
            "carbon_category": "neutral",
            "cost_estimate": 0.0,
            "carbon_impact": 0.0,
            "labor_hours": 0.5,
            "typical_duration": "Variable",
            "efficiency_tips": "Early documentation helps insurance claims and irrigation planning",
            "sustainability_score": 5,
            "qr_visibility": "medium",
            "consumer_message": "Weather transparency for informed consumers",
            "backend_event_type": 0,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": order,
            "backend_event_fields": build_weather_event_fields(
                subtype="DR",
                event_name=f"Drought conditions affecting {crop_slug}",
                temperature=38,
                water_deficit=45,
                duration=168,
                crop_impact=f"Soil moisture stress on {crop_slug} — leaf curling and reduced growth observed",
                observation=f"Drought stress monitoring for {crop_slug} — tracking soil moisture and crop wilting indicators",
            ),
        }
    elif crop_category == "vegetable":
        # Vegetables: frost damage is a primary concern
        return {
            "name": f"Frost Alert - {crop_label}",
            "event_type": "weather_protection",
            "description": f"Frost event documentation for {crop_slug} crop protection",
            "timing": "October - March",
            "frequency": "natural",
            "carbon_category": "neutral",
            "cost_estimate": 0.0,
            "carbon_impact": 0.0,
            "labor_hours": 0.5,
            "typical_duration": "Variable",
            "efficiency_tips": "Frost protection covers and irrigation can prevent significant crop loss",
            "sustainability_score": 5,
            "qr_visibility": "medium",
            "consumer_message": "Weather transparency for informed consumers",
            "backend_event_type": 0,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": order,
            "backend_event_fields": build_weather_event_fields(
                subtype="FR",
                event_name=f"Frost event affecting {crop_slug}",
                temperature=-2,
                duration=6,
                protection_measures="Row covers deployed, irrigation frost protection activated",
                observation=f"Frost event documentation for {crop_slug} — assessing crop damage and protection measures taken",
            ),
        }
    elif crop_category == "berry":
        # Berries: high humidity / rain during fruiting is the biggest threat
        return {
            "name": f"High Humidity Alert - {crop_label}",
            "event_type": "weather_protection",
            "description": f"High humidity and rain event documentation for {crop_slug} disease prevention",
            "timing": "May - August",
            "frequency": "natural",
            "carbon_category": "neutral",
            "cost_estimate": 0.0,
            "carbon_impact": 0.0,
            "labor_hours": 0.5,
            "typical_duration": "Variable",
            "efficiency_tips": "Monitor botrytis and mildew risk during prolonged humidity",
            "sustainability_score": 5,
            "qr_visibility": "medium",
            "consumer_message": "Weather transparency for informed consumers",
            "backend_event_type": 0,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": order,
            "backend_event_fields": build_weather_event_fields(
                subtype="HH",
                event_name=f"High humidity event affecting {crop_slug}",
                humidity_level=92,
                duration=96,
                crop_impact=f"Increased botrytis and mildew pressure on {crop_slug} — preventive fungicide applied",
                observation=f"High humidity documentation for {crop_slug} — monitoring disease pressure and fruit quality",
            ),
        }
    else:
        # Fallback: generic extreme weather
        return {
            "name": f"Weather Event - {crop_label}",
            "event_type": "weather_protection",
            "description": f"Weather event documentation for {crop_slug} production monitoring",
            "timing": "Year-round",
            "frequency": "natural",
            "carbon_category": "neutral",
            "cost_estimate": 0.0,
            "carbon_impact": 0.0,
            "labor_hours": 0.5,
            "typical_duration": "Variable",
            "efficiency_tips": "Early documentation helps insurance claims",
            "sustainability_score": 5,
            "qr_visibility": "medium",
            "consumer_message": "Weather transparency for informed consumers",
            "backend_event_type": 0,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": order,
            "backend_event_fields": build_weather_event_fields(
                subtype="HT",
                event_name=f"Weather event affecting {crop_slug}",
                temperature=40,
                duration=48,
                protection_measures="Increased irrigation, shade cloth deployed",
                observation=f"Weather event documentation for {crop_slug} production",
            ),
        }


def get_shared_extra_events(crop_slug, crop_data, start_order=7, crop_category="grain"):
    """
    Generate shared event templates for Weather, Business, General, Equipment Maintenance,
    Soil Test, Fungicide, Herbicide, and Pest Scouting that apply to all crop categories.

    crop_category: one of "grain", "vegetable", "berry" — controls weather event subtype.
    """
    area = crop_data["typical_area"]
    return [
        # Soil Test
        {
            "name": "Soil Analysis",
            "event_type": "soil_management",
            "description": "Soil testing for pH, organic matter, and nutrient levels",
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 85.0,
            "carbon_impact": 5.0,
            "labor_hours": 3.0,
            "typical_duration": "1 day",
            "efficiency_tips": "Sample 20-30 cores per field for accuracy",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Soil health monitoring for sustainable farming",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": start_order,
            "backend_event_fields": build_soil_event_fields(
                subtype="ST",
                area=area,
                soil_ph=6.5,
                organic_matter_pct=3.0,
                soil_texture=crop_data.get("soil_type", "loam"),
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Annual soil analysis for {crop_slug}",
            ),
        },
        # Fungicide
        {
            "name": "Fungicide Treatment",
            "event_type": "fertilization",
            "description": "Preventive or curative fungicide application for disease control",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 120.0,
            "carbon_impact": 45.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Preventive timing is more effective and uses less product",
            "sustainability_score": 6,
            "qr_visibility": "high",
            "consumer_message": "Disease prevention for healthy crops",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": start_order + 1,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FU",
                chemical_subtype=crop_data.get("fungicide_subtype", "synthetic_fungicide"),
                commercial_name=crop_data.get("primary_fungicide", "Preventive fungicide"),
                concentration="45",
                volume=area * 2.0,
                area=area,
                target_pest_disease=crop_data.get("fungicide_target", "Root rot, Blight"),
                fuel_consumed=6.0,
                fuel_unit="L",
                application_method="broadcast",
                observation=f"Fungicide treatment for {crop_slug}",
            ),
        },
        # Herbicide
        {
            "name": "Herbicide Application",
            "event_type": "fertilization",
            "description": "Targeted weed control application",
            "timing": "Pre-emergence or post-emergence",
            "frequency": "as_needed",
            "carbon_category": "medium",
            "cost_estimate": 95.0,
            "carbon_impact": 40.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Band application reduces herbicide use by 50%",
            "sustainability_score": 5,
            "qr_visibility": "high",
            "consumer_message": "Responsible weed management",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": start_order + 2,
            "backend_event_fields": build_chemical_event_fields(
                subtype="HE",
                chemical_subtype=crop_data.get("herbicide_subtype", "synthetic_herbicide"),
                commercial_name=crop_data.get("herbicide", "Post-emergent herbicide"),
                concentration="48",
                volume=area * 3.0,
                area=area,
                target_pest_disease="Broadleaf weeds, Annual grasses",
                fuel_consumed=6.0,
                fuel_unit="gal",
                application_method="broadcast",
                observation=f"Herbicide application for {crop_slug}",
            ),
        },
        # Equipment Maintenance (Production EM subtype, NOT Equipment type 4)
        {
            "name": "Equipment Maintenance",
            "event_type": "equipment",
            "description": "Scheduled maintenance on primary farm equipment",
            "timing": "Post-harvest",
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 85.0,
            "carbon_impact": 15.0,
            "labor_hours": 8.0,
            "typical_duration": "1 day",
            "efficiency_tips": "Regular maintenance improves fuel efficiency by 10-15%",
            "sustainability_score": 7,
            "qr_visibility": "low",
            "consumer_message": "Well-maintained equipment for efficient farming",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": start_order + 3,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                area=0.0,
                fuel_consumed=5.0,
                fuel_unit="gal",
                equipment_hours=8.0,
                equipment_type="tractor",
                equipment_operation_type="MN",
                observation="Annual equipment service and maintenance",
            ),
        },
        # Pest Scouting
        {
            "name": "Pest Scouting",
            "event_type": "pest_control",
            "description": f"Regular pest monitoring and population assessment for {crop_slug}",
            "timing": crop_data["timing_pest"],
            "frequency": "bi-weekly",
            "carbon_category": "neutral",
            "cost_estimate": 45.0,
            "carbon_impact": 0.0,
            "labor_hours": 2.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Systematic scouting prevents costly outbreaks",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Regular monitoring keeps crops healthy naturally",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": start_order + 4,
            "backend_event_fields": build_pest_event_fields(
                subtype="SC",
                pest_species=crop_data.get("primary_pest_species", crop_data["common_pests"]),
                pest_pressure_level="low",
                beneficial_insects_used="yes",
                action_threshold_met=False,
                area_covered=area,
                observation=f"Bi-weekly pest scouting for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 12,
                    "pest_species_observed": crop_data.get("primary_pest_species", crop_data["common_pests"]),
                    "average_pest_pressure": "low",
                    "area_covered_total": area,
                    "area_unit": "ha",
                    "carbon_impact": "zero",
                },
            ),
        },
        # Weather Event — subtype varies by crop category
        _build_shared_weather_event(crop_slug, crop_category, start_order + 5),
        # Certification Audit
        {
            "name": "Certification Audit",
            "event_type": "certification",
            "description": "Third-party certification audit for food safety or sustainability",
            "timing": "Annual",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 500.0,
            "carbon_impact": 0.0,
            "labor_hours": 8.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Maintain documentation year-round for smooth audits",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "Third-party verified farming practices",
            "backend_event_type": 7,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": start_order + 6,
            "backend_event_fields": build_business_event_fields(
                subtype="CE",
                name=crop_data.get("certification_standard", "Food Safety Certification"),
                business_type="certification",
                certification_type=crop_data.get("certification_type", "sustainable_agriculture"),
                verification_status="verified",
                verified_certifier_name=crop_data.get("certification_body", "Third-party auditor"),
                observation=f"Certification audit for {crop_slug} operation",
            ),
        },
        # General - Worker Training / Quality Control
        {
            "name": "Quality Control & Training",
            "event_type": "monitoring",
            "description": "Worker safety training, quality testing, and general farm management",
            "timing": "Quarterly / Annual",
            "frequency": "quarterly",
            "carbon_category": "neutral",
            "cost_estimate": 65.0,
            "carbon_impact": 0.0,
            "labor_hours": 4.0,
            "typical_duration": "2-6 hours",
            "efficiency_tips": "Regular training improves safety and product quality",
            "sustainability_score": 8,
            "qr_visibility": "medium",
            "consumer_message": "Quality assurance and worker safety programs",
            "backend_event_type": 3,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": start_order + 7,
            "backend_event_fields": build_general_event_fields(
                activity_type="training",
                name="Quality Control & Training",
                activity_name="Worker safety and quality assurance program",
                duration="4",
                people_involved=10,
                observation=f"Quality control and training for {crop_slug}",
            ),
        },
    ]


def get_grain_events(crop_slug, crop_data):
    """Generate events for grain crops (corn, wheat, soybeans, rice)"""
    events = [
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
                area_covered=crop_data["typical_area"],
                crop_growth_stage="vegetative",
                observation=f"Pest scouting for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 8,
                    "pest_species_observed": crop_data["common_pests"],
                    "average_pest_pressure": "medium",
                    "area_covered_total": crop_data["typical_area"],
                    "area_unit": "ha",
                    "carbon_impact": "zero",
                },
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
                fuel_consumed=45.0,
                fuel_unit="kWh",
                fuel_type="electric",
                irrigation_method=crop_data["irrigation_method"],
                irrigation_depth=2.5,
                observation=f"Field irrigation for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 10,
                    "water_volume_total": 2000000,
                    "water_volume_unit": "gallons",
                },
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
    events.extend(get_shared_extra_events(crop_slug, crop_data, start_order=7, crop_category="grain"))
    return events


def get_vegetable_events(crop_slug, crop_data):
    """Generate events for vegetable crops (tomatoes, potatoes, lettuce, carrots, onions)"""
    events = [
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
                fuel_unit="kWh",
                fuel_type="electric",
                irrigation_method="drip",
                irrigation_depth=1.5,
                observation=f"Drip irrigation for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 20,
                    "water_volume_total": 500000,
                    "water_volume_unit": "gallons",
                },
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
                area_covered=crop_data["typical_area"],
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
    # Phase 2: Post-Harvest Processing for mixed vegetables (washing/packing)
    events.append(
        {
            "name": "Post-Harvest Washing & Packing",
            "event_type": "production",
            "description": (
                f"Post-harvest processing for {crop_slug} — " "field washing, grading, and packing operations"
            ),
            "timing": "After harvest",
            "frequency": "seasonal",
            "carbon_category": "low",
            "cost_estimate": 120.0,
            "carbon_impact": 20.0,
            "labor_hours": 6.0,
            "typical_duration": "3-7 days",
            "efficiency_tips": "Rapid post-harvest cooling preserves quality and reduces waste",
            "sustainability_score": 8,
            "qr_visibility": "high",
            "consumer_message": (
                f"Post-harvest handling — careful washing, sorting, and packing " f"of {crop_slug} to reach you fresh."
            ),
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 7,
            "backend_event_fields": build_production_event_fields(
                subtype="PH",
                area=crop_data["typical_area"],
                area_unit="ha",
                fuel_consumed=round(crop_data["typical_area"] * 2.0, 1),
                fuel_unit="gal",
                fuel_type="diesel",
                equipment_hours=round(crop_data["typical_area"] * 1.5, 1),
                efficiency="normal",
                observation=f"Post-harvest washing and packing for {crop_slug}",
                extra_data={
                    "processing_steps": ["washing", "sorting", "grading", "packing"],
                    "equipment_used": "wash_line",
                    "packaging_type": "clamshell_or_carton",
                    "cold_storage": True,
                },
            ),
        }
    )
    events.extend(get_shared_extra_events(crop_slug, crop_data, start_order=8, crop_category="vegetable"))
    return events


def get_berry_events(crop_slug, crop_data):
    """Generate events for berry crops (strawberries)"""
    events = [
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
                area_covered=crop_data["typical_area"],
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
                fuel_unit="kWh",
                fuel_type="electric",
                irrigation_method="drip",
                irrigation_depth=0.5,
                observation=f"Precision irrigation for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 24,
                    "water_volume_total": 300000,
                    "water_volume_unit": "gallons",
                },
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
    events.extend(get_shared_extra_events(crop_slug, crop_data, start_order=7, crop_category="berry"))
    return events


def get_fiber_events(crop_slug, crop_data):
    """Generate events for fiber crops (cotton)"""
    events = [
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
                area_covered=crop_data["typical_area"],
                crop_growth_stage="flowering",
                observation=f"Pest scouting for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 10,
                    "pest_species_observed": crop_data["common_pests"],
                    "average_pest_pressure": "medium",
                    "area_covered_total": crop_data["typical_area"],
                    "area_unit": "ha",
                    "carbon_impact": "zero",
                },
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
                fuel_consumed=30.0,
                fuel_unit="kWh",
                fuel_type="electric",
                irrigation_method="furrow",
                irrigation_depth=3.0,
                observation=f"Furrow irrigation for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 8,
                    "water_volume_total": 1500000,
                    "water_volume_unit": "gallons",
                },
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
    events.extend(get_shared_extra_events(crop_slug, crop_data, start_order=7, crop_category="grain"))
    return events


# =============================================================================
# SECTION 4: COMMAND CLASS
# =============================================================================


class Command(BaseCommand):
    help = "Create comprehensive production templates V3 with complete backend_event_fields for ALL 7 event types"

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
        parser.add_argument(
            "--cleanup-v2",
            action="store_true",
            help="Remove old V2 templates after creating V3",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        specific_crop = options.get("crop")
        force = options.get("force", False)
        cleanup_v2 = options.get("cleanup_v2", False)

        self.stdout.write(
            self.style.NOTICE(f"\n{'='*60}\n" f"Production Templates V3 - All 7 Event Types\n" f"{'='*60}\n")
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
        event_type_counts = {}

        with transaction.atomic():
            for crop_type in crop_types:
                crop_slug = crop_type.slug

                # Check if we have customization data for this crop
                if crop_slug not in CROP_CUSTOMIZATIONS:
                    self.stdout.write(self.style.WARNING(f"  No customization data for {crop_slug}, using defaults"))
                    crop_data = CROP_CUSTOMIZATIONS.get("corn_field", list(CROP_CUSTOMIZATIONS.values())[0])
                else:
                    crop_data = CROP_CUSTOMIZATIONS[crop_slug]

                template_slug = f"{crop_slug}_conventional_v3"

                # Handle force mode
                if force:
                    existing = ProductionTemplate.objects.filter(slug=template_slug)
                    if existing.exists():
                        if not dry_run:
                            existing.delete()
                            self.stdout.write(f"  Deleted existing template: {template_slug}")

                # Create template
                template_data = {
                    "name": f"{crop_type.name} - Conventional Production",
                    "farming_approach": "conventional",
                    "description": (
                        f"Comprehensive production template for {crop_type.name.lower()} "
                        f"covering all 7 event types with real-world field defaults."
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
                        f"V3 template: all 7 event types, real commercial products, "
                        f"USDA-verified emission factors. "
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
                    events_data = get_fiber_events(crop_slug, crop_data)
                else:
                    events_data = get_fiber_events(crop_slug, crop_data)

                # Create event templates
                crop_event_count = 0
                for event_data in events_data:
                    evt_type = event_data["backend_event_type"]
                    subtype = event_data["backend_event_fields"].get(
                        "type", event_data["backend_event_fields"].get("activity_type", "N/A")
                    )

                    # Auto-populate typical_amounts and carbon_sources
                    if not event_data.get("typical_amounts"):
                        event_data["typical_amounts"] = get_typical_amounts(
                            evt_type, subtype, crop_data["typical_area"], crop_data
                        )
                    if not event_data.get("carbon_sources"):
                        event_data["carbon_sources"] = get_carbon_sources(evt_type, subtype)

                    if dry_run:
                        self.stdout.write(
                            f"    [DRY RUN] Would create: {event_data['name']} "
                            f"(backend_type={evt_type}, subtype={subtype})"
                        )
                        created_events += 1
                        crop_event_count += 1
                    else:
                        event_data["production_template"] = template
                        event, event_created = EventTemplate.objects.get_or_create(
                            production_template=template,
                            name=event_data["name"],
                            defaults=event_data,
                        )
                        if event_created:
                            created_events += 1
                            crop_event_count += 1
                            self.stdout.write(
                                f"    Event: {event.name} "
                                f"(type={event.backend_event_type}, subtype={subtype}, "
                                f"fields={len(event.backend_event_fields or {})})"
                            )

                    # Track event type distribution
                    event_type_counts[evt_type] = event_type_counts.get(evt_type, 0) + 1

                self.stdout.write(f"    -> {crop_event_count} events for {crop_type.name}")

            # Cleanup V2 templates if requested
            if cleanup_v2 and not dry_run:
                v2_count = ProductionTemplate.objects.filter(slug__endswith="_conventional_v2").delete()[0]
                self.stdout.write(self.style.WARNING(f"\n  Cleaned up {v2_count} V2 templates"))

        # Summary
        type_names = {
            0: "Weather",
            1: "Production",
            2: "Chemical",
            3: "General",
            5: "Soil",
            6: "Pest",
            7: "Business",
        }
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{'='*60}\n"
                f"V3 Production Templates Creation Complete!\n"
                f"{'='*60}\n"
                f"Created: {created_templates} production templates\n"
                f"Created: {created_events} event templates\n"
                f"Skipped: {skipped_templates} existing templates\n"
            )
        )

        if event_type_counts:
            self.stdout.write("\nEvent type distribution:")
            for etype, count in sorted(event_type_counts.items()):
                self.stdout.write(f"  {type_names.get(etype, f'Type {etype}')}: {count} events")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN COMPLETE - Run without --dry-run to create records"))
