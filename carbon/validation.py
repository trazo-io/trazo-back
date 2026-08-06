"""
Input validation utilities for carbon endpoints.
Implements secure validation patterns and XSS protection.
"""

import logging
import re
from typing import Any, Optional, Union

from django.core.exceptions import ValidationError
from django.utils.html import escape

from rest_framework import serializers

logger = logging.getLogger(__name__)


class QRParameterValidator:
    """
    Validator for QR endpoint parameters with security-focused validation.
    """

    @staticmethod
    def validate_production_id(production_id: Any) -> int:
        """
        Validate and sanitize production ID parameter.

        Args:
            production_id: Raw production ID from request

        Returns:
            Validated integer production ID

        Raises:
            ValidationError: If production ID is invalid
        """
        if not production_id:
            raise ValidationError("Production ID is required")

        try:
            # Convert to int to prevent injection attempts
            prod_id = int(production_id)

            # Validate range (reasonable production ID range)
            if prod_id <= 0 or prod_id > 999999999:
                raise ValidationError("Production ID must be between 1 and 999999999")

            return prod_id

        except (ValueError, TypeError):
            logger.warning(f"🚨 Invalid production ID format: {production_id}")
            raise ValidationError("Production ID must be a valid integer")

    @staticmethod
    def validate_quick_mode(quick_mode: Any) -> bool:
        """
        Validate quick_mode parameter.

        Args:
            quick_mode: Raw quick_mode from request

        Returns:
            Boolean quick_mode value
        """
        if quick_mode is None:
            return False

        # Handle various truthy string representations
        if isinstance(quick_mode, str):
            return quick_mode.lower() in ("true", "1", "yes", "on")

        return bool(quick_mode)

    @staticmethod
    def validate_cache_bust(cache_bust: Any) -> bool:
        """
        Validate cache_bust parameter.

        Args:
            cache_bust: Raw cache_bust from request

        Returns:
            Boolean cache_bust value
        """
        if cache_bust is None:
            return False

        # Handle various truthy string representations
        if isinstance(cache_bust, str):
            return cache_bust.lower() in ("true", "1", "yes", "bust_cache")

        return bool(cache_bust)


class ProductionDataSanitizer:
    """
    Sanitizer for production data to prevent XSS attacks.
    """

    @staticmethod
    def sanitize_text_field(value: Any, max_length: int = 1000) -> str:
        """
        Sanitize text fields to prevent XSS attacks.

        Args:
            value: Raw text value
            max_length: Maximum allowed length

        Returns:
            Sanitized text string
        """
        if not value:
            return ""

        # Convert to string and escape HTML
        text = escape(str(value))

        # Limit length to prevent DoS attacks
        if len(text) > max_length:
            text = text[:max_length] + "..."
            logger.warning(f"🚨 Text field truncated due to excessive length: {len(str(value))} chars")

        return text

    @staticmethod
    def sanitize_numeric_field(value: Any, field_name: str = "numeric") -> Union[float, int, None]:
        """
        Sanitize numeric fields with validation.

        Args:
            value: Raw numeric value
            field_name: Field name for logging

        Returns:
            Validated numeric value or None
        """
        if value is None or value == "":
            return None

        try:
            # Handle string representations
            if isinstance(value, str):
                # Remove any non-numeric characters except decimal point and minus
                cleaned = re.sub(r"[^\d.-]", "", value)
                if not cleaned:
                    return None
                value = float(cleaned)

            # Validate reasonable ranges to prevent overflow attacks
            if isinstance(value, (int, float)):
                if abs(value) > 1e10:  # Reasonable upper bound
                    logger.warning(f"🚨 Numeric value out of range for {field_name}: {value}")
                    return None
                return value

            return None

        except (ValueError, TypeError, OverflowError):
            logger.warning(f"🚨 Invalid numeric value for {field_name}: {value}")
            return None

    @staticmethod
    def sanitize_url_field(value: Any) -> str:
        """
        Sanitize URL fields to prevent malicious URLs.

        Args:
            value: Raw URL value

        Returns:
            Sanitized URL string
        """
        if not value:
            return ""

        url = str(value).strip()

        # Basic URL validation - only allow http/https
        if not re.match(r"^https?://", url):
            logger.warning(f"🚨 Invalid URL protocol: {url}")
            return ""

        # Limit URL length
        if len(url) > 2000:
            logger.warning(f"🚨 URL too long: {len(url)} chars")
            return ""

        # Escape HTML in URL
        return escape(url)


