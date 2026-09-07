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
    OSPAnnualUpdate,
    WSDAMaterial,
)
from certifications.services.omri_verifier import looks_like_omri_code
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, ParcelCropHistory, Product
from subscriptions.models import Plan, Subscription
from users.models import User, WorksIn

# Solana Verde is a DEMONSTRATION fixture, not a real operation. The "(DEMO)"
# suffix is deliberate and load-bearing: the establishment name is what the
# consumer hero, the QR page, the JSON-LD, and the audit PDF all render, so the
# disclosure travels with every screenshot and forward. Every third-party name in
# this dataset (certifier, inspector, suppliers, buyer) is likewise invented — a
# fictional farm must never carry a real accredited certifier's or supplier's
# name attached to invented compliance records.
COMPANY_NAME = "Solana Verde Farms LLC (DEMO)"
ESTABLISHMENT_NAME = "Solana Verde Organic Ranch (DEMO)"

# --- Canonical season figures -------------------------------------------------
# ONE definition, imported by every module that states a number, because the season
# yield is repeated in a History field, a harvest event's `yield_quantity`, three
# event NARRATIVES, a packing carton count and a shipping payload. When those drifted
# apart (2026-08-13/15) the packet showed 606,270 lb in the summary and "Total yield:
# 11,200 lbs" in the harvest event on the same production — and CCOF's Production
# Verification Audit ("estimated production/yield capacity vs. actual production/
# sales") is precisely the review that opens on that discrepancy.
#
# 275,000 kg over 34.4 ha = 7,994 kg/ha = 7,132 lb/acre over 4,250 trees = 143 lb/tree.
# All three framings land inside commercial California Hass ranges; the previous 5,080 kg
# was 148 kg/ha, ~50x low, and reconciled perfectly against itself.
SEASON_YIELD_KG = Decimal("275000")
SEASON_YIELD_LB = Decimal("606270")  # 275,000 kg x 2.20462, rounded
SEASON_SOLD_KG = Decimal("260000")  # 94.5%; balance is culls/grade-outs, per the packet
SEASON_SOLD_LB = Decimal("573201")
PRE_HARVEST_ESTIMATE_LB = Decimal("590000")  # thinning-time estimate; actual came in +2.8%
CARTON_NET_LB = Decimal("25")
SEASON_CARTONS = int(SEASON_YIELD_LB / CARTON_NET_LB)  # 24,250

