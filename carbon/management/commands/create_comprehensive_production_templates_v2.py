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
        # ⚠️ `organic_pesticide` is read by nothing; the organic citrus programme comes from
        # ORGANIC_OVERRIDES. Left in place, but it reaches no template.
        "organic_pesticide": "Surround WP (kaolin clay)",
        # Was `organic_pesticide`, while the material this event actually renders is Delegate WG
        # below — spinetoram, which is NOT on the National List (only Spinosad is). The event was
        # telling a conventional grower their insecticide was organic-approved. Fixed 2026-08-18.
        "pesticide_subtype": "synthetic_pesticide",
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
        "npk": "12-12-17",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 12.0,
        "potassium_pct": 17.0,
        "commercial_name": "YaraMila Complex 12-11-18",
        "secondary_fertilizer": "Urea 46-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Luna Sensation (fluopyram + trifloxystrobin)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Walnut blight, Botryosphaeria",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Intrepid 2F (methoxyfenozide)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Codling moth, walnut husk fly",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Codling moth, walnut husk fly, aphids",
        "common_pests": "Codling moth, walnut husk fly, scale, mites",
        "beneficial_insects": "Trichogramma wasps, predatory mites",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "flood",
        "water_source": "well_groundwater",
        "soil_type": "clay_loam",
        "typical_area": 20.0,
        "region": "Sacramento Valley, California",
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
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "YaraMila Complex 12-11-18",
        "secondary_fertilizer": "Calcium Ammonium Nitrate 27-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Captan 50W",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Brown rot, peach leaf curl",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Imidan 70-W (phosmet)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Oriental fruit moth, plum curculio",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Oriental fruit moth, plum curculio, peach twig borer",
        "common_pests": "Oriental fruit moth, plum curculio, aphids, scale",
        "beneficial_insects": "Trichogramma wasps, lacewings",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "sandy_loam",
        "typical_area": 12.0,
        "region": "San Joaquin Valley, California",
        "timing_soil": "November - December",
        "timing_plant": "January - February",
        "timing_fertilize": "February - April",
        "timing_irrigate": "April - September",
        "timing_pest": "March - August",
        "timing_harvest": "May - September",
        "yield_per_ha": 15.0,
        "yield_unit": "tons",
    },
    # MIXED VEGETABLES
    "mixed_vegetables": {
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Dr. Earth Organic 5 Tomato Vegetable & Herb 4-6-3",
        "secondary_fertilizer": "Fish Bone Meal 3-16-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Bonide Copper Fungicide",
        "fungicide_subtype": "copper_fungicide",
        "fungicide_target": "Downy mildew, early blight",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Sevin (carbaryl)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Aphids, caterpillars, beetles",
        "herbicide": "Prowl H2O (pendimethalin)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Aphids, whiteflies, caterpillars",
        "common_pests": "Aphids, whiteflies, flea beetles, cabbage worms",
        "beneficial_insects": "Ladybugs, lacewings, parasitic wasps",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "loam",
        "typical_area": 5.0,
        "region": "Salinas Valley, California",
        "timing_soil": "February - March",
        "timing_plant": "March - May",
        "timing_fertilize": "At planting + monthly",
        "timing_irrigate": "Year-round",
        "timing_pest": "April - October",
        "timing_harvest": "May - November",
        "yield_per_ha": 25.0,
        "yield_unit": "tons",
    },
    # === NON-CALIFORNIA REGIONS ===
    # Without an entry here a crop silently inherits corn_field's Midwest defaults
    # (see the `crop_slug not in CROP_CUSTOMIZATIONS` fallback in handle()), which
    # would have given an Oregon hazelnut grower a corn calendar and corn products.
    # Regions and timings below are the real production windows, not California's.
    "pecans": {
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "YaraMila Complex 12-11-18",
        "secondary_fertilizer": "Ammonium Sulfate 21-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Absolute Maxx (tebuconazole + trifloxystrobin)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Pecan scab, downy spot",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Intrepid 2F (methoxyfenozide)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Pecan nut casebearer, pecan weevil",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Pecan nut casebearer, pecan weevil, aphids",
        "common_pests": "Pecan nut casebearer, pecan weevil, black aphid, mites",
        "beneficial_insects": "Trichogramma wasps, lady beetles",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "micro_sprinkler",
        "water_source": "well_groundwater",
        "soil_type": "sandy_loam",
        "typical_area": 40.0,
        "region": "Southeast / Texas",
        "timing_soil": "December - January",
        "timing_plant": "January - February",
        "timing_fertilize": "March - June",
        "timing_irrigate": "May - October",
        "timing_pest": "April - September",
        "timing_harvest": "October - December",
        "yield_per_ha": 2.2,
        "yield_unit": "tons",
    },
    "hazelnuts": {
        "npk": "16-16-16",
        "nitrogen_pct": 16.0,
        "phosphorus_pct": 16.0,
        "potassium_pct": 16.0,
        "commercial_name": "YaraMila Complex 12-11-18",
        "secondary_fertilizer": "Urea 46-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Rally 40WSP (myclobutanil)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Eastern Filbert Blight",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Warrior II (lambda-cyhalothrin)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Filbertworm, filbert aphid",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Filbertworm, filbert aphid, big bud mite",
        "common_pests": "Filbertworm, filbert aphid, big bud mite",
        "beneficial_insects": "Trioxys pallidus, lady beetles",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "silt_loam",
        "typical_area": 20.0,
        "region": "Willamette Valley, Oregon",
        "timing_soil": "November - December",
        "timing_plant": "December - February",
        "timing_fertilize": "March - May",
        "timing_irrigate": "June - September",
        "timing_pest": "May - August",
        "timing_harvest": "September - October",
        "yield_per_ha": 2.8,
        "yield_unit": "tons",
    },
    "blueberries": {
        "npk": "12-4-8",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 4.0,
        "potassium_pct": 8.0,
        "commercial_name": "Ammonium Sulfate 21-0-0 (acidifying)",
        "secondary_fertilizer": "Sulfur-coated urea",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Switch 62.5WG (cyprodinil + fludioxonil)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Botrytis, anthracnose, mummy berry",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Delegate WG (spinetoram)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Spotted wing drosophila",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Spotted wing drosophila, blueberry maggot",
        "common_pests": "Spotted wing drosophila, blueberry maggot, aphids",
        "beneficial_insects": "Lady beetles, lacewings",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "sandy_loam",
        "typical_area": 10.0,
        "region": "Michigan / Pacific Northwest",
        "timing_soil": "March - April",
        "timing_plant": "April - May",
        "timing_fertilize": "April - June",
        "timing_irrigate": "May - September",
        "timing_pest": "June - August",
        "timing_harvest": "June - August",
        "yield_per_ha": 12.0,
        "yield_unit": "tons",
    },
    "hops": {
        "npk": "20-10-20",
        "nitrogen_pct": 20.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 20.0,
        "commercial_name": "YaraMila Complex 12-11-18",
        "secondary_fertilizer": "Urea 46-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Quintec (quinoxyfen)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Powdery mildew, downy mildew",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Movento (spirotetramat)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Hop aphid, twospotted spider mite",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Hop aphid, twospotted spider mite",
        "common_pests": "Hop aphid, twospotted spider mite, powdery mildew",
        "beneficial_insects": "Predatory mites, lady beetles",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "surface_water",
        "soil_type": "silt_loam",
        "typical_area": 40.0,
        "region": "Yakima Valley, Washington",
        "timing_soil": "February - March",
        "timing_plant": "March - April",
        "timing_fertilize": "April - June",
        "timing_irrigate": "May - August",
        "timing_pest": "May - August",
        "timing_harvest": "August - September",
        "yield_per_ha": 2.4,
        "yield_unit": "tons",
    },
    "spinach": {
        "npk": "15-15-15",
        "nitrogen_pct": 15.0,
        "phosphorus_pct": 15.0,
        "potassium_pct": 15.0,
        "commercial_name": "YaraMila Complex 12-11-18",
        "secondary_fertilizer": "Calcium Nitrate 15.5-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Ridomil Gold (mefenoxam)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Downy mildew (Peronospora)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Radiant SC (spinetoram)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Leafminer, armyworm, aphids",
        "herbicide": "Dual Magnum (S-metolachlor)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Leafminer, beet armyworm, green peach aphid",
        "common_pests": "Leafminer, armyworm, aphids, downy mildew",
        "beneficial_insects": "Lady beetles, parasitic wasps",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "sprinkler",
        "water_source": "surface_water",
        "soil_type": "silt_loam",
        "typical_area": 25.0,
        "region": "Yuma, Arizona / Texas",
        "timing_soil": "September - October",
        "timing_plant": "October - January",
        "timing_fertilize": "November - February",
        "timing_irrigate": "November - March",
        "timing_pest": "December - February",
        "timing_harvest": "November - March",
        "yield_per_ha": 18.0,
        "yield_unit": "tons",
    },
    # ---------------------------------------------------------------------------
    # California perennial specialty crops — added 2026-08-07 alongside their catalog entries.
    #
    # SCOPE OF WHAT IS ASSERTED HERE. Timing, pest/disease targets, irrigation method and harvest
    # window are established agronomy for these CA systems. The PRODUCT NAMES are standard,
    # registered choices offered as a STARTING POINT — a template is opt-in and the grower edits
    # it before anything is written. That distinction is the whole lesson of the Smart Setup
    # incident: the defect was auto-applying backdated records attributed to the farmer by name,
    # not the existence of a suggested product.
    # ---------------------------------------------------------------------------
    "pistachios": {
        "npk": "15-15-15",
        "nitrogen_pct": 15.0,
        "phosphorus_pct": 15.0,
        "potassium_pct": 15.0,
        "commercial_name": "Triple 15 Blend 15-15-15",
        "secondary_fertilizer": "UAN 32-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Quadris Top (azoxystrobin + difenoconazole)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Botryosphaeria panicle and shoot blight, Alternaria late blight",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Intrepid 2F (methoxyfenozide)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Navel orangeworm, leaffooted plant bug",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Navel orangeworm (Amyelois transitella)",
        "common_pests": "Navel orangeworm, leaffooted bug, stink bugs, mites",
        "beneficial_insects": "Trichogramma wasps, predatory mites",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "sandy_loam",
        "typical_area": 40.0,
        "region": "San Joaquin Valley, California",
        "timing_soil": "December - January",
        "timing_plant": "January - February",
        "timing_fertilize": "March - June",
        "timing_irrigate": "April - September",
        "timing_pest": "May - August",
        "timing_harvest": "August - October",
        "yield_per_ha": 2500.0,
        "yield_unit": "kg",
    },
    "olives": {
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Balanced Blend 10-10-10",
        "secondary_fertilizer": "Urea 46-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Kocide 3000 (copper hydroxide)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Olive knot, peacock spot (Spilocaea oleagina)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "GF-120 NF Naturalyte Fruit Fly Bait (spinosad)",
        # Spinosad IS on the National List, and GF-120 is the standard olive fruit fly bait in
        # conventional and organic groves alike. The `synthetic_pesticide` label was invisible
        # while the material rendered as "Targeted insecticide"; now that the material shows, the
        # label shows with it — and it also selects the emission factor. Fixed 2026-08-18.
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Olive fruit fly (Bactrocera oleae)",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Olive fruit fly (Bactrocera oleae)",
        "common_pests": "Olive fruit fly, black scale, olive knot",
        "beneficial_insects": "Parasitic wasps, lacewings",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "clay_loam",
        "typical_area": 20.0,
        "region": "Sacramento Valley, California",
        "timing_soil": "December - January",
        "timing_plant": "February - March",
        "timing_fertilize": "March - May",
        "timing_irrigate": "May - October",
        "timing_pest": "June - October",
        "timing_harvest": "September - December",
        "yield_per_ha": 6000.0,
        "yield_unit": "kg",
    },
    "dates": {
        "npk": "12-12-17",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 12.0,
        "potassium_pct": 17.0,
        "commercial_name": "YaraMila Complex 12-11-18",
        "secondary_fertilizer": "Urea 46-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        # Elemental sulfur is a mineral ON the National List, not a synthetic — on both the
        # fungicide and the miticide line. The pesticide label was invisible until the material
        # started rendering (it used to fall back to "Targeted insecticide"); the fungicide label
        # has been visible and wrong all along. Both fixed 2026-08-18.
        "primary_fungicide": "Elemental sulfur dust",
        "fungicide_subtype": "sulfur_fungicide",
        "fungicide_target": "Black scorch, inflorescence rot",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Elemental sulfur dust",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Old world date mite (Oligonychus afrasiaticus)",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Old world date mite (Oligonychus afrasiaticus)",
        "common_pests": "Date mite, nitidulid beetles, scale",
        "beneficial_insects": "Predatory mites",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "flood",
        "water_source": "well_groundwater",
        "soil_type": "sandy_loam",
        "typical_area": 20.0,
        "region": "Coachella Valley, California",
        "timing_soil": "December - January",
        "timing_plant": "February - April",
        "timing_fertilize": "February - June",
        "timing_irrigate": "March - October",
        "timing_pest": "May - August",
        "timing_harvest": "September - November",
        "yield_per_ha": 9000.0,
        "yield_unit": "kg",
    },
    "figs": {
        "npk": "10-10-10",
        "nitrogen_pct": 10.0,
        "phosphorus_pct": 10.0,
        "potassium_pct": 10.0,
        "commercial_name": "Balanced Blend 10-10-10",
        "secondary_fertilizer": "Urea 46-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        # Elemental sulfur is a mineral on the National List, not a synthetic. Fixed 2026-08-18.
        # The insecticide here (Malathion) genuinely is synthetic and keeps its label.
        "primary_fungicide": "Elemental sulfur dust",
        "fungicide_subtype": "sulfur_fungicide",
        "fungicide_target": "Fig souring, Botrytis limb blight",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Malathion 8 Aquamul",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Dried fruit beetle (Carpophilus spp.)",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Dried fruit beetle (Carpophilus spp.)",
        "common_pests": "Dried fruit beetle, spider mites, fig mosaic",
        "beneficial_insects": "Predatory mites, lacewings",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "sandy_loam",
        "typical_area": 15.0,
        "region": "San Joaquin Valley, California",
        "timing_soil": "December - January",
        "timing_plant": "January - February",
        "timing_fertilize": "March - June",
        "timing_irrigate": "April - September",
        "timing_pest": "June - August",
        "timing_harvest": "June - September",
        "yield_per_ha": 8000.0,
        "yield_unit": "kg",
    },
    "pomegranates": {
        "npk": "15-15-15",
        "nitrogen_pct": 15.0,
        "phosphorus_pct": 15.0,
        "potassium_pct": 15.0,
        "commercial_name": "Triple 15 Blend 15-15-15",
        "secondary_fertilizer": "UAN 32-0-0",
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Quadris Top (azoxystrobin + difenoconazole)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Alternaria heart rot, Botrytis",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "primary_pesticide": "Intrepid 2F (methoxyfenozide)",
        "pesticide_subtype": "synthetic_pesticide",
        "pesticide_target": "Omnivorous leafroller, leaffooted plant bug",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Leaffooted plant bug (Leptoglossus zonatus)",
        "common_pests": "Leaffooted bug, omnivorous leafroller, filbertworm, mites",
        "beneficial_insects": "Trichogramma wasps, lacewings",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "drip",
        "water_source": "well_groundwater",
        "soil_type": "clay_loam",
        "typical_area": 20.0,
        "region": "San Joaquin Valley, California",
        "timing_soil": "December - January",
        "timing_plant": "February - March",
        "timing_fertilize": "March - June",
        "timing_irrigate": "April - October",
        "timing_pest": "May - September",
        "timing_harvest": "September - November",
        "yield_per_ha": 20000.0,
        "yield_unit": "kg",
    },
    # ---------------------------------------------------------------------------
    # Pears — added 2026-08-18 alongside the catalog entry. Pacific Northwest programme, not a
    # California one: the target cohort is Washington's Wenatchee/Okanogan and Yakima valleys
    # (`documentation/gtm-v3/NAMED-LIST-2026-09.md`, tier T1). `typical_area` is the measured
    # median of those 62 farms — 67 acres ≈ 27 ha — not a round guess.
    # ---------------------------------------------------------------------------
    "pears": {
        "npk": "12-12-12",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 12.0,
        "potassium_pct": 12.0,
        "commercial_name": "Pome Fruit Blend 12-12-12",
        # The secondary-fertigation event reads `secondary_npk` / `secondary_*_pct` and falls
        # back to the PRIMARY analysis when they are missing (line ~2531) — which would print
        # "Calcium Nitrate 15.5-0-0" at 12-12-12 with 12% N, a wrong analysis attached to a named
        # product, and feed that N figure to the carbon calculation. 11 other entries in this
        # dict have exactly that mismatch today (pistachios, olives, dates, figs, pomegranates,
        # pecans, hazelnuts, hops, blueberries, spinach, mixed_vegetables) — separate fix.
        "secondary_fertilizer": "Calcium Nitrate 15.5-0-0",
        "secondary_npk": "15.5-0-0",
        "secondary_nitrogen_pct": 15.5,
        "secondary_phosphorus_pct": 0.0,
        "secondary_potassium_pct": 0.0,
        "slow_release_fertilizer": "Osmocote Plus 15-9-12",
        "primary_fungicide": "Ziram 76DF (ziram)",
        "fungicide_subtype": "synthetic_fungicide",
        "fungicide_target": "Pear scab (Venturia pirina), Fabraea leaf spot",
        "copper_fungicide": "Kocide 3000 (copper hydroxide)",
        "copper_target": "Fire blight (Erwinia amylovora) — dormant and delayed dormant",
        # `synthetic_pesticide` is the most specific key the insecticide event reads; it also
        # accepts `primary_pesticide` since the 2026-08-18 fallback fix, which is what the other
        # 13 crops use. Verified by reading the generated event rows, not by trusting the dict.
        "pesticide_subtype": "synthetic_pesticide",
        "synthetic_pesticide": "Movento HL (spirotetramat)",
        "synthetic_pesticide_target": "Pear psylla (Cacopsylla pyricola), pear rust mite",
        "herbicide": "Roundup PowerMax 3 (glyphosate)",
        "herbicide_subtype": "synthetic_herbicide",
        "primary_pest_species": "Pear psylla (Cacopsylla pyricola)",
        "common_pests": "Pear psylla, codling moth, pear rust mite, leafrollers",
        "beneficial_insects": "Anthocoris and Deraeocoris predatory bugs, predatory mites, lacewings",
        "beneficial_release_quantity": "per hectare",
        "certification_type": "global_gap",
        "certification_standard": "GLOBALG.A.P. IFA v6",
        "certification_body": "SCS Global Services",
        "irrigation_method": "sprinkler",
        "water_source": "surface_water",
        "soil_type": "sandy_loam",
        "typical_area": 27.0,
        "region": "Wenatchee, Okanogan and Yakima valleys, Washington",
        "timing_soil": "November - February",
        "timing_plant": "March - April",
        "timing_fertilize": "March - May",
        "timing_irrigate": "April - September",
        "timing_pest": "April - August",
        "timing_harvest": "August - September",
        "yield_per_ha": 35.0,
        "yield_unit": "tons",
    },
}

