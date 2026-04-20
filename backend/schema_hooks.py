"""
drf-spectacular preprocessing hooks for OpenAPI schema generation.

Used by SPECTACULAR_SETTINGS["PREPROCESSING_HOOKS"] to filter or modify
endpoints before schema generation.

Primary purpose (Phase 1: Event Field SSOT Migration):
Generate schema for the event-related endpoints that drive the frontend
field registry. Other apps can be added incrementally as their serializers
are cleaned up.
"""

# Path prefixes to INCLUDE in schema generation.
# For the Event Field SSOT migration, we need history/events endpoints to drive
# frontend TypeScript type generation for the registry. Other apps are
# excluded until their existing serializer issues (unrelated to this migration)
# are fixed.
INCLUDED_PATH_PREFIXES = (
    # History app: all event CRUD endpoints
    "/api/histories/",
    "/api/companies/",  # needed for history nested routes
    "/api/parcels/",  # needed for parcel-level event access
    "/api/productions/",  # needed for production-level event access
    "/api/events/",  # direct event endpoints if any
)

# Additional paths to exclude even if they match included prefixes.
# Used to skip known-broken endpoints with pre-existing serializer issues.
EXCLUDED_PATH_PREFIXES = (
    # IoT duplicate URL patterns — already registered via router in carbon/urls.py
    # These are legacy backward-compat routes that cause AttributeError
    # because they use .as_view({"get": "pending_events"}) syntax with @action methods.
    "/api/carbon/iot-devices/pending_events/",
    "/api/carbon/iot-devices/approve_event/",
    "/api/carbon/iot-devices/reject_event/",
    "/api/carbon/iot-devices/status/",
    "/api/carbon/iot-devices/simulate_data/",
)


def exclude_problematic_endpoints(endpoints):
    """
    Filter endpoints for Phase 1 Event Field SSOT schema generation.

    Includes only event-related endpoints (history, companies, parcels, productions)
    and excludes known-broken endpoints.

    Args:
        endpoints: List of (path, path_regex, method, callback) tuples.

    Returns:
        Filtered list of endpoints.
    """
    return [
        endpoint
        for endpoint in endpoints
        if any(endpoint[0].startswith(prefix) for prefix in INCLUDED_PATH_PREFIXES)
        and not any(endpoint[0].startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES)
    ]