# The buyer is INVENTED, like every other third-party name here (see above). An earlier
# scaling pass briefly wrote a real Pacific-Northwest distributor into these records;
# that is exactly what the note above forbids.
BUYER_NAME = "Pacific Organic Distributors (POD)"


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
            "DEMONSTRATION DATASET — this operation, its people, its certifier, and every "
            "record shown are invented for product demonstration. "
            "Family-owned certified organic avocado ranch in Fallbrook, California, "
            "operating since 2009. Producing premium Hass avocados for independent natural "
            "retailers via Pacific Organic Distributors distribution. 285 acres total, USDA Organic "
            "certified through PSOC, Pollinator Friendly Certified via Pollinator Habitat Alliance (DEMO)."
        ),
        contact_email="info@solanaverde.farm",
        contact_phone="+1-760-555-0142",
        employee_count=57,
        industry="Specialty Agriculture",
        is_active=True,
        legal_structure="LLC",
        primary_commodities="Hass Avocado",
        sustainability_commitment="USDA Organic, Pollinator Friendly Certified, regenerative soil practices",
        certifications="USDA Organic (PSOC), Pollinator Friendly Certified",
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
            "DEMONSTRATION DATASET — invented operation, people, certifier, and records. "
            "Family-owned organic avocado ranch in Fallbrook, California since 2009. "
            "We grow premium Hass avocados using regenerative organic practices, drip "
            "irrigation, and integrated pest management to protect our coastal hillside "
            "ecosystem. USDA Organic certified through PSOC. Our soil health program has "
            "increased organic matter from 1.8% to 4.2% over 15 years. We supply premium "
            "organic retailers through Pacific Organic Distributors (POD)."
        ),
        latitude=33.38,
        longitude=-117.25,
        contact_person="Maria Elena Gutierrez",
        contact_phone="+1-760-555-0143",
        is_active=True,
        crops_grown=["Hass Avocados", "Cover Crops", "Companion Herbs"],
        # Practices only. A certification belongs in the Certification table, where it can
        # be checked against the USDA Organic Integrity Database — not in a free-text list
        # a farmer types. "USDA Organic Certified" used to lead this array (2026-08-07).
        sustainability_practices=[
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
        # The `soil_types` COLUMN NAME is legacy. Every surface labels this field "Soil
        # health practices", and the farm form asks for practices ("Cover cropping,
        # Compost application, No-till"). Seeding soil texture classes here made the
        # producer profile AND the shopper page both read "Soil health practices: Clay
        # Loam, Sandy Loam" (fixed 2026-08-07).
        #
        # Practices are also the more useful concept on both surfaces: a certifier reads
        # soil fertility as management under 7 CFR 205.203, and "Cover cropping" means
        # something to a shopper where a texture class does not.
        soil_types=["Cover cropping (winter legumes)", "Compost application", "Reduced tillage"],
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
    # Seeded farm: the records below are invented, so every certifier packet, OSP module,
    # workbook and PUR export built from it is stamped a specimen (common/specimen.py).
    establishment.is_demo = True
    establishment.save(update_fields=["is_demo"])

    # ------------------------------------------------------------------ #
    # Certifications                                                       #
    # ------------------------------------------------------------------ #
    organic_cert = Certification.objects.create(
        establishment=establishment,
        certification_type="usda_organic",
        certification_number="DEMO-ORG-0000",
        certifier_name="DEMO — Pacific Slope Organic Certifiers (sample data, not an accredited agent)",
        effective_date=date(2024, 4, 1),
        # NOP organic certificates do not expire (§ 205.404(d)); this "expiry"
        # is the annual-renewal anniversary. Keep it in the future so the cert
        # renders ACTIVE across the 2026 production period and the current date.
        expiry_date=date(2027, 4, 1),
        certification_scope="Crops - All",
        certified_items=["Hass Avocado"],
        verification_status="verified",
    )
    Certification.objects.create(
        establishment=establishment,
        certification_type="other",
        certification_number="DEMO-POL-0000",
        certifier_name="DEMO — Pollinator Habitat Alliance (sample data, not an accredited agent)",
        effective_date=date(2024, 6, 1),
        expiry_date=date(2027, 5, 31),
        certification_scope="Pollinator Conservation",
        certified_items=["Hass Avocado"],
        verification_status="self_reported",
    )

    # ------------------------------------------------------------------ #
    # Organic System Plan (7 CFR 205.201) — active v1, linked to PSOC      #
    # cert. Six required narrative sections fully populated with real     #
    # operation details (no "farmer to complete" placeholders) so the     #
    # audit-export PDF renders a submission-ready dossier.                #
    # ------------------------------------------------------------------ #
    _seed_solana_verde_osp(establishment, organic_cert, user)

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
        # A demo parcel must not resolve to a real field boundary. "approximate"
        # is also the model default; the seeder states it explicitly so a future
        # edit cannot silently promote the demo farm back to exact coordinates.
        location_disclosure_level="approximate",
        certified=True,
        certification_type="USDA Organic (PSOC)",
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
            "PSOC inspection passed. Preparing for first certified organic season."
        ),
    )
    ParcelCropHistory.objects.create(
        parcel=parcel,
        year=2024,
        crop_grown="Hass Avocados",
        production_method="organic",
        substances_applied=("Neptune's Harvest 2-3-1, Bacillus thuringiensis (Bt), compost 10 tons/acre"),
        notes=(
            "First full certified organic year. PSOC inspection passed April 2024. "
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
            "USDA Organic certified through PSOC. Lot SVR-2026-HA-001."
        ),
        production_amount=SEASON_YIELD_KG,
        production_unit="kg",
        quality_grade="grade_a",
        harvest_method="manual",
        production_method="organic",
        # Consumer hero image. History.cover_image_url is only auto-derived on the
        # API creation path (models.py ~700, from the first gallery image); a seeder
        # that builds History() directly never gets one, so a `--reset` would leave
        # the QR page with a blank hero. Set it explicitly and deterministically.
        cover_image_url="https://images.unsplash.com/photo-1726177551991-270f9e79b65e?w=1600&q=80",
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
        sold_to=BUYER_NAME,
        sale_date=date(2026, 4, 15),
        quantity_sold=SEASON_SOLD_KG,
        quantity_sold_unit="kg",
        organic_on_invoice=True,
        transport_method="Refrigerated truck",
        destination="POD Distribution Hub, Portland, OR",
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


def _seed_solana_verde_osp(establishment, organic_cert, user):
    """
    Create an active Organic System Plan v1 for Solana Verde with fully-populated
    narratives for the six required sections per 7 CFR 205.201(a)(1)-(6).

    Linked to the active PSOC certification. Approved-input M2M tables are
    populated when seed_omri_minimal / seed_wsda_materials / seed_national_list
    have been run beforehand; otherwise the M2M attaches a partial set silently.
    """
    # OSP submission/approval timeline reflects a real PSOC cycle: drafted +
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
        "Irrigation: drip system (95% efficiency) fed by an on-site 180-foot, "
        "~1,500 GPM well, with soil moisture sensors monitoring every zone. "
        "Routine irrigation is drip only (no flood). Overhead micro-sprinklers "
        "are installed for frost/heat-stress protection (evaporative cooling) "
        "and are used only during extreme-weather events, not for routine "
        "irrigation. Irrigation events are logged per-event in Trazo with "
        "duration and volume.\n\n"
        "Soil management (§ 205.203): on-farm composting of prunings + cover-crop "
        "residue (C:N ~18:1), applied around tree basins. Separately, aged "
        "(uncomposted) horse manure is applied to younger tree rows at ~2 tons/acre "
        "and managed under the § 205.203(c)(1) 120-day raw-manure pre-harvest "
        "interval — it is NOT composted to the § 205.203(c)(2) standard. Cover-crop "
        "residue is incorporated as green manure each spring. Soil organic matter "
        "has risen from 1.8% (2009) to 4.2% (2025) per UC ANR-protocol soil tests.\n\n"
        "Pest management (§ 205.206): IPM-first program — weekly scouting (June-"
        "October), beneficial-insect releases (lacewings, lady beetles), "
        "monitoring traps for persea mite and avocado thrips, threshold-based "
        "intervention only. Approved organic inputs (copper hydroxide, DiPel "
        "DF, Entrust SC) listed and classified in section (a)(2) — applied at "
        "or below label rate when pest pressure exceeds documented thresholds.\n\n"
        "Conservation practices: hedgerows around field perimeters, pollinator "
        "strips, no-till between tree rows. PSOC inspection records, Pollinator Friendly "
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
        "  - Neptune's Harvest Organic Fish & Seaweed Fertilizer 2-3-1 "
        "(OMRI listed) — foliar feed, 1 gal/acre, sourced from "
        "Fallbrook Farm Supply, Fallbrook CA.\n"
        "  - Copper hydroxide (7 CFR 205.601(i)(1) National List allowed) — "
        "fungicide for anthracnose, label rate 1.5 lb/acre, sourced from "
        "Coastline Ag Supply Vista CA. Used in compliance with § 205.601(i)(1) "
        "tolerance and resistance-management restrictions.\n"
        "  - DiPel DF Bacillus thuringiensis (OMRI listed; § 205.601(e) "
        "Microbial products) — caterpillar control, 0.5 lb/acre, sourced from "
        "Coastline Ag Supply Vista CA.\n"
        "  - Entrust SC Naturalyte Insect Control / Spinosad (OMRI + WSDA "
        "listed; § 205.601(e) Spinosad) — thrips control, 4 fl oz/acre, "
        "sourced from Fallbrook Farm Supply.\n"
        "  - Avenger AG (d-limonene 70%, OMRI listed) — inter-row weed control, "
        "applied with a shielded boom sprayer, sourced from Fallbrook Farm Supply.\n"
        "  - On-farm compost (prunings + cover-crop residue) — no purchase, "
        "internal mass-balance tracked per 7 CFR 205.203(c)(2).\n"
        "  - Aged horse manure applied RAW under the § 205.203(c)(1) 120-day "
        "pre-harvest interval (not composted) — sourced from a local stable.\n"
        "  - Saticoy Grove Nursery (Saticoy CA) certified-organic Hass nursery stock "
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
        "  - Annual PSOC inspection (most recent 2026-03-28 by R. Alvarez, "
        "PASSED). Certified organic since 2024 (DEMO-ORG-0000); 36-month "
        "transition completed 2023.\n\n"
        "Fraud Prevention Plan (7 CFR 205.201(a)(3), SOE rule effective "
        "2024-03-19):\n"
        "  - OFPP uploaded 2026-03-19, responsible person Maria Elena Gutierrez.\n"
        "  - Vulnerability assessment covers: input procurement, supplier "
        "verification (organic certificates on file for all chemical and seed "
        "suppliers), commingling at harvest/handling, post-harvest recordkeeping.\n"
        "  - Supplier verification: every input supplier provides a current "
        "organic certificate (Coastline Ag Supply, Fallbrook Farm Supply, Saticoy Grove Nursery) "
        "filed with the OFPP.\n"
        "  - Fraud-risk review cadence: annual, conducted before each PSOC "
        "inspection cycle.\n\n"
        "Certifier notification duty (7 CFR 205.400(f)):\n"
        "  - Any application or drift of a prohibited substance reported to "
        "PSOC immediately per § 205.400(f)(1).\n"
        "  - Any change in the certified operation (new input, new parcel, "
        "buffer modification, split-operation change) reported to PSOC "
        "immediately per § 205.400(f)(2)."
    )

    recordkeeping = (
        "Records are maintained in Trazo, a digital recordkeeping system, and "
        "retained for 5 years per 7 CFR 205.103. Records include: production "
        "events (planting, irrigation, harvest, post-harvest), chemical / soil / "
        "pest management events with supplier name + purchase date + invoice "
        "number, harvest yield logs, sales invoices to Pacific Organic Distributors "
        "Company (POD) with 'organic' on invoice per § 205.103(b)(2) audit-trail documentation, input / "
        "material lists with OMRI / WSDA / CDFA-OIM / National List "
        "classification, certifications (PSOC + Pollinator Friendly), OSP versions, "
        "annual updates, ParcelCropHistory (3-year crop rotation history per "
        "§ 205.202).\n\n"
        "Change history is captured via django-auditlog applying 21 CFR Part 11 "
        "trustworthy-records principles: per-field user attribution, UTC "
        "timestamp, before/after diff. Operator credentials are individual "
        "(Maria Elena Gutierrez has primary admin access; field staff have "
        "scoped event-creation rights). Records are exportable on demand as a "
        "consolidated audit PDF for PSOC inspection."
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
        "PSOC inspector observation).\n\n"
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
        "labelled at fill, transported direct to POD cold-chain refer truck "
        "with seal-and-manifest tracking. No co-loading with non-organic loads."
    )

    additional = (
        "Certifier-specific attachments (PSOC G-forms, land-history "
        "affidavits, parcel maps, hedgerow inventory, 5-year crop-rotation "
        "diagram, water-source affidavit, well-permit copy) are filed with "
        "PSOC and referenced in Trazo via the OSP attachments section.\n\n"
        "Material / activity change requests: any operational change (new "
        "parcel, hedgerow modification, fence relocation, input list addition, "
        "split-operation change) is filed as a Material/Activity change "
        "request with PSOC per § 205.400(f)(2) and reflected in the next "
        "annual update per § 205.406.\n\n"
        "Pollinator Friendly Certified (DEMO-POL-0000, Pollinator Habitat Alliance (DEMO), valid through "
        "2027-05-31): pollinator habitat plan filed with the Pollinator Habitat Alliance (DEMO); hedgerow + "
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
        certification=organic_cert,
        version_number=1,
        status="active",
        effective_date=effective_date_value,
        submitted_at=submitted_at_dt,
        approved_at=approved_at_dt,
        sections=sections,
        created_by=user,
    )

    # Approved-input registry (§ 205.201(a)(2)). get_or_create so the OSP
    # registry is ALWAYS populated (regardless of what other seed commands ran)
    # and includes EVERY input actually applied this season — so the drift
    # detector has a baseline and the narrative↔registry cross-check passes.
    # Each name matches the inputs_list narrative above.
    # ⛔ These four rows used to be created with INVENTED identifiers — "OMRI-SVR-NEPTUNE",
    # "OMRI-SVR-DIPEL", "OMRI-SVR-ENTRUST", "OMRI-SVR-AVENGER" — keyed on `product_name`
    # into the GLOBAL OMRIProduct table. On a fresh database the demo farm therefore
    # defined the catalogue, and those strings printed into certifier packets as OMRI
    # identifiers that resolve to nothing. Every code below is OMRI's own, transcribed
    # from the free Crop Products List (September 5, 2026) and carried in
    # certifications/data/omri_seed.csv.
    #
    # Keyed on `omri_id` (the unique column), not on the name, so a near-miss name can no
    # longer mint a second row; and a code that is not OMRI-shaped is refused outright
    # rather than seeded — a demo must not be able to author a catalogue entry.
    for omri_id, name, maker in [
        ("nhf-3041", "Neptune's Harvest Organic Fish & Seaweed Fertilizer 2-3-1", "Ocean Crest Seafoods"),
        ("abb-15778", "DiPel DF Biological Insecticide Water Dispersible Granule", "Valent BioSciences® LLC"),
        ("dow-2900", "Entrust SC Naturalyte Insect Control", "Dow Agrosciences, LLC"),
        ("cef-12721", "Avenger AG Optima Burndown Herbicide", "Avenger Products, LLC"),
    ]:
        if not looks_like_omri_code(omri_id):
            raise ValueError(f"Refusing to seed catalog row with a non-OMRI identifier: {omri_id!r}")
        obj, _ = OMRIProduct.objects.get_or_create(
            omri_id=omri_id, defaults=dict(product_name=name, manufacturer=maker)
        )
        osp.approved_omri_products.add(obj)

    for sname, sec, sub in [
        ("Copper hydroxide", "205.601", "i"),
        ("Spinosad", "205.601", "e"),
    ]:
        obj, _ = NationalListSubstance.objects.get_or_create(
            substance_name_normalized=sname.lower(),
            cfr_section=sec,
            defaults=dict(substance_name=sname, subsection=sub, status="allowed"),
        )
        osp.approved_national_list_substances.add(obj)

    # Annual OSP continuation / update (§ 205.406) — required each year for a
    # continuously-certified operation. Filed for the 2025 reporting year.
    OSPAnnualUpdate.objects.get_or_create(
        prior_osp=osp,
        reporting_year=2025,
        defaults=dict(
            changes_summary=(
                "Added Avenger AG (d-limonene) for inter-row weed control. No prohibited "
                "substances used. All other OSP sections unchanged from the prior version. "
                "(The later east-boundary buffer widening is documented separately as the "
                "corrective action for the 2026-03-16 spray-drift incident, not in this update.)"
            ),
            additions=[
                {"section": "inputs_list", "field": "approved_inputs", "old": "", "new": "Avenger AG (d-limonene)"}
            ],
            deletions=[],
            sections_unchanged_attestation={k: (k != "inputs_list") for k in OSP_SECTION_KEYS},
            submitted_at=datetime(2026, 1, 10, 17, 0, tzinfo=dt_tz.utc),
            certifier_acknowledged_at=datetime(2026, 1, 22, 17, 0, tzinfo=dt_tz.utc),
            created_by=user,
        ),
    )

    return osp
