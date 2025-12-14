"""
Google Cloud Vision API service for agricultural photo content validation.

MVP Photo Verification Feature:
- Validates that uploaded photos contain agricultural content
- Detects AI-generated or stock images
- Provides confidence scores for photo relevance

Configuration:
- VISION_API_ENABLED: Enable/disable real API calls (default: False in dev)
- VISION_API_BYPASS_IN_DEV: Simulate success in development (default: True)
- GOOGLE_CLOUD_VISION_API_KEY: API key for Google Cloud Vision
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


class ContentValidationResult(Enum):
    """Photo content validation result codes."""

    VALID_AGRICULTURAL = "valid_agricultural"
    LIKELY_AGRICULTURAL = "likely_agricultural"
    UNCERTAIN = "uncertain"
    NOT_AGRICULTURAL = "not_agricultural"
    AI_GENERATED = "ai_generated"
    STOCK_PHOTO = "stock_photo"
    ERROR = "error"
    BYPASSED = "bypassed"  # Development bypass


@dataclass
class VisionAnalysisResult:
    """Result of Vision API analysis."""

    is_valid: bool
    validation_result: ContentValidationResult
    confidence_score: float  # 0.0 to 1.0
    detected_labels: List[str]
    agricultural_labels: List[str]
    warnings: List[str]
    raw_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


# Agricultural content labels that indicate valid farming photos
AGRICULTURAL_LABELS = {
    # Farming activities
    "farm",
    "farming",
    "agriculture",
    "agricultural",
    "crop",
    "crops",
    "harvest",
    "harvesting",
    "planting",
    "irrigation",
    "tractor",
    "farming equipment",
    "agricultural machinery",
    # Plants and produce
    "plant",
    "plants",
    "vegetation",
    "field",
    "orchard",
    "vineyard",
    "greenhouse",
    "garden",
    "fruit",
    "vegetable",
    "grain",
    "wheat",
    "corn",
    "rice",
    "avocado",
    "tomato",
    "potato",
    "lettuce",
    "tree",
    "trees",
    # Soil and land
    "soil",
    "dirt",
    "earth",
    "land",
    "farmland",
    "pasture",
    "meadow",
    # Equipment and tools
    "tractor",
    "plow",
    "sprayer",
    "fertilizer",
    "pesticide",
    "herbicide",
    "seed",
    "seeds",
    "seedling",
    "seedlings",
    # Animals (for mixed farming)
    "livestock",
    "cattle",
    "cow",
    "sheep",
    "chicken",
    "poultry",
    # Weather and environment
    "rain",
    "drought",
    "frost",
    "weather",
    "sun",
    "sky",
    "clouds",
    # Documents and labels (for chemical/certification events)
    "label",
    "bottle",
    "container",
    "package",
    "certificate",
    "document",
}

# Labels that might indicate non-authentic photos
SUSPICIOUS_LABELS = {
    "stock photo",
    "illustration",
    "clipart",
    "drawing",
    "cartoon",
    "graphic design",
    "digital art",
    "computer generated",
    "ai generated",
    "synthetic",
    "artificial",
}


class VisionAPIService:
    """
    Google Cloud Vision API service for validating agricultural photo content.

    Supports two modes:
    1. Production: Real API calls to Google Cloud Vision
    2. Development: Bypass mode that simulates successful validation
    """

    def __init__(self):
        """Initialize the Vision API service."""
        self._client = None
        self._api_key = getattr(settings, "GOOGLE_CLOUD_VISION_API_KEY", None)
        self._enabled = getattr(settings, "VISION_API_ENABLED", False)
        self._bypass_in_dev = getattr(settings, "VISION_API_BYPASS_IN_DEV", True)
        self._is_development = getattr(settings, "DEBUG", True)

    @property
    def is_enabled(self) -> bool:
        """Check if real API calls are enabled."""
        return self._enabled and self._api_key

    @property
    def should_bypass(self) -> bool:
        """Check if API should be bypassed in development."""
        return self._is_development and self._bypass_in_dev and not self._enabled

    def _get_client(self):
        """Get or create the Vision API client."""
        if self._client is None:
            try:
                from google.cloud import vision

                # Use API key authentication
                if self._api_key:
                    # For API key auth, we need to use REST transport
                    from google.cloud.vision_v1 import ImageAnnotatorClient
                    from google.api_core.client_options import ClientOptions

                    client_options = ClientOptions(
                        api_key=self._api_key,
                    )
                    self._client = ImageAnnotatorClient(client_options=client_options)
                else:
                    # Use default credentials (service account)
                    self._client = vision.ImageAnnotatorClient()

                logger.info("Google Cloud Vision API client initialized")

            except ImportError:
                logger.error("google-cloud-vision package not installed. " "Run: pip install google-cloud-vision")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Vision API client: {e}")
                raise

        return self._client

    def analyze_photo(self, image_content: bytes) -> VisionAnalysisResult:
        """
        Analyze photo content using Google Cloud Vision API.

        Args:
            image_content: Raw image bytes

        Returns:
            VisionAnalysisResult with validation details
        """
        # Check if we should bypass in development
        if self.should_bypass:
            logger.info("Vision API bypassed in development mode - simulating success")
            return self._simulate_successful_validation()

        # Check if API is enabled
        if not self.is_enabled:
            logger.warning("Vision API is disabled - returning uncertain result")
            return VisionAnalysisResult(
                is_valid=True,  # Allow upload when API is disabled
                validation_result=ContentValidationResult.UNCERTAIN,
                confidence_score=0.5,
                detected_labels=[],
                agricultural_labels=[],
                warnings=["Photo content validation is disabled"],
            )

        try:
            return self._analyze_with_api(image_content)
        except Exception as e:
            logger.error(f"Vision API analysis failed: {e}")
            return VisionAnalysisResult(
                is_valid=True,  # Allow upload on API error (graceful degradation)
                validation_result=ContentValidationResult.ERROR,
                confidence_score=0.0,
                detected_labels=[],
                agricultural_labels=[],
                warnings=["Photo validation failed - proceeding without verification"],
                error_message=str(e),
            )

    def _analyze_with_api(self, image_content: bytes) -> VisionAnalysisResult:
        """
        Perform actual API call to Google Cloud Vision.

        Args:
            image_content: Raw image bytes

        Returns:
            VisionAnalysisResult from API analysis
        """
        from google.cloud import vision

        client = self._get_client()

        # Create image object
        image = vision.Image(content=image_content)

        # Request label detection and safe search
        features = [
            vision.Feature(type_=vision.Feature.Type.LABEL_DETECTION, max_results=20),
            vision.Feature(type_=vision.Feature.Type.SAFE_SEARCH_DETECTION),
        ]

        request = vision.AnnotateImageRequest(image=image, features=features)
        response = client.annotate_image(request)

        # Check for errors
        if response.error.message:
            return VisionAnalysisResult(
                is_valid=True,
                validation_result=ContentValidationResult.ERROR,
                confidence_score=0.0,
                detected_labels=[],
                agricultural_labels=[],
                warnings=["API returned error - proceeding without verification"],
                error_message=response.error.message,
            )

        # Extract labels
        detected_labels = []
        agricultural_labels = []
        suspicious_detected = []

        for label in response.label_annotations:
            label_name = label.description.lower()
            detected_labels.append(label_name)

            # Check for agricultural content
            if label_name in AGRICULTURAL_LABELS or any(agri_label in label_name for agri_label in AGRICULTURAL_LABELS):
                agricultural_labels.append(label_name)

            # Check for suspicious content
            if label_name in SUSPICIOUS_LABELS or any(susp_label in label_name for susp_label in SUSPICIOUS_LABELS):
                suspicious_detected.append(label_name)

        # Calculate confidence and validation result
        warnings = []
        raw_response = {
            "labels": [{"description": l.description, "score": l.score} for l in response.label_annotations],
            "safe_search": {
                "adult": response.safe_search_annotation.adult.name,
                "violence": response.safe_search_annotation.violence.name,
            },
        }

        # Determine validation result
        if suspicious_detected:
            # Detected potential AI or stock photo
            validation_result = ContentValidationResult.AI_GENERATED
            is_valid = False
            confidence_score = 0.2
            warnings.append(f"Photo may be AI-generated or stock: {', '.join(suspicious_detected)}")

        elif len(agricultural_labels) >= 3:
            # Strong agricultural content
            validation_result = ContentValidationResult.VALID_AGRICULTURAL
            is_valid = True
            confidence_score = min(0.95, 0.5 + (len(agricultural_labels) * 0.1))

        elif len(agricultural_labels) >= 1:
            # Some agricultural content
            validation_result = ContentValidationResult.LIKELY_AGRICULTURAL
            is_valid = True
            confidence_score = 0.5 + (len(agricultural_labels) * 0.15)
            warnings.append("Photo has limited agricultural content - consider retaking")

        elif len(detected_labels) > 0:
            # No agricultural content detected
            validation_result = ContentValidationResult.NOT_AGRICULTURAL
            is_valid = False
            confidence_score = 0.3
            warnings.append(f"No agricultural content detected. Found: {', '.join(detected_labels[:5])}")

        else:
            # Couldn't analyze
            validation_result = ContentValidationResult.UNCERTAIN
            is_valid = True  # Allow when uncertain
            confidence_score = 0.5
            warnings.append("Could not analyze photo content")

        logger.info(
            f"Vision API analysis complete: {validation_result.value}, "
            f"confidence={confidence_score:.2f}, agricultural_labels={len(agricultural_labels)}"
        )

        return VisionAnalysisResult(
            is_valid=is_valid,
            validation_result=validation_result,
            confidence_score=confidence_score,
            detected_labels=detected_labels,
            agricultural_labels=agricultural_labels,
            warnings=warnings,
            raw_response=raw_response,
        )

    def _simulate_successful_validation(self) -> VisionAnalysisResult:
        """
        Simulate successful validation for development mode.

        Returns a realistic-looking successful result without making API calls.
        """
        return VisionAnalysisResult(
            is_valid=True,
            validation_result=ContentValidationResult.BYPASSED,
            confidence_score=0.85,
            detected_labels=[
                "farm",
                "agriculture",
                "crop",
                "field",
                "vegetation",
            ],
            agricultural_labels=["farm", "agriculture", "crop"],
            warnings=["DEV MODE: Vision API bypassed - simulated success"],
            raw_response={
                "bypassed": True,
                "mode": "development",
                "note": "This is simulated data. Enable VISION_API_ENABLED=True for real validation.",
            },
        )

    def validate_for_event_type(
        self, image_content: bytes, event_type: str, subtype: Optional[str] = None
    ) -> VisionAnalysisResult:
        """
        Validate photo content with event-type-specific requirements.

        Args:
            image_content: Raw image bytes
            event_type: Event type (e.g., 'chemical', 'production', 'weather')
            subtype: Event subtype (e.g., 'FE' for fertilizer)

        Returns:
            VisionAnalysisResult with event-specific validation
        """
        result = self.analyze_photo(image_content)

        # Add event-specific validations
        event_specific_labels = {
            "chemical": {
                "required_any": ["bottle", "label", "container", "sprayer", "fertilizer"],
                "description": "chemical product or application",
            },
            "production": {
                "required_any": ["farm", "field", "crop", "harvest", "planting"],
                "description": "farming activity",
            },
            "equipment": {
                "required_any": ["tractor", "equipment", "machine", "fuel", "maintenance"],
                "description": "equipment or maintenance",
            },
            "soil": {
                "required_any": ["soil", "dirt", "earth", "test", "sample"],
                "description": "soil or testing",
            },
            "pest": {
                "required_any": ["insect", "pest", "trap", "damage", "plant"],
                "description": "pest management",
            },
        }

        if event_type in event_specific_labels and result.is_valid:
            config = event_specific_labels[event_type]
            required_labels = config["required_any"]

            # Check if any required label is present
            has_required = any(
                label in result.detected_labels
                or any(req in label for label in result.detected_labels for req in required_labels)
                for label in required_labels
            )

            if not has_required and result.validation_result != ContentValidationResult.BYPASSED:
                result.warnings.append(
                    f"Photo may not show {config['description']}. "
                    f"Expected content related to: {', '.join(required_labels)}"
                )

        return result


# Singleton instance for easy importing
vision_api_service = VisionAPIService()
