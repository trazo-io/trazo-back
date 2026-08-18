"""
Trazo Shared Field Registry — Backend Single Source of Truth for Enum Choices.

This module centralizes all enum choices used across event types to:
1. Eliminate duplicate definitions (e.g., FUEL_TYPES was defined in 4+ places)
2. Provide consistent values across ChemicalEvent, ProductionEvent, SoilManagementEvent,
   PestManagementEvent, EquipmentEvent, WeatherEvent, BusinessEvent, GeneralEvent
3. Serve as the backend source of truth that drf-spectacular exports to OpenAPI schema
4. Enable the frontend to generate matching TypeScript types via openapi-typescript

All choice lists follow Django's (value, label) tuple pattern.

When adding new enum values:
- Add the value here FIRST
- Then reference from models via `choices=UNIT_AREA` etc.
- NEVER define inline choices in model files (creates drift)

Source: EPA 40 CFR Part 98, EPA eGRID 2023, USDA NASS 2023, USDA NRCS, OMRI
Last Updated: 2026-04-05 (Phase 1: Event Field SSOT Migration)
"""

# ============================================================================
# FUEL TYPES (already centralized in carbon/choices.py — re-exported here)
# ============================================================================
# Used in: ChemicalEvent.application_fuel_type, ProductionEvent.fuel_type,
#          SoilManagementEvent.fuel_type, PestManagementEvent.fuel_type, EquipmentEvent.fuel_type
from carbon.choices import FUEL_TYPE_FACTORS, FUEL_TYPES  # noqa: F401

# ============================================================================
# UNIT ENUMS — Physical units for quantitative fields
# ============================================================================

# Area units (most common: acres for US farms, ha for international)
# Used in: ChemicalEvent.area_unit, ProductionEvent.area_unit, SoilManagementEvent.area_unit,
#          PestManagementEvent.area_unit, EquipmentEvent.area_unit
UNIT_AREA = [
    ("ha", "Hectares"),
    ("acres", "Acres"),
    ("m2", "Square Meters"),
    ("km2", "Square Kilometers"),
]

# Volume units (liquid/solid chemicals, fertilizers)
# Used in: ChemicalEvent.volume_unit
UNIT_VOLUME = [
    ("L", "Liters"),
    ("gal", "Gallons"),
    ("mL", "Milliliters"),
    ("oz", "Ounces"),
    ("kg", "Kilograms"),
    ("lbs", "Pounds"),
]

# Soil-amendment mass/volume units.
# Used in: SoilManagementEvent.amendment_amount_unit, .amendment_quantity_purchased_unit
#
# Hoisted out of an inline `choices=[...]` on the model 2026-08-16, when the purchase-quantity
# field was added beside it. The APPLIED amount and the PURCHASED amount are the two halves of
# the § 205.103(b)(2) mass balance, and the export can only subtract them when the two unit
# strings match — the same trap that silently deleted sale-vs-harvest reconciliation from the
# packet when SalesRecord offered `tonnes` and the harvest form offered `tons`. One list, both
# columns; adding a unit means adding it here and in the frontend's AMENDMENT_UNITS.
UNIT_AMENDMENT = [
    ("kg", "Kilograms"),
    ("lbs", "Pounds"),
    ("tons", "Tons"),
    ("gal", "Gallons"),
]

# Fuel units (diesel, gasoline, electricity)
# Used in: ChemicalEvent.application_fuel_unit, ProductionEvent.fuel_unit,
#          SoilManagementEvent.fuel_unit, PestManagementEvent.fuel_unit, EquipmentEvent.fuel_unit
UNIT_FUEL = [
    ("L", "Liters"),
    ("gal", "Gallons"),
    ("kg", "Kilograms"),
    ("kWh", "Kilowatt-hours"),
]

# Yield/harvest units
# Used in: ProductionEvent.yield_unit
UNIT_YIELD = [
    ("kg", "Kilograms"),
    ("tons", "Tonnes"),
    ("lbs", "Pounds"),
    ("boxes", "Boxes"),
    ("bins", "Bins"),  # F18: tree-crop harvest unit — CA avocado/citrus are picked into field bins
    ("plants", "Plants"),
    ("seeds", "Seeds"),
]

