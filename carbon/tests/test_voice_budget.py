"""Per-company daily ceiling on billable voice sessions.

Before 2026-08-26 nothing bounded voice spend. The two endpoints that cost money inherited
only DRF's global ``user: 500/hour``, and that throttle is INERT whenever the cache is
DummyCache — the fallback prod.py selects when REDIS_URL is unset. MEASURED against this
project's settings: a ``3/minute`` throttle allowed 50 of 50 requests under DummyCache.
So the ceiling is counted in Postgres, where it holds either way.
"""

from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from carbon.models import VoiceUsageDay
from carbon.services.voice_budget import consume_voice_session, daily_limit
from company.models import Company


class VoiceBudgetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Budget Test Farm")
        cls.other = Company.objects.create(name="Other Farm")

    def test_the_inert_cache_premise_is_real(self):
        """ANTI-VACUITY. This whole model exists because cache-backed throttling can be a
        no-op. If that ever stops being true the justification changes, so assert it."""
        from django.core.cache import cache

        from rest_framework.throttling import UserRateThrottle

        class _T(UserRateThrottle):
            rate = "3/minute"

        class _U:
            pk = 1
            is_authenticated = True

        class _R:
            user = _U()
            META = {"REMOTE_ADDR": "1.2.3.4"}

        with override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}):
            cache.set("probe", "v", 60)
            self.assertIsNone(cache.get("probe"), "DummyCache unexpectedly stored a value")
            throttle = _T()
            allowed = sum(1 for _ in range(20) if throttle.allow_request(_R(), None))
        self.assertEqual(allowed, 20, "a 3/minute throttle should be inert under DummyCache")

    @override_settings(VOICE_DAILY_SESSION_LIMIT=3)
    def test_counts_up_then_refuses(self):
        for expected in (1, 2, 3):
            allowed, used, limit = consume_voice_session(self.company)
            self.assertTrue(allowed)
            self.assertEqual(used, expected)
            self.assertEqual(limit, 3)

        allowed, used, limit = consume_voice_session(self.company)
        self.assertFalse(allowed, "the ceiling did not hold")
        self.assertEqual(used, 3)

    @override_settings(VOICE_DAILY_SESSION_LIMIT=2)
    def test_the_budget_is_per_company(self):
        """The bill is per operation. One farm exhausting its day must not mute another."""
        consume_voice_session(self.company)
        consume_voice_session(self.company)
        self.assertFalse(consume_voice_session(self.company)[0])
        self.assertTrue(consume_voice_session(self.other)[0], "a different company was blocked")

    @override_settings(VOICE_DAILY_SESSION_LIMIT=1)
    def test_yesterdays_usage_does_not_spend_today(self):
        VoiceUsageDay.objects.create(
            company=self.company,
            day=timezone.now().date() - timezone.timedelta(days=1),
            session_count=99,
        )
        self.assertTrue(consume_voice_session(self.company)[0], "an old day blocked a new one")

    @override_settings(VOICE_DAILY_SESSION_LIMIT=0)
    def test_zero_disables_the_ceiling(self):
        for _ in range(25):
            self.assertTrue(consume_voice_session(self.company)[0])
        self.assertFalse(VoiceUsageDay.objects.filter(company=self.company).exists())

    @override_settings(VOICE_DAILY_SESSION_LIMIT=1)
    def test_fails_OPEN_when_accounting_breaks(self):
        """A farmer must never lose the ability to log because a counter table misbehaved.
        The events are the product; cost control is worth a ceiling, not an outage."""
        with patch(
            "carbon.models.VoiceUsageDay.objects.select_for_update",
            side_effect=RuntimeError("db on fire"),
        ):
            allowed, _, _ = consume_voice_session(self.company)
        self.assertTrue(allowed, "budget accounting failure blocked a farmer")

    def test_default_limit_is_generous_against_real_use(self):
        """A heavy logging day is tens of entries, not hundreds. If someone tightens this to
        a number a real farmer could hit, that is a product decision, not a tweak."""
        self.assertGreaterEqual(daily_limit(), 100)


class VoiceBudgetChargePointTests(TestCase):
    """WHERE the budget is charged — one unit per logical session, and only for work done."""

    def test_a_deepgram_session_is_charged_exactly_once(self):
        """A Deepgram entry hits BOTH endpoints: deepgram-token to start the stream, then
        process-voice-event to parse the transcript. Charging both made one voice entry cost
        two units — halving the ceiling and making the admin spend view report double."""
        views = _CARBON_VIEWS.read_text()

        token_fn = _function_source(views, "deepgram_token")
        parse_fn = _function_source(views, "process_voice_event_ai")

        self.assertIn("consume_voice_session(company)", token_fn, "the metered stream is not charged")
        # The parse endpoint may only charge when there is no Deepgram key — i.e. the Web
        # Speech path, where no token was ever minted and this is the only paid call.
        self.assertIn('if not getattr(settings, "DEEPGRAM_API_KEY", "")', parse_fn)
        charge_at = parse_fn.index("consume_voice_session(company)")
        gate_at = parse_fn.index('if not getattr(settings, "DEEPGRAM_API_KEY", "")')
        self.assertLess(gate_at, charge_at, "the parse endpoint charges unconditionally")

    def test_no_budget_is_spent_when_deepgram_is_not_configured(self):
        """A server with no Deepgram key returns 503 from deepgram-token. Charging before
        that check burned a farm's daily budget on requests that did nothing."""
        views = _CARBON_VIEWS.read_text()
        fn = _function_source(views, "deepgram_token")
        unconfigured_at = fn.index("HTTP_503_SERVICE_UNAVAILABLE")
        charge_at = fn.index("consume_voice_session(company)")
        self.assertLess(unconfigured_at, charge_at, "budget is spent before the 503 is returned")


#: carbon/views.py, resolved from THIS file rather than settings.BASE_DIR — BASE_DIR
#: points at backend/, not the repo root.
_CARBON_VIEWS = Path(__file__).resolve().parents[1] / "views.py"


def _function_source(module_source: str, name: str) -> str:
    """Source of one top-level `def name(...)`, up to the next top-level def."""
    start = module_source.index(f"def {name}(")
    rest = module_source[start:]
    end = rest.find("\ndef ", 1)
    return rest if end == -1 else rest[:end]
