import logging
import os
import uuid
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg

import qrcode
from PIL import Image
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import SolidFillColorMask
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer

from carbon.choices import FUEL_TYPES
from common.field_registry import (
    APPLICATION_METHOD,
    CHEMICAL_SUBTYPE,
    ELECTRICITY_SOURCE,
    EQUIPMENT_OPERATION_TYPE,
    EQUIPMENT_TYPE,
    GROWTH_STAGE,
    HARVEST_QUALITY_GRADE,
    IRRIGATION_METHOD,
    ORGANIC_APPROVED,
    PRODUCTION_EFFICIENCY,
    SEED_CERTIFICATION_STATUS,
    SEEDS_SOURCE,
    UNIT_AREA,
    UNIT_DEPTH,
    UNIT_DISTANCE,
    UNIT_FUEL,
    UNIT_VOLUME,
    UNIT_YIELD,
    WATER_SOURCE,
)
from common.models import Gallery
from product.models import Parcel

logger = logging.getLogger(__name__)

# Branded QR code configuration
TRAZO_GREEN = (46, 125, 50)
TRAZO_LEAF_LOGO = os.path.join(settings.BASE_DIR, "static", "img", "trazo-leaf.png")


class History(models.Model):
    ORCHARD = "OR"
    GARDEN = "GA"

    HISTORY_TYPES = (
        (ORCHARD, "Orchard"),
        (GARDEN, "Garden"),
    )

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    name = models.CharField(max_length=150, blank=True, null=True, help_text="Production name")
    type = models.CharField(max_length=2, choices=HISTORY_TYPES, blank=True, null=True)
    extra_data = models.JSONField(blank=True, null=True)
    start_date = models.DateTimeField(null=True, blank=True)
    expected_harvest = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Planned/estimated harvest date",
    )
    finish_date = models.DateTimeField(null=True, blank=True)
    published = models.BooleanField(default=False, blank=True)
    earning = models.FloatField(default=0)
    lot_id = models.CharField(max_length=50, blank=True, null=True, help_text="Lot identifier")
    description = models.TextField(blank=True, null=True)
    production_amount = models.FloatField(default=0)

    PRODUCTION_METHOD_CHOICES = [
        ("conventional", "Conventional"),
        ("organic", "Organic"),
        ("regenerative", "Regenerative"),
        ("integrated", "Integrated Pest Management"),
        ("biodynamic", "Biodynamic"),
        ("hydroponic", "Hydroponic"),
        ("no_till", "No-Till"),
    ]
    production_method = models.CharField(
        max_length=30,
        choices=PRODUCTION_METHOD_CHOICES,
        blank=True,
        null=True,
        default="conventional",
        help_text="Farming method used for this production",
    )

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
    # Off-farm post-harvest handler (huller / dryer / cold storage) this lot was
    # sent to. CCOF G6.1 / 7 CFR 205.272 — the handler's organic certificate is
    # surfaced in the audit export's Post-Harvest section. SET_NULL so deleting a
    # facility record never deletes the production.
    post_harvest_facility = models.ForeignKey(
        "certifications.PostHarvestFacility",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="productions",
    )
    cover_image_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        help_text=(
            "Optional hero/cover photo for the public consumer QR page. When set, this image is "
            "shown first (the hero background) and leads the photo gallery, overriding the "
            "auto-picked first timeline photo. Leave blank to auto-pick. Must be a publicly "
            "readable URL (the admin upload widget stores one in the media bucket)."
        ),
    )
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

    # Background event creation status
    EVENTS_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("ready", "Ready"),
        ("failed", "Failed"),
        ("no_events", "No Events"),
    ]
    events_status = models.CharField(
        max_length=20,
        choices=EVENTS_STATUS_CHOICES,
        default="no_events",
        help_text="Status of background template event creation",
    )

    # NOP Compliance: Post-Harvest Sales & Traceability (7 CFR 205.103)
    # These fields are filled AFTER production is finalized (post-finish).
    # NOT part of blockchain hash — hash is computed at finish time, sales happen after.
    sold_to = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Buyer/recipient name (for trace-back audit)",
    )
    sale_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date of sale or delivery",
    )
    quantity_sold = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Quantity sold to buyer",
    )
    quantity_sold_unit = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        blank=True,
        null=True,
        help_text="Unit for quantity sold",
    )
    # Box-to-pound conversion for mass-balance reconciliation (§ 205.103(b)(2)
    # one-step traceability). Optional: when null, the audit export falls back
    # to a crop-specific industry default (CROP_DEFAULT_BOX_WEIGHTS in
    # audit_export_service.py). Standard Hass avocado carton = 25 lb per USDA-
    # AMS Marketing Order 915.
    box_weight_lb = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Weight in pounds of one sales box / carton / lug. Used for mass-"
            "balance reconciliation between boxes shipped and harvest weight."
        ),
    )
    organic_on_invoice = models.BooleanField(
        default=False,
        help_text="Whether organic status is identified on sales documents (SOE requirement)",
    )
    transport_method = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Transportation method (truck, rail, etc.)",
    )
    destination = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Delivery destination/receiving location",
    )
    # NOP Compliance: Clean-transport record for bins moved to an off-farm handler
    # (CCOF G6.1 / 7 CFR 205.272 / 205.307). When organic product travels in a shared
    # truck/container, the operation must document the vehicle and that a clean-transport
    # affidavit is on file. Audit-only; never surfaced to consumers.
    transport_vehicle_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Vehicle / container / trailer identifier for the off-farm transfer",
    )
    transport_affidavit_on_file = models.BooleanField(
        default=False,
        help_text="Whether a clean-transport affidavit is on file for the shared vehicle (CCOF G6.1)",
    )
    transport_affidavit_document = models.FileField(
        upload_to="transport_affidavits/",
        blank=True,
        null=True,
        help_text="Scanned clean-transport affidavit for the off-farm transfer",
    )

    # NOP Compliance: Record Retention (7 CFR 205.103(b)(4))
    # Auto-set to finish_date + 5 years. Prevents deletion within retention period.
    retention_until = models.DateField(
        blank=True,
        null=True,
        help_text="Records retained until this date (auto-set: finish_date + 5 years per NOP)",
    )

    def delete(self, *args, **kwargs):
        """Prevent deletion of productions within NOP 5-year retention period."""
        from django.utils import timezone

        if self.retention_until and self.retention_until > timezone.now().date():
            from django.core.exceptions import ValidationError

            raise ValidationError(
                f"Cannot delete: NOP requires record retention until {self.retention_until}. "
                f"Records must be maintained for 5 years per 7 CFR 205.103(b)(4)."
            )
        super().delete(*args, **kwargs)

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
            prefetch_cache = getattr(self, "_prefetched_objects_cache", {})

            # Map relationship names to their prefetch cache keys
            event_relations = [
                "history_productionevent_events",
                "history_chemicalevent_events",
                "history_weatherevent_events",
                "history_generalevent_events",
                "history_equipmentevent_events",
                "history_soilmanagementevent_events",
                "history_pestmanagementevent_events",
                "history_businessevent_events",
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

        # USDA factors usage (20 points)
        if hasattr(self, "carbon_entries") and self.carbon_entries.filter(usda_factors_based=True).exists():
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

        # Ensure public_id is set before first save
        if not self.public_id:
            self.public_id = uuid.uuid4()

        # Allow callers to skip QR generation for speed (e.g., start_production
        # defers it to a background thread).
        skip_qr = kwargs.pop("skip_qr", False)

        # Save first to get ID if this is a new object
        if is_new:
            super().save(*args, **kwargs)

        if not skip_qr and is_new:
            self.generate_qr_code(is_new=is_new, save_args=args, save_kwargs=kwargs)
        elif not is_new:
            super().save(*args, **kwargs)

    def generate_qr_code(self, is_new=False, save_args=None, save_kwargs=None):
        """Generate branded QR code and save it. Can be called separately for deferred generation."""
        # Clean consumer URL - UUID public_id is unguessable, no HMAC needed
        consumer_url = f"{settings.BASE_CONSUMER_URL}production/{self.public_id}"

        # Generate branded Trazo QR code
        qr_image = self._generate_branded_qr(consumer_url)

        buf = BytesIO()
        qr_image.save(buf, format="PNG")

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
            super().save(*(save_args or ()), **(save_kwargs or {}))

    @staticmethod
    def _generate_branded_qr(data_url):
        """Generate a branded Trazo QR code with leaf logo, green styling, and CTA frame."""
        # Step 1: Generate styled QR with green rounded modules
        # box_size=20 produces ~660px output for high-quality print (300 DPI at 2.2")
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=20,
            border=4,
        )
        qr.add_data(data_url)
        qr.make(fit=True)

        styled_img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=RoundedModuleDrawer(),
            color_mask=SolidFillColorMask(
                back_color=(255, 255, 255),
                front_color=TRAZO_GREEN,
            ),
        )

        qr_img = styled_img.get_image().convert("RGBA")
        qr_width, qr_height = qr_img.size

        # Step 2: Overlay leaf logo in center (if available)
        # 25% of QR width = ~6.25% of total area, safe with ERROR_CORRECT_H (30%)
        if os.path.exists(TRAZO_LEAF_LOGO):
            try:
                logo_src = Image.open(TRAZO_LEAF_LOGO).convert("RGBA")
                logo_target_size = int(qr_width * 0.25)

                logo_resized = logo_src.resize((logo_target_size, logo_target_size), Image.LANCZOS)
                logo_x = (qr_width - logo_target_size) // 2
                logo_y = (qr_height - logo_target_size) // 2
                qr_img.paste(logo_resized, (logo_x, logo_y), logo_resized)
            except Exception as e:
                logger.warning(f"Could not embed logo in QR code: {e}")

        return qr_img.convert("RGB")

    @property
    def certificate_percentage(self):
        # Certificate percentage calculation removed as part of simplification
        return 0

    def finish(self, history_data, images):
        from datetime import datetime

        from django.utils import timezone

        if images:
            gallery = Gallery.objects.create()
            for image_data in images:
                # Pre-uploaded photos arrive as S3 URL strings (store on image_url so the
                # consumer serializer reads them directly); raw file uploads go on the
                # ImageField. Mixed lists are handled per item.
                if isinstance(image_data, str):
                    gallery.images.create(image_url=image_data)
                else:
                    gallery.images.create(image=image_data)
            self.album = gallery
            # The first photo is the cover. Persist it as the explicit hero override
            # (PublicHistorySerializer.get_images surfaces cover_image_url at images[0])
            # so the consumer hero is deterministic instead of relying on array order.
            # Don't clobber a cover an admin set earlier.
            if not self.cover_image_url:
                first_image = gallery.images.first()
                if first_image:
                    self.cover_image_url = first_image.image_url or (
                        first_image.image.url if first_image.image else None
                    )

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
        self.description = history_data.get("observation", "")
        self.published = True
        self.production_amount = history_data["production_amount"]
        self.lot_id = history_data["lot_id"]

        # Harvest details for consumer transparency (Sprint 3)
        self.production_unit = history_data.get("production_unit")
        self.quality_grade = history_data.get("quality_grade")
        self.harvest_method = history_data.get("harvest_method")

        # NOP 7 CFR 205.103(b)(4): 5-year record retention
        from datetime import timedelta

        if self.finish_date:
            finish_dt = self.finish_date
            if hasattr(finish_dt, "date"):
                finish_dt = finish_dt.date()
            self.retention_until = finish_dt + timedelta(days=5 * 365)

        self.save()

    def compute_finalization_hash(self):
        """Compute keccak256 hash of all event data for integrity verification.

        Single source of truth for finalization hashing. Used by:
        - product/views.py _store_finalization_hash() — at finish time
        - history/transparency_views.py — at verification time

        Returns (hash_hex, event_count) tuple.
        """
        import hashlib
        import json

        event_models = [
            WeatherEvent,
            ChemicalEvent,
            ProductionEvent,
            GeneralEvent,
            EquipmentEvent,
            SoilManagementEvent,
            PestManagementEvent,
            BusinessEvent,
        ]

        all_events = []
        for model in event_models:
            qs = model.objects.filter(history=self).values("id", "index", "date", "description")
            for row in qs:
                row["event_type"] = model.__name__
                all_events.append(row)

        all_events.sort(key=lambda e: e["index"])
        event_data = json.dumps(all_events, sort_keys=True, default=str, separators=(",", ":"))

        try:
            from web3 import Web3

            raw_hex = Web3.keccak(text=event_data).hex()
            return raw_hex.removeprefix("0x"), len(all_events)
        except ImportError:
            return hashlib.sha256(event_data.encode()).hexdigest(), len(all_events)

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
        return sorted(events, key=lambda event: (event["date"], event["index"]))


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

    # Phase 2: Agronomy context fields shared across all event types
    variety = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Crop variety (e.g., Nonpareil almonds, Hass avocados)",
    )
    block_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Farm block or section identifier",
    )
    growth_stage = models.CharField(
        max_length=30,
        choices=GROWTH_STAGE,
        blank=True,
        null=True,
        help_text="Crop growth stage at time of event",
    )

    # F21 (2026-06): supervisor review / sign-off. FSMA Produce Safety Rule
    # § 112.161(b) requires review-required records (training, agricultural water,
    # biological soil amendments, equipment/tool cleaning) to be reviewed "within a
    # reasonable time" by a supervisor, with the reviewer's name and the review date.
    # Universal on CommonEvent so any event type can carry a sign-off; the certifier
    # PDF surfaces it. (NOT codified as "7 working days" — that figure is not in the
    # regulation; see research-fsma-sgma.md.)
    reviewed = models.BooleanField(
        default=False,
        help_text="Whether a supervisor has reviewed this record (FSMA PSR § 112.161(b)).",
    )
    reviewer_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Name of the supervisor who reviewed the record (FSMA PSR § 112.161(b)).",
    )
    review_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the record was reviewed/signed off.",
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

    # Plausibility ranges for meteorological magnitudes. These are NOT
    # regulatory thresholds — they're sanity bounds to catch unit-of-measure
    # mistakes (e.g. °C entered in a °F field, kph in an mph field) before the
    # value ships in an inspector-facing PDF. An entry like 140°F on a
    # California farm is instantly implausible (world-record high is ~134°F,
    # Death Valley 1913) and undermines credibility of the rest of the data.
    _PLAUSIBILITY_BOUNDS = {
        # temperature in °F / °C (evaluated against both, narrower of the two)
        "temperature_f": (-40, 135),  # world record high ~134°F
        "temperature_c": (-40, 57),  # world record high ~56.7°C
        # F12 fix (2026-06): the WeatherTab form collects wind in km/h and
        # precipitation in mm (metric), so the stored extra_data values are metric.
        # Bounds were imperial (mph / inches), so a legitimate 150 mm storm or a
        # 300 km/h gust failed the (0,50)/(0,250) checks with a 400. Bounds are now
        # metric to match the form's units.
        "wind_speed_kmh": (0, 410),  # world record gust 253 mph ≈ 407 km/h (Barrow Island)
        "precipitation_mm": (0, 1200),  # single-event max ~43 in ≈ 1092 mm (TC Denise, 1966)
        "humidity_pct": (0, 100),
        "hail_size_in": (0, 8),  # largest verified ~8 in (Vivian, SD 2010)
    }

    def _plausibility_check(self, unit: str, value, low: float, high: float, field: str):
        """Return a ValidationError-style message if the magnitude is outside
        plausible meteorological bounds, else None. Used by clean() and by
        the serializer's pre-save validation so both the admin and the API
        catch unit-of-measure typos."""
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None  # non-numeric handled elsewhere
        if numeric < low or numeric > high:
            return (
                f"{field} {numeric}{unit} is outside the plausible range "
                f"[{low}, {high}]{unit}. Check that the value was entered in "
                "the correct unit — e.g. °C in a °F field will trigger this."
            )
        return None

    def clean(self):
        """
        Validate that numeric meteorological magnitudes are within plausible
        ranges. Catches °C-in-°F and kph-in-mph typos at save-time so they
        never ship in an inspector-facing PDF.
        """
        from django.core.exceptions import ValidationError

        super().clean()
        extra = self.extra_data or {}
        issues = {}

        # Temperature — unit-aware; extra_data.temperature_unit in {"F", "C"}.
        temp_unit = (extra.get("temperature_unit") or "F").upper()
        temp_bounds_key = "temperature_c" if temp_unit == "C" else "temperature_f"
        low, high = self._PLAUSIBILITY_BOUNDS[temp_bounds_key]
        unit_sym = "°C" if temp_unit == "C" else "°F"
        for key in ("highest_temperature", "lowest_temperature", "temperature", "lower_temperature"):
            msg = self._plausibility_check(unit_sym, extra.get(key), low, high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        wind_low, wind_high = self._PLAUSIBILITY_BOUNDS["wind_speed_kmh"]
        msg = self._plausibility_check(" km/h", extra.get("wind_speed"), wind_low, wind_high, "wind_speed")
        if msg:
            issues.setdefault("extra_data", []).append(msg)

        precip_low, precip_high = self._PLAUSIBILITY_BOUNDS["precipitation_mm"]
        for key in ("precipitation", "precipitation_amount"):
            msg = self._plausibility_check(" mm", extra.get(key), precip_low, precip_high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        hum_low, hum_high = self._PLAUSIBILITY_BOUNDS["humidity_pct"]
        # Check both humidity key variants separately — using ``or`` to pick
        # between them treats 0% (a valid low-humidity reading) as falsy
        # and silently swaps it for humidity_level, masking a real value.
        for key in ("humidity", "humidity_level"):
            msg = self._plausibility_check("%", extra.get(key), hum_low, hum_high, key)
            if msg:
                issues.setdefault("extra_data", []).append(msg)

        hail_low, hail_high = self._PLAUSIBILITY_BOUNDS["hail_size_in"]
        msg = self._plausibility_check(" in", extra.get("hail_size"), hail_low, hail_high, "hail_size")
        if msg:
            issues.setdefault("extra_data", []).append(msg)

        if issues:
            raise ValidationError(issues)


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
        ("organic", "Organic/Natural (Neem Oil, Potassium Bicarbonate, etc.)"),
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

    # Sprint 3 Epic 3.2: Consumer Trust Fields
    # Sprint 6 Fix: Expanded choices to match frontend organic certification options
    # These detailed options provide better transparency for consumers about organic certification types
    organic_approved = models.CharField(
        max_length=20,
        choices=ORGANIC_APPROVED,
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
        help_text="Matched National List entry (7 CFR 205.601/602) — auto-suggested",
    )

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
        help_text="Field fumigation method code — required for fumigation method / 1,3-D (DPR box 21 / 3 CCR 6624(c)(8)).",
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
            "Regulatory classification per NOP 7 CFR 205.204. "
            "Non-organic treated seed with prohibited substances disqualifies the crop."
        ),
    )
    seed_treatment = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Seed coatings, inoculants, or pelleting materials applied (NOP 7 CFR 205.204(a)(2))",
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

    # MVP Target Market Fields
    harvest_quality_grade = models.CharField(
        max_length=20,
        choices=HARVEST_QUALITY_GRADE,
        blank=True,
        null=True,
        help_text="Harvest quality grade for premium fruit operations (CA citrus, Uruguay exports)",
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

    # NOP Compliance: Irrigation/Well Water Test (7 CFR 205.272 / 205.671)
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
    cleaning_method = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Cleaning method used (pressure wash, manual scrub, steam, etc.)",
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
        help_text="Potable-water rinse step performed after sanitizer contact (required under § 205.605(b))",
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

        # NOP 5029 / 7 CFR 205.204(a)(1): Non-organic seed requires documented commercial
        # availability search of at least 3 suppliers. Applies to planting events only.
        if self.type == "PL" and self.seed_certification_status in (
            "non_organic_untreated",
            "non_organic_treated",
        ):
            attempts = self.seed_search_attempts or []
            if len(attempts) < 3:
                errors["seed_search_attempts"] = (
                    "NOP 5029 (7 CFR 205.204(a)(1)) requires documentation of at least 3 "
                    "supplier searches when using non-organic seed or planting stock. "
                    f"Current search attempts: {len(attempts)}. Add more suppliers to seed_search_attempts."
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

        if not self.date or not self.history or not self.history.parcel:
            return None

        crop_type = getattr(self.history, "crop_type", None)
        soil_contact = True  # Conservative default (120-day window)
        if crop_type is not None and crop_type.has_soil_contact is not None:
            soil_contact = crop_type.has_soil_contact
        interval_days = 120 if soil_contact else 90

        # SoilManagementEvent is defined later in this module; by the time this method
        # runs the entire module is loaded, so direct reference works without import.
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

    # NOP Compliance: Contamination Incident Reporting (7 CFR 205.201(b))
    CONTAMINATION_SOURCE_CHOICES = [
        ("spray_drift", "Spray Drift from Adjacent Land"),
        ("equipment", "Equipment Contamination"),
        ("storage", "Storage Commingling"),
        ("water", "Water Contamination"),
        ("soil", "Soil Contamination"),
        ("other", "Other"),
    ]
    is_contamination_incident = models.BooleanField(
        default=False,
        help_text="Whether this event documents a contamination incident (7 CFR 205.201(b))",
    )
    contamination_source = models.CharField(
        max_length=30,
        choices=CONTAMINATION_SOURCE_CHOICES,
        blank=True,
        null=True,
        help_text="Source of contamination (spray drift, equipment, storage, etc.)",
    )
    contamination_affected_area = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Area affected by contamination in acres",
    )
    corrective_action_taken = models.TextField(
        blank=True,
        null=True,
        help_text="Corrective actions taken in response to contamination incident",
    )
    corrective_action_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date corrective action was completed",
    )
    certifier_notified = models.BooleanField(
        default=False,
        help_text="Whether the certifying agent was notified of the contamination incident",
    )
    certifier_notification_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date certifier was notified of contamination incident",
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

    # CLAIM TOKEN — opaque token returned to the client so anonymous scans can be
    # linked to an account after sign-in, without exposing sequential IDs (IDOR prevention).
    claim_token = models.CharField(
        max_length=43,
        unique=True,
        db_index=True,
        blank=True,
        help_text="Opaque token for anonymous scan claiming (prevents IDOR)",
    )

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

    def save(self, *args, **kwargs):
        if not self.claim_token:
            import secrets

            self.claim_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

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
        # Skip placeholder/default values
        has_country = self.country_code and self.country_code != "XX"
        has_region = self.region and self.region != "Unknown"

        if has_country and has_region:
            return f"{self.region}, {self.country_code.upper()}"
        elif has_country:
            return self.country_code.upper()
        # Fallback to legacy data if new data not available
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return None


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
        choices=UNIT_FUEL,
        default="gal",
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
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    operation_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
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
    GRAZING = "GR"
    # Biodiversity / habitat (GTM-v3): documented habitat PRACTICES — facts only, never a score.
    HABITAT_DEVELOPMENT = "HD"  # planted/established habitat (hedgerow, insectary, riparian, living floor)
    NESTING_SHELTER = "NS"  # installed wildlife structures (owl/raptor/bee/bat boxes, insect hotel)

    SOIL_TYPE_CHOICES = [
        (SOIL_TEST, "Soil Test"),
        (PH_ADJUSTMENT, "pH Adjustment"),
        (ORGANIC_MATTER, "Organic Matter Addition"),
        (COVER_CROP, "Cover Crop"),
        (TILLAGE, "Tillage"),
        (COMPOSTING, "Composting"),
        (GRAZING, "Grazing Management"),
        (HABITAT_DEVELOPMENT, "Habitat Development"),
        (NESTING_SHELTER, "Nesting / Shelter Structures"),
    ]

    type = models.CharField(max_length=2, choices=SOIL_TYPE_CHOICES, default=SOIL_TEST)
    soil_ph = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    organic_matter_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amendment_type = models.CharField(max_length=100, blank=True)
    amendment_amount = models.CharField(max_length=100, blank=True)
    # Specific product identity for the amendment. amendment_type is only a generic
    # category (compost/manure/gypsum/...); the NOP/CCOF input record (7 CFR 205.203 /
    # CCOF Input Record) needs the actual product + manufacturer.
    amendment_product_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Specific commercial product name of the amendment, e.g. Malibu Compost Bu's Blend.",
    )
    amendment_manufacturer = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Manufacturer / supplier of the amendment product.",
    )
    test_results = models.JSONField(null=True, blank=True)  # Store complex test data
    carbon_sequestration_potential = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    extra_data = models.JSONField(blank=True, null=True)

    # Biodiversity / habitat fields (for HD / NS subtypes). Facts only — free-text species/notes
    # live in extra_data (mirrors cover_crop_species); the living-floor / bugs / birds proof rides
    # on the event photo album + an optional wildlife_observed note. No counts beyond structures, no score.
    habitat_type = models.CharField(
        max_length=40,
        blank=True,
        null=True,
        help_text="Habitat practice (HD) or structure (NS) — e.g. hedgerow, insectary_strip, barn_owl_box",
    )
    habitat_structure_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of structures installed (NS subtype, e.g. 6 barn-owl boxes)",
    )
    habitat_install_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "When the habitat was established (HD) or the structures installed (NS). "
            "Drives the consumer maturity story (an 8-year-old hedgerow vs a new one) and "
            "gives a certifier a date for the practice."
        ),
    )

    # Grazing management fields (for GR subtype)
    animal_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Type of grazing animal (e.g., sheep, goats, cattle)",
    )
    animal_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of animals used for grazing",
    )
    grazing_duration_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration of grazing period in days",
    )
    grazing_purpose = models.CharField(
        max_length=50,
        choices=[
            ("weed_control", "Weed Control"),
            ("cover_crop", "Cover Crop Termination"),
            ("soil_health", "Soil Health"),
            ("vegetation_management", "Vegetation Management"),
        ],
        blank=True,
        null=True,
        help_text="Primary purpose of the grazing activity",
    )

    # Numeric amendment field to replace legacy string field
    amendment_amount_numeric = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Amendment amount in numeric format (replaces legacy string field)",
    )
    amendment_amount_unit = models.CharField(
        max_length=10,
        choices=[
            ("kg", "Kilograms"),
            ("lbs", "Pounds"),
            ("tons", "Tons"),
            ("gal", "Gallons"),
        ],
        default="kg",
        blank=True,
        help_text="Unit for amendment_amount_numeric",
    )

    # Standardized fields for carbon calculations (matching ProductionEvent pattern)
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
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed during soil management activity",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
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

    # NOP Compliance: Amendment Organic Approval (7 CFR 205.203(b))
    amendment_organic_approved = models.CharField(
        max_length=20,
        choices=ORGANIC_APPROVED,
        blank=True,
        null=True,
        help_text="Whether this amendment/input is approved for organic farming (7 CFR 205.203(b))",
    )

    # NOP Compliance: Compost Temperature Tracking (7 CFR 205.203(c)(2))
    # Required for on-farm composting: must reach 131-170°F; windrow 15+ days @temp,
    # static aerated / in-vessel 3+ days @temp.
    compost_peak_temp_f = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Peak temperature reached during composting in °F (must reach 131-170°F per 7 CFR 205.203(c)(2))",
    )
    compost_duration_days_at_temp = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=(
            "Number of days compost maintained required temperature "
            "(windrow: 15+ days; static aerated / in-vessel: 3+ days per 7 CFR 205.203(c)(2))"
        ),
    )
    compost_turning_count = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Number of times compost was turned (minimum 5 turnings for windrow per 7 CFR 205.203(c)(2))",
    )

    # NOP Compliance: Initial C:N ratio + method (7 CFR 205.203(c)(2))
    # Regulatory: a pile with C:N outside 25:1-40:1 at start of composting
    # does NOT satisfy § 205.203(c)(2) and must be treated as raw manure
    # under (c)(1) 90/120-day intervals.
    COMPOST_METHOD_WINDROW = "windrow"
    COMPOST_METHOD_STATIC_AERATED = "static_aerated"
    COMPOST_METHOD_IN_VESSEL = "in_vessel"
    COMPOST_METHOD_CHOICES = [
        (COMPOST_METHOD_WINDROW, "Windrow (turned, open air)"),
        (COMPOST_METHOD_STATIC_AERATED, "Static Aerated Pile"),
        (COMPOST_METHOD_IN_VESSEL, "In-Vessel"),
    ]
    compost_method = models.CharField(
        max_length=20,
        choices=COMPOST_METHOD_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Compost method (7 CFR 205.203(c)(2)). Windrow requires 15+ days at "
            "131–170°F with 5+ turnings; static aerated / in-vessel require 3+ days "
            "at 131–170°F."
        ),
    )
    compost_initial_cn_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text=(
            "Initial carbon-to-nitrogen ratio (C:N) of the compost feedstock. "
            "7 CFR 205.203(c)(2) requires 25:1–40:1 at the start of composting. "
            "Outside this range, the pile must be handled as raw manure under (c)(1)."
        ),
    )
    # F24 (2026-06): complete the NOP 5021 compost record. A single peak temp + day count is not a
    # monitoring log — a certifier needs the feedstock and the actual temperature readings over time.
    compost_feedstock = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text="Feedstock composition/source (e.g., 'horse manure + straw + green waste') — NOP 5021",
    )
    compost_temperature_log = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Temperature-monitoring readings over the composting period (date · temp · turned?) — "
            "the NOP 5021 monitoring log. One reading per line."
        ),
    )

    # NOP Compliance: Raw Manure Harvest Interval (7 CFR 205.203(c)(1))
    # (c)(1) governs raw animal manure pre-harvest intervals; composted materials
    # live under (c)(2). Do not confuse the citations — an inspector flags either.
    MANURE_INTERVAL_CHOICES = [
        ("120", "120 days — edible portion contacts soil (root crops, leafy greens)"),
        ("90", "90 days — edible portion does NOT contact soil (tree fruit, trellised crops)"),
        ("na", "N/A — composted manure or no manure applied"),
    ]
    manure_harvest_interval = models.CharField(
        max_length=5,
        choices=MANURE_INTERVAL_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Required harvest interval after raw manure application: "
            "120 days if crop contacts soil, 90 days otherwise (7 CFR 205.203(c)(1))"
        ),
    )
    manure_application_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date raw manure was applied (used to calculate earliest safe harvest date)",
    )

    # NOP 5006 — Processed Animal Manures in Organic Crop Production.
    # A third manure class sits between raw (c)(1) and composted (c)(2):
    # manure PROCESSED to reduce human pathogens (heat-dried, pelletized,
    # thermophilic PFRP) that does NOT meet the (c)(2) compost definition is
    # still exempt from the (c)(1) 90/120-day raw interval. The exemption is
    # granted only when DOCUMENTED (processing temperature and/or an OMRI/
    # supplier attestation); undocumented "processed" manure is handled as raw.
    MANURE_TREATMENT_CHOICES = [
        ("raw", "Raw / uncomposted animal manure — 90/120-day interval applies (c)(1)"),
        ("composted", "Composted per 7 CFR 205.203(c)(2) — no interval"),
        ("processed_5006", "Processed to reduce pathogens per NOP 5006 — no interval"),
    ]
    manure_treatment = models.CharField(
        max_length=16,
        choices=MANURE_TREATMENT_CHOICES,
        blank=True,
        null=True,
        help_text=(
            "Animal-manure processing class. 'processed_5006' (heat-dried / "
            "pelletized / PFRP) exempts the crop from the raw-manure harvest "
            "interval when supported by a processing temperature or an OMRI / "
            "supplier attestation (NOP 5006)."
        ),
    )
    processed_manure_temp_f = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
        help_text="Peak processing temperature (°F) for NOP 5006 processed manure (pathogen reduction).",
    )
    processed_manure_attestation = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text=(
            "Supplier / OMRI attestation for NOP 5006 processed manure "
            "(e.g., 'OMRI-listed heat-processed poultry pellets, PFRP') — the "
            "documentation basis for the raw-interval exemption."
        ),
    )

    # Sprint 5.1 — Drift detector (same contract as ChemicalEvent.drift_warning).
    # Populated when amendment_type does not resolve to an approved input on
    # the establishment's active OSP.
    drift_warning = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Drift detector payload (7 CFR 205.400(f)(2)). Non-null when this "
            "event's amendment is not in the active OSP's approved_inputs — "
            "treated as an operation change requiring certifier notification."
        ),
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

        # Grazing event validation
        if self.type == self.GRAZING:
            if self.animal_type and not self.animal_count:
                errors["animal_count"] = "Number of animals is required when animal type is specified"
            if self.animal_count and self.animal_count > 10000:
                errors["animal_count"] = f"Animal count ({self.animal_count}) seems unusually high. Please verify."
            if self.grazing_duration_days and self.grazing_duration_days > 365:
                errors["grazing_duration_days"] = (
                    f"Grazing duration ({self.grazing_duration_days} days) exceeds one year. Please verify."
                )

        # Transportation efficiency check
        if self.transportation_distance and self.transportation_distance > 500:
            errors["transportation_distance"] = (
                f"Transportation distance ({self.transportation_distance} {self.transportation_unit}) is very long. Consider local processing to reduce carbon footprint."
            )

        # NOP Manure validation (7 CFR 205.203(c)(1))
        # The 90/120-day interval only applies to RAW manure. Composted (c)(2)
        # and processed (NOP 5006) manure are interval-exempt, so don't force
        # an interval selection for them.
        if (
            self.manure_application_date
            and not self.manure_harvest_interval
            and self.manure_treatment not in ("composted", "processed_5006")
        ):
            errors["manure_harvest_interval"] = (
                "Harvest interval (90 or 120 days) is required when a raw manure application date is specified."
            )

        # NOP Manure interval vs crop soil-contact classification.
        # Per 7 CFR 205.203(c)(1):
        #   (c)(1)(ii) — 120 days required when edible portion has direct
        #                soil contact (root crops, leafy greens).
        #   (c)(1)(iii) — 90 days required when edible portion does NOT
        #                 have direct soil contact (tree fruit, nuts,
        #                 elevated vine fruits).
        # A farmer selecting "120" for a canopy crop is factually wrong
        # even when the resulting harvest date would satisfy the stricter
        # rule: the choice wording includes "edible portion contacts
        # soil" which is false for avocados / apples / etc., and a CCOF
        # inspector reads that as a record-keeping failure under
        # § 205.103. Block the mismatch at save time so the log cannot
        # contain the wrong classification. We only BLOCK when the crop
        # has an authoritative ``has_soil_contact`` flag set — when the
        # crop type is unknown or the flag is None, we defer to the
        # PDF-side consistency linter rather than guessing.
        if self.manure_harvest_interval in ("90", "120"):
            crop_type = None
            try:
                crop_type = self.history.crop_type
            except Exception:  # noqa: BLE001 — FK not populated yet during form clean()
                crop_type = None
            if crop_type is not None and getattr(crop_type, "has_soil_contact", None) is not None:
                has_contact = bool(crop_type.has_soil_contact)
                selected = self.manure_harvest_interval
                if has_contact and selected == "90":
                    errors["manure_harvest_interval"] = (
                        f"Crop '{crop_type.name}' has direct soil contact for its "
                        "edible portion, so 7 CFR 205.203(c)(1)(ii) requires a "
                        "120-day pre-harvest interval. Selecting 90 days is a "
                        "record-keeping mismatch even if the harvest date would "
                        "satisfy the stricter rule."
                    )
                elif not has_contact and selected == "120":
                    errors["manure_harvest_interval"] = (
                        f"Crop '{crop_type.name}' does NOT have direct soil "
                        "contact for its edible portion (tree / canopy crop), "
                        "so 7 CFR 205.203(c)(1)(iii) applies — the required "
                        "interval is 90 days. The '120 days — edible portion "
                        "contacts soil' choice is for root crops and leafy "
                        "greens; using it here mis-classifies the crop and "
                        "creates an inspector-visible record-keeping conflict."
                    )

        # NOP Composting validation (7 CFR 205.203(c)(1)+(c)(2))
        if self.type == self.COMPOSTING:
            if self.compost_peak_temp_f is not None:
                temp = float(self.compost_peak_temp_f)
                if temp < 90 or temp > 200:
                    errors["compost_peak_temp_f"] = (
                        f"Temperature ({temp}°F) seems outside reasonable range (90-200°F). Please verify."
                    )
            if self.compost_duration_days_at_temp is not None and self.compost_duration_days_at_temp > 365:
                errors["compost_duration_days_at_temp"] = "Duration at temperature exceeds one year. Please verify."
            if self.compost_turning_count is not None and self.compost_turning_count > 100:
                errors["compost_turning_count"] = "Turning count seems unusually high. Please verify."
            # § 205.203(c)(2) initial C:N must fall in 25:1–40:1 at start of composting.
            if self.compost_initial_cn_ratio is not None:
                ratio = float(self.compost_initial_cn_ratio)
                if ratio < 5 or ratio > 100:
                    errors["compost_initial_cn_ratio"] = (
                        f"Initial C:N ratio ({ratio}:1) is outside plausible feedstock range (5:1–100:1). "
                        "Please verify — typical NOP-compliant composts start at 25:1–40:1."
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
    # F44 (2026-06): quantitative UC-IPM monitoring count — the actual data behind a scouting/trap
    # decision (e.g. "5 mites/leaf", "12% fruit infested", "8 moths/trap"). pest_pressure_level is
    # the qualitative summary; this is the measured number a certifier/PCA expects.
    monitoring_count = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Measured monitoring count (e.g. 5 mites per leaf) — SC/TM/PI",
    )
    monitoring_unit = models.CharField(
        max_length=20,
        choices=[
            ("per_leaf", "per leaf"),
            ("per_trap", "per trap"),
            ("per_tree", "per tree"),
            ("per_100_fruit", "per 100 fruit"),
            ("percent_infested", "% infested"),
            ("per_sample", "per sample"),
        ],
        blank=True,
        null=True,
        help_text="Unit for monitoring_count (UC IPM monitoring form vocabulary)",
    )
    beneficial_species = models.CharField(max_length=200, blank=True)
    release_quantity = models.CharField(max_length=100, blank=True)
    trap_count = models.IntegerField(null=True, blank=True)
    damage_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    # F17 fix (2026-06): nullable so "not assessed" (None) is distinct from "below threshold" (False).
    # An unanswered NOP 205.206(e) threshold question must NOT be fabricated into a definitive
    # "below threshold" record on the audit export.
    action_threshold_met = models.BooleanField(null=True, blank=True, default=None)
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

    # Beneficial-release traceability (BR subtype) — NOP 7 CFR 205.206 requires the SOURCE of any
    # introduced biological control to be documented; reusing beneficial_species/release_quantity
    # above, these add supplier + lot + organic status so a certifier can trace the release.
    beneficial_supplier = models.CharField(
        max_length=200, blank=True, null=True, help_text="Insectary/supplier the beneficials came from (BR)"
    )
    beneficial_lot_number = models.CharField(
        max_length=100, blank=True, null=True, help_text="Supplier lot / batch number for the release (BR)"
    )
    beneficial_organic_approved = models.CharField(
        max_length=10,
        choices=[("yes", "Yes"), ("no", "No"), ("unknown", "Unknown")],
        blank=True,
        null=True,
        help_text="Whether the beneficial organism is approved for organic systems (BR)",
    )

    # Trap monitoring (TM subtype) — trap_count above is the NUMBER OF TRAPS; these capture the
    # trap kind and the actual catch so an auditor sees real IPM pressure data.
    trap_type = models.CharField(
        max_length=20,
        choices=[
            ("sticky", "Sticky card"),
            ("pheromone", "Pheromone lure"),
            ("delta", "Delta trap"),
            ("bucket_funnel", "Bucket / funnel"),
            ("other", "Other"),
        ],
        blank=True,
        null=True,
        help_text="Kind of trap deployed (TM)",
    )
    pest_catch_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="Insects caught across the traps this monitoring (TM) — not the # of traps"
    )

    chemical_free_period_days = models.PositiveIntegerField(
        blank=True, null=True, help_text="Days since last synthetic chemical application"
    )

    # Sprint 3 Epic 3.1: Fuel/Equipment fields for carbon calculations (matching SoilManagementEvent)
    area_covered = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Area covered during pest management activity",
    )
    area_unit = models.CharField(
        max_length=10,
        choices=UNIT_AREA,
        default="acres",
        blank=True,
        help_text="Area unit",
    )
    fuel_consumed = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Fuel consumed during pest management activity",
    )
    fuel_unit = models.CharField(
        max_length=10,
        choices=UNIT_FUEL,
        default="gal",
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
    production_efficiency = models.CharField(
        max_length=10,
        choices=PRODUCTION_EFFICIENCY,
        default="normal",
        blank=True,
        help_text="Equipment efficiency level for carbon calculations",
    )

    # NOP Compliance: Pest Identification Verification (7 CFR 205.206)
    IDENTIFIED_BY_CHOICES = [
        ("farmer", "Farmer / Farm Staff"),
        ("agronomist", "Licensed Agronomist"),
        ("entomologist", "Entomologist"),
        ("extension_service", "Extension Service Agent"),
        ("crop_consultant", "Crop Consultant"),
        ("lab", "Laboratory Analysis"),
    ]
    identified_by = models.CharField(
        max_length=30,
        choices=IDENTIFIED_BY_CHOICES,
        blank=True,
        null=True,
        help_text="Who identified the pest species (7 CFR 205.206 - pest management practice standard)",
    )
    identification_method = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Method used for pest identification (e.g., field guide, lab analysis, visual inspection)",
    )

    # NOP Compliance: Action Threshold Rationale (7 CFR 205.206(e))
    threshold_rationale = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "Justification for why action threshold was/wasn't met "
            "(e.g., '5 trap catches/week per UC Davis IPM guidelines'). "
            "Required per 7 CFR 205.206(e) before applying any pest control material."
        ),
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
        ("food_safety", "SQF / Food Safety Certified"),
        ("kosher", "Kosher Certified"),
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

    # MVP Target Market Fields - Export operations need certificate references
    certificate_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Certificate reference number (GlobalG.A.P., phytosanitary, USDA Organic)",
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


