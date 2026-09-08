"""Deployment-time checks for security controls that fail SILENTLY when misconfigured.

The class of bug this exists for: a setting that declares a protection, and an environment
in which that protection quietly does nothing. Nothing raises, nothing logs, and the
settings file still reads as though the control is on.

⚠️ SEVERITY IS A PRODUCTION DECISION, NOT A JUDGEMENT OF HOW BAD THE FINDING IS.

Django runs system checks before every management command, and a `checks.Error` aborts it —
`migrate`, `collectstatic`, the gunicorn start, all of it. MEASURED 2026-08-27: this module
shipped its first finding as an Error, the DigitalOcean release step ran `manage.py check`,
and the app never bound its port:

    SystemCheckError: (security.E001) Rate limiting is configured but cannot work...
    ERROR failed health checks after 10 attempts ... connection refused
    ERROR component terminated with non-zero exit code: 1

The finding was CORRECT — production really was on DummyCache with every rate inert. But it
had been true for months, and the fix (provision Redis) is an infra change the operator
cannot make while the service is down. A check that takes prod offline to report a
pre-existing condition converts a standing risk into an outage, and it teaches everyone to
reach for `SILENCED_SYSTEM_CHECKS`, which loses the signal permanently.

So: **Warning by default — loud in every deploy log, never fatal.** Escalate to Error only
where blocking is the point, by setting ``SECURITY_CHECKS_STRICT = True`` in CI or staging.
Reserve Error for "this deploy is definitely broken", not "this deploy is unprotected".
"""

from django.conf import settings
from django.core.checks import Error, Warning, register

from backend.storage import S3_BACKEND

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

    message = "Rate limiting is configured but cannot work."
    if critical:
        message = (
            "Rate limiting is configured but cannot work: " f"brute-force protection on {', '.join(critical)} is inert."
        )

    # Blocking is opt-in. See the module docstring for why the default cannot be Error.
    if getattr(settings, "SECURITY_CHECKS_STRICT", False):
        problems.append(Error(message, hint=detail, id="security.E001"))
    else:
        problems.append(Warning(message, hint=detail, id="security.W001"))
    return problems


@register("security")
def media_storage_is_not_silently_local(app_configs, **kwargs):
    """S3 is configured but `STORAGES` does not select it, so uploads go to local disk.

    THE FAILURE THIS CATCHES
    ------------------------
    `DEFAULT_FILE_STORAGE` was REMOVED in Django 5.1. Under 5.2 it is not deprecated — it is
    IGNORED. MEASURED 2026-09-07 on 5.2.17: with `DEFAULT_FILE_STORAGE = S3Boto3Storage` and
    no `STORAGES`, `storages["default"]` resolved to FileSystemStorage. Nothing raises,
    nothing logs, and `manage.py check` is silent.

    On App Platform the container filesystem is ephemeral, so the consequence is not a
    misconfiguration to fix later — it is photo evidence and generated certifier documents
    written to a disk that disappears on the next restart. § 205.103 records that vanish.

    WHY THIS ONE IS AN ERROR, against this module's own default
    -----------------------------------------------------------
    The docstring above reserves Error for "this deploy is definitely broken", and this is
    that: the settings CONTRADICT THEMSELVES. It only fires when an AWS bucket is configured
    — i.e. someone plainly intended S3 — while `STORAGES` points somewhere else. That is not
    a standing risk being reported, it is a deploy that will lose data.

    It also differs from the security.E001 incident in the way that matters: the fix is a
    one-line settings change in this repository, deployable in minutes. The Redis finding
    could not be fixed while the service was down; this one can.

    Deliberately silent when no bucket is set (dev, tests, CI), so it cannot fire where
    local storage is the correct answer.
    """
    problems = []

    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or ""
    if not bucket:
        # No bucket configured => local storage is intentional. Nothing to say.
        return problems

    backend = ""
    try:
        backend = settings.STORAGES["default"]["BACKEND"]
    except (AttributeError, KeyError, TypeError):
        backend = "<unset>"

    if backend == S3_BACKEND:
        return problems

    legacy = getattr(settings, "DEFAULT_FILE_STORAGE", None)
    hint = (
        f'AWS_STORAGE_BUCKET_NAME is "{bucket}" but STORAGES["default"]["BACKEND"] is '
        f'"{backend}". Django 5.1 REMOVED DEFAULT_FILE_STORAGE and 5.2 ignores it silently, '
        f"so setting it has no effect. Fix by declaring, in this environment's settings "
        f'module: STORAGES = {{"default": {{"BACKEND": "{S3_BACKEND}"}}, "staticfiles": '
        f"{{...}}}} — one dict, both keys, because assigning STORAGES twice replaces it."
    )
    if legacy:
        hint += f' (DEFAULT_FILE_STORAGE is still set to "{legacy}" and is being ignored.)'

    problems.append(
        Error(
            "Media uploads would be written to the container's ephemeral local disk, not S3.",
            hint=hint,
            id="security.E002",
        )
    )
    return problems
