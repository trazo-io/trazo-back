"""DRF throttles that count against the real client address.

DRF's own `get_ident` uses X-Forwarded-For when NUM_PROXIES is unset, which on DigitalOcean is
a value the client sends (see `backend/security/client_ip.py`). Every throttle in this project
subclasses these instead of `rest_framework.throttling`.

The three auth throttles exist because the `login`, `signup` and `password_reset` rates in
DEFAULT_THROTTLE_RATES were declared and consumed by NO view until 2026-10-17: the auth
endpoints only had the shared `anon` 50/hour, so the security check reporting those rates as
inert was right for two reasons, and a real cache would have fixed only one of them.
"""

from rest_framework import throttling

from backend.security.client_ip import throttle_ident


class ClientIPMixin:
    def get_ident(self, request):
        return throttle_ident(request)


class AnonRateThrottle(ClientIPMixin, throttling.AnonRateThrottle):
    pass


class UserRateThrottle(ClientIPMixin, throttling.UserRateThrottle):
    pass


class ScopedRateThrottle(ClientIPMixin, throttling.ScopedRateThrottle):
    pass


class _ClientIPScopeThrottle(ClientIPMixin, throttling.SimpleRateThrottle):
    """Per address, signed in or not: these endpoints are reached before authentication."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginRateThrottle(_ClientIPScopeThrottle):
    scope = "login"


class SignupRateThrottle(_ClientIPScopeThrottle):
    scope = "signup"


class PasswordResetRateThrottle(_ClientIPScopeThrottle):
    scope = "password_reset"
