"""
Security permissions for Trazo carbon endpoints.
Implements rate limiting and basic security for public QR code access.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from rest_framework import permissions
from rest_framework.exceptions import Throttled

from backend.security.client_ip import client_ip

logger = logging.getLogger(__name__)

# Rate limit configuration - can be overridden in settings
# Production: 300 requests/hour (5 per minute) - reasonable for consumer QR pages
# Development: No limit (DEBUG=True bypasses rate limiting)
QR_RATE_LIMIT_REQUESTS = getattr(settings, "QR_RATE_LIMIT_REQUESTS", 300)
QR_RATE_LIMIT_WINDOW = getattr(settings, "QR_RATE_LIMIT_WINDOW", 3600)  # 1 hour in seconds


class PublicQRPermission(permissions.BasePermission):
    """
    Custom permission for public QR code endpoints.
    Implements rate limiting and basic security without breaking QR functionality.

    IMPORTANT:
    - Authenticated users bypass rate limiting (they have their own throttles)
    - DEBUG mode bypasses rate limiting for development convenience
    - Rate limits are configurable via settings.QR_RATE_LIMIT_REQUESTS
    """

    def has_permission(self, request, view):
        # CRITICAL: Authenticated users bypass public rate limiting
        # They're already subject to standard authentication throttles
        # This allows producer dashboards to use these endpoints freely
        if request.user and request.user.is_authenticated:
            logger.debug(f"✅ PublicQRPermission: Authenticated user {request.user.id} - bypassing rate limit")
            return True

        # DEBUG mode: Skip rate limiting for development convenience
        if settings.DEBUG:
            logger.debug("✅ PublicQRPermission: DEBUG mode - bypassing rate limit")
            return True

        # Only allow GET requests for public (unauthenticated) endpoints
        if request.method != "GET":
            logger.warning(
                f"🚨 PublicQRPermission: Non-GET request {request.method} blocked from {self._get_client_ip(request)}"
            )
            return False

        # Implement rate limiting for unauthenticated requests only
        if not self._check_rate_limit(request):
            logger.warning(f"🚨 PublicQRPermission: Rate limit exceeded for {self._get_client_ip(request)}")
            raise Throttled(detail="Rate limit exceeded for public QR access")

        # Basic user agent validation (block obvious bots)
        user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
        if self._is_suspicious_user_agent(user_agent):
            logger.warning(f"🚨 PublicQRPermission: Suspicious user agent blocked: {user_agent[:100]}")
            return False

        return True

    def _get_client_ip(self, request):
        """Get the real client IP address, handling proxies."""
        return client_ip(request)

    def _check_rate_limit(self, request):
        """
        Implement rate limiting: configurable requests per hour per IP.
        Default: 300 requests/hour (5 per minute) - reasonable for consumer QR pages.
        A single QR page load may trigger 3-5 API calls, so 60/hour was too restrictive.
        """
        ip = self._get_client_ip(request)
        cache_key = f"qr_rate_limit:{ip}"

        # Get current request count
        current_count = cache.get(cache_key, 0)

        # Rate limit check using configurable values
        if current_count >= QR_RATE_LIMIT_REQUESTS:
            return False

        # Increment counter with configurable expiry window
        cache.set(cache_key, current_count + 1, QR_RATE_LIMIT_WINDOW)
        return True

    def _is_suspicious_user_agent(self, user_agent):
        """
        Basic bot detection - block obvious scraping attempts while allowing legitimate browsers.
        """
        if not user_agent or len(user_agent) < 10:
            return True

        # Block known scraping/bot user agents
        suspicious_patterns = [
            "bot",
            "crawler",
            "spider",
            "scraper",
            "wget",
            "curl",
            "python-requests",
            "httpx",
            "axios",
            "scrapy",
        ]

        # Allow legitimate mobile browsers and QR scanner apps
        legitimate_patterns = [
            "mozilla",
            "webkit",
            "chrome",
            "safari",
            "firefox",
            "mobile",
            "android",
            "iphone",
            "ipad",
        ]

        # If it contains suspicious patterns and no legitimate patterns, block it
        has_suspicious = any(pattern in user_agent for pattern in suspicious_patterns)
        has_legitimate = any(pattern in user_agent for pattern in legitimate_patterns)

        return has_suspicious and not has_legitimate


# SecurePublicDataPermission was removed (2026-08-02).
#
# It guarded `obj.is_public` and `obj.company`, but its only consumer served `History`
# objects, which carry NEITHER attribute (the fields are `published` and
# `parcel.establishment.company`). Both `hasattr` checks were therefore always False and
# the method returned True unconditionally. DRF also never calls `has_object_permission`
# for list actions, so the list route had no object-level protection at all.
#
# The result: `GET /api/carbon/productions-flat/` served every tenant's productions —
# including unpublished drafts — plus their self-graded `transparency_score`, to
# unauthenticated callers. That endpoint is now `IsAuthenticated` and company-scoped
# (see `CarbonProductionViewSet` in carbon/views.py).
