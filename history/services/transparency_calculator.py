"""
Trazo Transparency Calculator Service
Calculates farm record completeness to encourage honest logging
Eliminates competitive carbon ranking - the root cause of farmer gaming behavior

Following Trazo's main goal: Authentic transparency over competitive metrics
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple

from django.db.models import prefetch_related_objects
from django.utils import timezone

from carbon.models import CropType

from ..models import (
    BusinessEvent,
    ChemicalEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)

# Establishment / Parcel imports dropped 2026-08-02 — their only uses were the type hints of
# the deleted calculate_establishment_transparency() cluster.


logger = logging.getLogger(__name__)


class TransparencyCalculator:
    """
    Calculate transparency percentage based on expected vs actual event logging

    Core principle: Reward complete documentation, eliminate competitive rankings
    This solves the farmer incentive problem by celebrating honesty over gaming
    """

    # Expected event counts by crop category and farming approach
    EXPECTED_EVENTS = {
        "tree_fruit": {"conventional": 12, "organic": 15, "biodynamic": 18},
        "tree_nut": {"conventional": 10, "organic": 13, "biodynamic": 16},
        "grain": {"conventional": 8, "organic": 11, "biodynamic": 14},
        "vegetable": {"conventional": 15, "organic": 18, "biodynamic": 22},
        "herb": {"conventional": 10, "organic": 13, "biodynamic": 16},
        "legume": {"conventional": 8, "organic": 11, "biodynamic": 14},
        "oilseed": {"conventional": 9, "organic": 12, "biodynamic": 15},
        "other": {"conventional": 10, "organic": 12, "biodynamic": 15},
    }

    # Event categories for balanced documentation assessment
    EVENT_CATEGORIES = {
        "production": [ProductionEvent],
        "chemical": [ChemicalEvent],
        "soil": [SoilManagementEvent],
        "pest": [PestManagementEvent],
        "weather": [WeatherEvent],
        "business": [BusinessEvent],
        "general": [GeneralEvent],
    }

    # ------------------------------------------------------------------------------------------
    # Event access — ALWAYS through the reverse accessors, never `Model.objects.filter(history=)`.
    #
    # Until 2026-09-05 every count and loop in this class went back to the database, so the
    # prefetch its callers already paid for was ignored: 16 COUNTs + one SELECT per event model
    # per history, then 2-3 queries per event for the photo check. Multiplied by every history
    # on a farm that is 282 queries for `dashboard_metrics`, 345 for `transparency/` and 369 for
    # `productions-flat` — ~3 s each in production, where every query crosses to the managed DB.
    # ------------------------------------------------------------------------------------------
    @staticmethod
    def _events_accessor(event_model) -> str:
        """Reverse accessor History exposes for one event model (`history_<model>_events`)."""
        return f"history_{event_model.__name__.lower()}_events"

    @classmethod
    def event_prefetch_lookups(cls) -> Tuple[str, ...]:
        """Prefetch lookups that make a calculation query-free. Idempotent with any caller that
        already did them (`prefetch_related_objects` skips fetched levels)."""
        return tuple(
            f"{cls._events_accessor(model)}__album__images"
            for models in cls.EVENT_CATEGORIES.values()
            for model in models
        )

    def _ensure_prefetched(self, history: History) -> None:
        """One bounded round of prefetching so the per-history loops below never hit the DB.

        A caller that prefetched already pays nothing; one that did not pays ~3 queries per
        event model ONCE, instead of 2 per model plus 2-3 per event.
        """
        prefetch_related_objects([history], *self.event_prefetch_lookups())

    def _events_of(self, history: History, event_model) -> list:
        """All events of one model for this history, from the prefetch cache."""
        return list(getattr(history, self._events_accessor(event_model)).all())

    # 3-Tier photo system — subtype-level photo requirements
    # Tier 1 ESSENTIAL: Full 50% penalty without photos
    #   High consumer interest, prevents gaming, irreplaceable verification
    PHOTO_TIER_ESSENTIAL = {
        "PL",
        "HA",  # Planting, Harvesting
        "FE",
        "PE",
        "FU",
        "HE",  # All chemical subtypes
        "CC",  # Cover Crop
        "BR",
        "PI",  # Beneficial Release, Pest Identification
    }

    # Tier 2 RECOMMENDED: Lighter 25% penalty without photos
    #   Photos add value but absence is understandable
    PHOTO_TIER_RECOMMENDED = {
        "PR",
        "TR",
        "CU",  # Pruning, Transplanting, Cultivation
        "ST",
        "OM",
        "CO",
        "GR",  # Soil Test, Organic Matter, Composting, Grazing
        "SC",
        "TM",
        "IP",  # Scouting, Trap Monitoring, IPM
        "LA",  # §E-2 Lab Analysis — the typed results are the record, a photo of the report
        #        corroborates it. Same weight as ST (Soil Test) above.
        # NOTE on "CU" above: these sets are keyed by the raw subtype CODE across every event
        # model, so "CU" now covers BOTH production Cultivation and the §E-4 pest Cultural /
        # Sanitation Control. Both are visible field work where a photo helps but the operation
        # is documented without one, so the shared tier is correct rather than merely tolerable.
    }

    # Tier 3 (implicit — everything else): No photo penalty
    #   IR, EM, TH = Production; PA, TI = Soil; TA = Pest
    #   All weather, business, general events

    # Anti-gaming: productions with fewer than this many total events are capped
    # at MINIMUM_EVENTS_SCORE regardless of category weights. This prevents a
    # farm from logging nothing (or a single token event) and receiving a high
    # transparency score due to organic-bypass or weight redistribution.
    MINIMUM_EVENTS_THRESHOLD = 3
    MINIMUM_EVENTS_SCORE_CAP = 30  # Maximum score when below threshold

    def calculate_transparency_score(self, history: History) -> Dict:
        """
        Calculate comprehensive transparency score for a production history.

        Anti-gaming rules applied (2026-03-21):
        - Zero total events always yields 0% (not 100% via organic bypass).
        - Fewer than MINIMUM_EVENTS_THRESHOLD events caps the score at
          MINIMUM_EVENTS_SCORE_CAP regardless of category weighting. A farm
          that has logged almost nothing should not appear transparent.

        Returns:
            Dict with transparency percentage, message, and category breakdown
        """
        try:
            # Get expected event count based on crop type and farming approach
            self._ensure_prefetched(history)
            expected_count = self._get_expected_event_count(history)

            # Count actual events across all categories
            actual_count = self._count_all_events(history)

            # Anti-gaming guard: zero events = zero transparency, full stop.
            # Without this, the organic-bypass path in _calculate_completeness_score
            # could award 100% chemical credit (and thus a non-zero weighted score)
            # to a production that has never had a single event logged.
            if actual_count == 0:
                return {
                    "transparency_percentage": 0,
                    "message": "No farming activities documented yet",
                    "completeness_score": 0,
                    "event_coverage_percentage": 0,
                    "category_breakdown": {},
                    "consumer_friendly_categories": [],
                    "actual_event_count": 0,
                    "expected_event_count": expected_count,
                    "farming_approach": self._get_farming_approach(history),
                    "calculation_timestamp": timezone.now().isoformat(),
                    "consumer_summary": "No farming activities have been documented for this production.",
                }

            # Calculate base transparency percentage
            if expected_count == 0:
                transparency_percentage = 100  # No events expected = perfect transparency
            else:
                transparency_percentage = min((actual_count / expected_count) * 100, 100)

            # Get category breakdown for detailed feedback
            category_breakdown = self._analyze_category_completeness(history, expected_count)

            # Calculate completeness score (weighted by category, includes photo penalty)
            # Pass history for Item #17 organic farm detection
            completeness_score = self._calculate_completeness_score(category_breakdown, history=history)

            # Anti-gaming cap: fewer than MINIMUM_EVENTS_THRESHOLD events cannot score
            # higher than MINIMUM_EVENTS_SCORE_CAP. This prevents a single logged event
            # from triggering the organic-bypass and inflating the score dramatically.
            if actual_count < self.MINIMUM_EVENTS_THRESHOLD:
                completeness_score = min(completeness_score, self.MINIMUM_EVENTS_SCORE_CAP)

            # The main transparency_percentage should reflect the weighted completeness
            # score (which includes photo penalties), not just raw event count ratio.
            # Raw ratio is kept as event_coverage_percentage for reference.
            effective_score = round(completeness_score, 1)

            # Generate consumer-friendly message using the effective score
            message = self._generate_transparency_message(effective_score, category_breakdown)

            return {
                "transparency_percentage": effective_score,
                "message": message,
                "completeness_score": completeness_score,
                "event_coverage_percentage": round(transparency_percentage, 1),
                "category_breakdown": category_breakdown,
                "consumer_friendly_categories": self._get_consumer_friendly_categories(category_breakdown),
                "actual_event_count": actual_count,
                "expected_event_count": expected_count,
                "farming_approach": self._get_farming_approach(history),
                "calculation_timestamp": timezone.now().isoformat(),
                "consumer_summary": self._generate_consumer_summary(effective_score, actual_count, expected_count),
            }

        except Exception as e:
            logger.error(f"Transparency calculation error for history {history.id}: {str(e)}")
            return {
                "transparency_percentage": 0,
                "message": "Unable to calculate transparency - please contact support",
                "error": str(e),
            }

    def _get_expected_event_count(self, history: History) -> int:
        """Determine expected event count based on crop type and farming approach"""

        # Crop type lives on the History (per-production), NOT on the Parcel.
        #
        # This read was `history.parcel.crop_type.category`, but Parcel.crop_type was removed
        # (see product/models.py: "crop_type removed - now stored in History model for
        # per-production tracking"). `hasattr` on the missing attribute returned False, so the
        # branch never ran and EVERY production silently fell back to the "other" row — making
        # the whole crop-specific EXPECTED_EVENTS table unreachable. A walnut block scored
        # against the generic baseline (organic 12) instead of tree_nut (organic 13).
        crop_category = "other"  # Fallback when a production has no crop type set
        crop_type = getattr(history, "crop_type", None)
        if crop_type is not None and getattr(crop_type, "category", None):
            crop_category = crop_type.category

        # Use single source of truth for farming approach detection
        farming_approach = self._get_farming_approach(history)

        expected_count = self.EXPECTED_EVENTS.get(crop_category, {}).get(farming_approach, 10)

        # Adjust based on production duration (only if dates are valid)
        if history.start_date and history.finish_date:
            duration_days = (history.finish_date - history.start_date).days
            if duration_days > 0:  # Guard against invalid dates (finish before start)
                duration_months = duration_days / 30
                if duration_months > 12:
                    expected_count = int(expected_count * 1.2)  # Longer productions need more events
                elif duration_months < 6:
                    expected_count = int(expected_count * 0.8)  # Shorter productions need fewer events

        return max(expected_count, 5)  # Minimum 5 events expected

    def _count_all_events(self, history: History) -> int:
        """Count all events across all categories for this production history"""

        total_events = 0

        # Count each event type
        for event_models in self.EVENT_CATEGORIES.values():
            for event_model in event_models:
                total_events += len(self._events_of(history, event_model))

        return total_events

    def _analyze_category_completeness(self, history: History, expected_total: int) -> Dict:
        """Analyze completeness by event category with 3-tier photo verification (anti-gaming)"""

        category_breakdown = {}
        events_per_category = expected_total / len(self.EVENT_CATEGORIES)  # Distribute evenly

        # Categories that contain tier 1/2 subtypes and thus can incur photo penalties
        photo_required_categories = {"production", "chemical", "soil", "pest"}

        for category_name, event_models in self.EVENT_CATEGORIES.items():
            actual_count = 0
            photo_verified_count = 0

            # Per-tier counters
            tier1_total = 0
            tier1_verified = 0
            tier2_total = 0
            tier2_verified = 0

            # Count actual events and photo-verified events for this category
            for event_model in event_models:
                category_events = self._events_of(history, event_model)
                actual_count += len(category_events)

                for event in category_events:
                    event_type = getattr(event, "type", "")
                    is_verified = self._has_photo_verification(event)

                    if is_verified:
                        photo_verified_count += 1

                    # Classify into tier
                    if event_type in self.PHOTO_TIER_ESSENTIAL:
                        tier1_total += 1
                        if is_verified:
                            tier1_verified += 1
                    elif event_type in self.PHOTO_TIER_RECOMMENDED:
                        tier2_total += 1
                        if is_verified:
                            tier2_verified += 1
                    # Tier 3 (implicit): no tracking needed

            expected_for_category = max(int(events_per_category), 1)
            base_completeness = min((actual_count / expected_for_category) * 100, 100)

            # Calculate blended photo multiplier using tier system
            if actual_count > 0 and (tier1_total > 0 or tier2_total > 0):
                # Tier 1: 50% penalty range (multiplier 0.5–1.0)
                tier1_rate = tier1_verified / tier1_total if tier1_total > 0 else 1.0
                tier1_mult = 0.5 + 0.5 * tier1_rate

                # Tier 2: 25% penalty range (multiplier 0.75–1.0)
                tier2_rate = tier2_verified / tier2_total if tier2_total > 0 else 1.0
                tier2_mult = 0.75 + 0.25 * tier2_rate

                # Blend by event count
                total_tiered = tier1_total + tier2_total
                blended_mult = (tier1_mult * tier1_total + tier2_mult * tier2_total) / total_tiered

                completeness = base_completeness * blended_mult
                photo_verification_rate = photo_verified_count / actual_count
            else:
                # No tier 1/2 events in category — no photo penalty
                completeness = base_completeness
                photo_verification_rate = 1.0

            category_breakdown[category_name] = {
                "actual_count": actual_count,
                "photo_verified_count": photo_verified_count,
                "photo_verification_rate": round(photo_verification_rate * 100, 1),
                "expected_count": expected_for_category,
                # Event coverage BEFORE the photo multiplier (added 2026-08-04).
                #
                # `completeness_percentage` below is this value multiplied by the photo penalty, and
                # the producer UI was presenting that product as "documented". A grower with 20
                # complete spray records and no photos saw 50% and an orange bar — while NOP 205.103
                # asks for auditable records, not photographs. Photos serve the CONSUMER page; they
                # are not a certifier requirement, so the two readings have to be separable.
                #
                # The penalty itself is unchanged and still drives the score: it is deliberate
                # anti-gaming, and photo evidence is what makes the QR page worth scanning. Only the
                # ability to say "records: 20 logged / photos: 0 of 20" separately is new.
                #
                # NB this is coverage against `expected_count`, which is `expected_total / 7` split
                # evenly across categories — it means "did you log about as many events as expected
                # for this crop", NOT "are the fields on these events complete for a certifier".
                # That question is answered by `AuditExportService.compliance_snapshot_rows()`,
                # which cites the actual CFR sections. Do not relabel this as certifier-readiness.
                "records_completeness_percentage": round(base_completeness, 1),
                "completeness_percentage": round(completeness, 1),
                "status": self._get_category_status(completeness),
                "requires_photos": category_name in photo_required_categories,
                "anti_gaming_applied": (tier1_total + tier2_total) > 0 and photo_verification_rate < 1.0,
                "photo_tier_summary": {
                    "essential": {"total": tier1_total, "verified": tier1_verified},
                    "recommended": {"total": tier2_total, "verified": tier2_verified},
                },
            }

        return category_breakdown

    def _has_photo_verification(self, event) -> bool:
        """
        ADVANCED Anti-Gaming Photo Verification System
        Prevents farmers from gaming transparency scores with fake/dummy photos

        Multi-layer verification:
        1. File existence and size validation
        2. Image format and metadata verification
        3. Content analysis for blank/dummy detection
        4. Timestamp correlation with event dates
        """
        try:
            # Event must have an album
            if not hasattr(event, "album") or not event.album:
                return False

            # Album must have actual images (prefetched with the events — one list, no queries)
            images_manager = getattr(event.album, "images", None)
            images = list(images_manager.all()) if images_manager is not None else []
            if not images:
                return False

            # Additional anti-gaming checks
            image_count = len(images)

            # Require 2+ images only for chemical subtypes (label + application evidence)
            min_images_required = (
                2 if hasattr(event, "type") and getattr(event, "type", "") in ["FE", "PE", "FU", "HE"] else 1
            )

            if image_count < min_images_required:
                return False

            verified_images = 0

            # Advanced verification for each image
            for image in images:
                if hasattr(image, "image") and image.image:
                    try:
                        # LAYER 1: File size validation (anti-placeholder)
                        if image.image.size < 10240:  # 10KB minimum
                            continue

                        # LAYER 2: Maximum reasonable size (anti-huge-fake-files)
                        if image.image.size > 50 * 1024 * 1024:  # 50MB maximum
                            continue

                        # LAYER 3: File format validation
                        if not self._is_valid_image_format(image.image):
                            continue

                        # LAYER 4: Anti-blank/dummy image detection
                        if not self._is_legitimate_photo_content(image.image):
                            continue

                        # LAYER 5: Timestamp correlation (events and photos should be close in time)
                        if not self._verify_photo_timestamp_correlation(image, event):
                            continue

                        # Photo passed all anti-gaming checks
                        verified_images += 1

                    except (OSError, AttributeError, Exception):
                        # File access error or any verification failure, skip this image
                        continue

                elif getattr(image, "s3_key", None) or getattr(image, "image_url", None):
                    # URL-based images (S3 uploads or external URLs)
                    # Basic validation: URL/key must be non-empty string.
                    url_or_key = image.s3_key or image.image_url or ""
                    if len(url_or_key.strip()) <= 10:
                        continue

                    # LAYER 6: Vision API content validation (anti-AI/stock photo)
                    # Photos flagged as not_agricultural, ai_generated, or stock_photo
                    # don't count toward transparency score
                    if hasattr(image, "extra_data") and image.extra_data and isinstance(image.extra_data, dict):
                        content_flag = image.extra_data.get("content_validation", "")
                        if content_flag in ("not_agricultural", "ai_generated", "stock_photo"):
                            continue

                    verified_images += 1

            # Must have at least the minimum required verified images
            return verified_images >= min_images_required

        except Exception:
            # Any error in verification = no verification
            return False

    def _is_valid_image_format(self, image_file) -> bool:
        """Verify image has valid format and is not corrupted"""
        try:
            # Check file extension
            valid_extensions = [".jpg", ".jpeg", ".png", ".webp", ".tiff"]
            file_name = getattr(image_file, "name", "").lower()

            if not any(file_name.endswith(ext) for ext in valid_extensions):
                return False

            # Try to read image headers (basic format validation)
            try:
                from io import BytesIO

                from PIL import Image

                # Read first few bytes to verify it's actually an image
                image_file.seek(0)
                header = image_file.read(1024)
                image_file.seek(0)

                # Check for valid image magic numbers
                image_signatures = [
                    b"\xff\xd8\xff",  # JPEG
                    b"\x89PNG\r\n\x1a\n",  # PNG
                    b"RIFF",  # WEBP (starts with RIFF)
                    b"II*\x00",  # TIFF little endian
                    b"MM\x00*",  # TIFF big endian
                ]

                if not any(header.startswith(sig) for sig in image_signatures):
                    return False

                return True

            except ImportError:
                # PIL not available, use basic checks
                return True

        except Exception:
            return False

    def _is_legitimate_photo_content(self, image_file) -> bool:
        """
        Advanced content analysis to detect blank, dummy, or generated images
        Prevents gaming with solid color images, text screenshots, etc.
        """
        try:
            import hashlib
            from io import BytesIO

            from PIL import Image, ImageStat

            # Reset file pointer
            image_file.seek(0)
            image_data = image_file.read()
            image_file.seek(0)

            # Check for known dummy/placeholder image hashes
            image_hash = hashlib.md5(image_data).hexdigest()
            known_dummy_hashes = {
                # Common placeholder images (update this list as needed)
                "d41d8cd98f00b204e9800998ecf8427e",  # Empty file
                "5d41402abc4b2a76b9719d911017c592",  # Simple text "hello"
                # Add more known dummy image hashes
            }

            if image_hash in known_dummy_hashes:
                return False

            try:
                # Open and analyze image
                img = Image.open(BytesIO(image_data))

                # Check minimum dimensions (too small = likely not a real photo)
                width, height = img.size
                if width < 100 or height < 100:
                    return False

                # Check if image is too uniform (solid color or very simple)
                if img.mode in ["RGB", "RGBA"]:
                    # Calculate color variance
                    stat = ImageStat.Stat(img)
                    variance = sum(stat.var) / len(stat.var)

                    # Very low variance indicates solid color or very simple image
                    if variance < 100:  # Adjust threshold as needed
                        return False

                # Check aspect ratio (extremely wide/tall images are suspicious)
                aspect_ratio = max(width, height) / min(width, height)
                if aspect_ratio > 10:  # More than 10:1 ratio is suspicious
                    return False

                return True

            except Exception:
                # If we can't analyze the image with PIL, assume it's legitimate
                # (better to allow some edge cases than block real photos)
                return True

        except ImportError:
            # PIL not available, use basic file size heuristics
            try:
                image_file.seek(0)
                data = image_file.read()
                image_file.seek(0)

                # Check for very repetitive data (characteristic of solid color images)
                if len(set(data[:1000])) < 10:  # Less than 10 unique bytes in first 1KB
                    return False

                return True

            except Exception:
                return True

        except Exception:
            return True  # Default to allowing if verification fails

    def _verify_photo_timestamp_correlation(self, image, event) -> bool:
        """
        Verify photo timestamp is reasonably close to event date
        Prevents using old photos for new events (temporal gaming)
        """
        try:
            # Get event date
            event_date = getattr(event, "date", None)
            if not event_date:
                return True  # Can't verify without event date

            # Get image creation/upload date
            image_date = getattr(image, "created_at", None) or getattr(image, "date_created", None)
            if not image_date:
                return True  # Can't verify without image date

            # Calculate time difference
            from datetime import timedelta

            time_diff = abs((event_date.date() - image_date.date()).days)

            # Photos should be taken within reasonable time of event
            # Allow up to 7 days difference (some flexibility for delayed uploads)
            max_days_difference = 7

            return time_diff <= max_days_difference

        except Exception:
            # If timestamp verification fails, allow the image
            # (temporal correlation is a bonus check, not mandatory)
            return True

    def _get_category_status(self, completeness: float) -> str:
        """Get user-friendly status for category completeness"""
        if completeness >= 90:
            return "excellent"
        elif completeness >= 70:
            return "good"
        elif completeness >= 50:
            return "partial"
        else:
            return "limited"

    def _is_organic_production(self, category_breakdown: Dict) -> bool:
        """
        Detect whether a production is organic based on chemical event data.

        An organic farm legitimately logs zero synthetic chemical events.
        Indicators of organic farming:
        - All chemical events have organic_approved set to organic values
        - Business events mention organic certification
        - No synthetic chemical subtypes logged
        """
        chemical_data = category_breakdown.get("chemical", {})

        # If no chemical events at all, check business events for organic certification
        if chemical_data.get("actual_count", 0) == 0:
            # Check for organic indicators in the extra_data stored during analysis
            organic_indicators = chemical_data.get("organic_indicators", [])
            return bool(organic_indicators)

        # If chemical events exist, check if they are all organic-approved subtypes
        organic_subtypes = {
            "organic_herbicide",
            "organic_pesticide",
            "organic_fungicide",
            "biological_fungicide",
            "organic_fertilizer",
            "sulfur_fungicide",
            "biological_pesticide",
        }
        chemical_subtypes = chemical_data.get("chemical_subtypes_used", set())
        if chemical_subtypes and chemical_subtypes.issubset(organic_subtypes):
            return True

        return False

    def _calculate_completeness_score(self, category_breakdown: Dict, history=None) -> int:
        """
        Calculate overall completeness score (0-100) based on category balance.

        Item #17 - Organic farm correction:
        Organic farms log zero chemical events by design. Under the standard weighting
        they lose 20% of their score for the Chemical category even though they are
        being MORE transparent (no synthetic inputs used). The fix redistributes the
        Chemical weight proportionally to the other categories when the farm appears
        to be organic AND has zero chemical events.

        Anti-gaming note (2026-03-21):
        The organic bypass (awarding 100% chemical credit) is intentionally gated
        behind a positive total event count check in calculate_transparency_score().
        Callers MUST NOT call this method directly when actual_count == 0, because
        the bypass would grant a non-zero score to a production with no events.
        The MINIMUM_EVENTS_THRESHOLD cap is applied in calculate_transparency_score
        as a second layer of protection for productions with 1-2 events.
        """

        if not category_breakdown:
            return 0

        # Base category weights
        category_weights = {
            "production": 0.30,  # Core farming activities
            "chemical": 0.20,  # Chemical transparency crucial (may be redistributed)
            "soil": 0.18,  # Sustainability practices
            "pest": 0.12,  # IPM practices
            "weather": 0.05,  # Environmental context
            "business": 0.10,  # Certifications
            "general": 0.05,  # Miscellaneous
        }

        chemical_data = category_breakdown.get("chemical", {})
        has_zero_chemical_events = chemical_data.get("actual_count", 0) == 0

        # Item #17: Determine if this is an organic production with no chemical events
        organic_production = False
        if has_zero_chemical_events and history is not None:
            # Anti-gaming tightening (Phase 3, 2026-06-11): this bypass previously
            # triggered on a bare "organic" keyword in any business-event
            # description — one free-text event saying "organic" was worth +20
            # points of chemical-category credit. Now it requires the same gate
            # the consumer organic claim uses (ConsumerClaimValidator): a
            # verified USDA Organic certification or documented transition
            # records. Free-text claims no longer qualify.
            try:
                from certifications.services.consumer_claim_validator import ConsumerClaimValidator

                claim = ConsumerClaimValidator().validate(history)
                organic_production = claim.status in ("certified_organic", "transitioning")
            except Exception:
                organic_production = False

            # Also check chemical events for organic-only subtypes (organic farms may
            # still log organic amendments — they just don't log synthetic chemicals)
            if not organic_production:
                chem_events = self._events_of(history, ChemicalEvent)
                if chem_events:
                    organic_subtypes = {
                        "organic_herbicide",
                        "organic_pesticide",
                        "organic_fungicide",
                        "biological_fungicide",
                        "organic_fertilizer",
                        "sulfur_fungicide",
                        "biological_pesticide",
                    }
                    all_organic = all(
                        (e.chemical_subtype or "") in organic_subtypes for e in chem_events if e.chemical_subtype
                    )
                    if all_organic and len(chem_events) > 0:
                        organic_production = True

        if has_zero_chemical_events and organic_production:
            # The Chemical category keeps its 0.20 weight and is awarded full credit: zero
            # synthetic chemical use on a certified-organic farm IS the documentation of that
            # practice, so the farm is not penalised for the absence of spray records.
            #
            # NB the previous comment here claimed the weight was "redistributed proportionally
            # among remaining categories". It never was: the code built `redistributed_weights`
            # and `non_chemical_total`, then assigned `effective_weights[cat] = w` on BOTH
            # branches of the loop, making the result identical to `category_weights`. The two
            # locals were never read. Only the 100% chemical credit was ever real, and that is
            # what this branch now says.
            chemical_credit = 100.0
            effective_weights = category_weights
        else:
            effective_weights = category_weights
            chemical_credit = None  # Use actual completeness

        weighted_score = 0
        total_weight = 0

        for category, weight in effective_weights.items():
            if category in category_breakdown:
                if category == "chemical" and chemical_credit is not None:
                    score = chemical_credit
                else:
                    score = category_breakdown[category]["completeness_percentage"]
                weighted_score += score * weight
                total_weight += weight

        if total_weight == 0:
            return 0

        base_score = int(weighted_score / total_weight)
        cert_bonus = self._calculate_certification_bonus(history)
        return min(100, base_score + cert_bonus)

    def _calculate_certification_bonus(self, history) -> int:
        """
        Calculate bonus points from verified certifications on the establishment.
        Up to +5 points added to transparency score.

        - Verified + active cert: +3 each (max 2 counted)
        - Self-reported + active cert: +1 each (max 2 counted)
        - Expired/revoked: +0
        """
        if history is None:
            return 0

        try:
            establishment = None
            if hasattr(history, "parcel") and history.parcel:
                establishment = history.parcel.establishment
            if not establishment:
                return 0

            from certifications.models import Certification

            certs = Certification.objects.filter(establishment=establishment)
            bonus = 0
            for cert in certs:
                if cert.is_active and cert.verification_status == "verified":
                    bonus += 3
                elif cert.is_active and cert.verification_status == "self_reported":
                    bonus += 1

            return min(bonus, 5)
        except Exception:
            # Certifications app may not have data yet, gracefully return 0
            return 0

    def _generate_transparency_message(self, transparency_percentage: float, category_breakdown: Dict) -> str:
        """Generate consumer-friendly transparency message with photo verification insights"""

        # Count total practices documented and photo-verified practices
        total_practices = sum(cat.get("actual_count", 0) for cat in category_breakdown.values())
        photo_verified_practices = sum(cat.get("photo_verified_count", 0) for cat in category_breakdown.values())
        expected_practices = sum(cat.get("expected_count", 0) for cat in category_breakdown.values())

        # Calculate overall photo verification rate
        photo_verification_rate = photo_verified_practices / total_practices if total_practices > 0 else 0

        # Generate base transparency message
        if transparency_percentage >= 95:
            base_message = (
                f"Complete transparency: {total_practices} farming practices documented with full growing details"
            )
        elif transparency_percentage >= 85:
            base_message = f"{transparency_percentage:.0f}% transparency: {total_practices} of {expected_practices} farming practices documented"
        elif transparency_percentage >= 70:
            base_message = f"{transparency_percentage:.0f}% transparency: Good record of how this food was grown ({total_practices} practices documented)"
        elif transparency_percentage >= 50:
            base_message = f"{transparency_percentage:.0f}% transparency: Basic growing information available ({total_practices} practices documented)"
        else:
            base_message = f"{transparency_percentage:.0f}% transparency: Limited growing information ({total_practices} practices documented)"

        # Add photo verification trust indicator for consumer confidence
        if photo_verification_rate >= 0.8:
            verification_note = f" with photo evidence for {photo_verified_practices} practices"
        elif photo_verification_rate >= 0.5:
            verification_note = f" including {photo_verified_practices} photo-verified practices"
        elif photo_verified_practices > 0:
            verification_note = f" with {photo_verified_practices} photo-verified practices"
        else:
            verification_note = ""

        return base_message + verification_note

    def _get_consumer_friendly_categories(self, category_breakdown: Dict) -> Dict:
        """Convert technical categories to consumer-friendly farming practice explanations"""

        # Map technical categories to consumer-friendly descriptions
        category_mapping = {
            "production": {
                "name": "Growing Practices",
                "description": "How this food was planted, grown, and harvested",
                "examples": "Planting dates, growing methods, harvest timing",
            },
            "chemical": {
                "name": "Treatment Details",
                "description": "What was used to help this food grow healthy",
                "examples": "Organic fertilizers, natural pest control, soil nutrients",
            },
            "soil": {
                "name": "Soil Care",
                "description": "How the soil was cared for to grow healthy food",
                "examples": "Soil testing, composting, cover crops, soil health",
            },
            "pest": {
                "name": "Pest Management",
                "description": "How pests were managed naturally and safely",
                "examples": "Beneficial insects, crop rotation, natural deterrents",
            },
            "weather": {
                "name": "Weather Conditions",
                "description": "Weather that affected how this food grew",
                "examples": "Rainfall, temperature, seasonal conditions",
            },
            "business": {
                "name": "Certifications",
                "description": "Official certifications and quality standards",
                "examples": "Organic certification, food safety, quality inspections",
            },
            "general": {
                "name": "Additional Details",
                "description": "Other important farming practices and notes",
                "examples": "Special techniques, sustainability practices, farm notes",
            },
        }

        consumer_categories = {}
        for tech_name, data in category_breakdown.items():
            if tech_name in category_mapping:
                mapping = category_mapping[tech_name]

                # Generate photo verification trust message
                photo_trust_message = self._get_photo_trust_message(data)

                consumer_categories[tech_name] = {
                    **data,  # Keep original data
                    "consumer_name": mapping["name"],
                    "consumer_description": mapping["description"],
                    "examples": mapping["examples"],
                    "documented": data["actual_count"] > 0,
                    "transparency_level": self._get_transparency_level(data["completeness_percentage"]),
                    "photo_trust_message": photo_trust_message,
                    "verification_strength": self._get_verification_strength(data),
                }

        return consumer_categories

    def _get_photo_trust_message(self, category_data: Dict) -> str:
        """Generate consumer-friendly photo verification trust message"""

        if not category_data.get("requires_photos", False):
            return "Documentation provided"

        photo_rate = category_data.get("photo_verification_rate", 0)
        photo_count = category_data.get("photo_verified_count", 0)
        total_count = category_data.get("actual_count", 0)

        if photo_rate >= 80:
            return f"Photo verified ({photo_count} of {total_count} practices)"
        elif photo_rate >= 50:
            return f"Partially photo verified ({photo_count} of {total_count} practices)"
        elif photo_count > 0:
            return f"Some photo verification ({photo_count} of {total_count} practices)"
        else:
            return "Text documentation only"

    def _get_verification_strength(self, category_data: Dict) -> str:
        """Get verification strength level for consumer trust indicators"""

        if not category_data.get("requires_photos", False):
            return "standard"  # Non-critical categories have standard verification

        photo_rate = category_data.get("photo_verification_rate", 0)

        if photo_rate >= 80:
            return "strong"  # High photo verification
        elif photo_rate >= 50:
            return "moderate"  # Moderate photo verification
        elif photo_rate > 0:
            return "basic"  # Some photo verification
        else:
            return "minimal"  # No photo verification

    def _get_transparency_level(self, completeness: float) -> str:
        """Get consumer-friendly transparency level description"""
        if completeness >= 90:
            return "Fully documented"
        elif completeness >= 70:
            return "Well documented"
        elif completeness >= 50:
            return "Partially documented"
        else:
            return "Limited documentation"

    def _generate_consumer_summary(self, transparency_percentage: float, actual_count: int, expected_count: int) -> str:
        """Generate a clear, compelling summary for consumers about transparency"""

        if transparency_percentage >= 95:
            return f"This food has complete transparency with {actual_count} documented farming practices. You can see exactly how it was grown from start to finish."
        elif transparency_percentage >= 85:
            return f"This food has excellent transparency with {actual_count} out of {expected_count} farming practices documented. The farmer has shared detailed growing information."
        elif transparency_percentage >= 70:
            return f"This food has good transparency with {actual_count} farming practices documented. You can learn about how it was grown and cared for."
        elif transparency_percentage >= 50:
            return f"This food has basic transparency with {actual_count} farming practices documented. Some growing information is available."
        else:
            return f"This food has limited transparency with only {actual_count} farming practices documented. Minimal growing information is available."

    def _get_farming_approach(self, history: History) -> str:
        """Determine farming approach from events and data"""

        # Check extra_data first
        if history.extra_data and isinstance(history.extra_data, dict):
            approach = history.extra_data.get("farming_approach")
            if approach in ["organic", "biodynamic", "conventional"]:
                return approach

        # Infer from chemical events
        chemical_events = self._events_of(history, ChemicalEvent)
        if chemical_events:
            # Same test as the old `description__icontains` filter, run on the prefetched rows
            synthetic_found = any(
                "synthetic" in (e.description or "").lower() or "pesticide" in (e.description or "").lower()
                for e in chemical_events
            )

            if not synthetic_found:
                return "organic"

        return "conventional"  # Default

    # get_transparency_insights(), _get_category_suggestion() and compare_with_own_history()
    # were deleted 2026-09-30. All three had zero callers anywhere in the codebase, and all
    # three returned a grade: `current_score` from `transparency_percentage`, a <70 threshold
    # that told the farmer to document more, and a personal-best comparison against the farm's
    # own previous seasons.
    #
    # The last of those was the careful one (it replaced hardcoded industry benchmarks with the
    # farm's own history, which is a real reference point), and it is still removed, because the
    # score it compares does not exist any more: `History.transparency_score` left every payload
    # on 2026-09-30 and the producer dashboard shows counts. Progress against a farm's own prior
    # seasons is worth building again from COUNTS, not from a percentage.
    #
    # What is left of this class is the FACTS the consumer QR endpoint reads: event count per
    # category, photo counts, farming approach.

    # calculate_establishment_transparency() and its six exclusive helpers
    # (_analyze_establishment_production_categories, _has_blockchain_verification,
    # _generate_enhancement_opportunities, _calculate_establishment_benchmarks,
    # _analyze_seasonal_patterns, _generate_farmer_profile) were deleted 2026-08-02.
    #
    # The entry point had no callers anywhere in the codebase, and each helper was called
    # only from it. It was also broken: overall_transparency_score was a 0-1 FRACTION
    # (total_points / total_possible, denominator += 100 per production) which
    # _calculate_establishment_benchmarks then compared against 90/80/70/60 — so every
    # farm would have graded "developing" had it ever been wired up.
    #
    # Farm-level aggregation lives in EstablishmentDashboardMetricsSerializer
    # (company/serializers.py), which averages FINISHED seasons only.
