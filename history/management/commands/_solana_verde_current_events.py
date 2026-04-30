"""
Solana Verde Organic Ranch — current-season events (2026-2027).

Seeds ~6 early-stage events on the in-progress production starting 2026-09-01.
Purpose: show an active dashboard. This is NOT the NOP-audited fixture
(the finished 2026 season handles that).
"""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from common.models import Gallery, GalleryImage
from history.models import ChemicalEvent, GeneralEvent, PestManagementEvent, ProductionEvent, SoilManagementEvent


def _dt(year, month, day, hour=8):
    return datetime(year, month, day, hour, 0, tzinfo=dt_tz.utc)


def _create_album(image_key, demo_images=None):
    """Reuse shared demo_images dict from create_demo_user."""
    urls = (demo_images or {}).get(image_key, [])
    if not urls:
        return None
    gallery = Gallery.objects.create()
    for url in urls:
        GalleryImage.objects.create(gallery=gallery, image_url=url)
    return gallery


def create_current_events(production, user, demo_images=None):
    """
    Seed 6 early-season events on the 2026-2027 in-progress production.

    Returns:
        int: event count created.
    """
    # 0: Pre-season soil test
    SoilManagementEvent.objects.create(
        history=production,
        index=0,
        date=_dt(2026, 9, 8, 9),
        description=(
            "Pre-season soil test for 2026-2027 season baseline. "
            "Lab: A&L Western Laboratories. pH 6.6, OM 4.4%, "
            "adequate NPK, zinc trending up from 2024 baseline."
        ),
        created_by=user,
        performed_by="A&L Western Laboratories",
        type=SoilManagementEvent.SOIL_TEST,
        name="Pre-Season Soil Analysis",
        soil_ph=Decimal("6.60"),
        organic_matter_percentage=Decimal("4.40"),
        soil_texture="clay_loam",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        test_results={
            "ph": 6.6,
            "organic_matter_pct": 4.4,
            "nitrogen_ppm": 48,
            "phosphorus_ppm": 38,
            "potassium_ppm": 295,
            "zinc_ppm": 2.4,
            "lab": "A&L Western Laboratories",
        },
        working_depth=Decimal("30.00"),
        depth_unit="cm",
        extra_data={"samples_collected": 24},
        album=_create_album("soil_test", demo_images),
    )

    # 1: Cover crop planting (fall)
    SoilManagementEvent.objects.create(
        history=production,
        index=1,
        date=_dt(2026, 9, 22, 7),
        description=(
            "Fall cover crop planting: crimson clover + hairy vetch mix "
            "between avocado rows. Seed rate 28 kg/ha for N-fixation "
            "and erosion control through winter rains."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=SoilManagementEvent.COVER_CROP,
        name="Fall Cover Crop Planting",
        area_covered=Decimal("17.20"),
        area_unit="ha",
        soil_moisture="moderate",
        amendment_type="Crimson clover + hairy vetch seed mix",
        amendment_amount="480",
        amendment_organic_approved="omri_listed",
        fuel_consumed=Decimal("10.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_hours=Decimal("6.00"),
        equipment_used="John Deere 5075E with seed drill",
        extra_data={
            "seed_mix": {"crimson_clover_pct": 65, "hairy_vetch_pct": 35},
            "expected_n_fixation_lbs_acre": 120,
            "seed_supplier": "Kamprath Seed (OMRI-listed organic seed)",
        },
        album=_create_album("cover_crop", demo_images),
    )

    # 2: Organic fertilizer (OMRI-listed, with NOP supplier chain)
    ChemicalEvent.objects.create(
        history=production,
        index=2,
        date=_dt(2026, 10, 5, 8),
        description=(
            "Fall organic fertilizer application: Neptune's Harvest Fish "
            "& Seaweed (2-3-1) via fertigation. Supports tree recovery "
            "post-harvest and winter bloom initiation."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ChemicalEvent.FERTILIZER,
        chemical_subtype="organic_fertilizer",
        name="Fall Fertigation - Neptune's Harvest",
        commercial_name="Neptune's Harvest Fish & Seaweed (2-3-1)",
        concentration="2-3-1",
        volume="220",
        area="34.40",
        way_of_application="fertigation",
        application_method_structured="fertigation",
        application_timing="dormant",
        weather_conditions="calm_dry",
        organic_approved="omri_listed",
        supplier_name="Hydra-Gardens Inc. (Neptune's Harvest)",
        purchase_date=date(2026, 9, 28),
        purchase_invoice="INV-HG-2026-0512",
        extra_data={
            "rate_gal_acre": 2.59,
            "delivery_method": "drip injection",
            "volume_unit": "gal",
        },
        album=_create_album("fertilizer", demo_images),
    )

    # 3: First irrigation of new season
    ProductionEvent.objects.create(
        history=production,
        index=3,
        date=_dt(2026, 10, 12, 6),
        description=(
            "First irrigation cycle of 2026-2027 season. Soil moisture "
            "sensors triggered at 17% VWC. 1.25 inches applied via drip "
            "emitters. Well pump at 180 ft depth."
        ),
        created_by=user,
        performed_by="Miguel Ramirez",
        type=ProductionEvent.IRRIGATION,
        name="Season Opener Irrigation",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        water_source="well_groundwater",
        irrigation_method="drip",
        irrigation_depth=Decimal("1.25"),
        irrigation_depth_unit="inches",
        fuel_type="electric",
        equipment_hours=Decimal("7.00"),
        production_efficiency="high",
        observation="Sensors confirmed uniform distribution. Run time 7 hours.",
        extra_data={
            "trigger_soil_moisture_pct": 17,
            "pump_depth_ft": 180,
        },
    )

    # 4: Early pest scouting with full NOP ID trace
    PestManagementEvent.objects.create(
        history=production,
        index=4,
        date=_dt(2026, 10, 20, 8),
        description=(
            "Routine bi-weekly IPM scout on 20 sample trees. No pest "
            "pressure detected. Beneficial populations intact."
        ),
        created_by=user,
        performed_by="Carlos Mendez",
        type=PestManagementEvent.SCOUTING,
        pest_species="No pests above threshold",
        pest_pressure_level="Low",
        action_threshold_met=False,
        identified_by="crop_consultant",
        identification_method="Visual inspection using 10x hand lens, UC Davis IPM field guide",
        threshold_rationale=(
            "Zero target pests found on 20 sample trees (randomized grid). "
            "Green lacewing and minute pirate bug populations healthy. "
            "Below 5/leaf economic threshold for thrips per UC Davis IPM."
        ),
        beneficial_insects_used="yes",
        area_covered=Decimal("34.40"),
        area_unit="ha",
        ipm_strategy=(
            "Bi-weekly visual scout, 20 randomized trees, 10x hand lens. "
            "Sticky traps supplement. Beneficial release planned if thresholds approached."
        ),
        extra_data={
            "trees_sampled": 20,
            "thrips_per_leaf_avg": 0.0,
        },
        album=_create_album("scouting", demo_images),
    )

    # 5: Season planning documentation note
    GeneralEvent.objects.create(
        history=production,
        index=5,
        date=_dt(2026, 10, 25, 10),
        description=("Season planning documentation for 2026-2027 Hass Avocado cycle."),
        created_by=user,
        performed_by="Maria Elena Gutierrez",
        name="2026-2027 Season Plan",
        activity_type="other",
        observation=(
            "2026-2027 season plan finalized. Targets: 11,500 lbs yield "
            "(up from 11,200 post-heat-wave 2026). Inputs: Neptune's Harvest "
            "fertigation schedule (5 applications), Kocide 3000 preventive "
            "fungicide (3 applications), Entrust SC on-demand for thrips. "
            "Beneficial release scheduled for February 2027. Water budget: "
            "40 inches via drip with CIMIS ET0 scheduling. CCOF annual "
            "inspection scheduled for March 2027."
        ),
    )

    return 6
