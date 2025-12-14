from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg

import qrcode

from backend.security.qr_security import generate_secure_qr_url
from carbon.choices import FUEL_TYPES
from common.models import Gallery
from product.models import Parcel


class History(models.Model):
    ORCHARD = "OR"
    GARDEN = "GA"

    HISTORY_TYPES = (
        (ORCHARD, "Orchard"),
        (GARDEN, "Garden"),
    )

    name = models.CharField(max_length=150, blank=True, null=True, help_text="Production name")
    type = models.CharField(max_length=2, choices=HISTORY_TYPES, blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)
    start_date = models.DateTimeField(null=True, blank=True)
    finish_date = models.DateTimeField(null=True, blank=True)
    published = models.BooleanField(default=False, blank=True)
    earning = models.FloatField(default=0)
    lot_id = models.CharField(max_length=50, blank=True, null=True, help_text="Lot identifier")
    description = models.TextField(blank=True, null=True)
    production_amount = models.FloatField(default=0)

    # Harvest details for transparency
    UNIT_CHOICES = [
        ("kg", "Kilograms"),
        ("lb", "Pounds"),
        ("boxes", "Boxes"),
        ("crates", "Crates"),
        ("tons", "Tons"),
        ("bushels", "Bushels"),
        ("units", "Units"),
    ]
    production_unit = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        blank=True,
        null=True,
        help_text="Unit of measurement for production amount",
    )

    QUALITY_CHOICES = [
        ("premium", "Premium Grade"),
        ("grade_a", "Grade A"),
        ("grade_b", "Grade B"),
        ("standard", "Standard"),
        ("processing", "Processing Grade"),
    ]
    quality_grade = models.CharField(
        max_length=20,
        choices=QUALITY_CHOICES,
        blank=True,
        null=True,
        help_text="Quality grade of the harvest",
    )

    HARVEST_METHOD_CHOICES = [
        ("manual", "Manual Harvest"),
        ("mechanical", "Mechanical Harvest"),
        ("mixed", "Mixed (Manual + Mechanical)"),
    ]
    harvest_method = models.CharField(
        max_length=20,
        choices=HARVEST_METHOD_CHOICES,
        blank=True,
        null=True,
        help_text="Method used for harvesting",
    )
    qr_code = models.ImageField(upload_to="qr_codes", blank=True)
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
    reputation = models.FloatField(default=0, validators=[MinValueValidator(0), MaxValueValidator(5)])

    # Trust metrics for enhanced transparency
    confidence_score = models.FloatField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Statistical confidence in carbon calculations (0-100%)",
    )
    transparency_score = models.FloatField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Overall transparency rating (0-100%)",
    )
    public_views = models.PositiveIntegerField(default=0, help_text="Total public page views (QR + direct + search)")
    unique_visitors = models.PositiveIntegerField(
        default=0, help_text="Estimated unique visitors (session-based tracking)"
    )
    updated_at = models.DateTimeField(auto_now=True, help_text="Last time production data was updated")
    product = models.ForeignKey(
        "product.Product",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="histories",
    )
    parcel = models.ForeignKey(
        Parcel,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="histories",
    )
    is_outdoor = models.BooleanField(default=True)
    age_of_plants = models.CharField(max_length=50, blank=True, null=True, help_text="Age of plants/trees")
    number_of_plants = models.CharField(max_length=50, blank=True, null=True, help_text="Number of plants")
    soil_ph = models.CharField(max_length=20, blank=True, null=True, help_text="Soil pH level")
    operator = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, blank=True, null=True, related_name="productions_operated"
    )

    # Crop type for this production (migrated from Parcel)
    crop_type = models.ForeignKey(
        "carbon.CropType",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="productions",
        help_text="Crop type for this production",
    )

    def __str__(self) -> str:
        return (
            "[ "
            + str(self.start_date.strftime("%m/%d/%Y"))
            + " - "
            + (str(self.finish_date.strftime("%m/%d/%Y")) if self.finish_date else "present")
            + " ]"
            + " - "
            + self.product.name
            if self.product
            else ""
        )

    def get_involved_users(self):
        users = (
            self.history_weatherevent_events.all()
            .values_list("created_by", flat=True)
            .union(self.history_chemicalevent_events.all().values_list("created_by", flat=True))
            .union(self.history_productionevent_events.all().values_list("created_by", flat=True))
            .union(self.history_generalevent_events.all().values_list("created_by", flat=True))
            .union(self.history_equipmentevent_events.all().values_list("created_by", flat=True))
            .union(self.history_soilmanagementevent_events.all().values_list("created_by", flat=True))
            .union(self.history_pestmanagementevent_events.all().values_list("created_by", flat=True))
            .union(self.history_businessevent_events.all().values_list("created_by", flat=True))
        )
        return users

    def update_reputation(self):
        average_reputation = self.reviews.aggregate(Avg("rating"))["rating__avg"]
        if average_reputation is not None:
            self.reputation = round(average_reputation, 2)
        else:
            # If there are no reviews, the default reputation is 0
            self.reputation = 0.00
        self.save()

    def calculate_confidence_score(self):
        """
        Calculate statistical confidence in carbon calculations (0-100%)
        Based on data completeness, measurement precision, verification status

        ⚡ OPTIMIZATION: Uses prefetched event data when available (no queries),
        falls back to .count() only when necessary.
        """
        score = 0

        # Data completeness (40 points)
        required_fields = ["start_date", "finish_date", "production_amount", "parcel", "product"]
        completed_fields = sum(1 for field in required_fields if getattr(self, field))
        score += (completed_fields / len(required_fields)) * 40

        # Events documentation (30 points)
        # ⚡ OPTIMIZATION: Use prefetched data if available, avoid COUNT queries
        total_events = 0
        try:
            # Check if events are prefetched (from view's prefetch_related)
            # Access the prefetch cache directly to avoid .count() queries
            prefetch_cache = getattr(self, '_prefetched_objects_cache', {})

            # Map relationship names to their prefetch cache keys
            event_relations = [
                'history_productionevent_events',
                'history_chemicalevent_events',
                'history_weatherevent_events',
                'history_generalevent_events',
                'history_equipmentevent_events',
                'history_soilmanagementevent_events',
                'history_pestmanagementevent_events',
                'history_businessevent_events'
            ]

            # Try to use prefetched data, fall back to .count() if not available
            if prefetch_cache:
                # Events are prefetched, use cached list lengths (no queries)
                for relation_name in event_relations:
                    if relation_name in prefetch_cache:
                        total_events += len(prefetch_cache[relation_name])
                    else:
                        # Fallback for this specific relation
                        total_events += getattr(self, relation_name).count()
            else:
                # Not prefetched, use .count() (triggers queries)
                for relation_name in event_relations:
                    total_events += getattr(self, relation_name).count()
        except Exception:
            # Fallback for any edge cases - use .count()
            total_events = (
                self.history_productionevent_events.count()
                + self.history_chemicalevent_events.count()
                + self.history_weatherevent_events.count()
                + self.history_generalevent_events.count()
                + self.history_equipmentevent_events.count()
                + self.history_soilmanagementevent_events.count()
                + self.history_pestmanagementevent_events.count()
                + self.history_businessevent_events.count()
            )
        if total_events > 0:
            score += min(total_events * 3, 30)  # 3 points per event, max 30

        # USDA verification (20 points)
        if hasattr(self, "carbon_entries") and self.carbon_entries.filter(usda_verified=True).exists():
            score += 20

        # Recent updates (10 points)
        from django.utils import timezone

        if self.updated_at and (timezone.now() - self.updated_at).days < 30:
            score += 10

        return min(round(score, 1), 100.0)

    def calculate_transparency_score(self):
        """
        Calculate overall transparency rating (0-100%) using enhanced anti-gaming system
        NOW INTEGRATED with advanced photo verification and anti-gaming measures
        """
        try:
            # Use the enhanced TransparencyCalculator service with anti-gaming photo verification
            from .services.transparency_calculator import TransparencyCalculator

            calculator = TransparencyCalculator()
            transparency_data = calculator.calculate_transparency_score(self)

            return transparency_data.get("transparency_percentage", 0.0)

        except Exception as e:
            # Fallback to basic calculation if service fails
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(f"Enhanced transparency calculation failed for history {self.id}: {str(e)}")

            # Simple fallback without photo verification
            score = 0

            # Basic completeness
            if self.name and self.description:
                score += 30

            # Event count (without photo requirements)
            total_events = (
                self.history_productionevent_events.count()
                + self.history_chemicalevent_events.count()
                + self.history_generalevent_events.count()
                + self.history_equipmentevent_events.count()
                + self.history_soilmanagementevent_events.count()
                + self.history_pestmanagementevent_events.count()
                + self.history_businessevent_events.count()
            )

            if total_events >= 10:
                score += 40
            elif total_events >= 5:
                score += 20

            # Public accessibility
            if self.published:
                score += 20

            # Verification
            if hasattr(self, "carbon_entries") and self.carbon_entries.exists():
                score += 10

            return min(score, 100.0)

    def get_farm_history_years(self):
        """
        Calculate years the farm has been operating based on establishment year
        """
        if self.parcel and self.parcel.establishment and self.parcel.establishment.year_established:
            from datetime import datetime

            current_year = datetime.now().year
            return max(0, current_year - self.parcel.establishment.year_established)
        return 0

    def update_trust_metrics(self):
        """
        Update all trust metrics (confidence_score, transparency_score)
        Call this when production data changes
        """
        self.confidence_score = self.calculate_confidence_score()
        self.transparency_score = self.calculate_transparency_score()
        # Note: public_views is updated separately via view tracking
        self.save(update_fields=["confidence_score", "transparency_score"])

    def increment_public_views(self, request=None, skip_bot_check=False):
        """
        Increment public view counter (separate from QR scans)
        with bot filtering and unique visitor tracking

        Args:
            request: Django request object for user agent analysis
            skip_bot_check: Skip bot detection (for testing)
        """
        import logging

        from django.db.models import F

        logger = logging.getLogger(__name__)

        # Bot detection - skip if likely a bot/crawler
        if request and not skip_bot_check:
            user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
            bot_indicators = [
                "bot",
                "crawler",
                "spider",
                "scraper",
                "facebook",
                "twitter",
                "linkedinbot",
                "whatsapp",
                "telegram",
                "googlebot",
                "bingbot",
                "slackbot",
                "discordbot",
                "applebot",
                "yandexbot",
                "baiduspider",
            ]

            if any(indicator in user_agent for indicator in bot_indicators):
                logger.info(f"Skipping view increment for bot: {user_agent[:100]}")
                return {"views_incremented": False, "unique_visitor": False, "reason": "bot_detected"}

        try:
            # Check if this is a unique visitor (session-based)
            is_unique_visitor = False
            if request and hasattr(request, "session"):
                session_key = f"viewed_production_{self.id}"
                if not request.session.get(session_key):
                    is_unique_visitor = True
                    request.session[session_key] = True
                    request.session.save()

            # Atomic increment to prevent race conditions
            update_fields = {"public_views": F("public_views") + 1}
            if is_unique_visitor:
                update_fields["unique_visitors"] = F("unique_visitors") + 1

            History.objects.filter(id=self.id).update(**update_fields)
            self.refresh_from_db(fields=["public_views", "unique_visitors"])

            logger.debug(
                f"Incremented public views for production {self.id} to {self.public_views}"
                f"{' (unique visitor)' if is_unique_visitor else ''}"
            )

            return {
                "views_incremented": True,
                "unique_visitor": is_unique_visitor,
                "total_views": self.public_views,
                "unique_visitors": self.unique_visitors,
            }

        except Exception as e:
            logger.error(f"Error incrementing public views for production {self.id}: {str(e)}")
            return {"views_incremented": False, "unique_visitor": False, "reason": "error", "error": str(e)}

    def save(self, *args, **kwargs):
        # Check if this is a new object
        is_new = not self.id

        # Save first to get ID if this is a new object
        if is_new:
            super().save(*args, **kwargs)

        # Generate secure QR URL with HMAC signature
        secure_url = generate_secure_qr_url(
            f"{settings.BASE_CONSUMER_URL}production/{self.id}",
            self.id,
            expiry_hours=24 * 365,  # 1 year expiry for production QR codes
        )

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(secure_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # Save the QR code image to a BytesIO object
        buf = BytesIO()
        img.save(buf)

        # Set the `qr_code` field to be the contents of the BytesIO object
        self.qr_code.save(
            f"{self.name}-{self.start_date}.png",
            ContentFile(buf.getvalue()),
            save=False,
        )

        # Only save again if this was a new object (to update the QR code field)
        # For existing objects, the save will happen normally
        if is_new:
            super().save(update_fields=["qr_code"])
        else:
            super().save(*args, **kwargs)

    @property
    def certificate_percentage(self):
        # Certificate percentage calculation removed as part of simplification
        return 0

    def finish(self, history_data, images):
        from datetime import datetime

        from django.utils import timezone

        if images is not None:
            gallery = Gallery.objects.create()
            for image_data in images:
                gallery_image = gallery.images.create(image=image_data)
                gallery_image.save()
            print(gallery.id)
            print(gallery.images.all())
            self.album = gallery

        # Handle finish_date with timezone awareness
        finish_date = history_data["finish_date"]
        if isinstance(finish_date, str):
            # Parse string datetime and make it timezone-aware
            finish_date = datetime.fromisoformat(finish_date.replace("Z", "+00:00"))
            if finish_date.tzinfo is None:
                finish_date = timezone.make_aware(finish_date)
        elif isinstance(finish_date, datetime) and finish_date.tzinfo is None:
            # Make naive datetime timezone-aware
            finish_date = timezone.make_aware(finish_date)

        self.finish_date = finish_date
        self.observation = history_data["observation"]
        self.published = True
        self.production_amount = history_data["production_amount"]
        self.lot_id = history_data["lot_id"]

        # Harvest details for consumer transparency (Sprint 3)
        self.production_unit = history_data.get("production_unit")
        self.quality_grade = history_data.get("quality_grade")
        self.harvest_method = history_data.get("harvest_method")

        self.save()

    def get_events(self):
        from .serializers import (
            BusinessEventSerializer,
            ChemicalEventSerializer,
            EquipmentEventSerializer,
            GeneralEventSerializer,
            PestManagementEventSerializer,
            ProductionEventSerializer,
            SoilManagementEventSerializer,
            WeatherEventSerializer,
        )

        events = (
            WeatherEventSerializer(self.history_weatherevent_events.all(), many=True).data
            + ChemicalEventSerializer(self.history_chemicalevent_events.all(), many=True).data
            + ProductionEventSerializer(self.history_productionevent_events.all(), many=True).data
            + GeneralEventSerializer(self.history_generalevent_events.all(), many=True).data
            + EquipmentEventSerializer(self.history_equipmentevent_events.all(), many=True).data
            + SoilManagementEventSerializer(self.history_soilmanagementevent_events.all(), many=True).data
            + PestManagementEventSerializer(self.history_pestmanagementevent_events.all(), many=True).data
            + BusinessEventSerializer(self.history_businessevent_events.all(), many=True).data
        )
        return sorted(events, key=lambda event: event["index"])


class CommonEvent(models.Model):
    description = models.TextField()
    date = models.DateTimeField()
    album = models.ForeignKey("common.Gallery", on_delete=models.CASCADE, blank=True, null=True)
    history = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_events",
    )
    index = models.IntegerField(default=0)
    created_by = models.ForeignKey("users.User", on_delete=models.CASCADE, blank=True, null=True)
    # Sprint 1 Epic 1.4: USDA GAP Traceability - Who performed this agricultural activity
    performed_by = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Name of person who performed this agricultural activity (USDA GAP traceability)",
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        if self.history is None:
            return "-"
        if self.history.parcel is not None:
            return self.history.parcel.name + " - " + self.history.parcel.establishment.name
        else:
            return self.history.name


