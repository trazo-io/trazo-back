import os

from decouple import config

from backend.settings.base import *

# ALLOWED_HOSTS - check for staging environment
if os.environ.get("ENVIRONMENT") == "staging":
    # Staging-specific allowed hosts
    ALLOWED_HOSTS = [
        "localhost",
        ".localhost",
        "127.0.0.1",
        "testserver",
        "staging-alb-1273700937.us-east-2.elb.amazonaws.com",
        "api-staging.trazo.io",
    ]
else:
    # Development allowed hosts
    ALLOWED_HOSTS = (
        "localhost",
        ".localhost",
        "127.0.0.1",
        "192.168.1.3",
        "7172-167-60-250-132.ngrok-free.app",
        "testserver",
    )

# Database configuration for local development
# Use PostgreSQL if Docker services are running, fallback to SQLite

# Check if PostgreSQL is available (Docker services running)
try:
    import psycopg2
    from decouple import config

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DATABASE_NAME", default="trazo_dev"),
            "USER": config("DATABASE_USER", default="postgres"),
            "PASSWORD": config("DATABASE_PASSWORD", default="postgres"),
            "HOST": config("DATABASE_HOST", default="localhost"),
            "PORT": config("DATABASE_PORT", default="5432"),
            # Unset: Django uses test_<NAME>, so every checkout on this machine builds the same
            # test_trazo_dev and two concurrent runs corrupt each other. The Orca worktree setup
            # (trazo-workspace scripts/orca-worktree.sh) writes a per-task name into .env.
            "TEST": {"NAME": config("TEST_DATABASE_NAME", default=None)},
        }
    }

    # Optimized Redis Cache Configuration for Carbon Calculations
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": config("REDIS_URL", default="redis://localhost:6379/1"),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "CONNECTION_POOL_KWARGS": {
                    "max_connections": 50,
                    "retry_on_timeout": True,
                    "socket_keepalive": True,
                    "socket_keepalive_options": {},
                },
                "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
                "SERIALIZER": "django_redis.serializers.json.JSONSerializer",
            },
            "TIMEOUT": 3600,  # 1 hour default timeout
            "KEY_PREFIX": "trazo_carbon",
        }
    }

    # Carbon calculation cache timeouts
    CARBON_CACHE_TIMEOUTS = {
        "emission_factors": 3600,  # 1 hour
        "calculations": 300,  # 5 minutes
        "dashboard_stats": 600,  # 10 minutes
        "usda_api_results": 7200,  # 2 hours
        "circuit_breaker": 300,  # 5 minutes
    }

    # Celery Configuration with Redis
    CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")

    # Email Configuration (MailDev)
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "localhost"
    EMAIL_PORT = 3025
    EMAIL_USE_TLS = False
    EMAIL_HOST_USER = ""
    EMAIL_HOST_PASSWORD = ""

except ImportError:
    # Fallback to SQLite if PostgreSQL is not available
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db_dev.sqlite3",
        }
    }

    # File-based cache backend for development (compatible with django_ratelimit)
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": "/tmp/django_cache",
        }
    }

    # Disable Celery and Redis for local development (optional services)
    CELERY_TASK_ALWAYS_EAGER = True  # Run tasks synchronously in development
    CELERY_TASK_EAGER_PROPAGATES = True
    CELERY_BROKER_URL = "memory://"  # In-memory broker for development
    CELERY_RESULT_BACKEND = "cache+memory://"

    # Use MailDev for email testing (fallback configuration)
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "localhost"
    EMAIL_PORT = 3025
    EMAIL_USE_TLS = False
    EMAIL_HOST_USER = ""
    EMAIL_HOST_PASSWORD = ""

# CSRF_TRUSTED_ORIGINS = [
#     "http://localhost:3000",
#     "http://app.localhost:3000",
#     "http://app.192.168.1.3:3000",
#     "http://localhost:8000",
# ]

# CSRF trusted origins - check for staging environment
if os.environ.get("ENVIRONMENT") == "staging":
    # Staging-specific CSRF configuration
    CSRF_TRUSTED_ORIGINS = [
        "https://staging-alb-1273700937.us-east-2.elb.amazonaws.com",
        "http://staging-alb-1273700937.us-east-2.elb.amazonaws.com",
        "https://*.localhost",
        "http://app.localhost:3000",
        "http://localhost:3000",  # Add direct localhost support
    ]
