"""
Almond demo production data for Coastal Valleys Ranch.

Realistic Nonpareil almond production in California's Central Valley.
25-hectare mature orchard with micro-sprinkler irrigation.

Sources:
    - Almond Board of California (almonds.org)
    - UC Davis Almond Production Cost Studies
    - UC IPM Almond Pest Management Guidelines (ipm.ucanr.edu)
    - CDFA Fertilization Guidelines for Almonds
    - EPA 40 CFR Part 98 emission factors
"""

from datetime import datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from carbon.models import CropType
from common.models import Gallery, GalleryImage
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    GeneralEvent,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from product.models import Parcel, Product

# Free-to-use Unsplash images for almond production events
ALMOND_IMAGES = {
    "almond_orchard": [
        "https://images.unsplash.com/photo-1583533230823-10efb2ba9a38?w=800&q=80",
    ],
    "almond_bloom": [
        "https://images.unsplash.com/photo-1551972873-b7e8754e8e26?w=800&q=80",
    ],
    "almond_harvest": [
        "https://images.unsplash.com/photo-1574856344991-aaa31b6f4ce3?w=800&q=80",
    ],
    "bee_pollination": [
        "https://images.unsplash.com/photo-1558642452-9d2a7deb7f62?w=800&q=80",
    ],
    "almond_processing": [
        "https://images.unsplash.com/photo-1608797178974-15b35a64ede9?w=800&q=80",
    ],
}


def _dt(year, month, day, hour=8):
    return datetime(year, month, day, hour, 0, tzinfo=dt_tz.utc)


def _create_album(image_key, demo_images=None):
    """Create a Gallery with GalleryImage(s) using free Unsplash URLs."""
    # Check almond-specific images first, then fall back to shared demo images
    urls = ALMOND_IMAGES.get(image_key, [])
    if not urls and demo_images:
        urls = demo_images.get(image_key, [])
    if not urls:
        return None
    gallery = Gallery.objects.create()
    for url in urls:
        GalleryImage.objects.create(gallery=gallery, image_url=url)
    return gallery


def create_almond_parcel(establishment, demo_images=None):
    """Create almond parcel, product, and crop type. Returns (parcel, product, crop_type)."""
    alm_product, _ = Product.objects.get_or_create(
        name="Almond",
        defaults={"description": "Nonpareil Almond"},
    )
    alm_crop, _ = CropType.objects.get_or_create(
        slug="almonds",
        defaults={
            "name": "Almond (Nonpareil)",
            "category": "tree_nut",
            "description": "Premium Nonpareil almond production",
            "typical_farm_size": "20-100 hectares",
            "growing_season": "February - October",
            "harvest_season": "August - September",
            "emissions_per_hectare": 3200.0,
            "industry_average": 3800.0,
            "best_practice": 2600.0,
            "carbon_credit_potential": 1.3,
            "typical_cost_per_hectare": 14000.0,
            "fertilizer_cost_per_hectare": 2800.0,
            "fuel_cost_per_hectare": 1600.0,
            "irrigation_cost_per_hectare": 2200.0,
            "labor_cost_per_hectare": 4500.0,
            "organic_premium": "20-35%",
            "sustainable_premium": "10-20%",
            "local_premium": "5-10%",
            "sustainability_opportunities": [
                "Micro-sprinkler irrigation efficiency",
                "Cover cropping between rows",
                "Mating disruption for NOW control",
                "Pollinator habitat restoration",
            ],
            "usda_factors_used": True,
            "data_source": "USDA ARS, UC Davis, Almond Board of CA",
        },
    )
    alm_parcel = Parcel.objects.create(
        name="Nonpareil Almond Orchard",
        description=(
            "25-hectare mature Nonpareil almond orchard in Central Valley. "
            "Trees 12-18 years old, micro-sprinkler irrigation, "
            "cross-pollinated with Monterey and Wood Colony varieties."
        ),
        establishment=establishment,
        product=alm_product,
        area=25.0,
        certified=True,
        certification_type="GLOBALG.A.P.",
        soil_type="Sandy Loam",
        contact_person="David Hernandez",
        address="Block C - East Section",
        agricultural_details={
            "primary_crop": "Nonpareil Almond",
            "planting_density": "275 trees/ha (112/acre)",
            "spacing": "6.7m x 5.5m (22ft x 18ft)",
            "pollinizer_varieties": "Monterey, Wood Colony",
            "pollinizer_ratio": "1:1 alternating rows",
            "irrigation_type": "Micro-sprinkler",
            "soil_ph": "7.0",
            "soil_organic_matter": "1.8%",
            "sustainability_practices": (
                "IPM, mating disruption for NOW, " "cover cropping, micro-sprinkler irrigation"
            ),
            "consumer_story": (
                "Our almond orchard comes alive every February when "
                "millions of honeybees arrive for pollination. We use "
                "mating disruption technology instead of broad-spectrum "
                "insecticides to protect both our crop and the bees "
                "that make it possible."
            ),
        },
        carbon_calculation_enabled=True,
    )
    return alm_parcel, alm_product, alm_crop


