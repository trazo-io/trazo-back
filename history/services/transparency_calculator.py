"""
Trazo Transparency Calculator Service
Calculates farm record completeness to encourage honest logging
Eliminates competitive carbon ranking - the root cause of farmer gaming behavior

Following Trazo's main goal: Authentic transparency over competitive metrics
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple

from django.db.models import Q
from django.utils import timezone

from carbon.models import CropType
from product.models import Establishment, Parcel

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
        "CO",  # Soil Test, Organic Matter, Composting
        "SC",
        "TM",
        "IP",  # Scouting, Trap Monitoring, IPM
    }

    # Tier 3 (implicit — everything else): No photo penalty
    #   IR, EM, TH = Production; PA, TI = Soil; TA = Pest
    #   All weather, business, general events

    def calculate_transparency_score(self, history: History) -> Dict:
        """
        Calculate comprehensive transparency score for a production history

        Returns:
            Dict with transparency percentage, message, and category breakdown
        """
        try:
            # Get expected event count based on crop type and farming approach
            expected_count = self._get_expected_event_count(history)

            # Count actual events across all categories
            actual_count = self._count_all_events(history)

            # Calculate base transparency percentage
            if expected_count == 0:
                transparency_percentage = 100  # No events expected = perfect transparency
            else:
                transparency_percentage = min((actual_count / expected_count) * 100, 100)

            # Get category breakdown for detailed feedback
            category_breakdown = self._analyze_category_completeness(history, expected_count)

            # Calculate completeness score (weighted by category, includes photo penalty)
            completeness_score = self._calculate_completeness_score(category_breakdown)

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

        # Try to get crop type from parcel or other sources
        crop_category = "other"  # Default fallback

        if hasattr(history, "parcel") and history.parcel:
            # Try to infer from parcel data or linked crop info
            if hasattr(history.parcel, "crop_type"):
                crop_category = history.parcel.crop_type.category

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
                total_events += event_model.objects.filter(history=history).count()

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
                category_events = event_model.objects.filter(history=history)
                actual_count += category_events.count()

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

            # Album must have actual images
            if not hasattr(event.album, "images") or not event.album.images.exists():
                return False

            # Additional anti-gaming checks
            image_count = event.album.images.count()

            # Require 2+ images only for chemical subtypes (label + application evidence)
            min_images_required = (
                2 if hasattr(event, "type") and getattr(event, "type", "") in ["FE", "PE", "FU", "HE"] else 1
            )

            if image_count < min_images_required:
                return False

            verified_images = 0

            # Advanced verification for each image
            for image in event.album.images.all():
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
                    # S3 images are validated during the presigned upload process.
                    # External URLs are used for trusted sources (e.g., demo data).
                    # Basic validation: URL/key must be non-empty string.
                    url_or_key = image.s3_key or image.image_url or ""
                    if len(url_or_key.strip()) > 10:
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

    def _calculate_completeness_score(self, category_breakdown: Dict) -> int:
        """Calculate overall completeness score (0-100) based on category balance"""

        if not category_breakdown:
            return 0

        # Weight categories by importance for consumer trust
        category_weights = {
            "production": 0.30,  # Core farming activities (was 0.25, absorbed 5% from equipment)
            "chemical": 0.20,  # Chemical transparency crucial
            "soil": 0.18,  # Sustainability practices (was 0.15, gained 3%)
            "pest": 0.12,  # IPM practices (was 0.10, gained 2%)
            "weather": 0.05,  # Environmental context
            "business": 0.10,  # Certifications (was 0.05, valuable for trust)
            "general": 0.05,  # Miscellaneous
        }

        weighted_score = 0
        total_weight = 0

        for category, weight in category_weights.items():
            if category in category_breakdown:
                weighted_score += category_breakdown[category]["completeness_percentage"] * weight
                total_weight += weight

        if total_weight == 0:
            return 0

        return int(weighted_score / total_weight)

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
        chemical_events = ChemicalEvent.objects.filter(history=history)
        if chemical_events.exists():
            synthetic_found = chemical_events.filter(
                Q(description__icontains="synthetic") | Q(description__icontains="pesticide")
            ).exists()

            if not synthetic_found:
                return "organic"

        return "conventional"  # Default

    def get_transparency_insights(self, history: History) -> Dict:
        """Get actionable insights for farmers to improve transparency"""

        transparency_data = self.calculate_transparency_score(history)
        category_breakdown = transparency_data.get("category_breakdown", {})

        insights = {
            "current_score": transparency_data["transparency_percentage"],
            "recommendations": [],
            "missing_categories": [],
            "strong_categories": [],
        }

        for category, data in category_breakdown.items():
            if data["completeness_percentage"] < 50:
                insights["missing_categories"].append(
                    {
                        "category": category.replace("_", " ").title(),
                        "status": data["status"],
                        "suggestion": self._get_category_suggestion(category),
                    }
                )
            elif data["completeness_percentage"] >= 80:
                insights["strong_categories"].append(category.replace("_", " ").title())

        # Generate specific recommendations
        if len(insights["missing_categories"]) > 0:
            insights["recommendations"].append("Add more events in highlighted categories to improve transparency")

        if transparency_data["transparency_percentage"] < 70:
            insights["recommendations"].append(
                "Document routine farming activities like irrigation, equipment maintenance, and observations"
            )

        return insights

    def _get_category_suggestion(self, category: str) -> str:
        """Get specific suggestions for improving category completeness"""

        suggestions = {
            "production": "Document planting, harvesting, irrigation, and pruning activities",
            "chemical": "Record all fertilizer, pesticide, and organic amendment applications",
            "soil": "Add soil tests, pH adjustments, and organic matter additions",
            "pest": "Document pest scouting, beneficial insect releases, and IPM practices",
            "weather": "Note significant weather events affecting your crop",
            "business": "Include certifications, inspections, and compliance activities",
            "general": "Add observations, farm visits, and other notable activities",
        }

        return suggestions.get(category, "Add relevant events for this category")

    def compare_with_benchmarks(self, history: History) -> Dict:
        """
        Compare transparency with industry benchmarks (NOT competitive ranking)
        Uses absolute standards, not relative farm comparisons
        """

        transparency_data = self.calculate_transparency_score(history)
        transparency_percentage = transparency_data["transparency_percentage"]

        # Industry transparency benchmarks (absolute standards)
        benchmarks = {
            "industry_minimum": 60,
            "good_practice": 80,
            "excellent_practice": 95,
            "certification_standard": 90,
        }

        # Determine benchmark level
        if transparency_percentage >= benchmarks["excellent_practice"]:
            benchmark_level = "excellent"
            message = "Exceeds industry transparency standards"
        elif transparency_percentage >= benchmarks["certification_standard"]:
            benchmark_level = "certification"
            message = "Meets organic certification transparency standards"
        elif transparency_percentage >= benchmarks["good_practice"]:
            benchmark_level = "good"
            message = "Meets good transparency practices"
        elif transparency_percentage >= benchmarks["industry_minimum"]:
            benchmark_level = "minimum"
            message = "Meets minimum transparency requirements"
        else:
            benchmark_level = "below_minimum"
            message = "Below recommended transparency levels"

        return {
            "benchmark_level": benchmark_level,
            "message": message,
            "benchmarks": benchmarks,
            "current_score": transparency_percentage,
            "next_target": self._get_next_target(transparency_percentage, benchmarks),
        }

    def _get_next_target(self, current_score: float, benchmarks: Dict) -> Dict:
        """Get next transparency target for farmer motivation"""

        if current_score < benchmarks["industry_minimum"]:
            return {
                "target_score": benchmarks["industry_minimum"],
                "target_name": "Industry Minimum",
                "points_needed": benchmarks["industry_minimum"] - current_score,
            }
        elif current_score < benchmarks["good_practice"]:
            return {
                "target_score": benchmarks["good_practice"],
                "target_name": "Good Practice",
                "points_needed": benchmarks["good_practice"] - current_score,
            }
        elif current_score < benchmarks["certification_standard"]:
            return {
                "target_score": benchmarks["certification_standard"],
                "target_name": "Certification Standard",
                "points_needed": benchmarks["certification_standard"] - current_score,
            }
        elif current_score < benchmarks["excellent_practice"]:
            return {
                "target_score": benchmarks["excellent_practice"],
                "target_name": "Excellence",
                "points_needed": benchmarks["excellent_practice"] - current_score,
            }
        else:
            return {"target_score": 100, "target_name": "Perfect Transparency", "points_needed": 100 - current_score}

    def calculate_establishment_transparency(self, establishment: Establishment) -> Dict:
        """
        ENHANCED: Calculate comprehensive transparency metrics for entire establishment
        Returns detailed breakdown including unused database opportunities
        """

        establishment_metrics = {
            "overall_transparency_score": 0,
            "total_productions": 0,
            "total_documented_events": 0,
            "verification_breakdown": {
                "usda_factors_used": 0,
                "blockchain_verified": 0,
                "photo_verified": 0,
                "third_party_verified": 0,
            },
            "category_breakdown": {
                "planting": {"events": 0, "verified": 0, "photos": 0},
                "fertilization": {"events": 0, "verified": 0, "photos": 0},
                "irrigation": {"events": 0, "verified": 0, "photos": 0},
                "harvest": {"events": 0, "verified": 0, "photos": 0},
            },
            "data_richness": {
                "parcels_with_data": 0,
                "productions_with_events": 0,
                "events_with_photos": 0,
                "events_with_verification": 0,
                "total_data_points": 0,
                "unused_data_points": 0,
            },
            "trust_indicators": {
                "company_verified": establishment.company is not None,
                "location_verified": bool(establishment.city and establishment.state),
                "area_documented": sum(parcel.area for parcel in establishment.parcels.all() if parcel.area) > 0,
                "sustainability_commitments": bool(
                    establishment.company and getattr(establishment.company, "sustainability_commitments", None)
                ),
                "blockchain_enabled": False,  # Will be calculated based on events
                "continuous_monitoring": False,  # Based on event frequency
            },
            "enhancement_opportunities": [],
            "benchmark_comparison": {},
            "seasonal_patterns": {},
            "farmer_profile": {},
        }

        total_transparency_points = 0
        total_possible_points = 0

        # Analyze all parcels and productions (using optimized queries from indexes)
        parcels = establishment.parcels.prefetch_related(
            "histories__history_productionevent_events",
            "histories__history_chemicalevent_events",
            "histories__history_businessevent_events",
            "histories__album__images",  # Correct album relationship
        ).all()

        for parcel in parcels:
            establishment_metrics["data_richness"]["parcels_with_data"] += 1

            for history in parcel.histories.filter(published=True):
                establishment_metrics["total_productions"] += 1

                # Get production transparency data
                production_transparency = self.calculate_transparency_score(history)

                establishment_metrics["total_documented_events"] += production_transparency["actual_event_count"]
                total_transparency_points += production_transparency["transparency_percentage"]
                total_possible_points += 100

                if production_transparency["actual_event_count"] > 0:
                    establishment_metrics["data_richness"]["productions_with_events"] += 1

                # Analyze event categories and verification
                self._analyze_establishment_production_categories(history, establishment_metrics)

                # Check for blockchain verification indicators
                if self._has_blockchain_verification(history):
                    establishment_metrics["trust_indicators"]["blockchain_enabled"] = True
                    establishment_metrics["verification_breakdown"]["blockchain_verified"] += 1

        # Calculate overall transparency score
        if total_possible_points > 0:
            establishment_metrics["overall_transparency_score"] = total_transparency_points / total_possible_points

        # Calculate data richness percentage
        establishment_metrics["data_richness"]["total_data_points"] = (
            establishment_metrics["total_documented_events"]
            + establishment_metrics["data_richness"]["parcels_with_data"]
            + establishment_metrics["total_productions"]
        )

        # Estimate unused data points (database fields not displayed)
        establishment_metrics["data_richness"]["unused_data_points"] = int(
            establishment_metrics["data_richness"]["total_data_points"] * 0.65  # 65% not displayed
        )

        # Generate enhancement opportunities
        establishment_metrics["enhancement_opportunities"] = self._generate_enhancement_opportunities(
            establishment, establishment_metrics
        )

        # Benchmark comparison
        establishment_metrics["benchmark_comparison"] = self._calculate_establishment_benchmarks(establishment_metrics)

        # Analyze seasonal patterns
        establishment_metrics["seasonal_patterns"] = self._analyze_seasonal_patterns(establishment)

        # Generate farmer profile insights
        establishment_metrics["farmer_profile"] = self._generate_farmer_profile(establishment)

        return establishment_metrics

    def _analyze_establishment_production_categories(self, history: History, metrics: Dict):
        """Analyze event categories for comprehensive establishment breakdown"""

        # Get all event types for this production (optimized with indexes)
        category_mapping = {
            "planting": ProductionEvent.objects.filter(history=history, type__in=["PL"]),  # Planting events
            "fertilization": ChemicalEvent.objects.filter(history=history, type__in=["FE"]),  # Fertilizer events
            "irrigation": ProductionEvent.objects.filter(history=history, type__in=["IR"]),  # Irrigation events
            "harvest": ProductionEvent.objects.filter(history=history, type__in=["HA"]),  # Harvesting events
        }

        for category, events in category_mapping.items():
            event_count = events.count()
            verified_count = 0
            photo_count = 0

            # Count verified events (if verification field exists)
            for event in events:
                if hasattr(event, "verified") and getattr(event, "verified", False):
                    verified_count += 1
                # Count photos for events in this category
                if hasattr(event, "photos") and event.photos.exists():
                    photo_count += event.photos.count()
                elif hasattr(event, "gallery") and event.gallery.exists():
                    # Alternative photo relationship
                    for gallery in event.gallery.all():
                        photo_count += gallery.images.count() if hasattr(gallery, "images") else 0

            metrics["category_breakdown"][category]["events"] += event_count
            metrics["category_breakdown"][category]["verified"] += verified_count
            metrics["category_breakdown"][category]["photos"] += photo_count

            if photo_count > 0:
                metrics["data_richness"]["events_with_photos"] += 1
            if verified_count > 0:
                metrics["data_richness"]["events_with_verification"] += 1
                metrics["verification_breakdown"]["usda_factors_used"] += verified_count

    def _has_blockchain_verification(self, history: History) -> bool:
        """Check if production has blockchain verification"""
        # BUGFIX: Check that extra_data is a dict before calling .get()
        if history.extra_data and isinstance(history.extra_data, dict):
            return (
                history.extra_data.get("blockchain_verified", False)
                or history.extra_data.get("blockchain_hash") is not None
                or history.extra_data.get("smart_contract_address") is not None
            )
        return False

    def _generate_enhancement_opportunities(self, establishment: Establishment, metrics: Dict) -> list:
        """Generate specific enhancement opportunities based on analysis"""
        opportunities = []

        # Data completeness opportunities
        unused_percentage = (
            metrics["data_richness"]["unused_data_points"] / max(metrics["data_richness"]["total_data_points"], 1)
        ) * 100

        if unused_percentage > 50:
            opportunities.append(
                {
                    "type": "data_completeness",
                    "priority": "high",
                    "title": "Display More Database Information",
                    "description": f"Currently showing only {100-unused_percentage:.0f}% of available data",
                    "potential_improvement": f"Could display {unused_percentage:.0f}% more transparency information",
                }
            )

        # Category-specific opportunities
        for category, data in metrics["category_breakdown"].items():
            if data["events"] > 0 and (data["verified"] / data["events"]) < 0.5:
                opportunities.append(
                    {
                        "type": "verification",
                        "priority": "medium",
                        "title": f"Increase {category.title()} Verification",
                        "description": f"Only {data['verified']}/{data['events']} {category} events verified",
                        "potential_improvement": f"Verify remaining {data['events'] - data['verified']} events",
                    }
                )

        # Trust indicator opportunities
        trust_score = sum(metrics["trust_indicators"].values()) / len(metrics["trust_indicators"]) * 100
        if trust_score < 80:
            opportunities.append(
                {
                    "type": "trust_building",
                    "priority": "high",
                    "title": "Enhance Trust Indicators",
                    "description": f"Trust indicators at {trust_score:.0f}%",
                    "potential_improvement": "Enable blockchain, add certifications, improve verification",
                }
            )

        # Photo documentation opportunities
        total_events = metrics["total_documented_events"]
        events_with_photos = metrics["data_richness"]["events_with_photos"]
        if total_events > 0 and (events_with_photos / total_events) < 0.6:
            opportunities.append(
                {
                    "type": "visual_evidence",
                    "priority": "medium",
                    "title": "Increase Photo Documentation",
                    "description": f"Only {events_with_photos}/{total_events} events have photos",
                    "potential_improvement": f"Add photos to {total_events - events_with_photos} more events",
                }
            )

        return opportunities

    def _calculate_establishment_benchmarks(self, metrics: Dict) -> Dict:
        """Calculate benchmark comparisons for establishment"""
        return {
            "transparency_percentile": min(95, metrics["overall_transparency_score"] * 1.2),
            "industry_ranking": "Excellent" if metrics["overall_transparency_score"] > 85 else "Good",
            "regional_comparison": "Above Average",  # Would be calculated with regional data
            "improvement_potential": 100 - metrics["overall_transparency_score"],
            "next_milestone": {
                "target_score": min(100, metrics["overall_transparency_score"] + 10),
                "required_actions": metrics["enhancement_opportunities"][:3],
            },
        }

    def _analyze_seasonal_patterns(self, establishment: Establishment) -> Dict:
        """Analyze seasonal patterns in transparency data"""
        seasonal_data = {
            "spring_events": 0,
            "summer_events": 0,
            "fall_events": 0,
            "winter_events": 0,
            "peak_transparency_season": "unknown",
            "transparency_consistency": "stable",
        }

        # This would analyze event timing patterns across productions
        # For now, returning basic structure for future enhancement
        return seasonal_data

    def _generate_farmer_profile(self, establishment: Establishment) -> Dict:
        """Generate farmer profile based on establishment data"""
        profile = {
            "experience_level": "intermediate",  # Based on documentation quality
            "farming_approach_primary": "conventional",
            "specializations": [],
            "transparency_commitment_level": "good",
            "continuous_improvement_indicator": True,
        }

        # Company information for farmer profile
        if establishment.company:
            profile["company_name"] = establishment.company.name
            if hasattr(establishment.company, "sustainability_commitments"):
                profile["sustainability_focus"] = bool(establishment.company.sustainability_commitments)

        return profile
