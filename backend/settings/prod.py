# Production Settings Override

import os

import dj_database_url
from decouple import config

from backend.settings.base import *

# Import secure settings after base settings are loaded
try:
    from backend.settings.secure import apply_secure_settings

    # Apply secure settings to this module's globals
    apply_secure_settings(globals())
except ImportError:
    import logging

    logging.getLogger(__name__).warning("Secure settings module not available, using environment variables")

# Allow DEBUG to be controlled by environment variable for staging
DEBUG = config("DEBUG", default=False, cast=bool)

# Validate SECRET_KEY for production
SECRET_KEY = config("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 50:
    raise ValueError("Production requires a strong SECRET_KEY with at least 50 characters")

# Database Configuration - Use individual environment variables for staging/production
# Use os.environ directly to avoid python-decouple file precedence issues
database_url = os.environ.get("DATABASE_URL") or config("DATABASE_URL", default=None)
if database_url:
    # Use DATABASE_URL if available (DigitalOcean/Railway/Heroku style)
    _parsed_db = dj_database_url.parse(database_url)
    # DigitalOcean may inject DATABASE_URL without database name — default to 'defaultdb'
    if not _parsed_db.get("NAME"):
        _parsed_db["NAME"] = os.environ.get("DATABASE_NAME", "defaultdb")
    DATABASES = {"default": _parsed_db}
else:
    # Use individual database variables (AWS Secrets Manager style)
    database_host = config("DATABASE_HOST")
    # Extract host and port if DATABASE_HOST contains port
    if ":" in database_host:
        host, port = database_host.split(":")
    else:
        host = database_host
        port = config("DATABASE_PORT", default="5432")

    import logging as _logging

    _logging.getLogger(__name__).debug(
        "Database connection: host=%s port=%s (raw DATABASE_HOST=%s)", host, port, database_host
    )

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DATABASE_NAME", default="trazo_staging"),
            "USER": config("DATABASE_USER", default="trazo_staging"),
            "PASSWORD": config("DATABASE_PASSWORD"),
            "HOST": host,
            "PORT": port,
        }
    }

# Get ALLOWED_HOSTS from environment variable or use defaults
allowed_hosts_env = config("ALLOWED_HOSTS", default="api.trazo.io,api-staging.trazo.io,localhost")
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_env.split(",")]

# Add additional hosts from other environment variables
additional_hosts = [
    os.environ.get("LOAD_BALANCER_DNS", ""),
    os.environ.get("RAILWAY_STATIC_URL", ""),
]

# Add non-empty additional hosts
for host in additional_hosts:
    if host and host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

# Add wildcard hosts for PaaS platforms (Django uses leading dot for subdomain wildcards)
if ".railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".railway.app")
if ".ondigitalocean.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".ondigitalocean.app")

CSRF_TRUSTED_ORIGINS = [
    "https://*.trazo.io",
    "https://trazo.io",
    "https://api.trazo.io",
    "https://api-staging.trazo.io",
    # Add ALB domain for staging - using HTTP since ALB doesn't have SSL cert
    "http://staging-alb-1273700937.us-east-2.elb.amazonaws.com",
]

CORS_ORIGIN_ALLOW_ALL = False

CORS_ORIGIN_WHITELIST = [
    "https://app.trazo.io",
    "https://consumer.trazo.io",
    "https://trazo.io",
    "https://app-staging.trazo.io",
    "https://consumer-staging.trazo.io",
    "https://staging.trazo.io",
]
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "https://app.trazo.io",
    "https://consumer.trazo.io",
    "https://trazo.io",
    "https://app-staging.trazo.io",
    "https://consumer-staging.trazo.io",
    "https://staging.trazo.io",
]

CSRF_COOKIE_DOMAIN = "trazo.io"

# When DEBUG is True, disable CSRF cookie security for non-SSL environments
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=not DEBUG, cast=bool)

# Security Headers for Production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Disable SSL redirect for staging (no SSL certificate configured)
# When DEBUG is True, disable SSL redirect by default
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=not DEBUG, cast=bool)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=not DEBUG, cast=bool)
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
SERVER_EMAIL = os.environ.get("FROM_EMAIL_ADDRESS", "noreply@trazo.io")
DEFAULT_FROM_EMAIL = config("FROM_EMAIL_ADDRESS", default="noreply@trazo.io")

# Frontend URL for email links (CTA buttons, upgrade links)
FRONTEND_URL = config("FRONTEND_URL", default="https://app.trazo.io")

# Support email shown in email body copy (distinct from envelope sender)
SUPPORT_EMAIL = config("SUPPORT_EMAIL", default="hello@trazo.io")

SENDGRID_API_KEY = config("SENDGRID_API_KEY", default=None)

EMAIL_HOST = config("EMAIL_HOST", default="smtp.sendgrid.net")
EMAIL_HOST_PASSWORD = SENDGRID_API_KEY
EMAIL_PORT = os.environ.get("EMAIL_PORT", 587)
EMAIL_USE_TLS = False if os.environ.get("EMAIL_DISABLE_TLS") == "True" else True

# Use S3 in production
DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

# Redis Configuration - Remove SSL for Railway internal Redis
REDIS_URL = config("REDIS_URL", default=None)