# Distance units (transportation, depth)
# Used in: ProductionEvent.transportation_unit
UNIT_DISTANCE = [
    ("km", "Kilometers"),
    ("miles", "Miles"),
    ("m", "Meters"),
]

# Depth units (irrigation, tillage)
# Used in: ProductionEvent.irrigation_depth_unit
UNIT_DEPTH = [
    ("inches", "Inches"),
    ("cm", "Centimeters"),
]


# ============================================================================
# APPLICATION METHODS
# ============================================================================

# Chemical application method (how chemical is delivered to the crop)
# Used in: ChemicalEvent.application_method_structured
APPLICATION_METHOD = [
    ("broadcast", "Broadcast"),
    ("injection", "Soil Injection"),
    ("foliar", "Foliar Application"),
    ("drip", "Drip/Fertigation"),
    ("banding", "Band Application"),
    # F20 (2026-06): DPR-PML-017C box 21 application-method categories + the
    # orchard-standard air-blast. Fumigation additionally requires ffm_code.
    ("ground_spray", "Ground Spray"),
    ("air_blast", "Air-Blast (orchard sprayer)"),
    ("aerial", "Aerial"),
    ("fumigation", "Fumigation"),
    ("chemigation", "Chemigation"),
    ("soil_incorporation", "Soil Incorporation"),
]

# USDA NASS 2023 irrigation methods
# Used in: ProductionEvent.irrigation_method
IRRIGATION_METHOD = [
    ("flood", "Flood Irrigation"),
    ("furrow", "Furrow Irrigation"),
    ("drip", "Drip Irrigation"),
    ("sprinkler", "Sprinkler System"),
    ("center_pivot", "Center Pivot"),
    ("sub_irrigation", "Sub-surface Irrigation"),
    ("micro_sprinkler", "Micro-sprinkler"),
    ("hand_watering", "Hand Watering"),
    ("rain_fed", "Rain-fed Only"),
]


# ============================================================================
# SOURCE ENUMS — Provenance/origin of inputs
# ============================================================================

# Seed/seedling source — WHERE the seed came from (transparency field; does NOT affect carbon)
# Used in: ProductionEvent.seeds_source
# Note: "certified_organic" is intentionally NOT a source — use seed_certification_status for that.
# Historical records with seeds_source="certified_organic" are migrated by 0152_nop_seed_traceability.
SEEDS_SOURCE = [
    ("farm_saved", "Farm-Saved Seeds"),
    ("local", "Local Nursery/Supplier"),
    ("cooperative", "Farmer Cooperative"),
    ("commercial", "Commercial Supplier"),
    ("other", "Other"),
]

# Seed regulatory classification — WHAT the seed is, per NOP 7 CFR 205.204
# Used in: ProductionEvent.seed_certification_status
# "non_organic_treated" with prohibited substances disqualifies the crop from organic sale.
SEED_CERTIFICATION_STATUS = [
    ("certified_organic", "Certified Organic"),
    ("transitional", "Transitional"),
    ("non_organic_untreated", "Non-organic (Untreated)"),
    ("non_organic_treated", "Non-organic (Treated)"),
]

#: USDA Form 11's "allowed status" column is a TRIPLE, not a single status:
#:   (a) the variety is on an allowed list, (b) no prohibited treatments were applied,
#:   (c) the seed is non-GMO (excluded methods, 7 CFR 205.105(e)).
#: `SEED_CERTIFICATION_STATUS` answers (a) and (b). (c) had no field at all, so a packet
#: could assert an organic planting while saying nothing about excluded methods — which is
#: the one of the three that § 205.105(e) states as a flat prohibition rather than a
#: conditional.
#:
#: NOT a boolean. "Not asked" and "the grower checked and it is not verified" are different
#: records, and a boolean collapses them into False — which would read on a packet as a
#: negative finding against a grower who was never asked the question.
#: ⚠️ Producer/certifier surface ONLY. "Non-GMO" is a marketing claim on a consumer surface
#: and this value is entirely self-reported; it must never reach the public payload.
SEED_NON_GMO_STATUS = [
    ("supplier_attested", "Supplier attested non-GMO (documentation on file)"),
    ("seed_label", "Stated on the seed label / tag"),
    ("organic_certified", "Certified organic — excluded methods prohibited by § 205.105(e)"),
    ("not_verified", "Checked — could not verify"),
]