else:
    # Development CSRF configuration.
    # 3001 must be here as well as in CORS_ALLOWED_ORIGINS: Vite silently falls back to
    # 3001 whenever 3000 is occupied, and without the CSRF entry every POST from that
    # port fails with "Origin checking failed" while GETs keep working — which reads
    # like a broken login rather than a config gap.
    CSRF_TRUSTED_ORIGINS = [
        "https://*.localhost",
        "http://*.localhost:3000",
        "http://*.localhost:3001",
        "http://*.localhost:4173",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:4173",
        "https://7172-167-60-250-132.ngrok-free.app",
    ]

CORS_ORIGIN_ALLOW_ALL = True

CORS_ORIGIN_WHITELIST = [
    "http://localhost:3000",  # Enable direct localhost support
    "http://app.localhost:3000",
    "http://consumer.localhost:3000",
    "http://app.192.168.1.3:3000",
    "https://7172-167-60-250-132.ngrok-free.app",
    "http://127.0.0.1:3000",  # Also add 127.0.0.1 support
    "http://localhost:4173",  # For production build testing
    "http://app.localhost:4173",  # For production build testing with subdomain
]
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",  # Enable direct localhost support
    "http://localhost:3001",  # Enable port 3001 for Vite dev server
    "http://app.localhost:3000",
    "http://app.localhost:3001",
    "http://consumer.localhost:3000",
    "http://consumer.localhost:3001",  # Enable port 3001 for consumer app
    "http://app.192.168.1.3:3000",
    "https://7172-167-60-250-132.ngrok-free.app",
    "http://127.0.0.1:3000",  # Also add 127.0.0.1 support
    "http://localhost:4173",  # For production build testing
    "http://app.localhost:4173",  # For production build testing with subdomain
]

# Allow custom consent header for GDPR compliance
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-analytics-consent",  # Custom header for consent management
]

# Fix for development - allow cross-subdomain cookies and HTTP
CSRF_COOKIE_DOMAIN = None  # Same-origin via Vite proxy — no cross-domain needed
CSRF_COOKIE_SECURE = False  # Allow HTTP in development
CSRF_COOKIE_SAMESITE = "Lax"  # Allow cross-subdomain requests in development (Lax works with HTTP)

# Development-specific rate limiting configuration
# Disable aggressive rate limiting for development
RATELIMIT_ENABLE = False  # Disable rate limiting in development

