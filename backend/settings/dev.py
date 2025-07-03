import os

from backend.settings.base import *
from decouple import config

ALLOWED_HOSTS = ("localhost", ".localhost", "127.0.0.1", "192.168.1.3", "7172-167-60-250-132.ngrok-free.app", "testserver")

# Database configuration for local development
# Use PostgreSQL if Docker services are running, fallback to SQLite

# Check if PostgreSQL is available (Docker services running)
try:
    import psycopg2
    from decouple import config
    
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DATABASE_NAME', default='trazo_dev'),
            'USER': config('DATABASE_USER', default='postgres'),
            'PASSWORD': config('DATABASE_PASSWORD', default='postgres'),
            'HOST': config('DATABASE_HOST', default='localhost'),
            'PORT': config('DATABASE_PORT', default='5432'),
        }
    }
    
    # Redis Cache Configuration
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": config('REDIS_URL', default='redis://localhost:6379/1'),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            }
        }
    }
    
    # Celery Configuration with Redis
    CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
    CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
    
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
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db_dev.sqlite3',
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
    CELERY_BROKER_URL = 'memory://'  # In-memory broker for development
    CELERY_RESULT_BACKEND = 'cache+memory://'
    
    # Use console backend to print emails to terminal instead of sending them
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# CSRF_TRUSTED_ORIGINS = [
#     "http://localhost:3000",
#     "http://app.localhost:3000",
#     "http://app.192.168.1.3:3000",
#     "http://localhost:8000",
# ]

CSRF_TRUSTED_ORIGINS = ["https://*.localhost", "http://app.localhost:3000", "https://7172-167-60-250-132.ngrok-free.app"]

CORS_ORIGIN_ALLOW_ALL = True

CORS_ORIGIN_WHITELIST = [
    # "http://localhost:3000",
    "http://app.localhost:3000",
    "http://app.192.168.1.3:3000",
    "https://7172-167-60-250-132.ngrok-free.app",
    # "http://127.0.0.1:3000",
]
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    # "http://localhost:3000",
    "http://app.localhost:3000",
    "http://app.192.168.1.3:3000",
    "https://7172-167-60-250-132.ngrok-free.app",
]

# Fix for development - allow cross-subdomain cookies and HTTP
CSRF_COOKIE_DOMAIN = None  # Allow cookies to work across app.localhost and localhost
CSRF_COOKIE_SECURE = False  # Allow HTTP in development

# Email configuration for development
# Use console backend to print emails to terminal instead of sending them
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SERVER_EMAIL = os.environ.get("FROM_EMAIL_ADDRESS", "info@trazo.io")
DEFAULT_FROM_EMAIL = os.environ.get("FROM_EMAIL_ADDRESS", "info@trazo.io")

# SMTP settings (commented out for development)
# EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
# EMAIL_PORT = 1025
# EMAIL_HOST = "localhost"
# EMAIL_USE_TLS = False
# EMAIL_HOST_USER = None
# EMAIL_HOST_PASSWORD = None

# Use local filesystem in development
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# Note: Using Redis and Celery services from Docker for consistency
# Cache and Celery are already configured above in the PostgreSQL section

# John Deere API Configuration
JOHN_DEERE_CLIENT_ID = os.environ.get('JOHN_DEERE_CLIENT_ID', 'test_client_id')
JOHN_DEERE_CLIENT_SECRET = os.environ.get('JOHN_DEERE_CLIENT_SECRET', 'test_client_secret')
JOHN_DEERE_REDIRECT_URI = os.environ.get('JOHN_DEERE_REDIRECT_URI', 'http://localhost:8000/carbon/john-deere/callback/')
JOHN_DEERE_USE_SANDBOX = os.environ.get('JOHN_DEERE_USE_SANDBOX', 'True').lower() == 'true'

# Weather API Configuration
# NOAA Weather Service (free, no API key required for US locations)
NOAA_API_BASE_URL = "https://api.weather.gov"

# OpenWeatherMap (backup service, requires API key)
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', None)
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5"

# Weather alert thresholds (can be customized per establishment)
WEATHER_ALERT_THRESHOLDS = {
    'high_temp': 85,  # Fahrenheit
    'low_temp': 35,   # Fahrenheit
    'high_wind': 20,  # mph
    'low_humidity': 30,  # percentage
    'high_humidity': 85  # percentage
}

# USDA API Configuration - Use environment variables for security
USDA_NASS_API_KEY = os.environ.get('USDA_NASS_API_KEY', None)
USDA_ERS_API_KEY = os.environ.get('USDA_ERS_API_KEY', None)
USDA_FOODDATA_API_KEY = os.environ.get('USDA_FOODDATA_API_KEY', None)

# API Attribution (required by NASS Terms of Service)
USDA_API_ATTRIBUTION = "This product uses the NASS API but is not endorsed or certified by NASS."