class WeatherEvent(CommonEvent):
    FROST = "FR"
    DROUGHT = "DR"
    HAILSTORM = "HL"
    HIGH_TEMPERATURE = "HT"
    TROPICAL_STORM = "TS"
    HIGH_WINDS = "HW"
    HIGH_HUMIDITY = "HH"
    LOW_HUMIDITY = "LH"

    WEATHER_EVENTS = (
        (FROST, "Frost"),
        (DROUGHT, "Drought"),
        (HAILSTORM, "Hailstorm"),
        (HIGH_TEMPERATURE, "High Temperature"),
        (TROPICAL_STORM, "Tropical Storm"),
        (HIGH_WINDS, "High Winds"),
        (HIGH_HUMIDITY, "High Humidity"),
        (LOW_HUMIDITY, "Low Humidity"),
    )

    type = models.CharField(
        max_length=2,
        choices=WEATHER_EVENTS,
    )
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)


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

    # Chemical subtype choices - used for accurate carbon emission factor selection
    # These subtypes have different manufacturing emission factors
    HERBICIDE_SUBTYPE_CHOICES = [
        ("synthetic", "Synthetic (Glyphosate, 2,4-D, Atrazine, etc.)"),
        ("organic", "Organic/Natural (Vinegar, Acetic Acid, Clove Oil, etc.)"),
    ]

    FUNGICIDE_SUBTYPE_CHOICES = [
        ("synthetic", "Synthetic (Chlorothalonil, Mancozeb, etc.)"),
        ("copper", "Copper-Based (Bordeaux Mix, Copper Sulfate, Kocide, etc.)"),
        ("sulfur", "Sulfur-Based"),
        ("biological", "Biological (Bacillus, Trichoderma, etc.)"),
    ]

    PESTICIDE_SUBTYPE_CHOICES = [
        ("synthetic", "Synthetic (Conventional)"),
        ("organic", "Organic/Natural (Neem, Pyrethrin, etc.)"),
        ("biological", "Biological (Bt, Spinosad, etc.)"),
    ]

    FERTILIZER_SUBTYPE_CHOICES = [
        ("synthetic", "Synthetic/Chemical (Urea, Ammonium Nitrate, etc.)"),
        ("organic", "Organic (Compost, Manure, etc.)"),
        ("slow_release", "Slow-Release/Controlled"),
    ]

    # Combined choices for database storage
    CHEMICAL_SUBTYPE_CHOICES = [
        # Herbicide subtypes
        ("synthetic_herbicide", "Synthetic Herbicide"),
        ("organic_herbicide", "Organic/Natural Herbicide"),
        # Fungicide subtypes
        ("synthetic_fungicide", "Synthetic Fungicide"),
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
    application_method_structured = models.CharField(
        max_length=20,
        choices=[
            ("broadcast", "Broadcast"),
            ("injection", "Soil Injection"),
            ("foliar", "Foliar Application"),
            ("drip", "Drip/Fertigation"),
            ("banding", "Band Application"),
        ],
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
        choices=[
            ("L", "Liters"),
            ("gal", "Gallons"),
            ("kg", "Kilograms"),
            ("kWh", "Kilowatt-hours"),
        ],
        default="L",
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

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    organic_approved = models.CharField(
        max_length=20,
        choices=[
            ("yes", "Yes - Organic Approved"),
            ("no", "No - Not Organic"),
            ("not_applicable", "Not Applicable"),
        ],
        blank=True,
        null=True,
        help_text="Whether this chemical is approved for organic farming",
    )
    buffer_zone_meters = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Buffer zone maintained near water sources or sensitive habitats (meters)",
    )

    # EPA Worker Protection Standard (WPS) Compliance Fields - 40 CFR 170.309
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
            total_npk = self.nitrogen_percentage + self.phosphorus_percentage + self.potassium_percentage
            if total_npk > 100:
                errors["__all__"] = (
                    f"Total NPK percentages cannot exceed 100%. "
                    f"Current total: {total_npk}% "
                    f"(N: {self.nitrogen_percentage}%, "
                    f"P: {self.phosphorus_percentage}%, "
                    f"K: {self.potassium_percentage}%)"
                )

        # EPA WPS Compliance Validation - 40 CFR 170.309
        # Restricted Use Pesticides (RUPs) require certified applicator
        if self.restricted_use_pesticide and not self.applicator_certification:
            errors["applicator_certification"] = (
                "Applicator certification is required for Restricted Use Pesticides (RUPs) "
                "per EPA Worker Protection Standard 40 CFR 170.309"
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

        if errors:
            raise ValidationError(errors)

        super().clean()


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
        choices=[
            ("ha", "Hectares"),
            ("acres", "Acres"),
            ("m2", "Square Meters"),
            ("km2", "Square Kilometers"),
        ],
        default="ha",
        blank=True,
        help_text="Area unit",
    )
    yield_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Quantity harvested or planted"
    )
    yield_unit = models.CharField(
        max_length=10,
        choices=[
            ("kg", "Kilograms"),
            ("tons", "Tonnes"),
            ("lbs", "Pounds"),
            ("boxes", "Boxes"),
            ("plants", "Plants"),
            ("seeds", "Seeds"),
        ],
        default="kg",
        blank=True,
        help_text="Yield unit",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Fuel consumed during production activity"
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=[
            ("L", "Liters"),
            ("gal", "Gallons"),
            ("kg", "Kilograms"),
            ("kWh", "Kilowatt-hours"),
        ],
        default="L",
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
        choices=[
            ("km", "Kilometers"),
            ("miles", "Miles"),
            ("m", "Meters"),
        ],
        default="km",
        blank=True,
        help_text="Transportation unit",
    )
    production_efficiency = models.CharField(
        max_length=10,
        choices=[
            ("high", "High Efficiency"),
            ("normal", "Normal Efficiency"),
            ("low", "Low Efficiency"),
        ],
        default="normal",
        blank=True,
        help_text="Production efficiency rating for carbon scoring",
    )

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    # Updated based on agricultural advisor + consumer trust analysis (2025-12-06)
    # Optimized for: farmer practicality, consumer trust, transparency-first approach
    seeds_source = models.CharField(
        max_length=50,
        choices=[
            ("certified_organic", "Certified Organic Seeds"),
            ("farm_saved", "Farm-Saved Seeds"),
            ("local", "Local Nursery/Supplier"),
            ("cooperative", "Farmer Cooperative"),
            ("commercial", "Commercial Supplier"),
            ("other", "Other"),
        ],
        blank=True,
        null=True,
        help_text="Source of seeds/seedlings for consumer transparency (does not affect carbon calculations)",
    )
    # Updated 2025-12-06: Aligned with transparency-first frontend choices
    water_source = models.CharField(
        max_length=50,
        choices=[
            ("well_groundwater", "Well/Groundwater"),
            ("municipal", "Municipal Water Supply"),
            ("rainwater_harvesting", "Rainwater Harvesting"),
            ("irrigation_canal", "Irrigation Canal/District"),
            ("river_stream", "River/Stream"),
            ("pond_reservoir", "Pond/Reservoir"),
            ("recycled_water", "Recycled/Reclaimed Water"),
            ("other", "Other"),
        ],
        blank=True,
        null=True,
        help_text="Water source for irrigation transparency (does not affect carbon calculations)",
    )

    # USDA NASS 2023 Irrigation Fields - For Irrigation (IR) events
    # These fields enable accurate water usage estimation for transparency reporting
    irrigation_method = models.CharField(
        max_length=30,
        choices=[
            ("flood", "Flood Irrigation"),
            ("furrow", "Furrow Irrigation"),
            ("drip", "Drip Irrigation"),
            ("sprinkler", "Sprinkler System"),
            ("center_pivot", "Center Pivot"),
            ("sub_irrigation", "Sub-surface Irrigation"),
            ("micro_sprinkler", "Micro-sprinkler"),
            ("hand_watering", "Hand Watering"),
            ("rain_fed", "Rain-fed Only"),
        ],
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
        choices=[
            ("inches", "Inches"),
            ("cm", "Centimeters"),
        ],
        default="inches",
        blank=True,
        null=True,
        help_text="Unit for irrigation depth measurement",
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
        choices=[
            ("tractor", "Tractor"),
            ("harvester", "Harvester/Combine"),
            ("sprayer", "Sprayer"),
            ("truck", "Truck/Transport"),
            ("generator", "Generator"),
            ("pump", "Irrigation Pump"),
            ("other", "Other Equipment"),
        ],
        blank=True,
        null=True,
        help_text="Type of equipment used (for carbon calculation accuracy)",
    )
    equipment_operation_type = models.CharField(
        max_length=2,
        choices=[
            ("FC", "Fuel Consumption"),
            ("MN", "Maintenance"),
            ("RE", "Repair"),
            ("CA", "Calibration"),
            ("BD", "Breakdown"),
            ("EI", "Inspection"),
        ],
        blank=True,
        null=True,
        help_text="Type of equipment operation (for Equipment Maintenance events)",
    )

    def clean(self):
        """Model-level validation for production event values and business logic"""
        errors = {}

        # Validate area_covered - must be positive for most operations
        if self.area_covered is not None and self.area_covered <= 0:
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

        if errors:
            raise ValidationError(errors)


