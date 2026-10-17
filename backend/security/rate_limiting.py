"""
Enhanced rate limiting and DDoS protection for Trazo
Provides advanced throttling and security measures
"""

import hashlib
import logging
import time
from typing import Dict, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from rest_framework.throttling import BaseThrottle
from rest_framework.views import exception_handler

from backend.security.client_ip import client_ip, throttle_ident

logger = logging.getLogger(__name__)


class IPBasedThrottle(BaseThrottle):
    """
    Enhanced IP-based throttling with progressive penalties
    """

    def __init__(self):
        self.cache_format = "throttle_%(scope)s_%(ident)s"
        self.timer = time.time

    def get_cache_key(self, request, view):
        """
        Generate cache key based on IP and endpoint
        """
        ident = self.get_ident(request)
        scope = getattr(view, "throttle_scope", "default")
        return self.cache_format % {"scope": scope, "ident": ident}

    def get_ident(self, request):
        """
        The address to count against (see backend/security/client_ip.py)
        """
        return throttle_ident(request)

    def allow_request(self, request, view):
        """
        Enhanced request allowance with progressive penalties
        """
        cache_key = self.get_cache_key(request, view)
        if cache_key is None:
            return True

        # Get current request data
        now = self.timer()
        history = cache.get(cache_key, [])

        # Clean old entries (older than 1 hour)
        cutoff = now - 3600
        history = [entry for entry in history if entry > cutoff]

        # Get rate limits based on endpoint sensitivity
        rate_limits = self.get_rate_limits(request, view)

        # Check each time window
        for window_seconds, max_requests in rate_limits.items():
            window_cutoff = now - window_seconds
            recent_requests = [entry for entry in history if entry > window_cutoff]

            if len(recent_requests) >= max_requests:
                logger.warning(
                    f"Rate limit exceeded for IP {self.get_ident(request)} "
                    f"on {request.path}: {len(recent_requests)}/{max_requests} "
                    f"in {window_seconds}s window"
                )
                return False

        # Add current request
        history.append(now)
        cache.set(cache_key, history, 3600)  # Cache for 1 hour

        return True

    def get_rate_limits(self, request, view) -> Dict[int, int]:
        """
        Get rate limits based on endpoint type and user status

        Returns:
            Dict mapping window_seconds to max_requests
        """
        # Default limits
        limits = {
            60: 30,  # 30 requests per minute
            3600: 300,  # 300 requests per hour
        }

        # Authentication endpoints - stricter limits
        if any(path in request.path for path in ["/login", "/signup", "/password"]):
            limits = {
                60: 5,  # 5 attempts per minute
                3600: 20,  # 20 attempts per hour
                86400: 50,  # 50 attempts per day
            }

        # API key sensitive endpoints
        elif any(path in request.path for path in ["/carbon/", "/blockchain/"]):
            limits = {
                60: 10,  # 10 requests per minute
                3600: 100,  # 100 requests per hour
            }

        # Public consumer endpoints - more permissive
        elif "/consumer/" in request.path or "/qr/" in request.path:
            limits = {
                60: 60,  # 60 requests per minute (QR scanning)
                3600: 1000,  # 1000 requests per hour
            }

        # Authenticated users get higher limits
        if hasattr(request, "user") and request.user.is_authenticated:
            for window in limits:
                limits[window] *= 2  # Double the limits for authenticated users

        return limits

    def wait(self):
        """
        Return recommended wait time
        """
        return 60  # Wait 1 minute


class BruteForceProtection:
    """
    Protection against brute force attacks on sensitive endpoints
    """

    def __init__(self):
        self.failed_attempts_cache_format = "failed_attempts_%s"
        self.blocked_ips_cache_format = "blocked_ip_%s"

    def record_failed_attempt(self, ip_address: str, endpoint: str):
        """
        Record a failed authentication attempt
        """
        cache_key = self.failed_attempts_cache_format % hashlib.md5(f"{ip_address}:{endpoint}".encode()).hexdigest()

        attempts = cache.get(cache_key, 0)
        attempts += 1

        # Progressive blocking times
        if attempts >= 10:
            block_time = 3600  # 1 hour
        elif attempts >= 5:
            block_time = 300  # 5 minutes
        else:
            block_time = 0

        cache.set(cache_key, attempts, 3600)  # Track for 1 hour

        if block_time > 0:
            self.block_ip(ip_address, block_time)
            logger.warning(f"IP {ip_address} blocked for {block_time}s after {attempts} failed attempts on {endpoint}")

    def block_ip(self, ip_address: str, duration: int):
        """
        Block an IP address for a specified duration
        """
        cache_key = self.blocked_ips_cache_format % hashlib.md5(ip_address.encode()).hexdigest()
        cache.set(cache_key, time.time(), duration)

    def is_ip_blocked(self, ip_address: str) -> bool:
        """
        Check if an IP address is currently blocked
        """
        cache_key = self.blocked_ips_cache_format % hashlib.md5(ip_address.encode()).hexdigest()
        return cache.get(cache_key) is not None

    def clear_failed_attempts(self, ip_address: str, endpoint: str):
        """
        Clear failed attempts for successful authentication
        """
        cache_key = self.failed_attempts_cache_format % hashlib.md5(f"{ip_address}:{endpoint}".encode()).hexdigest()
        cache.delete(cache_key)


