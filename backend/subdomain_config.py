# Subdomain Configuration
# This file defines subdomain constants for different environments

from urllib.parse import urlparse

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
def get_current_subdomains(environment=None):
    """Return the subdomain configuration for `environment` (default: the module-level one)."""
    return SUBDOMAIN_CONFIG.get(environment or ENVIRONMENT, SUBDOMAIN_CONFIG["development"])


# Export subdomain constants for current environment
_current_config = get_current_subdomains()
APP_SUBDOMAIN = _current_config["APP_SUBDOMAIN"]
CONSUMER_SUBDOMAIN = _current_config["CONSUMER_SUBDOMAIN"]


# Frontend URL configurations based on environment
def get_frontend_urls(environment=None):
    """Return frontend URL configuration for `environment` (default: the module-level one).

    The `environment` argument exists so that a settings module which already KNOWS which
    environment it is can say so, instead of inheriting the "development" fallback above.
    `ENVIRONMENT` here is read at import time and defaults to "development"; prod.py is
    imported after that has already happened, so without this argument production silently
    inherits localhost URLs whenever the ENVIRONMENT env var is unset. See prod.py.
    """
    environment = environment or ENVIRONMENT
    subdomains = get_current_subdomains(environment)
    app, consumer = subdomains["APP_SUBDOMAIN"], subdomains["CONSUMER_SUBDOMAIN"]

    base_urls = {
        "development": {
            "BASE_APP_URL": f"http://{app}.localhost:3000/",
            "BASE_CONSUMER_URL": f"http://{consumer}.localhost:3000/",
        },
        "staging": {
            "BASE_APP_URL": f"https://{app}.trazo.io/",
            "BASE_CONSUMER_URL": f"https://{consumer}.trazo.io/",
        },
        "production": {
            "BASE_APP_URL": f"https://{app}.trazo.io/",
            "BASE_CONSUMER_URL": f"https://{consumer}.trazo.io/",
        },
    }

    return base_urls.get(environment, base_urls["development"])


# Hosts that are unreachable from a consumer's phone or a mail client.
NON_PUBLIC_HOSTS = frozenset({"localhost", "0.0.0.0", "::1", "::"})


def is_non_public_host(hostname):
    """True when `hostname` cannot be reached from outside the machine serving it."""
    if not hostname:
        return False
    # urlparse leaves IPv6 literals bracketed in netloc but not in .hostname; strip anyway
    # so this is safe to call with either.
    hostname = hostname.strip().strip("[]").lower()
    if hostname in NON_PUBLIC_HOSTS:
        return True
    # `consumer.localhost` — the shape this project actually uses in development.
    if hostname.endswith(".localhost"):
        return True
    # The whole 127.0.0.0/8 loopback range, not just 127.0.0.1.
    return hostname.startswith("127.")


def find_non_public_urls(urls):
    """Return ``["NAME=value", ...]`` for every URL pointing at a non-public host.

    Used by deployed settings as a boot-time guard. These URLs are baked into printed QR
    codes and outbound email links, so a localhost value is not a degraded experience —
    it is unrecallable dead output. Empty list means every URL is publicly reachable.

    Matches on the parsed HOSTNAME, not on a substring of the URL: a legitimate public host
    may contain "localhost" (``localhost.example.com``) and a legitimate public URL may carry
    one in a query parameter (``?next=http://localhost``). Neither is a misconfiguration, and
    failing a deploy over one would be its own outage.
    """
    offenders = []
    for name, value in urls.items():
        if not value:
            # An unset URL is a different failure, caught by whatever consumes it. This guard
            # is only about values that ARE set and point somewhere unreachable.
            continue
        parsed = urlparse(str(value))
        # A bare "localhost:3000" with no scheme parses as scheme="localhost" with no
        # hostname, so fall back to treating the raw value as a host.
        hostname = parsed.hostname or str(value).split("/")[0].split(":")[0]
        if is_non_public_host(hostname):
            offenders.append(f"{name}={value}")
    return sorted(offenders)
