"""DRF throttles that count against the real client address.

DRF's own `get_ident` uses X-Forwarded-For when NUM_PROXIES is unset, which on DigitalOcean is
a value the client sends (see `backend/security/client_ip.py`). Every throttle in this project
subclasses these instead of `rest_framework.throttling`.

The three auth throttles exist because the `login`, `signup` and `password_reset` rates in
DEFAULT_THROTTLE_RATES were declared and consumed by NO view until 2026-10-17: the auth
endpoints only had the shared `anon` 50/hour, so the security check reporting those rates as
inert was right for two reasons, and a real cache would have fixed only one of them.

WHERE THE COUNTS LIVE (2026-11-11, OV-SEC-C06). The security throttles below count in the
`throttle` cache (Postgres), not in `default`, which production keeps as DummyCache. So they hold
in production; `anon` and `user` still count in `default` and are inert there by design, because
giving `default` a real backend wakes three dormant middlewares (see the CACHES note in base.py).
A new limit that must hold in production subclasses `_CountedThrottle` or calls
`throttle_cache()`; anything on `default` is a declaration, not a limit.
"""

from django.conf import settings
from django.core.cache import caches

from rest_framework import throttling

from backend.security.client_ip import throttle_ident


def throttle_cache():
    """The cache whose counters survive in production. Resolved per call so `override_settings`
    on CACHES reaches it."""
    return caches[settings.THROTTLE_CACHE_ALIAS]


class ClientIPMixin:
    def get_ident(self, request):
        return throttle_ident(request)


class AnonRateThrottle(ClientIPMixin, throttling.AnonRateThrottle):
    pass


class UserRateThrottle(ClientIPMixin, throttling.UserRateThrottle):
    pass


class ScopedRateThrottle(ClientIPMixin, throttling.ScopedRateThrottle):
    pass


class _CountedThrottle(throttling.SimpleRateThrottle):
    """Counts in the `throttle` cache, so the limit holds in production."""

    @property
    def cache(self):
        return throttle_cache()


class _ClientIPScopeThrottle(ClientIPMixin, _CountedThrottle):
    """Per address, signed in or not: these endpoints are reached before authentication."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginRateThrottle(_ClientIPScopeThrottle):
    scope = "login"


class SignupRateThrottle(_ClientIPScopeThrottle):
    scope = "signup"


class PasswordResetRateThrottle(_ClientIPScopeThrottle):
    scope = "password_reset"


class VerifyEmailRateThrottle(_ClientIPScopeThrottle):
    """Guessing the emailed six-character code. A matching code signs the account in."""

    scope = "verify_email"


class ResendVerificationRateThrottle(_ClientIPScopeThrottle):
    """Each call sends an email, so an open endpoint can fill someone's inbox."""

    scope = "resend_verification"
