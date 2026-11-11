from datetime import datetime

from django.core.validators import MinValueValidator
from django.db import models

from company.models import Establishment


class Product(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to="product_images", blank=True)

    def __str__(self):
        return self.name


class Parcel(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
    establishment = models.ForeignKey(Establishment, on_delete=models.CASCADE, related_name="parcels")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, blank=True, null=True)
    # MinValueValidator, not just a help_text: a 0 or negative parcel is not a data-entry
    # curiosity, it is a hole in the packet. The certifier dossier reconciles the farm's stated
    # total acreage against the sum of its parcels ("27.9 acres (parcels in this dossier total
    # 27.9 acres)"), and a zero-area parcel makes that line silently wrong while looking
    # arithmetically fine. `validators` only bite where full_clean() runs, so the serializer
    # enforces the same floor on the API path — DRF calls full_clean() on neither create nor
    # update. Smallest allowed value is arbitrary but must be > 0; 0.0001 ha is 1 m².
    area = models.FloatField(
        validators=[MinValueValidator(0.0001)],
        help_text="Parcel area in hectares",
    )
    #: 1 hectare = 2.47105 acres. Lived in six places before 2026-08-20 — `unit_converter`,
    #: `event_carbon_calculator`, a seeder, two spots in `audit_export_service`, and
    #: `common_osp_workbooks` — which is exactly why a seventh surface (the Parcel Application
    #: PDF, the § 205.202 document a certifier works from) printed the hectare value with the
    #: word "acres" beside it and understated a 59.4-acre operation as 24.0.
    HECTARES_TO_ACRES = 2.47105

    @property
    def area_acres(self) -> float:
        """`area` in ACRES.

        `area` is stored in hectares and every US-facing surface — certifier packets, parcel
        applications, workbooks, the consumer page — needs acres. Reading `parcel.area` and
        labelling it "acres" is the single most repeated unit error in this codebase, so the
        conversion lives on the model that owns the field rather than at each call site.
        """
        return float(self.area or 0) * self.HECTARES_TO_ACRES

    def area_display(self, decimals: int = 1) -> str:
        """ "28.4 acres (11.49 ha)" — the acre figure a US reader wants, with its source.

        Both units, always: a certifier who spots a number that looks like hectares can see
        immediately which one it is, instead of having to divide by 2.47 to find out.
        """
        return f"{self.area_acres:.{decimals}f} acres ({float(self.area or 0):.2f} ha)"

    certified = models.BooleanField(default=False, help_text="Certified by a professional")
    current_history = models.OneToOneField(
        "history.History",
        on_delete=models.SET_NULL,  # SET_NULL so deleting production doesn't delete parcel
        blank=True,
        null=True,
        related_name="current_parcel",
    )
    polygon = models.JSONField(blank=True, null=True)
    map_metadata = models.JSONField(blank=True, null=True)
    # Structured buffer-zone / adjoining-land-use / drift-prevention records per
    # parcel boundary (USDA NOP 7 CFR 205.202(c) buffer requirement; 205.400(f)(1)
    # drift notification). A list of dicts, one per boundary, e.g.:
    #   [{"direction": "North", "adjoining_land_use": "Conventional almond orchard",
    #     "buffer_width_m": 8, "drift_risk": "Medium",
    #     "prevention": "8 m vegetative hedgerow buffer + annual neighbor-notification letter"}]
    # Surfaced in the audit export's Field Map and Buffer Zone sections; empty/None
    # triggers a REVIEW flag for the inspector.
    buffer_zones = models.JSONField(blank=True, null=True)
    # WS-5 (2026-08): container/greenhouse production flag (NOP § 205.2 crop production
    # includes container systems; certifier parcel applications ask this directly —
    # it changes which land-history questions apply, since container media is not land).
    container_production = models.BooleanField(
        default=False,
        help_text="Whether this parcel produces in containers/greenhouse rather than in-ground",
    )
    # WS-5 Parcel Application: the FEW answers with no model home (county, livestock,
    # attestations). Everything that has a real column binds via parcel_field instead —
    # evidence lives once (plan Appendix A §f).
    application_answers = models.JSONField(
        default=dict,
        blank=True,
        help_text="Parcel Application answers that have no dedicated model field",
    )
    # CCOF Parcel Application identity — every parcel record keys to APN + S-T-R.
    apn = models.CharField(
        max_length=40,
        blank=True,
        null=True,
        help_text="Assessor's Parcel Number (APN) — CCOF Parcel Application identifier.",
    )
    section_township_range = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="PLSS Section-Township-Range (e.g. S12 T14S R22E) — CCOF Parcel Application.",
    )
    # CA DPR Site Identification Number, issued by the County Agricultural Commissioner per
    # site (3 CCR 6622; "one to eight characters ... exactly as it was issued by the CAC",
    # DPR-PML-017C instruction 8). PUR box 8. A site is a parcel/commodity, so the number
    # lives here; the PUR export reads the event's own value first and falls back to this.
    ca_site_id = models.CharField(
        max_length=8,
        blank=True,
        null=True,
        help_text="CA DPR Site ID for this parcel (PUR box 8, 1-8 characters as issued by the CAC). California only.",
    )
    # 3 CCR 6691 via 6434(6)(A) and 6626(c); DPR ENF 25-16, effective 2026-01-01 (AB 1864).
    # An application made to produce an agricultural commodity within 1/4 mile of a schoolsite
    # must carry a method code on the NOI and the PUR. The distance is a property of the GROUND,
    # not of the application, so it is asked once per parcel and not on every spray.
    #
    # Deliberately a nullable boolean, three states: True near a school, False checked and not
    # near one, None never asked. None must never be read as False — the export says the answer
    # is missing rather than asserting the parcel is clear, because "we never asked" and "the
    # grower says no" are different facts on a filing the County Agricultural Commissioner keys.
    ca_near_schoolsite = models.BooleanField(
        blank=True,
        null=True,
        default=None,
        help_text=(
            "Is any part of this parcel within 1/4 mile of a schoolsite? Applications here need a "
            "method code on the PUR (3 CCR 6691; DPR ENF 25-16, effective 2026-01-01). California only."
        ),
    )
    date_began_managing = models.DateField(
        blank=True,
        null=True,
        help_text="Date the operator began managing this parcel (CCOF Affidavit of Land History).",
    )
    # Prohibited treated-lumber contamination source (7 CFR 205.272) — e.g. arsenate-treated
    # trellis end-posts adjacent to the organic crop.
    treated_lumber_present = models.BooleanField(
        default=False,
        help_text="Whether prohibited treated lumber (e.g. arsenate end-posts) is present on the parcel.",
    )
    treated_lumber_description = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Description / location of the treated lumber and the mitigation in place.",
    )

    # ---- Irrigation pumping plant (§E-6) --------------------------------------------
    # A pump test is an ANNUAL measurement of one plant, and every irrigation event that
    # season should be costed against the same numbers — so these belong to the parcel, not
    # repeated on each event. The UC Davis 2024 organic-almond cost study budgets exactly one
    # January pump test per year (300 ft well, 75 ft pumping level, 125 HP pump).
    #
    # These are what make the corrected irrigation carbon ACCURATE rather than merely
    # defensible: without them the calculator falls back to a 70% efficiency and a
    # method-derived pressure. A grower who measures their plant gets their own figure.
    # See carbon/services/verified_emission_factors._pump_energy_kwh_per_1000gal.
    pump_efficiency_pct = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        blank=True,
        null=True,
        help_text=(
            "Overall pumping-plant efficiency (wire-to-water) from the most recent pump test, "
            "as a percentage. Leave empty to use the 70% default. A neglected plant can fall "
            "below 50%, which RAISES emissions — this is not a field that flatters the farm."
        ),
    )
    system_pressure_psi = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text=(
            "Operating pressure the irrigation system requires, in psi. Added to the lift as "
            "pressure head when computing total dynamic head. Leave empty to derive it from "
            "the irrigation method (drip ~15, micro-sprinkler ~30, sprinkler ~50, flood ~5)."
        ),
    )
    pump_test_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date of the most recent pump test. Efficiency drifts, so an old test is weaker evidence.",
    )
    pump_test_provider = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Who performed the pump test (utility programme, pump company, irrigation district).",
    )
    treated_lumber_install_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the treated lumber was installed (if known).",
    )
    # crop_type removed - now stored in History model for per-production tracking
    soil_type = models.CharField(max_length=50, blank=True, null=True)
    unique_code = models.CharField(max_length=50, blank=True, null=True)
    certification_type = models.CharField(max_length=50, blank=True, null=True)
    contact_person = models.CharField(max_length=60, blank=True, null=True)
    contact_phone = models.CharField(max_length=30, blank=True, null=True)
    contact_email = models.EmailField(max_length=254, blank=True, null=True)
    address = models.CharField(
        max_length=200, blank=True, null=True, help_text="Parcel specific address or location details"
    )

    # ✅ COMPREHENSIVE AGRICULTURAL DATA for Carbon Calculations
    agricultural_details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Detailed agricultural data for carbon footprint calculations and USDA compliance",
    )

    # ✅ CARBON CALCULATION FLAGS
    carbon_calculation_enabled = models.BooleanField(
        default=False, help_text="Enable advanced carbon footprint calculations"
    )

    usda_compliance_eligible = models.BooleanField(
        default=False, help_text="Meets USDA requirements for carbon credit verification"
    )

    # Phase 3 consumer-QR privacy: a public field polygon is a theft/scouting
    # exposure. Farmer-controlled disclosure on the consumer page:
    #   exact       — full polygon + precise map (current behavior, opt-in)
    #   approximate — satellite map near the field, no boundary, center ~1 km
    #   hidden      — no map or geodata, name/area only
    # New parcels default to approximate; existing parcels are grandfathered to
    # exact by the data migration (they were already published that way).
    LOCATION_DISCLOSURE_CHOICES = [
        ("exact", "Exact — field boundary and precise location"),
        ("approximate", "Approximate — general area only (~1 km)"),
        ("hidden", "Hidden — no location shown to consumers"),
    ]
    location_disclosure_level = models.CharField(
        max_length=20,
        choices=LOCATION_DISCLOSURE_CHOICES,
        default="approximate",
        help_text="How precisely this parcel's location is shown on the public consumer page",
    )
    # Whether a HUMAN at this operation has ever chosen the value above.
    #
    # 🔴 2026-08-31. Migration 0013 wrote `exact` onto every parcel that existed when the
    # setting was introduced — correct at the time, because those parcels were already
    # publishing boundaries and silently narrowing that would have changed what farms had
    # agreed to show. But the field was never exposed in the producer app, so those farms
    # have been publishing a field boundary under a setting they were never shown and cannot
    # reach. That is consent by inertia on the most sensitive datum the page carries: the
    # boundary sits beside the harvest date and the yield, which together read as a schedule
    # rather than a provenance claim.
    #
    # This flag distinguishes "chose exact" from "inherited exact", so the prompt can ask only
    # the farms that were never asked. It is NOT a second disclosure setting and must never
    # gate publication on its own — `public_parcel_geo` still reads
    # `location_disclosure_level` alone, and adding a second gate there is how one surface
    # ends up disagreeing with another.
    location_disclosure_choice_made = models.BooleanField(
        default=False,
        help_text=(
            "True once someone at the operation has explicitly confirmed or changed "
            "location_disclosure_level. False means the value was inherited, not chosen."
        ),
    )

    def __str__(self):
        return str(self.id) + " - " + self.name + " - " + self.establishment.name

    @property
    def productions_completed(self):
        return self.histories.filter(finish_date__year=datetime.now().year).count()

    # ✅ AGRICULTURAL DATA ACCESS METHODS
    def get_agricultural_detail(self, field_name, default=None):
        """Get specific agricultural detail field"""
        return self.agricultural_details.get(field_name, default)

    def set_agricultural_detail(self, field_name, value):
        """Set specific agricultural detail field"""
        if not isinstance(self.agricultural_details, dict):
            self.agricultural_details = {}
        self.agricultural_details[field_name] = value

    def has_complete_soil_data(self):
        """Check if soil health data is complete for carbon calculations"""
        required_soil_fields = ["soil_ph", "soil_organic_matter", "soil_nitrogen", "soil_phosphorus", "soil_potassium"]
        return all(field in self.agricultural_details for field in required_soil_fields)

    def has_complete_conservation_data(self):
        """Check if conservation practice data is complete for carbon credits"""
        required_conservation_fields = [
            "cover_crop_management",
            "crop_rotation_pattern",
            "carbon_sequestration_practices",
            "integrated_pest_management",
        ]
        return all(field in self.agricultural_details for field in required_conservation_fields)

    def calculate_carbon_readiness_score(self):
        """Calculate completeness score for carbon calculations (0-100)"""
        total_fields = 37  # Total advanced agricultural fields
        completed_fields = len([k for k, v in self.agricultural_details.items() if v])
        return min(100, (completed_fields / total_fields) * 100)

    def update_usda_compliance_status(self):
        """Update USDA compliance eligibility based on available data"""
        required_usda_fields = [
            "soil_organic_matter",
            "nrcs_practices",
            "organic_certification_status",
            "cover_crop_management",
            "irrigation_efficiency",
        ]
        self.usda_compliance_eligible = all(
            field in self.agricultural_details and self.agricultural_details[field] for field in required_usda_fields
        )

    # 🎯 TRANSPARENCY-FOCUSED METHODS
    def get_transparency_description(self):
        """Get consumer-facing parcel description"""
        return self.description or ""

    def get_sustainability_practices(self):
        """Get sustainability practices narrative for consumers"""
        # Check multiple possible keys due to form field mapping
        return (
            self.agricultural_details.get("sustainability_practices")
            or self.agricultural_details.get("cover_crop_management")
            or self.agricultural_details.get("carbon_sequestration_practices")
            or ""
        )

    # `get_consumer_story()` removed 2026-08-07. The field was dropped from the parcel form
    # and from every surface: it scored nothing, no consumer page rendered it, and its only
    # publisher was the anonymous carbon endpoint. Historic values may still sit inert under
    # agricultural_details["consumer_story" | "consumer_narrative"]; nothing reads them.

    def get_primary_crop(self):
        """Get primary crop focus for this parcel"""
        # Check multiple possible keys due to form field mapping
        return self.agricultural_details.get("primary_crop") or self.agricultural_details.get("crop_focus") or ""

    # `is_transparency_ready()` and `get_transparency_score()` removed 2026-09-09.
    #
    # `get_transparency_score()` was a 0-100 SELF-GRADE of the operation's own documentation
    # (40 points for a 100-character description, 30 for any practices text, 20 for three
    # photos), served on the authenticated parcel payload as `transparency_score` and echoed
    # into the Add-Parcel wizard's copy as "recommended for full points". The transparency
    # score is retired as a CONCEPT, not hidden: a producer surface gets COUNTS and a
    # per-record checklist naming the specific missing document, never a total, a percentage
    # or a grade. See .claude/rules/transparency-first.md.
    #
    # `is_transparency_ready()` was the same arithmetic with the number filed off — a boolean
    # verdict ("description AND (practices OR photos)") over the same self-reported inputs,
    # which is the virtue-label shape, not an escape from it.
    #
    # What replaces them is what already exists and is factual: `parcel_application_status()`
    # (product/services/parcel_application_status.py), which reports WHICH of the five
    # § 205.202 blocks are missing by name. That is the checklist the rule asks for, and it is
    # already on this serializer as `application_status` / `application_missing`.

    def finish_current_history(self, history_data, images):
        if self.current_history is not None:
            return self.finish_history_record(self.current_history, history_data, images)
        return None

    def finish_history_record(self, history, history_data, images):
        """Close the season the CALLER named, not whichever one the pointer happens to hold.

        `current_history` is a single pointer holding the most recently started season. A
        perennial block routinely has two open at once, and closing is irreversible — it makes
        the record read-only and starts the § 205.103(b)(4) retention clock — so the season
        being closed has to be the one the farmer was looking at.

        The pointer is only cleared when it is the season being closed; otherwise the other
        open season keeps it and the parcel page still shows a current production.
        """
        if history is None:
            return None
        history.finish(history_data, images)
        if self.current_history_id == history.id:
            self.current_history = None
            self.save(update_fields=["current_history"])
        return history