#: Free-text answers that MEAN "nothing was applied to the seed". The seed-treatment input is
#: a text box whose own placeholder reads "e.g., Rhizobium inoculant, None", so "None" is the
#: answer the UI invites. Treating it as a NAMED treatment made the certifier packet print
#: "Not recorded - 205.204(a)(2) asks why the treatment is allowed" beside it, telling a
#: grower who correctly reported that nothing was applied that their record had a gap.
#: Spanish included: the app ships es-419.
NO_TREATMENT_ANSWERS = {
    "none",
    "no",
    "n/a",
    "na",
    "-",
    "--",
    "nil",
    "nothing",
    "untreated",
    "no treatment",
    "ninguno",
    "ninguna",
    "sin tratamiento",
    "sin tratar",
}


# Production subtypes that put seed or planting stock in the ground, and are therefore
# subject to 7 CFR 205.204. Transplanting belongs here with Planting: the seedling or
# nursery stock is still seed/planting stock for § 205.204 purposes, common_osp_records
# already scores prod("PL", "TR") together, and the planting form shows the seed block for
# both. Testing "PL" alone — as the serializer and model validators did until 2026-08-15 —
# let a transplant of non-organic nursery stock skip the commercial-availability
# requirement entirely, which on a perennial orchard is the MORE common of the two records.
SEED_SOURCED_SUBTYPES = ("PL", "TR")

# The two seed_certification_status values that trigger the § 205.204(a)(1)
# commercial-availability obligation. Transitional is NOT among them here only because the
# statute speaks of "nonorganically produced" stock; osp_prefill maps transitional onto the
# non-organic OSP options separately.
NON_ORGANIC_SEED_STATUSES = ("non_organic_untreated", "non_organic_treated")

# Water source (affects pump energy factor — USDA NRCS)
# Used in: ProductionEvent.water_source
WATER_SOURCE = [
    ("well_groundwater", "Well/Groundwater"),
    ("municipal", "Municipal Water Supply"),
    ("rainwater_harvesting", "Rainwater Harvesting"),
    ("irrigation_canal", "Irrigation Canal/District"),
    ("river_stream", "River/Stream"),
    ("pond_reservoir", "Pond/Reservoir"),
    ("recycled_water", "Recycled/Reclaimed Water"),
    ("other", "Other"),
]

# Electricity source for irrigation pumps (affects CO2 emission factor)
# Used in: ProductionEvent.electricity_source
ELECTRICITY_SOURCE = [
    ("grid", "Grid Electricity"),
    ("solar", "Solar"),
    ("wind", "Wind"),
    ("diesel_generator", "Diesel Generator"),
    ("mixed", "Mixed Sources"),
]


# ============================================================================
# EFFICIENCY/GRADE ENUMS
# ============================================================================

# Production efficiency rating (carbon scoring modifier)
# Used in: ProductionEvent.production_efficiency, SoilManagementEvent.production_efficiency,
#          PestManagementEvent.production_efficiency
PRODUCTION_EFFICIENCY = [
    ("high", "High Efficiency"),
    ("normal", "Normal Efficiency"),
    ("low", "Low Efficiency"),
]

# Harvest quality grade (premium fruit operations — CA citrus, UY exports)
# Used in: ProductionEvent.harvest_quality_grade
HARVEST_QUALITY_GRADE = [
    ("export_quality", "Export Quality"),
    ("grade_a", "Grade A"),
    ("grade_b", "Grade B"),
    ("grade_c", "Grade C"),
    ("domestic", "Domestic Market"),
    ("processing", "Processing/Juice"),
]

