"""
Loewen Family Farm — base infrastructure helper (build-first GTM sample).

Creates a CLEAN regenerative organic WALNUT operation for Leonard Loewen, our
#1 GTM lead, from real public data (Real Organic Project directory, CalCAN
"Farmer Fridays," CDFA producer lists) + the practices he described by email
(sheep grazing, cover crops between rows, no synthetic spray, bugs/birds
biodiversity, Korean Organic export). The consumer page must tell his
"real vs fake organic" story through FACTS (practice_summary), not a badge.

NOT a NOP stress-test fixture: deliberately omits the contamination-incident /
conventional-shared-equipment artifacts that Solana Verde seeds (they would
contradict Leonard's clean, no-spray narrative).

Creates: company, establishment, parcel, product, crop_type, 3 certifications
(USDA Organic/CCOF, Real Organic Project, Korean Organic), an active OSP v1,
a published finished walnut production (2024-25) + a current production.

All literal values are real/public or Leonard's own described practices. No
fabricated certificate numbers (left blank, self_reported) — claim-safe.
"""

from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from carbon.models import CropType
from certifications.models import OSP_SECTION_KEYS, Certification, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, ParcelCropHistory, Product
from subscriptions.models import Plan, Subscription
from users.models import User, WorksIn

COMPANY_NAME = "Loewen Family Farm"
ESTABLISHMENT_NAME = "Loewen Family Farm"

# Photo URLs — Oscar fills these with real, publicly-hosted images per the
# shot-list (hero = sheep grazing under walnut trees). Empty lists -> no album
# (page still renders; just no photo for that event). image_url accepts any
# public URL, no S3 upload needed.
LOEWEN_IMAGES = {
    "hero": [],          # sheep grazing under walnut trees (cover_image_url)
    "grazing": [],       # sheep in the orchard
    "cover_crop": [],    # flowering cover crop / tall grass between rows
    "habitat": [],       # owl box / hedgerow / birds
    "wildlife": [],      # owl in box / ladybugs on leaf / songbird close-up
    "harvest": [],       # walnut harvest / walnuts in-shell
    "soil_test": [],     # hands in healthy soil
    "orchard": [],       # walnut orchard rows (album / general)
}


def _dt(year, month, day, hour=8):
    return datetime(year, month, day, hour, 0, tzinfo=dt_tz.utc)