class DDoSProtection:
    """
    DDoS protection with pattern detection
    """

    def __init__(self):
        self.request_pattern_cache = "ddos_pattern_%s"
        self.suspicious_ips_cache = "suspicious_ips"

    def analyze_request_pattern(self, request) -> Tuple[bool, str]:
        """
        Analyze request patterns for DDoS indicators

        Returns:
            Tuple of (is_suspicious, reason)
        """
        ip = self.get_client_ip(request)
        now = time.time()

        # Track request patterns
        cache_key = self.request_pattern_cache % hashlib.md5(ip.encode()).hexdigest()
        cached_data = cache.get(cache_key, {"requests": [], "endpoints": {}, "user_agents": []})

        # Convert user_agents back to set if it's a list (from cache)
        pattern_data = cached_data.copy()
        if isinstance(pattern_data["user_agents"], list):
            pattern_data["user_agents"] = set(pattern_data["user_agents"])
        elif not isinstance(pattern_data["user_agents"], set):
            pattern_data["user_agents"] = set()

        # Add current request
        pattern_data["requests"].append(now)
        pattern_data["endpoints"][request.path] = pattern_data["endpoints"].get(request.path, 0) + 1
        pattern_data["user_agents"].add(request.META.get("HTTP_USER_AGENT", ""))

        # Clean old requests (last 5 minutes)
        cutoff = now - 300
        pattern_data["requests"] = [req for req in pattern_data["requests"] if req > cutoff]

        # Analyze patterns
        suspicious_indicators = []

        # Too many requests in short time
        if len(pattern_data["requests"]) > 100:  # 100 requests in 5 minutes
            suspicious_indicators.append("high_frequency")

        # Targeting single endpoint repeatedly
        for endpoint, count in pattern_data["endpoints"].items():
            if count > 50:  # 50 requests to same endpoint
                suspicious_indicators.append(f"endpoint_targeting:{endpoint}")

        # Multiple user agents from same IP (botnet indicator)
        if len(pattern_data["user_agents"]) > 10:
            suspicious_indicators.append("multiple_user_agents")

        # No user agent (bot indicator)
        if not request.META.get("HTTP_USER_AGENT"):
            suspicious_indicators.append("no_user_agent")

        # Update cache (convert set to list for JSON serialization)
        cacheable_data = pattern_data.copy()
        cacheable_data["user_agents"] = list(pattern_data["user_agents"])
        cache.set(cache_key, cacheable_data, 300)  # 5 minutes

        is_suspicious = len(suspicious_indicators) >= 2
        reason = ", ".join(suspicious_indicators) if suspicious_indicators else "clean"

        if is_suspicious:
            self.mark_ip_suspicious(ip, reason)
            logger.warning(f"Suspicious DDoS pattern detected from IP {ip}: {reason}")

        return is_suspicious, reason

    def mark_ip_suspicious(self, ip: str, reason: str):
        """
        Mark an IP as suspicious
        """
        suspicious_ips = cache.get(self.suspicious_ips_cache, {})
        suspicious_ips[ip] = {"timestamp": time.time(), "reason": reason}
        cache.set(self.suspicious_ips_cache, suspicious_ips, 3600)  # 1 hour

    def get_client_ip(self, request):
        """
        Get the real client IP address
        """
        return client_ip(request)


class SecurityMiddleware:
    """
    Security middleware for rate limiting and DDoS protection
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.brute_force_protection = BruteForceProtection()
        self.ddos_protection = DDoSProtection()
        self.ip_throttle = IPBasedThrottle()

    def __call__(self, request):
        try:
            # Check if IP is blocked
            ip = self.ddos_protection.get_client_ip(request)
            if self.brute_force_protection.is_ip_blocked(ip):
                logger.warning(f"Blocked IP {ip} attempted access to {request.path}")
                return HttpResponse("Access denied", status=429)

            # DDoS pattern analysis
            is_suspicious, reason = self.ddos_protection.analyze_request_pattern(request)
            if is_suspicious and "high_frequency" in reason:
                logger.warning(f"DDoS attack detected from IP {ip}, blocking")
                self.brute_force_protection.block_ip(ip, 1800)  # Block for 30 minutes
                return HttpResponse("Rate limit exceeded", status=429)
        except Exception as e:
            # If cache/redis unavailable, allow request through (fail-open)
            logger.debug(f"Security middleware error (allowing request): {e}")

        response = self.get_response(request)

        try:
            # Record failed authentication attempts
            ip = self.ddos_protection.get_client_ip(request)
            if response.status_code in [401, 403] and any(
                path in request.path for path in ["/login", "/signup", "/password"]
            ):
                self.brute_force_protection.record_failed_attempt(ip, request.path)
            elif response.status_code == 200 and any(path in request.path for path in ["/login"]):
                # Clear failed attempts on successful login
                self.brute_force_protection.clear_failed_attempts(ip, request.path)
        except Exception:
            pass  # Cache unavailable, skip tracking

        return response


# Enhanced throttle rates for production
ENHANCED_THROTTLE_RATES = {
    "anon": "50/hour",  # Reduced from 100/hour
    "user": "500/hour",  # Reduced from 1000/hour
    "login": "3/minute",  # Reduced from 5/minute
    "signup": "2/minute",  # New rate for signup
    "password_reset": "3/hour",  # New rate for password reset
    "carbon_calculation": "100/hour",  # Reduced from 200/hour
    "api_sensitive": "30/hour",  # Reduced from 50/hour
    "qr_scan": "300/hour",  # New rate for QR scanning
    "blockchain": "20/hour",  # New rate for blockchain operations
}


def get_enhanced_throttle_rates():
    """
    Get enhanced throttle rates based on environment
    """
    if getattr(settings, "ENVIRONMENT", "development") == "production":
        return ENHANCED_THROTTLE_RATES
    else:
        # More permissive rates for development
        return {
            "anon": "200/hour",
            "user": "2000/hour",
            "login": "10/minute",
            "signup": "5/minute",
            "password_reset": "10/hour",
            "carbon_calculation": "400/hour",
            "api_sensitive": "100/hour",
            "qr_scan": "1000/hour",
            "blockchain": "50/hour",
        }
