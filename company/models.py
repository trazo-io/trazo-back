import uuid

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Company(models.Model):
    name = models.CharField(max_length=150, help_text="Company name")
    tradename = models.CharField(max_length=150, blank=True, null=True, help_text="Trade name or DBA")
    address = models.CharField(max_length=200, blank=True, default="", help_text="Street address")
    city = models.CharField(max_length=100, blank=True, default="", help_text="City name")
    state = models.CharField(max_length=100, blank=True, default="", help_text="State or province")
    country = models.CharField(max_length=100, blank=True, null=True, help_text="Country name")
    fiscal_id = models.CharField(max_length=50, help_text="Tax ID, RUT, or EIN", blank=True, null=True)
    logo = models.ImageField(upload_to="company_logos", blank=True)
    description = models.TextField(blank=True, null=True)
    invitation_code = models.CharField(max_length=50, blank=True, null=True, help_text="Invitation code for new users")
    contact_email = models.EmailField(max_length=254, blank=True, null=True, help_text="Primary contact email")
    contact_phone = models.CharField(max_length=20, blank=True, null=True, help_text="Primary contact phone")
    website = models.URLField(max_length=200, blank=True, null=True)
    facebook = models.URLField(max_length=200, blank=True, null=True)
    instagram = models.URLField(max_length=200, blank=True, null=True)
    certifications = models.TextField(blank=True, null=True)

    # Additional business fields
    zip_code = models.CharField(max_length=20, blank=True, null=True, help_text="Postal/ZIP code")
    employee_count = models.PositiveIntegerField(blank=True, null=True, help_text="Number of employees")
    industry = models.CharField(max_length=100, blank=True, null=True, help_text="Primary agricultural industry")
    is_active = models.BooleanField(default=True, help_text="Whether the company is active")

    # New agricultural compliance fields
    legal_structure = models.CharField(max_length=50, blank=True, null=True, help_text="Business legal structure")
    primary_commodities = models.CharField(
        max_length=100, blank=True, null=True, help_text="Main agricultural commodities"
    )
    sustainability_commitment = models.CharField(
        max_length=100, blank=True, null=True, help_text="Sustainability approach"
    )

    # Sustainability and carbon tracking metadata
    sustainability_metadata = models.JSONField(
        blank=True,
        null=True,
        help_text="JSON data containing crop selection, sustainability goals, and carbon benchmarks",
    )

    # Blockchain subscription status
    blockchain_subscription_status = models.BooleanField(
        default=False, help_text="Whether company has active blockchain verification subscription"
    )

    class Meta:
        verbose_name = _("Company")
        verbose_name_plural = _("Companies")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("company-detail", kwargs={"id": self.id})

    def save(self, *args, **kwargs):
        # Generate invitation code if not provided
        if not self.invitation_code:
            self.invitation_code = self.generate_invitation_code()
        super().save(*args, **kwargs)

    def generate_invitation_code(self):
        """Generate a unique company invitation code"""
        import secrets
        import string

        while True:
            # Generate a readable code (6 characters, uppercase + digits)
            code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
            if not Company.objects.filter(invitation_code=code).exists():
                return code

    # Subscription-related methods
    @property
    def subscription_plan(self):
        """Get the current subscription plan for this company"""
        try:
            if hasattr(self, "subscription") and self.subscription.status in ["active", "trialing"]:
                return self.subscription.plan
            return None
        except Exception:
            return None

    def get_feature_limit(self, feature_name, default=0):
        """Get limit for a specific feature from subscription plan"""
        if not self.subscription_plan:
            return default

        features = self.subscription_plan.features
        return features.get(feature_name, default)

    def has_feature(self, feature_name):
        """Check if company has access to a specific feature"""
        if not self.subscription_plan:
            return False

        features = self.subscription_plan.features
        return features.get(feature_name, False)

    def can_create_establishment(self):
        """Check if company can create more establishments"""
        max_allowed = self.get_feature_limit("max_establishments", 0)
        if max_allowed == -1:
            return True
        current_count = self.establishment_set.count()

        # Add purchased add-ons
        if hasattr(self, "subscription"):
            extra_establishments = sum(
                addon.quantity for addon in self.subscription.addons.filter(addon__slug="extra-establishment")
            )
            max_allowed += extra_establishments

        return current_count < max_allowed

    def can_create_parcel(self, establishment=None):
        """Check if company can create more parcels within their plan limit."""
        plan = self.subscription_plan
        if not plan:
            return False

        features = plan.features
        max_per_establishment = features.get("max_parcels_per_establishment", 0)

        # Unlimited parcels (-1)
        if max_per_establishment == -1:
            return True

        if max_per_establishment > 0 and establishment:
            current_count = establishment.parcels.count()
            max_allowed = max_per_establishment

            # Add purchased add-ons
            if hasattr(self, "subscription"):
                extra_parcels = sum(
                    addon.quantity for addon in self.subscription.addons.filter(addon__slug="extra-parcel")
                )
                max_allowed += extra_parcels

            return current_count < max_allowed

        return False

    def can_create_production(self):
        """Check if company can create more productions this year."""
        from history.models import History

        if not self.subscription_plan:
            return False

        # Unlimited productions (-1)
        max_productions = self.get_feature_limit("max_productions_per_year", 0)
        if max_productions == -1:
            return True

        # Single efficient query instead of N+1 nested loops
        start_of_year = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        productions_this_year = History.objects.filter(
            parcel__establishment__company=self,
            start_date__gte=start_of_year,
        ).count()

        # Add purchased add-ons
        if hasattr(self, "subscription"):
            extra_productions = sum(
                addon.quantity * 10 for addon in self.subscription.addons.filter(addon__slug="extra-production")
            )
            max_productions += extra_productions

        return productions_this_year < max_productions

    def get_remaining_scan_quota(self):
        """Get remaining scan quota for the current billing period"""
        if not self.subscription_plan:
            return 0

        base_quota = self.get_feature_limit("monthly_scan_limit", 5000)
        if base_quota == -1:
            return -1  # Unlimited

        # Count actual scans from HistoryScan aligned to billing cycle
        if hasattr(self, "subscription"):
            from django.utils import timezone

            from history.models import HistoryScan

            period_start = self.subscription.current_period_start
            if not period_start:
                period_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            current_usage = HistoryScan.objects.filter(
                history__parcel__establishment__company=self,
                date__gte=period_start,
            ).count()
            return max(0, base_quota - current_usage)

        return base_quota

    def get_storage_limit_gb(self):
        """Get storage limit in GB"""
        if not self.subscription_plan:
            return 0

        base_limit = self.get_feature_limit("storage_limit_gb", 10)
        if base_limit == -1:
            return -1  # Unlimited

        # Add purchased storage add-ons
        if hasattr(self, "subscription"):
            extra_storage = sum(
                addon.quantity for addon in self.subscription.addons.filter(addon__slug="extra-storage")
            )
            base_limit += extra_storage

        return base_limit


