"""
Enhanced DDoS Protection and API Rate Limiting for Trazo
Provides enterprise-grade protection against DDoS attacks and abuse
"""

import hashlib
import ipaddress
import json
import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.utils.deprecation import MiddlewareMixin
from django.views.decorators.cache import cache_page

logger = logging.getLogger(__name__)


class AdvancedDDoSProtection:
    """
    Enterprise-grade DDoS protection with machine learning-inspired detection
    """

    def __init__(self):
        self.cache_prefix = "ddos_advanced"
        self.whitelist_cache = f"{self.cache_prefix}_whitelist"
        self.blacklist_cache = f"{self.cache_prefix}_blacklist"
        self.threat_intel_cache = f"{self.cache_prefix}_threat_intel"

        # Known good IP ranges (CDNs, legitimate services)
        self.known_good_ranges = [
            "192.168.0.0/16",  # Private networks
            "10.0.0.0/8",  # Private networks
            "172.16.0.0/12",  # Private networks
            "127.0.0.0/8",  # Localhost
        ]

        # Malicious IP detection patterns
        self.threat_indicators = {
            "tor_exit_nodes": [],  # Would be populated from threat intel feeds
            "known_botnets": [],  # Would be populated from threat intel feeds
            "suspicious_patterns": {
                "rapid_requests": 100,  # Requests per minute
                "endpoint_scanning": 20,  # Different endpoints hit
                "user_agent_rotation": 10,  # Different user agents
                "country_hopping": 5,  # Different countries
            },
        }

    def get_client_ip(self, request) -> str:
        """Get the real client IP address with proxy support"""
        # Check for X-Forwarded-For header (load balancers, proxies)
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            # Take the first IP in the chain (original client)
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            # Direct connection
            ip = request.META.get("REMOTE_ADDR", "127.0.0.1")

        # Additional headers to check
        if not ip or ip == "127.0.0.1":
            # Check CloudFlare headers
            ip = request.META.get("HTTP_CF_CONNECTING_IP", ip)
            # Check other common proxy headers
            ip = request.META.get("HTTP_X_REAL_IP", ip)
            ip = request.META.get("HTTP_X_CLIENT_IP", ip)

        return ip

    def get_geolocation_info(self, ip: str) -> Dict:
        """Get geolocation information for IP (simplified implementation)"""
        # In production, this would use a geolocation service like MaxMind
        cache_key = f"geo_{hashlib.md5(ip.encode()).hexdigest()}"
        geo_info = cache.get(cache_key)

        if not geo_info:
            # Simplified geolocation (would use real service in production)
            geo_info = {
                "country": "Unknown",
                "region": "Unknown",
                "city": "Unknown",
                "asn": "Unknown",
                "is_tor": False,
                "is_proxy": False,
                "threat_score": 0,
            }
            cache.set(cache_key, geo_info, 3600)  # Cache for 1 hour

        return geo_info

    def analyze_behavioral_patterns(self, request) -> Tuple[int, List[str]]:
        """
        Analyze request patterns for suspicious behavior
        Returns: (threat_score, indicators_list)
        """
        ip = self.get_client_ip(request)
        now = time.time()
        threat_score = 0
        indicators = []

        # Get request history for this IP
        history_key = f"{self.cache_prefix}_history_{hashlib.md5(ip.encode()).hexdigest()}"
        history = cache.get(
            history_key,
            {
                "requests": [],
                "endpoints": defaultdict(int),
                "user_agents": set(),
                "referrers": set(),
                "countries": set(),
                "first_seen": now,
            },
        )

        # Convert sets back from cache (JSON serialization converts to lists)
        if isinstance(history["user_agents"], list):
            history["user_agents"] = set(history["user_agents"])
        if isinstance(history["referrers"], list):
            history["referrers"] = set(history["referrers"])
        if isinstance(history["countries"], list):
            history["countries"] = set(history["countries"])

        # Clean old requests (last 5 minutes)
        cutoff = now - 300
        history["requests"] = [req_time for req_time in history["requests"] if req_time > cutoff]

        # Add current request
        history["requests"].append(now)
        history["endpoints"][request.path] += 1
        history["user_agents"].add(request.META.get("HTTP_USER_AGENT", ""))
        history["referrers"].add(request.META.get("HTTP_REFERER", ""))

        # Geolocation analysis
        geo_info = self.get_geolocation_info(ip)
        history["countries"].add(geo_info["country"])

        # Analyze patterns
        request_rate = len(history["requests"]) / 5.0  # Requests per minute

        # 1. High request rate
        if request_rate > self.threat_indicators["suspicious_patterns"]["rapid_requests"]:
            threat_score += 30
            indicators.append(f"high_request_rate_{request_rate:.1f}/min")

        # 2. Endpoint scanning behavior
        if len(history["endpoints"]) > self.threat_indicators["suspicious_patterns"]["endpoint_scanning"]:
            threat_score += 25
            indicators.append(f"endpoint_scanning_{len(history['endpoints'])}_endpoints")

        # 3. User agent rotation (bot behavior)
        if len(history["user_agents"]) > self.threat_indicators["suspicious_patterns"]["user_agent_rotation"]:
            threat_score += 20
            indicators.append(f"user_agent_rotation_{len(history['user_agents'])}_agents")

        # 4. Country hopping (VPN/proxy behavior)
        if len(history["countries"]) > self.threat_indicators["suspicious_patterns"]["country_hopping"]:
            threat_score += 15
            indicators.append(f"country_hopping_{len(history['countries'])}_countries")

        # 5. No referrer on multiple requests (automated behavior)
        if len(history["requests"]) > 10 and not any(ref for ref in history["referrers"] if ref):
            threat_score += 10
            indicators.append("no_referrer_pattern")

        # 6. Known threat patterns
        user_agent = request.META.get("HTTP_USER_AGENT", "").lower()
        suspicious_ua_patterns = [
            "bot",
            "crawler",
            "spider",
            "scraper",
            "scanner",
            "sqlmap",
            "nikto",
            "nmap",
            "masscan",
            "zap",
        ]
        if any(pattern in user_agent for pattern in suspicious_ua_patterns):
            threat_score += 15
            indicators.append(f"suspicious_user_agent_{user_agent[:50]}")

        # 7. Empty or suspicious user agent
        if not user_agent or len(user_agent) < 10:
            threat_score += 10
            indicators.append("empty_or_short_user_agent")

        # 8. Geolocation-based scoring
        threat_score += geo_info.get("threat_score", 0)
        if geo_info.get("is_tor"):
            threat_score += 20
            indicators.append("tor_exit_node")
        if geo_info.get("is_proxy"):
            threat_score += 10
            indicators.append("proxy_connection")

        # Update cache (convert sets to lists for JSON serialization)
        cacheable_history = history.copy()
        cacheable_history["user_agents"] = list(history["user_agents"])
        cacheable_history["referrers"] = list(history["referrers"])
        cacheable_history["countries"] = list(history["countries"])
        cache.set(history_key, cacheable_history, 600)  # 10 minutes

        return threat_score, indicators

    def is_ip_whitelisted(self, ip: str) -> bool:
        """Check if IP is whitelisted"""
        # Check cache first
        whitelist = cache.get(self.whitelist_cache, set())
        if ip in whitelist:
            return True

        # Check if IP is in known good ranges
        try:
            ip_obj = ipaddress.ip_address(ip)
            for cidr in self.known_good_ranges:
                if ip_obj in ipaddress.ip_network(cidr):
                    return True
        except (ipaddress.AddressValueError, ValueError):
            pass

        return False

    def is_ip_blacklisted(self, ip: str) -> bool:
        """Check if IP is blacklisted"""
        blacklist = cache.get(self.blacklist_cache, set())
        return ip in blacklist

    def add_to_blacklist(self, ip: str, duration: int = 3600, reason: str = ""):
        """Add IP to blacklist for specified duration"""
        blacklist = cache.get(self.blacklist_cache, set())
        blacklist.add(ip)
        cache.set(self.blacklist_cache, blacklist, duration)

        # Log the blacklisting
        logger.warning(f"IP {ip} blacklisted for {duration}s: {reason}")

    def should_block_request(self, request) -> Tuple[bool, str, int]:
        """
        Determine if request should be blocked
        Returns: (should_block, reason, threat_score)
        """
        ip = self.get_client_ip(request)

        # Check whitelist first
        if self.is_ip_whitelisted(ip):
            return False, "whitelisted", 0

        # Check blacklist
        if self.is_ip_blacklisted(ip):
            return True, "blacklisted", 100

        # Analyze behavioral patterns
        threat_score, indicators = self.analyze_behavioral_patterns(request)

        # Determine action based on threat score
        if threat_score >= 70:
            # High threat - block immediately
            self.add_to_blacklist(ip, 3600, f"High threat score: {threat_score}")
            return True, f"high_threat_score_{threat_score}", threat_score
        elif threat_score >= 50:
            # Medium threat - block temporarily
            self.add_to_blacklist(ip, 300, f"Medium threat score: {threat_score}")
            return True, f"medium_threat_score_{threat_score}", threat_score
        elif threat_score >= 30:
            # Low threat - rate limit more aggressively
            return False, f"low_threat_score_{threat_score}", threat_score

        return False, "clean", threat_score


