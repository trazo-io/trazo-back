import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from backend.storage import private_records_storage

# Configure logging
logger = logging.getLogger(__name__)

# Database-driven Crop Template System


class CropType(models.Model):
    """Model for different crop types with their characteristics"""

    CATEGORY_CHOICES = [
        ("tree_fruit", "Tree Fruit"),
        ("tree_nut", "Tree Nut"),
        ("grain", "Grain"),
        ("oilseed", "Oilseed"),
        ("vegetable", "Vegetable"),
        ("berry", "Berry"),
        ("herb", "Herb"),
        ("legume", "Legume"),
        ("forage", "Forage"),
        ("other", "Other"),
    ]

    # Categories whose edible part does not touch the soil, so the raw-manure floor is
    # 90 days (7 CFR 205.203(c)(1)(iii)). The crop seeder falls back to this for a crop entry
    # that does not state `has_soil_contact`. It is a fallback only: a category does not
    # decide the class ("berry" holds blueberries, off the ground, and strawberries, on it),
    # so seeded crops outside these categories that hold the edible part off the ground
    # state False themselves.
    NO_SOIL_CONTACT_CATEGORIES = ("tree_fruit", "tree_nut")

    name = models.CharField(max_length=100, unique=True, help_text="e.g., Citrus, Almonds")
    slug = models.SlugField(max_length=100, unique=True, help_text="e.g., citrus_oranges")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    description = models.TextField(help_text="Brief description of the crop type")

    # Agricultural characteristics
    typical_farm_size = models.CharField(max_length=100, help_text="e.g., 20-100 hectares")
    growing_season = models.CharField(max_length=100, help_text="e.g., 12 months (evergreen)")
    harvest_season = models.CharField(max_length=100, help_text="e.g., November - April")

    # USDA benchmarks and carbon data
    emissions_per_hectare = models.FloatField(help_text="kg CO2e per hectare")
    industry_average = models.FloatField(help_text="Industry average emissions")
    best_practice = models.FloatField(help_text="Best practice emissions")
    carbon_credit_potential = models.FloatField(help_text="Potential carbon credits per hectare")

    # Economic data
    typical_cost_per_hectare = models.FloatField(help_text="Total production cost per hectare")
    fertilizer_cost_per_hectare = models.FloatField(default=0.0)
    fuel_cost_per_hectare = models.FloatField(default=0.0)
    irrigation_cost_per_hectare = models.FloatField(default=0.0)
    labor_cost_per_hectare = models.FloatField(default=0.0)

    # Premium pricing potential
    organic_premium = models.CharField(max_length=20, default="0%", help_text="e.g., 25-40%")
    sustainable_premium = models.CharField(max_length=20, default="0%", help_text="e.g., 10-20%")
    local_premium = models.CharField(max_length=20, default="0%", help_text="e.g., 5-15%")

    # Sustainability opportunities
    sustainability_opportunities = models.JSONField(default=list, help_text="List of sustainability practices")

    # Meta information
    usda_factors_used = models.BooleanField(default=False)
    data_source = models.CharField(max_length=200, default="USDA Agricultural Research Service")
    is_active = models.BooleanField(default=True)
    # NOP 7 CFR 205.203(c)(1): Raw manure harvest interval depends on whether the edible
    # portion of the crop contacts soil. 120 days for crops with soil contact (leafy greens,
    # root crops, melons, squash); 90 days for crops without (tree fruit, tree nut, sweet corn).
    has_soil_contact = models.BooleanField(
        default=True,
        help_text=(
            "Whether the edible portion of this crop contacts the soil. "
            "Determines the raw-manure harvest interval per NOP 7 CFR 205.203(c)(1) "
            "(True = 120 days, False = 90 days). Conservative default is True."
        ),
    )
    # Tree nuts shaken to the orchard floor and swept up (walnuts, almonds, pecans, hazelnuts). The kernel does
    # not touch the soil, so the floor stays 90 days ((c)(1)(iii)), but the shell lies on the ground, and
    # certifiers can read that as soil contact under (c)(1)(ii). Where a raw manure interval under 120 days
    # meets one of these crops, the dossier names both readings for the certifier; nothing is refused.
    harvested_from_ground = models.BooleanField(
        default=False,
        help_text=(
            "Whether the crop is gathered from the ground at harvest (nuts shaken to the orchard floor and swept). "
            "A raw manure interval under 120 days on such a crop is printed for the certifier to confirm."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carbon_crop_type"
        ordering = ["name"]
        verbose_name = "Crop Type"
        verbose_name_plural = "Crop Types"

    def __str__(self):
        return self.name

    @property
    def total_templates_count(self):
        """Count of associated production templates"""
        return self.production_templates.count()

    @property
    def total_events_count(self):
        """Count of associated event templates across all production templates"""
        return EventTemplate.objects.filter(production_template__crop_type=self).count()

    @property
    def carbon_benchmark_range(self):
        """Formatted carbon benchmark range"""
        return f"{self.best_practice}-{self.emissions_per_hectare} kg CO2e/ha"


class ProductionTemplate(models.Model):
    """Model for different production approaches per crop type (e.g., Conventional, Organic, Precision)"""

    FARMING_APPROACH_CHOICES = [
        ("conventional", "Conventional"),
        ("organic", "Organic"),
        ("precision", "Precision Agriculture"),
        ("regenerative", "Regenerative"),
        ("sustainable", "Sustainable"),
        ("integrated", "Integrated Pest Management"),
        ("no_till", "No-Till"),
        ("cover_crop", "Cover Crop System"),
    ]

    COMPLEXITY_CHOICES = [
        ("beginner", "Beginner Friendly"),
        ("intermediate", "Intermediate"),
        ("advanced", "Advanced"),
        ("expert", "Expert Level"),
    ]

    crop_type = models.ForeignKey(CropType, on_delete=models.CASCADE, related_name="production_templates")
    name = models.CharField(max_length=100, help_text="e.g., Citrus Organic Production")
    slug = models.SlugField(max_length=100, help_text="e.g., citrus_organic")
    farming_approach = models.CharField(max_length=20, choices=FARMING_APPROACH_CHOICES)
    description = models.TextField(help_text="Detailed description of this production approach")

    # Template characteristics
    complexity_level = models.CharField(max_length=15, choices=COMPLEXITY_CHOICES, default="intermediate")
    estimated_setup_time = models.IntegerField(help_text="Setup time in minutes", default=8)

    # Carbon and economic projections
    projected_emissions_reduction = models.FloatField(default=0.0, help_text="% reduction vs conventional")
    projected_cost_change = models.FloatField(default=0.0, help_text="% cost change vs conventional")
    projected_yield_impact = models.FloatField(default=0.0, help_text="% yield change vs conventional")

    # Premium pricing and market data
    premium_pricing_potential = models.CharField(max_length=20, default="0%", help_text="e.g., 25-40%")
    market_demand = models.CharField(
        max_length=20,
        choices=[
            ("low", "Low Demand"),
            ("medium", "Medium Demand"),
            ("high", "High Demand"),
            ("very_high", "Very High Demand"),
        ],
        default="medium",
    )

    # Certification and compliance
    certification_requirements = models.JSONField(default=list, help_text="Required certifications")
    compliance_notes = models.TextField(blank=True, help_text="USDA compliance and regulatory notes")

    # Template metadata
    is_active = models.BooleanField(default=True)
    is_recommended = models.BooleanField(default=False, help_text="Recommended template for this crop")
    usage_count = models.IntegerField(default=0, help_text="How many times this template has been used")
    success_rate = models.FloatField(default=0.0, help_text="Success rate based on user feedback")

    # USDA verification
    usda_reviewed = models.BooleanField(default=False, help_text="Template reviewed against USDA practices")
    usda_compliant = models.BooleanField(default=True, help_text="Meets USDA agricultural standards")
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "carbon_production_template"
        ordering = ["crop_type", "farming_approach", "name"]
        verbose_name = "Production Template"
        verbose_name_plural = "Production Templates"
        unique_together = ("crop_type", "slug")

    def __str__(self):
        return f"{self.crop_type.name} - {self.name}"

    def increment_usage(self):
        """Increment usage counter"""
        self.usage_count += 1
        self.save(update_fields=["usage_count"])

    @property
    def events_count(self):
        """Count of events in this template"""
        return self.event_templates.count()

    @property
    def total_carbon_impact(self):
        """Calculate total carbon impact of all events in template"""
        return self.event_templates.aggregate(total=models.Sum("carbon_impact"))["total"] or 0

    @property
    def total_cost_estimate(self):
        """Calculate total cost estimate of all events in template"""
        return self.event_templates.aggregate(total=models.Sum("cost_estimate"))["total"] or 0


class EventTemplate(models.Model):
    """Model for event templates associated with production templates"""

    EVENT_TYPE_CHOICES = [
        ("fertilization", "Fertilization"),
        ("irrigation", "Irrigation"),
        ("pest_control", "Pest Control"),
        ("pruning", "Pruning"),
        ("planting", "Planting"),
        ("harvest", "Harvest"),
        ("soil_management", "Soil Management"),
        ("equipment", "Equipment Operation"),
        ("weather_protection", "Weather Protection"),
        ("certification", "Certification Activity"),
        ("monitoring", "Monitoring & Testing"),
        ("other", "Other"),
    ]

    FREQUENCY_CHOICES = [
        ("annual", "Annual"),
        ("seasonal", "Seasonal"),
        ("monthly", "Monthly"),
        ("weekly", "Weekly"),
        ("as_needed", "As Needed"),
        ("natural", "Natural Process"),
        ("one_time", "One Time Setup"),
    ]

    CARBON_CATEGORY_CHOICES = [
        ("high", "High Impact (>100 kg CO2e)"),
        ("medium", "Medium Impact (25-100 kg CO2e)"),
        ("low", "Low Impact (<25 kg CO2e)"),
        ("negative", "Negative Impact (Carbon Sequestration)"),
        ("neutral", "Carbon Neutral"),
    ]

    QR_VISIBILITY_CHOICES = [
        ("high", "High - Prominent display to consumers"),
        ("medium", "Medium - Standard visibility"),
        ("low", "Low - Technical information"),
        ("hidden", "Hidden - Internal use only"),
    ]

    # Display priority for template ordering in UI
    DISPLAY_PRIORITY_CHOICES = [
        (1, "Featured - Top of list"),
        (2, "High - Upper section"),
        (3, "Normal - Standard position"),
        (4, "Low - Lower section"),
        (5, "Archive - Bottom of list"),
    ]

    # Template category for grouping in UI
    TEMPLATE_CATEGORY_CHOICES = [
        ("core", "Core Farm Operations"),
        ("seasonal", "Seasonal Activities"),
        ("maintenance", "Maintenance & Equipment"),
        ("monitoring", "Monitoring & Testing"),
        ("certification", "Certification & Compliance"),
        ("documentation", "Documentation"),
    ]

    # Temporary: Keep both fields during migration
    crop_type = models.ForeignKey(
        CropType, on_delete=models.CASCADE, related_name="old_event_templates", null=True, blank=True
    )
    production_template = models.ForeignKey(
        ProductionTemplate, on_delete=models.CASCADE, related_name="event_templates", null=True, blank=True
    )
    name = models.CharField(max_length=100, help_text="e.g., Winter Pruning")
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    description = models.TextField(help_text="Detailed description of the event")

    # Timing and scheduling
    timing = models.CharField(max_length=100, help_text="e.g., December - February")
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    typical_duration = models.CharField(max_length=50, help_text="e.g., 2-3 hours")
    order_sequence = models.IntegerField(default=0, help_text="Order in which this event typically occurs")

    # Carbon and environmental impact
    carbon_impact = models.FloatField(help_text="kg CO2e impact (negative for sequestration)")
    carbon_category = models.CharField(max_length=10, choices=CARBON_CATEGORY_CHOICES)
    carbon_sources = models.JSONField(default=list, help_text="List of carbon sources")
    typical_amounts = models.JSONField(default=dict, help_text="Typical amounts used")

    # Economic impact
    cost_estimate = models.FloatField(help_text="Estimated cost per hectare")
    labor_hours = models.FloatField(default=0.0, help_text="Estimated labor hours per hectare")

    # Sustainability and efficiency
    efficiency_tips = models.TextField(help_text="Tips for reducing environmental impact")
    sustainability_score = models.IntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(10)])
    alternative_methods = models.JSONField(default=list, help_text="Alternative methods for this event")

    # Consumer visibility
    qr_visibility = models.CharField(max_length=10, choices=QR_VISIBILITY_CHOICES, default="medium")
    consumer_message = models.CharField(max_length=200, blank=True, help_text="Message shown to consumers")

    # Backend event mapping
    backend_event_type = models.IntegerField(
        help_text=(
            "Maps to backend event model: 0=Weather, 1=Production, "
            "2=Chemical, 3=General, 4=Equipment, 5=Soil, 6=Pest, 7=Business"
        )
    )
    backend_event_fields = models.JSONField(default=dict, help_text="Default field values for backend event creation")

    # USDA compliance and verification
    usda_practice_code = models.CharField(max_length=10, blank=True, help_text="USDA NRCS practice code if applicable")
    usda_compliant = models.BooleanField(default=True, help_text="Meets USDA standards")
    emission_factor_source = models.CharField(max_length=200, default="USDA Agricultural Research Service")

    # Display and organization (for UI presentation)
    display_priority = models.IntegerField(
        choices=DISPLAY_PRIORITY_CHOICES,
        default=3,
        help_text="Controls template ordering in UI (1=featured, 5=archive)",
    )
    template_category = models.CharField(
        max_length=20,
        choices=TEMPLATE_CATEGORY_CHOICES,
        default="core",
        help_text="Category for grouping templates in UI",
    )
    translation_key = models.CharField(
        max_length=100,
        blank=True,
        help_text="i18n key for frontend translation (e.g., 'quickAdd.template.fertilization')",
    )

    # Meta information
    is_active = models.BooleanField(default=True)
    is_default_enabled = models.BooleanField(default=True, help_text="Enabled by default in production creation")
    is_required = models.BooleanField(default=False, help_text="Required event that cannot be disabled")
    usage_count = models.IntegerField(default=0, help_text="Track how often this template is used")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Run 8 (R8-23, Oscar's amendment 2026-10-05): templates are updated by a stable identity and
    # versioned, never matched by their text. `template_key` is fixed when the row is created
    # (from its name at that moment) and survives a later rename; `content_version` goes up each
    # time the seeder changes the row's wording.
    template_key = models.SlugField(max_length=150, blank=True, default="", db_index=True)
    content_version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "carbon_event_template"
        ordering = ["production_template", "display_priority", "template_category", "order_sequence", "name"]
        verbose_name = "Event Template"
        verbose_name_plural = "Event Templates"
        unique_together = ("production_template", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["production_template", "template_key"],
                condition=~models.Q(template_key=""),
                name="unique_event_template_key_per_production_template",
            )
        ]

    def __str__(self):
        return f"{self.production_template.name} - {self.name}"

    def increment_usage(self):
        """Increment usage counter"""
        self.usage_count += 1
        self.save(update_fields=["usage_count"])

    @property
    def crop_type(self):
        """Get crop type through production template"""
        return self.production_template.crop_type

    @property
    def formatted_carbon_impact(self):
        """Format carbon impact for display"""
        if self.carbon_impact < 0:
            return f"-{abs(self.carbon_impact)} kg CO₂ (sequestration)"
        return f"{self.carbon_impact} kg CO₂"

    @property
    def carbon_impact_color(self):
        """Color for carbon impact display"""
        if self.carbon_category == "negative":
            return "green"
        elif self.carbon_category == "high":
            return "red"
        elif self.carbon_category == "medium":
            return "orange"
        return "blue"