# Alias: DB has both "avocado" (singular) and "avocados" (plural) slugs
CROP_CUSTOMIZATIONS["avocado"] = CROP_CUSTOMIZATIONS["avocados"]

# Organic input overrides keyed by crop_slug.
# Only crops listed here get an organic template.  All inputs must be
# OMRI-listed or NOP-approved (7 CFR Part 205).
ORGANIC_OVERRIDES = {
    # Tree nuts are the GTM ICP (mid-size CA wholesale orchards) and had NO organic template
    # at all — 27 of the 33 shipped templates were conventional, and the 6 organic ones covered
    # apples, avocados, citrus, lettuce, strawberries and tomatoes. So an organic walnut grower
    # opening the flagship "Smart Setup" flow was offered "Walnuts - Conventional Production",
    # whose input list includes glyphosate. Inputs below are drawn from the CA organic walnut
    # season validated end-to-end on 2026-08-02 (NOP audit export + CA PUR both clean).
    "walnuts": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        # Walnut blight is THE walnut disease; copper is the backbone of organic control and
        # Serenade is the OMRI biological used alongside it.
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Walnut blight (Xanthomonas arboricola pv. juglandis)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Walnut blight (Xanthomonas arboricola pv. juglandis)",
        # Spinosad at hullsplit is the one conventional-equivalent spray an organic walnut
        # grower actually makes; everything before it is monitoring and biological control.
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Navel orangeworm (Amyelois transitella), codling moth",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,  # No synthetic herbicides in organic
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "almonds": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        # Almonds swap walnut blight for the bloom-time brown rot / shot hole complex.
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Brown rot blossom blight (Monilinia laxa), shot hole",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Shot hole (Wilsonomyces carpophilus), bacterial spot (Xanthomonas arboricola pv. pruni)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Navel orangeworm (Amyelois transitella), peach twig borer",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    # Pacific Northwest gap, same defect as the tree nuts above: grapes, blueberries and hops
    # all had a CONVENTIONAL-only template whose input list includes Roundup PowerMax 3
    # (glyphosate), a 7 CFR 205.105 prohibited substance. An organic grower in Yakima or the
    # Willamette Valley opening "Smart Setup" was offered exactly one template, and it was a
    # prohibited-input one.
    "grapes": {
        # Vineyard N demand is low; compost plus a light organic granular is the norm.
        "primary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "npk": "8-2-4",
        "nitrogen_pct": 8.0,
        "phosphorus_pct": 2.0,
        "potassium_pct": 4.0,
        "secondary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "secondary_npk": "2-3-1",
        "secondary_n": 2.0,
        "secondary_p": 3.0,
        "secondary_k": 1.0,
        "slow_release_fertilizer": "Down To Earth Bio-Fish 7-7-2 — OMRI Listed",
        # Powdery mildew IS the grape disease, and micronized sulfur is the backbone of organic
        # control — hence `sulfur_fungicide`, which the chemical form already offers as a
        # subtype (config/events/enums.ts FU list). Do not write a subtype the form lacks.
        "primary_fungicide": "Microthiol Disperss (micronized sulfur) — OMRI Listed",
        "fungicide_subtype": "sulfur_fungicide",
        "fungicide_target": "Powdery mildew (Erysiphe necator)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Downy mildew (Plasmopara viticola), Botrytis bunch rot",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Grape leafhopper (Erythroneura elegantula), Western grapeleaf skeletonizer",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,  # No synthetic herbicides in organic
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "blueberries": {
        # Blueberries want an acidic, high-N program; Acid Mix is the OMRI equivalent of the
        # ammonium-sulfate acidifier the conventional template uses.
        "primary_fertilizer": "Down To Earth Acid Mix 4-3-6 — OMRI Listed",
        "npk": "4-3-6",
        "nitrogen_pct": 4.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 6.0,
        "secondary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "secondary_npk": "2-3-1",
        "secondary_n": 2.0,
        "secondary_p": 3.0,
        "secondary_k": 1.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis) — OMRI Listed",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Mummy berry (Monilinia vaccinii-corymbosi), Botrytis blossom blight",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Anthracnose fruit rot (Colletotrichum acutatum)",
        # Spotted wing drosophila is the pest that decides whether an organic blueberry block
        # is harvestable, and Entrust is the primary organic tool against it.
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Spotted wing drosophila (Drosophila suzukii)",
        "biological_pesticide": "Grandevo WDG (Chromobacterium subtsugae) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Oregon Tilth Certified Organic (OTCO)",
    },
    "hops": {
        # Hops are heavy N feeders; Nature Safe 13-0-0 is the OMRI feather-meal equivalent of
        # the urea the conventional template reaches for.
        "primary_fertilizer": "Nature Safe 13-0-0 Organic",
        "npk": "13-0-0",
        "nitrogen_pct": 13.0,
        "phosphorus_pct": 0.0,
        "potassium_pct": 0.0,
        "secondary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "secondary_npk": "2-3-1",
        "secondary_n": 2.0,
        "secondary_p": 3.0,
        "secondary_k": 1.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        "primary_fungicide": "Microthiol Disperss (micronized sulfur) — OMRI Listed",
        "fungicide_subtype": "sulfur_fungicide",
        "fungicide_target": "Hop powdery mildew (Podosphaera macularis)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Hop downy mildew (Pseudoperonospora humuli)",
        "primary_pesticide": "PyGanic EC 5.0 II (pyrethrins) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Hop aphid (Phorodon humuli)",
        "biological_pesticide": "Mycotrol ESO (Beauveria bassiana) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        # Yakima Valley — WSDA runs the state organic program growers here certify under.
        "certification_body": "Washington State Department of Agriculture (WSDA) Organic Program",
    },
    # "Stone Fruit" is the ONLY catalogue entry a cherry, peach, plum or apricot grower can
    # pick — there is no separate cherries crop type — so a conventional-only Stone Fruit
    # template left that entire segment (including WA sweet cherries) with Captan, Imidan and
    # glyphosate as their one offered starting point.
    "stone_fruit": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        # Brown rot blossom blight is the disease that decides a stone-fruit crop; Serenade at
        # bloom plus dormant copper is the standard organic program, replacing Captan.
        "primary_fungicide": "Serenade ASO (Bacillus subtilis) — OMRI Listed",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Brown rot blossom blight (Monilinia fructicola)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Bacterial canker (Pseudomonas syringae), shot hole (Wilsonomyces carpophilus)",
        # Replaces Imidan (phosmet). Spinosad covers oriental fruit moth and, on cherries,
        # spotted wing drosophila — the pest that decides whether the block is packable.
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Oriental fruit moth (Grapholita molesta), spotted wing drosophila (Drosophila suzukii)",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "hazelnuts": {
        # Willamette Valley. Hazelnuts are moderate N feeders on a single annual application.
        "primary_fertilizer": "Nature Safe 13-0-0 Organic",
        "npk": "13-0-0",
        "nitrogen_pct": 13.0,
        "phosphorus_pct": 0.0,
        "potassium_pct": 0.0,
        "secondary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "secondary_npk": "2-3-1",
        "secondary_n": 2.0,
        "secondary_p": 3.0,
        "secondary_k": 1.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis) — OMRI Listed",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Bacterial blight (Xanthomonas arboricola pv. corylina)",
        # Eastern filbert blight is the disease that ends hazelnut blocks; organic programs
        # lean on resistant cultivars plus copper timed to bud break.
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Eastern filbert blight (Anisogramma anomala)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Filbertworm (Cydia latiferreana)",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Oregon Tilth Certified Organic (OTCO)",
    },
    "pecans": {
        "primary_fertilizer": "Nature Safe 13-0-0 Organic",
        "npk": "13-0-0",
        "nitrogen_pct": 13.0,
        "phosphorus_pct": 0.0,
        "potassium_pct": 0.0,
        "secondary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "secondary_npk": "2-3-1",
        "secondary_n": 2.0,
        "secondary_p": 3.0,
        "secondary_k": 1.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        # Pecan scab is the yield-limiting disease across the humid Southeast; sulfur and
        # copper are the two materials an organic grower actually has for it.
        "primary_fungicide": "Microthiol Disperss (micronized sulfur) — OMRI Listed",
        "fungicide_subtype": "sulfur_fungicide",
        "fungicide_target": "Pecan scab (Venturia effusa)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Pecan scab (Venturia effusa), bacterial leaf scorch",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Pecan nut casebearer (Acrobasis nuxvorella)",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Texas Department of Agriculture (TDA) Organic Program",
    },
    "avocados": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 5-5-5",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Phytophthora cinnamomi root rot",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Anthracnose (Colletotrichum gloeosporioides), Canker",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Avocado thrips, Persea mite",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis)",
        "herbicide": None,  # No synthetic herbicides in organic
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    # DB slug for citrus is citrus_oranges (see populate_usda_crop_types)
    "citrus_oranges": {
        "primary_fertilizer": "Neptune's Harvest Fish Fertilizer 2-4-1",
        "npk": "2-4-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 4.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Down To Earth Citrus Mix 6-3-3",
        "secondary_npk": "6-3-3",
        "secondary_n": 6.0,
        "secondary_p": 3.0,
        "secondary_k": 3.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Phytophthora brown rot, citrus canker",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Melanose (Diaporthe citri), citrus brown rot (Phytophthora spp.)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Citrus leafminer, Asian citrus psyllid",
        "biological_pesticide": "Bt kurstaki (DiPel DF) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "apples": {
        "primary_fertilizer": "North Country Organics Pro-Start 2-3-3",
        "npk": "2-3-3",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 3.0,
        "secondary_fertilizer": "Fertrell Super N 4-2-4",
        "secondary_npk": "4-2-4",
        "secondary_n": 4.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        "primary_fungicide": "Regalia (Reynoutria sachalinensis extract)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Apple scab, fire blight, powdery mildew",
        "copper_fungicide": "Badge X2 (copper hydroxide) — OMRI Listed",
        "copper_target": "Fire blight (Erwinia amylovora), apple scab (Venturia inaequalis)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Codling moth, apple maggot, leafrollers",
        "biological_pesticide": "Madex HP (Cydia pomonella granulovirus) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Oregon Tilth Certified Organic (OTCO)",
    },
    "strawberries": {
        "primary_fertilizer": "Neptune's Harvest Strawberry & Berry 3-1-2",
        "npk": "3-1-2",
        "nitrogen_pct": 3.0,
        "phosphorus_pct": 1.0,
        "potassium_pct": 2.0,
        "secondary_fertilizer": "Down To Earth Fish Bone Meal 3-16-0",
        "secondary_npk": "3-16-0",
        "secondary_n": 3.0,
        "secondary_p": 16.0,
        "secondary_k": 0.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        "primary_fungicide": "Regalia (Reynoutria sachalinensis extract)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Botrytis gray mold, powdery mildew",
        "copper_fungicide": "Badge X2 (copper hydroxide) — OMRI Listed",
        "copper_target": "Angular leaf spot (Xanthomonas fragariae), anthracnose (Colletotrichum acutatum)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Spotted wing drosophila, lygus bugs",
        "biological_pesticide": "Bt kurstaki (DiPel DF) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "lettuce": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 5 Vegetable 4-6-3",
        "primary_fungicide": "Actinovate AG (Streptomyces lydicus)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Downy mildew, lettuce drop (Sclerotinia)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Bacterial leaf spot (Xanthomonas campestris pv. vitians)",
        "primary_pesticide": "PyGanic (pyrethrins) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Aphids, leafminers, thrips",
        "biological_pesticide": "Bt kurstaki (DiPel DF) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "tomatoes": {
        "primary_fertilizer": "Neptune's Harvest Tomato & Veg 2-4-2",
        "npk": "2-4-2",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 4.0,
        "potassium_pct": 2.0,
        "secondary_fertilizer": "Down To Earth Fish Bone Meal 3-16-0",
        "secondary_npk": "3-16-0",
        "secondary_n": 3.0,
        "secondary_p": 16.0,
        "secondary_k": 0.0,
        "slow_release_fertilizer": "Dr. Earth Organic 5 Vegetable 4-6-3",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Early blight, late blight, Septoria leaf spot",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Bacterial speck (Pseudomonas syringae pv. tomato), bacterial spot (Xanthomonas spp.)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Tomato hornworm, Colorado potato beetle",
        "biological_pesticide": "Bt kurstaki (DiPel DF) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    # ---------------------------------------------------------------------------
    # Organic VEGETABLE variants — carrots, onions, spinach, potatoes. Added 2026-08-21
    # (F4, Calapooia Bend rehearsal).
    #
    # These four shipped with a CONVENTIONAL template and nothing else, so an organic
    # vegetable grower starting a spring season was offered exactly one plan — one whose
    # items include "Herbicide Application", "Pesticide Treatment", "Fungicide Treatment"
    # and a GLOBALG.A.P. audit. A template only writes a season PLAN, never a record, so
    # nothing false was logged; the cost is that the checklist an organic grower works from
    # starts wrong and every practice their season actually turns on is missing. Mid-size
    # organic vegetable operations are squarely in the ICP.
    #
    # Every SPRAY named below resolves on the seeded National List — Spinosad, Microbial
    # products (Bacillus thuringiensis, etc.), Copper hydroxide, Insecticidal soaps,
    # Horticultural oils, Elemental sulfur, Peracetic acid. Materials commonly assumed to be
    # organic but absent from the seed (kaolin, neem, pyrethrum, Reynoutria, Chromobacterium)
    # are deliberately NOT used here: an input the classifier cannot place prints as
    # "Self-reported" in the certifier packet, which defeats the point of suggesting it.
    # Fertility inputs (fish, feather meal, compost) are non-synthetic and are not § 205.601
    # entries at all, which is why they are named freely — the same as the existing
    # lettuce/tomato/strawberry entries.
    #
    # Three optional keys are read by `get_annual_crop_organic_events` and gate the
    # vegetable-specific events, so adding them here does not change any template that does
    # not declare them:
    #   uses_flame_weeding    -> pre-emergence flame weeding (CU)
    #   compost_material      -> purchased-compost application (soil OM)
    #   wash_water_sanitizer  -> post-harvest wash + sanitizer (PH). Absent for onions,
    #                            which are field- and shed-CURED, never washed.
    # ---------------------------------------------------------------------------
    "carrots": {
        # Feather meal pre-plant for slow-release N, fish emulsion as the side-dress —
        # the standard PNW organic carrot fertility program.
        "primary_fertilizer": "Down To Earth Feather Meal 12-0-0 — OMRI Listed",
        "npk": "12-0-0",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 0.0,
        "potassium_pct": 0.0,
        "secondary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "secondary_npk": "2-3-1",
        "secondary_n": 2.0,
        "secondary_p": 3.0,
        "secondary_k": 1.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis) — OMRI Listed",
        "fungicide_subtype": "biological_fungicide",
        # Cavity spot (Pythium violae) is the disease that decides an organic carrot crop and
        # has NO approved material — it is managed by rotation and drainage, so it is named in
        # the scouting event rather than pretended away with a spray here.
        "fungicide_target": "Alternaria leaf blight (Alternaria dauci), Cercospora leaf spot",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Bacterial leaf blight (Xanthomonas hortorum pv. carotae)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Aster leafhopper (Macrosteles quadrilineatus), armyworms",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis subsp. kurstaki) — OMRI Listed",
        "herbicide": None,
        "uses_flame_weeding": True,
        "compost_material": "Purchased OMRI-listed yard-debris compost",
        "wash_water_sanitizer": "SaniDate 5.0 (peracetic acid) — OMRI Listed",
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Oregon Tilth Certified Organic (OTCO)",
    },
    "onions": {
        "primary_fertilizer": "Down To Earth Feather Meal 12-0-0 — OMRI Listed",
        "npk": "12-0-0",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 0.0,
        "potassium_pct": 0.0,
        "secondary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "secondary_npk": "2-3-1",
        "secondary_n": 2.0,
        "secondary_p": 3.0,
        "secondary_k": 1.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis) — OMRI Listed",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Downy mildew (Peronospora destructor), Botrytis leaf blight",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Purple blotch (Alternaria porri), bacterial soft rots",
        # Onion thrips is the pest that decides an organic bulb crop; spinosad is the
        # primary tool and insecticidal soap the rotation partner for resistance management.
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Onion thrips (Thrips tabaci)",
        "biological_pesticide": "M-Pede insecticidal soap (potassium salts of fatty acids) — OMRI Listed",
        "herbicide": None,
        "uses_flame_weeding": True,
        "compost_material": "Purchased OMRI-listed yard-debris compost",
        # No wash sanitizer key on purpose: storage onions are field-cured then shed-cured
        # with forced air, topped and sacked. They are never washed, and a template that
        # suggested a wash step would put a food-safety record on the plan that the crop's
        # own handling contradicts.
        "post_harvest_operation": "curing",
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Oregon Tilth Certified Organic (OTCO)",
    },
    "spinach": {
        # Spinach is a short, fast, heavy-N crop: the liquid fish goes on first and the
        # feather meal is the pre-plant base, the reverse of the root crops above.
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Down To Earth Feather Meal 12-0-0 — OMRI Listed",
        "secondary_npk": "12-0-0",
        "secondary_n": 12.0,
        "secondary_p": 0.0,
        "secondary_k": 0.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis) — OMRI Listed",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Downy mildew (Peronospora effusa), white rust",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Bacterial leaf spot (Pseudomonas syringae pv. spinaciae)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Spinach leafminer (Pegomya hyoscyami), armyworms",
        "biological_pesticide": "M-Pede insecticidal soap (potassium salts of fatty acids) — OMRI Listed",
        "herbicide": None,
        "uses_flame_weeding": True,
        "compost_material": "Purchased OMRI-listed yard-debris compost",
        "wash_water_sanitizer": "SaniDate 5.0 (peracetic acid) — OMRI Listed",
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Oregon Tilth Certified Organic (OTCO)",
    },
    "potatoes": {
        "primary_fertilizer": "Down To Earth Feather Meal 12-0-0 — OMRI Listed",
        "npk": "12-0-0",
        "nitrogen_pct": 12.0,
        "phosphorus_pct": 0.0,
        "potassium_pct": 0.0,
        "secondary_fertilizer": "Down To Earth Fish Bone Meal 3-16-0",
        "secondary_npk": "3-16-0",
        "secondary_n": 3.0,
        "secondary_p": 16.0,
        "secondary_k": 0.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        # Copper is the load-bearing material in organic potatoes — late blight is the crop's
        # decisive disease and there is no biological substitute for it, so copper leads and
        # the Bacillus product is the partner, the reverse of the leaf crops above.
        "primary_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "fungicide_subtype": "organic_fungicide",
        "fungicide_target": "Late blight (Phytophthora infestans), early blight (Alternaria solani)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Late blight (Phytophthora infestans)",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Colorado potato beetle (Leptinotarsa decemlineata)",
        # subsp. TENEBRIONIS, not kurstaki: kurstaki is a caterpillar material and does nothing
        # to a beetle. Naming the wrong Bt on a potato plan is the kind of detail a grower
        # notices and a certifier does not, which makes it worse, not better. The organism is
        # spelled out rather than abbreviated to "Bt" for the reason in the block comment above:
        # 7 CFR 205.601 names SUBSTANCES, never brands, and "Bt" alone is not a substance name
        # any classifier can place.
        "biological_pesticide": "Novodor FC (Bacillus thuringiensis subsp. tenebrionis) — OMRI Listed",
        "herbicide": None,
        "uses_flame_weeding": True,
        "compost_material": "Purchased OMRI-listed yard-debris compost",
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Oregon Tilth Certified Organic (OTCO)",
    },
    # ---------------------------------------------------------------------------
    # California perennial specialty crops — organic variants, added 2026-08-07.
    #
    # EVERY material named below was checked against the seeded National List before being used:
    # Spinosad, Microbial products (Bacillus thuringiensis), Copper hydroxide, Horticultural oils
    # and Lime sulfur are all present at § 205.601. Materials that are commonly assumed to be
    # organic but are NOT in the seed — kaolin, neem, pyrethrum — are deliberately absent, because
    # an input the classifier cannot place would render as "Self-reported" on the certifier packet
    # and defeat the point of suggesting it.
    #
    # `test_organic_template_prohibited_inputs.py` iterates ORGANIC_OVERRIDES, so these entries
    # are checked against the 7 CFR 205.105 prohibited list automatically.
    # ---------------------------------------------------------------------------
    "pistachios": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Botryosphaeria panicle and shoot blight",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Botryosphaeria panicle and shoot blight",
        # Winter mummy sanitation is the backbone of organic navel orangeworm control; Bt and
        # spinosad at hullsplit are the sprays that follow it.
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Navel orangeworm (Amyelois transitella)",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "olives": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        "primary_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Olive knot, peacock spot (Spilocaea oleagina)",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Olive knot (Pseudomonas savastanoi pv. savastanoi)",
        # GF-120 is a spinosad bait and is the standard organic olive fruit fly programme.
        "primary_pesticide": "GF-120 NF Naturalyte Fruit Fly Bait (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Olive fruit fly (Bactrocera oleae)",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "dates": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Inflorescence rot, black scorch",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Black scorch (Thielaviopsis punctulata)",
        # Elemental sulfur is the standard organic control for date mite; bunch bagging and
        # sanitation carry the rest of the programme.
        "primary_pesticide": "Elemental sulfur dust — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Old world date mite (Oligonychus afrasiaticus)",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "figs": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Fig souring, Botrytis limb blight",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Botrytis limb blight",
        # Fig souring is vectored by dried fruit beetle, so orchard sanitation and timely harvest
        # do most of the work; spinosad is the one spray.
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Dried fruit beetle (Carpophilus spp.)",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    "pomegranates": {
        "primary_fertilizer": "Neptune's Harvest Fish & Seaweed 2-3-1",
        "npk": "2-3-1",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 1.0,
        "secondary_fertilizer": "Sustane 8-2-4 Organic Granular",
        "secondary_npk": "8-2-4",
        "secondary_n": 8.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Dr. Earth Organic 9 Fruit Tree 5-5-2",
        "primary_fungicide": "Serenade ASO (Bacillus subtilis)",
        "fungicide_subtype": "biological_fungicide",
        "fungicide_target": "Alternaria heart rot, Botrytis",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Botrytis",
        # Sunburn and fruit splitting are managed by even irrigation and canopy work, not by a
        # spray — kaolin is the usual organic answer but is absent from the seeded National List,
        # so it is deliberately not suggested here.
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Omnivorous leafroller, leaffooted plant bug",
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "CCOF (California Certified Organic Farmers)",
    },
    # ---------------------------------------------------------------------------
    # Pears — organic variant, added 2026-08-18.
    #
    # Every material below is in the seeded National List: Lime sulfur, Copper hydroxide,
    # Spinosad and "Microbial products (Bacillus thuringiensis, etc.)". Three materials a pear
    # grower might expect are deliberately ABSENT:
    #   · streptomycin / oxytetracycline — the standard organic fire blight materials until their
    #     § 205.601 listings expired in 2014. Suggesting them would suggest a prohibited input.
    #   · Blossom Protect (Aureobasidium pullulans) and kaolin (Surround) — both legitimate and
    #     widely used organically, both missing from the seeded list, so the classifier could not
    #     place them and the certifier packet would render them "Self-reported".
    # Horticultural oil is the backbone of organic psylla control and IS on the list, but this
    # dict has no key for it and nothing downstream would read one — the oil belongs in the
    # grower's own logged events, not in an invented template key.
    #
    # Certification body is WSDA, not CCOF: 60 of the 62 pear/pome farms in the Sep-30 named list
    # are WSDA-certified.
    # ---------------------------------------------------------------------------
    "pears": {
        "primary_fertilizer": "North Country Organics Pro-Start 2-3-3",
        "npk": "2-3-3",
        "nitrogen_pct": 2.0,
        "phosphorus_pct": 3.0,
        "potassium_pct": 3.0,
        "secondary_fertilizer": "Fertrell Super N 4-2-4",
        "secondary_npk": "4-2-4",
        "secondary_n": 4.0,
        "secondary_p": 2.0,
        "secondary_k": 4.0,
        "slow_release_fertilizer": "Sustane 8-2-4 Organic Granular",
        # Sulfur, not a biological: the subtype is `sulfur_fungicide` — the same call the grapes
        # entry makes. `biological_fungicide` would both mis-describe it to the grower and pick
        # the biological manufacturing emission factor (carbon/views.py:987 selects the factor
        # off this subtype).
        #
        # The product is the one the grapes entry already uses, deliberately. Every generated
        # organic chemical event is stamped `organic_approved="omri_listed"` — HARDCODED in the
        # generators (line ~3506), not read from this dict — so whatever is named here is
        # asserted to be an OMRI-listed PRODUCT. A bare substance string ("lime sulfur") would
        # therefore be stamped as a product OMRI has never listed. Naming an already-vetted
        # product keeps the assertion true. Lime sulfur is the other standard organic pear
        # material and is on the National List, but it is not encoded for that reason.
        # The active ingredient is spelled "elemental sulfur", the National List's own wording, so
        # the auto-classifier's forward substring pass can cite § 205.601 off it. The grapes entry
        # writes "(micronized sulfur)" for the same product and therefore classifies as NOTHING —
        # it renders "Self-reported" on the certifier packet. Same trap as brand-vs-substance in
        # the COG Pro rehearsal: name the substance the list names.
        "primary_fungicide": "Microthiol Disperss (elemental sulfur) — OMRI Listed",
        "fungicide_subtype": "sulfur_fungicide",
        "fungicide_target": "Pear scab (Venturia pirina), powdery mildew",
        "copper_fungicide": "Kocide 3000 (copper hydroxide) — OMRI Listed",
        "copper_target": "Fire blight (Erwinia amylovora) — dormant and delayed dormant",
        "primary_pesticide": "Entrust SC (spinosad) — OMRI Listed",
        "pesticide_subtype": "organic_pesticide",
        "pesticide_target": "Pear psylla nymphs (Cacopsylla pyricola), codling moth",
        # Required even though pears is a TREE crop and the tree generator never reads this key:
        # `get_annual_crop_organic_events` reads it as `oa['biological_pesticide']` (line ~4650,
        # bracket access, inside an efficiency tip), and the organic-template test exercises BOTH
        # generators for every crop. Omitting it raises KeyError rather than degrading — every
        # ORGANIC_OVERRIDES entry must carry it.
        "biological_pesticide": "DiPel DF (Bacillus thuringiensis kurstaki) — OMRI Listed",
        "herbicide": None,
        "organic_approved_default": "omri_listed",
        "certification_type": "organic_usda",
        "certification_standard": "USDA NOP (7 CFR Part 205)",
        "certification_body": "Washington State Department of Agriculture Organic Program",
    },
}

