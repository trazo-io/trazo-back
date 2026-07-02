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
from certifications.models import (
    OSP_SECTION_KEYS,
    Certification,
    NationalListSubstance,
    OMRIProduct,
    OrganicSystemPlan,
    WSDAMaterial,
)
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
    ccof_cert = Certification.objects.create(
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
    # Organic System Plan (7 CFR 205.201) — active v1, linked to CCOF      #
    # cert. Six required narrative sections fully populated with real     #
    # operation details (no "farmer to complete" placeholders) so the     #
    # audit-export PDF renders a submission-ready dossier.                #
    # ------------------------------------------------------------------ #
    _seed_solana_verde_osp(establishment, ccof_cert, user)

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


def _seed_solana_verde_osp(establishment, ccof_cert, user):
    """
    Create an active Organic System Plan v1 for Solana Verde with fully-populated
    narratives for the six required sections per 7 CFR 205.201(a)(1)-(6).

    Linked to the active CCOF certification. Approved-input M2M tables are
    populated when seed_omri_minimal / seed_wsda_materials / seed_national_list
    have been run beforehand; otherwise the M2M attaches a partial set silently.
    """
    # OSP submission/approval timeline reflects a real CCOF cycle: drafted +
    # submitted in the prior fall, certifier-approved in mid-December, and made
    # effective on the new calendar year. Last-updated stamp on each section
    # uses the effective date so the audit PDF shows a consistent OSP age,
    # independent of when the seed command is actually run.
    submitted_at_dt = datetime(2025, 11, 15, 17, 0, tzinfo=dt_tz.utc)
    approved_at_dt = datetime(2025, 12, 20, 17, 0, tzinfo=dt_tz.utc)
    effective_date_value = date(2026, 1, 1)
    last_updated_iso = effective_date_value.isoformat()

    practices_procedures = (
        "Operation: Solana Verde Organic Ranch — 285-acre orchard in Fallbrook, "
        "San Diego County, California (climate zone Csb, Mediterranean).\n\n"
        "Crops grown: Hass avocados (primary, 4,250 trees on 34.40 ha), "
        "winter cover crops (crimson clover + hairy vetch interplanted between "
        "tree rows), pollinator-strip companion herbs (yarrow, phacelia).\n\n"
        "Tree management: 25ft x 25ft spacing, 15-17 year established trees, "
        "Duke 7 phytophthora-resistant rootstock used for replants. Annual "
        "pruning February-March (skirting + dead-wood removal) — prunings "
        "chipped and returned to row middles as mulch.\n\n"
        "Irrigation: drip system (95% efficiency) fed by on-site 180-foot well, "
        "with soil moisture sensors monitoring every zone. Irrigation events "
        "logged per-event in Trazo with duration and volume; no flood or "
        "overhead application.\n\n"
        "Soil management (§ 205.203): on-farm composting (prunings + cover crop "
        "+ aged horse manure, C:N 18:1), 2 tons/acre application annually in "
        "6-foot rings around tree basins. Cover-crop residue incorporated as "
        "green manure each spring. Soil organic matter has risen from 1.8% (2009) "
        "to 4.2% (2025) per UC ANR-protocol soil tests.\n\n"
        "Pest management (§ 205.206): IPM-first program — weekly scouting (June-"
        "October), beneficial-insect releases (lacewings, lady beetles), "
        "monitoring traps for persea mite and avocado thrips, threshold-based "
        "intervention only. Approved organic inputs (copper hydroxide, DiPel "
        "DF, Entrust SC) listed and classified in section (a)(2) — applied at "
        "or below label rate when pest pressure exceeds documented thresholds.\n\n"
        "Conservation practices: hedgerows around field perimeters, pollinator "
        "strips, no-till between tree rows. CCOF inspection records, Bee Better "
        "habitat plan, and CDFA water-use reports retained per § 205.103."
    )

    inputs_list = (
        "All inputs are logged per-event in Trazo (chemical, soil, and pest "
        "management events), classified against OMRI / WSDA / CDFA-OIM / 7 CFR "
        "205.601 National List at entry time. The Trazo Audit Export "
        "'OMRI / National List Verification' section enumerates the full "
        "year-to-date list with classification, supplier, purchase date, and "
        "invoice number for each application.\n\n"
        "Inputs currently in use on Hillside Grove A (each cross-references the "
        "approved-materials catalog attached to this OSP):\n"
        "  - Neptune's Harvest Organic Fish and Seaweed Fertilizer 2-3-1 "
        "(OMRI + WSDA listed) — foliar feed, 1 gal/acre, sourced from "
        "Cal-West Ag Supply, Fallbrook CA.\n"
        "  - Copper hydroxide (7 CFR 205.601(i)(1) National List allowed) — "
        "fungicide for anthracnose, label rate 1.5 lb/acre, sourced from "
        "Wilbur-Ellis Vista CA. Used in compliance with § 205.601(i)(1) "
        "tolerance and resistance-management restrictions.\n"
        "  - DiPel DF Bacillus thuringiensis (OMRI + WSDA listed; § 205.601(e) "
        "Microbial products) — caterpillar control, 0.5 lb/acre, sourced from "
        "Wilbur-Ellis Vista CA.\n"
        "  - Entrust SC Naturalyte Insect Control / Spinosad (OMRI + WSDA "
        "listed; § 205.601(e) Spinosad) — thrips control, 4 fl oz/acre, "
        "sourced from Cal-West Ag Supply.\n"
        "  - On-farm compost (prunings + cover crop + aged horse manure) — no "
        "purchase, internal mass-balance tracked per 7 CFR 205.203(c).\n"
        "  - Brokaw Nursery (Saticoy CA) certified-organic Hass nursery stock "
        "on Duke 7 rootstock — used for replants, NOP 5029 supplier-search log "
        "documented per planting event.\n\n"
        "No prohibited substances per 7 CFR 205.602/.604 are stocked on premises."
    )

    monitoring_plan = (
        "Monitoring practices (§ 205.201(a)(3)):\n"
        "  - Weekly pest-scouting Jun-Oct: random transects, persea mite + "
        "thrips trap counts, beneficial-population observation, threshold "
        "rationale logged on each Pest Management event.\n"
        "  - Daily soil-moisture readout from in-field sensors during irrigation "
        "season; irrigation events triggered only when sensor falls below "
        "set-point.\n"
        "  - Monthly compost-pile temperature log during active turning phase "
        "(target 131-170°F per § 205.203(c)(2)); turning count, peak temp, and "
        "duration recorded on each compost event.\n"
        "  - Annual soil test (UC ANR protocol) — pH, organic matter, "
        "macronutrients, EC. Results filed under the establishment's soil-test "
        "history.\n"
        "  - Annual CCOF inspection (most recent 2026-03-28 by Sarah Chen, "
        "PASSED). Continuous certification CCOF-2012-4287.\n\n"
        "Fraud Prevention Plan (7 CFR 205.201(a)(3), SOE rule effective "
        "2024-03-19):\n"
        "  - OFPP uploaded 2026-03-19, responsible person Maria Elena Gutierrez.\n"
        "  - Vulnerability assessment covers: input procurement, supplier "
        "verification (organic certificates on file for all chemical and seed "
        "suppliers), commingling at harvest/handling, post-harvest recordkeeping.\n"
        "  - Supplier verification: every input supplier provides a current "
        "organic certificate (Wilbur-Ellis, Cal-West Ag Supply, Brokaw Nursery) "
        "filed with the OFPP.\n"
        "  - Fraud-risk review cadence: annual, conducted before each CCOF "
        "inspection cycle.\n\n"
        "Certifier notification duty (7 CFR 205.400(f)):\n"
        "  - Any application or drift of a prohibited substance reported to "
        "CCOF immediately per § 205.400(f)(1).\n"
        "  - Any change in the certified operation (new input, new parcel, "
        "buffer modification, split-operation change) reported to CCOF "
        "immediately per § 205.400(f)(2)."
    )

    recordkeeping = (
        "Records are maintained in Trazo, a digital recordkeeping system, and "
        "retained for 5 years per 7 CFR 205.103. Records include: production "
        "events (planting, irrigation, harvest, post-harvest), chemical / soil / "
        "pest management events with supplier name + purchase date + invoice "
        "number, harvest yield logs, sales invoices to Organically Grown "
        "Company (OGC) with 'organic' on invoice per § 205.103(b)(3) audit-trail documentation, input / "
        "material lists with OMRI / WSDA / CDFA-OIM / National List "
        "classification, certifications (CCOF + Bee Better), OSP versions, "
        "annual updates, ParcelCropHistory (3-year crop rotation history per "
        "§ 205.202).\n\n"
        "Change history is captured via django-auditlog applying 21 CFR Part 11 "
        "trustworthy-records principles: per-field user attribution, UTC "
        "timestamp, before/after diff. Operator credentials are individual "
        "(Maria Elena Gutierrez has primary admin access; field staff have "
        "scoped event-creation rights). Records are exportable on demand as a "
        "consolidated audit PDF for CCOF inspection."
    )

    commingling = (
        "Split-operation status: NO — Solana Verde Organic Ranch is wholly "
        "organic. No conventional production occurs on this operation, on any "
        "parcel, at any time of year (§ 205.201(a)(5)).\n\n"
        "Buffer zones (§ 205.202(c)): hedgerows on east and north property "
        "boundaries provide 25-foot vegetative buffer from neighboring "
        "conventional citrus. South and west boundaries face open hillside / "
        "natural habitat — no adjacent conventional operations within 100 feet. "
        "Drift-deposition signage at north boundary (refreshed 2026-03-29 per "
        "CCOF inspector observation).\n\n"
        "Storage separation: all certified-organic inputs stored in the "
        "dedicated organic-inputs locker (locked, separate from any "
        "non-organic items). Inventory log maintained.\n\n"
        "Equipment cleaning (§ 205.272): tractors, sprayers, and harvest bins "
        "used exclusively on this operation. When equipment is shared with the "
        "neighboring conventional citrus operator (rented sprayer, 2026-02-14), "
        "documented triple-rinse cleaning is performed per the Equipment "
        "Maintenance event with cleaning_date, cleaning_method, cleaned_by, and "
        "shared_with_conventional flag set true.\n\n"
        "Harvest commingling prevention: dedicated organic harvest bins, "
        "labelled at fill, transported direct to OGC cold-chain refer truck "
        "with seal-and-manifest tracking. No co-loading with non-organic loads."
    )

    additional = (
        "Certifier-specific attachments (CCOF G-forms, land-history "
        "affidavits, parcel maps, hedgerow inventory, 5-year crop-rotation "
        "diagram, water-source affidavit, well-permit copy) are filed with "
        "CCOF and referenced in Trazo via the OSP attachments section.\n\n"
        "Material / activity change requests: any operational change (new "
        "parcel, hedgerow modification, fence relocation, input list addition, "
        "split-operation change) is filed as a Material/Activity change "
        "request with CCOF per § 205.400(f)(2) and reflected in the next "
        "annual update per § 205.406.\n\n"
        "Bee Better Certified (BBV-2024-0891, Xerces Society, valid through "
        "2027-05-31): pollinator habitat plan filed with Xerces; hedgerow + "
        "pollinator-strip survey logs maintained alongside organic records.\n\n"
        "FSMA 204 readiness: Critical Tracking Events (CTE) and Key Data "
        "Elements (KDE) for harvest, cooling, packing, and shipping are "
        "captured in the History production lot record (lot_id SVR-2026-HA-001) "
        "with sold_to / sale_date / quantity_sold / transport_method / "
        "destination fields populated for downstream traceability."
    )

    narratives = {
        "practices_procedures": practices_procedures,
        "inputs_list": inputs_list,
        "monitoring_plan": monitoring_plan,
        "recordkeeping_description": recordkeeping,
        "commingling_barriers": commingling,
        "additional_certifier_info": additional,
    }
    sections = {key: {"narrative": narratives[key], "last_updated": last_updated_iso} for key in OSP_SECTION_KEYS}

    osp = OrganicSystemPlan.objects.create(
        establishment=establishment,
        certification=ccof_cert,
        version_number=1,
        status="active",
        effective_date=effective_date_value,
        submitted_at=submitted_at_dt,
        approved_at=approved_at_dt,
        sections=sections,
        created_by=user,
    )

    # Approved-input catalogs — attach ONLY the products that are explicitly
    # named in the inputs_list narrative above. The audit PDF cross-checks each
    # registry entry against the narrative; entries not name-matched in the
    # narrative are flagged as § 205.201(a)(2) gaps. Tight matching keeps the
    # demo's compliance snapshot at PASS for inputs traceability.
    #
    # Empty querysets are tolerated because seed_omri_minimal /
    # seed_wsda_materials / seed_national_list run independently.
    omri_named = OMRIProduct.objects.filter(
        product_name__in=[
            "Neptune's Harvest Organic Fish and Seaweed Fertilizer 2-3-1",
            "DiPel DF Biological Insecticide Water Dispersible Granule",
            "Entrust SC Naturalyte Insect Control",
        ]
    )
    if omri_named.exists():
        osp.approved_omri_products.add(*omri_named)

    wsda_named = WSDAMaterial.objects.filter(
        brand_name__in=[
            "Neptune's Harvest Fish & Seaweed 2-3-1",
            "Dipel DF",
            "Entrust SC",
        ]
    )
    if wsda_named.exists():
        osp.approved_wsda_materials.add(*wsda_named)

    nl_named = NationalListSubstance.objects.filter(
        substance_name__in=[
            "Copper hydroxide",
            "Spinosad",
            "Microbial products (Bacillus thuringiensis, etc.)",
        ]
    )
    if nl_named.exists():
        osp.approved_national_list_substances.add(*nl_named)

    return osp