# Create your models here.


class CarbonSource(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="e.g., Citrus Fertilizer")
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=50, help_text="e.g. kg CO2e, liters, kWh")
    category = models.CharField(max_length=50, help_text="e.g., Fuel, Offset")
    default_emission_factor = models.FloatField(help_text="kg CO2e per unit, USDA-aligned", default=0.0)
    # New fields for better verification tracking
    usda_factors_based = models.BooleanField(default=False, help_text="Whether calculations use USDA emission factors")
    verification_status = models.CharField(
        max_length=50, default="estimated", help_text="factors_verified, estimated, calculation_error"
    )
    data_source = models.CharField(
        max_length=200,
        default="Unknown",
        help_text="Source of emission factors (e.g., USDA Agricultural Research Service)",
    )
    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["category"]),
            models.Index(fields=["usda_factors_based"]),
            models.Index(fields=["verification_status"]),
        ]

    def __str__(self):
        return self.name


# ⛔ "verified" on a carbon record means A THIRD PARTY CHECKED IT. Nobody checks these.
# An offset the operator entered through the API is SELF-REPORTED, whatever the client sends
# in `verification_level` — a payload field is the claimant's assertion, never evidence for it.
# Until 2026-09-23 five write paths stamped "verified" on user-created offsets, one of them
# alongside `data_source="User-created offset"` in the same call. Those rows are a false
# attestation in the database and, netted against emissions, were the source of the public
# "Carbon Stored" badge (see self-created-label-can-be-a-colour-2026-09-23).
# FTC 16 CFR 260.5 governs offset claims; "self_reported" is the same vocabulary
# certifications already use (transparency_calculator.py, certifications/signals.py).
# ⛔ Do not write "verified" here without a named third party and a stored artifact.
VERIFICATION_SELF_REPORTED = "self_reported"


