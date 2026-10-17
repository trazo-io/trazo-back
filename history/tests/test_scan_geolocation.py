"""
Scan geolocation resolves locally, and never without consent.

WHY THIS EXISTS
---------------
The "Ubicación" column on the producer dashboard was empty for every scan in
production. The cause took four layers to reach, and each layer was silent:

  1. Consent is read from the `trazo-analytics-consent` cookie ONLY. Without it
     `process_scan_consent` returns early with country_code="XX" — correct, but
     indistinguishable downstream from a failed lookup.
  2. With consent, the code called ipapi.co over HTTPS. From the DigitalOcean
     App Platform egress that returns 429 RateLimited (shared egress IP — not a
     function of our own traffic) and 403 behind Cloudflare for any non-browser
     User-Agent. Permanently. No retry clears it.
  3. The caller branched only on `status_code == 200`, with no `else`, and wrapped
     everything in `except Exception: pass` — no log line on any failure path.
  4. So a permanently-dead dependency produced exactly the same rows as a
     visitor who declined analytics.

No test existed for any of it. These lock down the parts that were wrong.

WHAT THIS DOES NOT COVER
------------------------
Whether the .mmdb file ships with the deployment — that is a packaging property
of the image, not of this code. `test_geoip_database_is_present_and_usable`
asserts it for the local checkout only; it will pass locally and tell you
nothing about prod. Verify prod separately.
"""

import ipaddress
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, RequestFactory, TestCase
from django.utils import timezone

from history.models import History, HistoryScan
from history.services.geoip_service import GeoIPService, GeoLocation
from history.services.privacy_service import PrivacyService

CONSENT_COOKIE = "trazo-analytics-consent"

# Documented MaxMind test address; also a stable real-world lookup.
PUBLIC_IP = "8.8.8.8"


def _request(consent=None, ip=PUBLIC_IP):
    factory = RequestFactory()
    request = factory.post("/api/public_scans/", HTTP_DO_CONNECTING_IP=ip)
    if consent is not None:
        request.COOKIES[CONSENT_COOKIE] = consent
    return request


class GeoIPServiceTests(TestCase):
    def setUp(self):
        # The reader is a process-lifetime singleton with a latched failure flag.
        # Reset it so one test's simulated outage cannot leak into the next.
        GeoIPService._reader = None
        GeoIPService._unavailable = False

    def test_private_and_malformed_addresses_are_not_resolvable(self):
        for ip in [
            "127.0.0.1",  # loopback
            "10.0.0.5",  # RFC1918
            "192.168.1.1",  # RFC1918
            "169.254.1.1",  # link-local
            "100.64.0.1",  # CGNAT — a real client can sit behind this, but it has no location
            "0.0.0.0",  # unspecified
            "224.0.0.1",  # multicast — is_global reports True for this, hence the extra check
            "fd00::1",  # IPv6 unique-local
            "",
            "not-an-ip",
        ]:
            self.assertFalse(GeoIPService.is_resolvable_ip(ip), f"{ip!r} should not be resolvable")

    def test_public_address_is_resolvable(self):
        self.assertTrue(GeoIPService.is_resolvable_ip(PUBLIC_IP))
        self.assertTrue(GeoIPService.is_resolvable_ip("2001:4860:4860::8888"))

    def test_lookup_returns_none_instead_of_raising_when_database_missing(self):
        """A broken deploy must degrade to 'no location', never 500 the public QR endpoint."""
        with self.settings(GEOIP_PATH="/nonexistent/path"):
            GeoIPService._reader = None
            GeoIPService._unavailable = False
            self.assertIsNone(GeoIPService.lookup(PUBLIC_IP))

    def test_lookup_never_calls_out_over_the_network(self):
        """
        The whole point of the change. If someone reintroduces an HTTP
        geolocation call, this fails.
        """
        with patch("requests.get") as mock_get:
            GeoIPService.lookup(PUBLIC_IP)
            mock_get.assert_not_called()


class ClientIPResolutionTests(TestCase):
    """
    The left-most X-Forwarded-For entry is attacker-controlled — a proxy APPENDS to
    that header, so a client that sends `X-Forwarded-For: 8.8.8.8` arrives as
    "8.8.8.8, <real client>". While geolocation was broken this was inert. Now that
    it resolves, a forged header would paint a location of the caller's choosing onto
    a farmer's dashboard and poison the `ip_hash` that dedup and rate limiting key on.
    """

    def test_edge_header_wins_over_forged_forwarded_for(self):
        request = RequestFactory().post(
            "/api/public_scans/",
            HTTP_X_FORWARDED_FOR="8.8.8.8",  # forged by the caller
            HTTP_DO_CONNECTING_IP="203.0.113.7",  # overwritten by DigitalOcean's edge
        )
        self.assertEqual(PrivacyService.get_client_ip(request), "203.0.113.7")

    def test_forwarded_for_is_never_read(self):
        request = RequestFactory().post(
            "/api/public_scans/", HTTP_X_FORWARDED_FOR="8.8.8.8, 10.0.0.1", REMOTE_ADDR="203.0.113.7"
        )
        self.assertEqual(PrivacyService.get_client_ip(request), "203.0.113.7")

    def test_falls_back_to_remote_addr_when_no_proxy_headers(self):
        request = RequestFactory().post("/api/public_scans/", REMOTE_ADDR="203.0.113.7")
        self.assertEqual(PrivacyService.get_client_ip(request), "203.0.113.7")

    def test_malformed_header_yields_none_rather_than_a_bogus_lookup(self):
        request = RequestFactory().post("/api/public_scans/", HTTP_DO_CONNECTING_IP="not-an-ip")
        self.assertIsNone(PrivacyService.get_client_ip(request))