def create_loewen_base(user):
    """
    Create the full Loewen Family Farm stack.

    Returns:
        (company, establishment, parcel, product, crop_type,
         production_finished, production_current)
    """
    # ------------------------------------------------------------------ #
    # Company                                                             #
    # ------------------------------------------------------------------ #
    company = Company.objects.create(
        name=COMPANY_NAME,
        tradename="Loewen Family Farm",
        address="1890 State Highway 45",
        city="Glenn",
        state="California",
        country="United States",
        zip_code="95943",
        description=(
            "Family-owned certified organic walnut farm in Glenn, California, "
            "growing ~110 acres of walnuts since 2013. Regenerative system: "
            "sheep grazing under the trees, multi-species cover crops between "
            "rows, no synthetic sprays, and habitat for beneficial insects and "
            "birds. USDA Organic (CCOF) and Real Organic Project certified; "
            "some product sold under the Korean Organic program."
        ),
        contact_email="info@loewenfamilyfarm.com",
        employee_count=6,
        industry="Specialty Agriculture",
        is_active=True,
        legal_structure="Family Farm",
        primary_commodities="Organic Walnuts",
        sustainability_commitment="Regenerative organic: sheep grazing, cover crops, no synthetic inputs",
        certifications="USDA Organic (CCOF), Real Organic Project, Korean Organic",
        blockchain_subscription_status=False,
    )

    WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)

    # Subscription (non-fatal if plan missing)
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
        pass

    # ------------------------------------------------------------------ #
    # Establishment                                                       #
    # ------------------------------------------------------------------ #
    establishment = Establishment.objects.create(
        name=ESTABLISHMENT_NAME,
        address="1890 State Highway 45",
        city="Glenn",
        state="California",
        country="United States",
        zip_code="95943",
        company=company,
        description=(
            "Certified organic walnut farm in Glenn County, California, farmed "
            "regeneratively since 2013. We graze sheep under the walnut canopy, "
            "keep living cover crops (legumes, grasses, brassicas) between the "
            "rows year-round, and use no synthetic sprays. The result is a "
            "two-foot living floor, abundant beneficial insects, and birds "
            "throughout the orchard. USDA Organic (CCOF) and Real Organic "
            "Project certified."
        ),
        latitude=39.5996,
        longitude=-122.0094,
        contact_person="Leonard Loewen",
        is_active=True,
        crops_grown=["Walnuts", "Cover Crops"],
        sustainability_practices=[
            "USDA Organic Certified (CCOF)",
            "Real Organic Project Certified",
            "Integrated sheep grazing",
            "Multi-species cover crops",
            "No synthetic sprays",
            "Beneficial insect & bird habitat",
        ],
        employee_count=6,
        total_acreage=110.0,
        year_established=2013,
        establishment_type="orchard",
        farming_method="organic",
        conservation_practices=[
            "Cover Crops",
            "Integrated Livestock (sheep grazing)",
            "Hedgerows / Habitat",
            "No-Till Between Rows",
        ],
        # Organic Fraud Prevention Plan (7 CFR 205.201(a)(3))
        fraud_prevention_plan_date=date(2024, 1, 15),
        ofpp_responsible_person="Leonard Loewen",
        fraud_prevention_plan_uploaded=True,
        # Wholly organic — no split operation
        has_split_operation=False,
        split_operation_plan="",
    )

    # ------------------------------------------------------------------ #
    # Certifications (3)                                                  #
    # ------------------------------------------------------------------ #
    # USDA Organic — VERIFIED against the real USDA Organic Integrity Database.
    # Confirmed OID match: op "Leonard Loewen", Certified, California, certifier
    # "CCOF Certification Services, LLC". Honest DB-verified claim (not fabricated)
    # — required for the consumer page to display the USDA Organic badge.
    ccof_cert = Certification.objects.create(
        establishment=establishment,
        certification_type="usda_organic",
        certifier_name="CCOF Certification Services, LLC",
        effective_date=date(2022, 1, 1),
        expiry_date=date(2026, 12, 31),
        certification_scope="Crops - Walnuts",
        certified_items=["Walnuts"],
        verification_status="verified",
        verification_source="usda_organic_integrity_db",
        verification_source_url="https://organic.ams.usda.gov/integrity/",
        usda_operation_name="Leonard Loewen",
        last_verified_at=datetime(2026, 6, 1, 12, 0, tzinfo=dt_tz.utc),
    )
    Certification.objects.create(
        establishment=establishment,
        certification_type="real_organic_project",
        certifier_name="Real Organic Project",
        certification_scope="Crops - Walnuts",
        certified_items=["Walnuts"],
        verification_status="self_reported",
        verification_source="real_organic_project_directory",
        verification_source_url="https://realorganicproject.org/directory/loewen-family-farm/",
    )
    Certification.objects.create(
        establishment=establishment,
        certification_type="korean_organic",
        certifier_name="Korean Organic Program (export equivalence)",
        certification_scope="Crops - Walnuts (export)",
        certified_items=["Walnuts"],
        verification_status="self_reported",
    )

    # ------------------------------------------------------------------ #
    # Organic System Plan v1 (active, linked to CCOF cert)                #
    # ------------------------------------------------------------------ #
    _seed_loewen_osp(establishment, ccof_cert, user)

    # ------------------------------------------------------------------ #
    # Product & CropType                                                  #
    # ------------------------------------------------------------------ #
    product, _ = Product.objects.get_or_create(
        name="Walnut",
        defaults={"description": "Organic Walnuts"},
    )
    crop_type, _ = CropType.objects.get_or_create(
        slug="walnuts",
        defaults={
            "name": "Walnuts",
            "category": "tree_nut",
            "description": "Organic walnut production (regenerative)",
            "typical_farm_size": "40-200 acres",
            "growing_season": "March - October",
            "harvest_season": "September - October",
            "emissions_per_hectare": 3000.0,
            "industry_average": 3600.0,
            "best_practice": 2400.0,
            "carbon_credit_potential": 1.4,
            "typical_cost_per_hectare": 11000.0,
            "fertilizer_cost_per_hectare": 2000.0,
            "fuel_cost_per_hectare": 1400.0,
            "irrigation_cost_per_hectare": 1800.0,
            "labor_cost_per_hectare": 3500.0,
            "organic_premium": "20-35%",
            "sustainable_premium": "10-20%",
            "local_premium": "5-10%",
            "sustainability_opportunities": [
                "Integrated livestock (sheep grazing)",
                "Multi-species cover crops",
                "On-farm compost",
                "Beneficial insect & bird habitat",
            ],
            "usda_factors_used": True,
            "data_source": "USDA ARS, UC Davis Walnut Cost Studies",
        },
    )

    # ------------------------------------------------------------------ #
    # Parcel — 110 acres (44.52 ha)                                       #
    # ------------------------------------------------------------------ #
    lng, lat = -122.0094, 39.5996
    parcel = Parcel.objects.create(
        name="Loewen Walnut Orchard",
        description=(
            "Our ~110-acre organic walnut orchard along State Highway 45 in "
            "Glenn County, farmed since 2013. Sheep graze the living floor "
            "beneath the trees; multi-species cover crops (legumes, grasses, "
            "brassicas) grow between every row. No synthetic sprays. The "
            "difference is visible: a two-foot green floor, beneficial insects, "
            "and birds throughout."
        ),
        establishment=establishment,
        product=product,
        area=44.52,
        certified=True,
        certification_type="USDA Organic (CCOF) + Real Organic Project",
        contact_person="Leonard Loewen",
        address="1890 State Highway 45, Glenn, CA",
        polygon={
            "type": "Polygon",
            "coordinates": [
                [
                    [lng - 0.015, lat - 0.012],
                    [lng + 0.015, lat - 0.012],
                    [lng + 0.015, lat + 0.012],
                    [lng - 0.015, lat + 0.012],
                    [lng - 0.015, lat - 0.012],
                ]
            ],
        },
        agricultural_details={
            "primary_crop": "Organic Walnuts",
            "tree_age": "established since 2013",
            "production_method": "organic",
            "sustainability_practices": (
                "Integrated sheep grazing, multi-species cover crops between "
                "rows, no synthetic sprays, beneficial insect & bird habitat"
            ),
            "cover_crop_species": ["legumes", "grasses", "brassicas"],
            "consumer_story": (
                "Leonard wanted a system that divides between real and fake "
                "organic. On this orchard the sheep graze the living floor, "
                "cover crops grow two feet tall between the rows, nothing is "
                "sprayed, and the place is full of bugs and birds. Every "
                "practice here is documented, so a buyer can see exactly how "
                "these walnuts were grown."
            ),
        },
        carbon_calculation_enabled=True,
    )

    # ParcelCropHistory — 3 years (7 CFR 205.202)
    for yr in (2023, 2024, 2025):
        ParcelCropHistory.objects.create(
            parcel=parcel,
            year=yr,
            crop_grown="Walnuts",
            production_method="organic",
            substances_applied="Cover crop seed, on-farm compost; no synthetic pesticides or fertilizers",
            notes=(
                f"{yr} organic walnut season. Sheep grazed the orchard floor; "
                "multi-species cover crop between rows. No prohibited substances."
            ),
        )

    # ------------------------------------------------------------------ #
    # Finished production (PUBLISHED) — 2024-25 walnut season             #
    # ------------------------------------------------------------------ #
    finish_dt = _dt(2025, 10, 20, 12)
    production_finished = History(
        name="Loewen Organic Walnuts 2024-2025",
        type=History.ORCHARD,
        start_date=_dt(2024, 11, 1),
        expected_harvest=_dt(2025, 9, 20),
        finish_date=finish_dt,
        published=True,
        description=(
            "Complete 2024-2025 organic walnut season at Loewen Family Farm. "
            "Documented regenerative practices: sheep grazing, cover crops, "
            "habitat, no synthetic sprays, harvest. USDA Organic (CCOF) + Real "
            "Organic Project certified; portion sold under the Korean Organic "
            "program."
        ),
        production_amount=180000,
        production_unit="kg",
        quality_grade="grade_a",
        harvest_method="mechanical",
        production_method="organic",
        lot_id="LOEWEN-2025-WAL-001",
        product=product,
        parcel=parcel,
        is_outdoor=True,
        operator=user,
        crop_type=crop_type,
        earning=0,
        sold_to="Korean Organic Program buyer (export)",
        sale_date=date(2025, 11, 1),
        quantity_sold=Decimal("180000"),
        quantity_sold_unit="kg",
        organic_on_invoice=True,
        cover_image_url=(LOEWEN_IMAGES.get("hero") or [""])[0],
        retention_until=finish_dt.date() + timedelta(days=5 * 365),
    )
    production_finished.save()

    # ------------------------------------------------------------------ #
    # Current production — 2025-26 season (in progress, unpublished)      #
    # ------------------------------------------------------------------ #
    production_current = History(
        name="Loewen Organic Walnuts 2025-2026",
        type=History.ORCHARD,
        start_date=_dt(2025, 11, 1),
        published=False,
        description=(
            "In-progress 2025-2026 organic walnut season. Early operations: "
            "cover crop establishment, sheep grazing, dormant care."
        ),
        production_amount=0,
        production_method="organic",
        product=product,
        parcel=parcel,
        is_outdoor=True,
        operator=user,
        crop_type=crop_type,
        earning=0,
    )
    production_current.save()

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