# WS-4 (2026-08): how the harvest quantity was determined (§ 205.103(b)(2) —
# records must be "accurate"; a scale-verified figure carries a weigh ticket).
# Used in: ProductionEvent.amount_determination (HA subtype)
AMOUNT_DETERMINATION = [
    ("estimated", "Estimated"),
    ("scale_verified", "Scale-Verified (weigh ticket)"),
]

# WS-4 (2026-08): where the harvested lot went — first hop of the audit trail
# (§ 205.103(b)(2) tracking from production to sale; FSMA 204 KDE prep).
# Used in: ProductionEvent.harvest_destination (HA subtype)
HARVEST_DESTINATION = [
    ("stored", "Stored on farm"),
    ("sold_direct", "Sold / shipped from field"),
    # 🔴 2026-08-16, CCOF grower-checklist audit. Item 6 — "if you send your crops to another
    # certified organic operation for handling or processing" — had NO expressible answer here:
    # the four options were stored / sold / feed / other, and shipping a lot to a custom huller
    # is none of those. Title does not change, so it is not a sale; a grower with nowhere to
    # record it would enter the huller as the BUYER on a SalesRecord, which puts a non-sale in
    # the § 205.307 itemized sales table, double-counts against the real sale when the finished
    # product ships, and breaks the mass balance in a way that reads as the operation's
    # recordkeeping failure. For the California tree-nut ICP this is the normal path, not an
    # edge case.
    ("handler", "Sent to an off-farm handler (huller, dryer, cold store, packer)"),
    ("livestock_feed", "Livestock feed"),
    ("other", "Other"),
]

# WS-4 (2026-08): what happened to crop from buffer rows (§ 205.202(c) — buffer
# crop may never be sold, labeled, or represented as organic). NULL = question
# not answered; absence of an answer is NOT a claim that no buffer exists.
# Used in: ProductionEvent.buffer_disposition (HA subtype)
BUFFER_DISPOSITION = [
    ("not_harvested", "Buffer rows not harvested / excluded"),
    ("left_in_field", "Harvested and left in the field"),
    ("sold_conventional", "Sold as conventional"),
    ("fed_nonorganic_livestock", "Fed to non-organic livestock"),
    ("disposed", "Disposed of"),
    ("given_away", "Given away"),
    # Legacy value from the 2-option enum (2026-08-08) — kept selectable so stored
    # rows keep rendering; superseded by the specific dispositions above.
    ("harvested_conventional", "Harvested separately — sold or used as conventional"),
]

# WS-4 (2026-08): whether an input application covered the whole planting or a
# part of it (§ 205.103(b)(2) audit sufficiency — records must identify WHERE the input
# went; (b)(1) is "adapted to the particular business" and says nothing about location;
# PUR site-level reporting needs the same answer).
# Used in: ChemicalEvent.applied_scope
APPLIED_SCOPE = [
    ("all", "Entire planting"),
    ("part", "Part of planting"),
]


# 2026-08 QO-parity: WHAT was cleaned. § 205.272(a) commingling prevention —
# an inspector reads cleanout logs per asset class (harvester vs bin vs truck),
# not as one undifferentiated "cleaning" pile.
# Used in: ProductionEvent.cleaning_asset_class (EM cleaning ops)
CLEANING_ASSET_CLASS = [
    ("equipment", "Field / harvest equipment"),
    ("harvest_bins", "Harvest bins / totes"),
    ("storage", "Storage area / cooler"),
    ("transport_vehicle", "Transport vehicle / trailer"),
]


# ============================================================================
# EQUIPMENT ENUMS
# ============================================================================