class CarbonOffsetAction(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    unit = models.CharField(max_length=50, help_text="e.g. trees planted, tons CO2 offset")
    verification_required = models.BooleanField(default=False)
    verification_process = models.TextField(blank=True)
    usda_factors_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class CarbonEntry(models.Model):
    TYPE_CHOICES = (
        ("emission", "Emission"),
        ("offset", "Offset"),
    )
    establishment = models.ForeignKey("company.Establishment", on_delete=models.CASCADE, null=True, blank=True)
    production = models.ForeignKey("history.Production", on_delete=models.CASCADE, null=True, blank=True)
    # The activity this entry was computed from (schema remodel plan, CarbonEntry slice). Before
    # 2026-11 the only link was text in `description`/`registry_verification_id`; see
    # carbon/event_link.py. PROTECT: Activity rows are tombstoned, never deleted, and an entry must
    # never disappear with one (a seal's second layer counts entries). A plain FK, not OneToOne:
    # one event can carry more than one entry.
    activity = models.ForeignKey(
        "history.Activity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="carbon_entries",
    )
    created_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    source = models.ForeignKey("CarbonSource", on_delete=models.SET_NULL, null=True)
    amount = models.FloatField(help_text="Amount in kg CO2e")
    co2e_amount = models.FloatField(default=0.0, help_text="Amount in CO2 equivalent")
    year = models.IntegerField()
    timestamp = models.DateTimeField(default=timezone.now)
    description = models.TextField(blank=True)
    # Verification tracking
    usda_factors_based = models.BooleanField(default=False, help_text="Whether calculations use USDA emission factors")
    verification_status = models.CharField(
        max_length=50, default="estimated", help_text="factors_verified, estimated, calculation_error"
    )
    data_source = models.CharField(
        max_length=200,
        default="Unknown",
        help_text="Source of emission factors (e.g., USDA Agricultural Research Service)",
    )

    # Enhanced verification fields for offset verification system - MVP 2-tier system
    VERIFICATION_LEVEL_CHOICES = [
        ("self_reported", "Self Reported"),
        ("certified_project", "Certified Project"),
    ]

    AUDIT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("scheduled", "Audit Scheduled"),
        ("in_progress", "Under Review"),
        ("passed", "Audit Passed"),
        ("failed", "Audit Failed"),
    ]

    verification_level = models.CharField(max_length=25, choices=VERIFICATION_LEVEL_CHOICES, default="self_reported")
    trust_score = models.FloatField(default=0.5, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    effective_amount = models.FloatField(null=True, blank=True, help_text="Amount * trust_score")

    # Additionality and verification requirements
    additionality_verified = models.BooleanField(default=False)
    permanence_plan = models.TextField(blank=True)
    baseline_data = models.JSONField(default=dict)
    audit_status = models.CharField(max_length=20, choices=AUDIT_STATUS_CHOICES, default="pending")
    audit_scheduled_date = models.DateTimeField(null=True, blank=True)
    third_party_verification_url = models.URLField(blank=True)
    registry_verification_id = models.CharField(max_length=100, blank=True)
    methodology_template = models.CharField(max_length=50, blank=True)

    # Requirements tracking
    evidence_requirements_met = models.BooleanField(default=False)
    documentation_complete = models.BooleanField(default=False)
    additionality_evidence = models.TextField(blank=True)

    # Evidence files
    evidence_photos = models.JSONField(default=list, blank=True, help_text="List of photo URLs as evidence")
    evidence_documents = models.JSONField(default=list, blank=True, help_text="List of document URLs as evidence")

    # The 16 retired columns (carbon/retired_columns.py) left the model in migration 0048 and the
    # table in 0049.
    calculation_details = models.JSONField(default=dict, help_text="Detailed calculation methodology and factors used")

    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(establishment__isnull=False) | models.Q(production__isnull=False),
                name="either_establishment_or_production_set",
            )
        ]
        indexes = [
            models.Index(fields=["establishment"]),
            models.Index(fields=["production"]),
            models.Index(fields=["year"]),
            models.Index(fields=["timestamp"]),
            models.Index(
                fields=["production", "usda_factors_based"],
                name="carbon_production_factors_idx",
                condition=models.Q(production__isnull=False),
            ),
            models.Index(fields=["verification_status"]),
            models.Index(fields=["verification_level"]),
            models.Index(fields=["audit_status"]),
            models.Index(fields=["additionality_verified"]),
            models.Index(fields=["registry_verification_id"]),
        ]

    def save(self, *args, **kwargs):
        # Validate event type for establishment compatibility
        is_valid, error_message = self.validate_event_for_establishment()
        if not is_valid:
            from django.core.exceptions import ValidationError

            raise ValidationError(f"Invalid event for establishment: {error_message}")

        # Only set basic trust score if not already set by verification service
        if self.type == "offset" and not hasattr(self, "_verification_processed"):
            trust_scores = {"self_reported": 0.5, "certified_project": 1.0}
            # Only set trust score if it's still the default
            if self.trust_score == 0.5 or self.trust_score is None:
                self.trust_score = trust_scores.get(self.verification_level, 0.5)

            # Only set basic effective amount if not set by verification service
            if self.effective_amount is None:
                self.effective_amount = self.amount * self.trust_score
        elif self.type == "emission":
            self.effective_amount = self.amount

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.type.capitalize()} - {self.amount} ({self.timestamp})"

    @property
    def verification_badge(self):
        """Return verification badge configuration"""
        badges = {
            "self_reported": {"color": "orange", "text": "Self Reported", "icon": "document"},
            "certified_project": {"color": "green", "text": "Certified Project", "icon": "certificate"},
        }
        return badges.get(self.verification_level, badges["self_reported"])

    @classmethod
    def calculate_carbon_score(cls, total_emissions, total_offsets, industry_benchmark=None):
        """
        NEVER: DO NOT WIRE THIS TO ANYTHING. It has no production caller (verified 2026-09-30) and a
        self-assigned 0-100 grade is retired as a CONCEPT, not merely unused. `CarbonReport`'s
        `carbon_score` column, its index, its serializer field and the nightly task that wrote it
        were all removed on 2026-09-30. This method and the inline scores in
        `carbon/views.py` (`CarbonEntryViewSet.summary`, `CarbonEstablishmentSummaryViewSet.summary`,
        the latter also returning a `performance_tier` label) are the remaining sites and are their
        own slice, tracked in `backend/scheduled_work.py`. Kept here only because
        `carbon/test_carbon_calculations.py` exercises it and rewriting that file is that slice.

        Calculate a carbon score on a scale of 1-100.
        100 is the best (carbon negative), 50 is neutral, <50 is carbon positive.

        Args:
            total_emissions: Total emissions in kg CO2e
            total_offsets: Total offsets in kg CO2e
            industry_benchmark: Industry average emissions (optional)

        Returns:
            int: Carbon score from 1-100
        """
        # If no emissions or offsets, return neutral score
        if total_emissions == 0 and total_offsets == 0:
            return 50

        net_carbon = total_emissions - total_offsets

        # If carbon negative (more offsets than emissions)
        if net_carbon <= 0:
            # Scale from 50 (neutral) to 100 (highly negative)
            # The more negative, the higher the score
            if total_emissions == 0:
                return 100  # Perfect score if no emissions but has offsets

            # Calculate how much more offsets than emissions (as percentage)
            offset_ratio = abs(net_carbon) / total_emissions

            # Cap at 100% (or 2x emissions) for max score
            offset_ratio = min(offset_ratio, 1.0)

            # Scale from 50 to 100
            return int(50 + (offset_ratio * 50))

        # If carbon positive (more emissions than offsets)
        else:
            # If we have an industry benchmark to compare against
            if industry_benchmark and industry_benchmark > 0:
                # If better than industry average
                if net_carbon < industry_benchmark:
                    ratio = net_carbon / industry_benchmark
                    # Scale from 25 to 50 (50 being carbon neutral)
                    return int(50 - (ratio * 25))
                # If worse than industry average
                else:
                    ratio = min(net_carbon / industry_benchmark, 2.0)  # Cap at 2x industry average
                    # Scale from 1 to 25
                    return max(1, int(25 - (ratio - 1) * 24))

            # Without industry benchmark, use a simple ratio
            else:
                # Calculate ratio of offsets to emissions
                offset_ratio = total_offsets / total_emissions if total_emissions > 0 else 0
                # Scale from 1 to 50 (50 being carbon neutral)
                # Ensure minimum score of 1 for positive emissions
                score = int(offset_ratio * 50)
                return max(1, score) if total_emissions > 0 else 50

    @classmethod
    def get_allowed_event_types_for_establishment(cls, establishment_type):
        """
        Define which event types are allowed for different establishment types.
        Prevents inappropriate events like packaging at research facilities.

        Args:
            establishment_type: String representing the type of establishment

        Returns:
            dict: Configuration with allowed/restricted event patterns
        """
        # Default configuration for unknown establishment types
        default_config = {
            "allowed_patterns": [
                "fertilizer",
                "irrigation",
                "soil",
                "cover crop",
                "equipment",
                "solar",
                "organic",
                "harvest",
                "processing",
                "pest",
            ],
            "restricted_patterns": ["packaging"],
            "reasoning": "General farm operations without packaging",
        }

        # Establishment-specific configurations
        configs = {
            "Organic Research Center": {
                "allowed_patterns": [
                    "fertilizer",
                    "irrigation",
                    "soil",
                    "cover crop",
                    "equipment",
                    "solar",
                    "organic",
                    "research",
                    "experimental",
                    "pest",
                ],
                "restricted_patterns": ["packaging", "processing", "harvest"],
                "reasoning": "Research facilities should focus on agricultural research, not product packaging or processing",
            },
            "Regenerative Grain Ranch": {
                "allowed_patterns": [
                    "fertilizer",
                    "irrigation",
                    "soil",
                    "cover crop",
                    "equipment",
                    "solar",
                    "grain",
                    "harvest",
                    "pest",
                    "organic",
                ],
                "restricted_patterns": ["packaging"],
                "reasoning": "Grain ranches grow crops but typically do not package consumer products",
            },
            "Premium Citrus Ranch": {
                "allowed_patterns": [
                    "fertilizer",
                    "irrigation",
                    "soil",
                    "cover crop",
                    "equipment",
                    "solar",
                    "citrus",
                    "harvest",
                    "processing",
                    "pest",
                    "organic",
                ],
                "restricted_patterns": [],  # Citrus operations might legitimately package
                "reasoning": "Citrus ranches may have some packaging operations for direct sales",
            },
        }

        return configs.get(establishment_type, default_config)

    def validate_event_for_establishment(self):
        """
        Validate that this carbon entry is appropriate for the establishment type.

        Returns:
            tuple: (is_valid: bool, error_message: str)
        """
        if not self.establishment or not self.description:
            return True, ""

        establishment_type = getattr(self.establishment, "establishment_type", None)
        if not establishment_type:
            return True, ""  # Skip validation if establishment type is unknown

        config = self.get_allowed_event_types_for_establishment(establishment_type)
        description_lower = self.description.lower()

        # Check if event contains any restricted patterns
        for restricted_pattern in config["restricted_patterns"]:
            if restricted_pattern in description_lower:
                return (
                    False,
                    f"Event type '{restricted_pattern}' is not appropriate for {establishment_type}. {config['reasoning']}",
                )

        return True, ""


