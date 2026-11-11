"""The severity contract for security system checks.

MEASURED 2026-08-27 — the first version of `throttling_is_actually_enforced` returned a
`checks.Error`, and Django runs system checks before every management command. The
DigitalOcean release step ran `manage.py check`, the command exited 1, and the app never
bound its port:

    SystemCheckError: (security.E001) Rate limiting is configured but cannot work...
    ERROR failed health checks after 10 attempts ... connection refused
    ERROR component terminated with non-zero exit code: 1

The finding itself was true — production really was on DummyCache with every declared rate
inert. But the condition had been live for months, and provisioning Redis is an infra change
the operator cannot make while the service is down. A check that takes production offline to
report a pre-existing risk turns a standing problem into an outage, and it trains people to
reach for SILENCED_SYSTEM_CHECKS, which destroys the signal permanently.

Hence: Warning by default, Error only where blocking is the point (CI, staging) via
SECURITY_CHECKS_STRICT.
"""

from django.core.checks import ERROR, WARNING
from django.test import SimpleTestCase, override_settings

from backend.security.checks import throttling_is_actually_enforced

_DUMMY_BACKEND = {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}
_DB_BACKEND = {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "t"}
# Since 2026-11-11 the critical scopes count in CACHES["throttle"]; `default` is inert in
# production on purpose (OV-SEC-C06), so the check asks about `throttle`.
_INERT_THROTTLE = {"default": _DUMMY_BACKEND, "throttle": _DUMMY_BACKEND}
_LOCMEM_THROTTLE = {"default": _DUMMY_BACKEND, "throttle": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
_NO_THROTTLE = {"default": _DUMMY_BACKEND}
_PROD_SHAPE = {"default": _DUMMY_BACKEND, "throttle": _DB_BACKEND}
_RATES = {"DEFAULT_THROTTLE_RATES": {"login": "3/minute", "user": "500/hour"}}


class ThrottlingCheckSeverityTests(SimpleTestCase):
    @override_settings(CACHES=_INERT_THROTTLE, REST_FRAMEWORK=_RATES)
    def test_does_not_block_a_deploy_by_default(self):
        """The regression that broke production. If this ever returns ERROR again, every
        management command on a misconfigured environment starts failing, including the one
        that boots the web process."""
        messages = throttling_is_actually_enforced(None)
        self.assertTrue(messages, "the check went silent; the finding is real, keep reporting it")
        for message in messages:
            self.assertEqual(message.level, WARNING, f"{message.id} would abort manage.py check")
            self.assertFalse(message.is_serious())

    @override_settings(CACHES=_INERT_THROTTLE, REST_FRAMEWORK=_RATES, SECURITY_CHECKS_STRICT=True)
    def test_blocks_when_a_deploy_asks_it_to(self):
        messages = throttling_is_actually_enforced(None)
        self.assertTrue(messages)
        self.assertTrue(any(m.level == ERROR and m.id == "security.E001" for m in messages))

    @override_settings(CACHES=_INERT_THROTTLE, REST_FRAMEWORK=_RATES)
    def test_still_names_the_scopes_that_matter(self):
        """Downgrading severity must not soften the message: an operator skimming a deploy
        log needs to see WHICH protection is off, not that 'something' is."""
        message = throttling_is_actually_enforced(None)[0]
        self.assertIn("login", message.msg)
        self.assertIn("DummyCache", message.hint)
        self.assertIn("throttle", message.hint)

    @override_settings(CACHES=_NO_THROTTLE, REST_FRAMEWORK=_RATES)
    def test_a_missing_throttle_alias_is_reported(self):
        message = throttling_is_actually_enforced(None)[0]
        self.assertIn("no 'throttle' alias", message.hint)

    @override_settings(CACHES=_LOCMEM_THROTTLE, REST_FRAMEWORK=_RATES)
    def test_locmem_is_also_inert_across_workers(self):
        self.assertTrue(throttling_is_actually_enforced(None))

    @override_settings(CACHES=_PROD_SHAPE, REST_FRAMEWORK=_RATES)
    def test_silent_on_production_shape(self):
        """ANTI-VACUITY: a check that fires on everything is noise, and one that fires on
        nothing is decoration. Production's shape (inert `default`, Postgres `throttle`) is the
        configuration this check must accept, or every deploy log carries a false alarm."""
        self.assertEqual(throttling_is_actually_enforced(None), [])

    @override_settings(CACHES=_INERT_THROTTLE, REST_FRAMEWORK={"DEFAULT_THROTTLE_RATES": {"user": "500/hour"}})
    def test_silent_when_no_security_scope_is_declared(self):
        """No critical rate declared means no brute-force promise is being broken."""
        self.assertEqual(throttling_is_actually_enforced(None), [])
