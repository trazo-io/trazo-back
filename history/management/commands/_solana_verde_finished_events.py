"""
Solana Verde Organic Ranch — 24 finished-production events.

Covers the 2026-01-15 -> 2026-04-14 Hass Avocado season on Hillside Grove A.
Events map to Phase 7 of E2E_ORGANIC_FARM_TESTING_GUIDE.md (Events 1-21 + 8b = 22)
plus one PL replant event for seed_search_attempts (NOP 5029) coverage and one
post-finish POD delivery BusinessEvent (§ 205.501(a)(21) + § 205.103(b)(2) +
FSMA 204 shipping CTE) = 24 total.

NOP fields covered:
  - ChemicalEvent: supplier_name, purchase_date, purchase_invoice (events 3,7,10,13)
  - SoilManagementEvent: amendment_organic_approved, compost_peak_temp_f,
      compost_duration_days_at_temp, compost_turning_count (event 14/CO)
  - SoilManagementEvent: manure_harvest_interval, manure_application_date,
      amendment_organic_approved (event 21/OM)
  - PestManagementEvent: identified_by, identification_method, threshold_rationale (event 5/SC)
  - ProductionEvent: cleaning_date, cleaning_method, cleaning_materials_used,
      cleaned_by, shared_with_conventional (event 8b/EM)
  - ProductionEvent: seed_supplier_name, seed_purchase_date, seed_purchase_invoice,
      seed_certification_status, seed_search_attempts (event PL)
  - GeneralEvent: is_contamination_incident, contamination_source,
      contamination_affected_area, corrective_action_taken, corrective_action_date,
      certifier_notified, certifier_notification_date (event 20)
  - BusinessEvent (Sale/Delivery): bill_of_lading, purchase_order, invoice_number,
      buyer_organic_cert_on_file, organic_on_invoice, fsma_204_cte (event 24)
"""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal

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

from ._solana_verde_base import BUYER_NAME, PRE_HARVEST_ESTIMATE_LB, SEASON_CARTONS, SEASON_YIELD_KG, SEASON_YIELD_LB

# The fixture's packing and shipping events describe ONE truckload, not the season:
# 573,201 lb of sold fruit is ~14 refrigerated loads, and a single BOL for 286 short
# tons on one trailer is the kind of number a certifier notices immediately.
FIRST_LOAD_CARTONS = 1640
FIRST_LOAD_KG = 18600
FIRST_LOAD_LB = 41006
SEASON_LOADS = 14
# Pre-thinning estimate, before the fruit-drop revision to PRE_HARVEST_ESTIMATE_LB.
EARLY_ESTIMATE_LB = 650000
THINNED_LB = 65000

# Avocado-specific Unsplash images (free-to-use Unsplash License)
AVOCADO_IMAGES = {
    "avocado_grove": [
        # Green avocado grove hillside
        "https://images.unsplash.com/photo-1601004890684-d8cbf643f5f2?w=800&q=80",
    ],
    "avocado_harvest": [
        # Avocados hanging on tree branch
        "https://images.unsplash.com/photo-1726177551991-270f9e79b65e?w=800&q=80",
    ],
    "avocado_packed": [
        # Crates of harvested avocados
        "https://images.unsplash.com/photo-1573566291259-fd494a326b60?q=800&w=80",
    ],
}


def _dt(year, month, day, hour=8, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=dt_tz.utc)


def _create_album(image_key, demo_images=None):
    """Create Gallery with GalleryImage(s) from avocado-specific or shared demo images."""
    urls = AVOCADO_IMAGES.get(image_key, [])
    if not urls and demo_images:
        urls = demo_images.get(image_key, [])
    if not urls:
        return None
    gallery = Gallery.objects.create()
    for url in urls:
        GalleryImage.objects.create(gallery=gallery, image_url=url)
    return gallery


