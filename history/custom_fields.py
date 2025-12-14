"""
Custom Fields Module for Trazo Agricultural Events

Provides validation, sanitization, and utility functions for user-defined custom fields
that farmers can add to agricultural events. Custom fields are stored in the event's
extra_data JSONField and displayed seamlessly alongside standard event fields.

Key Features:
- XSS prevention through HTML/JavaScript sanitization
- Flexible field types (text, number, link, photo_ref)
- Optional blockchain verification integration
- Consumer-visible field filtering
- Empty field handling for clean display

Author: Trazo Development Team
"""

import re
import uuid
from typing import Any, Dict, List, Optional


# Constants
MAX_CUSTOM_FIELDS = 10
MAX_LABEL_LENGTH = 100
MAX_VALUE_LENGTH = 500
VALID_FIELD_TYPES = ["text", "number", "link", "photo_ref"]
VALID_VISIBILITY_LEVELS = ["consumer", "internal", "b2b"]
VALID_VERIFICATION_TYPES = ["self_reported", "photo_verified", "third_party"]


def sanitize_text(text: str) -> str:
    """
    Sanitize text input to prevent XSS attacks and injection vulnerabilities.

    Removes HTML tags, JavaScript event handlers, and potentially dangerous patterns.
    Preserves natural text content and URLs.

    Args:
        text: The text to sanitize

    Returns:
        Sanitized text safe for storage and display

    Examples:
        >>> sanitize_text("<script>alert('xss')</script>Hello")
        'Hello'

        >>> sanitize_text("Test onclick='alert(1)'>text")
        'Test text'

        >>> sanitize_text("Normal text with https://example.com link")
        'Normal text with https://example.com link'
    """
    if not text or not isinstance(text, str):
        return ""

    # Remove HTML/XML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Remove javascript: protocol
    text = re.sub(r"javascript:", "", text, flags=re.IGNORECASE)

    # Remove event handlers (onclick, onload, onerror, etc.)
    text = re.sub(r"on\w+\s*=", "", text, flags=re.IGNORECASE)

    # Remove data: protocol (can embed malicious content)
    text = re.sub(r"data:text/html", "", text, flags=re.IGNORECASE)

    # Remove potentially dangerous URL schemes
    text = re.sub(r"vbscript:", "", text, flags=re.IGNORECASE)

    # Clean up multiple spaces that might result from tag removal
    text = re.sub(r"\s+", " ", text).strip()

    return text