class BuyerDocRequest(models.Model):
    """
    Phase 4 — buyer documentation request from the consumer proof view.

    A retail/wholesale buyer scanning a product can request supplier
    documentation (certificates, audit packet) without calling anyone. Each
    request becomes a lead on the farmer's dashboard plus an in-app
    notification. Public endpoint is rate-limited and deduplicated (same
    email + production within 24h is idempotent).
    """

    STATUS_CHOICES = [
        ("new", "New"),
        ("contacted", "Contacted"),
        ("closed", "Closed"),
    ]

    production = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        related_name="buyer_doc_requests",
    )
    requester_name = models.CharField(max_length=120)
    requester_email = models.EmailField()
    organization = models.CharField(max_length=160, blank=True, default="")
    message = models.TextField(blank=True, default="", max_length=1000)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new", db_index=True)
    # SHA-256 like HistoryScan.ip_hash — rate limiting without storing raw IPs.
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Buyer Documentation Request"
        verbose_name_plural = "Buyer Documentation Requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["production", "-created_at"], name="buyerdocreq_prod_date_idx"),
            models.Index(fields=["requester_email", "created_at"], name="buyerdocreq_email_date_idx"),
        ]

    def __str__(self):
        return f"{self.requester_email} -> {self.production_id} ({self.status})"