class CarbonCertification(models.Model):
    establishment = models.ForeignKey("company.Establishment", on_delete=models.CASCADE, null=True, blank=True)
    production = models.ForeignKey("history.Production", on_delete=models.CASCADE, null=True, blank=True)
    certifier = models.CharField(max_length=100, help_text="e.g., USDA Organic", default="Unknown")
    certificate_id = models.CharField(max_length=50, unique=True, default="TEMP_ID")
    issue_date = models.DateField(default=timezone.now)
    expiry_date = models.DateField(null=True, blank=True)
    document = models.FileField(upload_to="certifications/", storage=private_records_storage, null=True, blank=True)
    is_usda_soe_verified = models.BooleanField(default=False)
    verification_date = models.DateField(null=True, blank=True)
    verification_details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(establishment__isnull=False) | models.Q(production__isnull=False),
                name="either_establishment_or_production_set_certification",
            )
        ]
        indexes = [models.Index(fields=["is_usda_soe_verified"]), models.Index(fields=["verification_date"])]

    def __str__(self):
        return f'{self.certificate_id} ({self.establishment.name if self.establishment else "N/A"})'


class CarbonAuditLog(models.Model):
    carbon_entry = models.ForeignKey(
        CarbonEntry, on_delete=models.CASCADE, related_name="audit_logs", null=True, blank=True
    )
    certification = models.ForeignKey(
        CarbonCertification, on_delete=models.CASCADE, related_name="audit_logs", null=True, blank=True
    )
    # `report` (FK to CarbonReport) left the model in carbon migration 0052 with CarbonReport; the
    # column stays, NULL in every row, until the step-2 migration drops it.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(
        max_length=50,
        choices=[
            ("create", "Create"),
            ("update", "Update"),
            ("delete", "Delete"),
            ("verify", "Verify"),
            ("gaming_detected", "Gaming Detected"),
            ("audit_scheduled", "Audit Scheduled"),
        ],
    )
    timestamp = models.DateTimeField(auto_now=True)
    details = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["action"]),
            models.Index(fields=["timestamp"]),
            models.Index(fields=["ip_address"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.user} at {self.timestamp}"


# SustainabilityBadge, MicroOffset and GreenPoints left the model in carbon migration 0050 and
# their tables in 0051 (2026-11-06): a self-assigned sustainability label, a shopper offset
# micro-purchase and a shopper gamification score. Their routes were retired in 2026-09 (see
# carbon/tests/test_retired_claim_routes_stay_retired.py), nothing has written a row in
# production, and an empty schema for a retired claim is an invitation to wire it back.
#
# CarbonOffsetProject, CarbonOffsetPurchase, CarbonOffsetCertificate, CarbonBenchmark and
# CarbonReport left the model in carbon migration 0052 (2026-11-07), 0 rows in every table: the
# pre-pivot offset marketplace (projects labelled "VCS", purchases, PDF certificates), an industry
# "benchmark" Trazo computed about itself, and report snapshots that carried a 0-100 carbon score.
# Their routes, views, services and seeders went first (#329, #332, #333, #337).


# IoT Device Management Models


# =============================================================================
# PERFORMANCE OPTIMIZATION MODELS - Added by Carbon API Optimization
# =============================================================================


class CachedEmissionFactor(models.Model):
    """
    Database cache for emission factors to reduce USDA API calls.

    PERFORMANCE: Reduces API calls by 70%, provides offline fallback.
    """

    crop_type = models.CharField(max_length=100, db_index=True)
    region = models.CharField(max_length=10, default="US", db_index=True)
    factors = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carbon_cached_emission_factors"
        indexes = [
            models.Index(fields=["crop_type", "region", "created_at"]),
            models.Index(fields=["created_at"]),  # For cleanup
        ]
        constraints = [models.UniqueConstraint(fields=["crop_type", "region"], name="unique_crop_region_factor")]


# NEW MODELS FOR ENHANCED USDA INTEGRATION


class USDAComplianceRecord(models.Model):
    """Model for tracking USDA compliance validation results"""

    COMPLIANCE_STATUS_CHOICES = [
        ("compliant", "USDA Compliant"),
        ("non_compliant", "Non-Compliant"),
        ("under_review", "Under Review"),
        ("pending_validation", "Pending Validation"),
        ("validation_error", "Validation Error"),
    ]

    CONFIDENCE_LEVEL_CHOICES = [
        ("high", "High (>90%)"),
        ("medium", "Medium (70-90%)"),
        ("low", "Low (<70%)"),
    ]

    # Related records
    carbon_entry = models.ForeignKey(CarbonEntry, on_delete=models.CASCADE, related_name="usda_compliance_records")
    establishment = models.ForeignKey("company.Establishment", on_delete=models.CASCADE, null=True, blank=True)
    production = models.ForeignKey("history.Production", on_delete=models.CASCADE, null=True, blank=True)

    # Compliance details
    compliance_status = models.CharField(max_length=20, choices=COMPLIANCE_STATUS_CHOICES, default="pending_validation")
    confidence_score = models.FloatField(
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)], help_text="Confidence score from 0.0 to 1.0"
    )
    confidence_level = models.CharField(max_length=10, choices=CONFIDENCE_LEVEL_CHOICES)

    # Validation details
    validation_method = models.CharField(
        max_length=50, default="api_validation", help_text="Method used for validation"
    )
    validation_details = models.JSONField(default=dict, help_text="Detailed validation results")
    recommendations = models.JSONField(default=list, help_text="USDA compliance recommendations")

    # API integration tracking
    usda_api_used = models.BooleanField(default=False, help_text="Whether USDA API was used for validation")
    api_response_code = models.IntegerField(null=True, blank=True, help_text="API response status code")
    api_response_data = models.JSONField(default=dict, help_text="Full API response data")

    # Regional factors
    crop_type = models.CharField(max_length=100, help_text="Crop type used in validation")
    state = models.CharField(max_length=2, help_text="State code for regional factors")
    regional_factors_used = models.BooleanField(default=False, help_text="Whether regional emission factors were used")

    # Metadata
    validated_at = models.DateTimeField(auto_now_add=True)
    validated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Additional validation notes")

    # Audit trail
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carbon_usda_compliance_record"
        ordering = ["-validated_at"]
        indexes = [
            models.Index(fields=["compliance_status"]),
            models.Index(fields=["confidence_level"]),
            models.Index(fields=["crop_type", "state"]),
            models.Index(fields=["validated_at"]),
        ]

    def __str__(self):
        return f"USDA Compliance - {self.carbon_entry} - {self.compliance_status}"

    def save(self, *args, **kwargs):
        # Set confidence level based on score
        if self.confidence_score >= 0.9:
            self.confidence_level = "high"
        elif self.confidence_score >= 0.7:
            self.confidence_level = "medium"
        else:
            self.confidence_level = "low"

        super().save(*args, **kwargs)

    @property
    def is_epa_factors_based(self):
        """
        Check if EPA/USDA emission factors were used in this carbon calculation.

        Returns True if:
        - Validation completed successfully (method is not error)
        - Crop type was identified (calculation ran with proper data)
        - Record is not in a failed state

        This means "EPA/USDA emission factors were applied", NOT that the USDA
        independently verified this farm's practices.
        """
        # If validation had an error, EPA/USDA factors were not successfully applied
        if self.validation_method == "validation_error":
            return False

        # If we don't have a crop type, the validation didn't run properly
        if not self.crop_type or self.crop_type == "unknown":
            return False

        # If we successfully validated (even with low confidence), EPA/USDA factors were used
        # The confidence_score indicates how precise the calculation is, not whether
        # factors were actually applied
        return self.validation_method in ["enhanced_api", "local_validation"]

    @property
    def needs_review(self):
        """Check if this record needs manual review"""
        return self.compliance_status in ["non_compliant", "validation_error"] or self.confidence_score < 0.7


