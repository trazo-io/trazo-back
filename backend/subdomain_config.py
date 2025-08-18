# Subdomain Configuration
# This file defines subdomain constants for different environments

from decouple import config

# Environment identifier
ENVIRONMENT = config("ENVIRONMENT", default="development")

# Subdomain configurations by environment
SUBDOMAIN_CONFIG = {
    "development": {
        "APP_SUBDOMAIN": "app",
        "CONSUMER_SUBDOMAIN": "consumer",
    },
    "staging": {
        "APP_SUBDOMAIN": "app-staging",
        "CONSUMER_SUBDOMAIN": "consumer-staging",
    },
    "production": {
        "APP_SUBDOMAIN": "app",
        "CONSUMER_SUBDOMAIN": "consumer",
    },
}


# Get current environment subdomain configuration
def get_current_subdomains():
    """Return the subdomain configuration for the current environment"""
    return SUBDOMAIN_CONFIG.get(ENVIRONMENT, SUBDOMAIN_CONFIG["development"])


# Export subdomain constants for current environment
_current_config = get_current_subdomains()
APP_SUBDOMAIN = _current_config["APP_SUBDOMAIN"]
CONSUMER_SUBDOMAIN = _current_config["CONSUMER_SUBDOMAIN"]


# Frontend URL configurations based on environment
def get_frontend_urls():
    """Return frontend URL configuration for the current environment"""
    base_urls = {
        "development": {
            "BASE_APP_URL": f"http://{APP_SUBDOMAIN}.localhost:3000/",
            "BASE_CONSUMER_URL": f"http://{CONSUMER_SUBDOMAIN}.localhost:3000/",
        },
        "staging": {
            "BASE_APP_URL": f"https://{APP_SUBDOMAIN}.trazo.io/",
            "BASE_CONSUMER_URL": f"https://{CONSUMER_SUBDOMAIN}.trazo.io/",
        },
        "production": {
            "BASE_APP_URL": f"https://{APP_SUBDOMAIN}.trazo.io/",
            "BASE_CONSUMER_URL": f"https://{CONSUMER_SUBDOMAIN}.trazo.io/",
        },
    }

    return base_urls.get(ENVIRONMENT, base_urls["development"])