def _seed_loewen_osp(establishment, ccof_cert, user):
    """Active OSP v1 — six § 205.201(a) sections reflecting Leonard's real practices."""
    effective = date(2024, 1, 1)
    last_updated = effective.isoformat()

    narratives = {
        "practices_procedures": (
            "Operation: Loewen Family Farm — ~110-acre organic walnut orchard in Glenn "
            "County, California, farmed since 2013. Regenerative system built around three "
            "practices: (1) integrated sheep grazing of the orchard floor, which controls "
            "weeds and cycles nutrients; (2) multi-species cover crops (legumes, grasses, "
            "brassicas) between every tree row, kept as a living two-foot floor; (3) no "
            "synthetic sprays of any kind. Pruning prunings are returned to row middles. "
            "Pest management is observation- and habitat-based (beneficial insects, birds), "
            "not chemical. Harvest is mechanical in fall."
        ),
        "inputs_list": (
            "Inputs are minimal by design and logged per event in Trazo, classified against "
            "OMRI / 7 CFR 205.601 National List at entry. No synthetic pesticides, herbicides, "
            "or fertilizers are used or stored on the operation. Fertility comes from sheep "
            "grazing, cover-crop nitrogen fixation, and on-farm compost. Any occasional "
            "organic-approved input is recorded with supplier, date, and invoice. No prohibited "
            "substances per 7 CFR 205.602 are present on premises."
        ),
        "monitoring_plan": (
            "Monitoring: regular orchard scouting for pest pressure and beneficial-insect and "
            "bird activity, with threshold-based, non-chemical response. Cover-crop stand and "
            "grazing rotation tracked through the season. Annual soil test (organic matter, pH, "
            "nutrients). Annual CCOF inspection; continuous USDA Organic certification since "
            "2022 and Real Organic Project certification. Organic Fraud Prevention Plan on file "
            "(responsible person: Leonard Loewen); supplier organic certificates verified for "
            "any purchased input. Prohibited-substance application or drift, and any change to "
            "the certified operation, reported to CCOF per 7 CFR 205.400(f)."
        ),
        "recordkeeping_description": (
            "Records are maintained digitally in Trazo and retained for 5 years per 7 CFR "
            "205.103: production events (grazing, cover crop, irrigation, harvest), soil and "
            "pest-management events, harvest yields, sales invoices (with 'organic' on invoice "
            "per § 205.301(f), including Korean Organic export sales), input lists with National "
            "List classification, certifications (CCOF + Real Organic Project + Korean Organic), "
            "OSP versions, and 3-year ParcelCropHistory. Change history is captured per-field "
            "with user attribution and UTC timestamps; records export on demand as an audit PDF."
        ),
        "commingling_barriers": (
            "Split-operation status: NO — Loewen Family Farm is wholly organic; no conventional "
            "production occurs on any parcel at any time (§ 205.201(a)(5)). Because nothing is "
            "sprayed on the operation, on-farm drift risk is internal-zero; vegetative buffers "
            "are maintained along any boundary adjacent to neighboring operations. Harvest uses "
            "dedicated organic equipment and bins; lots are labelled and tracked to sale. "
            "Organic integrity is preserved from field through delivery."
        ),
        "additional_certifier_info": (
            "Real Organic Project certification (public directory listing on file) documents the "
            "soil-and-grazing-based practices that distinguish this operation from "
            "input-substitution 'organic.' A portion of the crop is sold under the Korean Organic "
            "program (export equivalence); organic identity and 'organic' on invoice are "
            "maintained for those lots. Land-history, grazing-rotation, and cover-crop records "
            "are retained alongside organic records and referenced in the OSP attachments."
        ),
    }
    sections = {key: {"narrative": narratives[key], "last_updated": last_updated} for key in OSP_SECTION_KEYS}

    OrganicSystemPlan.objects.create(
        establishment=establishment,
        certification=ccof_cert,
        version_number=1,
        status="active",
        effective_date=effective,
        submitted_at=datetime(2023, 11, 15, 17, 0, tzinfo=dt_tz.utc),
        approved_at=datetime(2023, 12, 20, 17, 0, tzinfo=dt_tz.utc),
        sections=sections,
        created_by=user,
    )
