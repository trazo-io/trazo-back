"""
Solana Verde Organic Ranch — base infrastructure helper.

Creates:
  company, establishment, parcel, product, crop_type,
  finished_production (2026-01-15 -> 2026-04-14),
  current_production (2026-09-01 -> present).

All literal values sourced from:
  documentation/testing/E2E_ORGANIC_FARM_TESTING_GUIDE.md
"""

from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from carbon.models import CropType
from certifications.models import Certification
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, ParcelCropHistory, Product
from subscriptions.models import Plan, Subscription
from users.models import User, WorksIn

COMPANY_NAME = "Solana Verde Farms LLC"
ESTABLISHMENT_NAME = "Solana Verde Organic Ranch"


def _dt(year, month, day, hour=8):
    return datetime(year, month, day, hour, 0, tzinfo=dt_tz.utc)


def create_solana_verde_base(user):
    """
    Create company, establishment, parcel, product, crop_type,
    finished and current productions for Solana Verde.

    Returns:
        (company, establishment, parcel, product, crop_type,
         production_finished, production_current)
    """
    # ------------------------------------------------------------------ #
    # Company                                                              #
    # ------------------------------------------------------------------ #
    company = Company.objects.create(
        name=COMPANY_NAME,
        tradename="Solana Verde Organic Ranch",
        address="2847 Orchard Valley Road",
        city="Fallbrook",
        state="California",
        country="United States",
        zip_code="92028",
        fiscal_id="93-7654321",
        description=(
            "Family-owned certified organic avocado ranch in Fallbrook, California, "
            "operating since 2009. Producing premium Hass avocados for INFRA retailers "
            "via Organically Grown Company distribution. 285 acres total, USDA Organic "
            "certified through CCOF, Bee Better Certified via Xerces Society."
        ),
        contact_email="info@solanaverde.farm",
        contact_phone="+1-760-555-0142",
        employee_count=57,
        industry="Specialty Agriculture",
        is_active=True,
        legal_structure="LLC",
        primary_commodities="Hass Avocado",
        sustainability_commitment="USDA Organic, Bee Better Certified, regenerative soil practices",
        certifications="USDA Organic (CCOF), Bee Better Certified",
        blockchain_subscription_status=False,
    )

    WorksIn.objects.create(
        user=user,
        company=company,
        role=WorksIn.COMPANY_ADMIN,
    )

    # Subscription — corporate plan matches the demo's needs
    try:
        plan = Plan.objects.get(slug="corporate-monthly")
        import django.utils.timezone as dj_tz

        now = dj_tz.now()
        Subscription.objects.create(
            company=company,
            plan=plan,
            status="active",
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
    except Plan.DoesNotExist:
        pass  # Not fatal — command output will warn if needed

    # ------------------------------------------------------------------ #
    # Establishment — all NOP OFPP/split-op fields set                    #
    # ------------------------------------------------------------------ #
    establishment = Establishment.objects.create(
        name=ESTABLISHMENT_NAME,
        address="2847 Orchard Valley Road",
        city="Fallbrook",
        state="California",
        country="United States",
        zip_code="92028",
        company=company,
        description=(
            "Family-owned organic avocado ranch in Fallbrook, California since 2009. "
            "We grow premium Hass avocados using regenerative organic practices, drip "
            "irrigation, and integrated pest management to protect our coastal hillside "
            "ecosystem. USDA Organic certified through CCOF. Our soil health program has "
            "increased organic matter from 1.8% to 4.2% over 15 years. We supply premium "
            "organic retailers through Organically Grown Company (OGC)."
        ),
        latitude=33.3764,
        longitude=-117.2510,
        contact_person="Maria Elena Gutierrez",
        contact_phone="+1-760-555-0143",
        is_active=True,
        crops_grown=["Hass Avocados", "Cover Crops", "Companion Herbs"],
        sustainability_practices=[
            "USDA Organic Certified",
            "Drip irrigation (95% efficiency)",
            "Cover cropping (winter legumes)",
            "Composting (on-farm)",
            "Beneficial insect habitat",
            "No-till between rows",
            "Integrated Pest Management",
        ],
        employee_count=22,
        total_acreage=285.0,
        year_established=2009,
        establishment_type="orchard",
        # NOP: farming_method must be "organic"
        farming_method="organic",
        water_sources=["Well water (180ft)", "Rainwater collection"],
        climate_zone="Mediterranean (Csb)",
        soil_types=["Clay Loam", "Sandy Loam"],
        conservation_practices=[
            "Cover Crops",
            "Hedgerows",
            "Pollinator Strips",
            "No-Till Between Rows",
        ],
        irrigation_methods=["Drip irrigation", "Soil moisture sensors"],
        # NOP: Organic Fraud Prevention Plan (7 CFR 205.201(a)(3))
        fraud_prevention_plan_date=date(2026, 3, 19),
        ofpp_responsible_person="Maria Elena Gutierrez",
        fraud_prevention_plan_uploaded=True,
        # NOP: Split Operation (7 CFR 205.201(a)(5))
        has_split_operation=False,
        split_operation_plan="",
    )

    # ------------------------------------------------------------------ #
    # Certifications                                                       #
    # ------------------------------------------------------------------ #
    Certification.objects.create(
        establishment=establishment,
        certification_type="usda_organic",
        certification_number="CCOF-2012-4287",
        certifier_name="CCOF (California Certified Organic Farmers)",
        effective_date=date(2025, 1, 1),
        expiry_date=date(2026, 12, 31),
        certification_scope="Crops - All",
        certified_items=["Hass Avocado"],
        verification_status="verified",
    )
    Certification.objects.create(
        establishment=establishment,
        certification_type="other",
        certification_number="BBV-2024-0891",
        certifier_name="Xerces Society",
        effective_date=date(2024, 6, 1),
        expiry_date=date(2027, 5, 31),
        certification_scope="Pollinator Conservation",
        certified_items=["Hass Avocado"],
        verification_status="self_reported",
    )

    # ------------------------------------------------------------------ #
    # Product & CropType                                                   #
    # ------------------------------------------------------------------ #
    product, _ = Product.objects.get_or_create(
        name="Avocado",
        defaults={"description": "Hass Avocado"},
    )

    crop_type, _ = CropType.objects.get_or_create(
        slug="avocados",
        defaults={
            "name": "Avocados",
            "category": "tree_fruit",
            "description": "Premium Hass avocado production",
            "typical_farm_size": "10-50 hectares",
            "growing_season": "12 months (evergreen)",
            "harvest_season": "February - September",
            "emissions_per_hectare": 3500.0,
            "industry_average": 4200.0,
            "best_practice": 2800.0,
            "carbon_credit_potential": 1.5,
            "typical_cost_per_hectare": 18000.0,
            "fertilizer_cost_per_hectare": 3200.0,
            "fuel_cost_per_hectare": 1800.0,
            "irrigation_cost_per_hectare": 2500.0,
            "labor_cost_per_hectare": 8000.0,
            "organic_premium": "25-40%",
            "sustainable_premium": "10-20%",
            "local_premium": "5-15%",
            "sustainability_opportunities": [
                "Drip irrigation efficiency",
                "Cover cropping for N-fixation",
                "Biological pest control",
                "On-farm composting",
            ],
            "usda_factors_used": True,
            "data_source": "USDA ARS, UC Davis, CAC",
            # tree_fruit -> has_soil_contact=False (90-day default);
            # E2E guide uses 120 days because avocado fruit contacts ground
            # during ground-collection harvest. We override to True so the
            # manure validator enforces 120 days on this crop type.
            "has_soil_contact": True,
        },
    )

    # ------------------------------------------------------------------ #
    # Parcel — Hillside Grove A (85 acres = 34.40 ha)                     #
    # ------------------------------------------------------------------ #
    parcel = Parcel.objects.create(
        name="Hillside Grove A",
        description=(
            "Our premier south-facing hillside grove, established in 2009. "
            "Hillside Grove A produces our finest Hass avocados thanks to excellent "
            "drainage, coastal fog protection, and rich clay-loam soil. This parcel "
            "features a complete drip irrigation system fed by our 180-foot well, with "
            "soil moisture sensors monitoring every zone. Between the avocado rows, we "
            "grow crimson clover and hairy vetch cover crops to fix nitrogen naturally "
            "and support beneficial insects."
        ),
        establishment=establishment,
        product=product,
        area=34.40,
        certified=True,
        certification_type="USDA Organic (CCOF)",
        soil_type="Clay Loam",
        contact_person="Maria Elena Gutierrez",
        address="Hillside Grove A — south-facing slope",
        agricultural_details={
            "primary_crop": "Hass Avocado",
            "planting_density": "4,250 trees total",
            "tree_spacing": "25ft x 25ft",
            "tree_age": "15-17 years (established 2009)",
            "irrigation_type": "Drip irrigation (95% efficiency)",
            "well_depth_ft": 180,
            "soil_ph": "6.5",
            "soil_organic_matter": "4.2%",
            "sustainability_practices": (
                "Drip irrigation, cover cropping, on-farm composting, "
                "beneficial insect releases, IPM, no-till between rows"
            ),
            "consumer_story": (
                "Every avocado from this grove is grown with care for the land. "
                "Our 15-year soil health program has increased organic matter from "
                "1.8% to 4.2%. We maintain native hedgerows and pollinator strips "
                "to support the ecosystem."
            ),
        },
        carbon_calculation_enabled=True,
    )

    # ------------------------------------------------------------------ #
    # ParcelCropHistory — 3 years per 7 CFR 205.202                       #
    # ------------------------------------------------------------------ #
    ParcelCropHistory.objects.create(
        parcel=parcel,
        year=2023,
        crop_grown="Hass Avocados",
        production_method="organic",
        substances_applied=("Fish emulsion 2-3-1, OMRI copper fungicide, beneficial insects"),
        notes=(
            "Transition year 3 (final). No prohibited substances. "
            "CCOF inspection passed. Preparing for first certified organic season."
        ),
    )
    ParcelCropHistory.objects.create(
        parcel=parcel,
        year=2024,
        crop_grown="Hass Avocados",
        production_method="organic",
        substances_applied=("Neptune's Harvest 2-3-1, Bacillus thuringiensis (Bt), compost 10 tons/acre"),
        notes=(
            "First full certified organic year. CCOF inspection passed April 2024. "
            "Soil OM% at 3.8%. Cover crop N-fixation estimated 110 lbs N/acre."
        ),
    )
    ParcelCropHistory.objects.create(
        parcel=parcel,
        year=2025,
        crop_grown="Hass Avocados",
        production_method="organic",
        substances_applied=(
            "Neptune's Harvest 2-3-1, copper hydroxide, neem oil, " "winter cover crop (crimson clover)"
        ),
        notes=(
            "Full organic season. Soil OM% increased to 4.0%. "
            "Beneficial insect populations established. IPM program fully operational."
        ),
    )

    # ------------------------------------------------------------------ #
    # Finished production: 2026-01-15 -> 2026-04-14                       #
    # ------------------------------------------------------------------ #
    finish_dt = _dt(2026, 4, 14, 12)
    retention_until = finish_dt.date() + timedelta(days=5 * 365)

    production_finished = History(
        name="Hass Avocado Hillside Grove A 2026",
        type=History.ORCHARD,
        start_date=_dt(2026, 1, 15),
        expected_harvest=_dt(2026, 4, 1),
        finish_date=finish_dt,
        published=True,
        description=(
            "Complete 2026 organic Hass avocado production for Hillside Grove A. "
            "22 agricultural events documented covering soil management, irrigation, "
            "pest control, organic inputs, harvest, and post-harvest handling. "
            "USDA Organic certified through CCOF. Lot SVR-2026-HA-001."
        ),
        production_amount=5080,
        production_unit="kg",
        quality_grade="grade_a",
        harvest_method="manual",
        production_method="organic",
        lot_id="SVR-2026-HA-001",
        product=product,
        parcel=parcel,
        is_outdoor=True,
        age_of_plants="15-17 years",
        number_of_plants="4,250",
        soil_ph="6.5",
        operator=user,
        crop_type=crop_type,
        earning=0,
        # NOP post-finish sales/traceability fields (7 CFR 205.103)
        sold_to="Organically Grown Company (OGC)",
        sale_date=date(2026, 4, 15),
        quantity_sold=Decimal("5080"),
        quantity_sold_unit="kg",
        organic_on_invoice=True,
        transport_method="Refrigerated truck",
        destination="OGC Distribution Hub, Portland, OR",
        # NOP retention (7 CFR 205.103(b)(4))
        retention_until=retention_until,
    )
    production_finished.save()

    # ------------------------------------------------------------------ #
    # Current / in-progress production: 2026-2027 season                  #
    # ------------------------------------------------------------------ #
    production_current = History(
        name="Hass Avocado Hillside Grove A 2026-2027",
        type=History.ORCHARD,
        start_date=_dt(2026, 9, 1),
        published=False,
        description=(
            "In-progress 2026-2027 organic Hass avocado season. "
            "Early-stage management including soil prep, cover crop establishment, "
            "and baseline pest scouting."
        ),
        production_amount=0,
        production_method="organic",
        product=product,
        parcel=parcel,
        is_outdoor=True,
        age_of_plants="16-18 years",
        number_of_plants="4,250",
        soil_ph="6.5",
        operator=user,
        crop_type=crop_type,
        earning=0,
    )
    production_current.save()

    # Wire parcel.current_history to the in-progress season
    parcel.current_history = production_current
    parcel.save()

    return (
        company,
        establishment,
        parcel,
        product,
        crop_type,
        production_finished,
        production_current,
    )