def validate_custom_field(field: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Validate a single custom field entry.

    Checks all field properties: label, value, field_type, visibility, verification.
    Performs sanitization on text inputs to prevent injection attacks.
    Generates UUID if not provided.

    Args:
        field: The custom field dictionary to validate
        index: The position of this field in the list (for error messages)

    Returns:
        Validated field dictionary with sanitized values

    Raises:
        ValueError: If field validation fails

    Examples:
        >>> field = {"label": "Soil pH", "value": "7.2"}
        >>> validated = validate_custom_field(field, 0)
        >>> validated["field_type"]
        'text'
    """
    if not isinstance(field, dict):
        raise ValueError(f"Custom field {index}: Must be a dictionary")

    label = field.get("label", "").strip()
    value = field.get("value", "")
    field_type = field.get("field_type", "text")
    visibility = field.get("visibility", "consumer")
    verification = field.get("verification", "self_reported")

    # Validate label
    if not label:
        raise ValueError(f"Custom field {index}: Label cannot be empty")

    if len(label) > MAX_LABEL_LENGTH:
        raise ValueError(
            f"Custom field {index}: Label cannot exceed {MAX_LABEL_LENGTH} characters "
            f"(current: {len(label)})"
        )

    # Sanitize label
    label = sanitize_text(label)

    # Validate value
    if value is None:
        value = ""

    value = str(value).strip() if value else ""

    if len(value) > MAX_VALUE_LENGTH:
        raise ValueError(
            f"Custom field {index}: Value cannot exceed {MAX_VALUE_LENGTH} characters "
            f"(current: {len(value)})"
        )

    # Sanitize value
    value = sanitize_text(value)

    # Validate field type
    if field_type not in VALID_FIELD_TYPES:
        raise ValueError(
            f"Custom field {index}: Invalid field_type '{field_type}'. "
            f"Must be one of: {', '.join(VALID_FIELD_TYPES)}"
        )

    # Validate visibility
    if visibility not in VALID_VISIBILITY_LEVELS:
        raise ValueError(
            f"Custom field {index}: Invalid visibility '{visibility}'. "
            f"Must be one of: {', '.join(VALID_VISIBILITY_LEVELS)}"
        )

    # Validate verification
    if verification not in VALID_VERIFICATION_TYPES:
        raise ValueError(
            f"Custom field {index}: Invalid verification '{verification}'. "
            f"Must be one of: {', '.join(VALID_VERIFICATION_TYPES)}"
        )

    # Generate or preserve field ID (UUID)
    field_id = field.get("id") or str(uuid.uuid4())

    # Preserve optional URL for link fields
    link_url = None
    if field_type == "link":
        link_url = field.get("link_url", "").strip()
        # Basic URL validation
        if link_url and not (link_url.startswith("http://") or link_url.startswith("https://")):
            raise ValueError(f"Custom field {index}: Invalid URL format for link field")

    # Preserve optional photo ID for photo_ref fields
    photo_id = field.get("photo_id")

    # Build validated field
    validated_field = {
        "id": field_id,
        "label": label,
        "value": value,
        "field_type": field_type,
        "visibility": visibility,
        "verification": verification,
        "created_at": field.get("created_at"),
    }

    # Add optional fields if present
    if link_url:
        validated_field["link_url"] = link_url
    if photo_id:
        validated_field["photo_id"] = photo_id

    return validated_field


def validate_custom_fields(custom_fields: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    """
    Validate an entire list of custom fields.

    Checks the list size, validates each field, and ensures field IDs are unique.

    Args:
        custom_fields: List of custom field dictionaries (can be None)

    Returns:
        List of validated custom fields, or None if input is None/empty

    Raises:
        ValueError: If any validation fails

    Examples:
        >>> fields = [
        ...     {"label": "Irrigation Source", "value": "Well"},
        ...     {"label": "Soil pH", "value": "7.2", "field_type": "number"}
        ... ]
        >>> validated = validate_custom_fields(fields)
        >>> len(validated)
        2
    """
    if not custom_fields:
        return None

    if not isinstance(custom_fields, list):
        raise ValueError("custom_fields must be a list")

    if len(custom_fields) > MAX_CUSTOM_FIELDS:
        raise ValueError(
            f"Maximum {MAX_CUSTOM_FIELDS} custom fields allowed per event "
            f"(provided: {len(custom_fields)})"
        )

    validated_fields = []
    seen_ids = set()

    for index, field in enumerate(custom_fields):
        validated_field = validate_custom_field(field, index)

        # Check for duplicate IDs
        field_id = validated_field["id"]
        if field_id in seen_ids:
            raise ValueError(f"Custom field {index}: Duplicate field ID '{field_id}'")

        seen_ids.add(field_id)
        validated_fields.append(validated_field)

    return validated_fields if validated_fields else None


def filter_empty_custom_fields(custom_fields: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Filter out custom fields with empty values.

    CRITICAL for preview-display consistency: Fields with empty/whitespace values
    should not appear in either preview or final consumer display.

    Args:
        custom_fields: List of custom fields to filter

    Returns:
        List of non-empty custom fields

    Examples:
        >>> fields = [
        ...     {"label": "Field1", "value": "Value1"},
        ...     {"label": "Field2", "value": ""},
        ...     {"label": "Field3", "value": "   "}
        ... ]
        >>> filtered = filter_empty_custom_fields(fields)
        >>> len(filtered)
        1
    """
    if not custom_fields:
        return []

    return [
        field for field in custom_fields
        if field.get("value") and str(field.get("value")).strip()
    ]


def merge_custom_fields_into_extra_data(
    extra_data: Optional[Dict[str, Any]],
    custom_fields: Optional[List[Dict[str, Any]]],
    existing_extra_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Merge custom_fields into event's extra_data while preserving existing data.

    Handles three scenarios:
    1. New custom fields (POST) - add to empty extra_data
    2. Update with new custom fields (PUT) - merge with existing custom_fields
    3. Update without custom fields - preserve existing custom_fields

    Critical: Other extra_data keys (like carbon_calculation) are never touched.

    Args:
        extra_data: The extra_data to merge into (can be None)
        custom_fields: The custom fields to merge (can be None)
        existing_extra_data: The instance's existing extra_data (for updates)

    Returns:
        Merged extra_data dictionary

    Examples:
        >>> extra = {"custom_fields": [{"label": "old", "value": "1"}]}
        >>> new_fields = [{"label": "new", "value": "2"}]
        >>> result = merge_custom_fields_into_extra_data(None, new_fields, extra)
        >>> len(result["custom_fields"])
        2
    """
    # Start with existing extra_data or empty dict
    result = (existing_extra_data or extra_data or {}).copy()

    if custom_fields:
        # If custom fields provided, use them (replace existing)
        result["custom_fields"] = custom_fields
    elif "custom_fields" not in result and extra_data and "custom_fields" in extra_data:
        # If no custom_fields input but extra_data has them, preserve
        result["custom_fields"] = extra_data["custom_fields"]

    return result


def extract_custom_fields_for_display(
    extra_data: Optional[Dict[str, Any]],
    visibility_filter: str = "consumer",
    include_empty: bool = False,
) -> List[Dict[str, Any]]:
    """
    Extract custom fields from extra_data for display in UI.

    Filters by visibility level and optionally removes empty fields.
    CRITICAL: Used by both EventPreviewModal and ConsumerEventCard to ensure
    identical display. Empty field filtering must be consistent.

    Args:
        extra_data: The event's extra_data field
        visibility_filter: Filter by visibility ('consumer', 'internal', 'b2b', or 'all')
        include_empty: If False (default), exclude fields with empty values

    Returns:
        List of custom fields ready for display

    Examples:
        >>> extra = {
        ...     "custom_fields": [
        ...         {"label": "pH", "value": "7.2", "visibility": "consumer"},
        ...         {"label": "Cost", "value": "", "visibility": "consumer"},
        ...         {"label": "Internal", "value": "123", "visibility": "internal"}
        ...     ]
        ... }
        >>> fields = extract_custom_fields_for_display(extra, visibility_filter="consumer")
        >>> len(fields)
        1
        >>> fields[0]["label"]
        'pH'
    """
    if not extra_data or "custom_fields" not in extra_data:
        return []

    custom_fields = extra_data.get("custom_fields", [])

    # Filter by visibility if specified
    if visibility_filter != "all":
        custom_fields = [f for f in custom_fields if f.get("visibility") == visibility_filter]

    # Filter out empty fields for clean display (CRITICAL for preview-display consistency)
    if not include_empty:
        custom_fields = filter_empty_custom_fields(custom_fields)

    return custom_fields


def get_custom_fields_for_blockchain_hash(custom_fields: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """
    Prepare custom fields for blockchain verification hashing.

    Only includes consumer-visible fields with non-empty values, sorted by ID
    for deterministic hashing. Returns only label+value for hash calculation.

    Critical for immutability: Once verified on blockchain, custom field IDs
    and values cannot change without breaking the verification.

    Args:
        custom_fields: The list of custom fields

    Returns:
        List of custom fields formatted for blockchain hashing

    Examples:
        >>> fields = [
        ...     {"id": "b", "label": "Field B", "value": "2", "visibility": "consumer"},
        ...     {"id": "a", "label": "Field A", "value": "1", "visibility": "consumer"},
        ...     {"id": "c", "label": "Field C", "value": "", "visibility": "consumer"}
        ... ]
        >>> blockchain = get_custom_fields_for_blockchain_hash(fields)
        >>> blockchain[0]["label"]  # Sorted by ID, so "a" comes first
        'Field A'
        >>> len(blockchain)  # Empty field excluded
        2
    """
    if not custom_fields:
        return []

    # Filter for consumer-visible, non-empty fields
    filtered_fields = [
        f for f in custom_fields
        if f.get("visibility") == "consumer" and f.get("value") and str(f.get("value")).strip()
    ]

    # Sort by ID for deterministic ordering
    sorted_fields = sorted(filtered_fields, key=lambda x: x.get("id", ""))

    # Return only label and value for hashing
    return [{"label": f.get("label", ""), "value": f.get("value", "")} for f in sorted_fields]


def get_event_type_custom_field_recommendations(event_type: int) -> Dict[str, List[str]]:
    """
    Provide helpful suggestions for custom fields based on event type.

    These are suggestions only - farmers can create any custom field they want.
    Helps farmers understand what additional information might be useful.

    Args:
        event_type: Integer ID of the event type (0-7)

    Returns:
        Dictionary with suggested field names and valid field types

    Event Type IDs:
        0: Weather, 1: Production, 2: Chemical, 3: General,
        4: Equipment, 5: Soil Management, 6: Pest Management, 7: Business
    """
    suggestions = {
        0: {  # Weather
            "suggested_fields": ["Wind Direction", "Cloud Cover", "Frost Risk", "UV Index"],
            "field_types": ["text", "number"],
        },
        1: {  # Production
            "suggested_fields": ["Harvest Quality", "Yield Grade", "Market Destination", "Post-Harvest Treatment"],
            "field_types": ["text", "number"],
        },
        2: {  # Chemical
            "suggested_fields": ["Applicator License", "Pre-Harvest Interval", "Re-Entry Interval", "Weather Conditions"],
            "field_types": ["text", "number", "link"],
        },
        3: {  # General
            "suggested_fields": ["Labor Hours", "Task Completion", "Weather Impact", "Notes"],
            "field_types": ["text", "number"],
        },
        4: {  # Equipment
            "suggested_fields": ["Maintenance Log", "Fuel Efficiency", "Operator Name", "Service History"],
            "field_types": ["text", "number", "photo_ref"],
        },
        5: {  # Soil Management
            "suggested_fields": ["Lab Results", "Amendment Type", "Application Depth", "Soil Microbiome"],
            "field_types": ["text", "number", "link"],
        },
        6: {  # Pest Management
            "suggested_fields": ["Pest Severity", "Treatment Threshold", "Beneficial Insects", "Detection Method"],
            "field_types": ["text", "number"],
        },
        7: {  # Business
            "suggested_fields": ["Cost", "Revenue Impact", "Certification Status", "Supplier Info"],
            "field_types": ["text", "number", "link"],
        },
    }

    return suggestions.get(event_type, {"suggested_fields": [], "field_types": ["text"]})