# RegionalEmissionFactor left the model in carbon migration 0050 (table dropped in 0051): a table of
# "regional USDA emission factors" with a usda_api data source that nothing ever filled or read
# outside its own tests. Factor provenance lives per input class in the calculators
# (.claude/rules/carbon-methodology.md).


class USDACalculationAudit(models.Model):
    """Model for auditing USDA calculation processes"""

    CALCULATION_TYPES = [
        ("chemical_event", "Chemical Event"),
        ("production_event", "Production Event"),
        ("equipment_event", "Equipment Event"),
        ("soil_management", "Soil Management"),
        ("weather_event", "Weather Event"),
        ("pest_management", "Pest Management"),
        ("business_event", "Business Event"),
    ]

    # Event and calculation details
    event_type = models.CharField(max_length=20, choices=CALCULATION_TYPES)
    event_id = models.IntegerField(help_text="ID of the original event")
    carbon_entry = models.ForeignKey(CarbonEntry, on_delete=models.CASCADE, related_name="usda_audit_logs")

    # Calculation inputs
    input_data = models.JSONField(help_text="Original event data used in calculation")
    regional_factors_used = models.JSONField(default=dict, help_text="Regional emission factors used")
    calculation_method = models.CharField(max_length=100, help_text="Calculation method used")

    # USDA compliance tracking
    usda_factors_applied = models.BooleanField(default=False)
    regional_adjustments_applied = models.BooleanField(default=False)
    api_data_used = models.BooleanField(default=False)

    # Results
    calculated_co2e = models.FloatField(help_text="Calculated CO2e amount")
    confidence_score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    benchmark_comparison = models.JSONField(default=dict, help_text="Benchmark comparison results")

    # Processing metadata
    calculation_time_ms = models.IntegerField(help_text="Time taken for calculation in milliseconds")
    processor_version = models.CharField(max_length=50, default="1.0", help_text="Version of calculation engine used")

    # Audit trail
    calculated_at = models.DateTimeField(auto_now_add=True)
    calculated_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = "carbon_usda_calculation_audit"
        ordering = ["-calculated_at"]
        indexes = [
            models.Index(fields=["event_type", "event_id"]),
            models.Index(fields=["calculated_at"]),
            models.Index(fields=["usda_factors_applied"]),
            models.Index(fields=["confidence_score"]),
        ]

    def __str__(self):
        return f"USDA Audit - {self.event_type} #{self.event_id} - {self.calculated_at}"


