"""No paid plan advertises a trial it cannot honour.

Migration 0009 wrote `trial_no_card_days: 14` / `trial_with_card_days: 14` onto
`compliance-yearly` and nothing removed them for five migrations. `create_plans` meanwhile
omitted them deliberately, with a comment saying the pricing page renders its trial line from
exactly these keys. So the two seeding paths disagreed, and which one a database was built from
decided whether the $249/yr card printed "14-day free trial included" underneath its checkout
button. A developer seeding with `create_plans` could never see it; production, built by
`migrate`, would.

Nothing in the system could have honoured that promise: `start_trial` assigns Starter with
`trial_end=None`, and `expire_trials` no-ops on an empty EXPIRABLE_TRIAL_PLAN_SLUGS.

This test pins the INVARIANT rather than migration 0015's edit — a plan that charges money must
not carry a positive trial-day count, however the row got there. The frontend guard is truthiness
(`plan.features?.trial_with_card_days &&`), so a key present with value 0 is inert and stays
allowed: `pilot` and the retired ladder rows set it explicitly to 0, and both seeding paths agree
on that.
"""

from decimal import Decimal

from django.test import TestCase

from subscriptions.models import Plan

TRIAL_KEYS = ("trial_no_card_days", "trial_with_card_days")


class NoPhantomTrialOnPaidPlansTests(TestCase):
    """Migrations seed the plan rows, so these read what a real database actually holds."""

    def test_compliance_advertises_no_trial(self):
        plan = Plan.objects.filter(slug="compliance-yearly").first()
        # A negative assertion has to prove it READ something — an empty queryset would
        # otherwise pass this test while the page was still lying.
        self.assertIsNotNone(
            plan,
            "compliance-yearly is missing: the migrations that seed it did not run, so this " "test proved nothing.",
        )
        self.assertEqual(Decimal(str(plan.price)), Decimal("249.00"))

        features = plan.features or {}
        for key in TRIAL_KEYS:
            self.assertNotIn(
                key,
                features,
                f"compliance-yearly carries {key}={features.get(key)!r}. The pricing page renders "
                f"'{{days}}-day free trial included' from this key, on a plan billed $249/yr that "
                f"has no trial. See migration 0015.",
            )

    def test_no_priced_plan_offers_trial_days(self):
        """The general rule, across every row — including the retired ladder."""
        checked = 0
        for plan in Plan.objects.exclude(price=0):
            checked += 1
            features = plan.features or {}
            for key in TRIAL_KEYS:
                self.assertFalse(
                    features.get(key),
                    f"{plan.slug} (${plan.price}) advertises {key}={features.get(key)!r}. "
                    f"Trazo has no trial on any paid plan — Starter is the free path.",
                )
        self.assertGreater(checked, 0, "No priced plans found; the assertion loop never executed.")
