"""Chemical applications."""

import decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from carbon.choices import FUEL_TYPES
from common.field_registry import (
    APPLICATION_METHOD,
    APPLIED_SCOPE,
    CHEMICAL_SUBTYPE,
    ORGANIC_APPROVED,
    UNIT_APPLICATION_RATE,
    UNIT_AREA,
    UNIT_FUEL,
    UNIT_VOLUME,
)

from .common_event import CommonEvent


class ChemicalEvent(CommonEvent):
    FERTILIZER = "FE"
    PESTICIDE = "PE"
    FUNGICIDE = "FU"
    HERBICIDE = "HE"

    CHEMICAL_EVENTS = (
        (FERTILIZER, "Fertilizer"),
        (PESTICIDE, "Pesticide"),
        (FUNGICIDE, "Fungicide"),
        (HERBICIDE, "Herbicide"),
    )

    # Combined choices imported from common/field_registry.py (SSOT)
    CHEMICAL_SUBTYPE_CHOICES = CHEMICAL_SUBTYPE

    type = models.CharField(max_length=2, choices=CHEMICAL_EVENTS, blank=True, null=True)

    # Chemical subtype for accurate carbon emission factor selection
    # This field determines which emission factor to use in carbon calculations
    chemical_subtype = models.CharField(
        max_length=30,
        choices=CHEMICAL_SUBTYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Specific subtype of chemical for accurate carbon emission calculations. "
        "Different subtypes have different manufacturing emission factors.",
    )
    commercial_name = models.CharField(max_length=60, blank=True, null=True)
    volume = models.CharField(max_length=60, blank=True, null=True)
    concentration = models.CharField(max_length=60, blank=True, null=True)
    # The operator's statement that the source record does not show a fact, instead of a value
    # nobody observed (overall review 2026-11, OV-FJ-C12). The flag or the value, never both;
    # the rule and the printed wording live in `history/services/not_on_source_record.py`.
    # A record with `time_not_recorded` keeps its date, stored at noon UTC like an imported
    # day-only row, and no reader prints that noon.
    concentration_not_recorded = models.BooleanField(
        default=False,
        verbose_name="Concentration not on the source record",
        help_text="The operator stated the source record does not show the product concentration.",
    )
    time_not_recorded = models.BooleanField(
        default=False,
        verbose_name="Time not on the source record",
        help_text=(
            "The operator stated the source record does not show the clock time of the application. "
            "The date is kept, stored at noon UTC (the importer's encoding for a day without a time)."
        ),
    )
    area = models.CharField(max_length=60, blank=True, null=True)
    way_of_application = models.CharField(max_length=60, blank=True, null=True)
    time_period = models.CharField(max_length=60, blank=True, null=True)
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    # New structured fields for better carbon calculations
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    nitrogen_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Nitrogen content percentage"
    )
    phosphorus_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Phosphorus content percentage"
    )
    potassium_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, help_text="Potassium content percentage"
    )
    # NOP 5012 — Approval of Liquid Fertilizers. Certifiers must verify that
    # liquid/soluble fertilizers are not adulterated with prohibited synthetic
    # nitrogen (sodium nitrate is capped at 20% of the crop's N need; synthetic
    # N sources are prohibited under § 205.105(a)). Capturing the nitrogen source
    # lets the audit export flag an unverified or synthetic N source for review.
    NITROGEN_SOURCE_CHOICES = [
        ("organic", "Organic (plant / animal / approved natural source)"),
        ("mined_natural", "Mined / natural — restricted (e.g., sodium (Chilean) nitrate, ≤20% of N need)"),
        ("synthetic_prohibited", "Synthetic — prohibited under § 205.105(a)"),
        ("unknown", "Unknown / not verified"),
    ]
    nitrogen_source = models.CharField(
        max_length=24,
        choices=NITROGEN_SOURCE_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Nitrogen source for a liquid/soluble fertilizer (NOP 5012). Synthetic N is "
            "prohibited (§ 205.105(a)); sodium nitrate is restricted to 20% of the crop's "
            "N requirement (§ 205.602 annotation)."
        ),
    )
    # §E-3 — Micronutrients (FE subtype). NOP § 205.601(j)(7) allows synthetic micronutrients
    # ONLY where a documented soil/plant-tissue deficiency exists, and prohibits their use as a
    # defoliant, herbicide or desiccant. Recording WHICH micronutrient and at what rate is what
    # lets the audit export pair the application with its deficiency record (a soil `ST` or
    # lab-analysis `LA` event) — without both halves the application reads as unsupported at
    # inspection. UC Davis 2024 organic-almond study: zinc sulfate 10 lb/ac and 20% boron at
    # 2 lb/ac foliar post-harvest, plus fertigated boron.
    MICRONUTRIENT_CHOICES = [
        ("zinc", "Zinc (Zn)"),
        ("boron", "Boron (B)"),
        ("manganese", "Manganese (Mn)"),
        ("iron", "Iron (Fe)"),
        ("copper", "Copper (Cu)"),
        ("calcium", "Calcium (Ca)"),
        ("magnesium", "Magnesium (Mg)"),
        ("sulfur", "Sulfur (S)"),
        ("other", "Other"),
    ]
    micronutrient_type = models.CharField(
        max_length=20,
        choices=MICRONUTRIENT_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Micronutrient applied (FE subtype). Permitted under § 205.601(j)(7) only with a "
            "documented deficiency — log the soil OR tissue test that shows it, or the other "
            "verifiable method your certifier approved."
        ),
    )
    micronutrient_rate = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Rate of the micronutrient applied, in micronutrient_rate_unit.",
    )
    micronutrient_rate_unit = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Unit for micronutrient_rate, e.g. lb/ac, kg/ha, gal/ac, ppm.",
    )

    application_method_structured = models.CharField(
        max_length=20,
        choices=APPLICATION_METHOD,
        null=True,
        blank=True,
        help_text="Structured application method",
    )

    # Sprint 3 Epic 3.3: Application Fuel Tracking
    # Tracks fuel consumed by application equipment (sprayers, spreaders, etc.)
    # Important for accurate carbon emissions: application fuel often equals/exceeds manufacturing emissions
    application_fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for application equipment (EPA emission factor selection)",
    )
    application_fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed by application equipment (sprayer, spreader, etc.)",
    )
    application_fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
        blank=True,
        help_text="Fuel unit for application equipment",
    )

    # Environmental context fields for transparency
    weather_conditions = models.CharField(
        max_length=100, blank=True, null=True, help_text="Weather conditions during application for transparency"
    )
    application_timing = models.CharField(
        max_length=100, blank=True, null=True, help_text="When the application was made for consumer understanding"
    )
    target_pest_disease = models.CharField(
        max_length=200, blank=True, null=True, help_text="What problem this application addresses for transparency"
    )
    # USDA's Input Material Application Record has a "Purpose / Reason for Use" column, and its
    # footnote 5 states the reason it matters: "Some materials, for example, are allowed for pest
    # management but not as a soil amendment." § 205.601 lists synthetics BY USE, so the same
    # substance can be allowed for one purpose and prohibited for another — which makes purpose
    # part of the allowability record, not a nicety.
    #
    # `target_pest_disease` already covers the pest-targeting subtypes (PE/FU/HE) and
    # `record_completeness` requires it there. FERTILIZER had no purpose field at all: the event
    # `type` says "a fertilizer went on" and nothing says why, so a micronutrient applied to
    # correct a documented deficiency — the § 205.601(j)(7) condition — was indistinguishable
    # from routine feeding.
    APPLICATION_PURPOSE_CHOICES = [
        ("soil_fertility", "Soil fertility / crop nutrition"),
        ("micronutrient_deficiency", "Correcting a documented micronutrient deficiency"),
        ("soil_amendment", "Soil amendment / organic matter"),
        ("ph_adjustment", "pH adjustment"),
        ("pest_management", "Pest management"),
        ("disease_management", "Disease management"),
        ("weed_management", "Weed management"),
        ("plant_growth", "Plant growth regulation"),
        ("other", "Other (describe in notes)"),
    ]
    application_purpose = models.CharField(
        max_length=32,
        choices=APPLICATION_PURPOSE_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Why this input was applied (USDA Input Material Application Record, "
            "'Purpose / Reason for Use'). Allowability under § 205.601 can depend on the use."
        ),
    )

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    # Sprint 6 Fix: Expanded choices to match frontend organic certification options
    # These detailed options provide better transparency for consumers about organic certification types
    organic_approved = models.CharField(
        max_length=20,
        choices=ORGANIC_APPROVED,
        blank=True,
        null=True,
        help_text="The organic basis the operator recorded for this input (their own statement, not an approval)",
    )
    buffer_zone_meters = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Buffer zone maintained near water sources or sensitive habitats (meters)",
    )

    # WS-4 (2026-08) — § 205.103(b)(2): records must be auditable, which for an application
    # means identifying WHERE it went.
    #
    # Corrected 2026-08-15: this cited (b)(1), which reads "Be adapted to the particular
    # business that the certified operation is conducting" and says nothing about location.
    # The location expectation is (b)(2) audit sufficiency plus USDA's Input Material
    # Application Record, whose column 2 is "Location and Crop".
    # Whole planting vs part; the detail names the part (rows/blocks/area).
    applied_scope = models.CharField(
        max_length=10,
        choices=APPLIED_SCOPE,
        blank=True,
        null=True,
        help_text="Whether this application covered the entire planting or part of it",
    )
    applied_scope_detail = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Which rows/blocks/area were treated, when applied_scope is 'part'",
    )

    # Pesticide application fields. The EPA Worker Protection Standard's application record is
    # 40 CFR 170.311(b)(1) (product, EPA reg. no., active ingredient, site, start/end times, REI);
    # applicator certification for restricted use pesticides is 7 U.S.C. 136j(a)(2)(F), not the WPS.
    applicator_name = models.CharField(
        max_length=150, blank=True, null=True, help_text="Name of the certified applicator who applied the chemical"
    )
    epa_registration_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="EPA registration number from the product label (e.g., 12345-67)",
    )
    restricted_use_pesticide = models.BooleanField(
        default=False, help_text="Whether this is a Restricted Use Pesticide (RUP) requiring certified applicator"
    )
    applicator_certification = models.CharField(
        max_length=100, blank=True, null=True, help_text="Applicator certification/license number (required for RUPs)"
    )
    # F21 (2026-06): GLOBALG.A.P. IFA v6 FV-GFS 32.02.01 #10 — the technically
    # responsible person who AUTHORIZED the plant-protection-product application
    # (often the grower or PCA), distinct from the applicator who applied it.
    authorizer_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Technically-responsible person who authorized the application (GLOBALG.A.P. FV-GFS 32.02.01 #10).",
    )
    rei_hours = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Restricted Entry Interval in hours (worker safety)",
    )
    phi_days = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Pre-Harvest Interval in days (consumer safety)",
    )

    # Item #8: Numeric volume and area fields for accurate carbon calculations
    # The legacy string fields (volume, area) are kept for backward compatibility with existing data.
    # New events should populate these numeric fields instead.
    volume_numeric = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Volume applied (numeric value)",
    )
    volume_unit = models.CharField(
        max_length=20,
        choices=UNIT_VOLUME,
        default="gal",
        blank=True,
        help_text="Volume unit",
    )
    area_numeric = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Area treated (numeric value)",
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )

    # The rate — what the grower says, and what the label is written in.
    #
    # MEASURED 2026-09-02 across two real dictations: "six fluid ounces an acre" and "three and
    # a half pounds an acre". Both are RATES. `volume_numeric` above is a TOTAL ("Total volume of
    # product applied"), so before this column existed the number either landed there — wrong by
    # the whole acreage, on the value the certifier packet, the carbon calculation and CA PUR all
    # read — or was dropped so the record simply lost it.
    #
    # This does NOT replace the total. § 205.103(b)(2) mass balance reconciles what was PURCHASED
    # against what was APPLIED, and a rate alone cannot close that; a certifier wants the rate
    # (is it within the label?) AND the total (does it match the invoice?). The two answer
    # different questions, so both columns exist and neither is derived from the other:
    # multiplying rate x area to fabricate a total would assert a number nobody stated.
    application_rate = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        blank=True,
        null=True,
        help_text="Amount of product applied PER unit of land — the label rate, not the total.",
    )
    application_rate_unit = models.CharField(
        max_length=12,
        choices=UNIT_APPLICATION_RATE,
        blank=True,
        default="",
        help_text="Unit for application_rate (e.g. fl oz/acre).",
    )

    # Item #14: Fertigation flag — fertilizer injected through irrigation system.
    # When True, application fuel is skipped to avoid double-counting with the irrigation event.
    is_fertigation = models.BooleanField(
        default=False,
        help_text="Fertigation — fertilizer injected through irrigation system. "
        "Skips application fuel to avoid double-counting with irrigation events.",
    )

    # NOP Compliance: Supplier & Purchase Tracking (7 CFR 205.103)
    # Required for mass-balance audits — purchased inputs must match applied inputs
    supplier_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Input supplier/vendor name for audit trail",
    )
    purchase_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date input was purchased",
    )
    receipt_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chemical_receipts",
        help_text=(
            "The uploaded purchase receipt/invoice FILE behind purchase_invoice. "
            "2026-08-25: the record said 'INV-123' but the packet could not show the "
            "receipt — the farmer was the courier between Trazo's two halves. "
            "Same-establishment enforced in the serializer; embedded in the audit "
            "PDF and copied into the packet ZIP."
        ),
    )
    purchase_invoice = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Purchase invoice or receipt reference number",
    )
    quantity_purchased = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Total quantity purchased (for mass-balance audit reconciliation)",
    )
    quantity_purchased_unit = models.CharField(
        max_length=10,
        choices=UNIT_VOLUME,
        blank=True,
        null=True,
        help_text="Unit for quantity purchased",
    )
    chemical_lot_number = models.CharField(
        max_length=80,
        blank=True,
        null=True,
        help_text=(
            "Manufacturer/supplier lot or batch number of the purchased input — an "
            "explicitly required NOP purchase-record field (CCOF G8.0, Oregon Tilth) for "
            "input traceability and mass-balance. Audit-only; never surfaced to consumers."
        ),
    )

    # Sprint 3 — OMRI / National List cross-reference (7 CFR 205.601/602)
    # Farmer-confirmed OMRI ID (nullable) and auto-suggested National List match (nullable).
    # See certifications.services.omri_verifier for the matching logic.
    wsda_material = models.ForeignKey(
        "certifications.WSDAMaterial",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="chemical_events",
        help_text=(
            "WSDA Materials List row the operator attached in the input lookup. Co-equal with "
            "OMRI for CCOF, and for 23 of the 42 seeded WSDA brands (Feather Meal 13-0-0, "
            "AzaMax, Kaligreen, Madex HP …) it is the ONLY third-party listing that exists — "
            "so without this field those inputs could never be more than grower-reported, no "
            "matter what the catalogue held. Written only by the operator's tap, never by the "
            "fuzzy name matcher: see consumer-omri-listing-leak-2026-08-09."
        ),
    )
    omri_product = models.ForeignKey(
        "certifications.OMRIProduct",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="chemical_events",
        help_text="Farmer-confirmed OMRI product ID (reported, not Trazo-verified)",
    )
    national_list_substance = models.ForeignKey(
        "certifications.NationalListSubstance",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="chemical_events",
        help_text="Matched National List entry (7 CFR 205.601/602). Read it through "
        "`confirmed_national_list_substance`: only an exact, alias or operator basis is a classification.",
    )
    # OSP alignment audit, Phase 5 slice 1 (2026-10-02): how the classification above was made. Until
    # now every match, from an exact name to a substring guess, landed in the one FK and the packet
    # cited a § listing for each. Rows classified before this field existed carry `legacy_unverified`:
    # their method is not inferred from today's rules.
    NL_BASIS_EXACT = "exact"
    NL_BASIS_ALIAS = "alias"
    NL_BASIS_OPERATOR = "operator"
    NL_BASIS_LEGACY = "legacy_unverified"
    NL_BASIS_CHOICES = [
        (NL_BASIS_EXACT, "Exact name match"),
        (NL_BASIS_ALIAS, "Curated alias"),
        (NL_BASIS_OPERATOR, "Set by the operator"),
        (NL_BASIS_LEGACY, "Recorded before the basis was kept; not verified"),
    ]
    #: The bases that make the FK a classification a document may cite.
    NL_CONFIRMED_BASES = frozenset({NL_BASIS_EXACT, NL_BASIS_ALIAS, NL_BASIS_OPERATOR})
    national_list_basis = models.CharField(max_length=20, choices=NL_BASIS_CHOICES, blank=True, default="")
    #: A substring or container match: a possible listing, never a classification, never cited.
    national_list_suggestion = models.ForeignKey(
        "certifications.NationalListSubstance",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
        help_text="Possible National List entry from a partial name match. Not a classification.",
    )

    @property
    def confirmed_national_list_substance(self):
        """The National List classification a document or a claim may use, or None.

        Only an exact or curated-alias match, or one the operator set, qualifies. A legacy row whose
        basis was never recorded, and a partial-name suggestion, are not classifications.
        """
        if self.national_list_substance_id and self.national_list_basis in self.NL_CONFIRMED_BASES:
            return self.national_list_substance
        return None

    # Sprint 5.1 — Drift detector. Populated by post_save signal when the input
    # used on this event is not in the establishment's active OSP.approved_*.
    # Null = no drift (either input is approved or no active OSP to compare to).
    # Shape: see certifications.services.drift_detector.build_drift_warning().
    drift_warning = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Drift detector payload (7 CFR 205.400(f)(2)). Non-null when this "
            "event's input is not in the active OSP's approved_inputs — treated "
            "as an operation change requiring certifier notification."
        ),
    )

    # P0-3 — CA DPR Restricted Materials Permit (California state law).
    # Required for county-restricted materials (copper hydroxide, sulfur,
    # pyrethrin, spinosad, rotenone) even when NOP-allowed under § 205.601.
    # Enforcement is county Ag Commissioner — permit # + county + expiry
    # are surfaced to the inspector via the drift-finding sub-badge.
    ca_dpr_permit_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="CA DPR Restricted Materials Permit # issued by the county Ag Commissioner",
    )
    ca_dpr_permit_county = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="CA county that issued the permit (e.g., 'San Diego', 'Fresno')",
    )
    ca_dpr_permit_expires = models.DateField(
        blank=True,
        null=True,
        help_text="Expiration date of the CA DPR restricted-materials permit",
    )

    # ------------------------------------------------------------------
    # F20 (2026-06): Legal spray-record completeness.
    # Lets one Trazo chemical event double as (a) the CA legal pesticide-use
    # record / monthly PUR (DPR-PML-017C) and (b) a GLOBALG.A.P. IFA v6
    # FV-GFS 32.02.01 PPP application record. All nullable — only the CA fields
    # matter for a CA establishment; GG needs manufacturer + start/end + dose.
    # ------------------------------------------------------------------
    # Universal (GLOBALG.A.P. + DPR box 28 + traceability)
    manufacturer = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Product manufacturer/registrant (GLOBALG.A.P. FV-GFS 32.02.01; DPR-PML-017C box 28). "
        "commercial_name holds the brand/trade name.",
    )
    # ⏱️ WALL CLOCK, not an instant (convention, verified 2026-08-31).
    #
    # These are filled from `datetime-local` inputs, which carry no offset. With
    # TIME_ZONE="UTC" and USE_TZ=True, DRF makes the naive value aware AS UTC, so a Ventura
    # grower typing 14:30 gets 14:30Z stored -- seven hours off as an instant, and exactly
    # right as the wall clock they wrote down. Every reader honours that: the frontend
    # `formatDateTime` renders in UTC and `pur_export_service` prints boxes 17/18 verbatim
    # (DPR wants local time) -- those two are the ONLY consumers of these columns.
    # `cogpro_import._as_event_datetime` encodes imported dates to match. Nothing computes an
    # interval from them: § 205.203(c)'s safe-harvest date is derived from
    # `manure_application_date` (a DateField) and REI/PHI are stored durations.
    #
    # So do not "correct" this one field, or one form, to send a real offset: a half-migration
    # shifts printed compliance times by the offset while the rest of the system still reads
    # UTC. Doing it properly means a per-establishment timezone column (none exists today), a
    # data migration for stored rows, and farm-local rendering on every surface.
    application_start = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Date/time the application started (3 CCR 6624(c)(2) / DPR box 17).",
    )
    application_end = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Date/time the application completed (3 CCR 6624(c)(2) / DPR box 18).",
    )
    # CA requires BOTH total planted acreage (box 9) AND acreage treated (the
    # existing `area` field / box 19). They differ for band/spot/strip treatments.
    planted_area = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="Total planted acres/units at the site (DPR-PML-017C box 9). Distinct from `area` (acreage treated).",
    )
    planted_area_unit = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Unit for planted_area (acres, ha, sq_ft, units).",
    )
    # CA Pesticide Use Report identity (only relevant for CA establishments).
    operator_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Operator ID / permit number issued by the county Ag Commissioner (DPR box 3). "
        "Required for ALL CA ag pesticide use, not only restricted materials.",
    )
    site_id = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="County-issued site identification number, 1-8 chars (DPR box 8).",
    )
    application_county = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="County where the application was performed (DPR box 10).",
    )
    mtrs_section = models.CharField(max_length=20, blank=True, null=True, help_text="Legal section (DPR box 11).")
    mtrs_township = models.CharField(max_length=20, blank=True, null=True, help_text="Township N/S (DPR box 12).")
    mtrs_range = models.CharField(max_length=20, blank=True, null=True, help_text="Range E/W (DPR box 13).")
    mtrs_base_meridian = models.CharField(
        max_length=20, blank=True, null=True, help_text="Base & Meridian: H/M/S (DPR box 14)."
    )
    ffm_code = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text=(
            "DPR method code (PUR box 21). Two rules feed this ONE field. (1) Fumigation: the "
            "4-digit field fumigation method code, 3 CCR 6624(c)(8). (2) Schoolsites: any method "
            "on ground within 1/4 mile of a schoolsite, 3 CCR 6691 via 6434(6)(A) and 6626(c) — "
            "DPR ENF 25-16, effective 2026-01-01 under AB 1864, which REPURPOSED this same "
            "4-digit field rather than adding a box. NEVER scope this to fumigation alone: a "
            "ground rig (5101), airblast (5102) or drip line (5162) near a school owes a code too. "
            "Aircraft is the one method that owes none, 3 CCR 6691(a)(1)."
        ),
    )
    # Who made the application: the operation itself, or a licensed pest control business
    # hired for the pass. This is the switch the CA monthly PUR is keyed on. 3 CCR 6626(b)
    # makes the BUSINESS the reporter for its own applications (within 7 days, with a copy
    # to the grower within 30), and CDPR's PUE Compendium Vol. 1 Ch. 4 p. 4-8 is explicit:
    # "The grower or property operator should not include applications made by pest control
    # businesses on his/her use report to the county." Without this flag every spray on the
    # farm was exported as the grower's own, so a hired application was reported twice —
    # once by the business, once by us. The grower still KEEPS the record (3 CCR 6624(d)),
    # so the event stays; only the PUR export treats it differently.
    applied_by_pcb = models.BooleanField(
        default=False,
        help_text=(
            "Applied by a licensed pest control business (for hire), not by the operation. "
            "Excluded from the grower's CA PUR — the business files its own (3 CCR 6626(b))."
        ),
    )
    pcb_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Name of the pest control business that made the application (3 CCR 6626(c); PUE Compendium 4-7).",
    )
    # Tank-mix partners (adjuvants / spreader-stickers) applied together with the
    # primary product. CA-registered adjuvants ARE reportable to the PUR and each
    # needs its OWN DPR-PML-017C line (boxes 23/24), so this is a structured list —
    # each partner emits a separate PUR row. Shape (per item):
    #   {"commercial_name": str, "manufacturer": str, "epa_registration_number": str,
    #    "volume": str, "volume_unit": str, "organic_approved": bool}
    # Audit/compliance field; never surfaced to consumers.
    tank_mix_partners = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Tank-mix partners (adjuvants/spreader-stickers) applied with the primary "
            "product. Each CA-registered partner is reportable on its own PUR line "
            "(boxes 23/24). List of {commercial_name, manufacturer, "
            "epa_registration_number, volume, volume_unit, organic_approved}."
        ),
    )

    # ------------------------------------------------------------------
    # Tank mix (overall review 2026-11, OV-RK-C04 / OV-FJ-C10). Several products sprayed from
    # ONE tank are written as one FULL record per product (and per parcel or block), never as a
    # header with product lines: every reader (packet, CA PUR, National List, drift, purchases,
    # receipts, corrections, Activity) already works one product per record. These three columns
    # say which records shared a tank, and in which order the products were listed.
    #
    # NOT `application_group`. That one means "one product over several parcels": the purchase
    # table counts a group's purchase once and a receipt is shared across a group, so a tank on
    # it would drop every product's purchase but one. Each line keeps its own `application_group`
    # across parcels, derived from the tank id and the line number (`history/services/tank_mix.py`).
    #
    # A single product is not a tank: all three stay empty. Old records keep `tank_mix_partners`
    # exactly as they print today; nothing splits them into records (that would add rows and
    # carbon entries to sealed seasons and invent values nobody recorded).
    #
    # `editable=False` on all three: they are written once, by the tank write path, and a
    # correction can never move a record into or out of a tank, or reorder it.
    # ------------------------------------------------------------------
    TANK_MIX_ROLE_PRODUCT = "product"
    TANK_MIX_ROLE_ADJUVANT = "adjuvant"
    TANK_MIX_ROLE_CHOICES = [
        (TANK_MIX_ROLE_PRODUCT, "Product"),
        (TANK_MIX_ROLE_ADJUVANT, "Adjuvant / spreader-sticker"),
    ]
    tank_mix_group = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
        db_index=True,
        help_text="Shared by the records of the products sprayed from one tank (client-minted; idempotency key).",
    )
    tank_mix_line = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        editable=False,
        help_text="This product's line in its tank, 1..N, in the order the operator listed them.",
    )
    tank_mix_role = models.CharField(
        max_length=10,
        choices=TANK_MIX_ROLE_CHOICES,
        blank=True,
        default="",
        editable=False,
        help_text="What this line is in its tank: a product, or an adjuvant / spreader-sticker. Blank outside a tank.",
    )

    # ------------------------------------------------------------------
    # State application facts (overall review 2026-11, OV-FJ-C11 / OV-RK-C03).
    # WAC 16-228-1320(1) (WSR 25-22-065, effective 2026-01-01) asks every person applying
    # pesticides to more than one acre of agricultural land in Washington to record, among
    # others: (e) the wind direction and estimated speed in mph and the temperature in degrees
    # Fahrenheit at the time of application, (h) the concentration, which "may be recorded as"
    # gallons per acre of output volume, (k) the apparatus license plate number, (l) the
    # licensed applicator's address and telephone number, and (n) for a commercial application,
    # the firm's address. Wind and temperature matter for drift in every state, so the form asks
    # them everywhere. All optional and typed by the operator: nothing here is derived.
    # Printing lives in `history/services/application_conditions.py`.
    # ------------------------------------------------------------------
    WIND_FROM_CHOICES = [
        ("N", "N"),
        ("NE", "NE"),
        ("E", "E"),
        ("SE", "SE"),
        ("S", "S"),
        ("SW", "SW"),
        ("W", "W"),
        ("NW", "NW"),
        ("calm", "Calm"),
    ]
    wind_from = models.CharField(
        max_length=4,
        choices=WIND_FROM_CHOICES,
        blank=True,
        default="",
        verbose_name="Wind blowing from",
        help_text="The compass point the wind was blowing FROM at the time of application, or calm.",
    )
    wind_speed_mph = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(150)],
        verbose_name="Wind speed (mph)",
        help_text="Estimated wind speed in miles per hour at the time of application.",
    )
    air_temperature_f = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(-40), MaxValueValidator(140)],
        verbose_name="Air temperature (°F)",
        help_text="Air temperature in degrees Fahrenheit at the time of application.",
    )
    # The carrier (usually water) the product went out in. Not a product amount: `volume_numeric`
    # is the product, `concentration` the label strength, and before this column a spray had no
    # place to say "100 gallons of water per acre".
    CARRIER_VOLUME_UNIT_CHOICES = [
        ("gal_per_acre", "gal/acre"),
        ("gal_total", "gal total"),
        ("l_per_ha", "L/ha"),
    ]
    carrier_volume = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(decimal.Decimal("0.01"), message="The carrier volume must be greater than zero.")
        ],
        verbose_name="Carrier (water) volume",
        help_text="Volume of carrier (usually water) in the spray, in carrier_volume_unit.",
    )
    carrier_volume_unit = models.CharField(
        max_length=12,
        choices=CARRIER_VOLUME_UNIT_CHOICES,
        blank=True,
        default="",
        verbose_name="Carrier volume unit",
    )
    apparatus_license_plate = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name="Apparatus license plate",
        help_text="License plate number of the application apparatus, when it has one.",
    )
    # COPIES, not a link. The applicator's address and phone are typed (or, later, copied from a
    # profile) onto THIS record at save, so editing a profile can never rewrite a past record.
    applicator_address = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Applicator address",
        help_text="The licensed applicator's complete address, as it was when this application was made.",
    )
    applicator_phone = models.CharField(
        max_length=40,
        blank=True,
        default="",
        verbose_name="Applicator phone",
        help_text="The licensed applicator's telephone number, as it was when this application was made.",
    )
    commercial_firm_address = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Commercial firm address",
        help_text="Complete address of the pest control business, for an application made for hire.",
    )

    def clean(self):
        """
        Model-level validation for NPK percentages, EPA compliance, and business logic
        """
        from django.core.exceptions import ValidationError

        errors = {}

        # Validate individual NPK percentages are within range
        for field_name, percentage in [
            ("nitrogen_percentage", self.nitrogen_percentage),
            ("phosphorus_percentage", self.phosphorus_percentage),
            ("potassium_percentage", self.potassium_percentage),
        ]:
            if percentage is not None:
                if percentage < 0:
                    errors[field_name] = f'{field_name.replace("_", " ").title()} cannot be negative'
                if percentage > 100:
                    errors[field_name] = f'{field_name.replace("_", " ").title()} cannot exceed 100%'

        # Validate total NPK doesn't exceed 100%
        if (
            self.nitrogen_percentage is not None
            and self.phosphorus_percentage is not None
            and self.potassium_percentage is not None
        ):
            # These are DecimalFields, so a value loaded from the database is a Decimal —
            # but a value assigned in Python (a float off deserialised JSON, a template
            # default, a management command) stays a float until it round-trips. Summing a
            # mix raises `TypeError: unsupported operand type(s) for +: 'decimal.Decimal'
            # and 'float'`, which is an unhandled 500 out of clean()/full_clean() rather
            # than a validation error. Reproduced 2026-08-10 on a bare instance with N as
            # Decimal and P as float — no database or fixture involved.
            #
            # Decimal(str(x)) rather than Decimal(x): the latter converts a float's binary
            # representation exactly, so 10.5 would become 10.5000000000000017763568394...
            # and leak into the error message the grower reads.
            def _as_decimal(value):
                return value if isinstance(value, decimal.Decimal) else decimal.Decimal(str(value))

            total_npk = (
                _as_decimal(self.nitrogen_percentage)
                + _as_decimal(self.phosphorus_percentage)
                + _as_decimal(self.potassium_percentage)
            )
            if total_npk > 100:
                errors["__all__"] = (
                    f"Total NPK percentages cannot exceed 100%. "
                    f"Current total: {total_npk}% "
                    f"(N: {self.nitrogen_percentage}%, "
                    f"P: {self.phosphorus_percentage}%, "
                    f"K: {self.potassium_percentage}%)"
                )

        # Restricted Use Pesticides: 7 U.S.C. 136j(a)(2)(F), not the Worker Protection Standard
        # Restricted Use Pesticides (RUPs) require certified applicator
        if self.restricted_use_pesticide and not self.applicator_certification:
            errors["applicator_certification"] = (
                "Applicator certification is required for Restricted Use Pesticides (RUPs) "
                "under the federal certified-applicator rule (7 U.S.C. 136j(a)(2)(F))"
            )

        # REI validation - must be non-negative
        if self.rei_hours is not None and self.rei_hours < 0:
            errors["rei_hours"] = "Restricted Entry Interval (REI) cannot be negative"

        # PHI validation - must be non-negative
        if self.phi_days is not None and self.phi_days < 0:
            errors["phi_days"] = "Pre-Harvest Interval (PHI) cannot be negative"

        # REI reasonableness check (typical range 4-48 hours)
        if self.rei_hours is not None and self.rei_hours > 168:  # More than 7 days
            errors["rei_hours"] = (
                f"REI of {self.rei_hours} hours seems unusually high. " "Please verify against product label."
            )

        # PHI reasonableness check (typical range 0-120 days)
        if self.phi_days is not None and self.phi_days > 365:  # More than 1 year
            errors["phi_days"] = (
                f"PHI of {self.phi_days} days seems unusually high. " "Please verify against product label."
            )

        # Not on the source record: the flag or the value, never both. The stored date is not
        # checked here: whoever sets the flag (the serializer, a correction) moves it to the noon
        # placeholder, and every reader keys on the flag rather than on the clock.
        from history.services.not_on_source_record import conflicts

        errors.update(
            conflicts(
                concentration_not_recorded=self.concentration_not_recorded,
                concentration=self.concentration,
                time_not_recorded=self.time_not_recorded,
                application_start=self.application_start,
                application_end=self.application_end,
            )
        )

        # A carrier volume and its unit: both halves or neither.
        from history.services.application_conditions import carrier_conflicts

        errors.update(carrier_conflicts(self.carrier_volume, self.carrier_volume_unit))

        if errors:
            raise ValidationError(errors)

        super().clean()
