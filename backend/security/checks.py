"""Deployment-time checks for security controls that fail SILENTLY when misconfigured.

The class of bug this exists for: a setting that declares a protection, and an environment
in which that protection quietly does nothing. Nothing raises, nothing logs, and the
settings file still reads as though the control is on.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register

# Rates whose whole purpose is to stop an attack rather than to shape ordinary traffic.
# If these are inert, the door is open.
_SECURITY_CRITICAL_SCOPES = ("login", "signup", "password_reset")

_INERT_CACHE_BACKENDS = (
    "django.core.cache.backends.dummy.DummyCache",
    # LocMem is per-process: with more than one gunicorn worker each keeps its own counter,
    # so an N-worker deploy multiplies every rate by N and resets them on every restart.
    "django.core.cache.backends.locmem.LocMemCache",
)


@register("security")
def throttling_is_actually_enforced(app_configs, **kwargs):
    """DRF throttles keep their counters in the Django cache. With DummyCache every read
    returns empty, so `allow_request` always succeeds and every declared rate is a no-op.

    MEASURED 2026-08-26 against this project's own settings: a ``3/minute`` throttle
    allowed 50 of 50 requests under DummyCache.

    prod.py already falls back to DummyCache when REDIS_URL is unset, and in that branch it
    disables ``django_ratelimit`` explicitly — but DRF's own throttles are left declared and
    inert. That is worse than switching them off, because REST_FRAMEWORK still lists
    "login": "3/minute" and nothing anywhere says it is not happening.
    """
    problems = []

    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if backend not in _INERT_CACHE_BACKENDS:
        return problems

    rest = getattr(settings, "REST_FRAMEWORK", {}) or {}
    rates = rest.get("DEFAULT_THROTTLE_RATES", {}) or {}
    declared = {scope: rate for scope, rate in rates.items() if rate}
    if not declared:
        return problems

    critical = sorted(s for s in declared if s in _SECURITY_CRITICAL_SCOPES)
    detail = (
        f"CACHES['default'] is {backend}, which stores nothing, so all "
        f"{len(declared)} DEFAULT_THROTTLE_RATES are no-ops "
        f"({', '.join(sorted(declared))}). Set REDIS_URL so prod.py selects RedisCache, "
        f"or delete the rates so the settings stop claiming a protection that is absent."
    )

    if critical:
        problems.append(
            Error(
                "Rate limiting is configured but cannot work: "
                f"brute-force protection on {', '.join(critical)} is inert.",
                hint=detail,
                id="security.E001",
            )
        )
    else:
        problems.append(
            Warning(
                "Rate limiting is configured but cannot work.",
                hint=detail,
                id="security.W001",
            )
        )
    return problems
