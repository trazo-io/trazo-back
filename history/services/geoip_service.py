"""
Local GeoIP lookup backed by the MaxMind GeoLite2 database.

Replaces the previous ipapi.co HTTP calls, which are unusable from the
DigitalOcean App Platform egress:

    default UA   -> 429 {"error": true, "reason": "RateLimited"}
    browser UA   -> 403 Cloudflare interstitial

The egress IP is shared DigitalOcean space, so the rate limit is not a
function of our own traffic and no amount of retrying clears it. Every
consented scan was silently recorded as country_code="XX" / region="Unknown"
because the caller only branched on ``status_code == 200``.

The local database has no quota, no network round-trip (~microseconds, so it
is safe on the mobile QR path), and — importantly for the consent notice —
does not disclose the visitor's IP to a third-party processor.

The .mmdb files live at ``settings.GEOIP_PATH`` and are checked into the repo.
Refresh them from MaxMind periodically; GeoLite2 accuracy degrades as networks
are reallocated.
"""

import ipaddress
import logging
import os
import threading
from typing import NamedTuple, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

CITY_DB_FILENAME = "GeoLite2-City.mmdb"


class GeoLocation(NamedTuple):
    """Resolved location. Every field may be an empty string."""

    country_code: str  # ISO 3166-1 alpha-2, e.g. "US"
    country_name: str  # e.g. "United States"
    subdivision: str  # State / province / department, e.g. "California"
    city: str  # e.g. "Ventura"


class GeoIPService:
    """
    Thread-safe wrapper around a single ``geoip2.database.Reader``.

    The reader is opened lazily and kept for the process lifetime — it is a
    memory-mapped file, so reopening it per request would be pure waste.
    ``Reader`` is documented as safe for concurrent reads.
    """

    _reader = None
    _lock = threading.Lock()
    _unavailable = False  # latched once the DB is known to be unusable

    @classmethod
    def _get_reader(cls):
        """Return the shared Reader, or None if the database is unusable."""
        if cls._unavailable:
            return None
        if cls._reader is not None:
            return cls._reader

        with cls._lock:
            # Re-check inside the lock: another thread may have won the race.
            if cls._unavailable:
                return None
            if cls._reader is not None:
                return cls._reader

            geoip_path = getattr(settings, "GEOIP_PATH", "")
            if not geoip_path:
                # Distinct from "file missing": joining an empty dir yields a bare
                # relative filename that resolves against the CWD, which produces a
                # baffling error message. Say what is actually wrong.
                cls._unavailable = True
                logger.error("settings.GEOIP_PATH is not set — scan locations will be empty.")
                return None

            db_path = os.path.join(geoip_path, CITY_DB_FILENAME)
            try:
                import geoip2.database

                cls._reader = geoip2.database.Reader(db_path, locales=["en"])
            except Exception:
                # Missing file, unreadable file, corrupt database, or geoip2 not
                # installed. Latch so we log once instead of on every scan, and
                # so a broken deploy degrades to "no location" rather than
                # raising on the public QR endpoint.
                cls._unavailable = True
                logger.error(
                    "GeoIP database unavailable at %s — scan locations will be empty. "
                    "Confirm geoip_data/ ships with the deployment.",
                    db_path,
                    exc_info=True,
                )
                return None

            logger.info("GeoIP database opened: %s", db_path)
            return cls._reader

    @staticmethod
    def is_resolvable_ip(ip: Optional[str]) -> bool:
        """
        False for addresses that can never carry a meaningful location — loopback,
        RFC1918, link-local, CGNAT, unspecified, reserved, multicast. Checking here
        keeps the "not found" debug line meaningful instead of firing on every local
        request.

        `is_global` covers all of those EXCEPT multicast, which it reports as True
        (224.0.0.1 is globally routable in principle). A multicast source address is
        nonsense on an inbound request, so it is excluded explicitly.
        """
        if not ip:
            return False
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return parsed.is_global and not parsed.is_multicast

    @classmethod
    def lookup(cls, ip: Optional[str]) -> Optional[GeoLocation]:
        """
        Resolve an IP to a GeoLocation, or None.

        None means "could not resolve" for every reason — no database, private
        address, address absent from the database. Callers must treat it as
        missing data, never as an error worth failing the request over.
        """
        if not cls.is_resolvable_ip(ip):
            return None

        reader = cls._get_reader()
        if reader is None:
            return None

        try:
            response = reader.city(ip)
        except Exception as exc:
            # geoip2.errors.AddressNotFoundError is the common, expected case;
            # anything else is genuinely unexpected but still must not break a
            # scan. Debug level keeps unresolvable-IP noise out of production
            # logs while leaving the failure visible when it matters.
            logger.debug("GeoIP lookup failed for a scan: %s", exc.__class__.__name__)
            return None

        return GeoLocation(
            country_code=(response.country.iso_code or "").upper(),
            country_name=response.country.name or "",
            subdivision=response.subdivisions.most_specific.name or "",
            city=response.city.name or "",
        )