# Override REST_FRAMEWORK throttle rates for development
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("users.auth.CustomAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "10000/hour",  # Extremely permissive for development
        "user": "20000/hour",  # Extremely permissive for development
        "login": "1000/minute",  # Extremely permissive for development
        "signup": "500/minute",  # Extremely permissive for development
        "password_reset": "500/hour",  # Extremely permissive for development
        "carbon_calculation": "5000/hour",
        "api_sensitive": "2000/hour",
        "qr_scan": "10000/hour",
        "blockchain": "1000/hour",
        # Dossier-status poll from the anonymous certifier page (see base.py).
        "certifier_poll": "10000/hour",
        # Review landing pages (see base.py).
        "certifier_review": "10000/hour",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# SECURITY: Disable aggressive rate limiting in development
# This removes the custom SecurityMiddleware that blocks IPs after failed attempts
# WARNING: Only for development! Production must keep these security measures
MIDDLEWARE = [
    # Keep Django's security middleware
    "django.middleware.security.SecurityMiddleware",
    "backend.security.middleware.SecurityHeadersMiddleware",  # Keep security headers
    "backend.security.middleware.RequestSecurityMiddleware",  # Keep request validation
    "corsheaders.middleware.CorsMiddleware",
    # REMOVED: backend.security.rate_limiting.SecurityMiddleware - This was blocking IPs
    "backend.security_middleware.SecurityLoggingMiddleware",  # Keep logging
    "backend.security_middleware.CSRFSecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # REQUIRED by django-allauth >= 0.56. Mirrors base.py — this file redefines MIDDLEWARE
    # wholesale rather than extending it, so an addition to base.py alone would leave dev
    # broken with an ImproperlyConfigured at startup.
    "allauth.account.middleware.AccountMiddleware",
    "carbon.middleware.security_middleware.CarbonSecurityMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "subscriptions.middleware.SubscriptionMiddleware",
    # REMOVED: backend.security.middleware.RateLimitHeadersMiddleware
    # REMOVED: backend.security.middleware.SecurityEventMiddleware
    # Resolve JWT cookie to request.user BEFORE AuditlogMiddleware so audit
    # entries carry a named actor (7 CFR 205.103 / 21 CFR Part 11 attribution).
    "users.middleware.JWTCookieActorMiddleware",
    # One line per /api/ request (user id, path, status, IP). See backend/request_log.py.
    "backend.request_log.RequestLogMiddleware",
    # NOP audit trail — captures request user on every model save (Sprint 2)
    "auditlog.middleware.AuditlogMiddleware",
]

# Disable rate limiting for development
RATELIMIT_ENABLE = False

# JWT Cookie Configuration for Development
# Enable cross-subdomain cookies for localhost development
SIMPLE_JWT = {
    **SIMPLE_JWT,  # Inherit base settings
    "AUTH_COOKIE_DOMAIN": None,  # Same-origin via Vite proxy — no cross-domain needed
    "AUTH_COOKIE_SECURE": False,  # Allow HTTP in development
    "AUTH_COOKIE_SAMESITE": "Lax",  # Compatible with HTTP
}

# Email configuration for development
# Use MailDev for email testing in development
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "localhost"
EMAIL_PORT = 3025
EMAIL_USE_TLS = False
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
SERVER_EMAIL = os.environ.get("FROM_EMAIL_ADDRESS", "info@trazo.io")
DEFAULT_FROM_EMAIL = os.environ.get("FROM_EMAIL_ADDRESS", "info@trazo.io")

# Console backend (for debugging - switch back if needed)
# EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Use local filesystem in development. base.py sets STORAGES to S3; this overrides it.
# (DEFAULT_FILE_STORAGE was removed in Django 5.1 and is ignored — see base.py.)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Note: Using Redis and Celery services from Docker for consistency
# Cache and Celery are already configured above in the PostgreSQL section

# John Deere API Configuration
JOHN_DEERE_CLIENT_ID = os.environ.get("JOHN_DEERE_CLIENT_ID", "test_client_id")
JOHN_DEERE_CLIENT_SECRET = os.environ.get("JOHN_DEERE_CLIENT_SECRET", "test_client_secret")
JOHN_DEERE_REDIRECT_URI = os.environ.get("JOHN_DEERE_REDIRECT_URI", "http://localhost:8000/carbon/john-deere/callback/")
JOHN_DEERE_USE_SANDBOX = os.environ.get("JOHN_DEERE_USE_SANDBOX", "True").lower() == "true"

# Weather API Configuration
# NOAA Weather Service (free, no API key required for US locations)
NOAA_API_BASE_URL = "https://api.weather.gov"

# OpenWeatherMap (backup service, requires API key)
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", None)
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5"

# Weather alert thresholds (can be customized per establishment)
WEATHER_ALERT_THRESHOLDS = {
    "high_temp": 85,  # Fahrenheit
    "low_temp": 35,  # Fahrenheit
    "high_wind": 20,  # mph
    "low_humidity": 30,  # percentage
    "high_humidity": 85,  # percentage
}

# Override base URLs for development to include proper subdomains
BASE_APP_URL = "http://app.localhost:3000/"
BASE_CONSUMER_URL = "http://consumer.localhost:3000/"

# USDA API Configuration - Use environment variables for security
USDA_NASS_API_KEY = os.environ.get("USDA_NASS_API_KEY", None)
TRAZO_OPERATING_COUNTRY = os.environ.get("TRAZO_OPERATING_COUNTRY", "US")

# API Attribution (required by NASS Terms of Service)
USDA_API_ATTRIBUTION = "This product uses the NASS API but is not endorsed or certified by NASS."