class ScanConsentGeolocationTests(TestCase):
    def setUp(self):
        GeoIPService._reader = None
        GeoIPService._unavailable = False

    def test_no_consent_skips_geolocation_entirely(self):
        with patch.object(GeoIPService, "lookup") as mock_lookup:
            data = PrivacyService.process_scan_consent(_request(consent=None))

        mock_lookup.assert_not_called()
        self.assertFalse(data["consent_given"])
        self.assertEqual(data["country_code"], "XX")
        self.assertEqual(data["region"], "Unknown")
        self.assertEqual(data["ip_hash"], "")

    def test_declined_consent_skips_geolocation_entirely(self):
        with patch.object(GeoIPService, "lookup") as mock_lookup:
            data = PrivacyService.process_scan_consent(_request(consent="false"))

        mock_lookup.assert_not_called()
        self.assertFalse(data["consent_given"])
        self.assertEqual(data["country_code"], "XX")

    def test_consent_resolves_country_and_region(self):
        resolved = GeoLocation(
            country_code="US",
            country_name="United States",
            subdivision="California",
            city="Ventura",
        )
        with patch.object(GeoIPService, "lookup", return_value=resolved):
            data = PrivacyService.process_scan_consent(_request(consent="true"))

        self.assertTrue(data["consent_given"])
        self.assertEqual(data["country_code"], "US")
        # region is the SUBDIVISION, not the city — see the field's help_text.
        self.assertEqual(data["region"], "California")
        self.assertNotEqual(data["ip_hash"], "")

    def test_body_supplied_location_is_ignored(self):
        """
        A public unauthenticated endpoint must not let the caller choose the
        location its farmer sees on the dashboard.
        """
        request = _request(consent="true")
        request.data = {"city": "Napa", "country": "United States"}

        with patch.object(GeoIPService, "lookup", return_value=None):
            data = PrivacyService.process_scan_consent(request)

        self.assertEqual(data["country_code"], "XX")
        self.assertEqual(data["region"], "Unknown")

    def test_failed_lookup_falls_back_to_placeholders_without_raising(self):
        with patch.object(GeoIPService, "lookup", return_value=None):
            data = PrivacyService.process_scan_consent(_request(consent="true"))

        self.assertTrue(data["consent_given"])
        self.assertEqual(data["country_code"], "XX")
        self.assertEqual(data["region"], "Unknown")

    def test_legacy_columns_are_never_written(self):
        resolved = GeoLocation("UY", "Uruguay", "Canelones", "Barros Blancos")
        with patch.object(GeoIPService, "lookup", return_value=resolved):
            data = PrivacyService.process_scan_consent(_request(consent="true"))

        # Raw IP storage is the thing the privacy service exists to prevent.
        self.assertIsNone(data["ip_address"])
        self.assertIsNone(data["city"])
        self.assertIsNone(data["country"])


class GeoIPDatabaseTests(TestCase):
    """
    Local-checkout assertions. These say nothing about the deployed image.
    """

    def setUp(self):
        GeoIPService._reader = None
        GeoIPService._unavailable = False

    def test_geoip_database_is_present_and_usable(self):
        location = GeoIPService.lookup(PUBLIC_IP)
        self.assertIsNotNone(
            location,
            "GeoLite2-City.mmdb did not resolve a known public IP. " "Check geoip_data/ and settings.GEOIP_PATH.",
        )
        self.assertEqual(len(location.country_code), 2)
        self.assertTrue(location.country_code.isalpha())

    def test_resolved_country_code_is_a_real_iso_code(self):
        """
        The removed `extract_region_from_location` fell back to country[:2].upper(),
        inventing codes like "PO" for Portugal that passed the != "XX" check and
        rendered as plausible garbage. A real database cannot do that.
        """
        location = GeoIPService.lookup(PUBLIC_IP)
        self.assertIsNotNone(location)
        self.assertNotEqual(location.country_code, "XX")
        self.assertEqual(location.country_code, location.country_code.upper())

    def test_private_ip_yields_no_location(self):
        self.assertIsNone(GeoIPService.lookup("127.0.0.1"))
        self.assertIsNone(GeoIPService.lookup(str(ipaddress.ip_address("10.1.2.3"))))


