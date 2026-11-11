"""Rate limits count against an address the client cannot choose, and the auth endpoints have them.

Written 2026-10-17. Two defects, both measured:
  - production showed a forged `X-Forwarded-For: 198.51.100.9` arriving untouched while a forged
    `DO-Connecting-IP` was overwritten by DigitalOcean's edge, and fourteen copies of "take the
    first X-Forwarded-For entry" keyed every IP limiter on the forged value;
  - the `login`, `signup` and `password_reset` rates were declared and consumed by no view.
"""

import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import resolve
from django.utils.module_loading import import_string

from rest_framework.throttling import SimpleRateThrottle

from backend.security.checks import _SECURITY_CRITICAL_SCOPES
from backend.security.client_ip import client_ip, throttle_ident
from backend.security.throttling import (
    ClientIPMixin,
    LoginRateThrottle,
    PasswordResetRateThrottle,
    ResendVerificationRateThrottle,
    SignupRateThrottle,
    VerifyEmailRateThrottle,
    throttle_cache,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LOCMEM = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "throttle": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "throttle"},
}
RATES = {
    "anon": "1000/minute",
    "user": "1000/minute",
    "login": "3/minute",
    "signup": "2/minute",
    "password_reset": "3/hour",
}


class ClientIPTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_edge_header_wins_over_forged_forwarded_for(self):
        request = self.factory.get("/", HTTP_DO_CONNECTING_IP="203.0.113.7", HTTP_X_FORWARDED_FOR="198.51.100.9")
        self.assertEqual(client_ip(request), "203.0.113.7")

    def test_forwarded_for_is_ignored_without_the_edge_header(self):
        request = self.factory.get("/", HTTP_X_FORWARDED_FOR="198.51.100.9", REMOTE_ADDR="192.0.2.1")
        self.assertEqual(client_ip(request), "192.0.2.1")

    def test_ipv6_clients_share_a_bucket_per_64(self):
        a = self.factory.get("/", HTTP_DO_CONNECTING_IP="2001:db8:1:2::1")
        b = self.factory.get("/", HTTP_DO_CONNECTING_IP="2001:db8:1:2:ffff:ffff:ffff:ffff")
        other = self.factory.get("/", HTTP_DO_CONNECTING_IP="2001:db8:1:3::1")
        self.assertEqual(throttle_ident(a), "2001:db8:1:2::/64")
        self.assertEqual(throttle_ident(a), throttle_ident(b))
        self.assertNotEqual(throttle_ident(a), throttle_ident(other))

    def test_ipv4_stays_per_address(self):
        request = self.factory.get("/", HTTP_DO_CONNECTING_IP="203.0.113.7")
        self.assertEqual(throttle_ident(request), "203.0.113.7")


class NoOtherCodeReadsForwardedForTests(SimpleTestCase):
    """NEVER: a second reader of X-Forwarded-For brings back a limiter the client can reset."""

    def test_only_client_ip_reads_the_header(self):
        allowed = BACKEND_ROOT / "backend" / "security" / "client_ip.py"
        skip = {".venv", ".claude", "node_modules", "migrations", "tests"}
        pattern = re.compile(r"HTTP_X_FORWARDED_FOR|HTTP_CF_CONNECTING_IP|HTTP_X_REAL_IP|HTTP_X_CLIENT_IP")
        scanned, offenders = 0, []
        for path in BACKEND_ROOT.rglob("*.py"):
            if skip & set(path.relative_to(BACKEND_ROOT).parts) or path.name.startswith("test_"):
                continue
            scanned += 1
            if path != allowed and pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(BACKEND_ROOT)))
        self.assertGreater(scanned, 200, "the walk read almost nothing; the guard would pass vacuously")
        self.assertEqual(offenders, [])

    def test_default_throttles_key_on_the_client_ip(self):
        for dotted in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"]:
            self.assertTrue(issubclass(import_string(dotted), ClientIPMixin), dotted)


class AuthEndpointsAreThrottledTests(SimpleTestCase):
    def _throttles(self, path, method="post"):
        match = resolve(path)
        view_cls = match.func.cls
        action = match.func.actions[method]
        handler = getattr(view_cls, action)
        kwargs = getattr(handler, "kwargs", {})
        return kwargs.get("throttle_classes", view_cls.throttle_classes)

    def test_each_security_critical_scope_guards_its_endpoint(self):
        wired = {
            "/api/auth/login/": LoginRateThrottle,
            "/api/auth/register/": SignupRateThrottle,
            "/api/users/request_password_reset/": PasswordResetRateThrottle,
            "/api/users/verify_email/": VerifyEmailRateThrottle,
            "/api/users/resend_verification_email/": ResendVerificationRateThrottle,
        }
        self.assertEqual({t.scope for t in wired.values()}, set(_SECURITY_CRITICAL_SCOPES))
        for path, throttle in wired.items():
            self.assertIn(throttle, self._throttles(path), path)


@override_settings(CACHES=LOCMEM)
@patch.object(SimpleRateThrottle, "THROTTLE_RATES", RATES)
class LoginThrottleBehaviourTests(TestCase):
    URL = "/api/auth/login/"

    def setUp(self):
        cache.clear()
        throttle_cache().clear()

    def _post(self, **headers):
        return self.client.post(
            self.URL, {"email": "nobody@example.com", "password": "wrong"}, content_type="application/json", **headers
        )

    def test_fourth_attempt_in_a_minute_is_refused(self):
        statuses = [self._post(HTTP_DO_CONNECTING_IP="203.0.113.7").status_code for _ in range(4)]
        self.assertNotIn(429, statuses[:3])
        self.assertEqual(statuses[3], 429)

    def test_rotating_forwarded_for_does_not_reset_the_count(self):
        statuses = [
            self._post(HTTP_DO_CONNECTING_IP="203.0.113.7", HTTP_X_FORWARDED_FOR=f"198.51.100.{n}").status_code
            for n in range(4)
        ]
        self.assertEqual(statuses[3], 429)

    def test_another_address_has_its_own_count(self):
        for _ in range(4):
            self._post(HTTP_DO_CONNECTING_IP="203.0.113.7")
        self.assertNotEqual(self._post(HTTP_DO_CONNECTING_IP="203.0.113.8").status_code, 429)
