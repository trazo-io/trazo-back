"""
Django settings for testing environment.
Optimized for CI/CD with in-memory database and minimal external dependencies.
"""

import os

# Set required environment variables before importing base settings
os.environ.setdefault(
    "SECRET_KEY", "test-secret-key-for-ci-not-production-use-only-12345678901234567890123456789012345"
)
os.environ.setdefault("DATABASE_NAME", "test_trazo")
os.environ.setdefault("DATABASE_USER", "postgres")
os.environ.setdefault("DATABASE_PASSWORD", "postgres")
os.environ.setdefault("DATABASE_HOST", "localhost")
os.environ.setdefault("DATABASE_PORT", "5432")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("USDA_API_KEY", "test-key")
os.environ.setdefault("STRIPE_PUBLISHABLE_KEY", "pk_test_fake")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("BASE_TRAZO_URL", "http://localhost:3000/")
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("TRAZO_OPERATING_COUNTRY", "US")

from backend.settings.base import *

# Test-specific settings
DEBUG = False
TESTING = True

# Use environment variables from CI or fallback to test defaults
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

# Database configuration for testing
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DATABASE_NAME", "test_trazo"),
        "USER": os.environ.get("DATABASE_USER", "postgres"),
        "PASSWORD": os.environ.get("DATABASE_PASSWORD", "postgres"),
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "PORT": os.environ.get("DATABASE_PORT", "5432"),
        "TEST": {
            "NAME": "test_trazo_ci",
        },
    }
}

# In-process cache, deliberately NOT the shared Redis instance.
#
# `backend.security.rate_limiting.SecurityMiddleware` (active via base MIDDLEWARE)
# blocks a client IP for 30 MINUTES when it sees high-frequency requests, and it
# stores that block in this cache. Pointed at real Redis, one API-heavy test run
# would block 127.0.0.1 and then every subsequent run — locally and in CI — failed
# with a plain `429 Access denied` that looks nothing like a test problem. This was
# hit for real on 2026-08-02 while adding the certifier-link suite.
#
# LocMemCache is per-process and torn down with the run, so a suite can no longer
# poison the next one. The middleware still executes, so its behavior stays covered.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "trazo-test-cache",
    }
}

# django_ratelimit refuses a non-shared cache (E003) because in production a
# per-process counter would let each worker allow the full quota. Under test that
# is precisely what we want — a shared counter is what let one run poison the next.
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E003", "django_ratelimit.W001"]

# Drop the rate-limit / DDoS middleware family under test.
#
# `EnhancedRateLimitMiddleware` allows 30 requests per 60s per IP. A test run
# issues far more than that from 127.0.0.1 in seconds — that IS the pattern these
# middlewares exist to catch — so any suite above ~30 API calls starts returning
# `429 {"error": "Rate limit exceeded", "limit": 30, "window": 60}` partway through.
#
# Observed 2026-08-02: `subscriptions.test_billing` and
# `certifications.test_osp_change_notification_api` pass in isolation and fail only
# inside a 457-test run. That reads exactly like a real regression and is not one —
# it is why a green suite could not be trusted at scale.
#
# These middlewares keep their own direct unit tests
# (`backend/security/tests/test_enhanced_ddos_protection.py`), which exercise the
# classes rather than relying on them sitting in front of every other API test.
_RATE_LIMIT_MIDDLEWARE = {
    "backend.security.enhanced_ddos_protection.EnhancedRateLimitMiddleware",
    "backend.security.enhanced_ddos_protection.CircuitBreakerMiddleware",
    "backend.security.rate_limiting.SecurityMiddleware",
}
MIDDLEWARE = [m for m in MIDDLEWARE if m not in _RATE_LIMIT_MIDDLEWARE]  # noqa: F405


# Disable migrations for faster testing
class DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = DisableMigrations()

# Email backend for testing
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Media files for testing
MEDIA_ROOT = "/tmp/trazo_test_media"

# Disable logging during tests
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.NullHandler",
        },
    },
    "root": {
        "handlers": ["console"],
    },
}

# Test-specific security settings
SECRET_KEY = "test-secret-key-not-for-production"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",  # Fast for testing
]

# Disable external API calls during testing
USDA_API_ENABLED = False
BLOCKCHAIN_ENABLED = False
AWS_S3_ENABLED = False

# Override any external service configurations
AWS_STORAGE_BUCKET_NAME = "test-bucket"
STRIPE_PUBLISHABLE_KEY = "pk_test_fake"
STRIPE_SECRET_KEY = "sk_test_fake"

# Use local filesystem storage during tests. base.py points STORAGES at S3, so any
# FileField/ImageField save (e.g. QR/album images created in fixtures) otherwise tries to PutObject
# to a real bucket and fails with AccessDenied — defeating "minimal external dependencies".
# (This was DEFAULT_FILE_STORAGE until 2026-09-07; Django 5.1 removed that setting and 5.2
# ignores it silently, so the override would have stopped working without any error.)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# base.py forces SECURE_SSL_REDIRECT=True when DEBUG is False (production hardening). DEBUG is False
# here, so without this the test client's http requests get a 301 redirect to https and every
# endpoint test fails. Disable HTTPS redirect for the test environment.
SECURE_SSL_REDIRECT = False