class ConsentUpgradeTests(TestCase):
    """
    `POST public_scans/consent/` — attaches consented analytics to a row that was
    already written anonymously, because the scan POSTs on mount and the banner
    renders after it. Without this, first-visit QR traffic can never carry consent,
    and first visit is the only visit.
    """

    def setUp(self):
        GeoIPService._reader = None
        GeoIPService._unavailable = False
        self.history = History.objects.create(name="Consent Upgrade Production", published=True)
        self.url = "/api/public_scans/consent/"
        self.resolved = GeoLocation("UY", "Uruguay", "Canelones", "Barros Blancos")

    def _anonymous_scan(self):
        """A scan as `create` writes it before the banner is actioned."""
        return HistoryScan.objects.create(
            history=self.history,
            **PrivacyService.process_scan_consent(_request(consent=None)),
        )

    def _post(self, payload, consent=None):
        client = Client(HTTP_DO_CONNECTING_IP=PUBLIC_IP)
        if consent is not None:
            client.cookies[CONSENT_COOKIE] = consent
        return client.post(self.url, data=payload, content_type="application/json")

    def test_upgrade_fills_location_on_the_existing_row(self):
        scan = self._anonymous_scan()
        self.assertFalse(scan.consent_given)
        self.assertEqual(scan.country_code, "XX")

        with patch.object(GeoIPService, "lookup", return_value=self.resolved):
            response = self._post({"claim_token": scan.claim_token}, consent="true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "upgraded")

        scan.refresh_from_db()
        self.assertTrue(scan.consent_given)
        self.assertEqual(scan.country_code, "UY")
        self.assertEqual(scan.region, "Canelones")
        self.assertNotEqual(scan.ip_hash, "")

    def test_upgrade_does_not_create_a_second_row(self):
        """The whole reason for upgrading rather than re-POSTing: the count must not move."""
        scan = self._anonymous_scan()
        before = HistoryScan.objects.count()

        with patch.object(GeoIPService, "lookup", return_value=self.resolved):
            self._post({"claim_token": scan.claim_token}, consent="true")

        self.assertEqual(HistoryScan.objects.count(), before)

    def test_cookie_is_the_authority_not_the_body(self):
        """A valid token with no consent cookie must change nothing."""
        scan = self._anonymous_scan()

        with patch.object(GeoIPService, "lookup", return_value=self.resolved) as mock_lookup:
            response = self._post(
                {"claim_token": scan.claim_token, "explicit_consent": True, "country": "United States"},
                consent=None,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "no_consent")
        mock_lookup.assert_not_called()

        scan.refresh_from_db()
        self.assertFalse(scan.consent_given)
        self.assertEqual(scan.country_code, "XX")

    def test_wrong_token_cannot_upgrade_another_visitors_scan(self):
        scan = self._anonymous_scan()

        with patch.object(GeoIPService, "lookup", return_value=self.resolved):
            response = self._post({"claim_token": "not-a-real-token"}, consent="true")

        self.assertEqual(response.status_code, 404)
        scan.refresh_from_db()
        self.assertFalse(scan.consent_given)

    def test_scan_id_is_not_accepted_as_an_identifier(self):
        """Identification is by opaque token only — there is nothing to enumerate."""
        scan = self._anonymous_scan()

        with patch.object(GeoIPService, "lookup", return_value=self.resolved):
            response = self._post({"id": scan.id, "scan_id": scan.id}, consent="true")

        self.assertEqual(response.status_code, 400)
        scan.refresh_from_db()
        self.assertFalse(scan.consent_given)

    def test_expired_scan_cannot_be_upgraded(self):
        """A hoarded token must not attach a location to a visit that is long over."""
        scan = self._anonymous_scan()
        HistoryScan.objects.filter(pk=scan.pk).update(date=timezone.now() - timedelta(hours=2))

        with patch.object(GeoIPService, "lookup", return_value=self.resolved):
            response = self._post({"claim_token": scan.claim_token}, consent="true")

        self.assertEqual(response.status_code, 404)
        scan.refresh_from_db()
        self.assertFalse(scan.consent_given)

    def test_upgrade_is_idempotent(self):
        """A double-fired banner event must not re-stamp consent_timestamp."""
        scan = self._anonymous_scan()

        with patch.object(GeoIPService, "lookup", return_value=self.resolved):
            self._post({"claim_token": scan.claim_token}, consent="true")
            scan.refresh_from_db()
            first_timestamp = scan.consent_timestamp

            response = self._post({"claim_token": scan.claim_token}, consent="true")

        self.assertEqual(response.json()["status"], "already_consented")
        scan.refresh_from_db()
        self.assertEqual(scan.consent_timestamp, first_timestamp)

    def test_missing_token_is_rejected(self):
        for payload in [{}, {"claim_token": ""}, {"claim_token": "   "}, {"claim_token": None}]:
            response = self._post(payload, consent="true")
            self.assertEqual(response.status_code, 400, f"payload {payload!r} should be rejected")