class GeneralEvent(CommonEvent):
    name = models.CharField(max_length=150, help_text="Event name")
    observation = models.TextField(blank=True, null=True)

    # Activity details for comprehensive farm transparency
    activity_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Type of activity performed (e.g., Farm Maintenance, Equipment Setup)",
    )
    activity_name = models.CharField(
        max_length=200, blank=True, null=True, help_text="Specific name or description of the activity"
    )
    duration = models.CharField(
        max_length=50, blank=True, null=True, help_text="Duration of the activity (e.g., '2 hours', '1 day')"
    )
    people_involved = models.PositiveIntegerField(
        blank=True, null=True, help_text="Number of people involved in the activity"
    )

    extra_data = models.JSONField(blank=True, null=True)


class HistoryScan(models.Model):
    """
    Enhanced QR scan tracking with 2025 privacy, performance & security standards
    Supports dual functionality: page view analytics + consumer feedback collection
    """

    # EXISTING CORE FIELDS
    history = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        related_name="history_scans",
    )
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, blank=True, null=True)
    date = models.DateTimeField(auto_now_add=True)
    comment = models.TextField(blank=True, null=True)

    # PRIVACY & GDPR COMPLIANCE (2025 Standard)
    ip_hash = models.CharField(
        max_length=64,
        db_index=True,
        blank=True,
        null=True,
        help_text="SHA-256 hash of IP address for privacy-safe analytics",
    )
    consent_given = models.BooleanField(default=False, help_text="GDPR consent for analytics tracking")
    consent_timestamp = models.DateTimeField(null=True, blank=True, help_text="When consent was given")
    data_retention_until = models.DateTimeField(null=True, blank=True, help_text="Auto-cleanup date (GDPR compliance)")

    # ENHANCED GEOLOCATION (Privacy-safe)
    country_code = models.CharField(max_length=2, blank=True, help_text="ISO country code (privacy-safe)")
    region = models.CharField(max_length=100, blank=True, help_text="State/region only (no city for privacy)")

    # LEGACY FIELDS (Deprecated - use privacy-safe alternatives above)
    ip_address = models.CharField(max_length=45, blank=True, null=True, help_text="DEPRECATED: Use ip_hash instead")
    city = models.CharField(max_length=100, blank=True, null=True, help_text="DEPRECATED: Use region instead")
    country = models.CharField(max_length=100, blank=True, null=True, help_text="DEPRECATED: Use country_code instead")

    # SESSION & DEDUPLICATION
    session_hash = models.CharField(
        max_length=64, db_index=True, blank=True, help_text="Privacy-safe browser fingerprint for deduplication"
    )
    is_duplicate = models.BooleanField(default=False, help_text="Mark duplicate scans within timeframe")
    original_scan = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Link to original scan if this is a duplicate",
    )

    # BOT DETECTION & QUALITY CONTROL
    bot_score = models.FloatField(default=0.0, help_text="Bot probability (0.0=human, 1.0=bot)")
    is_verified_human = models.BooleanField(default=False, help_text="Passed human verification checks")
    user_agent_hash = models.CharField(max_length=64, blank=True, help_text="Hashed user agent for pattern analysis")

    # ENGAGEMENT & ANALYTICS
    scan_type = models.CharField(
        max_length=20,
        choices=[
            ("qr", "QR Code Scan"),
            ("feedback", "Feedback Only"),
            ("review", "Full Review"),
            ("share", "Social Share"),
        ],
        default="qr",
        help_text="Type of interaction",
    )
    engagement_score = models.FloatField(default=0.0, help_text="Engagement quality (time spent, interactions)")
    referrer_type = models.CharField(
        max_length=50,
        blank=True,
        choices=[
            ("qr", "QR Code"),
            ("direct", "Direct Link"),
            ("social", "Social Media"),
            ("search", "Search Engine"),
            ("email", "Email"),
            ("other", "Other"),
        ],
        default="qr",
        help_text="How user reached the page",
    )

    # PERFORMANCE INDEXES
    class Meta:
        indexes = [
            # Time-series queries for dashboard analytics
            models.Index(fields=["date", "history"], name="historyscan_date_history_idx"),
            # Session deduplication queries
            models.Index(fields=["session_hash", "date"], name="historyscan_session_date_idx"),
            # Rate limiting by IP hash
            models.Index(fields=["ip_hash", "date"], name="historyscan_ip_date_idx"),
            # GDPR cleanup queries
            models.Index(fields=["data_retention_until"], name="historyscan_retention_idx"),
            # Quality filtering (exclude bots/duplicates)
            models.Index(fields=["is_duplicate", "bot_score"], name="historyscan_quality_idx"),
            # Consent management
            models.Index(fields=["consent_given", "date"], name="historyscan_consent_idx"),
            # Analytics queries by scan type
            models.Index(fields=["scan_type", "date"], name="historyscan_type_date_idx"),
        ]
        verbose_name = "History Scan"
        verbose_name_plural = "History Scans"

    def __str__(self):
        return f"Scan {self.id} - {self.history} - {self.date.strftime('%Y-%m-%d')}"

    def is_privacy_compliant(self):
        """Check if scan data follows privacy best practices"""
        return bool(
            self.ip_hash  # Uses hashed IP, not raw
            and not self.ip_address  # No raw IP stored
            and self.consent_given  # Has user consent
            and self.data_retention_until  # Has cleanup date
        )

    def is_high_quality(self):
        """Check if scan is high quality (human, not duplicate, engaged)"""
        return bool(not self.is_duplicate and self.bot_score < 0.3 and self.engagement_score > 0.1)

    def get_location_display(self):
        """Get privacy-safe location display"""
        if self.country_code and self.region:
            return f"{self.region}, {self.country_code.upper()}"
        elif self.country_code:
            return self.country_code.upper()
        # Fallback to legacy data if new data not available
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return "Unknown"


