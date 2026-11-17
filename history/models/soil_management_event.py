"""Soil management activities."""

from django.core.exceptions import ValidationError
from django.db import models

from carbon.choices import FUEL_TYPES
from common.field_registry import (
    ORGANIC_APPROVED,
    PRODUCTION_EFFICIENCY,
    UNIT_AMENDMENT,
    UNIT_AREA,
    UNIT_DISTANCE,
    UNIT_FUEL,
)

from .common_event import CommonEvent


class SoilManagementEvent(CommonEvent):
    """Events related to soil testing, amendments, and organic matter management"""

    # Soil management event types
    SOIL_TEST = "ST"
    PH_ADJUSTMENT = "PA"
    ORGANIC_MATTER = "OM"
    COVER_CROP = "CC"
    TILLAGE = "TI"
    COMPOSTING = "CO"
    GRAZING = "GR"
    # Biodiversity / habitat (GTM-v3): documented habitat PRACTICES — facts only, never a score.
    HABITAT_DEVELOPMENT = "HD"  # planted/established habitat (hedgerow, insectary, riparian, living floor)
    NESTING_SHELTER = "NS"  # installed wildlife structures (owl/raptor/bee/bat boxes, insect hotel)
    # §E-2 — Lab analysis of any sampled matrix. ONE subtype with a `sample_matrix` enum rather
    # than one subtype per matrix: the record a certifier reads is identical (lab, sample id,
    # report date, results); only what was sampled differs. UC Davis 2024 organic-almond study:
    # leaf samples in July at 1/20 ac, hull samples at harvest at 1/40 ac, four compost samples
    # per delivery, soil every other year at three depths.
    LAB_ANALYSIS = "LA"

    SOIL_TYPE_CHOICES = [
        (SOIL_TEST, "Soil Test"),
        (PH_ADJUSTMENT, "pH Adjustment"),
        (ORGANIC_MATTER, "Organic Matter Addition"),
        (COVER_CROP, "Cover Crop"),
        (TILLAGE, "Tillage"),
        (COMPOSTING, "Composting"),
        (GRAZING, "Grazing Management"),
        (HABITAT_DEVELOPMENT, "Habitat Development"),
        (NESTING_SHELTER, "Nesting / Shelter Structures"),
        (LAB_ANALYSIS, "Lab Analysis"),
    ]

    SAMPLE_MATRIX_CHOICES = [
        ("soil", "Soil"),
        ("leaf", "Leaf tissue"),
        ("petiole", "Petiole"),
        ("hull", "Hull"),
        ("compost", "Compost"),
        ("water", "Irrigation water"),
    ]

    type = models.CharField(max_length=2, choices=SOIL_TYPE_CHOICES, default=SOIL_TEST)
    soil_ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    organic_matter_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amendment_type = models.CharField(max_length=100, blank=True)
    amendment_amount = models.CharField(max_length=100, blank=True)
    # Specific product identity for the amendment. amendment_type is only a generic
    # category (compost/manure/gypsum/...); the NOP/CCOF input record (7 CFR 205.203 /
    # CCOF Input Record) needs the actual product + manufacturer.
    amendment_product_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Specific commercial product name of the amendment, e.g. Malibu Compost Bu's Blend.",
    )
    amendment_manufacturer = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Who MAKES the product (label attribution). Not who sold it — see amendment_supplier_name.",
    )

    # --- Amendment purchase traceability (7 CFR 205.103(b)(1)-(2)) -------------------------
    #
    # 🔴 2026-08-16, CCOF grower-checklist audit. CCOF item 1 names "fertilizer, compost, soil
    # amendments, planting mixes" in one breath and asks for receipts. `ChemicalEvent` has
    # carried supplier / purchase date / invoice / quantity / lot since Sprint 3; this model
    # carried a product name and a manufacturer and nothing else. On a certified organic
    # orchard compost is routinely the largest purchased input by tonnage AND by dollar, so
    # the one input a grower most needs to trace was the one input with no purchase record.
    #
    # The consequence was not theoretical: the packet's mass-balance section builds its
    # "Inputs Purchased" table from ChemicalEvent alone and prints
    # "[REVIEW] Mass balance cannot be reconciled" when it finds nothing — a flag a
    # compost-fed operation could not clear no matter how carefully it logged.
    #
    # Field names mirror ChemicalEvent's deliberately (`*_supplier_name`, `*_purchase_date`,
    # `*_purchase_invoice`, `*_lot_number`) so the export, the Supplier List workbook and the
    # § 11 evidence lambdas can treat the two models the same way.
    #
    # ⛔ Never seed these from a template. A template that fills in a supplier and an invoice
    # number writes a purchase that did not happen into an audit file (see the Smart Setup
    # backdated-glyphosate incident, 2026-08-02).
    amendment_supplier_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Who the amendment was BOUGHT from — the name on the receipt (CCOF Input Record).",
    )
    amendment_purchase_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date on the purchase receipt / invoice for this amendment.",
    )
    receipt_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="soil_receipts",
        help_text="Uploaded receipt file behind amendment_purchase_invoice (see ChemicalEvent.receipt_document).",
    )
    amendment_purchase_invoice = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Invoice or receipt number, so the packet points an inspector at the paper record.",
    )
    amendment_quantity_purchased = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Total amount bought on this invoice (for the § 205.103(b)(2) mass balance).",
    )
    amendment_quantity_purchased_unit = models.CharField(
        max_length=20,
        choices=UNIT_AMENDMENT,
        blank=True,
        null=True,
        help_text="Unit for the purchased quantity. Same vocabulary as amendment_amount_unit.",
    )
    amendment_lot_number = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        help_text="Manufacturer lot / batch number from the bag, tote or delivery ticket.",
    )

    test_results = models.JSONField(null=True, blank=True)  # Store complex test data
    # §E-2 — WHAT was sampled. The results themselves stay in `test_results` (where the soil-test
    # form has always written them, so historical ST rows keep working); the read serializer
    # flattens that JSON into named fields so the display registry and the PDF can reach them.
    sample_matrix = models.CharField(
        max_length=20,
        choices=SAMPLE_MATRIX_CHOICES,
        blank=True,
        null=True,
        help_text="Material submitted to the lab (LA subtype): soil, leaf, petiole, hull, compost or water.",
    )
    carbon_sequestration_potential = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    # The farmer's own words, kept apart from `description`. `description` is NOT NULL and is
    # written by the 328+ AI templates as well as by hand, so it cannot be quoted to shoppers as
    # a grower's voice. Five of the seven event models already had this column; soil and pest did
    # not, which is why a cover-crop or trap-monitoring note could never reach the consumer card.
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Biodiversity / habitat fields (for HD / NS subtypes). Facts only — free-text species/notes
    # live in extra_data (mirrors cover_crop_species); the living-floor / bugs / birds proof rides
    # on the event photo album + an optional wildlife_observed note. No counts beyond structures, no score.
    habitat_type = models.CharField(
        max_length=40,
        blank=True,
        null=True,
        help_text="Habitat practice (HD) or structure (NS) — e.g. hedgerow, insectary_strip, barn_owl_box",
    )
    habitat_structure_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of structures installed (NS subtype, e.g. 6 barn-owl boxes)",
    )
    habitat_install_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "When the habitat was established (HD) or the structures installed (NS). "
            "Drives the consumer maturity story (an 8-year-old hedgerow vs a new one) and "
            "gives a certifier a date for the practice."
        ),
    )

    # Grazing management fields (for GR subtype)
    animal_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Type of grazing animal (e.g., sheep, goats, cattle)",
    )
    animal_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of animals used for grazing",
    )
    grazing_duration_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration of grazing period in days",
    )
    grazing_purpose = models.CharField(
        max_length=50,
        choices=[
            ("weed_control", "Weed Control"),
            ("cover_crop", "Cover Crop Termination"),
            ("soil_health", "Soil Health"),
            ("vegetation_management", "Vegetation Management"),
        ],
        blank=True,
        null=True,
        help_text="Primary purpose of the grazing activity",
    )

    # Numeric amendment field to replace legacy string field
    amendment_amount_numeric = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amendment amount in numeric format (replaces legacy string field)",
    )
    amendment_amount_unit = models.CharField(
        max_length=10,
        choices=UNIT_AMENDMENT,
        default="kg",
        blank=True,
        help_text="Unit for amendment_amount_numeric",
    )

    # Standardized fields for carbon calculations (matching ProductionEvent pattern)
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    area_covered = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Area covered in numeric format"
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed during soil management activity",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit",
    )
    fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for EPA emission factor calculation",
    )
    equipment_hours = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Equipment operating hours"
    )
    transportation_distance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Transportation distance for logistics emissions",
    )
    transportation_unit = models.CharField(
        max_length=10,
        choices=UNIT_DISTANCE,
        default="miles",
        blank=True,
        help_text="Transportation unit",
    )
    production_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
        default="normal",
        blank=True,
        help_text="Production efficiency rating for carbon scoring",
    )

    # Additional soil management fields for comprehensive data capture
    working_depth = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Working depth for tillage or soil operations"
    )
    depth_unit = models.CharField(
        max_length=10,
        choices=[
            ("cm", "Centimeters"),
            ("inches", "Inches"),
            ("m", "Meters"),
        ],
        default="cm",
        blank=True,
        help_text="Depth measurement unit",
    )
    soil_texture = models.CharField(
        max_length=50,
        choices=[
            ("clay", "Clay"),
            ("clay_loam", "Clay Loam"),
            ("loam", "Loam"),
            ("sandy_loam", "Sandy Loam"),
            ("sand", "Sand"),
            ("silt", "Silt"),
            ("silt_loam", "Silt Loam"),
        ],
        blank=True,
        null=True,
        help_text="Soil texture classification",
    )
    soil_moisture = models.CharField(
        max_length=20,
        choices=[
            ("dry", "Dry"),
            ("moderate", "Moderate"),
            ("moist", "Moist"),
            ("wet", "Wet"),
        ],
        blank=True,
        null=True,
        help_text="Soil moisture condition during operation",
    )
    weather_conditions = models.CharField(
        max_length=200, blank=True, null=True, help_text="Weather conditions during soil management"
    )
    temperature_range = models.CharField(
        max_length=50, blank=True, null=True, help_text="Temperature range during operation"
    )
    equipment_used = models.CharField(
        max_length=200, blank=True, null=True, help_text="Equipment used for soil management operation"
    )

    # NOP Compliance: Amendment Organic Approval (7 CFR 205.203(b))
    amendment_organic_approved = models.CharField(
        max_length=20,
        choices=ORGANIC_APPROVED,
        blank=True,
        null=True,
        help_text=(
            "The organic basis the operator recorded for this amendment/input (7 CFR 205.203(b)); "
            "their own statement, not an approval"
        ),
    )

    # Nitrogen content of the amendment, % by weight AS APPLIED.
    #
    # Two things depend on this and both were silently incomplete without it:
    #
    #  1. CARBON. Post-application field N2O depends on the nitrogen applied, whatever
    #     carried it. ChemicalEvent fertilisers declare N via nitrogen_percentage, but soil
    #     amendments had no N field at all — so on an organic orchard, where compost is
    #     usually the LARGEST nitrogen source, the biggest contributor to field N2O was
    #     counted as zero. (Pilot: 170 t of compost at ~1% N is ~1,540 kg N, roughly 25x
    #     the nitrogen in the season's fertigation.)
    #
    #  2. CALIFORNIA ILRP. Every irrigated CA grower files an Irrigation & Nitrogen
    #     Management Plan summary reporting total nitrogen APPLIED from all sources and
    #     nitrogen REMOVED in the harvested crop. "All sources" includes compost and
    #     manure, so a total built only from ChemicalEvent under-reports the filing.
    #
    # BASIS MATTERS — read this before changing the help text.
    #
    # Compost analyses report N on BOTH an "as-is / as-received" basis and a "dry weight"
    # basis, and compost is typically 30-50% moisture, so the two differ by roughly 2x.
    # The amendment_amount a grower enters is the delivered (wet) tonnage off the weigh
    # ticket, so the N% must be on the SAME as-received basis or the computed kg of N is
    # out by that factor. The UI says so explicitly rather than leaving it to be guessed.
    #
    # Typical DRY-weight values (WSU Tree Fruit, "Compost Considerations"): green/yard
    # waste 0.8-2.0%, manure-based 1-3% (avg ~1.5%). At ~40% moisture those correspond to
    # roughly 0.5-1.2% and 0.6-1.8% AS RECEIVED, which is what the help text quotes.
    amendment_nitrogen_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Nitrogen content of the amendment, % by weight ON THE SAME AS-RECEIVED (wet) "
            "BASIS as the tonnage entered above — use the 'as is' column of the supplier's "
            "analysis, not the 'dry weight' column (they differ by ~2x). Drives field N2O "
            "and the CA ILRP total-nitrogen-applied figure."
        ),
    )

    # NOP Compliance: Compost Temperature Tracking (7 CFR 205.203(c)(2))
    # Required for on-farm composting: must reach 131-170°F; windrow 15+ days @temp,
    # static aerated / in-vessel 3+ days @temp.
    compost_peak_temp_f = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Peak temperature reached during composting in °F (must reach 131-170°F per 7 CFR 205.203(c)(2))",
    )
    compost_duration_days_at_temp = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=(
            "Number of days compost maintained required temperature "
            "(windrow: 15+ days; static aerated / in-vessel: 3+ days per 7 CFR 205.203(c)(2))"
        ),
    )
    compost_turning_count = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Number of times compost was turned (minimum 5 turnings for windrow per 7 CFR 205.203(c)(2))",
    )

    # NOP Compliance: Initial C:N ratio + method (7 CFR 205.203(c)(2))
    # Regulatory: a pile with C:N outside 25:1-40:1 at start of composting
    # does NOT satisfy § 205.203(c)(2) and must be treated as raw manure
    # under (c)(1) 90/120-day intervals.
    COMPOST_METHOD_WINDROW = "windrow"
    COMPOST_METHOD_STATIC_AERATED = "static_aerated"
    COMPOST_METHOD_IN_VESSEL = "in_vessel"
    COMPOST_METHOD_CHOICES = [
        (COMPOST_METHOD_WINDROW, "Windrow (turned, open air)"),
        (COMPOST_METHOD_STATIC_AERATED, "Static Aerated Pile"),
        (COMPOST_METHOD_IN_VESSEL, "In-Vessel"),
    ]
    compost_method = models.CharField(
        max_length=20,
        choices=COMPOST_METHOD_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Compost method (7 CFR 205.203(c)(2)). Windrow requires 15+ days at "
            "131–170°F with 5+ turnings; static aerated / in-vessel require 3+ days "
            "at 131–170°F."
        ),
    )
    compost_initial_cn_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Initial carbon-to-nitrogen ratio (C:N) of the compost feedstock. "
            "7 CFR 205.203(c)(2) requires 25:1–40:1 at the start of composting. "
            "Outside this range, the pile must be handled as raw manure under (c)(1)."
        ),
    )
    # F24 (2026-06): complete the NOP 5021 compost record. A single peak temp + day count is not a
    # monitoring log — a certifier needs the feedstock and the actual temperature readings over time.
    compost_feedstock = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text="Feedstock composition/source (e.g., 'horse manure + straw + green waste') — NOP 5021",
    )
    compost_temperature_log = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Temperature-monitoring readings over the composting period (date · temp · turned?) — "
            "the NOP 5021 monitoring log. One reading per line."
        ),
    )
    # USDA's Compost Production Record heads every sheet with the batch identity and how the
    # temperature was taken. Without them a § 205.203(c)(2) log is unattributable: an inspector
    # holding two piles and one temperature series cannot tell which pile it describes, and a
    # reading with no stated depth or instrument cannot be reproduced.
    compost_unit_id = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="Compost pile, windrow or unit ID this batch's readings belong to (NOP 5021).",
    )
    compost_temp_reading_method = models.CharField(
        max_length=160,
        blank=True,
        null=True,
        help_text=(
            "Where and how the temperature was taken — e.g. 'probe at 36 in depth, mid-windrow'. "
            "USDA's form asks for the location AND method because a surface reading and a core "
            "reading on the same pile disagree."
        ),
    )

    # NOP Compliance: Raw Manure Harvest Interval (7 CFR 205.203(c)(1))
    # (c)(1) governs raw animal manure pre-harvest intervals; composted materials
    # live under (c)(2). Do not confuse the citations — an inspector flags either.
    # The choice is the wait the farm keeps, read as a floor: "120" is compliant for any crop,
    # "90" only where the edible part does not touch the soil. The labels say "at least" so a
    # tree crop kept at 120 days does not print as a claim that its fruit touches the soil.
    MANURE_INTERVAL_CHOICES = [
        ("120", "At least 120 days (required when the edible part touches the soil)"),
        ("90", "At least 90 days (only when the edible part does not touch the soil)"),
        ("na", "N/A — composted manure or no manure applied"),
    ]
    manure_harvest_interval = models.CharField(
        max_length=5,
        choices=MANURE_INTERVAL_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "The wait the farm keeps between raw manure and harvest, read as a floor (7 CFR 205.203(c)(1)): "
            "at least 120 days when the edible part touches the soil, at least 90 days otherwise"
        ),
    )
    manure_application_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date raw manure was applied (used to calculate earliest safe harvest date)",
    )
    manure_harvest_date_planned = models.DateField(
        blank=True,
        null=True,
        help_text=(
            "Harvest date the grower planned when the manure went on. USDA's crop "
            "documentation form records estimated AND actual harvest dates side by side; the "
            "actual date is the harvest event itself, so this is the estimate."
        ),
    )

    # NOP 5006 — Processed Animal Manures in Organic Crop Production.
    # A third manure class sits between raw (c)(1) and composted (c)(2):
    # manure PROCESSED to reduce human pathogens (heat-dried, pelletized,
    # thermophilic PFRP) that does NOT meet the (c)(2) compost definition is
    # still exempt from the (c)(1) 90/120-day raw interval. The exemption is
    # granted only when DOCUMENTED (processing temperature and/or an OMRI/
    # supplier attestation); undocumented "processed" manure is handled as raw.
    MANURE_TREATMENT_CHOICES = [
        ("raw", "Raw / uncomposted animal manure — 90/120-day interval applies (c)(1)"),
        ("composted", "Composted per 7 CFR 205.203(c)(2) — no interval"),
        ("processed_5006", "Processed to reduce pathogens per NOP 5006 — no interval"),
    ]
    manure_treatment = models.CharField(
        max_length=16,
        choices=MANURE_TREATMENT_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Animal-manure processing class. 'processed_5006' (heat-dried / "
            "pelletized / PFRP) exempts the crop from the raw-manure harvest "
            "interval when supported by a processing temperature or an OMRI / "
            "supplier attestation (NOP 5006)."
        ),
    )
    processed_manure_temp_f = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Peak processing temperature (°F) for NOP 5006 processed manure (pathogen reduction).",
    )
    processed_manure_attestation = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text=(
            "Supplier / OMRI attestation for NOP 5006 processed manure "
            "(e.g., 'OMRI-listed heat-processed poultry pellets, PFRP') — the "
            "documentation basis for the raw-interval exemption."
        ),
    )

    # ------------------------------------------------------------------
    # USDA Manure Application / Food Crop Harvest Interval Record (form #9)
    # ------------------------------------------------------------------
    # The published form carries two columns Trazo had no home for:
    #
    #   "How Applied / Incorporated"     e.g. "Manure spreader disk in"
    #   "Manure Type, Form and Source"   e.g. "Chicken, dry, on farm"
    #
    # USDA writes the second as ONE free-text column, but it is plainly three facets, and
    # storing three enums lets the packet reconstruct "Chicken, dry, on farm" while keeping
    # the data queryable. Splitting is safe here in a way it was NOT for
    # `buffer_disposition_quantity` (kept free text): a bin count has no closed vocabulary,
    # whereas the animal, the form and on/off-farm all do.
    #
    # None of these are added to `record_completeness`. The forms are OPTIONAL under
    # § 205.103 — an operation may keep records in any format — and no CFR paragraph
    # enumerates these facets. Requiring them would be Trazo inventing a rule, the same
    # call already made for #7 `application_purpose`.
    MANURE_APPLICATION_METHOD_CHOICES = [
        ("broadcast_incorporated", "Broadcast, incorporated (disked or tilled in)"),
        ("broadcast_surface", "Broadcast, left on the surface"),
        ("injected", "Injected below the surface"),
        ("banded", "Banded or side-dressed"),
        ("fertigation", "Applied through irrigation (fertigation)"),
        ("top_dressed", "Top-dressed / mulched around plantings"),
        ("other", "Other — described in the notes"),
    ]
    manure_application_method = models.CharField(
        max_length=32,
        choices=MANURE_APPLICATION_METHOD_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "How the manure was applied and whether it was incorporated — USDA's "
            '"How Applied / Incorporated" column (example: "Manure spreader disk in"). '
            "Recorded because the form asks; it does NOT change the 90/120-day interval, "
            "which turns on edible-portion soil contact under § 205.203(c)(1)(ii)-(iii)."
        ),
    )
    MANURE_ANIMAL_SOURCE_CHOICES = [
        ("poultry", "Poultry (chicken, turkey, duck)"),
        ("cattle", "Cattle / dairy"),
        ("horse", "Horse"),
        ("sheep_goat", "Sheep or goat"),
        ("swine", "Swine"),
        ("rabbit", "Rabbit"),
        ("mixed", "Mixed livestock"),
        ("other", "Other — described in the notes"),
    ]
    manure_animal_source = models.CharField(
        max_length=16,
        choices=MANURE_ANIMAL_SOURCE_CHOICES,
        blank=True,
        null=True,
        help_text='Animal the manure came from — the "Chicken" in USDA\'s "Chicken, dry, on farm".',
    )
    MANURE_FORM_CHOICES = [
        ("dry", "Dry / solid"),
        ("bedded_pack", "Bedded pack (manure with bedding)"),
        ("slurry", "Slurry"),
        ("liquid", "Liquid"),
        ("pelletized", "Pelletized or granulated"),
    ]
    manure_form = models.CharField(
        max_length=16,
        choices=MANURE_FORM_CHOICES,
        blank=True,
        null=True,
        help_text='Physical form as applied — the "dry" in USDA\'s "Chicken, dry, on farm".',
    )
    MANURE_ORIGIN_CHOICES = [
        ("on_farm", "Produced on this operation"),
        ("off_farm", "Brought in from off the farm"),
    ]
    manure_origin = models.CharField(
        max_length=16,
        choices=MANURE_ORIGIN_CHOICES,
        blank=True,
        null=True,
        help_text=(
            'Where the manure came from — the "on farm" in USDA\'s "Chicken, dry, on farm". '
            "For off-farm manure the supplier goes in `amendment_manufacturer`; a second "
            "supplier field would be a second writer of one fact."
        ),
    )

    def manure_type_form_source_display(self):
        """USDA's single "Manure Type, Form and Source" column, rebuilt from the three facets.

        Returns "" when nothing is recorded — the caller decides whether an empty column is a
        gap, because these facets are form parity, not a § 205.103 requirement.
        """
        parts = [
            self.get_manure_animal_source_display() if self.manure_animal_source else "",
            self.get_manure_form_display() if self.manure_form else "",
            self.get_manure_origin_display() if self.manure_origin else "",
        ]
        return ", ".join(p for p in parts if p)

    # Sprint 5.1 — Drift detector (same contract as ChemicalEvent.drift_warning).
    # Populated when amendment_type does not resolve to an approved input on
    # the establishment's active OSP.
    drift_warning = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Drift detector payload (7 CFR 205.400(f)(2)). Non-null when this "
            "event's amendment is not in the active OSP's approved_inputs — "
            "treated as an operation change requiring certifier notification."
        ),
    )

    def clean(self):
        """Model-level validation for soil management event values and business logic"""
        errors = {}

        # Validate area_covered - must be positive for most operations
        if self.area_covered is not None and self.area_covered <= 0:
            errors["area_covered"] = "Area covered must be greater than 0"

        # Validate transportation_distance - cannot be negative
        if self.transportation_distance is not None and self.transportation_distance < 0:
            errors["transportation_distance"] = "Transportation distance cannot be negative"

        # Validate equipment_hours - cannot be negative
        if self.equipment_hours is not None and self.equipment_hours < 0:
            errors["equipment_hours"] = "Equipment hours cannot be negative"

        # Validate fuel_consumed is non-negative
        if self.fuel_consumed is not None and self.fuel_consumed < 0:
            errors["fuel_consumed"] = "Fuel consumed cannot be negative"

        # Business logic validation: reasonable area coverage
        if self.area_covered and self.area_covered > 1000:  # More than 1000 hectares
            errors["area_covered"] = (
                f"Area coverage ({self.area_covered} {self.area_unit}) seems unusually large. Please verify."
            )

        # If fuel consumption is provided, hours operated should also be provided for accuracy
        if self.fuel_consumed and self.fuel_consumed > 0 and not self.equipment_hours:
            if "equipment_hours" not in errors:
                errors["equipment_hours"] = (
                    "Equipment hours should be provided when fuel consumption is specified for accurate carbon calculations."
                )

        # Validate reasonable fuel efficiency (basic sanity check)
        if self.fuel_consumed and self.fuel_consumed > 0 and self.equipment_hours and self.equipment_hours > 0:
            fuel_per_hour = float(self.fuel_consumed) / float(self.equipment_hours)

            # Reasonable fuel consumption: 0.5L/hr to 50L/hr (covers small pumps to large tractors)
            if fuel_per_hour > 50:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably high. Check values."
                )
            elif fuel_per_hour < 0.5:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably low. Check values."
                )

        # Grazing event validation
        if self.type == self.GRAZING:
            if self.animal_type and not self.animal_count:
                errors["animal_count"] = "Number of animals is required when animal type is specified"
            if self.animal_count and self.animal_count > 10000:
                errors["animal_count"] = f"Animal count ({self.animal_count}) seems unusually high. Please verify."
            if self.grazing_duration_days and self.grazing_duration_days > 365:
                errors["grazing_duration_days"] = (
                    f"Grazing duration ({self.grazing_duration_days} days) exceeds one year. Please verify."
                )

        # §E-2 — Lab analysis validation. A lab record whose matrix is unknown cannot support
        # anything: a certifier reading a micronutrient application needs to know the deficiency
        # was shown in LEAF tissue or in SOIL, and the two are not interchangeable. The results
        # themselves are not forced — a farmer may log the sample on the day it ships and fill in
        # the numbers when the report arrives.
        if self.type == self.LAB_ANALYSIS and not self.sample_matrix:
            errors["sample_matrix"] = (
                "Select what was sampled (soil, leaf, petiole, hull, compost or water). "
                "A lab analysis without its matrix cannot support a deficiency claim."
            )

        # Transportation efficiency check
        if self.transportation_distance and self.transportation_distance > 500:
            errors["transportation_distance"] = (
                f"Transportation distance ({self.transportation_distance} {self.transportation_unit}) is very long. Consider local processing to reduce carbon footprint."
            )

        # NOP Manure validation (7 CFR 205.203(c)(1))
        # The 90/120-day interval only applies to RAW manure. Composted (c)(2)
        # and processed (NOP 5006) manure are interval-exempt, so don't force
        # an interval selection for them.
        if (
            self.manure_application_date
            and not self.manure_harvest_interval
            and self.manure_treatment not in ("composted", "processed_5006")
        ):
            errors["manure_harvest_interval"] = (
                "Harvest interval (90 or 120 days) is required when a raw manure application date is specified."
            )

        # NOP 5006 — processed-manure consistency. An interval-exempt class
        # (processed / composted) must NOT also carry a raw 90/120-day interval:
        # an event cannot be both raw-with-interval AND processed-exempt, and that
        # contradiction reads to a certifier as reclassifying to dodge a flag.
        if self.manure_treatment in ("processed_5006", "composted") and self.manure_harvest_interval in (
            "90",
            "120",
        ):
            errors["manure_harvest_interval"] = (
                "A processed (NOP 5006) or composted (§ 205.203(c)(2)) manure event is "
                "interval-exempt and cannot also carry a raw 90/120-day interval. Set the "
                "interval to N/A, or classify the event as raw manure."
            )
        # Claiming the NOP 5006 exemption requires documenting the processing.
        if (
            self.manure_treatment == "processed_5006"
            and self.processed_manure_temp_f is None
            and not (self.processed_manure_attestation or "").strip()
        ):
            errors["manure_treatment"] = (
                "NOP 5006 processed manure requires a processing temperature or an "
                "OMRI/supplier attestation to claim the raw-interval exemption. Without "
                "documentation, classify the event as raw manure."
            )

        # NOP manure interval vs the crop's floor, 7 CFR 205.203(c)(1). The rule sets a minimum
        # ("not less than" 120 days when the edible part touches the soil, 90 when it does not),
        # so the only wrong answer is one SHORTER than the floor. Until 2026-11 this also refused
        # 120 days on a tree crop as a "mis-classification", which blocked the stricter wait a
        # certifier may ask of nuts swept from the orchard floor. One reading for every surface:
        # history/services/manure_interval.py. Unknown crop: defer to the export's check.
        if self.manure_harvest_interval in ("90", "120"):
            from history.services.manure_interval import below_minimum, below_minimum_message

            crop_type = None
            try:
                crop_type = self.history.crop_type
            except Exception:  # noqa: BLE001 — FK not populated yet during form clean()
                crop_type = None
            if crop_type is not None and below_minimum(self.manure_harvest_interval, crop_type):
                errors["manure_harvest_interval"] = below_minimum_message(crop_type)

        # NOP Composting validation (7 CFR 205.203(c)(1)+(c)(2))
        if self.type == self.COMPOSTING:
            if self.compost_peak_temp_f is not None:
                temp = float(self.compost_peak_temp_f)
                if temp < 90 or temp > 200:
                    errors["compost_peak_temp_f"] = (
                        f"Temperature ({temp}°F) seems outside reasonable range (90-200°F). Please verify."
                    )
            if self.compost_duration_days_at_temp is not None and self.compost_duration_days_at_temp > 365:
                errors["compost_duration_days_at_temp"] = "Duration at temperature exceeds one year. Please verify."
            if self.compost_turning_count is not None and self.compost_turning_count > 100:
                errors["compost_turning_count"] = "Turning count seems unusually high. Please verify."
            # § 205.203(c)(2) initial C:N must fall in 25:1–40:1 at start of composting.
            if self.compost_initial_cn_ratio is not None:
                ratio = float(self.compost_initial_cn_ratio)
                if ratio < 5 or ratio > 100:
                    errors["compost_initial_cn_ratio"] = (
                        f"Initial C:N ratio ({ratio}:1) is outside plausible feedstock range (5:1–100:1). "
                        "Please verify — typical NOP-compliant composts start at 25:1–40:1."
                    )

        if errors:
            raise ValidationError(errors)

    class Meta:
        verbose_name = "Soil Management Event"
        verbose_name_plural = "Soil Management Events"