class TimelineDataValidator:
    """
    Validator for timeline data with comprehensive security checks.
    """

    @staticmethod
    def validate_timeline_data(timeline_data: list) -> list:
        """
        Validate and sanitize entire timeline data structure.

        Args:
            timeline_data: Raw timeline data list

        Returns:
            Validated and sanitized timeline data
        """
        if not isinstance(timeline_data, list):
            logger.warning("🚨 Timeline data is not a list")
            return []

        validated_data = []

        for idx, event in enumerate(timeline_data):
            try:
                validated_event = TimelineDataValidator._validate_event(event, idx)
                if validated_event:
                    validated_data.append(validated_event)
            except Exception as e:
                logger.error(f"🚨 Error validating timeline event {idx}: {e}")
                continue

        return validated_data

    @staticmethod
    def _validate_event(event: dict, index: int) -> Optional[dict]:
        """
        Validate individual timeline event.

        Args:
            event: Raw event dictionary
            index: Event index for logging

        Returns:
            Validated event dictionary or None
        """
        if not isinstance(event, dict):
            logger.warning(f"🚨 Timeline event {index} is not a dictionary")
            return None

        sanitizer = ProductionDataSanitizer()

        # Validate required fields
        if "id" not in event or "type" not in event:
            logger.warning(f"🚨 Timeline event {index} missing required fields")
            return None

        validated_event = {
            "id": sanitizer.sanitize_text_field(event.get("id"), 100),
            "type": sanitizer.sanitize_text_field(event.get("type"), 50),
            "date": sanitizer.sanitize_text_field(event.get("date"), 50),
            "description": sanitizer.sanitize_text_field(event.get("description"), 1000),
            "observation": sanitizer.sanitize_text_field(event.get("observation"), 1000),
            "certified": bool(event.get("certified", False)),
        }

        # Validate chemical-specific fields if present.
        #
        # `volume` / `volume_unit` and the NPK percentages are DELIBERATELY ABSENT (2026-08-02).
        # They are stripped from the other two anonymous payloads by
        # PublicHistorySerializer._CERTIFIER_ONLY_EVENT_FIELDS as agronomic-audit detail, and
        # this endpoint — a third anonymous surface with its own allow-list — was publishing
        # them: live values of {"volume": "2250", "volume_unit": "gal"} and
        # npk_n_percentage on the same productions the main serializer redacts.
        #
        # One rule, three endpoints. Anything added here must be checked against that tuple
        # first; an allow-list that disagrees with the other two is a leak by construction.
        chemical_fields = [
            "commercial_name",
            "chemical_name",
            "area",
            "area_unit",
            "application_method",
        ]

        for field in chemical_fields:
            if field in event:
                if field == "area":
                    validated_event[field] = sanitizer.sanitize_text_field(event[field], 50)
                else:
                    validated_event[field] = sanitizer.sanitize_text_field(event[field], 200)

        # Validate albums data
        if "albums" in event and isinstance(event["albums"], list):
            validated_event["albums"] = TimelineDataValidator._validate_albums(event["albums"])

        return validated_event

    @staticmethod
    def _validate_albums(albums: list) -> list:
        """
        Validate album data with XSS protection.

        Args:
            albums: Raw albums list

        Returns:
            Validated albums list
        """
        validated_albums = []
        sanitizer = ProductionDataSanitizer()

        for album in albums:
            if not isinstance(album, dict):
                continue

            validated_album = {
                "id": sanitizer.sanitize_text_field(album.get("id"), 50),
                "title": sanitizer.sanitize_text_field(album.get("title"), 200),
                "image_url": sanitizer.sanitize_url_field(album.get("image_url")),
            }

            validated_albums.append(validated_album)

        return validated_albums


class APIResponseValidator:
    """
    Validator for API response data to ensure secure output.
    """

    @staticmethod
    def validate_response_data(response_data: dict) -> dict:
        """
        Validate and sanitize API response data.

        Args:
            response_data: Raw response dictionary

        Returns:
            Validated and sanitized response
        """
        if not isinstance(response_data, dict):
            logger.error("🚨 Response data is not a dictionary")
            return {"error": "Invalid response format"}

        sanitizer = ProductionDataSanitizer()
        validated_response = {}

        # Validate each field in response
        for key, value in response_data.items():
            try:
                validated_response[key] = APIResponseValidator._validate_response_field(key, value, sanitizer)
            except Exception as e:
                logger.error(f"🚨 Error validating response field {key}: {e}")
                continue

        return validated_response

    @staticmethod
    def _validate_response_field(key: str, value: Any, sanitizer: ProductionDataSanitizer) -> Any:
        """
        Validate individual response field based on its type and key.

        Args:
            key: Field name
            value: Field value
            sanitizer: Sanitizer instance

        Returns:
            Validated field value
        """
        # Handle different field types
        if key in ["transparencyScore", "carbonFootprint", "total_emissions", "total_offsets"]:
            return sanitizer.sanitize_numeric_field(value, key)

        elif key in ["verificationLevel", "cropName", "farmName", "recommendations"]:
            if isinstance(value, list):
                return [sanitizer.sanitize_text_field(item, 500) for item in value]
            return sanitizer.sanitize_text_field(value, 500)

        elif key == "timeline":
            if isinstance(value, list):
                return TimelineDataValidator.validate_timeline_data(value)
            return []

        elif isinstance(value, dict):
            # Recursively validate nested dictionaries
            return {k: APIResponseValidator._validate_response_field(k, v, sanitizer) for k, v in value.items()}

        elif isinstance(value, list):
            # Validate lists
            return [APIResponseValidator._validate_response_field(f"{key}_item", item, sanitizer) for item in value]

        elif isinstance(value, str):
            return sanitizer.sanitize_text_field(value, 1000)

        elif isinstance(value, (int, float)):
            return sanitizer.sanitize_numeric_field(value, key)

        else:
            # For other types, convert to string and sanitize
            return sanitizer.sanitize_text_field(str(value), 1000)