class SalesRecord(models.Model):
    """
    Lightweight sales record per production lot — the SOE traceback unit.

    Inspectors verify "crop and quantity sold, date of sale, buyer" at every
    annual inspection, and mass-balance audits are mandatory under the
    Strengthening Organic Enforcement rule. The legacy single History.sold_to
    field can't represent multiple sales from one lot; these records feed the
    audit PDF's Traceability + Mass-Balance sections.

    NOT consumer-facing — buyer identity and quantities are commercially
    sensitive (same policy as ChemicalEvent supplier fields).
    """

    production = models.ForeignKey(
        History,
        on_delete=models.CASCADE,
        related_name="sales_records",
    )
    sale_date = models.DateField()
    buyer_name = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    quantity_unit = models.CharField(max_length=20, default="kg")
    invoice_number = models.CharField(max_length=80, blank=True, default="")
    # § 205.307 — sales documents for organic product must identify it as organic.
    organic_on_invoice = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sales Record"
        verbose_name_plural = "Sales Records"
        ordering = ["-sale_date", "-created_at"]
        indexes = [
            models.Index(fields=["production", "-sale_date"], name="salesrecord_prod_date_idx"),
        ]

    def __str__(self):
        return f"{self.sale_date} {self.buyer_name} {self.quantity} {self.quantity_unit}"


