"""
Privacy Service for GDPR-compliant data handling (2025 Standards)
Handles IP hashing, session fingerprinting, and consent management
"""

import hashlib
import hmac
import ipaddress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Dict, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from backend.security.client_ip import client_ip

from .geoip_service import GeoIPService

if TYPE_CHECKING:
    from django.db.models import QuerySet


class PrivacyService:
    """2025 GDPR-compliant privacy management following EU regulations"""

    # Default data retention period (configurable via settings)
    DEFAULT_RETENTION_DAYS = getattr(settings, "SCAN_RETENTION_DAYS", 365)

    @staticmethod
    def get_client_ip(request) -> Optional[str]:
        """
        Extract the real client IP, preferring headers the client cannot forge.

        ⚠️ The left-most entry of X-Forwarded-For is ATTACKER-CONTROLLED. A proxy
        APPENDS to that header, so a request sent as

            X-Forwarded-For: 8.8.8.8

        arrives at the origin as "8.8.8.8, <real client>" and left-most picks the
        attacker's value. That was harmless while geolocation was broken; now that
        it resolves, a forged header would put a location of the caller's choosing
        on a farmer's dashboard, and would poison `ip_hash` — which deduplication
        and rate limiting both key on.

        The address comes from `backend.security.client_ip`, which reads DigitalOcean's
        `do-connecting-ip`. Measured 2026-10-17: the edge overwrites that header on every
        request, so a client-supplied value cannot survive, while X-Forwarded-For is passed
        through untouched.
        """
        ip = client_ip(request)

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

        # Screen resolution (measured by JS on the frontend; there is no header for it).
        #
        # Read from the request BODY first. Its own comment said "passed via request data", but the
        # lookup was `request.GET` — and `ProductDetail` sends `screen` in the POST body, so this
        # component was empty on every real scan. The fingerprint was therefore
        # user-agent + Accept-Language + Accept-Encoding alone: a DEVICE-CLASS signature, identical
        # for any two people on the same phone model, browser version and language. Dropping the
        # one client-measured component made same-device collisions markedly more likely, which
        # matters because a collision inside the dedup window marks a real second visitor's scan
        # as a duplicate. GET is kept as a fallback for any caller that passes it as a query param.
        screen_resolution = ""
        if hasattr(request, "data"):
            screen_resolution = str(request.data.get("screen", "") or "")
        if not screen_resolution:
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

    # `extract_region_from_location` lived here. It mapped a country NAME to an
    # ISO code via a 15-entry dict and fell back to `country[:2].upper()`, so
    # every country outside the list got a fabricated code — Portugal -> "PO",
    # Japan -> "JA". Those pass the `!= "XX"` placeholder check, so they
    # rendered as plausible-looking garbage rather than an honest em dash.
    # GeoIPService returns a real ISO 3166-1 alpha-2 code; nothing needs to guess.

    @staticmethod
    def process_scan_consent(request, explicit_consent: Optional[bool] = None) -> Dict:
        """
        Process user consent according to GDPR requirements.
        Consent is determined ONLY from the httpOnly-safe cookie set by the
        consent banner. The request body / custom header are NOT trusted
        because they can be forged by any client.

        When consent is not given, fingerprinting and geolocation are skipped
        entirely (GDPR Art. 5(1)(c) — data minimisation, ePrivacy Art. 5(3)).
        """
        # Determine consent from cookie only — never trust request body
        cookie_consent = request.COOKIES.get("trazo-analytics-consent")
        consent_given = cookie_consent == "true"

        if not consent_given:
            # No consent → return minimal data, no fingerprinting/geolocation
            return {
                "ip_hash": "",
                "session_hash": "",
                "user_agent_hash": "",
                "consent_given": False,
                "consent_timestamp": None,
                "data_retention_until": PrivacyService.calculate_retention_date(False),
                "country_code": "XX",
                "region": "Unknown",
                "ip_address": None,
                "city": None,
                "country": None,
            }

        # --- Consent granted: proceed with privacy-safe data collection ---

        raw_ip = PrivacyService.get_client_ip(request)

        # Geolocation from the local GeoLite2 database — only after consent is
        # confirmed. The request body is NOT consulted: `city`/`country` there
        # are attacker-controlled on a public unauthenticated endpoint, and a
        # farmer reading their own dashboard must not be shown a location a
        # scanner chose for them.
        country_code, region = None, None
        location = GeoIPService.lookup(raw_ip)
        if location:
            country_code = location.country_code
            # `region` is a state/province by design — see the field's help_text
            # ("State/region only (no city for privacy)"). The previous code
            # copied the city in here, contradicting the schema it shipped with.
            region = location.subdivision

        return {
            # Privacy-safe processed data (only computed after consent)
            "ip_hash": PrivacyService.hash_ip(raw_ip) if raw_ip else "",
            "session_hash": PrivacyService.generate_session_fingerprint(request),
            "user_agent_hash": PrivacyService.hash_user_agent(request.META.get("HTTP_USER_AGENT", "")),
            # GDPR compliance
            "consent_given": True,
            "consent_timestamp": timezone.now(),
            "data_retention_until": PrivacyService.calculate_retention_date(True),
            # Privacy-safe location (with defaults to avoid null constraint errors)
            "country_code": country_code or "XX",
            "region": region or "Unknown",
            # Clear legacy fields
            "ip_address": None,
            "city": None,
            "country": None,
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
