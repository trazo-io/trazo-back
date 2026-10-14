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

# Application-rate units — a quantity PER unit of land.
# Used in: ChemicalEvent.application_rate_unit
#
# A rate is the number a grower actually says, because it is the number written on the label:
# "six fluid ounces an acre", "three and a half pounds an acre". Until 2026-09-03 there was
# nowhere to put it. `volume_numeric` is a TOTAL (its help text and the form's label both say
# so), so a spoken rate either landed there — wrong by the whole acreage, on a value the
# certifier packet and CA PUR both read — or was dropped on the floor.
#
# ⛔ COMPOUND values, one string, never two columns. A rate is a single fact; splitting it into
# a numerator unit and a denominator unit invites the pair to be written half-way, and
# `UNIT_AMENDMENT` above records what happens when two halves of one measurement can disagree.
#
# US customary first: the ICP is CA/WA wholesale orchards and every label rate in that market is
# per acre. Metric follows for the same reason `UNIT_AREA` carries both.
UNIT_APPLICATION_RATE = [
    ("fl_oz_ac", "fl oz/acre"),
    ("pt_ac", "pints/acre"),
    ("qt_ac", "quarts/acre"),
    ("gal_ac", "gallons/acre"),
    ("oz_ac", "oz/acre"),
    ("lb_ac", "lbs/acre"),
    ("ton_ac", "tons/acre"),
    ("mL_ha", "mL/hectare"),
    ("L_ha", "L/hectare"),
    ("g_ha", "g/hectare"),
    ("kg_ha", "kg/hectare"),
    ("t_ha", "tonnes/hectare"),
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
    # Bulk compost, mulch and sawdust are sold, delivered and invoiced by the cubic yard —
    # the amendment volume a certifier reconciles against the supplier's ticket is a yardage,
    # not a weight. Without this the operator either converts by guessing a density (which
    # invents a number the invoice does not support) or types "yd3" into a column whose
    # `choices` reject it. A pilot farm's three sawdust top-dressings (392, 438 and 490 yd3)
    # sat in the database as exactly that invalid value until 2026-08-22.
    ("yd3", "Cubic yards"),
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

# CA schoolsite method codes — 3 CCR 6691, via 6434(6)(A) and 6626(c).
#
# DPR ENF 25-16 (2025-12-17), effective 2026-01-01 under AB 1864 (Stats. 2024, Ch. 552):
# for an application made to produce an agricultural commodity within 1/4 MILE OF A
# SCHOOLSITE, the NOI and the PUR must carry a method code. DPR did not add a new box for
# this — it REPURPOSED the existing 4-digit field fumigation method code field.
#
# NEVER: this is not a fumigation-only rule. Until 2026-09-17 Trazo asked for the code only
# when the method was fumigation (`pur_export_service`, gated on method == "Fume"), the PUR
# column was headed "FFM Code (fumigation)" and the model cited 3 CCR 6624(c)(8), the old
# fumigant basis. A ground rig, an airblast sprayer or a drip line near a school all owe a
# code and none of them would have been asked. Source: Tulare County Agricultural
# Commissioner, 2026-09-17, forwarding ENF 25-16.
#
# Codes are the grower's declaration, never Trazo's inference — see SCHOOLSITE_CODE_SUGGESTION.
SCHOOLSITE_METHOD_CODE = [
    # 3 CCR 6691(a) — minimum 1/4 mile distance restriction
    ("5102", "5102 — Airblast or air-carrier sprayer (no dust or powder)"),
    ("5161", "5161 — Chemigation: sprinkler (solid set, lateral move, traveling gun), no fumigants"),
    ("5104", "5104 — Dust or powder (except field soil injection)"),
    ("5149", "5149 — Outdoor fumigation (e.g. field burrow fumigation)"),
    ("5173", "5173 — Enclosed space fumigation (e.g. greenhouse)"),
    # 3 CCR 6691(b) — minimum 25-foot distance restriction
    ("5101", "5101 — Ground-rig sprayer (no dust, powder, fumigant or airblast)"),
    ("5111", "5111 — Field soil injection (no dusts, powders, fumigants or chemigation)"),
    ("5121", "5121 — Manual placement (e.g. twist ties), no dusts, powders or fumigants"),
    ("5129", "5129 — Other hand-held (e.g. pressurized hose-line sprayer)"),
    ("5162", "5162 — Chemigation: micro-irrigation (drip, trickle, micro-sprinkler), no fumigants"),
    ("5163", "5163 — Chemigation: surface/gravity flow (flood, furrow), no fumigants"),
    ("5169", "5169 — Chemigation: other method (no fumigants)"),
    ("5199", "5199 — Unspecified ground or other application equipment not listed"),
    # 3 CCR 6691(c) — no distance restriction
    ("5171", "5171 — Enclosed space application (greenhouse, mushroom house), no fumigants"),
    ("5131", "5131 — Bait station"),
    ("5112", "5112 — Field soil injection, dust or powder only"),
    ("5106", "5106 — Granule, flake or pellet (e.g. mechanical spreaders), no fumigants"),
    ("5123", "5123 — Backpack sprayer (no dust, powder or airblast)"),
    ("5122", "5122 — Hand pump sprayer (no dust, powder or fumigant)"),
]

#: Application methods that carry NO schoolsite method code at all.
#: 3 CCR 6691(a)(1): "Aircraft - manned or unmanned - no method code."
SCHOOLSITE_METHODS_WITHOUT_CODE = {"aerial"}

#: Trazo application_method -> the ONE DPR code it can only be.
#:
#: NEVER extend this with a method that maps to more than one code. "Foliar", "broadcast",
#: "banding" and bare "chemigation" each span several rows of SCHOOLSITE_METHOD_CODE (a foliar
#: pass is 5101, 5102, 5123 or 5129 depending on the rig; chemigation is 5161/5162/5163/5169
#: depending on the delivery), and a wrong 4-digit code on a filing the County Agricultural
#: Commissioner keys is worse than a blank one: blank is a visible gap, wrong is a silent
#: misstatement. Everything absent here is asked of the grower, not guessed.
SCHOOLSITE_CODE_SUGGESTION = {
    "ground_spray": "5101",
    "air_blast": "5102",
}
# ⛔ REMOVED 2026-09-17, on a re-read, because they were the very guess this map forbids:
#   "drip" -> 5162. Trazo's LABEL is "Drip/Fertigation", and fertigation through a solid set or
#     traveling gun is 5161, surface/gravity flow is 5163. One slug, three DPR rows.
#   "injection" -> 5111. 3 CCR 6691 splits field soil injection on FORMULATION: 5111 for liquids,
#     5112 for dust or powder only. The slug does not carry the formulation.
# Only add a slug here when the Trazo LABEL, not the developer's mental picture of it, can mean
# exactly one row of SCHOOLSITE_METHOD_CODE.

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


# Production subtypes carrying 7 CFR 205.204 seed / planting-stock obligations.
# Transplanting belongs here with Planting: the seedling or nursery stock is still
# seed/planting stock for § 205.204 purposes, common_osp_records already scores
# prod("PL", "TR") together, and the planting form shows the seed block for both. Testing
# "PL" alone — as the serializer and model validators did until 2026-08-15 — let a
# transplant of non-organic nursery stock skip the commercial-availability requirement
# entirely, which on a perennial orchard is the MORE common of the two records.
#
# 🔴 "SS" (Seed Search) added 2026-08-19. It does not put stock in the ground — it is the
# § 205.204(a)(1) commercial-availability search itself — so the old name read as excluding
# it, and it WAS excluded: an SS row declaring non-organic seed with zero documented
# supplier attempts validated clean, which is the one record the obligation exists to
# demand. The form has rendered the seed block and the attempts table for SS since the
# subtype shipped, so including it here costs the grower nothing they were not already
# being asked for.
SEED_SOURCED_SUBTYPES = ("PL", "TR", "SS")

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

# ⛔ RETIRED 2026-08-21 (F5). Kept as the legacy record, referenced by NOTHING.
#
# This list, and the DIFFERENT one on `History.quality_grade` (Premium / Grade A / Grade B /
# Standard / Processing), were two vocabularies for one fact — so a lot header and the harvest
# picks underneath it could not agree, and the certifier packet printed both. Neither carried a
# grade a US packing record uses: real records read "U.S. No. 1", "U.S. Commercial",
# "WA Extra Fancy". A certifier reviewer put it plainly — *"Grade A is not an apple grade."*
#
# The replacement is crop-aware and lives in `history/harvest_grades.py` (mirrored in
# `trazo-app/src/config/harvestGrades.ts`). These slugs survive there as
# `LEGACY_GRADE_LABELS` so rows written before the change still render a label.
_RETIRED_HARVEST_QUALITY_GRADE = [
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
# Aligned with the seven options Quick Organics offers on its Cleanout activity (verified in
# their live form, 2026-08-19). Trazo had the first four; the last three were unreachable, so a
# packing-line or a barn cleanout could only be misfiled as generic "equipment" — and § 205.272
# turns on WHICH surface the organic product touched, so the class is the substance of the
# record, not a label on it.
CLEANING_ASSET_CLASS = [
    ("equipment", "Field / harvest equipment"),
    ("harvest_bins", "Harvest bins / totes"),
    ("storage", "Storage area / cooler"),
    ("transport_vehicle", "Transport vehicle / trailer"),
    ("processing_line", "Processing equipment or line"),
    ("livestock_housing", "Livestock housing"),
    ("other", "Other"),
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
    # Run 8b (8b-06): was "Yes - Organic Approved". The answer names no basis and no approval
    # anyone can show, so the label says only what it is.
    ("yes", "Yes (legacy entry)"),
    ("no", "No - Not Organic"),
    ("not_applicable", "Not Applicable"),
    # Detailed organic certification options (Sprint 6, 2025-11)
    ("omri_listed", "OMRI Listed"),
    ("wsda_listed", "WSDA Listed"),
    ("nop_seal_on_label", "NOP seal on the product label"),
    ("certifier_approved", "Reviewed and approved by my certifier"),
    # Run 8 (R8-08, 2026-10-05): the grower could only save an organic record by picking a basis,
    # so an input whose listing was unknown forced a false declaration. "Not yet confirmed" is an
    # honest answer: it is neither approved nor prohibited (it is in neither set below), it never
    # earns an organic claim, and the record lists the basis as missing until it is confirmed.
    ("unverified", "Not yet confirmed: what shows it is allowed is still to be checked"),
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
    ("not_organic", "No organic basis - conventional use only"),
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
        "yes",  # legacy "Yes (legacy entry)", still selectable
        "organic",  # present in stored data; predates the detailed enum
    }
)

# Values that affirmatively state a PROHIBITED substance was applied. Only these
# may reset a transition clock. Deliberately NOT the complement of the allow-list:
# "not_applicable" means the question does not apply, and blank means nobody
# answered — neither is evidence that a prohibited substance was used.
ORGANIC_PROHIBITED_VALUES = frozenset({"not_organic", "no", "transitional"})

#: Run 8 (R8-08): an answer that is neither: the grower has not confirmed what shows the input is
#: allowed. Never earns an organic claim (not in the OK set) and is not a finding of prohibition.
ORGANIC_UNRESOLVED_VALUES = frozenset({"unverified"})


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