class LabelImage(models.Model):
    """
    A container-label artifact (retail / nonretail / unpackaged) for a production,
    surfaced in the audit export's Container Labeling block (CCOF G7.0 / NOPB34 /
    7 CFR 205.307). Reuses common.GalleryImage for the actual image (S3 +
    thumbnails + external-URL support); this model only adds labeling metadata.
    """

    LABEL_TYPE_CHOICES = [
        ("nonretail", "Nonretail container (shipping/storage)"),
        ("retail", "Retail package"),
        ("unpackaged", "Unpackaged / PLU tag"),
    ]
    CONTAINER_TYPE_CHOICES = [
        ("box", "Box"),
        ("bin", "Bin"),
        ("tote", "Tote"),
        ("bag", "Bag"),
        ("tag", "Tag / PLU"),
    ]

    history = models.ForeignKey("history.History", on_delete=models.CASCADE, related_name="label_images")
    label_type = models.CharField(max_length=20, choices=LABEL_TYPE_CHOICES, default="nonretail")
    container_type = models.CharField(max_length=20, choices=CONTAINER_TYPE_CHOICES, blank=True, null=True)
    gallery_image = models.ForeignKey(
        "common.GalleryImage",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="label_uses",
        help_text="The actual label image (reuses Gallery S3 + thumbnail infra).",
    )
    lot_link_note = models.TextField(
        blank=True,
        null=True,
        help_text="How this label links the container to the lot / traceback ID (SOE 205.307).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["label_type", "created_at"]

    def __str__(self):
        return f"{self.get_label_type_display()} label for production {self.history_id}"
