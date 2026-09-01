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


class PerPlanVoiceCeilingTests(TestCase):
    """The ceiling belongs to the plan, not to the deploy.

    Voice is the one entitlement in a plan's feature dict that costs money PER USE — a session
    streams metered audio and then calls a model — and it is ON for the free tier on purpose
    (migration 0014). Until 2026-08-31 every tier shared a single number read from
    `VOICE_DAILY_SESSION_LIMIT`, so the bound on a company paying NOTHING sat where the bound on
    one paying $1,200 sat: on the order of $700/yr of usage against $0 of revenue.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Ceiling Farm")

    def _plan_with(self, slug, features):
        from subscriptions.models import Plan, Subscription

        plan = Plan.objects.create(name=slug, slug=slug, description="", price=0, interval="yearly", features=features)
        Subscription.objects.update_or_create(company=self.company, defaults={"plan": plan, "status": "active"})
        # `subscription_plan` is read through the relation, so refresh what the instance holds.
        self.company.refresh_from_db()
        return plan

    def test_the_plans_own_ceiling_wins_over_the_environment(self):
        self._plan_with("tiny", {"voice_daily_sessions": 2})
        with override_settings(VOICE_DAILY_SESSION_LIMIT=200):
            self.assertEqual(daily_limit(self.company), 2)
            self.assertTrue(consume_voice_session(self.company)[0])
            self.assertTrue(consume_voice_session(self.company)[0])
            allowed, used, limit = consume_voice_session(self.company)
        self.assertFalse(allowed)
        self.assertEqual((used, limit), (2, 2))

    def test_a_plan_that_names_no_ceiling_falls_back_to_the_environment(self):
        # The retired ladder is deactivated as a product but LIVE AS CONTRACTS. Those rows carry
        # no key, and their behaviour must be exactly what it was before this feature existed.
        self._plan_with("legacy", {"voice_recording": True})
        with override_settings(VOICE_DAILY_SESSION_LIMIT=7):
            self.assertEqual(daily_limit(self.company), 7)

    def test_minus_one_is_unlimited(self):
        # Same convention as `max_establishments` and `max_parcels_per_establishment`.
        self._plan_with("unbounded", {"voice_daily_sessions": -1})
        for _ in range(3):
            self.assertTrue(consume_voice_session(self.company)[0])

    def test_an_unreadable_ceiling_falls_back_instead_of_failing_open(self):
        # A plan holding junk must not become "no ceiling at all" — that is the failure mode this
        # whole module exists to prevent.
        self._plan_with("broken", {"voice_daily_sessions": "lots"})
        with override_settings(VOICE_DAILY_SESSION_LIMIT=9):
            self.assertEqual(daily_limit(self.company), 9)

    def test_a_string_number_is_still_a_number(self):
        self._plan_with("stringy", {"voice_daily_sessions": "3"})
        self.assertEqual(daily_limit(self.company), 3)

    def test_no_company_still_answers_the_environment_default(self):
        with override_settings(VOICE_DAILY_SESSION_LIMIT=11):
            self.assertEqual(daily_limit(), 11)


class SeededVoiceCeilingsTests(TestCase):
    """What a FRESH environment actually enforces.

    ⛔ Asserted by RUNNING `create_plans`, not by reading the plan table. Migrations never INSERT
    plan rows — 0019 patches what it finds and no-ops on an empty database — so a guard that only
    queries `Plan` passes vacuously on a fresh install while the seeder ships no ceiling at all.
    Same reasoning as `subscriptions/tests/test_seeded_lineup.py`.
    """

    def _seed(self):
        from unittest import mock

        from django.core.management import call_command

        with mock.patch("subscriptions.management.commands.create_plans.stripe") as fake_stripe:
            fake_stripe.Product.create.side_effect = lambda **kw: mock.Mock(id="prod_test")
            fake_stripe.Price.create.side_effect = lambda **kw: mock.Mock(id="price_test")
            call_command("create_plans", verbosity=0)

    def test_every_plan_on_sale_names_its_own_ceiling(self):
        from subscriptions.models import Plan

        self._seed()
        for slug in ("starter", "compliance-yearly", "operation-yearly", "pilot"):
            plan = Plan.objects.get(slug=slug)
            self.assertIn(
                "voice_daily_sessions",
                plan.features,
                f"{slug} would silently inherit the deploy-wide ceiling",
            )

    def test_the_free_tier_is_bounded_well_below_the_paid_ones(self):
        from subscriptions.models import Plan

        self._seed()
        starter = Plan.objects.get(slug="starter").features["voice_daily_sessions"]
        compliance = Plan.objects.get(slug="compliance-yearly").features["voice_daily_sessions"]
        operation = Plan.objects.get(slug="operation-yearly").features["voice_daily_sessions"]

        self.assertLess(starter, compliance)
        self.assertGreater(operation, compliance, "the per-COMPANY budget must scale with farms")
        # ...and still far above real use: "a heavy logging day is tens of entries, not hundreds".
        # A ceiling that bites a grower at harvest defeats the reason voice is free at all.
        self.assertGreaterEqual(starter, 30)

    def test_voice_stays_on_for_the_free_tier(self):
        # The point of the ceiling is to make free voice affordable, never to walk it back.
        from subscriptions.models import Plan

        self._seed()
        self.assertTrue(Plan.objects.get(slug="starter").features["voice_recording"])


class VoiceCeilingCoercionTests(TestCase):
    """A plan's feature dict is mostly booleans, so the wrong TYPE in this key is a live risk."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Coercion Farm")

    def _plan_with(self, value):
        from subscriptions.models import Plan, Subscription

        plan = Plan.objects.create(
            name="t",
            slug="t",
            description="",
            price=0,
            interval="yearly",
            features={"voice_daily_sessions": value},
        )
        Subscription.objects.update_or_create(company=self.company, defaults={"plan": plan, "status": "active"})
        self.company.refresh_from_db()
        return plan

    def test_true_is_not_a_ceiling_of_one(self):
        # `int(True)` is 1. Pasted into this key beside `voice_recording: True`, that would hand a
        # farm ONE session a day — indistinguishable from a broken microphone in the field.
        self._plan_with(True)
        with override_settings(VOICE_DAILY_SESSION_LIMIT=200):
            self.assertEqual(daily_limit(self.company), 200)

    def test_false_does_not_silently_disable_the_feature(self):
        # `int(False)` is 0, and 0 means "no ceiling at all" in consume_voice_session — the exact
        # opposite of what someone writing False would intend.
        self._plan_with(False)
        with override_settings(VOICE_DAILY_SESSION_LIMIT=200):
            self.assertEqual(daily_limit(self.company), 200)

    def test_none_falls_back(self):
        self._plan_with(None)
        with override_settings(VOICE_DAILY_SESSION_LIMIT=42):
            self.assertEqual(daily_limit(self.company), 42)

    def test_a_float_truncates_rather_than_failing(self):
        self._plan_with(12.9)
        self.assertEqual(daily_limit(self.company), 12)