class VerificationAudit(models.Model):
    """Track verification audits and results"""

    AUDIT_TYPE_CHOICES = [
        ("random", "Random Audit"),
        ("scheduled", "Scheduled Review"),
        ("complaint", "Complaint Investigation"),
    ]

    RESULT_CHOICES = [("passed", "Passed"), ("failed", "Failed"), ("pending", "Pending Review")]

    carbon_entry = models.ForeignKey(CarbonEntry, on_delete=models.CASCADE, related_name="verification_audits")
    audit_type = models.CharField(max_length=20, choices=AUDIT_TYPE_CHOICES)
    auditor_name = models.CharField(max_length=200)
    audit_date = models.DateTimeField()
    findings = models.JSONField(default=dict)
    result = models.CharField(max_length=20, choices=RESULT_CHOICES)
    corrective_actions = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "carbon_verification_audit"
        ordering = ["-audit_date"]
        indexes = [
            models.Index(fields=["audit_type"]),
            models.Index(fields=["result"]),
            models.Index(fields=["audit_date"]),
        ]

    def __str__(self):
        return f"Audit {self.carbon_entry} - {self.result}"


# ConsumerTrustMetric was deleted 2026-09-30 (carbon migration 0040).
#
# It declared FIVE self-graded 0-100 columns about one production, all defaulting to 0.0 and
# all validated 0 to 100: overall_trust_score, data_completeness_score, verification_score,
# transparency_score and consistency_score, plus trust_factors and improvement_areas JSON
# blobs. A consumer trust score is the self-created sustainability label EU ECGT 2024/825
# bans without third-party verification, and `transparency-first.md` retired the concept
# outright: counts, never a grade.
#
# NOTHING EVER WROTE A ROW. Across the whole codebase the only references were an unused
# import in carbon/serializers.py and copy_production_to_parcel, which copied a row if one
# existed. No service, no view, no serializer, no task, no seeder ever created one, so the
# table could only ever have been populated by hand.
#
# That is why it is deleted rather than left dormant: an empty table with five grade columns
# and a OneToOne to History is an invitation. Someone wiring a trust widget finds a ready
# schema and the claim is back with no discussion. Same reasoning as
# carbon/tests/test_retired_claim_routes_stay_retired.py applies to routes.
# CarbonIntelligence left the model in carbon migration 0050 (table dropped in 0051), on the grounds of
# ConsumerTrustMetric above: "AI-generated insights" and a 0-100 confidence score about one
# production, which nothing ever wrote. copy_production_to_parcel was its only reader.