class ParcelCropHistory(models.Model):
    """Track annual crop rotation history per parcel for organic audit compliance.

    7 CFR 205.202 requires 36-month field history showing all crops grown
    and substances applied. Inspectors ask: 'What was planted here for the last 3 years?'
    """

    parcel = models.ForeignKey(
        Parcel,
        on_delete=models.CASCADE,
        related_name="crop_history",
        help_text="Parcel this crop history entry belongs to",
    )
    year = models.IntegerField(
        help_text="Calendar year of this crop history entry",
    )
    crop_grown = models.CharField(
        max_length=200,
        help_text="Crop or cover crop grown during this year",
    )
    # 2026-08 QO-parity: orchard reality is a main crop PLUS an alley/winter cover in
    # the same year. One optional companion field keeps the one-row-per-year shape
    # (and its unique_together) instead of forcing a second row that would read as a
    # split field.
    cover_crop = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Cover crop grown between/under the main crop this year (e.g., 'bell beans + oats alley cover')",
    )
    block_id = models.CharField(
        # 50 to match CommonEvent.block_id — same concept, same token, so a block name that fits
        # on an event must fit here. That model is nullable and this one is not: the difference is
        # deliberate, because this column takes part in a unique_together and Postgres treats
        # NULLs as distinct (see Meta below).
        max_length=50,
        blank=True,
        default="",
        help_text=(
            "Optional block, row or section within the parcel — the same free-text identifier "
            "CommonEvent.block_id uses. Lets a SPLIT FIELD be recorded honestly: one crop on "
            "rows 1-40, another on rows 41-80, in the same year."
        ),
    )
    production_method = models.CharField(
        max_length=30,
        choices=[
            ("conventional", "Conventional"),
            ("organic", "Organic"),
            ("transitional", "Transitional"),
            ("regenerative", "Regenerative"),
            ("fallow", "Fallow"),
        ],
        blank=True,
        null=True,
        help_text="Production method used during this year",
    )
    substances_applied = models.TextField(
        blank=True,
        null=True,
        help_text="Summary of all substances applied during this year (for 36-month history)",
    )
    #: USDA Field History / Previous Land Use Record (form #1) asks for three columns per
    #: material — "Material / Product Brand Name", "Manufacturer", "Application Date(s)".
    #: `substances_applied` is a single prose blob and cannot answer them: a certifier
    #: checking a 36-month window needs the DATE, and a blob reading "roundup, some 10-10-10"
    #: does not have one.
    #:
    #: Added ALONGSIDE the blob rather than replacing it, and the blob is NEVER parsed into
    #: this. Splitting prose means guessing which words are a manufacturer and which are a
    #: product, and a guess here lands in an eligibility determination. Operators keep what
    #: they wrote; new detail is entered structured.
    #:
    #: Shape: [{"material": str, "manufacturer": str, "application_dates": str}]
    #: `application_dates` is free text on purpose — USDA's own column is plural
    #: ("Date(s)"), growers write "3/14 and 6/2", and forcing one date would either lose
    #: applications or invent precision.
    substance_applications = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Structured per-material rows for USDA's Field History form: "
            '[{"material", "manufacturer", "application_dates"}]. Complements '
            "substances_applied (free-text summary); never derived from it."
        ),
    )
    last_prohibited_substance = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text=(
            "Name of the LAST prohibited substance applied to this field, e.g. 'Glyphosate'. "
            "Paired with date_last_prohibited to answer the Common OSP Field and Crop "
            "Information form's 'Name and Application Date of Last Prohibited Input' column, "
            "which USDA requires for EVERY field including already-organic ones. Distinct from "
            "substances_applied, which is a free-text summary of ALL substances that year — "
            "the last prohibited one cannot be inferred from that list without guessing."
        ),
    )
    date_last_prohibited = models.DateField(
        blank=True,
        null=True,
        help_text="Date of last prohibited substance application (if any)",
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Additional notes about this year's field use",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # A parcel may grow MORE THAN ONE crop in a year — split fields are ordinary practice,
        # and COG Pro's own data does it (South Field 2011: tomatoes on rows 1-40, melons on
        # rows 41-80). The previous ("parcel", "year") constraint made that unrecordable, which
        # forced a migrating farm to drop half its land history — exactly the history 7 CFR
        # 205.202 asks for.
        #
        # `block_id` carries default="" rather than null: Postgres treats NULLs as distinct, so a
        # nullable column here would silently permit true duplicate rows, and Django 4.1 has no
        # `nulls_distinct` to say otherwise.
        unique_together = ("parcel", "year", "crop_grown", "block_id")
        ordering = ["-year"]
        verbose_name = "Parcel Crop History"
        verbose_name_plural = "Parcel Crop Histories"

    def __str__(self):
        return f"{self.parcel.name} - {self.year}: {self.crop_grown}"


class ParcelPlannedCrop(models.Model):
    """A crop the operation grows now, or plans to grow, on a parcel, with its acreage.

    CCOF ORGB49 A8 ("List crops currently grown (or planned to be grown) on this parcel, and the
    acreage for each crop"), WSDA AGR 2264 ref 8 (crop and variety, estimated harvest date, acres,
    for each crop to be included on the certificate) and OTCO C2 2.1 10) ask the same table. It is
    not `ParcelCropHistory`, which is the § 205.202(b) record of years that have happened, and it is
    not a season (`History`), which carries no acreage. Typed by the operator; never derived.
    """

    parcel = models.ForeignKey(Parcel, on_delete=models.CASCADE, related_name="planned_crops")
    crop = models.CharField(max_length=200, help_text="Crop, as the operation names it, e.g. 'Apples'")
    variety = models.CharField(
        max_length=200, blank=True, default="", help_text="Variety or varieties, e.g. 'Honeycrisp, Gala'"
    )
    expected_harvest = models.DateField(
        blank=True, null=True, help_text="When harvest of this crop is expected to begin (WSDA AGR 2264 ref 8)"
    )
    acres = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Acres of this crop on the parcel. Stated by the operator; never computed from the parcel area.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["parcel_id", "pk"]
        verbose_name = "Parcel Planned Crop"
        verbose_name_plural = "Parcel Planned Crops"

    def __str__(self):
        return f"{self.parcel.name}: {self.crop}"
