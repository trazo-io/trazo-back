"""
Django settings for testing environment.
Optimized for CI/CD with in-memory database and minimal external dependencies.
"""

from backend.settings.base import *
import os

# Test-specific settings
DEBUG = False
TESTING = True

# Use environment variables from CI or fallback to test defaults
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]

# Database configuration for testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DATABASE_NAME', 'test_trazo'),
        'USER': os.environ.get('DATABASE_USER', 'postgres'),
        'PASSWORD': os.environ.get('DATABASE_PASSWORD', 'postgres'),
        'HOST': os.environ.get('DATABASE_HOST', 'localhost'),
        'PORT': os.environ.get('DATABASE_PORT', '5432'),
        'TEST': {
            'NAME': 'test_trazo_ci',
        }
    }
}

# Use Redis cache if available, fallback to dummy cache
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
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
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Media files for testing
MEDIA_ROOT = '/tmp/trazo_test_media'

# Disable logging during tests
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.NullHandler',
        },
    },
    'root': {
        'handlers': ['console'],
    },
}

# Test-specific security settings
SECRET_KEY = 'test-secret-key-not-for-production'
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',  # Fast for testing
]

# Disable external API calls during testing
USDA_API_ENABLED = False
BLOCKCHAIN_ENABLED = False
AWS_S3_ENABLED = False

# Override any external service configurations
AWS_STORAGE_BUCKET_NAME = 'test-bucket'
STRIPE_PUBLISHABLE_KEY = 'pk_test_fake'
STRIPE_SECRET_KEY = 'sk_test_fake'