class VoiceUsageDay(models.Model):
    """One row per company per day: how many billable voice sessions it started.

    WHY THIS IS IN THE DATABASE AND NOT THE CACHE
    ---------------------------------------------
    DRF's throttles keep their counters in the Django cache, and this project falls back to
    ``DummyCache`` whenever ``REDIS_URL`` is unset (prod.py). DummyCache stores nothing, so
    every declared rate becomes a no-op — MEASURED 2026-08-26: a ``3/minute`` throttle
    allowed 50 of 50 requests. A budget that protects real spend cannot be built on a store
    that may silently be a black hole, and it has to survive a restart and be reportable
    besides. `backend.security.checks` raises the cache problem separately; this is the
    control that holds either way.

    WHY A BUDGET AND NOT ONLY A RATE
    --------------------------------
    Every ``deepgram-token`` call mints a real Deepgram project key and opens a metered
    stream, and voice is free on EVERY plan (``voice_recording: True`` across create_plans).
    So the exposure is not request bursts, it is unbounded per-account cost — the same shape
    Otter, Granola and Fathom answer with monthly minutes rather than requests per second.
    A daily ceiling is the cheap version of that: invisible to a farmer logging a real day's
    work, and a hard stop on a loop.
    """

    company = models.ForeignKey(
        "company.Company",
        on_delete=models.CASCADE,
        related_name="voice_usage_days",
    )
    # Stored as the company's calendar day in UTC. Exact enough for a spend ceiling, and it
    # avoids making the limit depend on a per-farm timezone we do not reliably have.
    day = models.DateField(db_index=True)
    session_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "carbon_voice_usage_day"
        unique_together = ("company", "day")
        indexes = [models.Index(fields=["company", "day"])]
        verbose_name = "Voice usage (day)"
        verbose_name_plural = "Voice usage (days)"

    def __str__(self):
        return f"{self.company_id} {self.day}: {self.session_count}"
