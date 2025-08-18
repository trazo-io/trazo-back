"""
Privacy Service for GDPR-compliant data handling (2025 Standards)
Handles IP hashing, session fingerprinting, and consent management
"""

import hashlib
import hmac
import ipaddress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

if TYPE_CHECKING:
    from django.db.models import QuerySet


class PrivacyService:
    """2025 GDPR-compliant privacy management following EU regulations"""

    # Default data retention period (configurable via settings)
    DEFAULT_RETENTION_DAYS = getattr(settings, "SCAN_RETENTION_DAYS", 365)

    @staticmethod
    def get_client_ip(request) -> Optional[str]:
        """
        Extract real client IP considering proxies and load balancers
        Returns None if IP cannot be determined
        """
        # Check for forwarded IP (load balancers, CDNs)
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            # Take the first IP in the chain (original client)
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            # Direct connection
            ip = request.META.get("REMOTE_ADDR")

        # Validate IP address format
        if ip:
            try:
                ipaddress.ip_address(ip)
                return ip
            except ValueError:
                return None
        return None

    @staticmethod
    def hash_ip(ip_address: str) -> str:
        """
        Convert IP to privacy-safe hash for analytics
        Uses HMAC-SHA256 with secret key for security
        """
        if not ip_address:
            return ""

        # Get secret key from settings (should be in environment variables)
        secret_key = getattr(settings, "PRIVACY_HASH_KEY", settings.SECRET_KEY)

        # Create HMAC hash for security (prevents rainbow table attacks)
        return hmac.new(secret_key.encode("utf-8"), ip_address.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def generate_session_fingerprint(request) -> str:
        """
        Create privacy-safe browser fingerprint for session deduplication
        Uses stable browser characteristics without personal identification
        """
        components = []

        # User agent (truncated for privacy)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:150]
        if user_agent:
            components.append(user_agent)

        # Accept headers (language preference, encoding)
        accept_language = request.META.get("HTTP_ACCEPT_LANGUAGE", "")[:100]
        if accept_language:
            components.append(accept_language)

        accept_encoding = request.META.get("HTTP_ACCEPT_ENCODING", "")[:100]
        if accept_encoding:
            components.append(accept_encoding)

        # Screen resolution (if available via JS on frontend)
        # This would be passed via request data, not headers
        screen_resolution = request.GET.get("screen", "")
        if screen_resolution:
            components.append(screen_resolution[:20])

        # Create fingerprint hash
        fingerprint_data = "|".join(components)
        return hashlib.sha256(fingerprint_data.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_user_agent(user_agent: str) -> str:
        """
        Create privacy-safe hash of user agent for pattern analysis
        """
        if not user_agent:
            return ""

        # Truncate to prevent excessive storage and normalize
        normalized_ua = user_agent[:200].lower().strip()
        return hashlib.sha256(normalized_ua.encode("utf-8")).hexdigest()

    @staticmethod
    def calculate_retention_date(consent_given: bool = True) -> Optional[datetime]:
        """
        Calculate GDPR-compliant data retention period
        """
        if not consent_given:
            # Non-consented data should be deleted quickly (7 days)
            return timezone.now() + timedelta(days=7)

        # Consented data follows normal retention policy
        return timezone.now() + timedelta(days=PrivacyService.DEFAULT_RETENTION_DAYS)

    @staticmethod
    def extract_region_from_location(city: str, country: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract privacy-safe location info (region instead of city)
        Returns (country_code, region) tuple
        """
        # This is a simplified version - in production, you'd use a geolocation service
        # that can convert city -> region and country -> ISO code

        country_code = None
        region = None

        # Basic country to ISO code mapping (extend as needed)
        country_mapping = {
            "united states": "US",
            "usa": "US",
            "canada": "CA",
            "mexico": "MX",
            "united kingdom": "GB",
            "germany": "DE",
            "france": "FR",
            "spain": "ES",
            "italy": "IT",
            "brazil": "BR",
            "argentina": "AR",
            "colombia": "CO",
            "peru": "PE",
            "chile": "CL",
        }

        if country:
            country_normalized = country.lower().strip()
            country_code = country_mapping.get(country_normalized, country[:2].upper())

        # For regions, we could implement a city -> state/province mapping
        # For now, we'll use the city as region if it looks like a state/province
        if city:
            # This is very basic - in production, use proper geolocation service
            region = city

        return country_code, region

    @staticmethod
    def process_scan_consent(request, explicit_consent: Optional[bool] = None) -> Dict:
        """
        Process user consent according to GDPR requirements
        Returns all privacy-safe data for scan creation
        """
        # Get real IP address
        raw_ip = PrivacyService.get_client_ip(request)

        # Determine consent status with detailed logging
        consent_given = False

        print(f"🔍 Privacy service processing consent:")
        print(f"  - Explicit consent parameter: {explicit_consent}")
        print(f"  - Request cookies: {request.COOKIES}")
        print(f"  - trazo-analytics-consent cookie: {request.COOKIES.get('trazo-analytics-consent')}")

        # Check for explicit consent in request data (fallback for cookie domain issues)
        request_explicit_consent = None
        if hasattr(request, "data") and request.data:
            request_explicit_consent = request.data.get("explicit_consent")
            print(f"  - explicit_consent in request data: {request_explicit_consent}")

        # Check for consent header (additional fallback for cross-origin issues)
        header_consent = request.META.get("HTTP_X_ANALYTICS_CONSENT")
        print(f"  - X-Analytics-Consent header: {header_consent}")

        if explicit_consent is not None:
            consent_given = explicit_consent
            print(f"  - Using explicit consent parameter: {consent_given}")
        elif request_explicit_consent is not None:
            consent_given = bool(request_explicit_consent)
            print(f"  - Using explicit_consent from request data: {consent_given}")
        elif header_consent == "true":
            consent_given = True
            print(f"  - Using consent from X-Analytics-Consent header: {consent_given}")
        else:
            # Check for implicit consent via cookies/session
            cookie_consent = request.COOKIES.get("trazo-analytics-consent")
            consent_given = cookie_consent == "true"
            print(f"  - Cookie consent value: '{cookie_consent}' -> {consent_given}")

        print(f"  - Final consent_given: {consent_given}")

        # Process location data (from request data, not IP geolocation for privacy)
        country = request.data.get("country", "") if hasattr(request, "data") else ""
        city = request.data.get("city", "") if hasattr(request, "data") else ""

        country_code, region = PrivacyService.extract_region_from_location(city, country)

        return {
            # Privacy-safe processed data
            "ip_hash": PrivacyService.hash_ip(raw_ip) if raw_ip else "",
            "session_hash": PrivacyService.generate_session_fingerprint(request),
            "user_agent_hash": PrivacyService.hash_user_agent(request.META.get("HTTP_USER_AGENT", "")),
            # GDPR compliance
            "consent_given": consent_given,
            "consent_timestamp": timezone.now() if consent_given else None,
            "data_retention_until": PrivacyService.calculate_retention_date(consent_given),
            # Privacy-safe location (with defaults to avoid null constraint errors)
            "country_code": country_code or "XX",  # Default to 'XX' for unknown
            "region": region or "Unknown",  # Default to 'Unknown'
            # Clear legacy fields (will be migrated gradually)
            "ip_address": None,  # Don't store raw IP
            "city": None,  # Don't store exact city
            "country": None,  # Don't store full country name
        }

    @staticmethod
    def is_consent_required(request) -> bool:
        """
        Check if GDPR consent is required based on user location
        """
        # This is a simplified version - in production, you'd detect EU users
        # via IP geolocation or other means

        # For now, assume consent is always required (safest approach)
        return True

    @staticmethod
    def cache_session_data(session_hash: str, data: Dict, timeout: int = 900) -> None:
        """
        Cache session-related data for deduplication (15 minutes default)
        """
        cache_key = f"scan_session:{session_hash}"
        cache.set(cache_key, data, timeout)

    @staticmethod
    def get_cached_session_data(session_hash: str) -> Optional[Dict]:
        """
        Retrieve cached session data
        """
        cache_key = f"scan_session:{session_hash}"
        return cache.get(cache_key)


class GDPRComplianceService:
    """Service for GDPR-specific compliance operations"""

    @staticmethod
    def anonymize_scan(scan) -> bool:
        """
        Anonymize a scan according to GDPR requirements
        Returns True if successfully anonymized
        """
        try:
            # Clear all personally identifiable information
            scan.ip_hash = "ANONYMIZED"
            scan.session_hash = "ANONYMIZED"
            scan.user_agent_hash = "ANONYMIZED"
            scan.user = None
            scan.ip_address = None  # Clear legacy field
            scan.city = None  # Clear legacy field
            scan.country = None  # Clear legacy field

            # Keep aggregated analytics data
            # (region, country_code, scan_type, engagement_score are fine)

            scan.save()
            return True
        except Exception:
            return False

    @staticmethod
    def get_scans_for_cleanup() -> "QuerySet":
        """
        Get scans that need to be cleaned up according to retention policy
        """
        from ..models import HistoryScan

        now = timezone.now()

        return HistoryScan.objects.filter(data_retention_until__lt=now).exclude(ip_hash__in=["ANONYMIZED", ""])

    @staticmethod
    def get_non_consented_scans_for_deletion() -> "QuerySet":
        """
        Get non-consented scans older than 7 days for deletion
        """
        from ..models import HistoryScan

        cutoff_date = timezone.now() - timedelta(days=7)

        return HistoryScan.objects.filter(consent_given=False, date__lt=cutoff_date)