class EquipmentEvent(CommonEvent):
    """Events related to equipment maintenance, repairs, and fuel consumption"""

    # Equipment event types
    MAINTENANCE = "MN"
    REPAIR = "RE"
    CALIBRATION = "CA"
    FUEL_CONSUMPTION = "FC"
    BREAKDOWN = "BD"
    INSPECTION = "EI"

    EQUIPMENT_TYPE_CHOICES = [
        (MAINTENANCE, "Maintenance"),
        (REPAIR, "Repair"),
        (CALIBRATION, "Calibration"),
        (FUEL_CONSUMPTION, "Fuel Consumption"),
        (BREAKDOWN, "Breakdown"),
        (INSPECTION, "Inspection"),
    ]

    type = models.CharField(max_length=2, choices=EQUIPMENT_TYPE_CHOICES, default=MAINTENANCE)
    equipment_name = models.CharField(max_length=100, blank=True)
    fuel_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fuel_type = models.CharField(
        max_length=30,
        choices=FUEL_TYPES,
        blank=True,
        default="",
        help_text="Fuel type for EPA emission factor calculation",
    )
    maintenance_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hours_used = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    area_covered = models.CharField(max_length=100, blank=True)
    extra_data = models.JSONField(blank=True, null=True)

    # New structured fields for better carbon calculations
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    equipment_type_structured = models.CharField(
        max_length=30,
        choices=[
            ("tractor_small", "Small Tractor (<75 HP)"),
            ("tractor_medium", "Medium Tractor (75-150 HP)"),
            ("tractor_large", "Large Tractor (>150 HP)"),
            ("irrigation_pump", "Irrigation Pump"),
            ("harvester", "Combine Harvester"),
            ("sprayer", "Field Sprayer"),
            ("cultivator", "Cultivator/Plow"),
            ("transport", "Transport Vehicle"),
        ],
        null=True,
        blank=True,
        help_text="Structured equipment type for carbon calculations",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed (renamed from fuel_amount for clarity)",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=[
            ("L", "Liters"),
            ("gal", "Gallons"),
            ("kg", "Kilograms"),
            ("kWh", "Kilowatt-hours"),
        ],
        default="L",
        blank=True,
        help_text="Fuel unit",
    )
    hours_operated = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Hours operated (renamed from hours_used for clarity)",
    )
    area_worked = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Area worked in numeric format"
    )
    area_unit = models.CharField(
        max_length=10,
        choices=[
            ("ha", "Hectares"),
            ("acres", "Acres"),
            ("m2", "Square Meters"),
        ],
        default="ha",
        blank=True,
        help_text="Area unit",
    )
    operation_efficiency = models.CharField(
        max_length=10,
        choices=[
            ("high", "High Efficiency"),
            ("normal", "Normal Efficiency"),
            ("low", "Low Efficiency"),
        ],
        default="normal",
        blank=True,
        help_text="Operation efficiency rating for carbon scoring",
    )
    observation = models.TextField(blank=True, null=True, help_text="Equipment event observations")

    def clean(self):
        """Model-level validation for equipment event values and business logic"""
        from django.core.exceptions import ValidationError

        errors = {}

        # Validate fuel_consumed is non-negative
        if self.fuel_consumed is not None and self.fuel_consumed < 0:
            errors["fuel_consumed"] = "Fuel consumed cannot be negative"

        # Validate hours_operated is non-negative
        if self.hours_operated is not None and self.hours_operated < 0:
            errors["hours_operated"] = "Hours operated cannot be negative"

        # Validate maintenance_cost is non-negative
        if self.maintenance_cost is not None and self.maintenance_cost < 0:
            errors["maintenance_cost"] = "Maintenance cost cannot be negative"

        # Validate area_worked is non-negative
        if self.area_worked is not None and self.area_worked < 0:
            errors["area_worked"] = "Area worked cannot be negative"

        # Business logic validations

        # If fuel consumption is provided, hours operated should also be provided for accuracy
        if self.fuel_consumed and self.fuel_consumed > 0 and not self.hours_operated:
            if "hours_operated" not in errors:
                errors["hours_operated"] = "Hours operated should be provided when fuel consumption is recorded"

        # Validate reasonable fuel efficiency (basic sanity check)
        if self.fuel_consumed and self.fuel_consumed > 0 and self.hours_operated and self.hours_operated > 0:
            fuel_per_hour = float(self.fuel_consumed) / float(self.hours_operated)

            # Reasonable fuel consumption: 0.5L/hr to 50L/hr (covers small pumps to large tractors)
            if fuel_per_hour > 50:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably high. Check values."
                )
            elif fuel_per_hour < 0.5:
                errors["fuel_consumed"] = (
                    f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unreasonably low. Check values."
                )

        # Validate reasonable operating hours (max 1000 hours for multi-day operations)
        if self.hours_operated and self.hours_operated > 1000:
            errors["hours_operated"] = "Hours operated cannot exceed 1000 hours per event"

        if errors:
            raise ValidationError(errors)

        super().clean()

    class Meta:
        verbose_name = "Equipment Event"
        verbose_name_plural = "Equipment Events"


