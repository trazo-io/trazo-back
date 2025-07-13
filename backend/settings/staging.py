# Staging-specific settings
# This file provides a secure staging environment configuration

from backend.settings.base import *
from decouple import config
import dj_database_url
import os

# Staging environment identifier
ENVIRONMENT = 'staging'

# Override URL configurations for staging
from backend.subdomain_config import get_frontend_urls
_staging_urls = get_frontend_urls()
BASE_APP_URL = _staging_urls['BASE_APP_URL']
BASE_CONSUMER_URL = _staging_urls['BASE_CONSUMER_URL']

# Override production settings for staging
# NEVER set DEBUG=True in any deployed environment
DEBUG = False

# Validate SECRET_KEY for staging
SECRET_KEY = config('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 50:
    raise ValueError("Staging requires a strong SECRET_KEY with at least 50 characters")

# Database Configuration - Use individual environment variables for staging
if config('DATABASE_URL', default=None):
    # Use DATABASE_URL if available (Railway/Heroku style)
    DATABASES = {
        'default': dj_database_url.parse(config('DATABASE_URL'))
    }
else:
    # Use individual database variables (AWS Secrets Manager style)
    database_host = config('DATABASE_HOST')
    # Extract host and port if DATABASE_HOST contains port
    if ':' in database_host:
        host, port = database_host.split(':')
    else:
        host = database_host
        port = config('DATABASE_PORT', default='5432')
        
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DATABASE_NAME', default='trazo_staging'),
            'USER': config('DATABASE_USER', default='trazo_staging'),
            'PASSWORD': config('DATABASE_PASSWORD'),
            'HOST': host,
            'PORT': port,
        }
    }

# Get ALLOWED_HOSTS from environment variable or use defaults
allowed_hosts_env = config("ALLOWED_HOSTS", default="api-staging.trazo.io,localhost")
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_env.split(",")]

# Add additional hosts from other environment variables
additional_hosts = [
    os.environ.get("LOAD_BALANCER_DNS", ""),
    "staging-alb-1273700937.us-east-2.elb.amazonaws.com",  # ALB DNS name for staging
]

# Add non-empty additional hosts
for host in additional_hosts:
    if host and host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)

# Staging-specific security settings
# Relaxed for staging environment with self-signed certificates
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=False, cast=bool)
CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=False, cast=bool)

# CORS configuration for staging
CORS_ORIGIN_ALLOW_ALL = True
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    "http://staging-alb-1273700937.us-east-2.elb.amazonaws.com",
    "https://staging-alb-1273700937.us-east-2.elb.amazonaws.com",
    "http://localhost:3000",
    "https://localhost:3000",
]

# CSRF configuration for staging - allow environment variable override
csrf_trusted_origins_env = config('CSRF_TRUSTED_ORIGINS', default='')
CSRF_COOKIE_DOMAIN = config('CSRF_COOKIE_DOMAIN', default=None)  # Allow any domain in staging

# Default staging trusted origins
default_trusted_origins = [
    'http://staging-alb-1273700937.us-east-2.elb.amazonaws.com',
    'https://staging-alb-1273700937.us-east-2.elb.amazonaws.com',
    'http://localhost:8000',
    'https://localhost:8000',
]

# Add environment variable origins if provided
if csrf_trusted_origins_env:
    env_origins = [origin.strip() for origin in csrf_trusted_origins_env.split(',')]
    CSRF_TRUSTED_ORIGINS = default_trusted_origins + env_origins
else:
    CSRF_TRUSTED_ORIGINS = default_trusted_origins

# Disable problematic security headers for staging
CSRF_COOKIE_SAMESITE = 'Lax'  # More permissive than 'Strict'
SESSION_COOKIE_SAMESITE = 'Lax'

# Security Headers for staging (relaxed)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = False  # Relaxed for staging
SECURE_HSTS_PRELOAD = False  # Relaxed for staging
SECURE_HSTS_SECONDS = 3600  # 1 hour instead of 1 year
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# Email configuration for staging
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"  # Console for staging
SERVER_EMAIL = os.environ.get("FROM_EMAIL_ADDRESS", "osmunogue@gmail.com")
DEFAULT_FROM_EMAIL = config("FROM_EMAIL_ADDRESS", "osmunogue@gmail.com")

# Storage configuration for staging
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

# Staging logging configuration - more verbose than production
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',  # Log 4XX and 5XX responses
            'propagate': False,
        },
        'backend': {
            'handlers': ['console'],
            'level': 'DEBUG',  # More verbose for our app code
            'propagate': False,
        },
    },
}

# Email settings for staging - use console backend to prevent accidental emails
if config('USE_CONSOLE_EMAIL', default=True, cast=bool):
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Cache configuration for staging
REDIS_URL = config('REDIS_URL', default=None)

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'SSL': False,  # No SSL for staging Redis
                'CONNECTION_POOL_KWARGS': {"retry_on_timeout": True},
            },
            'TIMEOUT': 300,  # 5 minutes default timeout
        }
    }
else:
    # Use dummy cache for staging without Redis
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    }
    
    # Disable django-ratelimit for staging (no shared cache available)
    RATELIMIT_ENABLE = False

# Staging-specific feature flags
FEATURES = {
    'ENABLE_BLOCKCHAIN_VERIFICATION': config('ENABLE_BLOCKCHAIN_VERIFICATION', default=False, cast=bool),
    'ENABLE_AI_VOICE_PROCESSING': config('ENABLE_AI_VOICE_PROCESSING', default=False, cast=bool),
    'ENABLE_CARBON_CREDITS': config('ENABLE_CARBON_CREDITS', default=False, cast=bool),
}

# Performance settings for staging
# Less aggressive than production to help with debugging
CONN_MAX_AGE = 300  # 5 minutes instead of 600

# Static files - ensure proper serving in staging
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
WHITENOISE_AUTOREFRESH = True  # Auto-refresh static files in staging