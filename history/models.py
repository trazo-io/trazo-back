import qrcode
from django.conf import settings
from io import BytesIO
from django.db import models
from django.db.models import Avg
from django.core.validators import MinValueValidator, MaxValueValidator
from common.models import Gallery

from django.core.files.base import ContentFile
from backend.security.qr_security import generate_secure_qr_url


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
    qr_code = models.ImageField(upload_to="qr_codes", blank=True)
    album = models.ForeignKey(
        "common.Gallery", on_delete=models.CASCADE, blank=True, null=True
    )
    reputation = models.FloatField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(5)]
    )
    
    # Trust metrics for enhanced transparency
    confidence_score = models.FloatField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Statistical confidence in carbon calculations (0-100%)"
    )
    transparency_score = models.FloatField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Overall transparency rating (0-100%)"
    )
    public_views = models.PositiveIntegerField(
        default=0, help_text="Total public page views (QR + direct + search)"
    )
    unique_visitors = models.PositiveIntegerField(
        default=0, help_text="Estimated unique visitors (session-based tracking)"
    )
    updated_at = models.DateTimeField(
        auto_now=True, help_text="Last time production data was updated"
    )
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
        "carbon.CropType", on_delete=models.SET_NULL, blank=True, null=True, 
        related_name="productions", help_text="Crop type for this production"
    )

    def __str__(self) -> str:
        return (
            "[ "
            + str(self.start_date.strftime("%m/%d/%Y"))
            + " - "
            + (
                str(self.finish_date.strftime("%m/%d/%Y"))
                if self.finish_date
                else "present"
            )
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
            .union(
                self.history_chemicalevent_events.all().values_list(
                    "created_by", flat=True
                )
            )
            .union(
                self.history_productionevent_events.all().values_list(
                    "created_by", flat=True
                )
            )
            .union(
                self.history_generalevent_events.all().values_list(
                    "created_by", flat=True
                )
            )
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
        """
        score = 0
        
        # Data completeness (40 points)
        required_fields = ['start_date', 'finish_date', 'production_amount', 'parcel', 'product']
        completed_fields = sum(1 for field in required_fields if getattr(self, field))
        score += (completed_fields / len(required_fields)) * 40
        
        # Events documentation (30 points)
        total_events = (
            self.history_productionevent_events.count() +
            self.history_chemicalevent_events.count() +
            self.history_weatherevent_events.count() +
            self.history_generalevent_events.count()
        )
        if total_events > 0:
            score += min(total_events * 3, 30)  # 3 points per event, max 30
        
        # USDA verification (20 points)
        if hasattr(self, 'carbon_entries') and self.carbon_entries.filter(usda_verified=True).exists():
            score += 20
        
        # Recent updates (10 points)
        from django.utils import timezone
        if self.updated_at and (timezone.now() - self.updated_at).days < 30:
            score += 10
        
        return min(round(score, 1), 100.0)
    
    def calculate_transparency_score(self):
        """
        Calculate overall transparency rating (0-100%)
        Based on documentation completeness, public accessibility, third-party verifications
        """
        score = 0
        
        # Basic information completeness (25 points)
        if self.name and self.description:
            score += 15
        if self.album and self.album.images.exists():
            score += 10
        
        # Event documentation with images (25 points)
        events_with_images = 0
        total_events = (
            self.history_productionevent_events.count() +
            self.history_chemicalevent_events.count() +
            self.history_generalevent_events.count()
        )
        
        for event in self.history_productionevent_events.all():
            if hasattr(event, 'images') and event.images.exists():
                events_with_images += 1
        
        if total_events > 0:
            score += (events_with_images / total_events) * 25
        
        # Public accessibility (25 points)
        if self.published:
            score += 15
        if self.qr_code:
            score += 10
        
        # Third-party verification (25 points)
        if hasattr(self, 'carbon_entries') and self.carbon_entries.exists():
            score += 10
        if hasattr(self, 'reviews') and self.reviews.count() > 0:
            score += 10
        if hasattr(self, 'blockchain_verification') and self.blockchain_verification:
            score += 5
        
        return min(round(score, 1), 100.0)
    
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
        self.save(update_fields=['confidence_score', 'transparency_score'])
    
    def increment_public_views(self, request=None, skip_bot_check=False):
        """
        Increment public view counter (separate from QR scans)
        with bot filtering and unique visitor tracking
        
        Args:
            request: Django request object for user agent analysis
            skip_bot_check: Skip bot detection (for testing)
        """
        from django.db.models import F
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Bot detection - skip if likely a bot/crawler
        if request and not skip_bot_check:
            user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
            bot_indicators = [
                'bot', 'crawler', 'spider', 'scraper', 'facebook', 'twitter',
                'linkedinbot', 'whatsapp', 'telegram', 'googlebot', 'bingbot',
                'slackbot', 'discordbot', 'applebot', 'yandexbot', 'baiduspider'
            ]
            
            if any(indicator in user_agent for indicator in bot_indicators):
                logger.info(f"Skipping view increment for bot: {user_agent[:100]}")
                return {'views_incremented': False, 'unique_visitor': False, 'reason': 'bot_detected'}
        
        try:
            # Check if this is a unique visitor (session-based)
            is_unique_visitor = False
            if request and hasattr(request, 'session'):
                session_key = f'viewed_production_{self.id}'
                if not request.session.get(session_key):
                    is_unique_visitor = True
                    request.session[session_key] = True
                    request.session.save()
            
            # Atomic increment to prevent race conditions
            update_fields = {'public_views': F('public_views') + 1}
            if is_unique_visitor:
                update_fields['unique_visitors'] = F('unique_visitors') + 1
            
            History.objects.filter(id=self.id).update(**update_fields)
            self.refresh_from_db(fields=['public_views', 'unique_visitors'])
            
            logger.debug(
                f"Incremented public views for production {self.id} to {self.public_views}"
                f"{' (unique visitor)' if is_unique_visitor else ''}"
            )
            
            return {
                'views_incremented': True, 
                'unique_visitor': is_unique_visitor,
                'total_views': self.public_views,
                'unique_visitors': self.unique_visitors
            }
            
        except Exception as e:
            logger.error(f"Error incrementing public views for production {self.id}: {str(e)}")
            return {'views_incremented': False, 'unique_visitor': False, 'reason': 'error', 'error': str(e)}

    def save(self, *args, **kwargs):
        # Save first to get ID if this is a new object
        if not self.id:
            super().save(*args, **kwargs)
        
        # Generate secure QR URL with HMAC signature
        secure_url = generate_secure_qr_url(
            f"{settings.BASE_CONSUMER_URL}production/{self.id}",
            self.id,
            expiry_hours=24 * 365  # 1 year expiry for production QR codes
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

        super().save(*args, **kwargs)

    @property
    def certificate_percentage(self):
        # Certificate percentage calculation removed as part of simplification
        return 0

    def finish(self, history_data, images):
        from django.utils import timezone
        from datetime import datetime
        
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
            finish_date = datetime.fromisoformat(finish_date.replace('Z', '+00:00'))
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
        self.save()

    def get_events(self):
        from .serializers import (
            WeatherEventSerializer,
            ChemicalEventSerializer,
            ProductionEventSerializer,
            GeneralEventSerializer,
            EquipmentEventSerializer,
            SoilManagementEventSerializer,
            PestManagementEventSerializer,
        )

        events = (
            WeatherEventSerializer(
                self.history_weatherevent_events.all(), many=True
            ).data
            + ChemicalEventSerializer(
                self.history_chemicalevent_events.all(), many=True
            ).data
            + ProductionEventSerializer(
                self.history_productionevent_events.all(), many=True
            ).data
            + GeneralEventSerializer(
                self.history_generalevent_events.all(), many=True
            ).data
            + EquipmentEventSerializer(
                self.history_equipmentevent_events.all(), many=True
            ).data
            + SoilManagementEventSerializer(
                self.history_soilmanagementevent_events.all(), many=True
            ).data
            + PestManagementEventSerializer(
                self.history_pestmanagementevent_events.all(), many=True
            ).data
        )
        return sorted(events, key=lambda event: event["index"])


class CommonEvent(models.Model):
    description = models.TextField()
    date = models.DateTimeField()
    album = models.ForeignKey(
        "common.Gallery", on_delete=models.CASCADE, blank=True, null=True
    )
    history = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_events",
    )
    index = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, blank=True, null=True
    )

    class Meta:
        abstract = True

    def __str__(self) -> str:
        if self.history is None:
            return "-"
        if self.history.parcel is not None:
            return (
                self.history.parcel.name
                + " - "
                + self.history.parcel.establishment.name
            )
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

    type = models.CharField(
        max_length=2, choices=CHEMICAL_EVENTS, blank=True, null=True
    )
    commercial_name = models.CharField(max_length=60, blank=True, null=True)
    volume = models.CharField(max_length=60, blank=True, null=True)
    concentration = models.CharField(max_length=60, blank=True, null=True)
    area = models.CharField(max_length=60, blank=True, null=True)
    way_of_application = models.CharField(max_length=60, blank=True, null=True)
    time_period = models.CharField(max_length=60, blank=True, null=True)
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)


class ProductionEvent(CommonEvent):
    PLANTING = "PL"
    HARVESTING = "HA"
    IRRIGATION = "IR"
    PRUNING = "PR"

    PRODUCTION_EVENTS = (
        (PLANTING, "Planting"),
        (HARVESTING, "Harvesting"),
        (IRRIGATION, "Irrigation"),
        (PRUNING, "Pruning"),
    )

    type = models.CharField(max_length=2, choices=PRODUCTION_EVENTS)
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)


class GeneralEvent(CommonEvent):
    name = models.CharField(max_length=150, help_text="Event name")
    observation = models.TextField(blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)


class HistoryScan(models.Model):
    history = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        related_name="history_scans",
    )
    user = models.ForeignKey(
        "users.User", on_delete=models.CASCADE, blank=True, null=True
    )
    date = models.DateTimeField(auto_now_add=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True, help_text="IP address (IPv4/IPv6)")
    city = models.CharField(max_length=100, blank=True, null=True, help_text="Scanner city")
    country = models.CharField(max_length=100, blank=True, null=True, help_text="Scanner country")
    comment = models.TextField(blank=True, null=True)


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
    
    type = models.CharField(
        max_length=2, choices=EQUIPMENT_TYPE_CHOICES, default=MAINTENANCE
    )
    equipment_name = models.CharField(max_length=100, blank=True)
    fuel_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    fuel_type = models.CharField(max_length=50, blank=True)  # diesel, gasoline, etc.
    maintenance_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hours_used = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    area_covered = models.CharField(max_length=100, blank=True)
    extra_data = models.JSONField(blank=True, null=True)
    
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
    
    type = models.CharField(
        max_length=2, choices=SOIL_TYPE_CHOICES, default=SOIL_TEST
    )
    soil_ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    organic_matter_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amendment_type = models.CharField(max_length=100, blank=True)
    amendment_amount = models.CharField(max_length=100, blank=True)
    test_results = models.JSONField(null=True, blank=True)  # Store complex test data
    carbon_sequestration_potential = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    extra_data = models.JSONField(blank=True, null=True)
    
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
    
    type = models.CharField(
        max_length=2, choices=PEST_TYPE_CHOICES, default=SCOUTING
    )
    pest_species = models.CharField(max_length=200, blank=True)
    pest_pressure_level = models.CharField(max_length=50, blank=True)  # Low, Medium, High
    beneficial_species = models.CharField(max_length=200, blank=True)
    release_quantity = models.CharField(max_length=100, blank=True)
    trap_count = models.IntegerField(null=True, blank=True)
    damage_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    action_threshold_met = models.BooleanField(default=False)
    ipm_strategy = models.TextField(blank=True)
    extra_data = models.JSONField(blank=True, null=True)
    
    class Meta:
        verbose_name = "Pest Management Event"
        verbose_name_plural = "Pest Management Events"
