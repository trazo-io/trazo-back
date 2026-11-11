"""The security limits count in production, and production's default cache stays inert.

Written 2026-11-11 for OV-SEC-C06. Production ran `CACHES["default"]` as DummyCache, so the
sign-in, sign-up, password reset, verification and invitation limits counted nothing. Giving
`default` a real backend was not the fix: it wakes three middlewares that sit in MIDDLEWARE doing
nothing today, among them a circuit breaker that answers 503 to every user once 50 server errors
have happened within an hour, and per-address blocks that would lock a shared farm office out.

So the security counters live in their own Postgres cache, `CACHES["throttle"]`, and `default`
stays inert. These tests pin both halves:
  - the counted limits refuse in a world where `default` stores nothing (production's world);
  - production's settings cannot give `default` a real backend while those middlewares exist.
"""

import ast
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.cache import caches
from django.test import SimpleTestCase, TestCase, override_settings

from rest_framework.throttling import SimpleRateThrottle

from backend.security.throttling import (
    LoginRateThrottle,
    PasswordResetRateThrottle,
    ResendVerificationRateThrottle,
    SignupRateThrottle,
    VerifyEmailRateThrottle,
    throttle_cache,
)
from company.models import Company
from users.constants import PRODUCER
from users.models import User
from users.models_invitation import CompanyInvitation

BACKEND_ROOT = Path(__file__).resolve().parents[3]

# Production's world: `default` stores nothing, `throttle` is the real Postgres cache. The
# `throttle` alias is NOT overridden, so these tests run against the DatabaseCache table that
# users migration 0017 creates.
PROD_LIKE_CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
    "throttle": settings.THROTTLE_CACHE,
}
PROD_RATES = {
    "anon": "50/hour",
    "user": "500/hour",
    "login": "3/minute",
    "signup": "2/minute",
    "password_reset": "3/hour",
    "verify_email": "10/hour",
    "resend_verification": "3/hour",
}

# The middlewares that act on a real `default` cache (inventory 2026-11-11).
DORMANT_MIDDLEWARE = (
    "backend.security.enhanced_ddos_protection.CircuitBreakerMiddleware",
    "backend.security.enhanced_ddos_protection.EnhancedRateLimitMiddleware",
    "backend.security.rate_limiting.SecurityMiddleware",
)
DUMMY = "django.core.cache.backends.dummy.DummyCache"


class ThrottleCacheIsRealTests(TestCase):
    def test_the_alias_is_a_database_cache_with_its_table(self):
        self.assertEqual(settings.CACHES["throttle"]["BACKEND"], "django.core.cache.backends.db.DatabaseCache")
        # A missing table raises here (ProgrammingError), which is the failure a deploy without
        # the migration would hit on the first sign-in.
        throttle_cache().set("probe", "kept", 30)
        self.assertEqual(throttle_cache().get("probe"), "kept")

    def test_the_security_throttles_count_in_it(self):
        for throttle in (
            LoginRateThrottle,
            SignupRateThrottle,
            PasswordResetRateThrottle,
            VerifyEmailRateThrottle,
            ResendVerificationRateThrottle,
        ):
            self.assertIs(throttle().cache, caches["throttle"], throttle.__name__)