# Override Celery settings for production - No SSL for Railway internal Redis
if REDIS_URL:
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    # Remove SSL requirements for Railway internal Redis
    CELERY_BROKER_USE_SSL = False
    CELERY_REDIS_BACKEND_USE_SSL = False
else:
    # Disable Celery if no Redis
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_STORE_EAGER_RESULT = True

# Override Redis Cache settings for production - No SSL for Railway internal Redis
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                # Remove SSL requirements for Railway internal Redis
                "SSL": False,
                "CONNECTION_POOL_KWARGS": {"retry_on_timeout": True},
            },
        }
    }
else:
    # Use dummy cache for staging without Redis
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.dummy.DummyCache",
        }
    }

    # Disable django-ratelimit for staging (no shared cache available)
    RATELIMIT_ENABLE = False

    # Remove django-ratelimit from INSTALLED_APPS for staging
    try:
        INSTALLED_APPS.remove("django_ratelimit")
    except ValueError:
        pass  # Already removed

# USDA API Configuration - Use environment variables for security
USDA_NASS_API_KEY = os.environ.get("USDA_NASS_API_KEY", None)
TRAZO_OPERATING_COUNTRY = os.environ.get("TRAZO_OPERATING_COUNTRY", "US")

# API Attribution (required by NASS Terms of Service)
USDA_API_ATTRIBUTION = "This product uses the NASS API but is not endorsed or certified by NASS."

# John Deere API Configuration
JOHN_DEERE_CLIENT_ID = os.environ.get("JOHN_DEERE_CLIENT_ID", None)
JOHN_DEERE_CLIENT_SECRET = os.environ.get("JOHN_DEERE_CLIENT_SECRET", None)
JOHN_DEERE_REDIRECT_URI = os.environ.get("JOHN_DEERE_REDIRECT_URI", "https://api.trazo.io/carbon/john-deere/callback/")
JOHN_DEERE_USE_SANDBOX = os.environ.get("JOHN_DEERE_USE_SANDBOX", "False").lower() == "true"

# Weather API Configuration
NOAA_API_BASE_URL = "https://api.weather.gov"
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

# Blockchain Configuration - REQUIRED in production
BLOCKCHAIN_ENABLED = config("BLOCKCHAIN_ENABLED", default=True, cast=bool)
POLYGON_RPC_URL = config("POLYGON_RPC_URL", default=None)
CARBON_CONTRACT_ADDRESS = config("CARBON_CONTRACT_ADDRESS", default=None)
BLOCKCHAIN_PRIVATE_KEY = config("BLOCKCHAIN_PRIVATE_KEY", default=None)
POLYGON_EXPLORER_URL = config("POLYGON_EXPLORER_URL", default="https://polygonscan.com")

# Force blockchain verification configuration
FORCE_BLOCKCHAIN_VERIFICATION = config("FORCE_BLOCKCHAIN_VERIFICATION", default=False, cast=bool)

# Production blockchain validation
if BLOCKCHAIN_ENABLED:
    required_blockchain_vars = [
        ("POLYGON_RPC_URL", POLYGON_RPC_URL),
        ("CARBON_CONTRACT_ADDRESS", CARBON_CONTRACT_ADDRESS),
        ("BLOCKCHAIN_PRIVATE_KEY", BLOCKCHAIN_PRIVATE_KEY),
    ]

    missing_vars = [var for var, value in required_blockchain_vars if not value]
    if missing_vars:
        # For staging, log warning instead of failing
        environment = config("ENVIRONMENT", default="production")
        if environment == "staging":
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                f"Staging blockchain is enabled but missing environment variables: {', '.join(missing_vars)}. "
                f"Blockchain features may not work properly."
            )
        else:
            raise ValueError(
                f"Production blockchain is enabled but missing required environment variables: {', '.join(missing_vars)}. "
                f"Set these variables or set BLOCKCHAIN_ENABLED=False to disable blockchain features."
            )

# ICR (International Carbon Registry) Configuration
ICR_API_KEY = config("ICR_API_KEY", default=None)
ICR_PRODUCTION_URL = config("ICR_PRODUCTION_URL", default="https://api.carbonregistry.com")
USE_ICR_SANDBOX = config("USE_ICR_SANDBOX", default=False, cast=bool)  # Production uses real API

# AWS Services Configuration
AWS_SERVICES_ENABLED = config("AWS_SERVICES_ENABLED", default=True, cast=bool)
FORCE_AWS_KEY_MANAGEMENT = config("FORCE_AWS_KEY_MANAGEMENT", default=False, cast=bool)
ENVIRONMENT = config("ENVIRONMENT", default="production")

# Override logging configuration for Railway deployment - Console logging only
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[%(asctime)s] %(levelname)s | %(name)s | "
            "%(module)s | %(funcName)s | %(lineno)d | %(message)s",
            "datefmt": "%d/%b/%Y %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "loggers": {
        "backend": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "security": {
            "handlers": ["console"],  # Remove file handler
            "level": "WARNING",
            "propagate": False,
        },
        "django.security.DisallowedHost": {
            "handlers": ["null"],
            "propagate": False,
        },
        "": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": True,
        },
    },
}