# Alias: avocado (singular) also gets an organic template
ORGANIC_OVERRIDES["avocado"] = ORGANIC_OVERRIDES["avocados"]


# =============================================================================
# SECTION 2: EVENT TYPE BUILDER FUNCTIONS
# =============================================================================


def build_soil_event_fields(
    subtype="ST",
    name=None,
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
    test_results=None,
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

    if name:
        fields["name"] = name
    if amendment_type:
        fields["amendment_type"] = amendment_type
    if amendment_amount:
        fields["amendment_amount"] = amendment_amount
    if test_results:
        fields["test_results"] = test_results
    if extra_data:
        fields["extra_data"] = extra_data

    return fields


def build_production_event_fields(
    subtype="PL",
    name=None,
    area=10.0,
    area_unit="ha",
    yield_quantity=None,
    yield_unit="tons",
    harvest_quality_grade=None,
    fuel_consumed=8.0,
    fuel_unit="L",
    fuel_type="diesel",
    equipment_hours=4.0,
    efficiency="normal",
    observation="Production operation",
    seeds_source="commercial",
    # NOP 7 CFR 205.204 seed classification. Four call sites already passed this
    # and every one of them raised TypeError — the parameter was simply never
    # added. It stayed latent because all 22 shipped templates already exist and
    # are skipped on re-run, so the berry/tree/grain generators were never
    # re-entered until a new crop type was introduced.
    seed_certification_status=None,
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

    if name:
        fields["name"] = name

    # Subtype-specific fields
    if subtype == "PL":
        fields["seeds_source"] = seeds_source
        if seed_certification_status:
            fields["seed_certification_status"] = seed_certification_status
    elif subtype == "HA":
        fields["yield_quantity"] = yield_quantity
        fields["yield_unit"] = yield_unit
        fields["harvest_quality_grade"] = harvest_quality_grade or "grade_a"
        fields["transportation_distance"] = transportation_distance
        fields["transportation_unit"] = transportation_unit
    elif subtype == "IR":
        fields["water_source"] = water_source
        fields["irrigation_method"] = irrigation_method
        fields["irrigation_depth"] = irrigation_depth
        fields["irrigation_depth_unit"] = irrigation_depth_unit
    elif subtype == "PR":
        fields["equipment_type"] = equipment_type or "tractor"
    elif subtype == "EM":
        fields["equipment_type"] = equipment_type or "tractor"
        fields["equipment_operation_type"] = equipment_operation_type or "MN"

    if extra_data:
        fields["extra_data"] = extra_data

    return fields


def build_chemical_event_fields(
    subtype="FE",
    name=None,
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
    # Map application_method to structured choices (broadcast, injection, foliar, drip, banding)
    _METHOD_TO_STRUCTURED = {
        "broadcast": "broadcast",
        "banded": "banding",
        "banding": "banding",
        "fertigation": "drip",
        "drip": "drip",
        "foliar": "foliar",
        "foliar_spray": "foliar",
        "soil_incorporation": "injection",
        "injection": "injection",
    }

    fields = {
        "type": subtype,
        "chemical_subtype": chemical_subtype,
        "commercial_name": commercial_name,
        "concentration": concentration,
        # Model fields are CharField — store as strings (matches demo user command)
        "volume": str(volume),
        "area": str(area),
        "way_of_application": application_method,
        "application_method_structured": _METHOD_TO_STRUCTURED.get(application_method, "broadcast"),
        "application_fuel_type": fuel_type,
        "application_fuel_consumed": fuel_consumed,
        "application_fuel_unit": fuel_unit,
        "organic_approved": organic_approved,
        "weather_conditions": weather_conditions,
        "application_timing": application_timing,
        "observation": observation,
    }

    if name:
        fields["name"] = name

    # Fertilizer-specific fields
    if subtype == "FE":
        fields["nitrogen_percentage"] = nitrogen_pct
        fields["phosphorus_percentage"] = phosphorus_pct
        fields["potassium_percentage"] = potassium_pct
        fields["target_pest_disease"] = target_pest_disease

    # Pesticide/Herbicide/Fungicide-specific fields
    if subtype in ["PE", "HE", "FU"]:
        fields["target_pest_disease"] = target_pest_disease
        fields["restricted_use_pesticide"] = restricted_use_pesticide
        fields["applicator_name"] = applicator_name
        fields["rei_hours"] = rei_hours
        fields["phi_days"] = phi_days

    # Ensure volume_unit is always in extra_data (critical convention from demo data)
    base_extra = {"volume_unit": volume_unit}
    if extra_data:
        base_extra.update(extra_data)
    fields["extra_data"] = base_extra

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
    # Frontend expects "way_of_protection" for FR/HL, "protection_measures" for HT/TS/HW
    if protection_measures:
        if subtype in ("FR", "HL"):
            extra_data["way_of_protection"] = protection_measures
        else:
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
                name="Annual Soil Analysis",
                area=area,
                working_depth=30.0,
                soil_ph=6.5,
                organic_matter_pct=3.0,
                soil_texture=crop_data.get("soil_type", "loam"),
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Annual soil analysis for {crop_slug} orchard",
                test_results={"ph": 6.5, "organic_matter_pct": 3.0, "lab": "Soil testing laboratory"},
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
                name="Cover Crop / Compost Application",
                area=area,
                fuel_consumed=8.0,
                fuel_unit="gal",
                equipment_hours=6.0,
                amendment_type="Crimson Clover + White Mustard seed mix",
                amendment_amount="375",
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
                name="Base Fertilization",
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
                name="Secondary Fertigation",
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
                name="Fungicide Prevention Treatment",
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
                name="Organic Fungicide Spray",
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
                name="Herbicide Application",
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
                name="Pesticide Treatment",
                chemical_subtype=crop_data.get("pesticide_subtype", "synthetic_pesticide"),
                # FIXED 2026-08-18. This read only `synthetic_pesticide`, a key exactly ONE crop
                # sets (citrus). The other 13 crops carrying a named insecticide put it in
                # `primary_pesticide` — which is read only off ORGANIC_OVERRIDES — so their
                # conventional pest event silently rendered the literal string "Targeted
                # insecticide" and the generic `common_pests` list. A dict key nothing downstream
                # reads: same class as the template-flow blindness of 2026-08-12.
                #
                # Chain, most specific first. The 17 crops that name no insecticide at all still
                # land on the generic fallback, which for them is correct — there is nothing to
                # lose, and inventing a material would be worse than a generic label.
                commercial_name=crop_data.get(
                    "synthetic_pesticide", crop_data.get("primary_pesticide", "Targeted insecticide")
                ),
                concentration="25",
                volume=3.0,
                area=area,
                target_pest_disease=crop_data.get(
                    "synthetic_pesticide_target",
                    crop_data.get("pesticide_target", crop_data["common_pests"]),
                ),
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
                name="Season Irrigation Program",
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
                    "irrigation_depth": "2.5",
                    "irrigation_depth_unit": "inches",
                    "irrigation_method": crop_data["irrigation_method"],
                    "water_source": crop_data.get("water_source", "well_groundwater"),
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
                name="Annual Structural Pruning",
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
                name="Harvest",
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
                name="Planting / Replanting",
                area=2.5,
                fuel_consumed=18.0,
                fuel_unit="L",
                fuel_type="biodiesel",
                equipment_hours=10.0,
                seeds_source="commercial",
                seed_certification_status="certified_organic",
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
                name="Mechanical Weed Management",
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
                name="Fruit Thinning",
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
                name="Equipment Maintenance",
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
                name="Sprayer Calibration",
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
                name="Pollination Management",
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
                name="Post-Harvest Processing",
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
                name="Canopy Management",
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


def get_tree_crop_organic_events(crop_slug, crop_data, organic_overrides):
    """
    Generate organic-specific events for tree crops.

    Mirrors get_tree_crop_events() but substitutes OMRI-listed / NOP-approved
    inputs (7 CFR Part 205).  Key differences from conventional:
      - All chemical events: organic_approved="omri_listed"
      - No herbicide event  -> replaced by Cultivation / Weed Control
      - Dedicated Cover Crop event (required, high priority)
      - Biological pest control only (Bt, spinosad, beneficial insects)
      - USDA NOP Certification Inspection (Business CE)
      - Equipment Cleaning / Sanitation (Production EM, shared_with_conventional=False)
    """
    area = crop_data["typical_area"]
    oa = organic_overrides  # shorthand

    return [
        # === SOIL MANAGEMENT (backend_event_type=5) ===
        # 1. Annual Soil Analysis
        {
            "name": "Annual Soil Analysis",
            "event_type": "soil_management",
            "description": (
                f"Annual soil testing for pH, organic matter, and nutrient levels "
                f"in organic {crop_slug} orchard — required for NOP OSP documentation"
            ),
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 95.0,
            "carbon_impact": 5.0,
            "labor_hours": 3.0,
            "typical_duration": "1 day",
            "efficiency_tips": "Take 20-30 soil samples per block; results guide OMRI-approved amendment selection",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Certified soil health monitoring for organic produce",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 1,
            "backend_event_fields": build_soil_event_fields(
                subtype="ST",
                name="Annual Soil Analysis",
                area=area,
                working_depth=30.0,
                soil_ph=6.5,
                organic_matter_pct=4.5,
                soil_texture=crop_data.get("soil_type", "loam"),
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Annual organic soil analysis for {crop_slug} orchard — NOP OSP documentation",
                test_results={
                    "ph": 6.5,
                    "organic_matter_pct": 4.5,
                    "lab": "A&L Western Laboratories",
                    "nop_compliant": True,
                },
            ),
        },
        # 2. Cover Crop (required for NOP soil fertility program)
        {
            "name": "Cover Crop Establishment",
            "event_type": "soil_management",
            "description": (
                "Certified organic cover crop planting — primary NOP-compliant "
                "nitrogen source and soil organic matter builder"
            ),
            "timing": "October - November",
            "frequency": "annual",
            "carbon_category": "negative",
            "cost_estimate": 175.0,
            "carbon_impact": -35.0,
            "labor_hours": 6.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": (
                "Legume-brassica mix fixes nitrogen naturally — document seed source "
                "and supplier for NOP OSP compliance"
            ),
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Certified organic cover crops build healthy soil naturally",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 2,
            "backend_event_fields": build_soil_event_fields(
                subtype="CC",
                name="Cover Crop Establishment",
                area=area,
                fuel_consumed=8.0,
                fuel_unit="gal",
                equipment_hours=6.0,
                amendment_type="Certified Organic Crimson Clover + White Mustard seed mix",
                amendment_amount="375",
                observation=f"Organic cover crop establishment for {crop_slug} orchard — NOP compliant",
                extra_data={
                    "seed_supplier": "Peaceful Valley Farm & Garden Supply",
                    "seed_certification": "CCOF certified organic",
                    "seed_mix": {
                        "crimson_clover_pct": 60,
                        "white_mustard_pct": 40,
                    },
                    "expected_biomass_tons_ha": 5.5,
                    "nop_compliant": True,
                },
            ),
        },
        # === CHEMICAL EVENTS (backend_event_type=2) ===
        # 3. Base Organic Fertilization
        {
            "name": "Base Organic Fertilization",
            "event_type": "fertilization",
            "description": (
                f"Primary OMRI-listed fish & seaweed fertilization for {crop_slug} "
                "growth — NOP-approved, no synthetic inputs"
            ),
            "timing": crop_data["timing_fertilize"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 310.0,
            "carbon_impact": 45.0,
            "labor_hours": 2.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Soil test first to calibrate rate; fish hydrolysate improves microbial activity",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "OMRI-listed organic fertilizer applied — no synthetic chemicals",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 3,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                name="Base Organic Fertilization",
                chemical_subtype="organic_fertilizer",
                commercial_name=oa["primary_fertilizer"],
                concentration=oa["npk"],
                volume=area * 150,
                area=area,
                nitrogen_pct=oa["nitrogen_pct"],
                phosphorus_pct=oa["phosphorus_pct"],
                potassium_pct=oa["potassium_pct"],
                application_method="banded",
                fuel_consumed=round(area * 0.88, 1),
                fuel_unit="L",
                organic_approved="omri_listed",
                application_timing="fall",
                observation=f"OMRI-listed base fertilization for organic {crop_slug}",
                extra_data={
                    "rate_kg_ha": 150,
                    "volume_unit": "kg",
                    "supplier_name": "Neptune's Harvest",
                    "omri_certificate": "OMRI-listed",
                    "nop_compliant": True,
                },
            ),
        },
        # 4. Secondary Organic Fertigation
        {
            "name": "Secondary Organic Fertigation",
            "event_type": "fertilization",
            "description": "In-season organic fertigation with OMRI-listed granular fertilizer through drip system",
            "timing": "June - August",
            "frequency": "seasonal",
            "carbon_category": "low",
            "cost_estimate": 250.0,
            "carbon_impact": 35.0,
            "labor_hours": 1.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Dissolve granular product fully before injecting; flush lines after application",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "OMRI-listed organic nutrition through efficient drip irrigation",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 4,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                name="Secondary Organic Fertigation",
                chemical_subtype="organic_fertilizer",
                commercial_name=oa["secondary_fertilizer"],
                concentration=oa["secondary_npk"],
                volume=area * 100,
                area=area,
                nitrogen_pct=oa["secondary_n"],
                phosphorus_pct=oa["secondary_p"],
                potassium_pct=oa["secondary_k"],
                application_method="drip",
                fuel_type="electric",
                fuel_consumed=2.5,
                fuel_unit="kWh",
                organic_approved="omri_listed",
                application_timing="summer",
                observation=f"OMRI-listed organic secondary fertigation for {crop_slug}",
                extra_data={
                    "volume_unit": "kg",
                    "supplier_name": "Sustane Natural Fertilizer",
                    "omri_certificate": "OMRI-listed",
                    "nop_compliant": True,
                },
            ),
        },
        # 5. Biological Fungicide Treatment
        {
            "name": "Biological Fungicide Treatment",
            "event_type": "fertilization",
            "description": (
                "Preventive biological fungicide application — Bacillus subtilis "
                "OMRI-listed for Phytophthora and root rot suppression"
            ),
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 165.0,
            "carbon_impact": 25.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Apply at first disease sign; Bacillus subtilis colonizes root zone for residual protection",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "OMRI-listed biological disease prevention — no synthetic fungicides",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 5,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FU",
                name="Biological Fungicide Treatment",
                chemical_subtype=oa["fungicide_subtype"],
                commercial_name=oa["primary_fungicide"],
                concentration="1.34",
                volume=15.0,
                area=area,
                target_pest_disease=oa["fungicide_target"],
                fuel_consumed=4.5,
                fuel_unit="L",
                organic_approved="omri_listed",
                application_method="trunk_drench",
                observation=f"OMRI-listed biological fungicide for organic {crop_slug}",
                extra_data={
                    "dilution_rate": "4 fl oz/gal",
                    "water_volume_L": int(area * 500),
                    "supplier_name": "Bayer Crop Science (BioControl)",
                    "omri_certificate": "OMRI-listed",
                    "nop_compliant": True,
                },
            ),
        },
        # 6. Copper Fungicide Spray (OMRI-listed)
        {
            "name": "Copper Fungicide Spray",
            "event_type": "fertilization",
            "description": "OMRI-listed copper hydroxide fungicide spray for anthracnose and canker prevention",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 145.0,
            "carbon_impact": 30.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Document copper cumulative loading; NOP limits copper to 3 lb/acre/year for orchards",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "OMRI-listed copper disease protection — certified organic approved",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 6,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FU",
                name="Copper Fungicide Spray",
                chemical_subtype="copper_fungicide",
                commercial_name=oa["copper_fungicide"],
                concentration="46",
                volume=area * 2.24,
                area=area,
                # Was hardcoded to "Anthracnose (Colletotrichum gloeosporioides), Canker" — an
                # AVOCADO disease — for every tree crop, so the organic walnut, grape, stone
                # fruit, hazelnut and pecan copper sprays all recorded a disease that does not
                # occur on that crop. A certifier reading a walnut copper application against
                # avocado anthracnose has a legitimate question about the record.
                # `copper_target` was already present in the override data; nothing read it.
                # Fallback is deliberately generic, NOT avocado's anthracnose: a tree crop added
                # without `copper_target` should read as unspecified, not as a disease that does
                # not occur on it. Every tree crop in ORGANIC_OVERRIDES now sets one, and a test
                # keeps it that way.
                target_pest_disease=oa.get("copper_target", "Fungal and bacterial canker diseases"),
                fuel_consumed=7.0,
                fuel_unit="gal",
                organic_approved="omri_listed",
                application_method="airblast",
                observation=f"OMRI-listed copper fungicide spray for organic {crop_slug}",
                extra_data={
                    "volume_unit": "L",
                    "supplier_name": "FMC Corporation",
                    "omri_certificate": "OMRI-listed",
                    "copper_loading_lb_acre": 1.5,
                    "nop_compliant": True,
                },
            ),
        },
        # 7. Cultivation / Organic Weed Control (replaces herbicide event)
        {
            "name": "Mechanical Organic Weed Control",
            "event_type": "other",
            "description": (
                "Mechanical cultivation and mowing for weed management — " "no synthetic herbicides per NOP standards"
            ),
            "timing": "Spring - Summer",
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 110.0,
            "carbon_impact": 35.0,
            "labor_hours": 5.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": "Cultivate when weeds are small (2-4 leaf stage) for best results with least fuel",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Chemical-free weed control — certified organic practices",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 7,
            "backend_event_fields": build_production_event_fields(
                subtype="CU",
                name="Mechanical Organic Weed Control",
                area=area,
                fuel_consumed=50.0,
                fuel_unit="gal",
                fuel_type="diesel",
                equipment_hours=14.0,
                observation=f"Mechanical weed control for organic {crop_slug} orchard — no synthetic herbicides",
                extra_data={
                    "weed_control_method": "mechanical_cultivation",
                    "herbicide_free": True,
                    "nop_compliant": True,
                },
            ),
        },
        # 8. OMRI-listed Pesticide Treatment
        {
            "name": "Organic Pesticide Treatment",
            "event_type": "fertilization",
            "description": (
                "OMRI-listed spinosad (Entrust SC) application when pest scouting "
                "confirms action threshold — avocado thrips and Persea mite"
            ),
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 195.0,
            "carbon_impact": 30.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Rotate with Bt to delay spinosad resistance; apply at cooler temps for better efficacy",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "OMRI-listed organic pest control — no synthetic pesticides",
            "backend_event_type": 2,
            "is_default_enabled": False,
            "is_required": False,
            "order_sequence": 8,
            "backend_event_fields": build_chemical_event_fields(
                subtype="PE",
                name="Organic Pesticide Treatment",
                chemical_subtype=oa["pesticide_subtype"],
                commercial_name=oa["primary_pesticide"],
                concentration="22.5",
                volume=3.0,
                area=area,
                target_pest_disease=oa["pesticide_target"],
                fuel_consumed=8.0,
                fuel_unit="gal",
                organic_approved="omri_listed",
                application_method="airblast",
                observation=f"OMRI-listed organic pesticide treatment for {crop_slug}",
                extra_data={
                    "volume_unit": "fl oz",
                    "supplier_name": "Corteva Agriscience",
                    "omri_certificate": "OMRI-listed",
                    "rei_hours": 4,
                    "phi_days": 1,
                    "nop_compliant": True,
                },
            ),
        },
        # === PRODUCTION EVENTS (backend_event_type=1) ===
        # 9. Season Irrigation
        {
            "name": "Season Irrigation Program",
            "event_type": "irrigation",
            "description": f"Year-round drip irrigation management for organic {crop_slug} orchard",
            "timing": crop_data["timing_irrigate"],
            "frequency": "weekly",
            "carbon_category": "medium",
            "cost_estimate": 180.0,
            "carbon_impact": 78.0,
            "labor_hours": 2.0,
            "typical_duration": "Ongoing",
            "efficiency_tips": "Soil moisture sensors reduce water use 20-30%; document all volumes for NOP OSP",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": "Efficient water management for organic avocado production",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 9,
            "backend_event_fields": build_production_event_fields(
                subtype="IR",
                name="Season Irrigation Program",
                area=area,
                fuel_consumed=3060.0,
                fuel_unit="kWh",
                fuel_type="electric",
                irrigation_method=crop_data["irrigation_method"],
                water_source=crop_data.get("water_source", "well_groundwater"),
                irrigation_depth=2.5,
                observation=f"Season irrigation for organic {crop_slug} orchard",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 18,
                    "water_volume_total": 3600000,
                    "water_volume_unit": "gallons",
                    "irrigation_depth": "2.5",
                    "irrigation_depth_unit": "inches",
                    "irrigation_method": crop_data["irrigation_method"],
                    "water_source": crop_data.get("water_source", "well_groundwater"),
                    "nop_compliant": True,
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
            "efficiency_tips": "Chip prunings on-site to return organic matter — document as compost input for NOP OSP",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Expert organic tree care for healthy fruit",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 10,
            "backend_event_fields": build_production_event_fields(
                subtype="PR",
                name="Annual Structural Pruning",
                area=area,
                fuel_consumed=12.0,
                fuel_unit="gal",
                equipment_hours=24.0,
                observation=f"Annual structural pruning for organic {crop_slug}",
                extra_data={
                    "pruning_material_disposition": "chipped_on_site",
                    "nop_compliant": True,
                },
            ),
        },
        # 11. Harvest
        {
            "name": "Harvest",
            "event_type": "harvest",
            "description": "Hand harvest of certified organic avocados at optimal Hass maturity index",
            "timing": crop_data["timing_harvest"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 320.0,
            "carbon_impact": 25.0,
            "labor_hours": 12.0,
            "typical_duration": "5-10 days per pass",
            "efficiency_tips": "Test dry matter (>21%) before harvest; multiple passes optimize quality and pack-out",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Hand-harvested certified organic avocados at peak maturity",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 11,
            "backend_event_fields": build_production_event_fields(
                subtype="HA",
                name="Harvest",
                area=area,
                yield_quantity=crop_data["yield_per_ha"] * area,
                yield_unit="kg",
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Manual organic {crop_slug} harvest — certified organic",
                extra_data={
                    "crew_size": 12,
                    "bins_filled": int(crop_data["yield_per_ha"] * area / 18),
                    "kg_per_bin": 18,
                    "organic_certified": True,
                    "nop_compliant": True,
                },
            ),
        },
        # 12. Planting / Replanting with Certified Organic Stock
        {
            "name": "Planting / Replanting (Certified Organic Stock)",
            "event_type": "planting",
            "description": (
                "Replanting with certified organic or non-treated nursery stock — "
                "NOP requires organic seed/stock when commercially available"
            ),
            "timing": crop_data["timing_plant"],
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 300.0,
            "carbon_impact": 35.0,
            "labor_hours": 10.0,
            "typical_duration": "2-3 days",
            "efficiency_tips": "Document seed/nursery stock supplier and organic certificate number for NOP OSP",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Certified organic nursery stock — documented for NOP compliance",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 12,
            "backend_event_fields": build_production_event_fields(
                subtype="PL",
                name="Planting / Replanting (Certified Organic Stock)",
                area=2.5,
                fuel_consumed=18.0,
                fuel_unit="L",
                fuel_type="biodiesel",
                equipment_hours=10.0,
                seeds_source="commercial",
                seed_certification_status="certified_organic",
                observation=f"Replanting organic {crop_slug} with certified organic nursery stock",
                extra_data={
                    "trees_planted": 625,
                    "rootstock": "Dusa clonal (untreated)",
                    "nursery": "Brokaw Nursery — certified organic block",
                    "spacing_m": "6x4",
                    "nursery_organic_cert": "CCOF",
                    "nop_compliant": True,
                },
            ),
        },
        # 13. Equipment Cleaning / Sanitation (NOP requirement)
        {
            "name": "Equipment Cleaning and Sanitation",
            "event_type": "equipment",
            "description": (
                "NOP-required equipment cleaning before use in certified organic fields — "
                "prevents contamination from conventional operations or prohibited substances"
            ),
            "timing": "Before each use in organic blocks",
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 45.0,
            "carbon_impact": 8.0,
            "labor_hours": 2.0,
            "typical_duration": "1-2 hours",
            "efficiency_tips": "Document cleaning materials used and equipment cleaned — required for NOP audit trail",
            "sustainability_score": 10,
            "qr_visibility": "low",
            "consumer_message": "Equipment cleaned and sanitized before organic field operations",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 13,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                name="Equipment Cleaning and Sanitation",
                area=0.0,
                fuel_consumed=0.5,
                fuel_unit="gal",
                equipment_hours=2.0,
                equipment_type="sprayer",
                equipment_operation_type="MN",
                observation="NOP-required equipment cleaning before organic field use",
                extra_data={
                    "equipment_name": "Airblast sprayer + tractor implements",
                    "cleaning_method": "high_pressure_water_wash",
                    "cleaning_materials_used": "water only — no prohibited cleaners",
                    "shared_with_conventional": False,
                    "nop_compliant": True,
                    "audit_log_required": True,
                },
            ),
        },
        # 14. Fruit Thinning
        {
            "name": "Fruit Thinning",
            "event_type": "other",
            "description": "Hand thinning to optimize fruit size and quality — no chemical thinners (NOP compliant)",
            "timing": "May - June",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 200.0,
            "carbon_impact": 0.0,
            "labor_hours": 8.0,
            "typical_duration": "3-5 days",
            "efficiency_tips": "Hand thinning only — chemical thinners not permitted in organic systems",
            "sustainability_score": 10,
            "qr_visibility": "low",
            "consumer_message": "Hand-thinned for premium organic fruit quality",
            "backend_event_type": 1,
            "is_default_enabled": False,
            "is_required": False,
            "order_sequence": 14,
            "backend_event_fields": build_production_event_fields(
                subtype="TH",
                name="Fruit Thinning",
                area=area,
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Hand thinning for organic {crop_slug} quality optimization",
                extra_data={
                    "thinning_method": "hand_only",
                    "chemical_thinners_used": False,
                    "nop_compliant": True,
                },
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
            "efficiency_tips": "Use biodegradable, NOP-compatible lubricants where possible; document all products",
            "sustainability_score": 7,
            "qr_visibility": "low",
            "consumer_message": "Well-maintained equipment for efficient organic farming",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 15,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                name="Equipment Maintenance",
                area=0.0,
                fuel_consumed=5.0,
                fuel_unit="gal",
                equipment_hours=8.0,
                equipment_type="tractor",
                equipment_operation_type="MN",
                observation="Annual tractor service — oil change, filter, hydraulic check (organic operation)",
                extra_data={
                    "equipment_name": "John Deere 5075E",
                    "maintenance_cost": 450,
                    "odometer_hours": 1200,
                    "next_service_hours": 1450,
                    "lubricants_nop_compatible": True,
                },
            ),
        },
        # 16. Sprayer Calibration
        {
            "name": "Sprayer Calibration",
            "event_type": "equipment",
            "description": "Annual calibration of spray equipment — critical for accurate OMRI-listed product application",
            "timing": "Pre-season",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 45.0,
            "carbon_impact": 10.0,
            "labor_hours": 3.0,
            "typical_duration": "3-4 hours",
            "efficiency_tips": "Proper calibration prevents over-application of costly OMRI products; document for NOP audit",
            "sustainability_score": 10,
            "qr_visibility": "low",
            "consumer_message": "Precision equipment calibration ensures accurate organic input application",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 16,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                name="Sprayer Calibration",
                area=0.0,
                fuel_consumed=4.5,
                fuel_unit="gal",
                fuel_type="gasoline",
                equipment_hours=3.0,
                equipment_type="sprayer",
                equipment_operation_type="CA",
                observation="Airblast sprayer calibration for OMRI-listed organic inputs",
                extra_data={
                    "equipment_name": "Rears Pul-Blast 500",
                    "nozzles_tested": 24,
                    "nozzles_replaced": 4,
                    "calibration_purpose": "organic_inputs_only",
                    "nop_compliant": True,
                },
            ),
        },
        # === PEST MANAGEMENT (backend_event_type=6) ===
        # 17. Pest Scouting
        {
            "name": "Pest Scouting",
            "event_type": "pest_control",
            "description": (
                f"Bi-weekly visual IPM scouting for organic {crop_slug} — "
                "documents pest pressure to justify OMRI-listed treatment decisions"
            ),
            "timing": crop_data["timing_pest"],
            "frequency": "bi-weekly",
            "carbon_category": "neutral",
            "cost_estimate": 45.0,
            "carbon_impact": 0.0,
            "labor_hours": 2.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Scouting records are required NOP documentation — use standardized forms",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Regular organic IPM monitoring keeps crops healthy without synthetic pesticides",
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
                observation=f"Organic IPM scouting for {crop_slug}",
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
                    "ipm_records_nop_required": True,
                },
            ),
        },
        # 18. Trap Monitoring
        {
            "name": "Pest Trap Monitoring",
            "event_type": "pest_control",
            "description": "Sticky trap and pheromone trap monitoring — NOP-approved, zero-chemical population tracking",
            "timing": crop_data["timing_pest"],
            "frequency": "bi-weekly",
            "carbon_category": "neutral",
            "cost_estimate": 35.0,
            "carbon_impact": 0.0,
            "labor_hours": 1.5,
            "typical_duration": "1-2 hours",
            "efficiency_tips": "4 traps per hectare; record counts on every inspection for NOP audit documentation",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Chemical-free monitoring tracks organic orchard pest populations",
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
                observation=f"Sticky trap monitoring for organic {crop_slug}",
                extra_data={
                    "traps_per_ha": 4,
                    "avg_pests_per_trap": 2.5,
                    "trap_type": "yellow sticky + pheromone",
                    "treatment_threshold": 10,
                    "nop_compliant": True,
                },
            ),
        },
        # 19. Beneficial Insect Release (required for organic IPM)
        {
            "name": "Beneficial Insect Release",
            "event_type": "pest_control",
            "description": (
                "Release of commercially reared Galendromus helveolus predatory mites — "
                "primary organic biological control for Persea mite"
            ),
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "neutral",
            "cost_estimate": 240.0,
            "carbon_impact": 0.0,
            "labor_hours": 2.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Release 50-100 predatory mites per tree before Persea mite populations peak",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Natural biological pest control with beneficial insects — certified organic",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 19,
            "backend_event_fields": build_pest_event_fields(
                subtype="BR",
                pest_species=crop_data.get("primary_pest_species", crop_data["common_pests"]),
                pest_pressure_level="low",
                beneficial_species="Galendromus helveolus (predatory mite)",
                release_quantity="500 per hectare",
                beneficial_insects_used="yes",
                area_covered=area,
                observation=f"Beneficial predatory mite release for organic {crop_slug}",
                extra_data={
                    "supplier": "Biobest Group — OMRI listed source",
                    "release_rate_per_tree": 75,
                    "nop_compliant": True,
                },
            ),
        },
        # === WEATHER (backend_event_type=0) ===
        # 20. Heat Stress Alert
        {
            "name": f"Heat Stress Alert - {crop_slug.replace('_', ' ').title()}",
            "event_type": "weather_protection",
            "description": (
                f"High temperature event documentation for organic {crop_slug} — "
                "heat stress increases pest pressure and requires irrigation response"
            ),
            "timing": "June - September",
            "frequency": "natural",
            "carbon_category": "neutral",
            "cost_estimate": 0.0,
            "carbon_impact": 0.0,
            "labor_hours": 0.5,
            "typical_duration": "Variable",
            "efficiency_tips": "Early documentation helps insurance claims; log irrigation response for NOP OSP",
            "sustainability_score": 5,
            "qr_visibility": "medium",
            "consumer_message": "Weather transparency — organic orchard monitoring for informed consumers",
            "backend_event_type": 0,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 20,
            "backend_event_fields": build_weather_event_fields(
                subtype="HT",
                event_name=f"Heat stress event in organic {crop_slug} orchard",
                temperature=42,
                duration=72,
                start_date="",
                end_date="",
                protection_measures="Increased irrigation frequency, overhead mist activation",
                observation=(
                    f"High temperature event affecting organic {crop_slug} orchard — "
                    "monitoring tree stress and irrigation needs"
                ),
            ),
        },
        # === BUSINESS (backend_event_type=7) ===
        # 21. USDA NOP Certification Inspection
        {
            "name": "USDA NOP Certification Inspection",
            "event_type": "certification",
            "description": (
                "Annual USDA NOP certification inspection by CCOF — "
                "reviews OSP, input records, field activities, and sales certificates"
            ),
            "timing": "Annual",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 750.0,
            "carbon_impact": 0.0,
            "labor_hours": 8.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": (
                "Maintain complete input purchase records, field activity logs, "
                "and parallel production separation docs year-round"
            ),
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "USDA NOP certified — annual third-party inspection by CCOF",
            "backend_event_type": 7,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 21,
            "backend_event_fields": build_business_event_fields(
                subtype="CE",
                name=oa["certification_standard"],
                business_type="certification",
                certification_type=oa["certification_type"],
                verification_status="verified",
                verified_certifier_name=oa["certification_body"],
                observation=f"Annual USDA NOP certification inspection for organic {crop_slug} operation",
                extra_data={
                    "audit_date": "",
                    "auditor": oa["certification_body"],
                    "standard": oa["certification_standard"],
                    "certificate_scope": "organic_avocados",
                    "major_nc": 0,
                    "minor_nc": 0,
                    "valid_until": "",
                    "nop_compliant": True,
                },
            ),
        },
        # === GENERAL (backend_event_type=3) ===
        # 22. Quality Control / Worker Training (NOP-specific)
        {
            "name": "Quality Control & Organic Training",
            "event_type": "monitoring",
            "description": (
                "Water quality testing, worker organic training, and OSP review — "
                "NOP requires all employees understand and follow the organic system plan"
            ),
            "timing": "Quarterly / Annual",
            "frequency": "quarterly",
            "carbon_category": "neutral",
            "cost_estimate": 85.0,
            "carbon_impact": 0.0,
            "labor_hours": 4.0,
            "typical_duration": "2-6 hours",
            "efficiency_tips": "Document all training sessions — required evidence for NOP certification renewal",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Quality assurance and certified organic worker training programs",
            "backend_event_type": 3,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 22,
            "backend_event_fields": build_general_event_fields(
                activity_type="training",
                name="Quality Control & Organic Training",
                activity_name=(
                    "NOP organic system plan review, prohibited substance training, " "and water quality testing"
                ),
                duration="4",
                people_involved=3,
                observation=f"NOP organic training and quality control for {crop_slug} operation",
                extra_data={
                    "training_topics": [
                        "nop_prohibited_substances",
                        "equipment_cleaning_procedures",
                        "record_keeping_requirements",
                        "buffer_zone_management",
                    ],
                    "nop_compliant": True,
                },
            ),
        },
    ]