@override_settings(CACHES=PROD_LIKE_CACHES)
@patch.object(SimpleRateThrottle, "THROTTLE_RATES", PROD_RATES)
class LimitsRefuseWithAnInertDefaultCacheTests(TestCase):
    """Each limit, exercised through its endpoint with `default` = DummyCache."""

    ADDRESS = {"HTTP_DO_CONNECTING_IP": "203.0.113.7"}

    def _statuses(self, n, path, body):
        return [
            self.client.post(path, body, content_type="application/json", **self.ADDRESS).status_code for _ in range(n)
        ]

    def test_fourth_sign_in_in_a_minute_is_refused(self):
        statuses = self._statuses(4, "/api/auth/login/", {"email": "nobody@example.com", "password": "wrong"})
        self.assertNotIn(429, statuses[:3])
        self.assertEqual(statuses[3], 429)

    def test_a_correct_sign_in_still_works(self):
        User.objects.create_user(
            email="grower@example.com",
            password="Correct-horse-9",
            is_verified=True,
            is_active=True,
            user_type=PRODUCER,
        )
        response = self.client.post(
            "/api/auth/login/",
            {"email": "grower@example.com", "password": "Correct-horse-9"},
            content_type="application/json",
            HTTP_ORIGIN="https://app.trazo.io",
            **self.ADDRESS,
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_eleventh_verification_code_in_an_hour_is_refused(self):
        statuses = self._statuses(11, "/api/users/verify_email/", {"email": "nobody@example.com", "code": "AAAAAA"})
        self.assertNotIn(429, statuses[:10])
        self.assertEqual(statuses[10], 429)

    def test_fourth_resend_in_an_hour_is_refused(self):
        statuses = self._statuses(4, "/api/users/resend_verification_email/", {"email": "nobody@example.com"})
        self.assertNotIn(429, statuses[:3])
        self.assertEqual(statuses[3], 429)

    def test_sixth_invitation_accept_in_an_hour_is_refused(self):
        company = Company.objects.create(name="Throttle Farm")
        inviter = User.objects.create_user(email="owner@example.com", password="Correct-horse-9")
        invitation = CompanyInvitation.objects.create(
            email="new@example.com", invitee_name="New", company=company, role="FM", inviter=inviter
        )
        path = f"/api/invitation/{invitation.invitation_code}/accept/"
        statuses = [self.client.post(path, **self.ADDRESS).status_code for _ in range(6)]
        self.assertNotIn(429, statuses[:5])
        self.assertEqual(statuses[5], 429)

    def test_eleventh_company_code_check_in_an_hour_is_refused(self):
        def attempt(n):
            body = {
                "first_name": "J",
                "last_name": "K",
                "email": f"joiner{n}@example.com",
                "password": "Str0ng!Passw0rd",
                "user_type": "PRODUCER",
                "company_code": "INVALID",
            }
            return self.client.post("/api/auth/register/", body, content_type="application/json", **self.ADDRESS)

        # Sign-up allows two a minute per address, so its own throttle is lifted here: this test
        # is about the company-code counter, which lives in the serializer.
        with patch.object(SignupRateThrottle, "allow_request", return_value=True):
            responses = [attempt(n) for n in range(11)]
        self.assertNotIn("Too many validation attempts", str(responses[9].content))
        self.assertIn("Too many validation attempts", str(responses[10].content))


class ProductionDefaultCacheStaysInertTests(SimpleTestCase):
    """NEVER: production's `default` cache gets a real backend while the dormant middlewares
    are installed. Read from prod.py's source, because importing prod settings reaches AWS."""

    def _prod_caches_assignments(self):
        tree = ast.parse((BACKEND_ROOT / "backend" / "settings" / "prod.py").read_text(encoding="utf-8"))
        assigns = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "CACHES":
                        assigns.append(node)
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "CACHES"
                    ):
                        key = target.slice
                        if isinstance(key, ast.Constant) and key.value == "default":
                            assigns.append(node)
        return tree, assigns

    def test_the_middlewares_this_guards_against_are_still_installed(self):
        """When they are removed, this guard can go; until then it must apply."""
        # base.py's list is production's (prod.py does not redefine MIDDLEWARE; dev.py does).
        from backend.settings import base

        installed = [m for m in DORMANT_MIDDLEWARE if m in base.MIDDLEWARE]
        self.assertTrue(installed, "remove ProductionDefaultCacheStaysInertTests with the middlewares")

    def test_prod_assigns_default_once_unconditionally_and_to_dummy(self):
        tree, assigns = self._prod_caches_assignments()
        self.assertEqual(len(assigns), 1, "prod.py must set CACHES['default'] in exactly one place")
        (node,) = assigns
        self.assertIn(node, tree.body, "the CACHES assignment sits inside an if: an env var can arm the middlewares")
        default = next(
            v
            for k, v in zip(node.value.keys, node.value.values)
            if isinstance(k, ast.Constant) and k.value == "default"
        )
        backend = next(
            v.value
            for k, v in zip(default.keys, default.values)
            if isinstance(k, ast.Constant) and k.value == "BACKEND"
        )
        self.assertEqual(backend, DUMMY)

    def test_prod_keeps_django_ratelimit_off(self):
        """Its decorators on the carbon views count in `default`."""
        source = (BACKEND_ROOT / "backend" / "settings" / "prod.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        top = [
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "RATELIMIT_ENABLE" for t in n.targets)
        ]
        self.assertEqual(len(top), 1)
        self.assertIs(top[0].value.value, False)
