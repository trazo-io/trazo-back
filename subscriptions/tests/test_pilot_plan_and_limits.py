"""The Pilot plan, and the plan-limit repair that made October pilots possible.

Context: a real mid-size California orchard maps one block to one Parcel, so it needs 15-25
parcels and ~20 productions a year. Starter allows 1 and 1, enforcement is a hard 403
(`subscriptions/permissions.py`), and no exemption flag existed anywhere in the codebase — so a
free pilot could not complete onboarding at all.

Limits live in `Plan.features` (a JSONField). They are DATA, so `create_plans` cannot repair a row
that has drifted: it skips any plan that already exists.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase


def _ensure_pilot_plan():
    """Materialise the Pilot plan from the migration's own definition.

    Tests must not depend on data-migration state: with `--keepdb` the test database may predate
    the migration, and `TestCase` rolls back per test but not per migration. Building the row from
    `PILOT_FEATURES` — the same constant the migration writes — keeps these tests honest about the
    DEFINITION while `SeedAndMigrationAgreeTests` separately guards it against drift.
    """
    import importlib

    from subscriptions.models import Plan

    migration = importlib.import_module("subscriptions.migrations.0008_pilot_plan_and_parcel_limit_repair")
    plan, _ = Plan.objects.update_or_create(
        slug=migration.PILOT_SLUG,
        defaults={
            "name": "Pilot",
            "description": "Free pilot programme",
            "price": 0,
            "interval": "monthly",
            "features": migration.PILOT_FEATURES,
            "stripe_price_id": None,
            "is_active": True,
        },
    )
    return plan


class PilotPlanTests(TestCase):
    """Three properties of the Pilot plan are load-bearing; none may be 'simplified' away."""

    def setUp(self):
        self.pilot = _ensure_pilot_plan()

    def test_pilot_plan_exists_and_is_active(self):
        self.assertTrue(self.pilot.is_active)
        self.assertEqual(self.pilot.name, "Pilot")

    def test_pilot_books_zero_mrr_even_when_active(self):
        # The reason the plan is priced 0 rather than reusing Enterprise: mrr_for() returns
        # plan.price for active/past_due, so hosting a pilot on Enterprise/active would book
        # $299/mo of revenue that does not exist, in the very instrumentation meant to prove
        # whether pilots convert.
        from subscriptions.models import mrr_for

        self.assertEqual(self.pilot.price, Decimal("0.00"))
        self.assertEqual(mrr_for(self.pilot, "active"), Decimal("0"))
        self.assertEqual(mrr_for(self.pilot, "past_due"), Decimal("0"))

    def test_pilot_slug_is_not_starter_so_expire_trials_cannot_cancel_it(self):
        # expire_trials filters plan__slug="starter" and flips the subscription to "canceled",
        # which nulls Company.subscription_plan and 403s every creation across the app. A pilot
        # built on Starter would die on day 14.
        self.assertNotEqual(self.pilot.slug, "starter")

    def test_expire_trials_leaves_a_trialing_pilot_alone(self):
        from django.core.management import call_command
        from django.utils import timezone

        from company.models import Company
        from subscriptions.models import Subscription

        company = Company.objects.create(name="Pilot Orchard")
        subscription = Subscription.objects.create(
            company=company,
            plan=self.pilot,
            status="trialing",
            trial_end=timezone.now() - timedelta(days=30),
        )
        call_command("expire_trials")
        subscription.refresh_from_db()
        self.assertEqual(subscription.status, "trialing")

    def test_pilot_has_no_creation_ceilings(self):
        features = self.pilot.features
        for key in ("max_establishments", "max_parcels_per_establishment", "max_productions_per_year"):
            with self.subTest(key=key):
                self.assertEqual(features[key], -1, f"{key} must be unlimited on the pilot plan")

    def test_pilot_is_identifiable_as_a_pilot(self):
        # Cohort instrumentation needs to separate pilots from paying customers without
        # string-matching a slug.
        self.assertIs(self.pilot.features.get("is_pilot"), True)

    def test_pilot_carries_no_stripe_price(self):
        self.assertIsNone(self.pilot.stripe_price_id)

    def test_pilot_is_not_a_trial(self):
        # A pilot ends by agreement (90 days per GTM v3 Stage-1), never by a timer that silently
        # cancels the account.
        self.assertEqual(self.pilot.features["trial_no_card_days"], 0)
        self.assertEqual(self.pilot.features["trial_with_card_days"], 0)


class PlanLimitIntegrityTests(TestCase):
    """Every plan must state all three count limits explicitly."""

    def setUp(self):
        # Same reasoning as _ensure_pilot_plan: apply the migration's repair to whatever plans
        # this database holds, so the assertions test the RULE rather than the test DB's history.
        import importlib

        from subscriptions.models import Plan

        migration = importlib.import_module("subscriptions.migrations.0008_pilot_plan_and_parcel_limit_repair")

        # A fresh/kept test database may hold no seeded plans at all. Materialise each managed
        # slug with DELIBERATELY WRONG limits first, so the repair below has real drift to fix and
        # the assertions exercise the rule rather than a vacuously-correct fixture.
        for slug in migration.MANAGED_LIMITS:
            Plan.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": slug,
                    "description": slug,
                    "price": 0,
                    "interval": "monthly",
                    "features": {"max_parcels_per_establishment": 1},
                    "is_active": True,
                },
            )

        for plan in Plan.objects.all():
            managed = migration.MANAGED_LIMITS.get(plan.slug)
            legacy = migration.LEGACY_FILL_ONLY_LIMITS.get(plan.slug)
            if not managed and not legacy:
                continue
            features = dict(plan.features or {})
            for key, value in (managed or {}).items():
                features[key] = value
            for key, value in (legacy or {}).items():
                features.setdefault(key, value)
            plan.features = features
            plan.save(update_fields=["features"])
        _ensure_pilot_plan()

    def test_no_plan_is_missing_a_count_limit(self):
        # company/models.py reads all three with `default=0` (lines 110, 131, 160), so an ABSENT
        # key silently means "zero allowed", not "unlimited". The legacy $499 enterprise row was
        # missing all three: a customer on it could not create a farm, a parcel or a production.
        from subscriptions.models import Plan

        required = ("max_establishments", "max_parcels_per_establishment", "max_productions_per_year")
        missing = {
            plan.slug: [key for key in required if key not in (plan.features or {})] for plan in Plan.objects.all()
        }
        missing = {slug: keys for slug, keys in missing.items() if keys}
        self.assertEqual(missing, {}, f"plans missing limit keys (each reads as 0 = blocked): {missing}")

    def test_basic_advertises_and_delivers_two_parcels(self):
        # Regression: both basic rows carried 1 while create_plans.py and the CLAUDE.md pricing
        # table said 2 — Basic shipped half its advertised allowance.
        from subscriptions.models import Plan

        for slug in ("basic-monthly", "basic-yearly"):
            with self.subTest(slug=slug):
                plan = Plan.objects.get(slug=slug)
                self.assertEqual(plan.features["max_parcels_per_establishment"], 2)

    def test_every_limit_is_a_positive_int_or_unlimited(self):
        from subscriptions.models import Plan

        required = ("max_establishments", "max_parcels_per_establishment", "max_productions_per_year")
        for plan in Plan.objects.all():
            for key in required:
                value = (plan.features or {}).get(key)
                with self.subTest(slug=plan.slug, key=key):
                    self.assertIsInstance(value, int)
                    # 0 is never a legitimate configured value — it is what an ABSENT key
                    # degrades to, and it blocks creation entirely.
                    self.assertTrue(value == -1 or value >= 1, f"{plan.slug}.{key} = {value}")


class SeedAndMigrationAgreeTests(TestCase):
    """The Pilot feature set is written twice and the copies must not drift.

    A migration has to freeze its own copy (it must keep working against historical code), so the
    duplication is unavoidable — but silent divergence is not. If create_plans.py is edited, a
    freshly seeded environment and a migrated one would disagree about what a pilot may do.
    """

    def test_create_plans_pilot_features_match_the_migration(self):
        import importlib

        migration = importlib.import_module("subscriptions.migrations.0008_pilot_plan_and_parcel_limit_repair")
        command_source = importlib.import_module("subscriptions.management.commands.create_plans").__file__
        with open(command_source) as fh:
            text = fh.read()

        # The migration's copy is frozen history; keys the product has since RETIRED are
        # exempt from the drift check but must be named in the command's own retired list —
        # so a key cannot quietly vanish from the seeder without being declared retired,
        # and the strip step removes it from every existing row on the next re-run.
        from subscriptions.management.commands.create_plans import Command

        for key, value in migration.PILOT_FEATURES.items():
            with self.subTest(key=key):
                if key in Command.RETIRED_FEATURE_KEYS:
                    # `"key":` (with the colon) is the dict-entry shape — the retired-list
                    # tuple and prose mentions don't carry it, so this catches a re-seeded
                    # key anywhere in the file without matching the declaration itself.
                    self.assertNotIn(
                        f'"{key}":',
                        text,
                        f"{key} is declared retired but still seeded by create_plans.py",
                    )
                    continue
                self.assertIn(
                    f'"{key}": {value}',
                    text,
                    f"pilot_features in create_plans.py has drifted from the migration on {key}",
                )