class Establishment(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    name = models.CharField(max_length=150, help_text="Establishment name")
    address = models.CharField(max_length=200, blank=True, default="", help_text="Street address")
    city = models.CharField(max_length=100, blank=True, null=True, help_text="City name")
    zone = models.CharField(max_length=100, blank=True, null=True, help_text="Zone or region")
    state = models.CharField(max_length=100, blank=True, default="", help_text="State or province")
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True, help_text="Country name")
    type = models.CharField(max_length=100, blank=True, null=True, help_text="Establishment type")
    latitude = models.FloatField(blank=True, null=True, help_text="GPS latitude")
    longitude = models.FloatField(blank=True, null=True, help_text="GPS longitude")
    contact_person = models.CharField(max_length=100, blank=True, null=True, help_text="Contact person name")
    contact_phone = models.CharField(max_length=20, blank=True, null=True, help_text="Contact phone number")
    contact_email = models.EmailField(max_length=254, blank=True, null=True)
    certifications = models.TextField(blank=True, null=True)
    about = models.TextField(blank=True, null=True)
    main_activities = models.TextField(blank=True, null=True)
    location_highlights = models.TextField(blank=True, null=True)
    custom_message = models.TextField(blank=True, null=True)

    # New valuable fields
    email = models.EmailField(max_length=254, blank=True, null=True, help_text="Main establishment email")
    phone = models.CharField(max_length=20, blank=True, null=True, help_text="Main establishment phone")
    zip_code = models.CharField(max_length=20, blank=True, null=True, help_text="Postal/ZIP code")
    is_active = models.BooleanField(default=True, help_text="Whether the establishment is active")
    crops_grown = models.JSONField(default=list, blank=True, help_text="List of crops grown at this establishment")
    sustainability_practices = models.JSONField(default=list, blank=True, help_text="List of sustainability practices")
    employee_count = models.PositiveIntegerField(blank=True, null=True, help_text="Number of employees")
    total_acreage = models.FloatField(blank=True, null=True, help_text="Total land area in acres")
    year_established = models.PositiveIntegerField(
        blank=True, null=True, help_text="Year the establishment was founded"
    )
    establishment_type = models.CharField(
        max_length=50, blank=True, null=True, help_text="Type of agricultural operation"
    )
    farming_method = models.CharField(max_length=50, blank=True, null=True, help_text="Primary farming approach")

    # Operational agricultural fields
    water_sources = models.JSONField(
        default=list, blank=True, help_text="Primary water sources (well, surface water, irrigation district, etc.)"
    )
    climate_zone = models.CharField(
        max_length=50, blank=True, null=True, help_text="Climate zone or growing region classification"
    )
    soil_types = models.JSONField(default=list, blank=True, help_text="Primary soil types present on the establishment")
    conservation_practices = models.JSONField(
        default=list, blank=True, help_text="Conservation practices implemented (cover crops, buffer strips, etc.)"
    )
    irrigation_methods = models.JSONField(
        default=list, blank=True, help_text="Irrigation methods used (drip, sprinkler, flood, etc.)"
    )

    # SOE Compliance: Organic Fraud Prevention Plan (7 CFR 205.201(a)(3))
    # Required since March 19, 2024 for all certified organic operations
    fraud_prevention_plan_uploaded = models.BooleanField(
        default=False,
        help_text="Whether an Organic Fraud Prevention Plan has been uploaded",
    )
    fraud_prevention_plan_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the fraud prevention plan was last updated",
    )
    fraud_prevention_plan_document = models.FileField(
        upload_to="ofpp/",
        blank=True,
        null=True,
        help_text="Uploaded Organic Fraud Prevention Plan document",
    )
    ofpp_responsible_person = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        help_text="Person responsible for fraud prevention oversight",
    )

    # NOP Compliance: Split Operation Tracking (7 CFR 205.201(a)(5), 7 CFR 205.272)
    has_split_operation = models.BooleanField(
        default=False,
        help_text=(
            "Whether this establishment operates both organic and conventional production "
            "(7 CFR 205.201(a)(5) — requires commingling prevention documentation)"
        ),
    )
    split_operation_plan = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Description of measures to prevent commingling of organic and conventional products "
            "(labeling, storage separation, equipment cleaning protocols per 7 CFR 205.272)"
        ),
    )

    class Meta:
        verbose_name = _("Establishment")
        verbose_name_plural = _("Establishments")

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("establishment-detail", kwargs={"id": self.id})

    def get_location(self) -> str:
        return f"{self.city if self.city is not None else '-'}, {self.country if self.country is not None else '-'}"