class VoiceHardCapTests(TestCase):
    """The lever that still works when the plans disagree with you.

    Before the ceilings moved onto the plans, lowering `VOICE_DAILY_SESSION_LIMIT` capped every
    company immediately — the thing you reach for when a metered vendor bill spikes at 2am. A plan
    value now wins over that variable, so the lever would have quietly stopped working at exactly
    the moment it was needed. `VOICE_DAILY_SESSION_HARD_CAP` is that lever, unset by default.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Cap Farm")

    def _plan_with(self, value):
        from subscriptions.models import Plan, Subscription

        plan = Plan.objects.create(
            name="c",
            slug="c",
            description="",
            price=0,
            interval="yearly",
            features={"voice_daily_sessions": value},
        )
        Subscription.objects.update_or_create(company=self.company, defaults={"plan": plan, "status": "active"})
        self.company.refresh_from_db()

    def test_unset_changes_nothing(self):
        self._plan_with(1000)
        with override_settings(VOICE_DAILY_SESSION_HARD_CAP=0):
            self.assertEqual(daily_limit(self.company), 1000)

    def test_it_caps_a_plan_that_asks_for_more(self):
        self._plan_with(1000)
        with override_settings(VOICE_DAILY_SESSION_HARD_CAP=25):
            self.assertEqual(daily_limit(self.company), 25)

    def test_it_never_raises_a_plan_that_asks_for_less(self):
        # An environment variable must not GRANT budget — that is the opposite of an emergency
        # brake, and it would silently overrule the free tier's deliberate bound.
        self._plan_with(50)
        with override_settings(VOICE_DAILY_SESSION_HARD_CAP=500):
            self.assertEqual(daily_limit(self.company), 50)

    def test_it_reaches_an_unlimited_plan(self):
        # The plan that most needs bounding in an incident must not be the one the lever cannot
        # touch. `-1` would otherwise sail straight through a min().
        self._plan_with(-1)
        with override_settings(VOICE_DAILY_SESSION_HARD_CAP=10):
            self.assertEqual(daily_limit(self.company), 10)
            self.assertTrue(consume_voice_session(self.company)[0])

    def test_it_applies_without_a_company_too(self):
        with override_settings(VOICE_DAILY_SESSION_LIMIT=200, VOICE_DAILY_SESSION_HARD_CAP=5):
            self.assertEqual(daily_limit(), 5)