class EnhancedRateLimitMiddleware(MiddlewareMixin):
    """
    Enhanced rate limiting middleware with adaptive protection
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        self.ddos_protection = AdvancedDDoSProtection()
        self.rate_limits = self.get_rate_limits()

    def get_rate_limits(self) -> Dict:
        """Get rate limits based on environment and endpoint sensitivity"""
        base_limits = {
            # Authentication endpoints (most restrictive)
            "auth": {
                "window": 60,  # 1 minute
                "max_requests": 5,  # 5 attempts per minute
                "burst_limit": 10,  # Allow burst of 10
                "penalty_factor": 2,  # Double penalty on violations
            },
            # API endpoints (moderate)
            "api": {
                "window": 60,  # 1 minute
                "max_requests": 30,  # 30 requests per minute
                "burst_limit": 50,  # Allow burst of 50
                "penalty_factor": 1.5,  # 1.5x penalty on violations
            },
            # Carbon calculation endpoints (business critical)
            "carbon": {
                "window": 60,  # 1 minute
                "max_requests": 20,  # 20 calculations per minute
                "burst_limit": 30,  # Allow burst of 30
                "penalty_factor": 1.2,  # Moderate penalty
            },
            # Blockchain endpoints (expensive operations)
            "blockchain": {
                "window": 300,  # 5 minutes
                "max_requests": 10,  # 10 operations per 5 minutes
                "burst_limit": 15,  # Allow burst of 15
                "penalty_factor": 3,  # High penalty (expensive ops)
            },
            # QR/Consumer endpoints (high volume expected)
            "consumer": {
                "window": 60,  # 1 minute
                "max_requests": 100,  # 100 requests per minute
                "burst_limit": 200,  # Allow burst of 200
                "penalty_factor": 1,  # No penalty increase
            },
            # Default for all other endpoints
            "default": {
                "window": 60,  # 1 minute
                "max_requests": 60,  # 60 requests per minute
                "burst_limit": 100,  # Allow burst of 100
                "penalty_factor": 1.5,  # Standard penalty
            },
        }

        # Adjust for development environment
        if getattr(settings, "DEBUG", False):
            for category in base_limits:
                base_limits[category]["max_requests"] *= 5  # 5x more permissive
                base_limits[category]["burst_limit"] *= 5

        return base_limits

    def get_endpoint_category(self, path: str) -> str:
        """Categorize endpoint based on path"""
        path_lower = path.lower()

        if any(auth_path in path_lower for auth_path in ["/login", "/signup", "/password", "/auth/"]):
            return "auth"
        elif "/carbon/" in path_lower:
            return "carbon"
        elif "/blockchain/" in path_lower:
            return "blockchain"
        elif any(consumer_path in path_lower for consumer_path in ["/qr/", "/consumer/", "/public/"]):
            return "consumer"
        elif "/api/" in path_lower:
            return "api"
        else:
            return "default"

    def check_rate_limit(self, request, threat_score: int = 0) -> Tuple[bool, Dict]:
        """
        Check if request exceeds rate limits
        Returns: (is_allowed, limit_info)
        """
        ip = self.ddos_protection.get_client_ip(request)
        endpoint_category = self.get_endpoint_category(request.path)
        limits = self.rate_limits[endpoint_category]

        # Adjust limits based on threat score
        adjusted_limits = limits.copy()
        if threat_score >= 30:
            # Reduce limits for suspicious IPs
            reduction_factor = 1 + (threat_score / 100)
            adjusted_limits["max_requests"] = int(limits["max_requests"] / reduction_factor)
            adjusted_limits["burst_limit"] = int(limits["burst_limit"] / reduction_factor)

        # Authenticated users get higher limits
        if hasattr(request, "user") and request.user.is_authenticated:
            adjusted_limits["max_requests"] = int(adjusted_limits["max_requests"] * 1.5)
            adjusted_limits["burst_limit"] = int(adjusted_limits["burst_limit"] * 1.5)

        # Cache key for this IP and endpoint category
        cache_key = f"rate_limit_{endpoint_category}_{hashlib.md5(ip.encode()).hexdigest()}"

        now = time.time()
        window_start = now - adjusted_limits["window"]

        # Get request history
        request_times = cache.get(cache_key, [])

        # Remove old requests outside the window
        request_times = [req_time for req_time in request_times if req_time > window_start]

        # Check rate limits
        current_requests = len(request_times)
        max_allowed = adjusted_limits["max_requests"]
        burst_allowed = adjusted_limits["burst_limit"]

        # Determine if request is allowed
        is_allowed = current_requests < max_allowed
        is_burst_allowed = current_requests < burst_allowed

        # If within burst limit but over normal limit, allow but log
        if not is_allowed and is_burst_allowed:
            is_allowed = True
            logger.info(f"Burst limit used for IP {ip} on {endpoint_category}: {current_requests}/{burst_allowed}")

        # Add current request if allowed
        if is_allowed:
            request_times.append(now)
            cache.set(cache_key, request_times, adjusted_limits["window"] * 2)

        # Prepare limit info for headers
        limit_info = {
            "limit": max_allowed,
            "remaining": max(0, max_allowed - current_requests - (1 if is_allowed else 0)),
            "reset": int(window_start + adjusted_limits["window"]),
            "window": adjusted_limits["window"],
            "category": endpoint_category,
        }

        return is_allowed, limit_info

    def process_request(self, request):
        """Process request for DDoS protection and rate limiting"""
        try:
            # Check for DDoS patterns
            should_block, reason, threat_score = self.ddos_protection.should_block_request(request)

            if should_block:
                logger.warning(f"Request blocked from {self.ddos_protection.get_client_ip(request)}: {reason}")
                return JsonResponse(
                    {
                        "error": "Request blocked",
                        "reason": "Security policy violation",
                        "retry_after": 300,
                    },
                    status=429,
                )

            # Check rate limits
            is_allowed, limit_info = self.check_rate_limit(request, threat_score)

            if not is_allowed:
                logger.warning(
                    f"Rate limit exceeded for {self.ddos_protection.get_client_ip(request)} "
                    f"on {limit_info['category']}: {limit_info['limit'] - limit_info['remaining']}/{limit_info['limit']}"
                )

                response = JsonResponse(
                    {
                        "error": "Rate limit exceeded",
                        "limit": limit_info["limit"],
                        "window": limit_info["window"],
                        "retry_after": limit_info["reset"] - int(time.time()),
                    },
                    status=429,
                )

                # Add rate limit headers
                response["X-RateLimit-Limit"] = str(limit_info["limit"])
                response["X-RateLimit-Remaining"] = "0"
                response["X-RateLimit-Reset"] = str(limit_info["reset"])
                response["X-RateLimit-Window"] = str(limit_info["window"])
                response["Retry-After"] = str(limit_info["reset"] - int(time.time()))

                return response

            # Store limit info in request for response headers
            request._rate_limit_info = limit_info
            request._threat_score = threat_score
        except Exception as e:
            # If cache/redis unavailable, allow request through (fail-open)
            logger.debug(f"Rate limit middleware error (allowing request): {e}")

        return None

    def process_response(self, request, response):
        """Add rate limit headers to response"""
        if hasattr(request, "_rate_limit_info"):
            limit_info = request._rate_limit_info

            response["X-RateLimit-Limit"] = str(limit_info["limit"])
            response["X-RateLimit-Remaining"] = str(limit_info["remaining"])
            response["X-RateLimit-Reset"] = str(limit_info["reset"])
            response["X-RateLimit-Window"] = str(limit_info["window"])
            response["X-RateLimit-Category"] = limit_info["category"]

        # Add threat score header for monitoring (only in debug mode)
        if getattr(settings, "DEBUG", False) and hasattr(request, "_threat_score"):
            response["X-Threat-Score"] = str(request._threat_score)

        return response


class CircuitBreakerMiddleware(MiddlewareMixin):
    """
    Circuit breaker pattern for protecting against cascading failures
    """

    def __init__(self, get_response):
        super().__init__(get_response)
        self.circuit_breaker_cache = "circuit_breaker_status"
        self.failure_threshold = 50  # Trip after 50 failures
        self.timeout = 60  # 1 minute timeout
        self.half_open_max_calls = 5  # Max calls in half-open state

    def get_circuit_status(self) -> Dict:
        """Get current circuit breaker status"""
        default_status = {
            "state": "closed",  # closed, open, half_open
            "failure_count": 0,
            "last_failure_time": None,
            "next_attempt_time": None,
        }
        try:
            return cache.get(self.circuit_breaker_cache, default_status)
        except Exception:
            return default_status

    def update_circuit_status(self, status: Dict):
        """Update circuit breaker status"""
        try:
            cache.set(self.circuit_breaker_cache, status, 3600)  # Cache for 1 hour
        except Exception:
            pass  # Cache unavailable, circuit breaker operates stateless

    def record_success(self):
        """Record successful request"""
        status = self.get_circuit_status()
        if status["state"] == "half_open":
            # Transition back to closed state
            status.update(
                {
                    "state": "closed",
                    "failure_count": 0,
                    "last_failure_time": None,
                    "next_attempt_time": None,
                }
            )
            self.update_circuit_status(status)
            logger.info("Circuit breaker: Transitioned to CLOSED state")

    def record_failure(self):
        """Record failed request"""
        status = self.get_circuit_status()
        status["failure_count"] += 1
        status["last_failure_time"] = time.time()

        if status["failure_count"] >= self.failure_threshold and status["state"] == "closed":
            # Trip the circuit breaker
            status.update(
                {
                    "state": "open",
                    "next_attempt_time": time.time() + self.timeout,
                }
            )
            self.update_circuit_status(status)
            logger.error(f"Circuit breaker: Transitioned to OPEN state after {status['failure_count']} failures")
        else:
            self.update_circuit_status(status)

    def process_request(self, request):
        """Check circuit breaker state before processing request"""
        try:
            status = self.get_circuit_status()
            now = time.time()

            if status["state"] == "open":
                # Check if timeout has elapsed
                if status.get("next_attempt_time", 0) <= now:
                    # Transition to half-open state
                    status.update(
                        {
                            "state": "half_open",
                            "failure_count": 0,
                        }
                    )
                    self.update_circuit_status(status)
                    logger.info("Circuit breaker: Transitioned to HALF_OPEN state")
                else:
                    # Circuit is still open, reject request
                    return JsonResponse(
                        {
                            "error": "Service temporarily unavailable",
                            "reason": "Circuit breaker is open",
                            "retry_after": int(status.get("next_attempt_time", now) - now),
                        },
                        status=503,
                    )
        except Exception as e:
            # If cache/redis unavailable, allow request through (fail-open)
            logger.debug(f"Circuit breaker middleware error (allowing request): {e}")

        return None

    def process_response(self, request, response):
        """Record success/failure based on response status"""
        try:
            if response.status_code >= 500:
                self.record_failure()
            elif response.status_code < 400:
                self.record_success()
        except Exception:
            pass  # Cache unavailable, skip circuit breaker tracking

        return response
