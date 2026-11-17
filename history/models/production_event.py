"""Production activities: planting through harvest."""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from carbon.choices import FUEL_TYPES
from common.field_registry import (
    AMOUNT_DETERMINATION,
    APPLIED_SCOPE,
    BUFFER_DISPOSITION,
    CLEANING_ASSET_CLASS,
    ELECTRICITY_SOURCE,
    EQUIPMENT_OPERATION_TYPE,
    EQUIPMENT_TYPE,
    HARVEST_DESTINATION,
    IRRIGATION_METHOD,
    NON_ORGANIC_SEED_STATUSES,
    PRODUCTION_EFFICIENCY,
    SEED_CERTIFICATION_STATUS,
    SEED_NON_GMO_STATUS,
    SEED_SOURCED_SUBTYPES,
    SEEDS_SOURCE,
    UNIT_AREA,
    UNIT_DEPTH,
    UNIT_DISTANCE,
    UNIT_FUEL,
    UNIT_YIELD,
    WATER_SOURCE,
)
from history.harvest_grades import MAX_GRADE_LENGTH

from .common_event import CommonEvent


class ProductionEvent(CommonEvent):
    PLANTING = "PL"
    HARVESTING = "HA"
    IRRIGATION = "IR"
    PRUNING = "PR"
    TRANSPLANTING = "TR"  # NEW - matches UI screenshot option "🌿 Transplanting - Plant relocation"
    # Sprint 2 Epic 2.1: Event Consolidation - Equipment merged into Production
    EQUIPMENT_MAINTENANCE = "EM"  # Merged from EquipmentEvent
    # Sprint 2 Epic 2.2: Missing USDA production types
    CULTIVATION = "CU"  # Mechanical weed removal, row cultivation
    THINNING = "TH"  # Plant density reduction

    # Phase 2 additions
    POLLINATION = "PO"  # Bee placement, pollinator management (almonds, tree fruit)
    POST_HARVEST_PROCESSING = "PH"  # Hulling, shelling, washing, sorting, packing
    CANOPY_MANAGEMENT = "CM"  # Leaf pulling, hedging, shoot positioning (distinct from Pruning)

    # Batch 3 (2026-06): Scope-1 fuel operations that previously had no structured
    # home — frost-fuel and orchard-floor mowing were either logged as Weather/General
    # (carbon-invisible: weather excluded, General flat 0.1) or miscategorized as CU
    # (tillage). Both route through the existing ProductionEvent fuel pipeline.
    FROST_PROTECTION = "FP"  # Wind machines / heaters / under-tree sprinklers on cold nights
    MOWING = "MO"  # Orchard-floor mowing / mulching / cover-crop or herbicide-strip management

    # Batch 4 (2026-08-19): parity with the activities Quick Organics offers a crop operation.
    # All three facts were already recordable — but only as FIELDS on some other event, which
    # is the wrong shape whenever the activity does not belong to that event:
    #   * a load leaves for the handler days after the harvest it came from, and one harvest
    #     can ship on several dates (§ 205.272 commingling turns on the LOAD, not the pick);
    #   * buffer-zone crop is disposed of on its own schedule and must never be sold as
    #     organic (§ 205.202(c));
    #   * an organic-seed search precedes planting and covers varieties that may never be
    #     planted — recording it only on a planting event loses the searches that succeeded.
    # They reuse the existing columns (handler/destination, buffer_disposition*,
    # seed_search_attempts), so this adds a shape, not a second home for the same fact.
    TRANSPORT = "TP"  # A load moving off-farm: destination, quantity, cleanout reference
    BUFFER_USE = "BU"  # Harvest or disposal from a § 205.202(c) buffer zone
    SEED_SEARCH = "SS"  # § 205.204(a)(1) organic-seed commercial-availability search

    PRODUCTION_EVENTS = (
        (PLANTING, "Planting"),
        (HARVESTING, "Harvesting"),
        (IRRIGATION, "Irrigation"),
        (PRUNING, "Pruning"),
        (TRANSPLANTING, "Transplanting"),  # NEW - enables complete transparency tracking
        # Sprint 2 additions
        (EQUIPMENT_MAINTENANCE, "Equipment Maintenance"),  # Merged from Equipment events
        (CULTIVATION, "Cultivation/Weed Control"),  # USDA aligned
        (THINNING, "Thinning"),  # USDA aligned
        # Phase 2 additions
        (POLLINATION, "Pollination"),  # Bee placement / pollinator management
        (POST_HARVEST_PROCESSING, "Post-Harvest Processing"),  # Hulling, shelling, washing, sorting, packing
        (CANOPY_MANAGEMENT, "Canopy Management"),  # Leaf pulling, hedging, shoot positioning
        # Batch 3 additions
        (FROST_PROTECTION, "Frost Protection"),  # Wind machines / heaters (Scope-1 fuel)
        (MOWING, "Mowing / Orchard-Floor"),  # Mowing, mulching, floor management
        # Batch 4 additions — see the note on the constants above
        (TRANSPORT, "Transport"),
        (BUFFER_USE, "Buffer Use"),
        (SEED_SEARCH, "Seed Search"),
    )

    type = models.CharField(max_length=2, choices=PRODUCTION_EVENTS)
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # New structured fields for better carbon calculations
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
    yield_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Quantity harvested or planted"
    )
    yield_unit = models.CharField(
        max_length=10,
        choices=UNIT_YIELD,
        default="lbs",
        blank=True,
        help_text="Yield unit",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Fuel consumed during production activity"
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit",
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

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    # Updated based on agricultural advisor + consumer trust analysis (2025-12-06)
    # Optimized for: farmer practicality, consumer trust, transparency-first approach
    seeds_source = models.CharField(
        max_length=50,
        choices=SEEDS_SOURCE,
        blank=True,
        null=True,
        help_text=(
            "Where the seed/planting stock came from (transparency field; does not affect carbon). "
            "For regulatory classification (organic/transitional/non-organic), use seed_certification_status."
        ),
    )
    # NOP Compliance: Seed Commercial Availability Search (NOP 5029)
    # When non-organic seed is used, NOP requires documentation of at least 3 supplier searches
    seed_search_attempts = models.JSONField(
        default=list,
        blank=True,
        help_text="Organic seed search documentation per NOP 5029. "
        "Format: [{supplier_name, date_contacted, result, notes}]",
    )
    # USDA's "Seed Records Part B" asks for the "Reason for Commercial Nonavailability: form,
    # quality, quantity". Those three words are not a UI convention — they are the statutory
    # test. § 205.2 defines "commercially available" as "the ability to obtain a production
    # input in an appropriate FORM, QUALITY, or QUANTITY to fulfil an essential function",
    # and § 205.204(a)(1) permits non-organic seed only when that test fails.
    #
    # `seed_search_attempts` records WHO was contacted and WHEN, with the outcome as free text
    # ("Available — certified organic Hass rootstock in stock"). Free text cannot be reviewed
    # against a three-part statutory test, so the ground for the exemption was unstructured.
    SEED_NONAVAILABILITY_REASON_CHOICES = [
        ("none_offered", "Not offered organically by any supplier contacted"),
        ("form", "Form — not available in the required form (§ 205.2)"),
        ("quality", "Quality — available stock did not meet quality requirements (§ 205.2)"),
        ("quantity", "Quantity — insufficient quantity available (§ 205.2)"),
        ("other", "Other (explain in the search notes)"),
    ]
    seed_nonavailability_reason = models.CharField(
        max_length=16,
        choices=SEED_NONAVAILABILITY_REASON_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Statutory ground for using non-organic seed (§ 205.204(a)(1); the form/quality/"
            "quantity test is § 205.2's definition of commercially available)."
        ),
    )
    # NOP Compliance: Seed Traceability (7 CFR 205.204 / NOP 5029)
    # Planting subtype (type="PL") only. Mirrors ChemicalEvent.supplier_name pattern (migration 0146).
    seed_supplier_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Name of the seed/planting stock supplier (NOP 7 CFR 205.204 traceability)",
    )
    seed_purchase_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date seed/planting stock was purchased (traceability to supplier invoice)",
    )
    seed_purchase_invoice = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Supplier invoice number for the seed/planting stock purchase",
    )
    seed_lot_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Supplier lot/batch identifier for the seed/planting stock",
    )
    seed_certification_status = models.CharField(
        max_length=30,
        choices=SEED_CERTIFICATION_STATUS,
        blank=True,
        null=True,
        help_text=(
            "Regulatory classification per NOP 7 CFR 205.204. § 205.204(a)(2) sets when nonorganic "
            "seed treated with a National List substance may be used; whether a crop may be sold "
            "as organic is the certifying agent's decision."
        ),
    )
    seed_treatment = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Seed coatings, inoculants, or pelleting materials applied (NOP 7 CFR 205.204(a)(2))",
    )
    # USDA's "Seed Records Part C: Documentation of Allowability of Seed Treatments, Coatings,
    # or Inoculants" pairs every named treatment with a "Documentation of Allowed Status"
    # column. Trazo named the treatment and stopped there — the same "named but unjustified"
    # shape as the 2026-08-09 OMRI leak, where an input was labelled OMRI Listed with no
    # catalog row behind it.
    #
    # § 205.204(a)(2) permits untreated non-organic seed only when an equivalent organic
    # variety is not commercially available, and any treatment applied must itself be an
    # allowed substance (§ 205.601). "Neem oil coating" alone does not say which of those is
    # true, so the record cannot be reviewed.
    SEED_TREATMENT_BASIS_CHOICES = [
        ("untreated", "Untreated — no coating, inoculant or pelleting applied"),
        ("omri_listed", "OMRI-listed product (catalog entry on file)"),
        ("national_list", "Allowed under National List § 205.601"),
        ("certifier_approved", "Reviewed and approved by the certifying agent"),
        ("organic_seed", "Certified organic seed — treatment allowed for organic production"),
        ("not_documented", "Not documented yet"),
    ]
    seed_treatment_allowed_basis = models.CharField(
        max_length=24,
        choices=SEED_TREATMENT_BASIS_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Why this seed treatment is permitted (USDA Seed Records Part C, 'Documentation of "
            "Allowed Status'). A named treatment with no basis is unreviewable under "
            "§ 205.204(a)(2)."
        ),
    )
    # ---- Harvest lot identity (HA) — added 2026-08-15 -------------------------------
    #
    # 🔴 The § 205.103(b)(2) join key, and the largest gap the 2026-08-15 audit found.
    #
    # `lot_id` lives on History — the PRODUCTION header — and `SalesRecord` points at the
    # same header. So for a multi-pick operation, n harvest passes collapsed into one lot and
    # one sales pool, and the operation could not say which pick went to which buyer. For the
    # ICP — California wholesale avocado and citrus, picked over weeks — that is the normal
    # case, not an edge case.
    #
    # USDA's Guide is explicit: growers "with multiple fields of the same crop will need to
    # assign lot numbers to the crops harvested from different fields", and a lot links
    # "products to the fields of origin and the year or date". Both halves — field AND date —
    # are properties of the harvest pass, not of the season.
    #
    # Deliberately a free CharField, not a generated key: growers arrive with a lot scheme
    # their buyers already use, and overwriting it would break the trace it exists to support.
    # `suggest_harvest_lot_code()` offers one when the field is empty; it never overwrites.
    harvest_lot_code = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text=(
            "Lot identifier for THIS harvest pass (7 CFR 205.103(b)(2)). Links the pick to its "
            "block and date, and is what a sales record references. Leave blank to accept the "
            "suggested code."
        ),
    )

    # ---- Perennial planting stock (PL/TR) — added 2026-08-15 ------------------------
    #
    # 🔴 These three had NO home. `rootstock` in particular was written by three seeders and
    # sat on the consumer extra_data allow-list, so shoppers could be shown a rootstock the
    # grower had no field to enter — and the certifier packet carried a written disclosure
    # that "Trazo does not yet structure rootstock records in this export".
    #
    # For the ICP — California wholesale avocado, citrus and nut orchards — rootstock IS the
    # identity of a planting. "40 Hass on Duke 7" is the sentence a grower says out loud, and
    # the variety half of it was the only half that had a column. It also carries real
    # § 205.204 weight: rootstock is planting stock, so its organic status and, for perennials,
    # the (a)(4) twelve-month rule attach to it rather than to the scion variety.
    rootstock = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text=(
            "Rootstock the scion was grafted onto (e.g. 'Duke 7', 'Dusa clonal'). Planting "
            "stock under 7 CFR 205.2; its organic status is what § 205.204 tests."
        ),
    )
    plants_established = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=(
            "How many trees/plants went in. On a perennial replant this is the number a "
            "certifier reconciles against the nursery invoice — area alone does not say it."
        ),
    )
    plant_spacing = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text=(
            "Spacing or density as the grower records it (e.g. '27 ft x 22 ft', "
            "'73 trees/ac'). Free text on purpose: COG Pro's export carries both forms in two "
            "separate columns and growers use whichever their block plan uses."
        ),
    )

    # ---- § 205.105(e) excluded methods + § 205.204(a)(4) — added 2026-08-15 ------------
    #
    # Both were named as gaps by the Planting teardown and neither had a column anywhere.
    #
    # `seed_non_gmo_status` is the third leg of USDA Form 11's allowed-status triple. The
    # other two legs (on an allowed list / no prohibited treatment) are answered by
    # `seed_certification_status` and `seed_treatment_allowed_basis`; excluded methods had
    # no field, so the packet asserted an organic planting while saying nothing about the
    # one § 205.105 prohibition that is unconditional.
    seed_non_gmo_status = models.CharField(
        max_length=32,
        choices=SEED_NON_GMO_STATUS,
        blank=True,
        null=True,
        help_text=(
            "How the exclusion of GMO/excluded methods was established for this planting "
            "stock (7 CFR 205.105(e)). Blank means the question was not answered — which is "
            "NOT the same as 'not verified'."
        ),
    )
    stock_organic_management_start = models.DateField(
        blank=True,
        null=True,
        help_text=(
            "Date this planting stock came under continuous organic management. 7 CFR "
            "205.204(a)(4): nonorganically produced PERENNIAL planting stock may itself be sold, "
            "labeled or represented as organic only after ONE YEAR of organic management. Without "
            "this date the packet cannot show that year; the grower's own nursery invoice date is "
            "the usual answer."
        ),
    )

    # Updated 2025-12-06: Aligned with transparency-first frontend choices
    water_source = models.CharField(
        max_length=50,
        choices=WATER_SOURCE,
        blank=True,
        null=True,
        help_text="Water source for irrigation - affects pump energy factor in carbon calculations (USDA NRCS)",
    )

    # USDA NASS 2023 Irrigation Fields - For Irrigation (IR) events
    # These fields enable accurate water usage estimation for transparency reporting
    irrigation_method = models.CharField(
        max_length=30,
        choices=IRRIGATION_METHOD,
        blank=True,
        null=True,
        help_text="Irrigation method used (USDA NASS 2023 categories for transparency)",
    )
    irrigation_depth = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Irrigation depth applied (USDA NASS: ~27,154 gal/acre per inch)",
    )
    irrigation_depth_unit = models.CharField(
        max_length=10,
        choices=UNIT_DEPTH,
        default="inches",
        blank=True,
        null=True,
        help_text="Unit for irrigation depth measurement",
    )

    # Phase 2: Quality metric for harvest and post-harvest events
    brix_level = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(45)],
        help_text="Brix level (sugar content) - key quality metric for fruit crops",
    )

    # Sprint 2 Epic 2.1: Equipment Maintenance fields (merged from EquipmentEvent)
    # These fields are used when production_type = 'EM' (Equipment Maintenance)
    fuel_type = models.CharField(
        max_length=20,
        choices=FUEL_TYPES,
        blank=True,
        null=True,
        help_text="Fuel type for equipment (EPA emission factor selection)",
    )
    equipment_type = models.CharField(
        max_length=30,
        choices=EQUIPMENT_TYPE,
        blank=True,
        null=True,
        help_text="Type of equipment used (for carbon calculation accuracy)",
    )
    equipment_operation_type = models.CharField(
        max_length=2,
        choices=EQUIPMENT_OPERATION_TYPE,
        blank=True,
        null=True,
        help_text="Type of equipment operation (for Equipment Maintenance events)",
    )

    # 🔴 F5 (2026-08-21) — see `History.quality_grade` above. Both columns share one
    # crop-aware vocabulary now (`history/harvest_grades.py`); this one used to offer
    # Export Quality / Grade A / B / C / Domestic / Processing, which is not a grade family
    # any US packing record uses, and disagreed with the season header besides.
    harvest_quality_grade = models.CharField(
        max_length=MAX_GRADE_LENGTH,
        blank=True,
        null=True,
        help_text=(
            "Grade this pick was packed to, as stated on the packing record. Free text: the "
            "crop-aware suggestions live in history/harvest_grades.py. No `choices` — see "
            "History.quality_grade for why."
        ),
    )

    # Sprint 3.2 — Post-harvest storage traceability (NOP 205.272 commingling; FSMA 204 prep).
    # Used on Harvest (HA) events to connect harvested lot -> bin/cooler/warehouse -> sale.
    storage_location = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Post-harvest storage location (e.g., 'Cooler 3', 'Warehouse B-Bin-12') for lot traceback",
    )
    storage_temperature_f = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Storage temperature in °F (quality control + FSMA 204 KDE)",
    )

    # 2026-08 QO-parity — custom-harvest arrangements (§ 205.103(b)): ties the
    # harvest record to the harvest contract when an uncertified custom
    # harvester runs the pass (G6.1 module collects the standing arrangement;
    # this field ties the individual harvest event to it).
    harvest_contract_number = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        help_text="Custom-harvest contract or work-order reference for this pass",
    )
    # 2026-08 QO-parity — whole-vs-part parcel coverage on harvest (HA) and
    # planting (PL), mirroring ChemicalEvent.applied_scope. ProductionTab gates the
    # payload on HA or PL only — TR reuses the seed widget but not this pair, so do not
    # read this comment as evidence that a transplant carries a scope answer.
    # (§ 205.103(b)(2) audit sufficiency: records must identify WHERE the activity happened.
    # NOT (b)(1), which is "adapted to the particular business". Corrected 2026-08-15.)
    applied_scope = models.CharField(
        max_length=10,
        choices=APPLIED_SCOPE,
        blank=True,
        null=True,
        help_text="Whether this activity covered the entire parcel/planting or part of it",
    )
    applied_scope_detail = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Which rows/blocks/area, when applied_scope is 'part'",
    )
    grain_moisture = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Grain moisture percentage at harvest (Midwest corn/soy operations)",
    )
    # F43 (2026-06): tree-crop maturity metric — the correct vocabulary for the CA orchard ICP.
    # Avocado uses dry-matter % as the legal CA maturity standard (CDFA; Hass min ~20.8%); nuts use
    # kernel dry-matter at drydown. brix_level is for citrus/sugar fruit; grain_moisture is grain-only.
    dry_matter_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Dry matter % at harvest — avocado/nut maturity (CA Hass legal min ~20.8%)",
    )

    # WS-4 (2026-08) — harvest-record completeness for the HA subtype.
    # § 205.103(b)(2): records must track product from production to sale AND be accurate.
    amount_determination = models.CharField(
        max_length=20,
        choices=AMOUNT_DETERMINATION,
        blank=True,
        null=True,
        help_text="How the harvest quantity was determined — estimated or scale-verified (weigh ticket)",
    )
    harvest_date_end = models.DateField(
        blank=True,
        null=True,
        help_text="Last day of a multi-day harvest window (event date is the first day)",
    )
    harvest_destination = models.CharField(
        max_length=20,
        choices=HARVEST_DESTINATION,
        blank=True,
        null=True,
        help_text="First hop of the harvested lot — storage, off-farm handler, direct sale, feed, or other",
    )

    # --- Off-farm handling round trip (7 CFR 205.272 · CCOF G6.1) -------------------------
    #
    # 🔴 2026-08-16, CCOF grower-checklist audit. Item 6 asks for four facts about crop sent to
    # another certified operation: "what you sent, where you sent it, when you sent it, and what
    # you received as the outcome". Trazo could answer "where" (History.post_harvest_facilities)
    # and nothing else. The finished quantity was only ever INFERRED, as shrinkage between
    # harvest and sale at a ±10% tolerance — which is a plausibility check, not a record.
    #
    # These live on the harvest event rather than on History because a multi-pick season sends
    # several loads to the same huller on different dates, and the pack-out comes back per load.
    #
    # All optional: a grower who sells field-run answers none of them, and the packet says the
    # crop did not leave the farm for handling rather than printing a gap.
    sent_to_handler_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date this lot was delivered to the off-farm handler (CCOF: 'when you sent it').",
    )
    quantity_sent_to_handler = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="How much left the farm for handling (CCOF: 'what you sent').",
    )
    quantity_returned_from_handler = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Finished quantity received back — the pack-out / outturn figure (CCOF: 'what you "
            "received as the outcome'). For tree nuts this is normally a different unit from "
            "what was sent (in-shell in, shelled out), so the two carry separate units."
        ),
    )
    handler_quantity_unit = models.CharField(
        max_length=20,
        choices=UNIT_YIELD,
        blank=True,
        null=True,
        help_text="Unit for the quantity SENT to the handler.",
    )
    handler_return_unit = models.CharField(
        max_length=20,
        choices=UNIT_YIELD,
        blank=True,
        null=True,
        help_text=(
            "Unit for the quantity RECEIVED BACK. Separate from handler_quantity_unit on "
            "purpose — hulling changes the unit, and forcing one unit would invent a "
            "conversion nobody measured."
        ),
    )
    handler_document_reference = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text=(
            "Pack-out summary, settlement statement or receiving-document number from the "
            "handler — CCOF's 'invoices, pack-out summaries, or other final statements'."
        ),
    )
    # § 205.202(c): buffer-row crop may never be sold or represented as organic.
    # NULL means the question was not answered, NOT that no buffer exists.
    buffer_disposition = models.CharField(
        max_length=30,
        choices=BUFFER_DISPOSITION,
        blank=True,
        null=True,
        help_text="Disposition of crop from buffer rows for this harvest (7 CFR 205.202(c))",
    )
    #: Dispositions that put the buffer crop into commerce. USDA's Buffer Crop Disposition
    #: Record warns that these are the ones needing formal proof: "Commercial quantities of
    #: crops require more formal documentation (delivery tags and nonorganic sales records) to
    #: show that the buffer crop has not been represented as organic." A crop disked under or
    #: left in the field cannot be mis-sold, so demanding paperwork there would be Trazo
    #: inventing a requirement.
    BUFFER_DISPOSITIONS_ENTERING_COMMERCE = frozenset(
        {"sold_conventional", "fed_nonorganic_livestock", "given_away", "harvested_conventional"}
    )
    buffer_disposition_quantity = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text=(
            "How much buffer crop was removed, in the grower's own units — USDA's form gives "
            '"1 4x4 bin" as its example. Free text on purpose: buffer quantities are not '
            "mass-balanced anywhere, and a forced unit would invite a fabricated conversion."
        ),
    )
    buffer_disposition_evidence = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text=(
            "Documentation type and location proving the buffer crop was not represented as "
            'organic — USDA\'s "Documentation (type and location)" column, e.g. "Delivery tag '
            "and sales record, Apple Bob's, buffer-crop folder\" (7 CFR 205.202(c))."
        ),
    )

    def buffer_disposition_entered_commerce(self):
        """True when this harvest's buffer disposition put the crop into someone else's hands.

        The § 205.202(c) proof obligation attaches here and nowhere else — which is why the
        packet asks for evidence on these dispositions and stays silent on the rest.
        """
        return (self.buffer_disposition or "") in self.BUFFER_DISPOSITIONS_ENTERING_COMMERCE

    # Item #13: Pump depth and electricity source for irrigation (IR) events.
    # These fields enable accurate energy calculation per USDA NRCS pump curve methodology.
    pump_depth_ft = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Well pump depth in feet — affects irrigation energy calculation (USDA NRCS)",
    )
    electricity_source = models.CharField(
        max_length=20,
        choices=ELECTRICITY_SOURCE,
        blank=True,
        null=True,
        help_text="Electricity source for pump — affects CO2 emission factor",
    )

    # Irrigation/well water test — NOT a 7 CFR Part 205 requirement.
    #
    # 🔴 Corrected 2026-08-15. This block was headed "NOP Compliance" and cited § 205.272
    # (handler commingling) and § 205.671 (exclusion from sale on residue exceedance).
    # Neither requires a producer water test: § 205.670(b)-(c) puts residue testing on the
    # CERTIFYING AGENT, at the agent's own expense, and USDA's Guide for Organic Crop
    # Producers says plainly that "the USDA organic regulations have very little to say
    # about irrigation and irrigation water quality." Microbial ag-water testing is FDA
    # FSMA Produce Safety Rule (21 CFR 112), and some certifiers ask for it contractually.
    # The certifier packet already states this correctly; these comments did not.
    # For the Irrigation (IR) subtype. CCOF requires an annual water-source analysis
    # demonstrating no prohibited substances / contamination. Mirrors the SoilManagementEvent
    # ST test_results pattern. Audit-only; never surfaced to consumers.
    water_test_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the irrigation/well water sample was taken or analyzed",
    )
    water_test_lab = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Name of the laboratory that analyzed the water sample",
    )
    water_test_results = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "List of {parameter, value, unit, result} dicts from the water analysis "
            "(e.g. coliform, nitrate, pH). Backs the certifier Water Quality record."
        ),
    )

    # NOP Compliance: Equipment Cleaning Logs (7 CFR 205.272)
    # For Equipment Maintenance (EM) subtype — required when equipment shared with conventional
    cleaning_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date equipment was cleaned (for shared equipment compliance)",
    )
    # ---- Purge records (§ 205.272) — parity with Quick Organics' Cleanout activity ----
    #
    # A purge is how a shared line, auger or bin is cleared: you run material through it and
    # discard the first output. Trazo recorded the cleaning METHOD and MATERIALS but had no
    # concept of a purge, so the question § 205.272 actually turns on — what happened to the
    # purged material — had nowhere to go. QO asks all three (verified in their live form,
    # 2026-08-19), and the third is the one an inspector cares about: purge material fed to
    # livestock, sold as conventional or discarded are different compliance stories.
    purge_material = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Material run through the equipment to purge it (§ 205.272).",
    )
    purge_quantity = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="Quantity of purge material used, including its unit (e.g. '200 lb').",
    )
    purge_material_end_use = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "What happened to the purge material afterwards — fed to livestock, sold as "
            "conventional, discarded. § 205.272 turns on this, not on the purge itself."
        ),
    )

    # ---- Transport endpoints (§ 205.272 / § 205.307) — parity with QO's Transport activity ----
    #
    # `harvest_destination` is a CATEGORY (stored / sold / handler / feed). It answers "what
    # kind of move" and not "to whom, where" — and for a load going to a custom huller there is
    # no sale, so no SalesRecord carries the counterparty either. QO asks for the name and
    # address of both endpoints, with an explicit "it is on other documentation" escape.
    transport_origin = models.TextField(
        blank=True,
        null=True,
        help_text="Name and address the load left from. Blank if recorded on other documentation.",
    )
    transport_destination_address = models.TextField(
        blank=True,
        null=True,
        help_text="Name and address the load went to. Blank if recorded on other documentation.",
    )

    cleaning_method = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Cleaning method used (pressure wash, manual scrub, steam, etc.)",
    )
    # 2026-08 QO-parity — WHAT was cleaned (§ 205.272(a) commingling prevention).
    cleaning_asset_class = models.CharField(
        max_length=20,
        choices=CLEANING_ASSET_CLASS,
        blank=True,
        null=True,
        help_text="Asset class this cleanout covers (equipment, bins, storage, transport)",
    )
    cleaning_materials_used = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Cleaning materials/agents used (must be NOP-approved for organic)",
    )
    cleaned_by = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Person who performed or verified the cleaning",
    )
    shared_with_conventional = models.BooleanField(
        default=False,
        help_text="Whether this equipment is shared between organic and conventional operations",
    )
    cleaning_protocol_reference = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Reference to cleaning SOP or protocol used (e.g., SOP-CLEAN-001)",
    )

    # §E-5 — Custom operators and the cleaning event that covers a shared-equipment operation.
    #
    # In the UC Davis 2024 organic-almond study, cover-crop seeding, flame weeding, brush
    # shredding, winter sanitation, harvest and hulling are all custom-hired, and custom harvest
    # equipment moves between conventional and organic orchards on the same day. That is exactly
    # the § 205.272 commingling exposure — but the operation had no way to say "this pass was run
    # by a contractor" or "this is the cleaning that preceded it".
    #
    # Deliberately NOT a Custom Operator entity: the operator's NAME already has a home in
    # `performed_by`, and a contact/rate/scheduling record would be farm-management drift.
    operator_is_custom = models.BooleanField(
        default=False,
        help_text=(
            "Whether a custom operator (contractor) performed this operation with their own "
            "equipment. Their name goes in performed_by."
        ),
    )
    equipment_cleaning_event = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operations_covered",
        help_text=(
            "The Equipment Maintenance (EM) cleaning event that covers this operation "
            "(7 CFR 205.272). Linking it turns the page-1 contamination-prevention row from an "
            "aggregate count into per-operation evidence."
        ),
    )

    # NOP Compliance: Post-Harvest Sanitizer Detail (7 CFR 205.272 + § 205.605)
    # Chlorine/peracetic/hydrogen peroxide etc. used in post-harvest brush
    # wash require concentration + rinse-step documentation + a § 205.605
    # reference so an inspector can confirm the sanitizer is on the National
    # List (allowed synthetics in organic crop handling).
    sanitizer_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Sanitizer used (e.g., 'Chlorine (sodium hypochlorite)', 'Peracetic acid', 'Hydrogen peroxide')",
    )
    sanitizer_ppm = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Applied/wash sanitizer concentration in ppm (dose at point of use)",
    )
    # NOP 5026 — chlorine materials. § 205.605(b) caps the RESIDUAL chlorine in
    # water at the point of last crop contact / discharge at the Safe Drinking
    # Water Act MRDL (4 mg/L free chlorine or chloramine; 0.8 mg/L chlorine
    # dioxide). This is distinct from the applied wash dose above.
    sanitizer_residual_ppm_at_discharge = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Residual chlorine (ppm) measured in water at the point of last crop "
            "contact / discharge — must not exceed the SDWA MRDL (4 mg/L free "
            "chlorine/chloramine, 0.8 mg/L chlorine dioxide) per NOP 5026 / § 205.605(b)."
        ),
    )
    rinse_step_documented = models.BooleanField(
        default=False,
        help_text=(
            "Potable-water rinse step performed after sanitizer contact. Whether one is required depends "
            "on the material and its use (7 CFR 205.605(b) sets conditions per material)."
        ),
    )
    sanitizer_nop_reference = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="National List reference (e.g., '§ 205.605(b) - Hydrogen peroxide') or OMRI certificate # for sanitizer",
    )

    # Phase 2 — Seed source drift detector (§ 205.204 / NOP 5029).
    # Populated by post_save signal on Planting (type="PL") events when the
    # seed certification status documents a non-organic source without the
    # required commercial-availability search, or is missing outright.
    # Shape mirrors ChemicalEvent.drift_warning so the frontend banner and
    # audit PDF can handle all three event models uniformly.
    # Null = no finding (either organic seed or no active OSP to compare).
    drift_warning = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Seed source drift payload (§ 205.204 / NOP 5029). Non-null when "
            "a Planting event's seed certification or search documentation is "
            "incomplete or prohibited."
        ),
    )

    def suggest_harvest_lot_code(self):
        """A lot code for this harvest pass, in USDA's own shape: crop + place + date.

        The Guide's worked examples are `OC0603` (Organic Corn, bin 06, 2003) and `B041433`
        (Broccoli, field 04, Julian day 143, 2003) — both encode WHAT, WHERE and WHEN. This
        produces a readable equivalent, e.g. `HAS-BLOCK2-20260410`, because a code a grower
        cannot read is a code they will not use on a bin tag.

        Returns None when the inputs for a meaningful code are missing — a lot code built from
        nothing but a date would collide across blocks, which is the failure it exists to stop.

        Two rules learned from running this over the existing records:

        * Every token is stripped to alphanumerics, not just the block. A product named "QA "
          produced the lot code `QA -BLOCKCEA-20251011` — a space inside an identifier that
          gets typed onto a bin tag, read back off it, and matched against a sales record.
        * Same crop + same block + same DAY is a real pattern (a morning pick and an afternoon
          pick), and it was minting one code for both. A lot code that is not unique identifies
          nothing, so a second pass on the same day gets a -2 suffix, a third -3, ordered by
          creation so an existing pass never has its code change under it.
        """
        if self.type != "HA" or not self.date:
            return None

        def _token(value, length):
            return "".join(ch for ch in (value or "") if ch.isalnum())[:length].upper()

        crop = ""
        history = getattr(self, "history", None)
        if history is not None:
            product = getattr(history, "product", None)
            crop = _token(getattr(product, "name", ""), 3)
        what = crop or _token(self.variety, 3)
        where = _token(self.block_id, 8)
        when = self.date.strftime("%Y%m%d")

        if not what and not where:
            return None
        base = "-".join(part for part in (what, where, when) if part)

        # Ordinal within the day/block, so a same-day second pick is distinguishable.
        # Needs a saved row on both sides: an unsaved event cannot be ordered against its
        # siblings, and `history` without a pk cannot be used as a filter value at all.
        # (`exclude(pk=None)` is not a no-op — it becomes `pk IS NULL` and silently drops
        # every row, which would make the first pick of a day look like the second.)
        if history is None or not getattr(history, "pk", None) or not getattr(self, "pk", None):
            return base
        try:
            earlier = (
                type(self)
                .objects.filter(
                    history=history,
                    type="HA",
                    date__date=self.date.date(),
                    block_id=self.block_id,
                    id__lt=self.pk,
                )
                .count()
            )
        except Exception:
            return base
        return base if earlier == 0 else f"{base}-{earlier + 1}"

    def save(self, *args, **kwargs):
        """Assign a harvest lot code when the operator did not supply one.

        Done here rather than in the serializer because a lot code that only exists when the
        record arrived through the web form is not a traceability scheme — the same production
        also gets harvest passes from templates, the API and the COG Pro import, and a pick
        with no lot is exactly the row an inspector cannot follow to a sales record
        (7 CFR 205.103(b)(2)).

        Runs AFTER the insert on create: the same-day ordinal needs this row's own id to know
        how many picks preceded it, so the code is written back in a second, narrow UPDATE.
        Never overwrites a value already present — an operator's own scheme wins.
        """
        super().save(*args, **kwargs)

        if self.type != "HA" or self.harvest_lot_code:
            return

        # Django's signature is save(force_insert, force_update, using, update_fields), and
        # every one of those is legal POSITIONALLY. Reading only `kwargs` meant a caller
        # writing `obj.save(False, False, None, ["description"])` looked like a full save, so
        # the lot code got written on top of someone else's narrow update — the exact
        # widening this guard exists to prevent. Resolve from args first, then kwargs.
        using = args[2] if len(args) > 2 else kwargs.get("using")
        update_fields = args[3] if len(args) > 3 else kwargs.get("update_fields")

        # An explicit update_fields that does not mention the code means the caller is
        # touching something else; assigning here would widen their write unexpectedly.
        if update_fields is not None and "harvest_lot_code" not in update_fields:
            return

        suggested = self.suggest_harvest_lot_code()
        if not suggested:
            return
        self.harvest_lot_code = suggested
        # `using` is carried through so the write-back lands on the same connection as the
        # insert it belongs to, rather than silently defaulting.
        super().save(update_fields=["harvest_lot_code"], using=using)

    def clean(self):
        """Model-level validation for production event values and business logic"""
        errors = {}

        # Validate area_covered - must be positive for most operations
        # Equipment Maintenance (EM), Pollination (PO), and Post-Harvest Processing (PH)
        # can have area_covered=0 (facility/equipment-based, not field-based).
        if self.area_covered is not None and self.area_covered <= 0 and self.type not in ("EM", "PO", "PH"):
            errors["area_covered"] = "Area covered must be greater than 0"

        # Validate transportation_distance - cannot be negative
        if self.transportation_distance is not None and self.transportation_distance < 0:
            errors["transportation_distance"] = "Transportation distance cannot be negative"

        # Validate yield_quantity - cannot be negative
        if self.yield_quantity is not None and self.yield_quantity < 0:
            errors["yield_quantity"] = "Yield quantity cannot be negative"

        # Validate equipment_hours - cannot be negative
        if self.equipment_hours is not None and self.equipment_hours < 0:
            errors["equipment_hours"] = "Equipment hours cannot be negative"

        # WS-4: multi-day harvest window — end date cannot precede the start (event date)
        if self.harvest_date_end and self.date and self.harvest_date_end < self.date.date():
            errors["harvest_date_end"] = "Harvest end date cannot be before the harvest start date"

        # §E-5 — the cleaning link must be capable of being evidence.
        # A cleaning performed AFTER the organic pass does not protect that pass (§ 205.272), and
        # a link to a non-cleaning event or to another production's record is not a record of
        # this one. Better to refuse the link than to print a page-1 PASS that rests on it.
        cleaning = self.equipment_cleaning_event
        if cleaning is not None:
            if cleaning.pk == self.pk:
                errors["equipment_cleaning_event"] = "An operation cannot be its own cleaning record."
            elif cleaning.type != self.EQUIPMENT_MAINTENANCE:
                errors["equipment_cleaning_event"] = (
                    "The linked event must be an Equipment Maintenance (EM) cleaning event."
                )
            elif self.history_id and cleaning.history_id != self.history_id:
                errors["equipment_cleaning_event"] = (
                    "The cleaning event must belong to the same production as this operation."
                )
            elif self.date and cleaning.date and cleaning.date > self.date:
                errors["equipment_cleaning_event"] = (
                    "The cleaning event is dated after this operation, so it cannot be the "
                    "cleaning that protected it (§ 205.272). Link the cleaning that preceded it."
                )

        # Business logic validation: reasonable area coverage
        if self.area_covered and self.area_covered > 1000:  # More than 1000 hectares
            errors["area_covered"] = (
                f"Area coverage ({self.area_covered} {self.area_unit}) seems unusually large. Please verify."
            )

        # Business logic: yield efficiency checks
        if self.yield_quantity and self.area_covered and self.yield_quantity > 0 and self.area_covered > 0:
            yield_per_hectare = float(self.yield_quantity) / float(self.area_covered)
            # Example check for unreasonably high yields (varies by crop)
            if self.yield_unit in ["kg", "tons"] and yield_per_hectare > 100000:  # 100 tons per hectare
                errors["yield_quantity"] = (
                    f"Yield rate ({yield_per_hectare:.1f} {self.yield_unit}/ha) seems unreasonably high. Please verify."
                )

        # Transportation efficiency check
        if self.transportation_distance and self.transportation_distance > 500:
            errors["transportation_distance"] = (
                f"Transportation distance ({self.transportation_distance} {self.transportation_unit}) is very long. Consider local processing to reduce carbon footprint."
            )

        # 7 CFR 205.204(a)(1): non-organic seed or planting stock is permitted only when an
        # equivalent organic variety is not commercially available, so the record must show
        # the ground for that determination. Zero documented suppliers means no ground at all.
        #
        # ⚠️ Not "at least 3". § 205.204 sets no count; three is a certifier expectation from
        # USDA's optional Guide for Organic Crop Producers. Kept in step with the serializer
        # (which is what the API actually runs — DRF never calls clean()) so the two cannot
        # drift apart again. TR is included: transplanting non-organic nursery stock carries
        # the same obligation and, on a perennial orchard, is the more common record.
        if self.type in SEED_SOURCED_SUBTYPES and self.seed_certification_status in NON_ORGANIC_SEED_STATUSES:
            attempts = self.seed_search_attempts or []
            documented = [
                a
                for a in attempts
                if isinstance(a, dict) and str(a.get("supplier_name") or a.get("supplier") or "").strip()
            ]
            if not documented:
                errors["seed_search_attempts"] = (
                    "Non-organic seed or planting stock may only be used when an equivalent "
                    "organic variety is not commercially available (7 CFR 205.204(a)(1)). "
                    "Record at least one supplier contacted in seed_search_attempts; "
                    "certifiers typically look for three."
                )

        # NOP 7 CFR 205.203(c)(1): Raw manure harvest interval. Blocks harvest entries
        # scheduled inside the unsafe window (90 or 120 days, by crop soil-contact flag).
        # Composted events that meet 205.203(c)(2) (temp >=131F + turnings >=5) do not trigger.
        # Bypass with obj.skip_manure_validation = True for historical data imports.
        if self.type == "HA" and not getattr(self, "skip_manure_validation", False):
            manure_error = self._validate_raw_manure_harvest_interval()
            if manure_error:
                errors["date"] = manure_error

        if errors:
            raise ValidationError(errors)

    def _validate_raw_manure_harvest_interval(self):
        """
        NOP 7 CFR 205.203(c)(1) raw-manure harvest-interval validator.

        Returns an error message string if the harvest date violates the 90/120-day
        window after a raw manure application on the same parcel; None otherwise.

        "Raw" means the source SoilManagementEvent does NOT satisfy the 205.203(c)(2)
        compost exception (temp >=131F + turnings >=5). Once the most recent non-exempt
        manure event is found, no need to check older ones — they age, they don't get fresher.
        """
        from datetime import timedelta

        from history.models import SoilManagementEvent

        if not self.date or not self.history or not self.history.parcel:
            return None

        from history.services.manure_interval import minimum_interval_days

        # Unknown crop: 120, the floor that satisfies both paragraphs.
        interval_days = minimum_interval_days(getattr(self.history, "crop_type", None))

        # SoilManagementEvent lives in a module registered after this one, so it is imported in
        # this method (above), not at the top: a top-level import would register it early.
        parcel_id = self.history.parcel_id
        manure_events = SoilManagementEvent.objects.filter(
            history__parcel_id=parcel_id,
            manure_application_date__isnull=False,
            manure_application_date__lte=self.date.date(),
        ).order_by("-manure_application_date")

        for ev in manure_events:
            # Skip events that satisfy the 205.203(c)(2) compost exception.
            # (c)(2) requires: C:N 25:1–40:1 + 131–170°F + method-specific duration
            # (windrow: 15d @temp + 5 turnings; static/in-vessel: 3d @temp).
            peak_temp = ev.compost_peak_temp_f
            turnings = ev.compost_turning_count
            duration = ev.compost_duration_days_at_temp
            cn = ev.compost_initial_cn_ratio
            method = ev.compost_method
            cn_ok = cn is not None and 25.0 <= float(cn) <= 40.0
            temp_ok = peak_temp is not None and 131.0 <= float(peak_temp) <= 170.0
            if method == "windrow":
                duration_ok = (duration or 0) >= 15 and (turnings or 0) >= 5
            elif method in ("static_aerated", "in_vessel"):
                duration_ok = (duration or 0) >= 3
            else:
                duration_ok = False  # Missing method — (c)(2) cannot be asserted.
            compost_exempt = cn_ok and temp_ok and duration_ok
            if compost_exempt:
                continue

            # NOP 5006 processed-manure exemption: manure processed to reduce
            # pathogens is exempt from the (c)(1) interval when the processing is
            # documented (peak temperature and/or an OMRI/supplier attestation).
            # Undocumented "processed_5006" falls through and is treated as raw.
            processed_5006_exempt = ev.manure_treatment == "processed_5006" and (
                ev.processed_manure_temp_f is not None or bool((ev.processed_manure_attestation or "").strip())
            )
            if processed_5006_exempt:
                continue

            application_date = ev.manure_application_date
            safe_harvest_date = application_date + timedelta(days=interval_days)
            if self.date.date() < safe_harvest_date:
                days_remaining = (safe_harvest_date - self.date.date()).days
                return (
                    f"NOP 7 CFR 205.203(c)(1): Harvest date {self.date.date()} is inside the "
                    f"{interval_days}-day raw-manure safety window. Last raw manure applied on "
                    f"{application_date}; earliest organic-eligible harvest is "
                    f"{safe_harvest_date} ({days_remaining} days after this harvest). "
                    f"Adjust the harvest date or confirm the amendment met 7 CFR 205.203(c)(2) "
                    f"compost requirements: initial C:N 25:1–40:1, 131–170°F, plus "
                    f"method-specific duration (windrow 15+ days with 5+ turnings; "
                    f"static aerated / in-vessel 3+ days)."
                )

            # Most recent non-exempt event is outside the window; older events are
            # guaranteed to be even older. No need to scan further.
            return None

        return None
