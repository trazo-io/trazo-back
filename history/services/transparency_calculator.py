"""Counts of what a production logged, for the consumer QR page (`/api/transparency/<uuid>/`).

Facts only: events per category, how many carry a photo, the farming approach. It computed a
0-100 transparency score, per-category statuses and a "transparency level" until 2026-11-08; the
score is retired as a concept (`.claude/rules/transparency-first.md`), so nothing here grades.
"""

import logging
from typing import Dict, Tuple

from django.db.models import prefetch_related_objects

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
    """Counts what a production logged, per event category. Never a percentage or a grade."""

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

    # Tier 3 (implicit — everything else): No photo penalty
    #   IR, EM, TH = Production; PA, TI = Soil; TA = Pest
    #   All weather, business, general events

    def calculate_transparency_score(self, history: History) -> Dict:
        """FACTS about what a production logged, for the consumer QR page. Never a grade.

        The name stayed when the method stopped grading (2026-11-08): the QR view and the
        retired-score guard (history/tests/test_no_transparency_score_served.py) both name it.
        Until then it computed a weighted 0-100 `transparency_percentage`, a completeness score,
        per-category "complete/partial/missing" statuses, a `transparency_level`, photo-tier
        penalties and a consumer verdict on every QR request, and the gate in
        transparency_views.py stripped them before the response. The score is retired as a
        CONCEPT, so nothing here computes one any more: the gate stays as a second line.

        Returns `actual_event_count`, `farming_approach` and `category_breakdown`
        ({category: {"actual_count", "photo_verified_count"}}).

        NEVER catch here. An error must reach the view, whose handler answers 500. Returning zero
        counts instead would publish "0 practices documented" for a farm that logged plenty: an
        unknown is not a zero (review of #353).
        """
        self._ensure_prefetched(history)
        return {
            "actual_event_count": self._count_all_events(history),
            "farming_approach": self._get_farming_approach(history),
            "category_breakdown": self._category_counts(history),
        }

    def _category_counts(self, history: History) -> Dict:
        """Per category: events logged, and how many carry a photo that passes the checks."""
        breakdown = {}
        for category_name, event_models in self.EVENT_CATEGORIES.items():
            events = [event for model in event_models for event in self._events_of(history, model)]
            breakdown[category_name] = {
                "actual_count": len(events),
                "photo_verified_count": sum(1 for event in events if self._has_photo_verification(event)),
            }
        return breakdown

    def _count_all_events(self, history: History) -> int:
        """Count all events across all categories for this production history"""

        total_events = 0

        # Count each event type
        for event_models in self.EVENT_CATEGORIES.values():
            for event_model in event_models:
                total_events += len(self._events_of(history, event_model))

        return total_events

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
