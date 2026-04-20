"""
JWTCookieActorMiddleware — resolves the JWT access-token cookie to a User and
sets it on `request.user` BEFORE AuditlogMiddleware runs. Without this, all
audit-log entries carry actor=None (django-auditlog's middleware captures the
user from request.user at request-start, but Trazo authenticates via DRF
per-view so request.user is still AnonymousUser at middleware time).

Regulatory motivation: 7 CFR 205.103 requires that digital records identify
the person who created or modified them (the 21 CFR Part 11 trustworthy-
records principle parallels). An audit log that reports every change as
actor="system" does not meet this bar; an accredited certifier will flag it.

Fail-open: any error decoding the cookie leaves `request.user` anonymous.
This middleware never raises — it is purely an enhancement to audit
attribution, not an authorization gate. The actual DRF JWT authentication
(users.auth.CustomAuthentication) continues to run per-view for authorization.
"""

import logging

from django.conf import settings

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

logger = logging.getLogger(__name__)


class JWTCookieActorMiddleware:
    """Set request.user from the access-token cookie so auditlog captures the actor."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._jwt = JWTAuthentication()

    def __call__(self, request):
        # Only override if AuthenticationMiddleware left us with AnonymousUser.
        # If something already authenticated the request (admin session, etc.),
        # leave it alone.
        existing = getattr(request, "user", None)
        if existing is not None and getattr(existing, "is_authenticated", False):
            return self.get_response(request)

        cookie_name = settings.SIMPLE_JWT.get("AUTH_COOKIE", "access_token")
        raw_token = request.COOKIES.get(cookie_name)
        if not raw_token:
            return self.get_response(request)

        try:
            validated = self._jwt.get_validated_token(raw_token)
            user = self._jwt.get_user(validated)
        except (InvalidToken, TokenError, Exception) as exc:
            # Expired / malformed / revoked — leave as anonymous. DRF will
            # reject the request at auth-check time if the endpoint requires
            # authentication; this middleware is best-effort only.
            logger.debug(f"JWTCookieActorMiddleware: could not resolve user ({exc})")
            return self.get_response(request)

        if user is not None:
            request.user = user
        return self.get_response(request)
