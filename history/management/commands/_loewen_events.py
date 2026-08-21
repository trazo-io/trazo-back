"""
Loewen Family Farm — event builders (clean regenerative organic walnut story).

Populates the consumer page's `practice_summary` (FACTS, not a badge) with the
practices Leonard described: integrated sheep grazing, multi-species cover crops,
on-farm compost, hedgerow + nest-box habitat, no synthetic spray (IPM via
beneficials), plus walnut irrigation (summary-event flow), harvest, an
organic-approved fertility input, and certification + Korean-export sale.

Deliberately NO contamination incident and NO conventional-shared equipment
(those would contradict the "real, clean, no-spray" story).
"""

from datetime import date, datetime
from datetime import timezone as dt_tz
from decimal import Decimal

from certifications.models import OMRIProduct
from common.models import Gallery, GalleryImage
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    PestManagementEvent,
    ProductionEvent,
    SalesRecord,
    SoilManagementEvent,
    WeatherEvent,
)

from ._loewen_base import LOEWEN_IMAGES

# Itemized sale for the finished 2024–25 walnut season. Mirrors the production-
# level export sale (Korean Organic Program buyer, 180,000 kg on 2025-11-01) so
# the SOE sales record and the mass-balance reconcile to the same story instead
# of contradicting it. Generic, non-specific buyer — this is a sample record, so
# it must not assert an invented transaction with a real, checkable company.
# Keyed by invoice_number so apply_loewen_audit_fields is idempotent.
LOEWEN_SALES = [
    {
        "buyer_name": "Korean Organic Program buyer (export)",
        "sale_date": date(2025, 11, 1),
        "quantity": Decimal("180000.00"),
        "quantity_unit": "kg",
        "invoice_number": "LOEWEN-2025-EXP-001",
        "organic_on_invoice": True,
    },
]


def apply_loewen_audit_fields(prod):
    """
    Add the AUTHENTIC certifier-facing audit data the new export sections read,
    onto an existing finished Loewen production. Idempotent — safe to re-run and
    shared by both the seed command and backfill_loewen_audit_fields.

    Authentic to a regenerative organic walnut operation only:
      * NOP 5012 nitrogen_source = "organic" on fertilizer events
      * SOE (§ 205.307(a)) one itemized SalesRecord that mirrors the export sale

    Intentionally omits processed manure (5006), chlorine sanitizer (5026), an
    off-farm handler, and OSP change notifications — none fit his operation and
    all would fabricate his audit record.

    Also REPAIRS in place (idempotent): purges fabricated records left by an
    earlier version of this fixture, so an already-published production is
    corrected WITHOUT changing its public_id (Leonard's live sample link).
    """
    # REPAIR — purge fabricated third-party records from any production seeded by
    # an earlier fixture version. Safe no-op on freshly seeded data.
    keep_invoices = {s["invoice_number"] for s in LOEWEN_SALES}
    prod.sales_records.exclude(invoice_number__in=keep_invoices).delete()

    stale_facilities = list(prod.post_harvest_facilities.all())
    if stale_facilities:
        prod.post_harvest_facilities.clear()
        for fac in stale_facilities:
            try:
                fac.delete()
            except Exception:  # noqa: BLE001 — non-fatal
                pass

    try:
        from certifications.models import OrganicSystemPlan, OSPChangeNotification

        _osp = (
            OrganicSystemPlan.objects.filter(establishment=prod.parcel.establishment)
            .order_by("-version_number")
            .first()
        )
        if _osp is not None:
            # Loewen files no change notifications; clear any (incl. phantom
            # "Block C" and E2E-test residue) so the record reads "no changes".
            OSPChangeNotification.objects.filter(osp=_osp).delete()
    except Exception:  # noqa: BLE001 — non-fatal
        pass

    # Mark the summer-heat weather event's temperature as Celsius so the export
    # renders "42°C" (matching the "~42C" note) instead of defaulting the unit to
    # °F and printing "42°F" (winter cold in July).
    for wev in prod.history_weatherevent_events.filter(type=WeatherEvent.HIGH_TEMPERATURE):
        ed = dict(wev.extra_data or {})
        if ed.get("highest_temperature") and not ed.get("temperature_unit"):
            ed["temperature_unit"] = "C"
            wev.extra_data = ed
            wev.save(update_fields=["extra_data"])

    # NOP 5012 — nitrogen source on fertilizer events (fill only when blank).
    for ev in prod.history_chemicalevent_events.filter(type=ChemicalEvent.FERTILIZER):
        if not ev.nitrogen_source:
            ev.nitrogen_source = "organic"
            ev.save(update_fields=["nitrogen_source"])

    # SOE — itemized sales records (idempotent on production + invoice_number).
    for s in LOEWEN_SALES:
        SalesRecord.objects.get_or_create(
            production=prod,
            invoice_number=s["invoice_number"],
            defaults=dict(
                buyer_name=s["buyer_name"],
                sale_date=s["sale_date"],
                quantity=s["quantity"],
                quantity_unit=s["quantity_unit"],
                organic_on_invoice=s["organic_on_invoice"],
            ),
        )

    # NOP 2615 — no OSP change notifications are seeded for Loewen. The operation
    # reports no acreage/practice/input changes for the season, so fabricating one
    # (e.g. a phantom "Block C") would contradict the "no recorded changes" record
    # and read as invented regulatory correspondence to a certifier.


