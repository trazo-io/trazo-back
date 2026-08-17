from datetime import datetime

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
    area = models.FloatField(help_text="Parcel area in hectares")
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

    def is_transparency_ready(self):
        """Check if parcel has sufficient transparency data for consumer display"""
        has_description = bool(self.description and len(self.description.strip()) >= 10)
        has_practices = bool(
            self.agricultural_details.get("sustainability_practices")
            or self.agricultural_details.get("cover_crop_management")
            or self.agricultural_details.get("carbon_sequestration_practices")
        )
        has_images = bool(self.album and self.album.images.exists())

        return has_description and (has_practices or has_images)

    def get_transparency_score(self):
        """Calculate transparency readiness score (0-100) for consumer confidence"""
        score = 0

        # Description quality (40 points)
        if self.description and len(self.description.strip()) >= 10:
            description_length = len(self.description.strip())
            if description_length >= 100:
                score += 40
            elif description_length >= 50:
                score += 30
            else:
                score += 20

        # Sustainability practices (30 points)
        if (
            self.agricultural_details.get("sustainability_practices")
            or self.agricultural_details.get("cover_crop_management")
            or self.agricultural_details.get("carbon_sequestration_practices")
        ):
            score += 30

        # Visual documentation (20 points)
        if self.album and self.album.images.exists():
            image_count = self.album.images.count()
            if image_count >= 3:
                score += 20
            elif image_count >= 1:
                score += 15

        return min(100, score)

    def finish_current_history(self, history_data, images):
        if self.current_history is not None:
            self.current_history.finish(history_data, images)
            history = self.current_history
            self.current_history = None
            self.save()
            return history
        return None


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