def create_almond_finished_events(prod, user, demo_images=None):
    """
    Create ~22 realistic events for a finished Nonpareil almond season (2024-2025).

    Timeline: Nov 2024 dormant pruning through Oct 2025 post-harvest.
    Uses all 7 event categories + almond-specific PO, PH, CM subtypes.
    """
    # 0: Soil Test (Soil Management)
    SoilManagementEvent.objects.create(
        history=prod,
        index=0,
        date=_dt(2024, 11, 5),
        description=(
            "Pre-season soil analysis across 25ha Nonpareil almond orchard. "
            "Lab results: pH 7.0, organic matter 1.8%, adequate potassium, "
            "nitrogen needs supplementation. Sandy loam texture, good drainage."
        ),
        created_by=user,
        performed_by="David Hernandez",
        type=SoilManagementEvent.SOIL_TEST,
        name="Annual Soil Analysis",
        soil_ph=Decimal("7.00"),
        organic_matter_percentage=Decimal("1.80"),
        soil_texture="sandy_loam",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        test_results={
            "ph": 7.0,
            "organic_matter_pct": 1.8,
            "nitrogen_ppm": 32,
            "phosphorus_ppm": 28,
            "potassium_ppm": 245,
            "zinc_ppm": 1.4,
            "boron_ppm": 0.6,
            "lab": "A&L Western Laboratories",
        },
        working_depth=Decimal("30.00"),
        depth_unit="cm",
        extra_data={"samples_collected": 40},
        album=_create_album("soil_test", demo_images),
    )

    # 1: Canopy Management - Dormant Pruning (CM subtype)
    ProductionEvent.objects.create(
        history=prod,
        index=1,
        date=_dt(2024, 12, 10),
        description=(
            "Dormant structural pruning of 25ha Nonpareil almond orchard. "
            "Thinning cuts to open canopy center, remove dead and crossing "
            "branches, and raise skirts for equipment clearance (30 inch "
            "minimum). Prunings chipped and left as mulch between rows."
        ),
        created_by=user,
        performed_by="Jose Garcia",
        type=ProductionEvent.CANOPY_MANAGEMENT,
        name="Dormant Structural Pruning",
        variety="Nonpareil",
        block_id="Block C - East Section",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        fuel_consumed=Decimal("22.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_type="tractor",
        equipment_hours=Decimal("40.00"),
        production_efficiency="normal",
        growth_stage="dormant",
        observation=(
            "Removed 8% canopy volume. Open center maintained for light "
            "penetration and spray coverage. Skirts raised to 30 inches."
        ),
        extra_data={
            "crew_size": 8,
            "biomass_chipped_tons": 15,
            "canopy_removed_pct": 8,
            "canopy_operation": "pruning",
            "pass_number": 1,
            "equipment_name": "John Deere 5075E with chipper",
            "skirt_clearance_inches": 30,
        },
        album=_create_album("pruning", demo_images),
    )

    # 2: Pre-Emergent Herbicide (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=2,
        date=_dt(2025, 1, 10),
        description=(
            "Chateau WDG (flumioxazin) pre-emergent herbicide application "
            "on tree rows for winter weed control. 370 g/ha rate applied "
            "to moist soil via ground sprayer. Tank-mixed with Alion for "
            "extended residual control through bloom."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.HERBICIDE,
        chemical_subtype="synthetic_herbicide",
        name="Winter Pre-Emergent Herbicide",
        commercial_name="Chateau WDG (flumioxazin) + Alion (indaziflam)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="dormant",
        volume="14.8",
        volume_unit="kg",
        concentration="51",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="pre_plant",
        weather_conditions="overcast_humid",
        target_pest_disease="Winter annual weeds, broadleaf weeds",
        organic_approved="not_organic",
        rei_hours=Decimal("12.0"),
        phi_days=Decimal("60.0"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("10.00"),
        application_fuel_unit="gal",
        extra_data={
            "active_ingredient": "Flumioxazin + Indaziflam",
            "application_details": "Tractor-mounted boom sprayer, incorporated 4 inches deep",
            "buffer_zone_meters": 15,
            "rate_g_ha": 370,
            "tank_mix": "Chateau WDG 8 oz/acre + Alion 5 oz/acre",
            "water_volume_L_ha": 280,
            "spray_equipment": "Tractor-mounted boom sprayer",
            "volume_unit": "kg",
        },
        album=_create_album("herbicide", demo_images),
    )

    # 3: Dormant Copper Spray for Bacterial Blast (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=3,
        date=_dt(2025, 1, 25),
        description=(
            "Badge X2 (copper hydroxide + copper oxychloride) dormant spray "
            "for bacterial blast (Pseudomonas syringae) prevention before "
            "bloom. 8.5 kg/ha rate via airblast sprayer. Critical timing: "
            "applied 2 weeks before anticipated bloom."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.FUNGICIDE,
        chemical_subtype="copper_fungicide",
        name="Dormant Copper - Bacterial Blast Prevention",
        commercial_name="Badge X2 (copper hydroxide + copper oxychloride)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="dormant",
        volume="212.5",
        volume_unit="kg",
        concentration="33",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="pre_plant",
        weather_conditions="overcast_humid",
        target_pest_disease="Bacterial blast (Pseudomonas syringae pv. syringae)",
        organic_approved="omri_listed",
        rei_hours=Decimal("48.0"),
        phi_days=Decimal("0.0"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("12.00"),
        application_fuel_unit="gal",
        buffer_zone_meters=Decimal("15"),
        extra_data={
            "rate_kg_ha": 8.5,
            "water_volume_L_ha": 935,
            "active_ingredient": "Copper hydroxide + Copper oxychloride",
            "spray_equipment": "Turbomist 500 airblast sprayer",
            "copper_metallic_pct": 24.8,
            "volume_unit": "kg",
            "application_details": "Turbomist 500 airblast sprayer at 8.5 kg/ha rate, full canopy coverage",
            "buffer_zone_meters": 15,
        },
        album=_create_album("fungicide", demo_images),
    )

    # 4: Pollination - Bee Colony Placement (PO subtype)
    ProductionEvent.objects.create(
        history=prod,
        index=4,
        date=_dt(2025, 2, 10),
        description=(
            "Placed 124 honeybee colonies (2 per acre) for Nonpareil almond "
            "pollination. Colonies sourced from Central Valley beekeeper, "
            "each with 8+ frames of bees (industry standard). Hives placed "
            "at orchard perimeter and internal access roads for maximum "
            "coverage. Cross-pollination with Monterey and Wood Colony "
            "varieties in alternating rows."
        ),
        created_by=user,
        performed_by="David Hernandez",
        type=ProductionEvent.POLLINATION,
        name="Honeybee Colony Placement for Bloom",
        variety="Nonpareil",
        block_id="Block C - East Section",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        production_efficiency="high",
        growth_stage="bloom",
        observation=(
            "Bloom began Feb 14, peak bloom Feb 22-28. "
            "Weather favorable: sunny, 15-18C, light winds. "
            "Excellent bee flight activity observed."
        ),
        extra_data={
            "is_summary": True,
            "date_start": "2025-02-10",
            "date_end": "2025-03-12",
            "event_count": 1,
            "colonies_placed": 124,
            "colonies_per_acre": 2,
            "colony_strength": "8+ frames of bees per colony",
            "hive_rental_per_colony": 225,
            "total_pollination_cost": 27900,
            "bee_source": "Central Valley Apiaries, Bakersfield CA",
            "pollinizer_varieties": "Monterey, Wood Colony",
            "bloom_start": "2025-02-14",
            "bloom_peak": "2025-02-22",
            "bloom_end": "2025-03-08",
            "colonies_removed": "2025-03-12",
            # Form-compatible keys
            "pollinator_type": "honeybee",
            "hive_count": 124,
            "placement_date": "2025-02-10",
            "removal_date": "2025-03-12",
        },
        album=_create_album("bee_pollination", demo_images),
    )

    # 5: First N Fertigation (Chemical - 20% of N budget)
    ChemicalEvent.objects.create(
        history=prod,
        index=5,
        date=_dt(2025, 3, 15),
        description=(
            "First nitrogen application (20% of season budget) via "
            "micro-sprinkler fertigation. CAN-17 (calcium ammonium nitrate "
            "17-0-0) at 290 L/ha. Post-bloom timing at full leaf-out. "
            "Total 7,250 L applied across 25 ha."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.FERTILIZER,
        chemical_subtype="synthetic_fertilizer",
        name="Spring N Fertigation (20%)",
        commercial_name="CAN-17 (calcium ammonium nitrate 17-0-0)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="leaf_out",
        concentration="17-0-0",
        volume="7250",
        volume_unit="L",
        area="25",
        area_unit="ha",
        way_of_application="fertigation",
        application_method_structured="drip",
        application_timing="post_emergence",
        weather_conditions="calm_dry",
        target_pest_disease="Post-bloom nitrogen, Leaf-out nutrition",
        organic_approved="not_organic",
        application_fuel_type="electric",
        application_fuel_consumed=Decimal("4.50"),
        application_fuel_unit="kWh",
        extra_data={
            "rate_L_ha": 290,
            "n_budget_pct": 20,
            "n_applied_lbs_acre": 42,
            "cost_usd": 3200,
            "volume_unit": "L",
        },
        album=_create_album("fertilizer", demo_images),
    )

    # 6: NOW Mating Disruption Setup (Pest Management)
    PestManagementEvent.objects.create(
        history=prod,
        index=6,
        date=_dt(2025, 4, 1),
        description=(
            "Deployed ISOMATE NOW Mist aerosol emitters for Navel Orangeworm "
            "(Amyelois transitella) mating disruption across 25 ha. "
            "62 emitters (1 per acre) hung at 2m height in canopy. "
            "Season-long pheromone release disrupts NOW mating, reducing "
            "insecticide applications. Also installed 20 wing traps for "
            "flight monitoring."
        ),
        created_by=user,
        performed_by="Ana Torres",
        type=PestManagementEvent.IPM_IMPLEMENTATION,
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="vegetative",
        pest_species="Navel Orangeworm (Amyelois transitella)",
        pest_pressure_level="Medium",
        action_threshold_met=False,
        beneficial_insects_used="no",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        ipm_strategy=(
            "Season-long mating disruption with ISOMATE NOW Mist emitters. "
            "Pheromone-based, reduces NOW mating success by 80-95%. "
            "Combined with winter sanitation (mummy nut removal) and "
            "monitoring traps for flight timing."
        ),
        extra_data={
            "name": "NOW Mating Disruption Program",
            "emitters_deployed": 62,
            "emitters_per_acre": 1,
            "product": "ISOMATE NOW Mist (Pacific Biocontrol)",
            "cost_per_acre": 112,
            "total_cost": 6944,
            "traps_installed": 20,
            "trap_type": "NOW wing trap with pheromone lure",
            "emitter_height_m": 2.0,
            "season_coverage": "April through September",
        },
        album=_create_album("ipm", demo_images),
    )

    # 7: Irrigation Season Summary (Production - Summary Mode)
    ProductionEvent.objects.create(
        history=prod,
        index=7,
        date=_dt(2025, 4, 15),
        description=(
            "Micro-sprinkler irrigation program for 25ha Nonpareil almond "
            "orchard. 28 irrigation cycles from March through October 2025, "
            "totaling 75,000,000 gallons (3.5 acre-ft/acre). Electric pump "
            "from 200ft deep well consuming 262,500 kWh total. Scheduling "
            "guided by CIMIS ET data and soil moisture sensors at 1ft and "
            "3ft depths."
        ),
        created_by=user,
        performed_by="Carlos Mendoza",
        type=ProductionEvent.IRRIGATION,
        name="Season Irrigation Program",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="vegetative",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        fuel_consumed=Decimal("262500.00"),
        fuel_unit="kWh",
        fuel_type="electric",
        water_source="well_groundwater",
        pump_depth_ft=Decimal("200.0"),
        electricity_source="grid",
        irrigation_method="micro_sprinkler",
        irrigation_depth=Decimal("3.50"),
        irrigation_depth_unit="inches",
        production_efficiency="high",
        observation=(
            "CIMIS station #39 (Parlier) ET data + soil moisture probes. "
            "Deficit irrigation applied pre-harvest (July) to manage hull rot."
        ),
        extra_data={
            "is_summary": True,
            "date_start": "2025-03-01",
            "date_end": "2025-10-15",
            "event_count": 28,
            "water_volume_total": 75000000,
            "water_volume_unit": "gallons",
            "acre_feet_per_acre": 3.5,
            "irrigation_depth": "3.5",
            "irrigation_depth_unit": "inches",
            "irrigation_method": "micro_sprinkler",
            "water_source": "well_groundwater",
            "well_depth_ft": 200,
            "pump_efficiency_pct": 85,
            "scheduling_method": "CIMIS ET + soil moisture sensors",
        },
        album=_create_album("almond_orchard", demo_images),
    )

    # 8: Second N Fertigation (Chemical - 30% of N budget)
    ChemicalEvent.objects.create(
        history=prod,
        index=8,
        date=_dt(2025, 4, 20),
        description=(
            "Second nitrogen application (30% of season budget) via "
            "fertigation. UAN-32 (32-0-0) at 195 L/ha, leaf-out to "
            "shell hardening stage. 4,875 L total across 25 ha."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.FERTILIZER,
        chemical_subtype="synthetic_fertilizer",
        name="Spring N Fertigation (30%)",
        commercial_name="UAN-32 (32-0-0)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="fruit_set",
        concentration="32-0-0",
        volume="4875",
        volume_unit="L",
        area="25",
        area_unit="ha",
        way_of_application="fertigation",
        application_method_structured="drip",
        application_timing="fruit_development",
        weather_conditions="calm_dry",
        target_pest_disease="Shell hardening nitrogen, Nut fill support",
        organic_approved="not_organic",
        application_fuel_type="electric",
        application_fuel_consumed=Decimal("4.50"),
        application_fuel_unit="kWh",
        extra_data={
            "rate_L_ha": 195,
            "n_budget_pct": 30,
            "n_applied_lbs_acre": 65,
            "volume_unit": "L",
        },
        album=_create_album("fertilizer", demo_images),
    )

    # 9: Potassium Fertigation (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=9,
        date=_dt(2025, 5, 10),
        description=(
            "Protassium+ SOP (sulfate of potash 0-0-50) ground-banded "
            "application at 560 kg/ha (500 lbs/acre). Peak potassium "
            "demand period March-May. Banded 1.5m from trunk line."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.FERTILIZER,
        chemical_subtype="synthetic_fertilizer",
        name="Spring Potassium Application",
        commercial_name="Protassium+ SOP (sulfate of potash 0-0-50)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="fruit_set",
        concentration="0-0-50",
        volume="14000",
        volume_unit="kg",
        area="25",
        area_unit="ha",
        way_of_application="banded",
        application_method_structured="banding",
        application_timing="fruit_development",
        weather_conditions="calm_dry",
        target_pest_disease="Potassium replenishment, Nut development",
        organic_approved="not_organic",
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("8.00"),
        application_fuel_unit="gal",
        extra_data={
            "rate_kg_ha": 560,
            "rate_lbs_acre": 500,
            "band_distance_m": 1.5,
            "cost_usd": 7000,
            "volume_unit": "kg",
        },
        album=_create_album("fertilizer", demo_images),
    )

    # 10: Third N Fertigation (Chemical - 30% of N budget)
    ChemicalEvent.objects.create(
        history=prod,
        index=10,
        date=_dt(2025, 5, 25),
        description=(
            "Third nitrogen application (30% of season budget). UAN-32 "
            "at 195 L/ha during shell hardening to nut fill. 4,875 L total."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.FERTILIZER,
        chemical_subtype="synthetic_fertilizer",
        name="Nut Fill N Fertigation (30%)",
        commercial_name="UAN-32 (32-0-0)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="maturation",
        concentration="32-0-0",
        volume="4875",
        volume_unit="L",
        area="25",
        area_unit="ha",
        way_of_application="fertigation",
        application_method_structured="drip",
        application_timing="fruit_development",
        weather_conditions="calm_dry",
        target_pest_disease="Nut fill nitrogen, Kernel development",
        organic_approved="not_organic",
        application_fuel_type="electric",
        application_fuel_consumed=Decimal("4.50"),
        application_fuel_unit="kWh",
        extra_data={
            "rate_L_ha": 195,
            "n_budget_pct": 30,
            "n_applied_lbs_acre": 65,
            "volume_unit": "L",
        },
        album=_create_album("fertilizer", demo_images),
    )

    # 11: Hull Rot Fungicide (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=11,
        date=_dt(2025, 6, 15),
        description=(
            "Merivon (fluxapyroxad + pyraclostrobin) fungicide application "
            "for hull rot (Monilinia, Rhizopus) prevention. Applied 3 weeks "
            "before anticipated hull split at 0.75 L/ha via airblast sprayer. "
            "Irrigation reduced 2 weeks prior to limit hull rot conditions."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.FUNGICIDE,
        chemical_subtype="synthetic_fungicide",
        name="Hull Rot Prevention (Merivon)",
        commercial_name="Merivon (fluxapyroxad + pyraclostrobin)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="fruit_set",
        volume="18.75",
        volume_unit="L",
        concentration="42",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="fruit_development",
        weather_conditions="calm_dry",
        target_pest_disease="Hull rot (Monilinia fructicola, Rhizopus stolonifer)",
        organic_approved="not_organic",
        rei_hours=Decimal("12.0"),
        phi_days=Decimal("0.0"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("12.00"),
        application_fuel_unit="gal",
        extra_data={
            "rate_L_ha": 0.75,
            "frac_group": "FRAC 7 + FRAC 11",
            "water_volume_L_ha": 935,
            "spray_equipment": "Turbomist 500 airblast sprayer",
            "active_ingredient": "Fluxapyroxad + Pyraclostrobin",
            "irrigation_reduced": True,
            "volume_unit": "L",
        },
        album=_create_album("fungicide", demo_images),
    )

    # 12: NOW Insecticide Spray #1 at Hull Split (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=12,
        date=_dt(2025, 7, 10),
        description=(
            "Altacor (chlorantraniliprole) insecticide at 1% hull split "
            "for Navel Orangeworm (NOW) control. 0.137 kg/ha rate via "
            "airblast sprayer. First of two hull split sprays."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.PESTICIDE,
        chemical_subtype="synthetic_pesticide",
        name="NOW Hull Split Spray #1 (Altacor)",
        commercial_name="Altacor (chlorantraniliprole)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="maturation",
        volume="3.43",
        volume_unit="kg",
        concentration="35",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="fruit_development",
        weather_conditions="calm_dry",
        target_pest_disease="Navel Orangeworm (Amyelois transitella)",
        organic_approved="not_organic",
        rei_hours=Decimal("4.0"),
        phi_days=Decimal("10.0"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("12.00"),
        application_fuel_unit="gal",
        extra_data={
            "rate_oz_acre": 3.0,
            "rate_kg_ha": 0.137,
            "hull_split_pct": 1,
            "spray_number": "1 of 2",
            "water_volume_L_ha": 935,
            "active_ingredient": "Chlorantraniliprole",
            "spray_equipment": "Turbomist 500 airblast sprayer",
            "irac_group": "Group 28 (diamide)",
            "volume_unit": "kg",
        },
        album=_create_album("pesticide", demo_images),
    )

    # 13: NOW Insecticide Spray #2 (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=13,
        date=_dt(2025, 7, 24),
        description=(
            "Intrepid 2F (methoxyfenozide) insecticide second hull split "
            "spray, 14 days after first. 1.17 L/ha rate targeting NOW "
            "second generation. Rotated mode of action from Altacor."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.PESTICIDE,
        chemical_subtype="synthetic_pesticide",
        name="NOW Hull Split Spray #2 (Intrepid 2F)",
        commercial_name="Intrepid 2F (methoxyfenozide)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="maturation",
        volume="29.25",
        volume_unit="L",
        concentration="22.6",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="fruit_development",
        weather_conditions="calm_dry",
        target_pest_disease="Navel Orangeworm (Amyelois transitella)",
        organic_approved="not_organic",
        rei_hours=Decimal("4.0"),
        phi_days=Decimal("14.0"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("12.00"),
        application_fuel_unit="gal",
        extra_data={
            "rate_L_ha": 1.17,
            "rate_fl_oz_acre": 16,
            "spray_number": "2 of 2",
            "rotation_note": "Mode of action rotation from Group 28 to Group 18",
            "active_ingredient": "Methoxyfenozide",
            "irac_group": "Group 18 (diacylhydrazine)",
            "water_volume_L_ha": 935,
            "volume_unit": "L",
        },
        album=_create_album("pesticide", demo_images),
    )

    # 14: Heat Wave (Weather)
    WeatherEvent.objects.create(
        history=prod,
        index=14,
        date=_dt(2025, 7, 18),
        description=(
            "4-day extreme heat event with temperatures reaching 44C (111F). "
            "Increased irrigation frequency and applied overhead cooling. "
            "Some hull closure delay on south-facing canopy. No significant "
            "kernel damage."
        ),
        created_by=user,
        performed_by="David Hernandez",
        type=WeatherEvent.HIGH_TEMPERATURE,
        observation=(
            "Peak temps 44C/111F days 2-3. Extra irrigation applied "
            "25,000 gal/day. Hull split progression delayed ~5 days "
            "on south-facing canopy."
        ),
        extra_data={
            "event_name": "Central Valley Heat Wave",
            "highest_temperature": "44",
            "start_date": "2025-07-18T10:00",
            "end_date": "2025-07-21T18:00",
            "duration_days": 4,
            "extra_irrigation_gal": 100000,
            "hull_split_delay_days": 5,
        },
    )

    # 15: Harvest - Shaking (Production HA)
    ProductionEvent.objects.create(
        history=prod,
        index=15,
        date=_dt(2025, 8, 12),
        description=(
            "Mechanical tree shaking of 6,875 Nonpareil almond trees across "
            "25 ha. Self-propelled trunk shaker processed ~200 trees/hour. "
            "Nonpareil harvested first (earliest hull split variety). "
            "Total fuel consumption 55 gallons diesel."
        ),
        created_by=user,
        performed_by="Jose Garcia",
        type=ProductionEvent.HARVESTING,
        name="Harvest - Mechanical Shaking",
        variety="Nonpareil",
        block_id="Block C - East Section",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        fuel_consumed=Decimal("55.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_type="tractor",
        equipment_hours=Decimal("35.00"),
        production_efficiency="high",
        growth_stage="harvest_ready",
        observation=("Clean shake with minimal bark damage. 95% of nuts " "dropped on first pass."),
        extra_data={
            "trees_shaken": 6875,
            "trees_per_hour": 200,
            "equipment_name": "Orchard-Rite self-propelled trunk shaker",
            "shake_passes": 1,
            "ground_dry_days_target": "7-10 days on ground",
        },
        album=_create_album("almond_harvest", demo_images),
    )

    # 16: Harvest - Sweeping & Pickup (Production HA)
    ProductionEvent.objects.create(
        history=prod,
        index=16,
        date=_dt(2025, 8, 22),
        description=(
            "Mechanical sweeping into windrows followed by pickup after "
            "7-10 days of ground drying. Flory 8800 sweeper formed "
            "windrows, Exact pickup harvester collected. Total yield "
            "170,000 kg kernel weight (2,755 kg/ha). Kernel moisture "
            "4.8% at pickup."
        ),
        created_by=user,
        performed_by="Jose Garcia",
        type=ProductionEvent.HARVESTING,
        name="Harvest - Sweeping & Pickup",
        variety="Nonpareil",
        block_id="Block C - East Section",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        yield_quantity=Decimal("170000.00"),
        yield_unit="kg",
        harvest_quality_grade="grade_a",
        fuel_consumed=Decimal("45.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_type="tractor",
        equipment_hours=Decimal("28.00"),
        production_efficiency="high",
        growth_stage="harvest_ready",
        observation=(
            "Kernel moisture 4.8% at pickup. Excellent quality: "
            "minimal insect damage (NOW < 1%), no mold. "
            "2,755 kg/ha (2,460 lbs/acre)."
        ),
        extra_data={
            "equipment_sweeper": "Flory 8800 Series sweeper",
            "equipment_harvester": "Exact Corp pickup harvester",
            "kernel_moisture_pct": 4.8,
            "now_damage_pct": 0.8,
            "yield_kg_ha": 2755,
            "yield_lbs_acre": 2460,
            "crew_size": 6,
        },
        album=_create_album("almond_harvest", demo_images),
    )

    # 17: Post-Harvest Processing - Hulling & Shelling (PH subtype)
    ProductionEvent.objects.create(
        history=prod,
        index=17,
        date=_dt(2025, 9, 5),
        description=(
            "Post-harvest hulling and shelling of 170,000 kg almonds at "
            "Blue Diamond receiving station. Hulls removed by rollers and "
            "beaters, shells cracked by impactors, kernels air-separated "
            "and graded. USDA grade: 87% U.S. Extra No. 1. "
            "Hulls sold as dairy feed, shells for biomass energy."
        ),
        created_by=user,
        performed_by="David Hernandez",
        type=ProductionEvent.POST_HARVEST_PROCESSING,
        name="Hulling & Shelling",
        variety="Nonpareil",
        block_id="Block C - East Section",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        fuel_consumed=Decimal("850.00"),
        fuel_unit="kWh",
        fuel_type="electric",
        production_efficiency="high",
        growth_stage="post_harvest",
        observation=(
            "87% U.S. Extra No. 1 grade. NOW damage 0.8% (well below "
            "2% reject threshold). Hulls: 340 tons to dairy feed. "
            "Shells: 85 tons to biomass."
        ),
        extra_data={
            "processor": "Blue Diamond Growers, Sacramento CA",
            "processing_method": "Mechanical hulling + impact shelling",
            "usda_grade": "U.S. Extra No. 1",
            "grade_pct": 87,
            "kernel_weight_kg": 170000,
            "hull_weight_tons": 340,
            "hull_destination": "Dairy feed",
            "shell_weight_tons": 85,
            "shell_destination": "Biomass energy",
            "now_damage_pct": 0.8,
            "reject_threshold_pct": 2.0,
        },
        album=_create_album("almond_processing", demo_images),
    )

    # 18: Fall Foliar Nutrition - Zinc & Boron (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=18,
        date=_dt(2025, 10, 5),
        description=(
            "Fall foliar spray of zinc sulfate (36% Zn) and Solubor "
            "(20.5% B) before leaf drop. Addresses zinc deficiency "
            "identified in soil test (1.4 ppm, below 15 ppm leaf threshold). "
            "Boron at 3.4 kg/ha, zinc sulfate at 5.6 kg/ha."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.FERTILIZER,
        chemical_subtype="synthetic_fertilizer",
        name="Fall Foliar Zinc & Boron",
        commercial_name="Zinc Sulfate (36% Zn) + Solubor (20.5% B)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="post_harvest",
        concentration="36-0-0",
        volume="225",
        volume_unit="kg",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="post_harvest",
        weather_conditions="calm_dry",
        target_pest_disease="Zinc deficiency correction, Boron replenishment",
        organic_approved="not_organic",
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("12.00"),
        application_fuel_unit="gal",
        extra_data={
            "zinc_sulfate_rate_kg_ha": 5.6,
            "solubor_rate_kg_ha": 3.4,
            "water_volume_gal_acre": 100,
            "spray_equipment": "Turbomist 500 airblast",
            "timing": "Before leaf drop, October",
            "volume_unit": "kg",
        },
        album=_create_album("fertilizer", demo_images),
    )

    # 19: Post-Harvest Herbicide (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=19,
        date=_dt(2025, 10, 15),
        description=(
            "Rely 280 (glufosinate-ammonium) post-harvest burndown "
            "herbicide for resistant broadleaf weeds and winter annuals. "
            "Non-selective contact herbicide applied to tree rows only."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.HERBICIDE,
        chemical_subtype="synthetic_herbicide",
        name="Post-Harvest Weed Burndown",
        commercial_name="Rely 280 (glufosinate-ammonium)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="post_harvest",
        volume="92.5",
        volume_unit="L",
        concentration="24.5",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="post_harvest",
        weather_conditions="calm_dry",
        target_pest_disease="Glyphosate-resistant weeds, Winter annuals",
        organic_approved="not_organic",
        rei_hours=Decimal("12.0"),
        phi_days=Decimal("14.0"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("10.00"),
        application_fuel_unit="gal",
        extra_data={
            "rate_L_ha": 3.7,
            "water_volume_L_ha": 280,
            "spray_equipment": "Tractor-mounted boom, shielded nozzles",
            "active_ingredient": "Glufosinate-ammonium",
            "target_weeds": "Fleabane, marestail, pigweed",
            "volume_unit": "L",
        },
        album=_create_album("herbicide", demo_images),
    )

    # 20: GLOBALG.A.P. Certification Audit (Business)
    BusinessEvent.objects.create(
        history=prod,
        index=20,
        date=_dt(2025, 9, 15),
        description=(
            "Annual GLOBALG.A.P. IFA v6 certification audit for almond "
            "orchard conducted by SCS Global Services. All control points "
            "reviewed: food safety, traceability, IPM records, worker "
            "welfare, and environmental management. Certified with "
            "one minor observation."
        ),
        created_by=user,
        performed_by="Ana Torres",
        type=BusinessEvent.CERTIFICATION,
        name="GLOBALG.A.P. Annual Certification",
        business_type="certification",
        certification_type="global_gap",
        verification_status="verified",
        sustainability_practice="integrated_pest",
        verified_certifier_name="SCS Global Services",
        certificate_number="GGN-4052852100014-ALM-2025",
        observation=(
            "One minor observation: update chemical storage signage. "
            "Corrected within 48 hours. Strong IPM and mating "
            "disruption program highlighted as best practice."
        ),
        extra_data={
            "audit_date": "2025-09-15",
            "auditor": "SCS Global Services",
            "standard": "GLOBALG.A.P. IFA v6",
            "control_points": 217,
            "major_nc": 0,
            "minor_nc": 1,
            "valid_until": "2026-09-14",
        },
    )

    # 21: Mummy Nut Sanitation (General)
    GeneralEvent.objects.create(
        history=prod,
        index=21,
        date=_dt(2025, 10, 20),
        description=(
            "Post-harvest mummy nut sanitation across 25 ha. Removed "
            "remaining nuts from trees and ground to eliminate NOW "
            "overwintering habitat. Critical cultural control: must "
            "complete before mid-March for effective NOW reduction."
        ),
        created_by=user,
        performed_by="Jose Garcia",
        name="Mummy Nut Sanitation (NOW Control)",
        activity_type="pest_prevention",
        activity_name="Post-harvest mummy nut removal and destruction",
        duration="32",
        people_involved=10,
        observation=(
            "99% mummy removal achieved. Pole shakers for tree "
            "mummies, mechanical pickup for ground nuts. Destroyed "
            "by composting at high temperature."
        ),
        extra_data={
            "mummy_removal_pct": 99,
            "method": "Pole shaker + mechanical pickup",
            "disposal": "High-temperature composting",
            "target_pest": "Navel Orangeworm (overwintering larvae)",
            "crew_days": 4,
        },
    )

    return 22  # event count


def create_almond_current_events(prod, user, demo_images=None):
    """
    Create ~8 realistic events for an active Nonpareil almond season (2025-2026).

    Timeline: Nov 2025 dormant operations through early 2026.
    """
    # 0: Cover Crop Planting (Soil Management)
    SoilManagementEvent.objects.create(
        history=prod,
        index=0,
        date=_dt(2025, 11, 5),
        description=(
            "Planted triticale and crimson clover cover crop mix between "
            "almond rows at 45 kg/ha seeding rate. Improves soil organic "
            "matter (currently 1.8%), reduces erosion, and provides "
            "beneficial insect habitat."
        ),
        created_by=user,
        performed_by="Carlos Mendoza",
        type=SoilManagementEvent.COVER_CROP,
        name="Fall Cover Crop Planting",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        working_depth=Decimal("5.00"),
        depth_unit="cm",
        soil_ph=Decimal("7.00"),
        organic_matter_percentage=Decimal("1.80"),
        soil_texture="sandy_loam",
        soil_moisture="moderate",
        amendment_type="Triticale + Crimson Clover seed mix",
        amendment_amount="1125",
        fuel_consumed=Decimal("12.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_hours=Decimal("10.00"),
        equipment_used="John Deere 5100E with no-till drill",
        extra_data={
            "seed_mix": {
                "triticale_pct": 70,
                "crimson_clover_pct": 30,
            },
            "seeding_rate_kg_ha": 45,
            "expected_biomass_tons_ha": 5.0,
            "pollinator_benefit": "Crimson clover provides early-season forage for bees",
        },
        album=_create_album("cover_crop", demo_images),
    )

    # 1: Canopy Management - Dormant Pruning (CM subtype)
    ProductionEvent.objects.create(
        history=prod,
        index=1,
        date=_dt(2025, 12, 5),
        description=(
            "Annual dormant pruning focusing on dead wood removal, "
            "crossing branches, and skirt raising. Lighter pruning year "
            "to maximize bearing surface."
        ),
        created_by=user,
        performed_by="Jose Garcia",
        type=ProductionEvent.CANOPY_MANAGEMENT,
        name="Dormant Pruning - Light Year",
        variety="Nonpareil",
        block_id="Block C - East Section",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        fuel_consumed=Decimal("18.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_type="tractor",
        equipment_hours=Decimal("32.00"),
        production_efficiency="normal",
        growth_stage="dormant",
        observation=(
            "Light pruning year - removed 5% canopy. Focus on dead "
            "wood, low-hanging branches, and equipment clearance."
        ),
        extra_data={
            "crew_size": 6,
            "biomass_chipped_tons": 10,
            "canopy_removed_pct": 5,
            "canopy_operation": "pruning",
            "pass_number": 1,
            "equipment_name": "John Deere 5100E with chipper",
        },
        album=_create_album("pruning", demo_images),
    )

    # 2: Pre-Emergent Herbicide (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=2,
        date=_dt(2026, 1, 5),
        description=(
            "Prowl H2O (pendimethalin) pre-emergent herbicide at 4.7 L/ha "
            "for spring weed control. Applied to moist soil via ground "
            "sprayer. Activated by winter rain."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.HERBICIDE,
        chemical_subtype="synthetic_herbicide",
        name="Pre-Emergent Herbicide (Prowl H2O)",
        commercial_name="Prowl H2O (pendimethalin)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="dormant",
        volume="117.5",
        volume_unit="L",
        concentration="38.7",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="pre_plant",
        weather_conditions="overcast_humid",
        target_pest_disease="Annual grasses, Broadleaf weeds",
        organic_approved="not_organic",
        rei_hours=Decimal("24.0"),
        phi_days=Decimal("60.0"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("10.00"),
        application_fuel_unit="gal",
        extra_data={
            "rate_L_ha": 4.7,
            "water_volume_L_ha": 280,
            "active_ingredient": "Pendimethalin",
            "spray_equipment": "Tractor-mounted boom sprayer",
            "volume_unit": "L",
        },
        album=_create_album("herbicide", demo_images),
    )

    # 3: Dormant Copper Spray (Chemical)
    ChemicalEvent.objects.create(
        history=prod,
        index=3,
        date=_dt(2026, 1, 20),
        description=(
            "Kocide 3000 (copper hydroxide) dormant spray for bacterial "
            "blast prevention. 7.8 kg/ha rate, applied 2 weeks before "
            "anticipated bloom."
        ),
        created_by=user,
        performed_by="Roberto Silva",
        type=ChemicalEvent.FUNGICIDE,
        chemical_subtype="copper_fungicide",
        name="Dormant Copper - Bacterial Blast",
        commercial_name="Kocide 3000 (copper hydroxide)",
        variety="Nonpareil",
        block_id="Block C - East Section",
        growth_stage="dormant",
        volume="195",
        volume_unit="kg",
        concentration="46.1",
        area="25",
        area_unit="ha",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="pre_plant",
        weather_conditions="overcast_humid",
        target_pest_disease="Bacterial blast (Pseudomonas syringae)",
        organic_approved="omri_listed",
        rei_hours=Decimal("48.0"),
        phi_days=Decimal("0.0"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("12.00"),
        application_fuel_unit="gal",
        extra_data={
            "rate_kg_ha": 7.8,
            "water_volume_L_ha": 935,
            "active_ingredient": "Copper hydroxide",
            "spray_equipment": "Turbomist 500 airblast sprayer",
            "copper_metallic_pct": 30,
            "volume_unit": "kg",
        },
        album=_create_album("fungicide", demo_images),
    )

    # 4: Pollination - Bee Colony Placement (PO subtype)
    ProductionEvent.objects.create(
        history=prod,
        index=4,
        date=_dt(2026, 2, 8),
        description=(
            "Placed 124 honeybee colonies for 2026 bloom pollination. "
            "Colonies positioned at orchard edges and internal access roads. "
            "Bloom expected to begin around February 12-14."
        ),
        created_by=user,
        performed_by="David Hernandez",
        type=ProductionEvent.POLLINATION,
        name="Honeybee Colony Placement for 2026 Bloom",
        variety="Nonpareil",
        block_id="Block C - East Section",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        production_efficiency="normal",
        growth_stage="dormant",
        observation=(
            "Colonies placed Feb 8. Bud swell visible on Nonpareil, "
            "bloom expected in 5-7 days. Weather forecast favorable."
        ),
        extra_data={
            "colonies_placed": 124,
            "colonies_per_acre": 2,
            "colony_strength": "8+ frames of bees",
            "hive_rental_per_colony": 230,
            "total_pollination_cost": 28520,
            "bee_source": "Central Valley Apiaries, Bakersfield CA",
            "anticipated_bloom_start": "2026-02-12",
            # Form-compatible keys
            "pollinator_type": "honeybee",
            "hive_count": 124,
            "placement_date": "2026-02-08",
            "removal_date": "2026-03-10",
        },
        album=_create_album("bee_pollination", demo_images),
    )

    # 5: Frost Event (Weather)
    WeatherEvent.objects.create(
        history=prod,
        index=5,
        date=_dt(2026, 2, 20),
        description=(
            "Overnight radiation frost during early bloom. Temperatures "
            "dropped to -2C (28F) at 5:30am. Wind machines activated "
            "at 2am and ran for 5 hours. Some petal browning observed "
            "on exposed lower canopy but overall pollination unaffected."
        ),
        created_by=user,
        performed_by="David Hernandez",
        type=WeatherEvent.FROST,
        observation=(
            "Min temp -2C at 5:30am. Wind machines ran 2am-7am. "
            "Inversion layer present, wind machines effective. "
            "Petal browning on 3-5% of lower canopy flowers. "
            "Bee flight resumed normally by 10am."
        ),
        extra_data={
            "event_name": "Bloom Frost Event",
            "lower_temperature": "-2",
            "start_date": "2026-02-20T02:00",
            "end_date": "2026-02-20T07:30",
            "way_of_protection": "Wind machines (4 units)",
            "wind_machine_hours": 5,
            "wind_machines_count": 4,
            "fuel_consumed_gal": 50,
            "damage": "3-5% petal browning on lower canopy",
            "bloom_impact": "Minimal - pollination continued normally",
        },
    )

    # 6: NOW Trap Monitoring (Pest Management)
    PestManagementEvent.objects.create(
        history=prod,
        index=6,
        date=_dt(2026, 3, 1),
        description=(
            "Installed 20 NOW pheromone wing traps for first-flight "
            "monitoring. Traps placed at 8ft height in canopy on south "
            "side of trees. Will check weekly through harvest."
        ),
        created_by=user,
        performed_by="Ana Torres",
        type=PestManagementEvent.TRAP_MONITORING,
        pest_species="Navel Orangeworm (Amyelois transitella)",
        pest_pressure_level="Low",
        trap_count=20,
        action_threshold_met=False,
        beneficial_insects_used="no",
        area_covered=Decimal("25.00"),
        area_unit="ha",
        ipm_strategy=(
            "Weekly wing trap monitoring for NOW flight timing. "
            "First flight typically March-April. Data guides hull split "
            "insecticide spray timing. Mating disruption emitters "
            "to be deployed in April."
        ),
        extra_data={
            "name": "NOW First-Flight Trap Monitoring",
            "traps_per_block": 5,
            "trap_height_ft": 8,
            "trap_placement": "South side of tree canopy",
            "check_frequency": "Weekly",
            "first_moth_captured": None,
        },
        album=_create_album("trap_monitoring", demo_images),
    )

    # 7: Worker Safety Training (General)
    GeneralEvent.objects.create(
        history=prod,
        index=7,
        date=_dt(2026, 3, 5),
        description=(
            "Annual Worker Protection Standard (WPS) and heat illness "
            "prevention training for all almond orchard crew. Covers "
            "pesticide safety, PPE requirements, REI/PHI compliance, "
            "heat stress recognition, and harvest equipment safety. "
            "Bilingual training (English/Spanish)."
        ),
        created_by=user,
        performed_by="Ana Torres",
        name="Annual Worker Safety Training",
        activity_type="training",
        activity_name="WPS and harvest equipment safety certification",
        duration="6",
        people_involved=16,
        observation=(
            "All 16 crew members completed training. Special emphasis "
            "on shaker/sweeper safety and heat illness protocols for "
            "August harvest season."
        ),
        extra_data={
            "training_topics": [
                "Worker Protection Standard (EPA)",
                "Heat Illness Prevention (Cal/OSHA)",
                "Harvest Equipment Safety (shaker, sweeper, pickup)",
                "PPE Selection and Use",
            ],
            "certifications_issued": 16,
            "language": "Bilingual EN/ES",
            "trainer": "Kern County Farm Bureau",
        },
    )

    return 8  # event count