def _dt(year, month, day, hour=8):
    return datetime(year, month, day, hour, 0, tzinfo=dt_tz.utc)


def _album(key):
    """Create a Gallery from LOEWEN_IMAGES[key] public URLs, or None if empty."""
    urls = LOEWEN_IMAGES.get(key, [])
    if not urls:
        return None
    gallery = Gallery.objects.create()
    for url in urls:
        GalleryImage.objects.create(gallery=gallery, image_url=url)
    return gallery


def create_loewen_finished_events(prod, user):
    """~13 events for the finished, PUBLISHED 2024-25 organic walnut season."""
    by = "Leonard Loewen"

    # 0: Soil Test
    SoilManagementEvent.objects.create(
        history=prod,
        index=0,
        date=_dt(2024, 11, 12),
        description=(
            "Annual soil health test across the walnut orchard. Years of sheep "
            "grazing and cover cropping show in the numbers: organic matter at "
            "3.6% and a healthy, biologically active soil."
        ),
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.SOIL_TEST,
        name="Annual Soil Health Test",
        soil_ph=Decimal("6.80"),
        organic_matter_percentage=Decimal("3.60"),
        soil_texture="clay_loam",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        test_results={"ph": 6.8, "organic_matter_pct": 3.6, "lab": "A&L Western Laboratories"},
        album=_album("soil_test"),
    )

    # 1: Cover Crop
    SoilManagementEvent.objects.create(
        history=prod,
        index=1,
        date=_dt(2024, 11, 20),
        description=(
            "Planted a multi-species cover crop (legumes, grasses, brassicas) "
            "between every walnut row. Kept as a living two-foot floor through "
            "spring to fix nitrogen, feed soil biology, and host beneficial insects."
        ),
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.COVER_CROP,
        name="Multi-Species Cover Crop",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        amendment_type="Legume + grass + brassica cover crop seed",
        equipment_used="No-till drill",
        extra_data={"cover_crop_species": "legumes, grasses, brassicas"},
        album=_album("cover_crop"),
    )

    # 2: Sheep Grazing  -> practice_summary "integrated_grazing"
    SoilManagementEvent.objects.create(
        history=prod,
        index=2,
        date=_dt(2024, 12, 10),
        description=(
            "Sheep grazed the orchard floor through winter and early spring, "
            "managing the cover crop and weeds and returning nutrients directly "
            "to the soil. No mowing, no herbicide."
        ),
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.GRAZING,
        name="Integrated Sheep Grazing",
        animal_type="sheep",
        grazing_duration_days=52,
        area_covered=Decimal("44.52"),
        area_unit="ha",
        extra_data={"shepherd": "Roo Loewen", "method": "rotational grazing under canopy"},
        album=_album("grazing"),
    )

    # 3: On-farm Compost -> practice_summary "on_farm_compost"
    SoilManagementEvent.objects.create(
        history=prod,
        index=3,
        date=_dt(2025, 2, 15),
        description=(
            "Applied on-farm compost made from orchard prunings and cover-crop "
            "residue. Windrows held at temperature and turned through the cycle "
            "before application around the tree rows."
        ),
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.COMPOSTING,
        name="On-Farm Compost Application",
        compost_method="windrow",
        compost_peak_temp_f=Decimal("150.0"),
        compost_duration_days_at_temp=20,
        compost_turning_count=6,
        area_covered=Decimal("44.52"),
        area_unit="ha",
        album=_album("orchard"),
    )

    # 4: Habitat (hedgerows / insectary) -> practice_summary "habitat_development"
    SoilManagementEvent.objects.create(
        history=prod,
        index=4,
        date=_dt(2025, 3, 1),
        description=(
            "Maintained hedgerows and flowering insectary strips along orchard "
            "edges that host beneficial insects and birds. This living habitat "
            "is the backbone of our no-spray pest management."
        ),
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.HABITAT_DEVELOPMENT,
        name="Hedgerows & Insectary Habitat",
        habitat_type="Hedgerows and flowering insectary strips",
        habitat_install_date=date(2016, 3, 1),
        area_covered=Decimal("44.52"),
        area_unit="ha",
        album=_album("habitat"),
    )

    # 5: Nesting / shelter (owl & songbird boxes) -> practice_summary "nesting_shelter"
    SoilManagementEvent.objects.create(
        history=prod,
        index=5,
        date=_dt(2025, 3, 5),
        description=(
            "Owl and songbird nest boxes throughout the orchard support natural "
            "rodent and insect control. The birds are part of how this farm works "
            "without synthetic sprays."
        ),
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.NESTING_SHELTER,
        name="Owl & Songbird Nest Boxes",
        habitat_type="Owl and songbird nest boxes",
        habitat_structure_count=14,
        habitat_install_date=date(2016, 3, 5),
        area_covered=Decimal("44.52"),
        area_unit="ha",
        album=_album("habitat"),
    )

    # 6: Pest Management — beneficials, NO spray
    PestManagementEvent.objects.create(
        history=prod,
        index=6,
        date=_dt(2025, 6, 5),
        description=(
            "Season-long monitoring for walnut pests with a beneficial-insect and "
            "bird-driven approach. Pressure stayed low; no chemical spray was "
            "needed or applied."
        ),
        created_by=user,
        performed_by=by,
        type=PestManagementEvent.IPM_IMPLEMENTATION,
        pest_species="Codling moth, walnut husk fly (monitored)",
        pest_pressure_level="Low",
        action_threshold_met=False,
        beneficial_insects_used="yes",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        ipm_strategy=(
            "Habitat-based biological control (beneficial insects + birds from "
            "hedgerows and nest boxes), trap monitoring, and sanitation. No "
            "synthetic insecticides used."
        ),
        extra_data={"name": "No-Spray IPM Program", "sprays_applied": 0},
        album=_album("habitat"),
    )

    # 7: Irrigation — SUMMARY / aggregate event (summary-event flow)
    ProductionEvent.objects.create(
        history=prod,
        index=7,
        date=_dt(2025, 7, 1),
        description=(
            "Season irrigation for the walnut orchard, summarized: 9 irrigation "
            "sets from May through September drawing on the on-farm well, "
            "scheduled to soil moisture."
        ),
        created_by=user,
        performed_by=by,
        type=ProductionEvent.IRRIGATION,
        name="Season Irrigation (summary)",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        water_source="well_groundwater",
        irrigation_method="micro_sprinkler",
        production_efficiency="high",
        extra_data={
            "is_summary": True,
            "date_start": "2025-05-01",
            "date_end": "2025-09-15",
            "event_count": 9,
            "water_volume_total": 22000000,
            "water_volume_unit": "gallons",
            "scheduling_method": "Soil moisture monitoring",
        },
        album=_album("orchard"),
    )

    # 8: Pruning
    ProductionEvent.objects.create(
        history=prod,
        index=8,
        date=_dt(2025, 1, 20),
        description=(
            "Dormant pruning of the walnut trees. Prunings were chipped and "
            "returned to the row middles as mulch for the soil."
        ),
        created_by=user,
        performed_by=by,
        type=ProductionEvent.PRUNING,
        name="Dormant Pruning",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        fuel_consumed=Decimal("35.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_type="tractor",
        equipment_hours=Decimal("48.00"),
        growth_stage="dormant",
        album=_album("orchard"),
    )

    # 9: Harvest
    ProductionEvent.objects.create(
        history=prod,
        index=9,
        date=_dt(2025, 9, 25),
        description=(
            "Mechanical walnut harvest — shake, sweep, and pickup. Clean, "
            "high-quality organic crop off a living-floor orchard."
        ),
        created_by=user,
        performed_by=by,
        type=ProductionEvent.HARVESTING,
        name="Walnut Harvest",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        yield_quantity=Decimal("180000.00"),
        yield_unit="kg",
        harvest_quality_grade="grade_a",
        fuel_consumed=Decimal("60.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_type="tractor",
        equipment_hours=Decimal("40.00"),
        growth_stage="harvest_ready",
        album=_album("harvest"),
    )

    # 9b: Post-harvest processing — on-farm hulling/drying + dedicated organic cold
    # storage (NOP 7 CFR 205.272 commingling prevention; storage = FSMA-style KDE).
    ProductionEvent.objects.create(
        history=prod,
        index=11,
        date=_dt(2025, 10, 5),
        description=(
            "On-farm hulling and drying of the walnut harvest, then transfer to "
            "dedicated organic cold storage. Walnuts dried to ~8% kernel moisture; "
            "the lot is kept on labelled organic bins with no commingling with any "
            "conventional crop. All handling equipment is dedicated organic."
        ),
        created_by=user,
        performed_by=by,
        type=ProductionEvent.POST_HARVEST_PROCESSING,
        name="Hulling, Drying & Storage",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        storage_location="On-farm dryer → Organic Cooler 2 (Bin OR-WAL-2025)",
        storage_temperature_f=Decimal("38.0"),
        album=_album("harvest"),
    )

    # 10: Organic-approved fertility input (NO synthetic) — supplier chain for clean audit
    # Link the OMRI-listed fish/seaweed input to its catalog record so the audit
    # export's OMRI verification + OSP-approval cross-check resolve it (not just
    # "self-reported"). The OSP approval is wired in _loewen_base.create_loewen_base.
    neptune_omri = (
        OMRIProduct.objects.filter(product_name__icontains="neptune").filter(product_name__icontains="fish").first()
    )
    ChemicalEvent.objects.create(
        history=prod,
        index=10,
        date=_dt(2025, 4, 10),
        description=(
            "Foliar application of an OMRI-listed organic fish-and-seaweed fertilizer "
            "to support nut fill. The only purchased input of the season — fertility "
            "is primarily from grazing, cover crops, and compost."
        ),
        created_by=user,
        performed_by=by,
        type=ChemicalEvent.FERTILIZER,
        chemical_subtype="organic",
        name="Organic Foliar Nutrition",
        commercial_name="Neptune's Harvest Fish & Seaweed 2-3-1 (OMRI listed)",
        concentration="2-3-1",
        volume="420",
        volume_unit="L",
        area="44.52",
        area_unit="ha",
        way_of_application="foliar",
        application_method_structured="foliar",
        organic_approved="omri_listed",
        omri_product=neptune_omri,
        supplier_name="Cal-West Ag Supply",
        purchase_date=date(2025, 4, 2),
        purchase_invoice="CWAS-2025-0417",
        application_fuel_type="diesel",
        application_fuel_consumed=Decimal("8.00"),
        application_fuel_unit="gal",
        extra_data={"active_ingredient": "Fish + seaweed", "n_source": "organic"},
        album=_album("orchard"),
    )

    # 11: Certification (timeline entry)
    BusinessEvent.objects.create(
        history=prod,
        index=11,
        date=_dt(2025, 5, 1),
        description=(
            "Annual organic certification maintained: USDA Organic through CCOF and "
            "Real Organic Project. Inspection records on file."
        ),
        created_by=user,
        performed_by=by,
        type=BusinessEvent.CERTIFICATION,
        name="Organic Certification (USDA/CCOF + Real Organic Project)",
        business_type="certification",
        certification_type="organic_usda",
        verification_status="verified",
        verified_certifier_name="CCOF Certification Services, LLC",
        extra_data={"programs": ["USDA Organic (CCOF)", "Real Organic Project"]},
    )

    # 12: Korean Organic export sale (downstream traceability)
    BusinessEvent.objects.create(
        history=prod,
        index=12,
        date=_dt(2025, 11, 1),
        description=(
            "Sale of certified organic walnuts under the Korean Organic program "
            "(export). Organic identity preserved on invoice and shipping records."
        ),
        created_by=user,
        performed_by=by,
        type=BusinessEvent.COMPLIANCE,
        name="Korean Organic Export Sale",
        business_type="sale",
        extra_data={
            "buyer": "Korean Organic Program buyer (export)",
            "program": "Korean Organic equivalence",
            "bill_of_lading": "BOL-LOEWEN-2025-1101",
            "purchase_order": "PO-KR-2025-0442",
            "invoice_number": "INV-LOEWEN-2025-1101",
            "organic_on_invoice": True,
        },
    )

    # 13: Spring sheep grazing rotation -> reinforces signature practice (grazing count 2)
    SoilManagementEvent.objects.create(
        history=prod,
        index=13,
        date=_dt(2025, 4, 5),
        description=(
            "Second sheep rotation through the orchard in spring, grazing down the "
            "cover crop before bloom. The flock turns the living floor into fertility "
            "and keeps the rows clean without a single pass of a mower or sprayer."
        ),
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.GRAZING,
        name="Spring Sheep Rotation",
        animal_type="sheep",
        grazing_duration_days=38,
        area_covered=Decimal("44.52"),
        area_unit="ha",
        extra_data={"shepherd": "Roo Loewen", "method": "rotational grazing, spring paddocks"},
        album=_album("grazing"),
    )

    # 14: Beneficial release + owl-box monitoring -> the "bugs galore and birds" no-spray proof
    PestManagementEvent.objects.create(
        history=prod,
        index=14,
        date=_dt(2025, 5, 20),
        description=(
            "Released beneficial insects and checked the owl and songbird boxes across "
            "the orchard. The hedgerows are full of lacewings and lady beetles and the "
            "boxes are active. This living control is why the season ran start to finish "
            "with zero synthetic sprays."
        ),
        created_by=user,
        performed_by=by,
        type=PestManagementEvent.BENEFICIAL_RELEASE,
        pest_species="Aphids, mites (managed biologically)",
        pest_pressure_level="Low",
        action_threshold_met=False,
        beneficial_insects_used="yes",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        ipm_strategy=(
            "Biological control from hedgerow insectary and nest-box birds + targeted "
            "beneficial releases (lacewings, lady beetles). No synthetic insecticide used."
        ),
        extra_data={
            "name": "Beneficial Release & Owl-Box Monitoring",
            "beneficials_released": ["lacewings", "lady beetles"],
            "nest_boxes_active": 14,
            "sprays_applied": 0,
        },
        album=_album("wildlife"),
    )

    # 15: Summer heat managed by the living floor -> resilience story (Central Valley real)
    WeatherEvent.objects.create(
        history=prod,
        index=15,
        date=_dt(2025, 7, 22),
        description=(
            "A Central Valley summer heat run with several days above 40C (104F). The "
            "grazed cover and shaded, living orchard floor held soil moisture; irrigation "
            "was adjusted to soil-moisture readings and the trees came through without stress."
        ),
        created_by=user,
        performed_by=by,
        type=WeatherEvent.HIGH_TEMPERATURE,
        observation=(
            "Peak ~42C. Living floor and cover crop residue buffered soil temperature and "
            "moisture; no heat stress or crop loss. Irrigation matched to sensor readings."
        ),
        extra_data={
            "event_name": "Central Valley Summer Heat",
            "highest_temperature": "42",
            # Value is in Celsius (matches "Peak ~42C" in the notes). Without this
            # the export defaults the unit to °F and renders "42°F" (winter cold).
            "temperature_unit": "C",
            "duration_days": 4,
            "impact": "No crop stress; living floor buffered soil moisture",
        },
        album=_album("orchard"),
    )

    # Authentic certifier-facing audit data for the new export sections
    # (nitrogen source, wholesale sales, benign OSP change notification).
    apply_loewen_audit_fields(prod)

    return 16


def create_loewen_current_events(prod, user):
    """~3 early events for the in-progress 2025-26 season (unpublished)."""
    by = "Leonard Loewen"

    SoilManagementEvent.objects.create(
        history=prod,
        index=0,
        date=_dt(2025, 11, 18),
        description="Planted the multi-species cover crop between rows for the new season.",
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.COVER_CROP,
        name="Fall Cover Crop",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        amendment_type="Legume + grass + brassica cover crop seed",
        extra_data={"cover_crop_species": "legumes, grasses, brassicas"},
        album=_album("cover_crop"),
    )
    SoilManagementEvent.objects.create(
        history=prod,
        index=1,
        date=_dt(2025, 12, 8),
        description="Sheep moved into the orchard to graze the new cover crop.",
        created_by=user,
        performed_by=by,
        type=SoilManagementEvent.GRAZING,
        name="Winter Sheep Grazing",
        animal_type="sheep",
        grazing_duration_days=20,
        area_covered=Decimal("44.52"),
        area_unit="ha",
        extra_data={"shepherd": "Roo Loewen"},
        album=_album("grazing"),
    )
    ProductionEvent.objects.create(
        history=prod,
        index=2,
        date=_dt(2026, 1, 15),
        description="Dormant pruning underway; prunings chipped back to the row middles.",
        created_by=user,
        performed_by=by,
        type=ProductionEvent.PRUNING,
        name="Dormant Pruning",
        area_covered=Decimal("44.52"),
        area_unit="ha",
        fuel_consumed=Decimal("30.00"),
        fuel_unit="gal",
        fuel_type="diesel",
        equipment_type="tractor",
        equipment_hours=Decimal("40.00"),
        growth_stage="dormant",
        album=_album("orchard"),
    )

    return 3