def create_finished_events(production, user, demo_images=None):
    """
    Create 24 NOP-complete events on the finished 2026 Hass Avocado production.

    Maps to Phase 7 Events 1-21 + 8b of E2E_ORGANIC_FARM_TESTING_GUIDE.md (22),
    plus one PL replant event (NOP 5029 seed_search_attempts) and one POD
    delivery BusinessEvent (§ 205.501(a)(21) downstream traceability) — 24 total.

    Returns the count of events created (24).
    """
    # ------------------------------------------------------------------ #
    # Event 1: Soil Test (ST) — 2026-01-10                                #
    # ------------------------------------------------------------------ #
    SoilManagementEvent.objects.create(
        history=production,
        index=1,
        date=_dt(2026, 1, 10, 9),
        description=(
            "Annual pre-season soil analysis across 85-acre Hillside Grove A. "
            "Full panel by A&L Western Labs: pH 6.5, OM 4.2%, N 45 ppm, P 35 ppm, "
            "K 280 ppm, CEC 18.5. Zinc slightly low at 2.1 ppm (threshold 2.5). "
            "Recommendation: foliar zinc application in spring. Cover crop residue "
            "improving OM trend (was 3.8% in 2024)."
        ),
        created_by=user,
        performed_by="A&L Western Laboratories",
        type=SoilManagementEvent.SOIL_TEST,
        name="Annual Pre-Season Soil Analysis",
        soil_ph=Decimal("6.50"),
        organic_matter_percentage=Decimal("4.20"),
        soil_texture="clay_loam",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        test_results={
            "ph": 6.5,
            "organic_matter_pct": 4.2,
            "nitrogen_ppm": 45,
            "phosphorus_ppm": 35,
            "potassium_ppm": 280,
            "zinc_ppm": 2.1,
            "cec": 18.5,
            "lab": "A&L Western Laboratories",
        },
        working_depth=Decimal("30.00"),
        depth_unit="cm",
        extra_data={"samples_collected": 30},
        album=_create_album("soil_test", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 21: Raw Manure (OM) — 2026-01-05 (pre-production, early)     #
    # Date ordered first in calendar but indexed 21 per E2E guide         #
    # ------------------------------------------------------------------ #
    SoilManagementEvent.objects.create(
        history=production,
        index=21,
        date=_dt(2026, 1, 5, 8),
        description=(
            "Applied aged horse manure (6 months stored, not composted to NOP standards — "
            "no temperature monitoring). Source: Hillside Equestrian Center, Fallbrook. "
            "Applied at 2 tons/acre to younger tree rows (planted 2022). "
            "120-day interval applies: crop contacts soil during ground harvest. "
            "Earliest safe harvest: May 5, 2026. Main harvest starts April 10 — "
            "this parcel section will NOT be harvested until after May 5."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=SoilManagementEvent.ORGANIC_MATTER,
        name="Winter Manure Application (Pre-Season)",
        area_covered=Decimal("16.19"),
        area_unit="ha",
        amendment_type="Aged horse manure (uncomposted, local stable)",
        amendment_amount="80",
        amendment_amount_unit="tons",
        fuel_consumed=Decimal("12.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_hours=Decimal("8.00"),
        equipment_used="John Deere 5075E with manure spreader",
        # NOP 7 CFR 205.203(b): amendment organic approval. Raw farm-sourced
        # manure is an allowed input WITH the § 205.203(c)(1) pre-harvest
        # interval — it is NOT an OMRI-listed product, so don't label it as one.
        amendment_organic_approved="yes",
        # NOP 7 CFR 205.203(c)(1): raw manure harvest interval
        # Note: avocado fruit contacts soil during ground collection -> 120 days
        manure_harvest_interval="120",
        manure_application_date=date(2026, 1, 5),
        extra_data={
            "manure_source": "Hillside Equestrian Center, Fallbrook CA",
            "application_rate_tons_acre": 2,
            "storage_duration_months": 6,
            "composted": False,
            "earliest_safe_harvest": "2026-05-05",
        },
        album=_create_album("organic_matter", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 2: Cover Crop Termination (CC) — 2026-01-12                  #
    # ------------------------------------------------------------------ #
    SoilManagementEvent.objects.create(
        history=production,
        index=2,
        date=_dt(2026, 1, 12, 7, 30),
        description=(
            "Mowed and incorporated winter cover crop mix (70% crimson clover, "
            "30% hairy vetch) using flail mower on John Deere 5075E. Cover crop "
            "was at peak bloom for maximum N-fixation (~120 lbs N/acre). Left residue "
            "on surface as mulch in erosion-prone zones. Estimated 2.8 tons dry matter/acre."
        ),
        created_by=user,
        performed_by="Miguel Ramirez (Farm Manager)",
        type=SoilManagementEvent.COVER_CROP,
        name="Winter Cover Crop Mow & Incorporation",
        area_covered=Decimal("17.20"),
        area_unit="ha",
        amendment_type="Green manure (crimson clover + hairy vetch mix)",
        amendment_amount="3500",
        fuel_consumed=Decimal("18.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_hours=Decimal("6.00"),
        equipment_used="John Deere 5075E with flail mower",
        extra_data={
            "seed_mix": {"crimson_clover_pct": 70, "hairy_vetch_pct": 30},
            "n_fixation_lbs_acre": 120,
            "dry_matter_tons_acre": 2.8,
        },
        album=_create_album("cover_crop", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 3: Organic Fertilizer (FE) — 2026-01-20                      #
    # NOP: supplier_name, purchase_date, purchase_invoice                  #
    # ------------------------------------------------------------------ #
    ChemicalEvent.objects.create(
        history=production,
        index=3,
        date=_dt(2026, 1, 20, 8),
        description=(
            "Pre-bloom fertility boost via fertigation. Neptune's Harvest Fish & Seaweed "
            "(2-3-1) OMRI-listed. Applied at 2.35 gal/acre through drip system. "
            "Target: support January bloom set and early fruit development. Soil moisture "
            "adequate from recent rain. Zinc foliar to follow separately per soil test."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ChemicalEvent.FERTILIZER,
        chemical_subtype="organic_fertilizer",
        name="Pre-Bloom Organic Fertilizer (Neptune's Harvest)",
        commercial_name="Neptune's Harvest Fish & Seaweed (2-3-1)",
        variety="Hass",
        block_id="Hillside Grove A",
        growth_stage="dormant",
        volume="200",
        volume_unit="gal",
        concentration="2-3-1",
        area="85",
        area_unit="acres",
        way_of_application="fertigation",
        application_method_structured="drip",
        is_fertigation=True,
        application_timing="pre_plant",
        weather_conditions="calm_dry",
        target_pest_disease="Pre-bloom bloom nutrition, early fruit development",
        organic_approved="omri_listed",
        # NOP 7 CFR 205.103 mass-balance traceability
        supplier_name="Hydra-Gardens Inc. (Neptune's Harvest)",
        purchase_date=date(2026, 1, 10),
        purchase_invoice="INV-HG-2026-0142",
        extra_data={
            "application_details": "Applied at 2.35 gal/acre through drip system",
            "application_fuel": "fertigation — no separate application fuel",
        },
        album=_create_album("fertilizer", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 4: Winter Irrigation (IR) — 2026-01-25                        #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=4,
        date=_dt(2026, 1, 25, 6),
        description=(
            "Scheduled winter irrigation. Soil moisture sensors (Teros-12) showed 18% VWC "
            "(threshold 22%). Applied ~0.3 inch through drip emitters (2 GPH at 24-inch "
            "spacing). Run time: 8 hours; well pump at 180 ft depth, 1,500 GPM capacity "
            "(~720,000 gallons). Next irrigation scheduled based on ET data from CIMIS "
            "station #152 (Fallbrook)."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ProductionEvent.IRRIGATION,
        name="Winter Drip Irrigation Cycle",
        variety="Hass",
        block_id="Hillside Grove A",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        fuel_consumed=Decimal("0.00"),
        fuel_unit="kWh",
        fuel_type="electric",
        equipment_hours=Decimal("8.00"),
        water_source="well_groundwater",
        irrigation_method="drip",
        irrigation_depth=Decimal("0.30"),
        irrigation_depth_unit="inches",
        pump_depth_ft=Decimal("180.0"),
        electricity_source="grid",
        production_efficiency="normal",
        extra_data={
            "soil_moisture_vwc_pct": 18,
            "threshold_vwc_pct": 22,
            "cimis_station": "#152 Fallbrook",
            "well_capacity_gpm": 1500,
            "total_water_gallons_est": 720000,
        },
        album=_create_album("avocado_grove", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 5: Pest Scouting (SC) — 2026-02-05                           #
    # NOP: identified_by, identification_method, threshold_rationale      #
    # ------------------------------------------------------------------ #
    PestManagementEvent.objects.create(
        history=production,
        index=5,
        date=_dt(2026, 2, 5, 8, 30),
        description=(
            "Bi-weekly IPM scout. Checked 20 sample trees (randomized grid pattern). "
            "Found low avocado thrips populations on new flush growth (avg 2.3 thrips/leaf, "
            "threshold is 5/leaf). No persea mite detected. Green lacewing and minute pirate "
            "bug populations healthy (natural biocontrol). Avocado lace bug absent. "
            "No action needed — beneficial insect populations maintaining control. "
            "Continue monitoring every 2 weeks."
        ),
        created_by=user,
        performed_by="Carlos Mendez (IPM Scout)",
        type=PestManagementEvent.SCOUTING,
        # NOP 7 CFR 205.206: pest identification
        pest_species="Scirtothrips perseae (Avocado Thrips)",
        pest_pressure_level="Low",
        damage_percentage=Decimal("3.00"),
        action_threshold_met=False,
        beneficial_insects_used="yes",
        beneficial_species="Chrysoperla rufilabris (Green Lacewing), Orius insidiosus (Minute Pirate Bug)",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        ipm_strategy=(
            "Bi-weekly scouting with UC Davis IPM field guide thresholds. "
            "Beneficial insect populations maintaining biological control of thrips. "
            "No chemical intervention warranted at this time."
        ),
        # NOP 7 CFR 205.206: identification verification fields
        identified_by="crop_consultant",
        identification_method=("Visual inspection using 10x hand lens, UC Davis IPM field guide"),
        # NOP 7 CFR 205.206(e): action threshold rationale
        threshold_rationale=(
            "Avg 2.3 thrips/leaf on 20 sample trees, below 5/leaf economic threshold "
            "per UC Davis IPM guidelines for Hass avocados. Beneficial insect populations "
            "maintaining control."
        ),
        extra_data={
            "sample_trees": 20,
            "sampling_method": "Randomized grid pattern",
            "thrips_per_leaf_avg": 2.3,
            "thrips_threshold": 5.0,
        },
        album=_create_album("scouting", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 6: Beneficial Insect Release (BR) — 2026-02-15               #
    # ------------------------------------------------------------------ #
    PestManagementEvent.objects.create(
        history=production,
        index=6,
        date=_dt(2026, 2, 15, 17),
        description=(
            "Preventive green lacewing release for thrips biocontrol. Chrysoperla rufilabris "
            "eggs from Rincon-Vitova Insectaries. Release rate: 50,000 eggs/acre distributed "
            "via slow-release capsules hung on tree branches. Evening release at 68F, 45% "
            "humidity, calm winds. Expected larval emergence in 4-5 days. Lacewing larvae "
            "are voracious thrips predators. This is our 3rd annual release — established "
            "populations supplemented with fresh genetics. Cost: $0.85/1000 eggs = $3,612 total."
        ),
        created_by=user,
        performed_by="Carlos Mendez, Maria Gutierrez",
        type=PestManagementEvent.BENEFICIAL_RELEASE,
        pest_species="Avocado Thrips (Scirtothrips perseae)",
        pest_pressure_level="Low",
        beneficial_species="Chrysoperla rufilabris (Green Lacewing)",
        release_quantity="50,000 eggs/acre (4,250,000 total)",
        action_threshold_met=False,
        beneficial_insects_used="yes",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        ipm_strategy=(
            "Preventive biological control using green lacewing eggs. "
            "Season-long population establishment to maintain thrips below economic threshold."
        ),
        extra_data={
            "name": "Green Lacewing Release",
            "supplier": "Rincon-Vitova Insectaries",
            "release_rate_eggs_acre": 50000,
            "total_eggs": 4250000,
            "cost_per_1000_eggs": 0.85,
            "total_cost": 3612,
        },
        album=_create_album("beneficial_insects", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 7: Organic Fungicide (FU) — 2026-02-20                       #
    # NOP: supplier_name, purchase_date, purchase_invoice                  #
    # ------------------------------------------------------------------ #
    ChemicalEvent.objects.create(
        history=production,
        index=7,
        date=_dt(2026, 2, 20, 7),
        description=(
            "Preventive anthracnose spray (Kocide 3000, OMRI listed). Applied at 1 lb/acre "
            "via airblast sprayer (John Deere 5075E + Rears Pul-Blast 500). Full canopy "
            "coverage. 300 GPA spray volume. REI 48 hours posted. Buffer zone maintained "
            "30m from Reche Creek. Application 1 of 3 for season."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ChemicalEvent.FUNGICIDE,
        chemical_subtype="copper_fungicide",
        name="Preventive Copper Fungicide - Anthracnose",
        commercial_name="Kocide 3000 (Copper Hydroxide 46.1%)",
        variety="Hass",
        block_id="Hillside Grove A",
        growth_stage="dormant",
        volume="85",
        volume_unit="lb",
        concentration="46.1",
        area="85",
        area_unit="acres",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="dormant",
        weather_conditions="calm_dry",
        target_pest_disease="Anthracnose (Colletotrichum gloeosporioides)",
        organic_approved="omri_listed",
        rei_hours=Decimal("48.0"),
        phi_days=Decimal("0.0"),
        epa_registration_number="352-662",
        applicator_name="Miguel Ramirez",
        applicator_certification="CA QAL-4287",
        buffer_zone_meters=Decimal("30"),
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("12.00"),
        application_fuel_unit="gal",
        # NOP 7 CFR 205.103 mass-balance traceability
        supplier_name="Certis USA (Kocide manufacturer)",
        purchase_date=date(2026, 2, 10),
        purchase_invoice="INV-CU-2026-0087",
        extra_data={
            "application_details": "Full canopy coverage, 300 GPA spray volume",
            "active_ingredient": "Copper Hydroxide",
            "spray_equipment": "John Deere 5075E + Rears Pul-Blast 500",
        },
        album=_create_album("fungicide", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 8: Post-Bloom Pruning (PR) — 2026-02-25                      #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=8,
        date=_dt(2026, 2, 25, 7),
        description=(
            "Selective pruning on all 4,250 trees. Removed dead/crossing branches, opened "
            "canopy center for light penetration, maintained 12-15ft height for hand-picking "
            "harvest. Crew of 8 with hand pruners, loppers, and pole saws (gas chainsaws for "
            "large limbs only). Prunings chipped on-site and distributed as mulch between rows. "
            "No prunings removed from property — all organic matter recycled. "
            "Approximately 2.5 tons of prunings generated."
        ),
        created_by=user,
        performed_by="Pruning crew (8 workers), supervised by Miguel Ramirez",
        type=ProductionEvent.PRUNING,
        name="Post-Bloom Selective Pruning",
        variety="Hass",
        block_id="Hillside Grove A",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        fuel_consumed=Decimal("3.00"),
        fuel_unit="gal",
        fuel_type="gasoline",
        equipment_type="other",
        equipment_hours=Decimal("24.00"),
        production_efficiency="normal",
        growth_stage="dormant",
        extra_data={
            "crew_size": 8,
            "prunings_tons": 2.5,
            "prunings_disposal": "Chipped on-site, distributed as mulch",
            "canopy_target_height_ft": "12-15",
        },
        album=_create_album("pruning", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 8b: Post-Pruning Equipment Cleaning (EM) — 2026-02-26        #
    # NOP 7 CFR 205.272: equipment cleaning when shared w/ conventional   #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=9,
        date=_dt(2026, 2, 26, 8),
        description=(
            "Cleaned all pruning equipment (3 chainsaws, 8 hand pruners, 2 pole saws, "
            "1 wood chipper) after use. Equipment was borrowed by Rodriguez Ranch "
            "(conventional) last week — full cleaning protocol per NOP 205.272 before use "
            "on organic orchard. Pressure washed all contact surfaces, followed by SaniDate "
            "sanitizer rinse. All equipment inspected for residue. Cleaning log photographed."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ProductionEvent.EQUIPMENT_MAINTENANCE,
        name="Post-Pruning Equipment Cleaning",
        variety="Hass",
        block_id="Hillside Grove A",
        equipment_type="other",
        equipment_hours=Decimal("1.50"),
        production_efficiency="normal",
        equipment_operation_type="CL",
        # NOP 7 CFR 205.272: equipment cleaning log fields
        cleaning_date=date(2026, 2, 26),
        cleaning_method="Pressure wash + manual scrub with brushes",
        cleaning_materials_used=(
            "Water, NOP-approved BioSafe Systems SaniDate " "(hydrogen peroxide + peroxyacetic acid)"
        ),
        cleaned_by="Miguel Ramirez (Farm Manager)",
        shared_with_conventional=True,
        cleaning_protocol_reference="SOP-CLEAN-001 (NOP 205.272 Compliance)",
        extra_data={
            "equipment_cleaned": [
                "3 chainsaws",
                "8 hand pruners",
                "2 pole saws",
                "1 wood chipper",
            ],
            "conventional_operator": "Rodriguez Ranch (conventional citrus)",
        },
        album=_create_album("cultivation", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 9 (guide #9): Spring Irrigation (IR) — 2026-03-05            #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=10,
        date=_dt(2026, 3, 5, 6),
        description=(
            "Spring irrigation increasing as ET rises — ~0.4 inch applied over 10 h at "
            "1,500 GPM (~900,000 gallons). Fruit set confirmed on 90% of bloom clusters. "
            "Soil moisture sensors show faster depletion (22% to 16% in 5 days vs 7 days in "
            "winter). CIMIS ET0 data: 0.12 inches/day. Next irrigation in 10-12 days based "
            "on sensor readings and ET modeling."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ProductionEvent.IRRIGATION,
        name="Spring Drip Irrigation — Fruit Set",
        variety="Hass",
        block_id="Hillside Grove A",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        fuel_type="electric",
        equipment_hours=Decimal("10.00"),
        water_source="well_groundwater",
        irrigation_method="drip",
        irrigation_depth=Decimal("0.40"),
        irrigation_depth_unit="inches",
        pump_depth_ft=Decimal("180.0"),
        electricity_source="grid",
        production_efficiency="normal",
        extra_data={
            "cimis_et0_inches_day": 0.12,
            "soil_moisture_depletion_days": 5,
            "well_capacity_gpm": 1500,
            "total_water_gallons_est": 900000,
        },
        album=_create_album("avocado_grove", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 10 (guide #10): Organic Herbicide (HE) — 2026-03-10          #
    # NOP: supplier_name, purchase_date, purchase_invoice                  #
    # ------------------------------------------------------------------ #
    ChemicalEvent.objects.create(
        history=production,
        index=11,
        date=_dt(2026, 3, 10, 7),
        description=(
            "Targeted weed control between tree rows using Avenger AG (d-limonene). "
            "Applied with shielded boom sprayer to prevent drift onto avocado foliage. "
            "Targeting winter annual weeds that regrew after cover crop mowing. Organic "
            "alternative to glyphosate — contact herbicide only, no soil residual. "
            "8 gal concentrate diluted to 170 gal total spray volume (4 gal/acre). "
            "Second application may be needed in 3 weeks."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ChemicalEvent.HERBICIDE,
        chemical_subtype="organic_herbicide",
        name="Organic Herbicide — Between-Row Weed Control",
        commercial_name="Avenger AG (d-limonene 70%)",
        variety="Hass",
        block_id="Hillside Grove A",
        growth_stage="fruit_set",
        volume="8",
        volume_unit="gal",
        concentration="70",
        area="42.5",
        area_unit="acres",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="post_emergence",
        weather_conditions="calm_dry",
        target_pest_disease="Winter annual weeds (chickweed, filaree)",
        organic_approved="omri_listed",
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("6.00"),
        application_fuel_unit="gal",
        # NOP 7 CFR 205.103 mass-balance traceability
        supplier_name="Avenger Organics (Cutting Edge Formulations)",
        purchase_date=date(2026, 3, 1),
        purchase_invoice="INV-AO-2026-0231",
        extra_data={
            "active_ingredient": "d-limonene",
            "spray_equipment": "Shielded boom sprayer",
            "dilution_ratio": "8 gal concentrate in 170 gal total",
            "target_weeds": "Chickweed, filaree (winter annuals)",
        },
        album=_create_album("herbicide", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 11 (guide #11): Heat Wave (HT) — 2026-03-15                  #
    # ------------------------------------------------------------------ #
    WeatherEvent.objects.create(
        history=production,
        index=12,
        date=_dt(2026, 3, 15, 14),
        description=(
            "Santa Ana wind event brought extreme heat (40.5°C / 105°F peak on 3/15). "
            "Avocado trees show stress signs: leaf curl, some fruit drop on sun-exposed "
            "branches. Emergency irrigation triggered. Applied overhead microsprinkler misting "
            "for evaporative cooling on most exposed trees. Estimated 5-8% young fruit drop "
            "from heat stress. No structural damage to trees. Some sunburn on south-facing "
            "fruit — will affect cosmetic grade at harvest. Yield estimate revised from "
            f"{EARLY_ESTIMATE_LB:,} to {int(PRE_HARVEST_ESTIMATE_LB):,} lbs."
        ),
        created_by=user,
        performed_by="Maria Elena Gutierrez",
        type=WeatherEvent.HIGH_TEMPERATURE,
        observation=(
            "Peak temps 40.5C/105F on day 2. Emergency irrigation activated. "
            f"Estimated 5-8% fruit drop. Yield revised to ~{int(PRE_HARVEST_ESTIMATE_LB):,} lbs."
        ),
        extra_data={
            "event_name": "Santa Ana Heat Wave",
            "highest_temperature": "40.5",
            "start_date": "2026-03-14T08:00",
            "end_date": "2026-03-16T20:00",
            "fruit_drop_pct": "5-8",
            "yield_revision_lbs": int(PRE_HARVEST_ESTIMATE_LB),
        },
    )

    # ------------------------------------------------------------------ #
    # Event 12 (guide #12): Emergency Irrigation (IR) — 2026-03-15       #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=13,
        date=_dt(2026, 3, 15, 16),
        description=(
            "Emergency irrigation triggered by 105F heat wave. Applied ~0.45 inch through "
            "drip plus overhead micro-sprinklers on the most exposed blocks for evaporative "
            "cooling (frost/heat-protection use — not routine irrigation). Priority: prevent "
            "additional fruit drop. Soil moisture had dropped to 12% VWC (critical threshold "
            "15%). Outside the normal drip schedule. Run time ~12 hours at 1,500 GPM; total "
            "water use approximately 1.08 million gallons."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ProductionEvent.IRRIGATION,
        name="Emergency Heat-Wave Irrigation",
        variety="Hass",
        block_id="Hillside Grove A",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        fuel_type="electric",
        equipment_hours=Decimal("12.00"),
        water_source="well_groundwater",
        irrigation_method="drip",
        irrigation_depth=Decimal("0.45"),
        irrigation_depth_unit="inches",
        pump_depth_ft=Decimal("180.0"),
        electricity_source="grid",
        production_efficiency="high",
        extra_data={
            "trigger": "Heat wave 105F",
            "soil_moisture_vwc_pct_start": 12,
            "supplemental_microsprinklers": True,
            "well_capacity_gpm": 1500,
            "total_water_gallons_est": 1080000,
        },
        album=_create_album("avocado_grove", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 20 (guide #20): Contamination Incident (General) — 2026-03-16 #
    # NOP 7 CFR 205.201(b): contamination incident documentation          #
    # ------------------------------------------------------------------ #
    GeneralEvent.objects.create(
        history=production,
        index=14,
        date=_dt(2026, 3, 16, 14, 30),
        description=(
            "Wind shifted to west at ~14:15, observed mist from neighboring property "
            "(Johnson Citrus, conventional). Applied via airblast sprayer. Affected "
            "approximately 3.5 acres of east buffer zone (rows 1-12). No fruit in affected "
            "rows — these are young replants (2024). Leaf samples collected from 5 trees "
            "for lab analysis."
        ),
        created_by=user,
        performed_by="Maria Elena Gutierrez",
        name="Spray Drift Incident - East Buffer Zone",
        activity_type="emergency",
        activity_name="Contamination incident — spray drift from adjacent conventional farm",
        # NOP 7 CFR 205.201(b): contamination incident fields
        is_contamination_incident=True,
        contamination_source="spray_drift",
        contamination_affected_area=Decimal("3.5"),
        corrective_action_taken=(
            "Immediately stopped harvest in affected area. Notified PSOC inspector within "
            "24 hours. Collected leaf tissue samples for residue testing (results returned "
            "within tolerance 2026-03-24, before harvest). "
            "Documented wind direction and timing. Widened the east-boundary buffer from the "
            "standing 25 ft to 100 ft. Neighbor notified of organic certification boundary."
        ),
        corrective_action_date=date(2026, 3, 17),
        certifier_notified=True,
        certifier_notification_date=date(2026, 3, 16),
        observation=(
            "Spray drift from Johnson Citrus (conventional neighbor, east boundary). "
            "Affected rows 1-12 of east buffer zone (~3.5 acres). Young replant trees only "
            "(no mature fruit). Lab analysis ordered. PSOC notified same day."
        ),
        extra_data={
            "adjacent_farm": "Johnson Citrus",
            "wind_direction_at_incident": "West",
            "time_observed": "14:15",
            "leaf_samples_collected": 5,
            "buffer_zone_expanded_ft": 100,
        },
        album=_create_album("scouting", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 13 (guide #13): Organic Pesticide (PE) — 2026-03-20          #
    # NOP: supplier_name, purchase_date, purchase_invoice                  #
    # ------------------------------------------------------------------ #
    ChemicalEvent.objects.create(
        history=production,
        index=15,
        date=_dt(2026, 3, 20, 6, 30),
        description=(
            "Post-heat-wave thrips population surge (avg 8.2 thrips/leaf, action threshold "
            "5/leaf). Applied Entrust SC (Spinosad) at 6 oz/acre via airblast sprayer. "
            "Pre-dawn application to minimize impact on beneficials. Spinosad has 3-hour UV "
            "degradation — dawn application preserves pollinators. Will scout in 7 days to "
            "assess efficacy."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ChemicalEvent.PESTICIDE,
        chemical_subtype="biological_pesticide",
        name="Organic Pesticide — Thrips Post-Heat-Wave Response",
        commercial_name="Entrust SC (Spinosad 22.5%)",
        variety="Hass",
        block_id="Hillside Grove A",
        growth_stage="fruit_set",
        volume="15080",
        volume_unit="mL",
        concentration="22.5",
        area="85",
        area_unit="acres",
        way_of_application="ground_spray",
        application_method_structured="ground_spray",
        application_timing="fruit_development",
        weather_conditions="calm_dry",
        target_pest_disease="Avocado Thrips (Scirtothrips perseae)",
        organic_approved="omri_listed",
        rei_hours=Decimal("4.0"),
        phi_days=Decimal("7.0"),
        epa_registration_number="62719-621",
        applicator_name="Miguel Ramirez",
        applicator_certification="CA QAL-4287",
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("12.00"),
        application_fuel_unit="gal",
        # NOP 7 CFR 205.103 mass-balance traceability
        supplier_name="Corteva Agriscience (Dow AgroSciences)",
        purchase_date=date(2026, 3, 15),
        purchase_invoice="INV-CA-2026-0419",
        extra_data={
            "active_ingredient": "Spinosad",
            "application_rate_oz_acre": 6,
            "pre_dawn_application": True,
            "thrips_per_leaf_trigger": 8.2,
            "threshold": 5.0,
        },
        album=_create_album("pesticide", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 14 (guide #14): Compost Application (CO) — 2026-03-25        #
    # NOP: amendment_organic_approved, compost_peak_temp_f,               #
    #      compost_duration_days_at_temp, compost_turning_count            #
    # ------------------------------------------------------------------ #
    SoilManagementEvent.objects.create(
        history=production,
        index=16,
        date=_dt(2026, 3, 25, 8),
        description=(
            "Applied finished compost (12 months aged, on-farm produced from prunings, "
            "cover crop residue, and local horse stable manure). Application rate: 2 tons/acre "
            "around tree basins in 6-foot diameter rings. Compost analysis: C:N ratio 18:1, "
            "pH 7.1, no detectable E. coli or Salmonella (lab tested). This application "
            "expected to add ~0.1% organic matter to soil over the season."
        ),
        created_by=user,
        performed_by="Miguel Ramirez, compost crew (4)",
        type=SoilManagementEvent.COMPOSTING,
        name="Spring Compost Application",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        amendment_type="Finished compost (on-farm, pruning + cover crop residue)",
        amendment_amount="170",
        fuel_consumed=Decimal("25.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_hours=Decimal("16.00"),
        equipment_used="John Deere 5075E with compost spreader",
        # NOP 7 CFR 205.203(b): amendment organic approval
        amendment_organic_approved="omri_listed",
        # NOP 7 CFR 205.203(c)(2): compost temperature & process records
        compost_peak_temp_f=Decimal("158.0"),
        compost_duration_days_at_temp=21,
        compost_turning_count=7,
        extra_data={
            "compost_age_months": 12,
            "compost_source": "On-farm (prunings + cover crop + horse manure)",
            "cn_ratio": "18:1",
            "compost_ph": 7.1,
            "lab_tested": True,
            "application_method": "6-foot diameter rings around tree basins",
            "application_rate_tons_acre": 2,
        },
        album=_create_album("composting", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 15 (guide #15): PSOC Inspection (Business - CE) — 2026-03-28  #
    # ------------------------------------------------------------------ #
    BusinessEvent.objects.create(
        history=production,
        index=17,
        date=_dt(2026, 3, 28, 9),
        description=(
            "Annual USDA Organic inspection by PSOC inspector R. Alvarez. Full audit of: "
            "(1) Input records — all materials OMRI-listed, no prohibited substances found, "
            "(2) Field inspection — buffer zones maintained, no contamination risk, "
            "(3) Compost records — temperature logs and lab analysis reviewed, NOP 90-day "
            "rule compliance confirmed, (4) Pest management — IPM records reviewed, "
            "Entrust SC application compliant, (5) Harvest/handling — no commingling risk, "
            "(6) Recordkeeping — Trazo documentation praised as excellent. "
            "Result: PASSED. Certificate renewed through Dec 2027. "
            "Minor observation: improve signage at north property boundary."
        ),
        created_by=user,
        performed_by="R. Alvarez (PSOC Inspector)",
        type=BusinessEvent.CERTIFICATION,
        name="Annual USDA Organic Inspection (PSOC)",
        business_type="certification",
        certification_type="organic_usda",
        verification_status="verified",
        sustainability_practice="integrated_pest",
        verified_certifier_name="DEMO — Pacific Slope Organic Certifiers (sample data, not an accredited agent)",
        certificate_number="DEMO-ORG-0000",
        observation=(
            "All 6 inspection areas passed. Minor observation: improve north boundary "
            "signage — corrected within 24 hours. Certificate renewed through Dec 2027."
        ),
        extra_data={
            "audit_date": "2026-03-28",
            "inspector": "R. Alvarez (PSOC)",
            "result": "PASSED",
            "minor_observations": 1,
            "major_nonconformances": 0,
            "valid_until": "2027-12-31",
        },
    )

    # ------------------------------------------------------------------ #
    # Event 16 (guide #16): Fruit Thinning (TH) — 2026-03-30             #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=18,
        date=_dt(2026, 3, 30, 7),
        description=(
            "Hand thinning by 12-person crew. Removed approximately 15% of set fruit to "
            "improve size of remaining avocados. Targeting premium size (48-60 count per "
            "carton). Removed sun-damaged fruit from heat wave, undersized fruit, and "
            "clusters too dense for proper development. All removed fruit left on ground "
            f"as organic matter. Estimated {THINNED_LB:,} lbs of fruit removed. "
            f"Remaining crop load: approximately {int(PRE_HARVEST_ESTIMATE_LB):,} lbs estimated yield."
        ),
        created_by=user,
        performed_by="Harvest crew (12 workers)",
        type=ProductionEvent.THINNING,
        name="Spring Fruit Thinning — Premium Grade Selection",
        variety="Hass",
        block_id="Hillside Grove A",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        production_efficiency="high",
        growth_stage="fruit_set",
        extra_data={
            "crew_size": 12,
            "thinning_pct": 15,
            "fruit_removed_lbs": 1200,
            "remaining_yield_lbs_est": 11200,
            "target_count_per_carton": "48-60",
        },
        album=_create_album("avocado_harvest", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 17 (guide #17): Main Harvest (HA) — 2026-04-10               #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=19,
        date=_dt(2026, 4, 10, 6),
        description=(
            "Five-day hand harvest completed. 18-person crew using picking poles and bags. "
            "Fruit clipped with stems (industry standard for premium grade). Average fruit "
            "weight 8.2 oz (premium 48-count size). Dry matter content tested at 26.4% "
            "(minimum 21.5% for Hass). Fruit sorted field-side: Premium 72%, Grade A 20%, "
            "Grade B 8% (mostly sunburn cosmetic). All bins moved to packing shed within "
            "2 hours of harvest. Pre-cooling to 45F within 4 hours. "
            f"Total yield: {int(SEASON_YIELD_LB):,} lbs ({int(SEASON_YIELD_KG):,} kg)."
        ),
        created_by=user,
        performed_by="Harvest crew (18 workers), Maria Elena Gutierrez (QA)",
        type=ProductionEvent.HARVESTING,
        name="Main Hass Avocado Harvest 2026",
        variety="Hass",
        block_id="Hillside Grove A",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        yield_quantity=SEASON_YIELD_KG,
        yield_unit="kg",
        harvest_quality_grade="grade_a",
        fuel_consumed=Decimal("8.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_type="other",
        equipment_hours=Decimal("40.00"),
        production_efficiency="high",
        growth_stage="harvest_ready",
        storage_location="On-farm cooler, pre-cooled 45F",
        storage_temperature_f=Decimal("45.0"),
        observation=(
            "Premium grade achieved: 72% premium, 20% Grade A, 8% Grade B (cosmetic). "
            f"Dry matter 26.4%. Yield {int(SEASON_YIELD_KG):,} kg total."
        ),
        extra_data={
            "crew_size": 18,
            "harvest_days": 5,
            "avg_fruit_weight_oz": 8.2,
            "dry_matter_pct": 26.4,
            "min_dry_matter_pct": 21.5,
            "premium_pct": 72,
            "grade_a_pct": 20,
            "grade_b_pct": 8,
            "pre_cool_temp_f": 45,
            "pre_cool_time_hours": 4,
        },
        album=_create_album("avocado_harvest", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 18 (guide #18): Post-Harvest Packing (PH) — 2026-04-12      #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=20,
        date=_dt(2026, 4, 12, 5),
        description=(
            "Post-harvest handling at on-farm packing shed. Process: (1) Brush wash with "
            "chlorinated water (NOP-compliant, <200ppm), (2) Size sorting (automated optical "
            "grader), (3) Quality grading (manual inspection), (4) Pack into 25-lb cartons "
            "with Solana Verde branding + Trazo QR stickers, (5) Pre-cool to 40F in "
            "forced-air cooler, (6) Cold storage at 40F, 90% humidity. "
            f"Season total packed: {SEASON_CARTONS:,} cartons (25 lbs each), shipped over "
            f"{SEASON_LOADS} refrigerated loads. First load ready for POD pickup on 4/14: "
            f"{FIRST_LOAD_CARTONS:,} cartons. Lot: SVR-2026-HA-001."
        ),
        created_by=user,
        performed_by="Packing crew (6 workers), Maria Elena Gutierrez (QA)",
        type=ProductionEvent.POST_HARVEST_PROCESSING,
        name="Packing & Cold Storage for POD Shipment",
        variety="Hass",
        block_id="Hillside Grove A",
        area_covered=Decimal("0.00"),
        area_unit="ha",
        fuel_type="electric",
        fuel_consumed=Decimal("0.00"),
        fuel_unit="kWh",
        equipment_hours=Decimal("16.00"),
        production_efficiency="high",
        storage_location="On-farm packing shed cooler",
        storage_temperature_f=Decimal("40.0"),
        extra_data={
            "cartons_packed": SEASON_CARTONS,
            "carton_weight_lbs": 25,
            "lot_id": "SVR-2026-HA-001",
            "qr_stickers_applied": True,
            "sanitizer_chlorine_ppm": 200,
            "cooler_humidity_pct": 90,
        },
        album=_create_album("avocado_packed", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 19 (guide #19): Season Summary (General) — 2026-04-13        #
    # ------------------------------------------------------------------ #
    GeneralEvent.objects.create(
        history=production,
        index=22,
        date=_dt(2026, 4, 13, 10),
        description=(
            f"Production season summary for POD buyer package: Total yield {int(SEASON_YIELD_LB):,} lbs "
            f"({int(SEASON_YIELD_KG):,} kg) Hass avocados from 85-acre Hillside Grove A. Premium grade 72%, "
            "Grade A 20%, Grade B 8%. Organic certification DEMO-ORG-0000 renewed March 2026 "
            "(passed with no violations). Season challenges: March heat wave caused 5-8% fruit "
            "drop and cosmetic sunburn on exposed fruit. Pest management: biological control "
            "successful (green lacewings + Spinosad), no synthetic inputs used. Water: 3 "
            "irrigation events totaling approximately 7 inches applied through drip system. "
            "Soil health: OM increased to 4.2% (was 3.8% in 2024). Cover crop: crimson "
            "clover + vetch provided estimated 120 lbs N/acre. "
            "Lot SVR-2026-HA-001 ready for POD pickup April 14."
        ),
        created_by=user,
        performed_by="Maria Elena Gutierrez",
        name="2026 Season Summary — POD Buyer Package",
        activity_type="other",
        activity_name="Season documentation and buyer package preparation",
        duration="4",
        people_involved=3,
        observation=(
            "Successful organic season. Events documented across all 7 categories; "
            "records compiled into the POD buyer package and organic documentation export."
        ),
    )

    # ------------------------------------------------------------------ #
    # Seed/Planting event (PL) — replant event on production              #
    # Represents the 2022 replant of east buffer zone young trees.        #
    # NOP: seed_supplier_name, seed_purchase_date, seed_purchase_invoice, #
    #      seed_certification_status, seed_search_attempts (NOP 5029)     #
    # ------------------------------------------------------------------ #
    ProductionEvent.objects.create(
        history=production,
        index=23,
        date=_dt(2026, 1, 8, 7),
        # 2026-08-15: rewritten. The old text named the nursery inline (which the consumer
        # payload strips from `seed_supplier_name` and therefore has to strip here too — see
        # privacy.redact_own_vendor_names) and asserted "All 3 required supplier searches
        # documented per NOP 5029" on a shopper-visible surface. 205.204 sets no supplier
        # count, and demo data that states a requirement the regulation does not make is how a
        # fabricated claim ends up quoted in a screenshot.
        description=(
            "Replanted 28 Hass avocado trees in the east buffer zone (rows 1-12) after "
            "root-rot losses. Nursery stock and its organic certificate are on file; supplier "
            "contacts are recorded on this event."
        ),
        created_by=user,
        performed_by="Maria Elena Gutierrez",
        type=ProductionEvent.PLANTING,
        name="Replant — East Buffer Zone Young Trees",
        variety="Hass",
        block_id="Hillside Grove A — East Buffer Zone (rows 1-12)",
        area_covered=Decimal("1.42"),
        area_unit="ha",
        production_efficiency="normal",
        growth_stage="dormant",
        seeds_source="commercial",
        seed_certification_status="certified_organic",
        seed_supplier_name="Saticoy Grove Nursery, Saticoy CA",
        seed_purchase_date=date(2025, 11, 20),
        seed_purchase_invoice="BN-2025-11-4871",
        seed_lot_number="BN-HASS-2025-L047",
        # NOP 5029: 3 supplier search attempts (certified_organic so not strictly required,
        # included as best practice / belt-and-suspenders documentation)
        seed_search_attempts=[
            {
                "supplier_name": "Saticoy Grove Nursery, Saticoy CA",
                "date_contacted": "2025-11-10",
                "result": "Available — certified organic Hass rootstock in stock",
                "notes": "Primary supplier. Ordered 28 trees at $45/tree.",
            },
            {
                "supplier_name": "Durling Nursery, Fallbrook CA",
                "date_contacted": "2025-11-08",
                "result": "Available — certified organic Hass in limited quantity",
                "notes": "Local alternative contacted. Saticoy Grove selected for quality consistency.",
            },
            {
                "supplier_name": "OC Nursery, San Marcos CA",
                "date_contacted": "2025-11-08",
                "result": "Out of stock — certified organic Hass not available until spring 2026",
                "notes": "Third supplier per NOP 5029. Not available for fall planting timeline.",
            },
        ],
        extra_data={
            "trees_replanted": 28,
            "replant_reason": "Root rot loss in east buffer zone (rows 1-12)",
            "rootstock": "Duke 7 (phytophthora-resistant)",
            "tree_size": "5-gallon container, 2-year nursery stock",
        },
        album=_create_album("planting", demo_images),
    )

    # ------------------------------------------------------------------ #
    # Event 24: Sale & Delivery to POD (Business - CM) — 2026-04-15      #
    # § 205.501(a)(21) traceability + § 205.103(b)(2) "organic on invoice"  #
    # + FSMA 204 Critical Tracking Event (shipping). Documents the full  #
    # downstream chain so an inspector can trace lot SVR-2026-HA-001     #
    # from this farm to POD's Portland distribution hub.                  #
    # ------------------------------------------------------------------ #
    BusinessEvent.objects.create(
        history=production,
        index=24,
        # 06:30 PDT (UTC-7) = 13:30 UTC. Narrative time references are PT.
        date=_dt(2026, 4, 15, 13, 30),
        description=(
            f"Refrigerated shipment of lot SVR-2026-HA-001 to {BUYER_NAME} — load 1 of "
            f"{SEASON_LOADS} for the season. "
            f"{FIRST_LOAD_CARTONS:,} cartons ({FIRST_LOAD_KG:,} kg, {FIRST_LOAD_LB:,} lbs net) "
            "loaded at 06:00 PT into POD-contracted "
            "refrigerated trailer (Cool-Chain Logistics #CCL-2814) at 38°F set point. "
            "Bill of Lading BOL-POD-2026-04-15-007 signed by driver Tomás Reyes and Maria "
            "Elena Gutierrez. Pre-loading: trailer interior swept and inspected — no "
            f"non-organic residue. All {FIRST_LOAD_CARTONS:,} cartons bear lot SVR-2026-HA-001 sticker + Trazo "
            "QR code. PO #POD-PO-2026-0412 from POD Procurement. Invoice #SVR-INV-2026-041 "
            "marks each line item ORGANIC per 7 CFR 205.103(b)(2) audit-trail documentation. Departed Fallbrook 06:30 PT, "
            "ETA POD Portland Distribution Hub 2026-04-16 18:00 PT (1,030 mi, ~26 hrs "
            "transit, fixed cold-chain). § 205.501(a)(21) downstream attestation: POD has "
            "filed signed receipt of organic certification copy DEMO-ORG-0000 on file at "
            "Solana Verde."
        ),
        created_by=user,
        performed_by="Maria Elena Gutierrez",
        type=BusinessEvent.COMPLIANCE,
        name="Shipment to POD — Lot SVR-2026-HA-001",
        business_type="compliance",
        certification_type="organic_usda",
        verification_status="verified",
        verified_certifier_name="DEMO — Pacific Slope Organic Certifiers (sample data, not an accredited agent)",
        certificate_number="DEMO-ORG-0000",
        observation=(
            "Sale and delivery record per § 205.501(a)(21) and § 205.103(b)(2). "
            f"FSMA 204 Critical Tracking Event (shipping) populated. All {FIRST_LOAD_CARTONS:,} cartons "
            "labelled 'Organic' with farm lot ID, traceable end-to-end."
        ),
        extra_data={
            "buyer_name": BUYER_NAME,
            "buyer_address": "1800 Prairie Rd, Eugene, OR 97402",
            "destination": "POD Distribution Hub, 5005 NE Portland Hwy, Portland, OR 97218",
            "lot_id": "SVR-2026-HA-001",
            "cartons_shipped": FIRST_LOAD_CARTONS,
            "net_weight_kg": FIRST_LOAD_KG,
            "net_weight_lbs": FIRST_LOAD_LB,
            "load_sequence": "1 of %d" % SEASON_LOADS,
            "bill_of_lading": "BOL-POD-2026-04-15-007",
            "purchase_order": "POD-PO-2026-0412",
            "invoice_number": "SVR-INV-2026-041",
            "carrier": "Cool-Chain Logistics",
            "trailer_number": "CCL-2814",
            "trailer_set_point_f": 38,
            "departure_time": "2026-04-15T06:30:00-07:00",
            "estimated_arrival": "2026-04-16T18:00:00-07:00",
            "transit_distance_miles": 1030,
            "organic_on_invoice": True,
            "buyer_organic_cert_on_file": True,
            "fsma_204_cte": "shipping",
            "downstream_attestation_signed": True,
        },
    )

    return 24
