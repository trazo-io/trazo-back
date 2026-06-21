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

# Use Redis cache if available, fallback to dummy cache
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
        "KEY_PREFIX": "trazo_test",
    }
}


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

# Use local filesystem storage during tests. base.py defaults DEFAULT_FILE_STORAGE to S3, so any
# FileField/ImageField save (e.g. QR/album images created in fixtures) otherwise tries to PutObject
# to a real bucket and fails with AccessDenied — defeating "minimal external dependencies".
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"

# base.py forces SECURE_SSL_REDIRECT=True when DEBUG is False (production hardening). DEBUG is False
# here, so without this the test client's http requests get a 301 redirect to https and every
# endpoint test fails. Disable HTTPS redirect for the test environment.
SECURE_SSL_REDIRECT = False
