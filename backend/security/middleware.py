"""
Security Middleware for Trazo
Implements OWASP 2025 security headers and protections
"""

import logging

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    SECURITY: Adds comprehensive security headers to all responses
    Implements OWASP 2025 security header recommendations
    """

    def process_response(self, request, response):
        """
        Add security headers to all responses
        """

        # X-Content-Type-Options: Prevent MIME type sniffing
        response["X-Content-Type-Options"] = "nosniff"

        # X-Frame-Options: Prevent clickjacking attacks
        if not response.get("X-Frame-Options"):
            response["X-Frame-Options"] = "DENY"

        # X-XSS-Protection: Legacy XSS protection (for older browsers)
        response["X-XSS-Protection"] = "1; mode=block"

        # Referrer-Policy: Control referrer information
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy: Control browser features
        # SECURITY: microphone=(self) required for voice recording feature (Deepgram)
        response["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(self), "
            "camera=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "speaker=(), "
            "vibrate=(), "
            "fullscreen=()"
        )

        # HSTS (HTTP Strict Transport Security) - only for HTTPS
        if request.is_secure() or not settings.DEBUG:
            response["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        # Content Security Policy
        if not response.get("Content-Security-Policy"):
            csp = self.get_content_security_policy(request)
            response["Content-Security-Policy"] = csp

        return response

    def get_content_security_policy(self, request):
        """
        Generate Content Security Policy based on environment
        """
        # Base CSP for production
        csp_directives = {
            "default-src": ["'self'"],
            "script-src": [
                "'self'",
                "'unsafe-inline'",  # Needed for React in development
                "https://apis.google.com",
                "https://connect.facebook.net",
                "https://appleid.cdn-apple.com",
            ],
            "style-src": [
                "'self'",
                "'unsafe-inline'",  # Needed for styled-components
                "https://fonts.googleapis.com",
            ],
            "font-src": [
                "'self'",
                "https://fonts.gstatic.com",
            ],
            "img-src": [
                "'self'",
                "data:",
                "https:",
                "blob:",
            ],
            "connect-src": [
                "'self'",
                "https://api.trazo.io" if not settings.DEBUG else "http://localhost:8000",
                "https://api.pwnedpasswords.com",  # For password breach checking
                "https://accounts.google.com",
                "https://graph.facebook.com",
                "https://appleid.apple.com",
            ],
            "frame-src": [
                "'self'",
                "https://accounts.google.com",
                "https://www.facebook.com",
                "https://appleid.apple.com",
            ],
            "object-src": ["'none'"],
            "base-uri": ["'self'"],
            "form-action": ["'self'"],
            "frame-ancestors": ["'none'"],
            "upgrade-insecure-requests": [] if settings.DEBUG else [""],
        }

        # Development environment adjustments
        if settings.DEBUG:
            # Allow WebSocket connections for development
            csp_directives["connect-src"].extend(
                [
                    "ws://localhost:*",
                    "wss://localhost:*",
                    "http://localhost:*",
                ]
            )

            # Allow unsafe-eval for development tools
            csp_directives["script-src"].append("'unsafe-eval'")

        # Convert to CSP string
        csp_parts = []
        for directive, sources in csp_directives.items():
            if sources:
                csp_parts.append(f"{directive} {' '.join(sources)}")
            else:
                csp_parts.append(directive)

        return "; ".join(csp_parts)


class RequestSecurityMiddleware(MiddlewareMixin):
    """
    SECURITY: Validates and logs suspicious requests
    """

    def process_request(self, request):
        """
        Validate request security before processing
        """
        # Log requests without User-Agent (potential bot activity)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        if not user_agent:
            logger.warning(f"Request without User-Agent from {request.META.get('REMOTE_ADDR')} " f"to {request.path}")

        # Log suspicious request patterns
        path = request.path.lower()
        suspicious_patterns = [
            "/wp-admin",
            "/admin.php",
            "/.env",
            "/config.php",
            "/phpinfo.php",
            "/phpmyadmin",
            "/sql",
            "/backup",
            "eval(",
            "base64_decode",
            "<script",
            "javascript:",
        ]

        for pattern in suspicious_patterns:
            if pattern in path or pattern in request.body.decode("utf-8", errors="ignore"):
                logger.warning(
                    f"Suspicious request pattern '{pattern}' from "
                    f"{request.META.get('REMOTE_ADDR')} to {request.path}"
                )
                break

        return None


class RateLimitHeadersMiddleware(MiddlewareMixin):
    """
    SECURITY: Add rate limiting headers for transparency
    """

    def process_response(self, request, response):
        """
        Add rate limiting information to responses
        """
        # Add rate limit headers if not already present
        if not response.get("X-RateLimit-Limit"):
            # Default rate limits (can be overridden by specific endpoints)
            if request.path.startswith("/api/auth/"):
                response["X-RateLimit-Limit"] = "60"  # 60 requests per hour for auth
                response["X-RateLimit-Window"] = "3600"  # 1 hour window
            else:
                response["X-RateLimit-Limit"] = "1000"  # 1000 requests per hour for API
                response["X-RateLimit-Window"] = "3600"  # 1 hour window

        return response


class SecurityEventMiddleware(MiddlewareMixin):
    """
    SECURITY: Log security-relevant events for monitoring
    """

    def process_response(self, request, response):
        """
        Log security events based on response status and content
        """
        # Log authentication failures
        if response.status_code == 401 and request.path.startswith("/api/auth/"):
            logger.warning(f"Authentication failure from {request.META.get('REMOTE_ADDR')} " f"to {request.path}")

        # Log CSRF failures
        if response.status_code == 403 and "CSRF" in str(response.content):
            logger.warning(f"CSRF failure from {request.META.get('REMOTE_ADDR')} " f"to {request.path}")

        # Log rate limit violations
        if response.status_code == 429:
            logger.warning(f"Rate limit exceeded from {request.META.get('REMOTE_ADDR')} " f"to {request.path}")

        # Log server errors for security analysis
        if response.status_code >= 500:
            logger.error(
                f"Server error {response.status_code} from " f"{request.META.get('REMOTE_ADDR')} to {request.path}"
            )

        return response