class SoilManagementEvent(CommonEvent):
    """Events related to soil testing, amendments, and organic matter management"""

    # Soil management event types
    SOIL_TEST = "ST"
    PH_ADJUSTMENT = "PA"
    ORGANIC_MATTER = "OM"
    COVER_CROP = "CC"
    TILLAGE = "TI"
    COMPOSTING = "CO"

    SOIL_TYPE_CHOICES = [
        (SOIL_TEST, "Soil Test"),
        (PH_ADJUSTMENT, "pH Adjustment"),
        (ORGANIC_MATTER, "Organic Matter Addition"),
        (COVER_CROP, "Cover Crop"),
        (TILLAGE, "Tillage"),
        (COMPOSTING, "Composting"),
    ]

    type = models.CharField(max_length=2, choices=SOIL_TYPE_CHOICES, default=SOIL_TEST)
    soil_ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    organic_matter_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amendment_type = models.CharField(max_length=100, blank=True)
    amendment_amount = models.CharField(max_length=100, blank=True)
    test_results = models.JSONField(null=True, blank=True)  # Store complex test data
    carbon_sequestration_potential = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Standardized fields for carbon calculations (matching ProductionEvent pattern)
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")
    area_covered = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="Area covered in numeric format"
    )
    area_unit = models.CharField(
        max_length=10,
        choices=[
            ("ha", "Hectares"),
            ("acres", "Acres"),
            ("m2", "Square Meters"),
            ("km2", "Square Kilometers"),
        ],
        default="ha",
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
        choices=[
            ("L", "Liters"),
            ("gal", "Gallons"),
            ("kg", "Kilograms"),
            ("kWh", "Kilowatt-hours"),
        ],
        default="L",
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
        choices=[
            ("km", "Kilometers"),
            ("miles", "Miles"),
            ("m", "Meters"),
        ],
        default="km",
        blank=True,
        help_text="Transportation unit",
    )
    production_efficiency = models.CharField(
        max_length=10,
        choices=[
            ("high", "High Efficiency"),
            ("normal", "Normal Efficiency"),
            ("low", "Low Efficiency"),
        ],
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

        # Transportation efficiency check
        if self.transportation_distance and self.transportation_distance > 500:
            errors["transportation_distance"] = (
                f"Transportation distance ({self.transportation_distance} {self.transportation_unit}) is very long. Consider local processing to reduce carbon footprint."
            )

        if errors:
            raise ValidationError(errors)

    class Meta:
        verbose_name = "Soil Management Event"
        verbose_name_plural = "Soil Management Events"


class PestManagementEvent(CommonEvent):
    """Events related to pest monitoring, beneficial insect releases, and IPM practices"""

    # Pest management event types
    SCOUTING = "SC"
    BENEFICIAL_RELEASE = "BR"
    TRAP_MONITORING = "TM"
    PEST_IDENTIFICATION = "PI"
    THRESHOLD_ASSESSMENT = "TA"
    IPM_IMPLEMENTATION = "IP"

    PEST_TYPE_CHOICES = [
        (SCOUTING, "Scouting"),
        (BENEFICIAL_RELEASE, "Beneficial Release"),
        (TRAP_MONITORING, "Trap Monitoring"),
        (PEST_IDENTIFICATION, "Pest Identification"),
        (THRESHOLD_ASSESSMENT, "Threshold Assessment"),
        (IPM_IMPLEMENTATION, "IPM Implementation"),
    ]

    type = models.CharField(max_length=2, choices=PEST_TYPE_CHOICES, default=SCOUTING)
    pest_species = models.CharField(max_length=200, blank=True)
    pest_pressure_level = models.CharField(max_length=50, blank=True)  # Low, Medium, High
    beneficial_species = models.CharField(max_length=200, blank=True)
    release_quantity = models.CharField(max_length=100, blank=True)
    trap_count = models.IntegerField(null=True, blank=True)
    damage_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    action_threshold_met = models.BooleanField(default=False)
    ipm_strategy = models.TextField(blank=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    beneficial_insects_used = models.CharField(
        max_length=20,
        choices=[
            ("yes", "Yes - Using Beneficial Insects"),
            ("no", "No"),
            ("planning", "Planning to Implement"),
        ],
        blank=True,
        null=True,
        help_text="Whether beneficial insects are used for pest control",
    )
    chemical_free_period_days = models.PositiveIntegerField(
        blank=True, null=True, help_text="Days since last synthetic chemical application"
    )

    class Meta:
        verbose_name = "Pest Management Event"
        verbose_name_plural = "Pest Management Events"


class BusinessEvent(CommonEvent):
    """Carbon-focused business events for transparency and consumer value"""

    # Business event types (legacy compatibility)
    CERTIFICATION = "CE"
    COMPLIANCE = "CM"
    INSPECTION = "IN"

    BUSINESS_TYPE_CHOICES = [
        (CERTIFICATION, "Certification"),
        (COMPLIANCE, "Compliance"),
        (INSPECTION, "Inspection"),
    ]

    # Carbon-focused business activity types
    BUSINESS_ACTIVITY_CHOICES = [
        ("certification", "Certification Event (Organic, Carbon, etc.)"),
        ("carbon_credits", "Carbon Credits Transaction"),
        ("sustainability_audit", "Sustainability Audit/Assessment"),
        ("verification", "Third-Party Verification"),
        ("compliance", "Regulatory Compliance Activity"),
        ("transparency", "Consumer Transparency Initiative"),
    ]

    # Sprint 2 Epic 2.2: Expanded certification types with GlobalG.A.P., Non-GMO, CNG
    CERTIFICATION_TYPE_CHOICES = [
        # Organic & Food Safety Certifications
        ("organic_usda", "USDA Organic"),
        ("regenerative", "Regenerative Organic Certified (ROC)"),
        ("cng", "Certified Naturally Grown (CNG)"),
        ("non_gmo", "Non-GMO Project Verified"),
        # Environmental & Sustainability Certifications
        ("carbon_neutral", "Carbon Neutral Certification"),
        ("rainforest_alliance", "Rainforest Alliance"),
        ("water_stewardship", "Water Stewardship Certification"),
        ("sustainable_agriculture", "Sustainable Agriculture Standard"),
        # Global Food Safety & Trade Certifications
        ("global_gap", "GlobalG.A.P. Certified"),
        ("fair_trade", "Fair Trade Certified"),
    ]

    CARBON_CREDIT_UNITS = [
        ("tCO2e", "tCO2e (tonnes CO2 equivalent)"),
        ("kgCO2e", "kgCO2e (kilograms CO2 equivalent)"),
        ("credits", "Carbon Credits (units)"),
    ]

    VERIFICATION_STATUS_CHOICES = [
        ("pending", "Pending Verification"),
        ("verified", "Verified"),
        ("in_progress", "Verification In Progress"),
        ("failed", "Verification Failed"),
        ("not_applicable", "Not Applicable"),
    ]

    SUSTAINABILITY_PRACTICE_CHOICES = [
        ("cover_cropping", "Cover Cropping Implementation"),
        ("no_till", "No-Till Farming Adoption"),
        ("integrated_pest", "Integrated Pest Management"),
        ("water_conservation", "Water Conservation Measures"),
        ("renewable_energy", "Renewable Energy Installation"),
        ("composting", "On-Farm Composting Program"),
        ("biodiversity", "Biodiversity Conservation"),
        ("soil_health", "Soil Health Improvement"),
    ]

    type = models.CharField(max_length=2, choices=BUSINESS_TYPE_CHOICES, default=CERTIFICATION)
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Event name")

    # New carbon-focused fields
    business_type = models.CharField(
        max_length=30,
        choices=BUSINESS_ACTIVITY_CHOICES,
        default="certification",
        help_text="Type of carbon-relevant business activity",
    )
    certification_type = models.CharField(
        max_length=50,
        choices=CERTIFICATION_TYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Type of certification obtained or renewed",
    )
    carbon_credits_earned = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True, help_text="Amount of carbon credits generated or traded"
    )
    carbon_credits_unit = models.CharField(
        max_length=10, choices=CARBON_CREDIT_UNITS, default="tCO2e", blank=True, help_text="Unit for carbon credits"
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default="pending",
        help_text="Status of verification for consumer transparency",
    )
    sustainability_practice = models.CharField(
        max_length=30,
        choices=SUSTAINABILITY_PRACTICE_CHOICES,
        blank=True,
        null=True,
        help_text="Sustainability practice implemented",
    )

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    verified_certifier_name = models.CharField(
        max_length=150, blank=True, null=True, help_text="Name of the certifying organization for consumer trust"
    )

    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)

    def clean(self):
        """Model-level validation for business event values and business logic"""
        from django.core.exceptions import ValidationError

        errors = {}

        # Validate carbon_credits_earned - must be non-negative
        if self.carbon_credits_earned is not None and self.carbon_credits_earned < 0:
            errors["carbon_credits_earned"] = "Carbon credits earned cannot be negative"

        # Business logic validation: reasonable carbon credit amounts
        if self.carbon_credits_earned and self.carbon_credits_earned > 10000:
            errors["carbon_credits_earned"] = (
                f"Carbon credits amount ({self.carbon_credits_earned} {self.carbon_credits_unit}) seems unusually large. Please verify."
            )

        # Validate business_type is not empty
        if not self.business_type or len(self.business_type.strip()) == 0:
            errors["business_type"] = "Business type is required"

        # Business logic: certification events should have certification_type
        if self.business_type == "certification" and not self.certification_type:
            errors["certification_type"] = "Certification type is required for certification events"

        # Business logic: carbon_credits events should have carbon_credits_earned
        if self.business_type == "carbon_credits" and not self.carbon_credits_earned:
            errors["carbon_credits_earned"] = "Carbon credits amount is required for carbon credit transactions"

        if errors:
            raise ValidationError(errors)

    class Meta:
        verbose_name = "Business Event"
        verbose_name_plural = "Business Events"