def get_annual_crop_organic_events(crop_slug, crop_data, organic_overrides):
    """
    Generate organic-specific events for annual vegetable and berry crops.

    Mirrors get_tree_crop_organic_events() but replaces tree-specific events
    (Annual Structural Pruning, Fruit Thinning) with annual-crop equivalents
    (Certified Organic Transplanting, Season Bed Management).

    Suitable for: strawberries (berry), lettuce, tomatoes (vegetable).
    Key differences from tree-crop organic template:
      - No structural pruning or fruit thinning events
      - Transplanting uses certified organic seedling stock
      - Season bed preparation / cultivation replaces canopy management
      - Weed control via cultivation (same as tree — no synthetic herbicides)
      - All 7 event types represented across 20 events
    """
    area = crop_data["typical_area"]
    oa = organic_overrides  # shorthand
    crop_label = crop_slug.replace("_", " ").title()

    base_events = [
        # === SOIL MANAGEMENT (backend_event_type=5) ===
        # 1. Annual Soil Analysis
        {
            "name": "Annual Soil Analysis",
            "event_type": "soil_management",
            "description": (
                f"Annual soil testing for pH, organic matter, and nutrient levels "
                f"in organic {crop_slug} field — required for NOP OSP documentation"
            ),
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 85.0,
            "carbon_impact": 5.0,
            "labor_hours": 2.0,
            "typical_duration": "1 day",
            "efficiency_tips": "Take 15-20 soil samples per field block; results guide OMRI-approved amendment selection",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Certified soil health monitoring for organic produce",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 1,
            "backend_event_fields": build_soil_event_fields(
                subtype="ST",
                name="Annual Soil Analysis",
                area=area,
                working_depth=25.0,
                soil_ph=6.5,
                organic_matter_pct=3.5,
                soil_texture=crop_data.get("soil_type", "loam"),
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Annual organic soil analysis for {crop_slug} — NOP OSP documentation",
                test_results={
                    "ph": 6.5,
                    "organic_matter_pct": 3.5,
                    "lab": "A&L Western Laboratories",
                    "nop_compliant": True,
                },
            ),
        },
        # 2. Cover Crop / Organic Bed Preparation
        {
            "name": "Cover Crop and Bed Preparation",
            "event_type": "soil_management",
            "description": (
                "Certified organic cover crop termination and bed preparation — "
                "primary NOP-compliant nitrogen source and organic matter builder"
            ),
            "timing": crop_data["timing_soil"],
            "frequency": "annual",
            "carbon_category": "negative",
            "cost_estimate": 145.0,
            "carbon_impact": -20.0,
            "labor_hours": 5.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": (
                "Legume cover crop fixes nitrogen — document seed source and supplier "
                "for NOP OSP compliance. Incorporate before bolting."
            ),
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Certified organic cover crops build healthy soil naturally",
            "backend_event_type": 5,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 2,
            "backend_event_fields": build_soil_event_fields(
                subtype="CC",
                name="Cover Crop and Bed Preparation",
                area=area,
                fuel_consumed=6.0,
                fuel_unit="gal",
                equipment_hours=5.0,
                amendment_type="Certified Organic Crimson Clover + Oat seed mix",
                amendment_amount="280",
                observation=f"Organic cover crop incorporation and bed prep for {crop_slug} — NOP compliant",
                extra_data={
                    "seed_supplier": "Peaceful Valley Farm & Garden Supply",
                    "seed_certification": "CCOF certified organic",
                    "seed_mix": {"crimson_clover_pct": 50, "oats_pct": 50},
                    "expected_biomass_tons_ha": 3.5,
                    "nop_compliant": True,
                },
            ),
        },
        # === CHEMICAL EVENTS (backend_event_type=2) ===
        # 3. Base Organic Fertilization
        {
            "name": "Base Organic Fertilization",
            "event_type": "fertilization",
            "description": (
                f"Primary OMRI-listed organic fertilization for {crop_slug} "
                "establishment — NOP-approved, no synthetic inputs"
            ),
            "timing": crop_data["timing_fertilize"],
            "frequency": "seasonal",
            "carbon_category": "low",
            "cost_estimate": 245.0,
            "carbon_impact": 35.0,
            "labor_hours": 2.0,
            "typical_duration": "4-6 hours",
            "efficiency_tips": "Soil test first to calibrate rate; fish-seaweed blend improves microbial activity",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "OMRI-listed organic fertilizer applied — no synthetic chemicals",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 3,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                name="Base Organic Fertilization",
                chemical_subtype="organic_fertilizer",
                commercial_name=oa["primary_fertilizer"],
                concentration=oa["npk"],
                volume=area * 120,
                area=area,
                nitrogen_pct=oa["nitrogen_pct"],
                phosphorus_pct=oa["phosphorus_pct"],
                potassium_pct=oa["potassium_pct"],
                application_method="banded",
                fuel_consumed=round(area * 0.65, 1),
                fuel_unit="L",
                organic_approved="omri_listed",
                application_timing="pre_plant",
                observation=f"OMRI-listed base fertilization for organic {crop_slug}",
                extra_data={
                    "rate_kg_ha": 120,
                    "volume_unit": "kg",
                    "supplier_name": "Neptune's Harvest",
                    "omri_certificate": "OMRI-listed",
                    "nop_compliant": True,
                },
            ),
        },
        # 4. Secondary Organic Fertigation
        {
            "name": "Secondary Organic Fertigation",
            "event_type": "fertilization",
            "description": "In-season organic fertigation with OMRI-listed granular fertilizer through drip system",
            "timing": crop_data["timing_fertilize"],
            "frequency": "seasonal",
            "carbon_category": "low",
            "cost_estimate": 195.0,
            "carbon_impact": 28.0,
            "labor_hours": 1.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Dissolve granular product fully before injecting; flush lines after application",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "OMRI-listed organic nutrition through efficient drip irrigation",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 4,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FE",
                name="Secondary Organic Fertigation",
                chemical_subtype="organic_fertilizer",
                commercial_name=oa["secondary_fertilizer"],
                concentration=oa["secondary_npk"],
                volume=area * 80,
                area=area,
                nitrogen_pct=oa["secondary_n"],
                phosphorus_pct=oa["secondary_p"],
                potassium_pct=oa["secondary_k"],
                application_method="drip",
                fuel_type="electric",
                fuel_consumed=2.0,
                fuel_unit="kWh",
                organic_approved="omri_listed",
                application_timing="in_season",
                observation=f"OMRI-listed organic secondary fertigation for {crop_slug}",
                extra_data={
                    "volume_unit": "kg",
                    "supplier_name": "Down To Earth Distributors",
                    "omri_certificate": "OMRI-listed",
                    "nop_compliant": True,
                },
            ),
        },
        # 5. Biological Fungicide Treatment
        {
            "name": "Biological Fungicide Treatment",
            "event_type": "fertilization",
            "description": (
                f"Preventive biological fungicide application — {oa['primary_fungicide']} "
                f"OMRI-listed for {oa['fungicide_target']}"
            ),
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 140.0,
            "carbon_impact": 20.0,
            "labor_hours": 2.0,
            "typical_duration": "2-4 hours",
            "efficiency_tips": "Apply preventively at first disease sign; rotate with copper for resistance management",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "OMRI-listed biological disease prevention — no synthetic fungicides",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 5,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FU",
                name="Biological Fungicide Treatment",
                chemical_subtype=oa["fungicide_subtype"],
                commercial_name=oa["primary_fungicide"],
                concentration="1.34",
                volume=12.0,
                area=area,
                target_pest_disease=oa["fungicide_target"],
                fuel_consumed=3.5,
                fuel_unit="L",
                organic_approved="omri_listed",
                application_method="boom_sprayer",
                observation=f"OMRI-listed biological fungicide for organic {crop_slug}",
                extra_data={
                    "dilution_rate": "4 fl oz/gal",
                    "water_volume_L": int(area * 400),
                    "omri_certificate": "OMRI-listed",
                    "nop_compliant": True,
                },
            ),
        },
        # 6. Copper Fungicide Spray (OMRI-listed)
        {
            "name": "Copper Fungicide Spray",
            "event_type": "fertilization",
            "description": "OMRI-listed copper hydroxide fungicide spray for disease prevention",
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 120.0,
            "carbon_impact": 25.0,
            "labor_hours": 1.5,
            "typical_duration": "2-4 hours",
            "efficiency_tips": "Document copper cumulative loading; NOP limits copper to 3 lb/acre/year",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "OMRI-listed copper disease protection — certified organic approved",
            "backend_event_type": 2,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 6,
            "backend_event_fields": build_chemical_event_fields(
                subtype="FU",
                name="Copper Fungicide Spray",
                chemical_subtype="copper_fungicide",
                commercial_name=oa["copper_fungicide"],
                concentration="46",
                volume=area * 1.8,
                area=area,
                # Copper and the primary fungicide treat different diseases; reusing
                # `fungicide_target` recorded the biological product's target against a copper
                # application. Falls back to it only when no copper-specific target is given.
                target_pest_disease=oa.get("copper_target", oa["fungicide_target"]),
                fuel_consumed=5.0,
                fuel_unit="L",
                organic_approved="omri_listed",
                application_method="boom_sprayer",
                observation=f"OMRI-listed copper fungicide spray for organic {crop_slug}",
                extra_data={
                    "volume_unit": "L",
                    "copper_loading_lb_acre": 1.2,
                    "omri_certificate": "OMRI-listed",
                    "nop_compliant": True,
                },
            ),
        },
        # 7. Cultivation / Organic Weed Control (replaces herbicide event)
        {
            "name": "Mechanical Organic Weed Control",
            "event_type": "other",
            "description": (
                "Mechanical cultivation between rows for weed management — " "no synthetic herbicides per NOP standards"
            ),
            "timing": "Throughout season",
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 85.0,
            "carbon_impact": 25.0,
            "labor_hours": 4.0,
            "typical_duration": "4-8 hours",
            "efficiency_tips": "Cultivate when weeds are at 2-leaf stage; hand hoe in-row; flame weeding is NOP-compliant",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "Chemical-free weed control — certified organic practices",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 7,
            "backend_event_fields": build_production_event_fields(
                subtype="CU",
                name="Mechanical Organic Weed Control",
                area=area,
                fuel_consumed=30.0,
                fuel_unit="gal",
                fuel_type="diesel",
                equipment_hours=8.0,
                observation=f"Mechanical weed control for organic {crop_slug} — no synthetic herbicides",
                extra_data={
                    "weed_control_method": "mechanical_cultivation",
                    "herbicide_free": True,
                    "nop_compliant": True,
                },
            ),
        },
        # 8. OMRI-listed Pesticide Treatment
        {
            "name": "Organic Pesticide Treatment",
            "event_type": "fertilization",
            "description": (
                f"OMRI-listed {oa['primary_pesticide']} application when pest scouting "
                f"confirms action threshold — targets {oa['pesticide_target']}"
            ),
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 155.0,
            "carbon_impact": 22.0,
            "labor_hours": 2.0,
            "typical_duration": "2-4 hours",
            "efficiency_tips": f"Rotate with {oa['biological_pesticide']} to delay resistance; apply at cooler temps",
            "sustainability_score": 9,
            "qr_visibility": "high",
            "consumer_message": "OMRI-listed organic pest control — no synthetic pesticides",
            "backend_event_type": 2,
            "is_default_enabled": False,
            "is_required": False,
            "order_sequence": 8,
            "backend_event_fields": build_chemical_event_fields(
                subtype="PE",
                name="Organic Pesticide Treatment",
                chemical_subtype=oa["pesticide_subtype"],
                commercial_name=oa["primary_pesticide"],
                concentration="22.5",
                volume=2.5,
                area=area,
                target_pest_disease=oa["pesticide_target"],
                fuel_consumed=5.0,
                fuel_unit="L",
                organic_approved="omri_listed",
                application_method="boom_sprayer",
                observation=f"OMRI-listed organic pesticide treatment for {crop_slug}",
                extra_data={
                    "volume_unit": "fl oz",
                    "omri_certificate": "OMRI-listed",
                    "rei_hours": 4,
                    "phi_days": 1,
                    "nop_compliant": True,
                },
            ),
        },
        # === PRODUCTION EVENTS (backend_event_type=1) ===
        # 9. Season Irrigation
        {
            "name": "Season Irrigation Program",
            "event_type": "irrigation",
            "description": f"Season drip irrigation management for organic {crop_slug}",
            "timing": crop_data["timing_irrigate"],
            "frequency": "weekly",
            "carbon_category": "medium",
            "cost_estimate": 140.0,
            "carbon_impact": 55.0,
            "labor_hours": 1.5,
            "typical_duration": "Ongoing",
            "efficiency_tips": "Soil moisture sensors reduce water use 20-30%; document all volumes for NOP OSP",
            "sustainability_score": 9,
            "qr_visibility": "medium",
            "consumer_message": f"Efficient water management for organic {crop_label} production",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 9,
            "backend_event_fields": build_production_event_fields(
                subtype="IR",
                name="Season Irrigation Program",
                area=area,
                fuel_consumed=round(area * 150.0, 0),
                fuel_unit="kWh",
                fuel_type="electric",
                irrigation_method=crop_data["irrigation_method"],
                water_source=crop_data.get("water_source", "well_groundwater"),
                irrigation_depth=1.0,
                observation=f"Season irrigation for organic {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 14,
                    "water_volume_total": int(area * 180000),
                    "water_volume_unit": "gallons",
                    "irrigation_depth": "1.0",
                    "irrigation_depth_unit": "inches",
                    "irrigation_method": crop_data["irrigation_method"],
                    "water_source": crop_data.get("water_source", "well_groundwater"),
                    "nop_compliant": True,
                },
            ),
        },
        # 10. Transplanting with Certified Organic Stock
        {
            "name": "Transplanting (Certified Organic Stock)",
            "event_type": "planting",
            "description": (
                "Transplanting with certified organic or non-treated seedling stock — "
                "NOP requires organic seed/stock when commercially available"
            ),
            "timing": crop_data["timing_plant"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 225.0,
            "carbon_impact": 30.0,
            "labor_hours": 8.0,
            "typical_duration": "1-3 days",
            "efficiency_tips": "Document seed/nursery stock supplier and organic certificate number for NOP OSP",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Certified organic seedling stock — documented for NOP compliance",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 10,
            "backend_event_fields": build_production_event_fields(
                subtype="PL",
                name="Transplanting (Certified Organic Stock)",
                area=area,
                fuel_consumed=10.0,
                fuel_unit="L",
                fuel_type="diesel",
                equipment_hours=8.0,
                seeds_source="commercial",
                seed_certification_status="certified_organic",
                observation=f"Transplanting organic {crop_slug} with certified organic seedling stock",
                extra_data={
                    "seedling_source": "CCOF certified organic transplant supplier",
                    "seed_treatment": "none — untreated",
                    "nop_compliant": True,
                },
            ),
        },
        # 11. Harvest
        {
            "name": "Harvest",
            "event_type": "harvest",
            "description": f"Hand harvest of certified organic {crop_label} at optimal maturity",
            "timing": crop_data["timing_harvest"],
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 260.0,
            "carbon_impact": 20.0,
            "labor_hours": 10.0,
            "typical_duration": "3-7 days",
            "efficiency_tips": "Grade and cool product immediately after harvest to preserve organic quality",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": f"Hand-harvested certified organic {crop_label} at peak maturity",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 11,
            "backend_event_fields": build_production_event_fields(
                subtype="HA",
                name="Harvest",
                area=area,
                yield_quantity=crop_data["yield_per_ha"] * area,
                yield_unit="kg",
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Manual organic {crop_slug} harvest — certified organic",
                extra_data={
                    "crew_size": 8,
                    "organic_certified": True,
                    "nop_compliant": True,
                },
            ),
        },
        # 12. Equipment Cleaning / Sanitation (NOP requirement)
        {
            "name": "Equipment Cleaning and Sanitation",
            "event_type": "equipment",
            "description": (
                "NOP-required equipment cleaning before use in certified organic fields — "
                "prevents contamination from conventional operations or prohibited substances"
            ),
            "timing": "Before each use in organic blocks",
            "frequency": "as_needed",
            "carbon_category": "low",
            "cost_estimate": 35.0,
            "carbon_impact": 6.0,
            "labor_hours": 1.5,
            "typical_duration": "1-2 hours",
            "efficiency_tips": "Document cleaning materials used and equipment cleaned — required for NOP audit trail",
            "sustainability_score": 10,
            "qr_visibility": "low",
            "consumer_message": "Equipment cleaned and sanitized before organic field operations",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 12,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                name="Equipment Cleaning and Sanitation",
                area=0.0,
                fuel_consumed=0.5,
                fuel_unit="gal",
                equipment_hours=1.5,
                equipment_type="sprayer",
                equipment_operation_type="MN",
                observation="NOP-required equipment cleaning before organic field use",
                extra_data={
                    "equipment_name": "Boom sprayer + tractor implements",
                    "cleaning_method": "high_pressure_water_wash",
                    "cleaning_materials_used": "water only — no prohibited cleaners",
                    "shared_with_conventional": False,
                    "nop_compliant": True,
                    "audit_log_required": True,
                },
            ),
        },
        # 13. Equipment Maintenance
        {
            "name": "Equipment Maintenance",
            "event_type": "equipment",
            "description": "Scheduled maintenance on primary farm equipment (tractor, sprayer, drip system)",
            "timing": "Post-harvest",
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 70.0,
            "carbon_impact": 12.0,
            "labor_hours": 6.0,
            "typical_duration": "1 day",
            "efficiency_tips": "Use biodegradable, NOP-compatible lubricants where possible; document all products",
            "sustainability_score": 7,
            "qr_visibility": "low",
            "consumer_message": "Well-maintained equipment for efficient organic farming",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 13,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                name="Equipment Maintenance",
                area=0.0,
                fuel_consumed=3.0,
                fuel_unit="gal",
                equipment_hours=6.0,
                equipment_type="tractor",
                equipment_operation_type="MN",
                observation="Annual tractor service — oil change, filter, hydraulic check (organic operation)",
                extra_data={
                    "equipment_name": "John Deere 5075E",
                    "maintenance_cost": 350,
                    "lubricants_nop_compatible": True,
                },
            ),
        },
        # === PEST MANAGEMENT (backend_event_type=6) ===
        # 14. Pest Scouting
        {
            "name": "Pest Scouting",
            "event_type": "pest_control",
            "description": (
                f"Weekly visual IPM scouting for organic {crop_slug} — "
                "documents pest pressure to justify OMRI-listed treatment decisions"
            ),
            "timing": crop_data["timing_pest"],
            "frequency": "weekly",
            "carbon_category": "neutral",
            "cost_estimate": 35.0,
            "carbon_impact": 0.0,
            "labor_hours": 1.5,
            "typical_duration": "1-2 hours",
            "efficiency_tips": "Scouting records are required NOP documentation — use standardized forms",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Regular organic IPM monitoring keeps crops healthy without synthetic pesticides",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 14,
            "backend_event_fields": build_pest_event_fields(
                subtype="SC",
                pest_species=crop_data.get("primary_pest_species", crop_data["common_pests"]),
                pest_pressure_level="low",
                beneficial_insects_used="yes",
                action_threshold_met=False,
                area_covered=area,
                observation=f"Organic IPM scouting for {crop_slug}",
                extra_data={
                    "is_summary": True,
                    "date_start": "",
                    "date_end": "",
                    "event_count": 14,
                    "pest_species_observed": crop_data.get("primary_pest_species", crop_data["common_pests"]),
                    "average_pest_pressure": "low",
                    "area_covered_total": area,
                    "area_unit": "ha",
                    "carbon_impact": "zero",
                    "ipm_records_nop_required": True,
                },
            ),
        },
        # 15. Trap Monitoring
        {
            "name": "Pest Trap Monitoring",
            "event_type": "pest_control",
            "description": "Sticky trap and pheromone trap monitoring — NOP-approved, zero-chemical population tracking",
            "timing": crop_data["timing_pest"],
            "frequency": "weekly",
            "carbon_category": "neutral",
            "cost_estimate": 25.0,
            "carbon_impact": 0.0,
            "labor_hours": 1.0,
            "typical_duration": "1-2 hours",
            "efficiency_tips": "4-6 traps per hectare; record counts on every inspection for NOP audit documentation",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Chemical-free monitoring tracks organic field pest populations",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 15,
            "backend_event_fields": build_pest_event_fields(
                subtype="TM",
                pest_species=crop_data.get("primary_pest_species", crop_data["common_pests"]),
                pest_pressure_level="low",
                action_threshold_met=False,
                trap_count=int(area * 5),
                area_covered=area,
                observation=f"Sticky trap monitoring for organic {crop_slug}",
                extra_data={
                    "traps_per_ha": 5,
                    "avg_pests_per_trap": 2.0,
                    "trap_type": "yellow sticky + pheromone",
                    "treatment_threshold": 8,
                    "nop_compliant": True,
                },
            ),
        },
        # 16. Beneficial Insect Release
        {
            "name": "Beneficial Insect Release",
            "event_type": "pest_control",
            "description": (
                "Release of commercially reared beneficial insects — "
                "primary organic biological control for key pests"
            ),
            "timing": crop_data["timing_pest"],
            "frequency": "as_needed",
            "carbon_category": "neutral",
            "cost_estimate": 180.0,
            "carbon_impact": 0.0,
            "labor_hours": 1.5,
            "typical_duration": "1-2 hours",
            "efficiency_tips": "Release beneficials before pest populations peak; document supplier and quantity for NOP",
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": "Natural biological pest control with beneficial insects — certified organic",
            "backend_event_type": 6,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 16,
            "backend_event_fields": build_pest_event_fields(
                subtype="BR",
                pest_species=crop_data.get("primary_pest_species", crop_data["common_pests"]),
                pest_pressure_level="low",
                beneficial_species=crop_data.get("beneficial_insects", "Parasitic wasps, Ladybugs"),
                release_quantity="500 per hectare",
                beneficial_insects_used="yes",
                area_covered=area,
                observation=f"Beneficial insect release for organic {crop_slug}",
                extra_data={
                    "supplier": "Biobest Group — OMRI listed source",
                    "nop_compliant": True,
                },
            ),
        },
        # === WEATHER (backend_event_type=0) ===
        # 17. Frost / Weather Alert (vegetable/berry appropriate)
        {
            "name": f"Frost Alert - {crop_label}",
            "event_type": "weather_protection",
            "description": (
                f"Frost event documentation for organic {crop_slug} — "
                "cold snaps increase disease pressure and require crop protection response"
            ),
            "timing": "October - March",
            "frequency": "natural",
            "carbon_category": "neutral",
            "cost_estimate": 0.0,
            "carbon_impact": 0.0,
            "labor_hours": 0.5,
            "typical_duration": "Variable",
            "efficiency_tips": "Row covers and overhead irrigation can prevent significant crop loss; document for NOP OSP",
            "sustainability_score": 5,
            "qr_visibility": "medium",
            "consumer_message": "Weather transparency — organic field monitoring for informed consumers",
            "backend_event_type": 0,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 17,
            "backend_event_fields": build_weather_event_fields(
                subtype="FR",
                event_name=f"Frost event in organic {crop_slug} field",
                temperature=-2,
                duration=6,
                start_date="",
                end_date="",
                protection_measures="Row covers deployed, overhead irrigation frost protection activated",
                observation=(
                    f"Frost event affecting organic {crop_slug} — "
                    "monitoring crop damage and protection measures taken"
                ),
            ),
        },
        # === BUSINESS (backend_event_type=7) ===
        # 18. USDA NOP Certification Inspection
        {
            "name": "USDA NOP Certification Inspection",
            "event_type": "certification",
            "description": (
                "Annual USDA NOP certification inspection — "
                "reviews OSP, input records, field activities, and sales certificates"
            ),
            "timing": "Annual",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 650.0,
            "carbon_impact": 0.0,
            "labor_hours": 6.0,
            "typical_duration": "1-2 days",
            "efficiency_tips": (
                "Maintain complete input purchase records, field activity logs, "
                "and parallel production separation docs year-round"
            ),
            "sustainability_score": 10,
            "qr_visibility": "high",
            "consumer_message": f"USDA NOP certified — annual third-party inspection by {oa['certification_body']}",
            "backend_event_type": 7,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": 18,
            "backend_event_fields": build_business_event_fields(
                subtype="CE",
                name=oa["certification_standard"],
                business_type="certification",
                certification_type=oa["certification_type"],
                verification_status="verified",
                verified_certifier_name=oa["certification_body"],
                observation=f"Annual USDA NOP certification inspection for organic {crop_slug} operation",
                extra_data={
                    "audit_date": "",
                    "auditor": oa["certification_body"],
                    "standard": oa["certification_standard"],
                    "certificate_scope": f"organic_{crop_slug}",
                    "major_nc": 0,
                    "minor_nc": 0,
                    "valid_until": "",
                    "nop_compliant": True,
                },
            ),
        },
        # === GENERAL (backend_event_type=3) ===
        # 19. Quality Control / Worker Training (NOP-specific)
        {
            "name": "Quality Control & Organic Training",
            "event_type": "monitoring",
            "description": (
                "Water quality testing, worker organic training, and OSP review — "
                "NOP requires all employees understand and follow the organic system plan"
            ),
            "timing": "Quarterly / Annual",
            "frequency": "quarterly",
            "carbon_category": "neutral",
            "cost_estimate": 75.0,
            "carbon_impact": 0.0,
            "labor_hours": 3.0,
            "typical_duration": "2-4 hours",
            "efficiency_tips": "Document all training sessions — required evidence for NOP certification renewal",
            "sustainability_score": 10,
            "qr_visibility": "medium",
            "consumer_message": "Quality assurance and certified organic worker training programs",
            "backend_event_type": 3,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 19,
            "backend_event_fields": build_general_event_fields(
                activity_type="training",
                name="Quality Control & Organic Training",
                activity_name=(
                    "NOP organic system plan review, prohibited substance training, " "and water quality testing"
                ),
                duration="3",
                people_involved=3,
                observation=f"NOP organic training and quality control for {crop_slug} operation",
                extra_data={
                    "training_topics": [
                        "nop_prohibited_substances",
                        "equipment_cleaning_procedures",
                        "record_keeping_requirements",
                        "buffer_zone_management",
                    ],
                    "nop_compliant": True,
                },
            ),
        },
        # 20. Sprayer Calibration
        {
            "name": "Sprayer Calibration",
            "event_type": "equipment",
            "description": "Annual calibration of spray equipment — critical for accurate OMRI-listed product application",
            "timing": "Pre-season",
            "frequency": "annual",
            "carbon_category": "neutral",
            "cost_estimate": 35.0,
            "carbon_impact": 8.0,
            "labor_hours": 2.0,
            "typical_duration": "2-3 hours",
            "efficiency_tips": "Proper calibration prevents over-application of costly OMRI products; document for NOP audit",
            "sustainability_score": 10,
            "qr_visibility": "low",
            "consumer_message": "Precision equipment calibration ensures accurate organic input application",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": False,
            "order_sequence": 20,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                name="Sprayer Calibration",
                area=0.0,
                fuel_consumed=2.0,
                fuel_unit="gal",
                fuel_type="gasoline",
                equipment_hours=2.0,
                equipment_type="sprayer",
                equipment_operation_type="CA",
                observation="Boom sprayer calibration for OMRI-listed organic inputs",
                extra_data={
                    "equipment_name": "Boom Sprayer",
                    "nozzles_tested": 16,
                    "nozzles_replaced": 2,
                    "calibration_purpose": "organic_inputs_only",
                    "nop_compliant": True,
                },
            ),
        },
    ]

    # -----------------------------------------------------------------------------------
    # The practices an organic ANNUAL season actually turns on (F4, 2026-08-21).
    #
    # Everything above is the shared organic programme. What follows is what a real organic
    # vegetable season is MADE of, and none of it was on any template: the § 205.204(a)(1)
    # organic-seed search, the purchased compost, pre-emergence flame weeding, and the
    # post-harvest wash. Appended rather than woven in so the order_sequence of the existing
    # 20 events — and therefore every template already seeded — is untouched.
    #
    # Each is gated on a key the crop's ORGANIC_OVERRIDES entry declares, EXCEPT the seed
    # search, which is universal: § 205.204(a) binds every organic crop grown from seed or
    # planting stock, so a template that omits it omits a record the certifier will ask for.
    # -----------------------------------------------------------------------------------
    extra_events = []
    next_order = 21

    # § 205.204(a)(1) — organic seed sourcing, and the documented search when the variety is
    # not commercially available in organic form. This is a RECORD an inspector asks for by
    # name, and it was on no annual template at all.
    extra_events.append(
        {
            "name": "Organic Seed Sourcing & Availability Search",
            "event_type": "production",
            "description": (
                f"Source organic {crop_label.lower()} seed or planting stock; where the variety "
                "is not commercially available in organic form, document the suppliers "
                "contacted and keep the records on file (7 CFR 205.204(a)(1))."
            ),
            "timing": crop_data.get("timing_plant", "Before planting"),
            "frequency": "annual",
            "carbon_category": "low",
            "cost_estimate": 0.0,
            "carbon_impact": 0.0,
            "labor_hours": 2.0,
            "typical_duration": "1 day",
            "efficiency_tips": (
                "Contact at least three suppliers and keep the quotes or out-of-stock replies. "
                "A search with no paper behind it is the same as no search."
            ),
            "sustainability_score": 9,
            "qr_visibility": "low",
            "consumer_message": "Organic seed sourced first, with the search documented when it is not available",
            "backend_event_type": 1,
            "is_default_enabled": True,
            "is_required": True,
            "order_sequence": next_order,
            "backend_event_fields": build_production_event_fields(
                subtype="SS",
                name="Organic Seed Sourcing & Availability Search",
                area=0.0,
                fuel_consumed=0.0,
                fuel_unit="gal",
                fuel_type="none",
                equipment_hours=0.0,
                observation=(
                    f"Organic seed search for {crop_label.lower()} — suppliers contacted and "
                    "responses kept on file (7 CFR 205.204(a)(1))"
                ),
            ),
        }
    )
    next_order += 1

    if oa.get("compost_material"):
        extra_events.append(
            {
                "name": "Purchased Compost Application",
                "event_type": "soil_management",
                "description": (
                    f"Apply purchased OMRI-listed compost to organic {crop_label.lower()} ground. Keep the "
                    "supplier's compost analysis and the delivery record: § 205.203(c) governs "
                    "the material, and a purchased compost is only as documented as its paperwork."
                ),
                "timing": crop_data.get("timing_soil", "Before planting"),
                "frequency": "annual",
                "carbon_category": "low",
                "cost_estimate": 480.0,
                "carbon_impact": 12.0,
                "labor_hours": 4.0,
                "typical_duration": "1-2 days",
                "efficiency_tips": (
                    "Ask the supplier for the batch analysis, not just the invoice — the "
                    "certifier asks for the analysis."
                ),
                "sustainability_score": 10,
                "qr_visibility": "medium",
                "consumer_message": "Soil fed with composted organic matter rather than synthetic fertiliser",
                "backend_event_type": 5,
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": next_order,
                "backend_event_fields": build_soil_event_fields(
                    subtype="OM",
                    name="Purchased Compost Application",
                    area=area,
                    fuel_consumed=round(area * 2.0, 1),
                    fuel_type="diesel",
                    equipment_hours=round(area * 0.5, 1),
                    observation=(
                        f"{oa['compost_material']} applied to the {crop_label.lower()} ground — supplier "
                        "compost analysis and delivery record on file (7 CFR 205.203(c))"
                    ),
                ),
            }
        )
        next_order += 1

    if oa.get("uses_flame_weeding"):
        extra_events.append(
            {
                "name": "Pre-Emergence Flame Weeding",
                "event_type": "production",
                "description": (
                    f"Propane flame weeding of the {crop_label.lower()} beds in the window between "
                    "planting and crop emergence — the organic substitute for a pre-emergence "
                    "herbicide, and the pass that decides how much hand weeding the season needs."
                ),
                "timing": crop_data.get("timing_plant", "After planting"),
                "frequency": "1-2 per season",
                "carbon_category": "medium",
                "cost_estimate": 95.0,
                # Propane, and it is real: this is the one organic weed operation with a fuel
                # burn worth stating rather than hiding behind "mechanical cultivation".
                "carbon_impact": 38.0,
                "labor_hours": 3.0,
                "typical_duration": "1 day",
                "efficiency_tips": (
                    "Time it to the crop's emergence, not the calendar — a day late and the "
                    "flame takes the crop with the weeds."
                ),
                "sustainability_score": 8,
                "qr_visibility": "medium",
                "consumer_message": "Weeds burned off before the crop emerges — no herbicide is used",
                "backend_event_type": 1,
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": next_order,
                "backend_event_fields": build_production_event_fields(
                    subtype="CU",
                    name="Pre-Emergence Flame Weeding",
                    area=area,
                    fuel_consumed=round(area * 12.0, 1),  # ~12 gal propane/ha, one pass
                    fuel_unit="gal",
                    fuel_type="propane",
                    equipment_hours=round(area * 0.8, 1),
                    observation=(
                        f"Propane flame weeding of the {crop_label.lower()} beds before crop emergence — "
                        "no herbicide used (7 CFR 205.206(a))"
                    ),
                ),
            }
        )
        next_order += 1

    if oa.get("wash_water_sanitizer"):
        extra_events.append(
            {
                "name": "Post-Harvest Wash & Sanitize",
                "event_type": "production",
                "description": (
                    f"Wash and pack {crop_label.lower()} using potable water and an approved sanitizer. "
                    "Record the material, the label rate and the water source: § 205.272 asks "
                    "how organic product is kept from contacting a prohibited substance, and "
                    "the wash line is where that question is actually answered."
                ),
                "timing": "After harvest",
                "frequency": "per lot",
                "carbon_category": "medium",
                "cost_estimate": 140.0,
                "carbon_impact": 22.0,
                "labor_hours": 8.0,
                "typical_duration": "1 day per lot",
                "efficiency_tips": (
                    "Log the sanitizer concentration and the residual at discharge — the label "
                    "rate is the compliance boundary, and 'per label' is not a reading."
                ),
                "sustainability_score": 8,
                "qr_visibility": "medium",
                "consumer_message": "Washed with potable water and an approved sanitizer before packing",
                "backend_event_type": 1,
                "is_default_enabled": True,
                "is_required": False,
                "order_sequence": next_order,
                "backend_event_fields": build_production_event_fields(
                    subtype="PH",
                    name="Post-Harvest Wash & Sanitize",
                    area=area,
                    fuel_consumed=0.0,
                    fuel_unit="gal",
                    fuel_type="electric",
                    equipment_hours=round(area * 1.5, 1),
                    observation=(
                        f"{crop_label} washed and packed — {oa['wash_water_sanitizer']} at label "
                        "rate, well water (7 CFR 205.272)"
                    ),
                    extra_data={
                        "processing_type": "wash_and_pack",
                        "sanitizer_name": oa["wash_water_sanitizer"],
                        "sanitizer_nop_reference": "7 CFR 205.605(b) — peracetic acid",
                        "water_source": "well_groundwater",
                    },
                ),
            }
        )
        next_order += 1

    return base_events + extra_events


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
    events = [
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
                name="Soil Analysis",
                area=area,
                working_depth=30.0,
                soil_ph=6.5,
                organic_matter_pct=3.0,
                soil_texture=crop_data.get("soil_type", "loam"),
                fuel_consumed=0.0,
                fuel_type="none",
                equipment_hours=0.0,
                observation=f"Annual soil analysis for {crop_slug}",
                test_results={"ph": 6.5, "organic_matter_pct": 3.0, "lab": "Soil testing laboratory"},
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
                name="Fungicide Treatment",
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
                name="Herbicide Application",
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
            "order_sequence": start_order + 4,
            "backend_event_fields": build_production_event_fields(
                subtype="EM",
                name="Equipment Maintenance",
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
            "order_sequence": start_order + 5,
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
        _build_shared_weather_event(crop_slug, crop_category, start_order + 6),
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
            "order_sequence": start_order + 7,
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
            "order_sequence": start_order + 8,
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

    # Insecticide — added 2026-08-18, and CONDITIONAL on purpose.
    #
    # Only the tree path built a chemical insecticide event. Berry, vegetable, grain and fiber
    # crops got "Pest Management"/"Pest Scouting" (backend_event_type=6, scouting and beneficial
    # releases) and no spray event at all, so a conventional blueberry template had nowhere to
    # record the spotted-wing-drosophila sprays that define the season. Same for hops (aphid and
    # mite work) and spinach.
    #
    # ⛔ Emitted ONLY when the crop's dict actually names a material. The tree path falls back to
    # the literal "Targeted insecticide" for crops with no data; copying that here would add an
    # event suggesting a spray to ~17 crops nobody wrote a programme for. A template suggests
    # ACTIVITIES and must not invent FACTS — an absent material means no event, not a placeholder.
    insecticide = crop_data.get("synthetic_pesticide") or crop_data.get("primary_pesticide")
    if insecticide:
        events.append(
            {
                "name": "Pesticide Treatment",
                "event_type": "fertilization",
                "description": "Insecticide application when pest thresholds are exceeded",
                "timing": crop_data["timing_pest"],
                "frequency": "as_needed",
                "carbon_category": "medium",
                "cost_estimate": 130.0,
                "carbon_impact": 50.0,
                "labor_hours": 2.0,
                "typical_duration": "3-5 hours",
                "efficiency_tips": "Spray only when scouting confirms the threshold is exceeded",
                "sustainability_score": 5,
                "qr_visibility": "high",
                "consumer_message": "Targeted treatment only when necessary",
                "backend_event_type": 2,
                # Off by default, like the tree path's equivalent: a suggested spray must be an
                # opt-in, never something a grower accepts without noticing.
                "is_default_enabled": False,
                "is_required": False,
                # Grouped with the other chemical events — Fungicide (+1), Herbicide (+2),
                # this (+3) — rather than parked after the certification audit. The five events
                # that used to hold +3..+7 were shifted one place to open the slot; nothing pins
                # these numbers (they are display order only, checked in tests and frontend).
                # When a crop names no insecticide the slot is simply unused, which is fine.
                "order_sequence": start_order + 3,
                "backend_event_fields": build_chemical_event_fields(
                    subtype="PE",
                    name="Pesticide Treatment",
                    chemical_subtype=crop_data.get("pesticide_subtype", "synthetic_pesticide"),
                    commercial_name=insecticide,
                    concentration="25",
                    volume=area * 2.0,
                    area=area,
                    target_pest_disease=crop_data.get(
                        "synthetic_pesticide_target",
                        crop_data.get("pesticide_target", crop_data["common_pests"]),
                    ),
                    fuel_consumed=6.0,
                    fuel_unit="L",
                    # Not "airblast": these are berry rows, beds and bines, not orchard canopy.
                    application_method="broadcast",
                    observation=f"Insecticide treatment for {crop_slug}",
                ),
            }
        )

    return events


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
                name="Land Preparation",
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
                name="Planting",
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
                name="Fertilizer Application",
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
                name="Irrigation Management",
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
                    "irrigation_depth": "2.5",
                    "irrigation_depth_unit": "inches",
                    "irrigation_method": crop_data["irrigation_method"],
                    "water_source": crop_data.get("water_source", "well_groundwater"),
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
                name="Harvest",
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
                name="Soil Preparation",
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
                name="Transplanting/Seeding",
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
                name="Drip Irrigation Setup",
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
                    "irrigation_depth": "1.5",
                    "irrigation_depth_unit": "inches",
                    "irrigation_method": "drip",
                    "water_source": crop_data.get("water_source", "well_groundwater"),
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
                name="Fertilizer Program",
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
                name="Harvest",
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
                name="Post-Harvest Washing & Packing",
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
                name="Bed Preparation",
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
                name="Plant Installation",
                area=crop_data["typical_area"],
                fuel_consumed=4.0,
                equipment_hours=12.0,
                seeds_source="commercial",
                seed_certification_status="certified_organic",
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
                name="Fertigation System",
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
                name="Irrigation Management",
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
                    "irrigation_depth": "0.5",
                    "irrigation_depth_unit": "inches",
                    "irrigation_method": "drip",
                    "water_source": crop_data.get("water_source", "well_groundwater"),
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
                name="Harvest",
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
                name="Land Preparation",
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
                name="Planting",
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
                name="Fertilizer Application",
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
                name="Irrigation",
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
                    "irrigation_depth": "3.0",
                    "irrigation_depth_unit": "inches",
                    "irrigation_method": "furrow",
                    "water_source": crop_data.get("water_source", "well_groundwater"),
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
                name="Harvest",
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

                # Skip crops we have no real practice data for.
                #
                # This previously fell back to CROP_CUSTOMIZATIONS["corn_field"], which meant a
                # crop added to the catalog without customisations silently received a full
                # programme of CORN operations — tillage passes, corn fertigation schedules — as
                # a suggested template for, say, a pistachio orchard. Because accepting a
                # template writes real, backdated records attributed to the farmer by name, that
                # is the same defect class as the fabricated glyphosate application: operations
                # they never performed, in their own audit trail.
                #
                # No template is strictly better than a wrong one. Templates are opt-in, so a
                # crop without one still onboards fine — the grower just logs events directly.
                if crop_slug not in CROP_CUSTOMIZATIONS:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Skipping {crop_slug}: no practice data in CROP_CUSTOMIZATIONS. "
                            f"Add an entry rather than letting it inherit another crop's operations."
                        )
                    )
                    continue
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

                    conventional_events_needed = True
                    if created:
                        created_templates += 1
                        self.stdout.write(self.style.SUCCESS(f"\n  Created template: {template.name}"))
                    else:
                        skipped_templates += 1
                        self.stdout.write(f"\n  Template exists: {template.name}")
                        # Skip re-creating this crop's CONVENTIONAL events, but do NOT `continue`
                        # out of the crop entirely. The organic template is created further down,
                        # so bailing here meant a crop that already had a conventional template
                        # could never gain an organic one — the only way to add organic coverage
                        # was --force, which deletes and rebuilds the conventional template as a
                        # side effect. Seeding should be additive.
                        conventional_events_needed = False

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

                # Conventional events already exist for this crop — iterate nothing rather than
                # re-creating them, and fall through to the organic block below.
                if not conventional_events_needed:
                    events_data = []

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

                # --- Organic template (if applicable) ---
                organic_overrides = ORGANIC_OVERRIDES.get(crop_slug)
                if organic_overrides and not dry_run:
                    organic_slug = f"{crop_slug}_organic_v3"

                    if force:
                        existing_organic = ProductionTemplate.objects.filter(slug=organic_slug)
                        if existing_organic.exists():
                            existing_organic.delete()
                            self.stdout.write(f"  Deleted existing organic template: {organic_slug}")

                    organic_template, organic_created = ProductionTemplate.objects.get_or_create(
                        crop_type=crop_type,
                        slug=organic_slug,
                        defaults={
                            "name": f"{crop_type.name} - Organic Production",
                            "farming_approach": "organic",
                            "complexity_level": "intermediate",
                            "estimated_setup_time": 10,
                            "description": (
                                f"Organic production template for {crop_type.name} using "
                                "OMRI-listed and NOP-approved inputs. All 7 event types "
                                "with organic-specific defaults."
                            ),
                            "compliance_notes": (
                                "Designed for USDA NOP certified operations (7 CFR Part 205). "
                                "All inputs are OMRI-listed or NOP-approved. Includes organic "
                                "seed search documentation, equipment cleaning logs, and "
                                "certification inspection events."
                            ),
                            "usda_compliant": True,
                            "usda_reviewed": True,
                            "projected_emissions_reduction": 15.0,
                            # NOT "20-35%". `compliance.md` bans stating a price premium
                            # ("Premium positioning through transparency", never "earn premium
                            # prices" / "20-40% premium"), and the 20-40% USDA-premium figure
                            # this echoed is not a real sourced statistic. The field is
                            # serialized but currently rendered nowhere, so this was a latent
                            # claim rather than a live one — left at the model default so it
                            # cannot become one if a surface starts showing it.
                            "premium_pricing_potential": "0%",
                            "market_demand": "high",
                        },
                    )

                    if organic_created or force:
                        # Route to the correct organic event generator based on crop category.
                        # Tree crops (tree_fruit, tree_nut) use the full orchard template with
                        # pruning and canopy events. Annual crops (vegetable, berry) use a
                        # shorter template suited for seasonal production.
                        if crop_type.category in ["tree_fruit", "tree_nut"]:
                            organic_events = get_tree_crop_organic_events(crop_slug, crop_data, organic_overrides)
                        else:
                            organic_events = get_annual_crop_organic_events(crop_slug, crop_data, organic_overrides)

                        if force:
                            EventTemplate.objects.filter(production_template=organic_template).delete()

                        for event_data in organic_events:
                            evt_type = event_data["backend_event_type"]
                            subtype = event_data["backend_event_fields"].get(
                                "type",
                                event_data["backend_event_fields"].get("activity_type", "N/A"),
                            )

                            if not event_data.get("typical_amounts"):
                                event_data["typical_amounts"] = get_typical_amounts(
                                    evt_type, subtype, crop_data["typical_area"], crop_data
                                )
                            if not event_data.get("carbon_sources"):
                                event_data["carbon_sources"] = get_carbon_sources(evt_type, subtype)

                            event_data["production_template"] = organic_template
                            EventTemplate.objects.get_or_create(
                                production_template=organic_template,
                                name=event_data["name"],
                                defaults=event_data,
                            )

                        organic_event_count = EventTemplate.objects.filter(production_template=organic_template).count()
                        created_templates += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  Organic template: {organic_template.name} " f"({organic_event_count} events)"
                            )
                        )
                    else:
                        skipped_templates += 1
                        self.stdout.write(f"  Organic template exists: {organic_template.name}")

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