# Equipment type (for carbon calculation accuracy)
# Used in: ProductionEvent.equipment_type
EQUIPMENT_TYPE = [
    ("tractor", "Tractor"),
    ("harvester", "Harvester/Combine"),
    ("sprayer", "Sprayer"),
    ("truck", "Truck/Transport"),
    ("generator", "Generator"),
    ("pump", "Irrigation Pump"),
    ("other", "Other Equipment"),
]

# Equipment operation type (for Equipment Maintenance events within ProductionEvent)
# Used in: ProductionEvent.equipment_operation_type
EQUIPMENT_OPERATION_TYPE = [
    ("FC", "Fuel Consumption"),
    ("MN", "Maintenance"),
    ("RE", "Repair"),
    ("CA", "Calibration"),
    ("BD", "Breakdown"),
    ("EI", "Inspection"),
    ("CL", "Cleaning"),
]


# ============================================================================
# AGRONOMIC/CROP ENUMS
# ============================================================================

# Crop growth stage (agronomic context — used on all event types via CommonEvent)
# Used in: CommonEvent.growth_stage (abstract base class, inherited by all events)
GROWTH_STAGE = [
    ("dormant", "Dormant"),
    ("budbreak", "Bud Break"),
    ("bloom", "Bloom/Flowering"),
    ("fruit_set", "Fruit Set"),
    ("vegetative", "Vegetative Growth"),
    ("maturation", "Maturation"),
    ("harvest_ready", "Harvest Ready"),
    ("post_harvest", "Post-Harvest"),
]


# ============================================================================
# COMPLIANCE/CERTIFICATION ENUMS
# ============================================================================

# Organic approval status (transparency + consumer trust)
# NOTE: Legacy values (yes/no/not_applicable) kept for backward compatibility with existing data.
# New entries should use the detailed values (omri_listed, usda_nop_approved, etc.)
# Used in: ChemicalEvent.organic_approved
ORGANIC_APPROVED = [
    # Legacy choices (kept for backward compatibility with pre-2025-11 data)
    ("yes", "Yes - Organic Approved"),
    ("no", "No - Not Organic"),
    ("not_applicable", "Not Applicable"),
    # Detailed organic certification options (Sprint 6, 2025-11)
    ("omri_listed", "OMRI Listed"),
    ("wsda_listed", "WSDA Listed"),
    ("nop_seal_on_label", "NOP seal on the product label"),
    ("certifier_approved", "Reviewed and approved by my certifier"),
    # ⛔ Retired 2026-08-15, kept so existing rows still render a label rather than a raw slug.
    #
    # "usda_nop_approved / USDA NOP Approved - National Organic Program" asserted a federal
    # product approval that does not exist: the NOP publishes a substance list (§ 205.601 /
    # § 205.602) and licenses a seal — it does not approve or list products. USDA's own
    # Input Material Application Record enumerates exactly four lawful verification bases,
    # verbatim: "OMRI or WSDA List, NOP Seal on label, or certifier review and approval".
    # Two of those four (WSDA, certifier review) had no option at all, which is why growers
    # reached for the invented ones.
    #
    # "organic_equivalent / Meets organic standards" is a grower-graded self-assessment
    # sitting in the column an inspector reads as a verification basis. It appears nowhere
    # in the frozen corpus.
    ("usda_nop_approved", "NOP seal on label (legacy entry)"),
    ("organic_equivalent", "Grower-assessed as equivalent (legacy entry — no listing)"),
    ("not_organic", "Not Organic Approved - Conventional use only"),
    ("transitional", "Transitional - In certification process"),
]

# THE allow-list for "this input is approved for organic production". One list,
# derived from the enum above, because two hand-maintained copies drifted:
# `transition_status_service` omitted the legacy "yes" that `claim_resolver`
# accepted, and NEITHER carried the "organic" value the database actually holds.
# The result on the audit dossier (2026-08-04): an OMRI-listed copper fungicide
# the farmer recorded as organic was counted as a PROHIBITED SUBSTANCE and reset
# the § 205.202(b) 36-month clock, declaring certified land "in transition" for
# three years on the document that goes to the certifier.
#
# Add a value here — never in a caller.
ORGANIC_APPROVED_OK_VALUES = frozenset(
    {
        "omri_listed",
        "wsda_listed",  # 2026-08-15 — a lawful basis USDA's own form names; had no option
        "nop_seal_on_label",  # 2026-08-15 — ditto, and what "usda_nop_approved" meant to say
        "certifier_approved",  # 2026-08-15 — the ordinary basis for a non-listed material
        "usda_nop_approved",  # legacy rows; label retired, value still means "seal on label"
        "organic_equivalent",  # legacy rows; grower self-assessment, retained for continuity
        "yes",  # legacy "Yes - Organic Approved", still selectable
        "organic",  # present in stored data; predates the detailed enum
    }
)

# Values that affirmatively state a PROHIBITED substance was applied. Only these
# may reset a transition clock. Deliberately NOT the complement of the allow-list:
# "not_applicable" means the question does not apply, and blank means nobody
# answered — neither is evidence that a prohibited substance was used.
ORGANIC_PROHIBITED_VALUES = frozenset({"not_organic", "no", "transitional"})


# ============================================================================
# CHEMICAL SUBTYPE ENUMS — For accurate carbon emission factor selection
# ============================================================================

# Combined chemical subtype (what's stored in DB)
# Used in: ChemicalEvent.chemical_subtype
CHEMICAL_SUBTYPE = [
    # Herbicide subtypes
    ("synthetic_herbicide", "Synthetic Herbicide"),
    ("organic_herbicide", "Organic/Natural Herbicide"),
    # Fungicide subtypes
    ("synthetic_fungicide", "Synthetic Fungicide"),
    ("organic_fungicide", "Organic/Natural Fungicide"),
    ("copper_fungicide", "Copper-Based Fungicide"),
    ("sulfur_fungicide", "Sulfur-Based Fungicide"),
    ("biological_fungicide", "Biological Fungicide"),
    # Pesticide subtypes
    ("synthetic_pesticide", "Synthetic Pesticide"),
    ("organic_pesticide", "Organic/Natural Pesticide"),
    ("biological_pesticide", "Biological Pesticide"),
    # Fertilizer subtypes
    ("synthetic_fertilizer", "Synthetic/Chemical Fertilizer"),
    ("organic_fertilizer", "Organic Fertilizer"),
    ("slow_release_fertilizer", "Slow-Release Fertilizer"),
]

# Sub-options filtered by chemical main type (for frontend UI rendering)
# The structured subtype UI shows only relevant options based on main type (FE/PE/FU/HE)
CHEMICAL_SUBTYPE_BY_MAIN_TYPE = {
    "FE": [
        ("synthetic_fertilizer", "Synthetic/Chemical Fertilizer"),
        ("organic_fertilizer", "Organic Fertilizer"),
        ("slow_release_fertilizer", "Slow-Release Fertilizer"),
    ],
    "PE": [
        ("synthetic_pesticide", "Synthetic Pesticide"),
        ("organic_pesticide", "Organic/Natural Pesticide"),
        ("biological_pesticide", "Biological Pesticide"),
    ],
    "FU": [
        ("synthetic_fungicide", "Synthetic Fungicide"),
        ("organic_fungicide", "Organic/Natural Fungicide"),
        ("copper_fungicide", "Copper-Based Fungicide"),
        ("sulfur_fungicide", "Sulfur-Based Fungicide"),
        ("biological_fungicide", "Biological Fungicide"),
    ],
    "HE": [
        ("synthetic_herbicide", "Synthetic Herbicide"),
        ("organic_herbicide", "Organic/Natural Herbicide"),
    ],
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_choice_values(choices):
    """Return list of valid values (first element of each tuple) from a choices list."""
    return [choice[0] for choice in choices]


def get_choice_label(choices, value):
    """Return the human label for a given value in a choices list."""
    for choice_value, choice_label in choices:
        if choice_value == value:
            return choice_label
    return None


def is_valid_choice(choices, value):
    """Check if a value exists in a choices list."""
    return value in get_choice_values(choices)
