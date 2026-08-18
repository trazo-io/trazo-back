"""What a FRESH environment actually sells.

## The defect this exists to prevent

Migrations never INSERT plan rows — 0008/0009/0012/0014 all read
`Plan.objects.filter(slug=...).first()` and patch what they find. On a fresh database they run
before any plan exists and quietly no-op. `create_plans` is the only thing that creates plans,
so `create_plans` is the only thing that decides what a new environment sells.

It decided wrong. The Stripe branch hardcoded `is_active: True`, ignoring the `is_active: False`
carried by every retired plan definition. That was invisible in every environment Trazo has ever
run, because `STRIPE_SECRET_KEY` is empty and the free/no-Stripe branch honours the flag — and it
would have fired on the exact day Stripe was switched on, which is the day the first customer
pays. MEASURED on a pristine `migrate` + `create_plans` database (2026-08-16), the public
`/api/subscriptions/plans/` endpoint answered with TEN plans: Basic $69, Standard $119, Corporate
$149, Enterprise $299 and their annual twins, all carrying `trial_with_card_days: 14`, beside the
$249/yr tier that replaced them. It also minted live Stripe products for eight withdrawn ones.

## Why the assertions are shaped this way

The lineup is asserted by RUNNING the seeder with Stripe enabled, not by reading the definitions.
A test that reads `is_active` out of the definition list would have passed against the broken
code — the definitions were always right; the writer ignored them. The only thing that proves the
lineup is executing the path that builds it.

Stripe is mocked rather than skipped for the same reason: the no-Stripe branch was never the
broken one, so a test that runs without a key exercises the wrong half.
"""

from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from subscriptions.models import AddOn, Plan
from subscriptions.views import internal_plans, self_serve_plans

# What Trazo sells, in public, to anyone.
#
# `operation-yearly` joined on 2026-08-17. It is the CEILING the lineup did not have: one paid
# product capped at one farm meant the ladder inverted at the top — farms #2 onward at $149 each
# put a six-farm business at $994 against QO's $4,250 for the same operation.
PUBLIC_LINEUP = {"starter", "compliance-yearly", "operation-yearly"}

# The paid tiers, cheapest first. Order is load-bearing: a lineup whose prices do not ascend is a
# packaging bug, not a display one.
PAID_LADDER = ["compliance-yearly", "operation-yearly"]

# Hand-provisioned only. Real, never listed.
INTERNAL_LINEUP = {"pilot"}

# Deactivated as PRODUCTS by migrations 0009/0012. Rows survive because they still carry active
# SUBSCRIPTIONS — retiring a product is not cancelling a contract.
RETIRED_LADDER = {
    "basic-monthly",
    "basic-yearly",
    "standard-monthly",
    "standard-yearly",
    "corporate-monthly",
    "corporate-yearly",
    "enterprise-monthly",
    "enterprise-yearly",
}


@override_settings(STRIPE_SECRET_KEY="sk_test_lineup_guard")
class SeededLineupTests(TestCase):
    """Seed the way a fresh production environment seeds, then look at what is on sale."""

    def _seed_with_stripe(self):
        """Run `create_plans` down the STRIPE branch, capturing what it tried to create."""
        with mock.patch("subscriptions.management.commands.create_plans.stripe") as fake_stripe:
            fake_stripe.Product.create.side_effect = lambda **kw: mock.Mock(
                id="prod_test", **{"metadata": kw.get("metadata")}
            )
            fake_stripe.Price.create.side_effect = lambda **kw: mock.Mock(id="price_test")
            call_command("create_plans", verbosity=0)
            return fake_stripe

    def test_a_fresh_environment_sells_exactly_two_plans(self):
        self._seed_with_stripe()

        public = {p.slug for p in self_serve_plans()}
        self.assertEqual(
            public,
            PUBLIC_LINEUP,
            "the public pricing API is an offer to the world; this is the whole October lineup",
        )
        self.assertEqual({p.slug for p in internal_plans()}, INTERNAL_LINEUP)

    def test_the_paid_ladder_ascends_and_each_step_buys_something(self):
        """A higher tier must cost more AND grant more. Both halves have been wrong here before.

        Price alone is not enough: `pilot` once granted unlimited farms and 50 GB, entitlements no
        customer could buy, which made conversion a DOWNGRADE. And capacity alone is not enough
        either — the ladder inverted at the top for months because nothing checked that the most
        expensive product was also the largest.
        """
        self._seed_with_stripe()

        rungs = [Plan.objects.get(slug=slug) for slug in PAID_LADDER]

        for lower, higher in zip(rungs, rungs[1:]):
            self.assertLess(
                lower.price,
                higher.price,
                f"{higher.slug} does not cost more than {lower.slug}",
            )

            def cap(plan, key):
                """-1 (unlimited) sorts above every finite value."""
                value = (plan.features or {}).get(key, 0)
                return float("inf") if value == -1 else value

            for key in ("max_establishments", "storage_limit_gb"):
                self.assertGreaterEqual(
                    cap(higher, key),
                    cap(lower, key),
                    f"{higher.slug} costs more than {lower.slug} but grants less {key}",
                )

            # The paid tiers share one entitlement set by construction (`operation_features`
            # spreads `compliance_features`). If that spread is ever replaced by a hand-written
            # dict, this catches the first thing to silently go missing.
            self.assertTrue(
                (higher.features or {}).get("compliance_exports"),
                f"{higher.slug} is a paid tier without the certifier documents",
            )

    def test_extra_farm_stays_cheaper_than_the_first_farm(self):
        """The marginal farm must never cost more than farm #1.

        At $30/MONTH the add-on made farm #2 cost 45% MORE than farm #1. That is fixed, and this
        pins the DIRECTION rather than the number so a future reprice cannot re-invert it. It also
        checks the crossover: buying enough Extra Farms must eventually cost more than Operation,
        or the ceiling tier is unreachable and nobody ever climbs to it.
        """
        self._seed_with_stripe()

        compliance = Plan.objects.get(slug="compliance-yearly")
        operation = Plan.objects.get(slug="operation-yearly")
        extra_farm = AddOn.objects.get(slug="extra-establishment")

        self.assertEqual(extra_farm.interval, "yearly", "an add-on on a yearly plan must bill yearly")
        self.assertLess(
            extra_farm.price,
            compliance.price,
            "farm #2 costs more than farm #1 — the marginal price is running the wrong way",
        )

        # Somewhere below a sane farm count, Operation has to win.
        crossover = next(
            (n for n in range(1, 50) if compliance.price + n * extra_farm.price > operation.price),
            None,
        )
        self.assertIsNotNone(crossover, "no number of Extra Farms ever exceeds Operation — the ceiling is unreachable")
        self.assertLessEqual(crossover, 12, f"Operation only wins at {crossover} extra farms — the ceiling is too high")

    def test_the_retired_ladder_is_seeded_inactive(self):
        self._seed_with_stripe()

        rows = Plan.objects.filter(slug__in=RETIRED_LADDER)
        # Prove the query read something: an empty queryset would pass the loop below for free.
        self.assertEqual(rows.count(), len(RETIRED_LADDER), "retired rows must still EXIST — they hold contracts")
        for plan in rows:
            self.assertFalse(plan.is_active, f"{plan.slug} came back on sale")

    def test_no_retired_plan_reaches_stripe(self):
        """A withdrawn product must not exist in the payment processor.

        The eight retired tiers had live Stripe products and prices minted for them on every
        seed of a Stripe-enabled environment — an account meant to have no such thing, and a
        price anyone holding the id could still be billed against.
        """
        fake_stripe = self._seed_with_stripe()

        seeded_slugs = {
            call.kwargs.get("metadata", {}).get("plan_slug") for call in fake_stripe.Product.create.call_args_list
        }
        seeded_slugs.discard(None)
        self.assertTrue(seeded_slugs, "no plan reached Stripe at all — the branch under test did not run")
        self.assertFalse(
            seeded_slugs & RETIRED_LADDER,
            f"withdrawn plans were created in Stripe: {sorted(seeded_slugs & RETIRED_LADDER)}",
        )

    def test_no_plan_on_sale_advertises_a_trial(self):
        """Starter is free forever and Compliance is $249/yr. Neither has a trial.

        The retired ladder carries `trial_no_card_days: 7` / `trial_with_card_days: 14`, so
        listing any of it re-publishes the claim migration 0015 exists to remove.
        """
        self._seed_with_stripe()

        checked = 0
        for plan in self_serve_plans():
            checked += 1
            for key in ("trial_no_card_days", "trial_with_card_days"):
                self.assertFalse(
                    (plan.features or {}).get(key),
                    f"{plan.slug} advertises {key}={plan.features.get(key)}",
                )
        self.assertGreater(checked, 0, "nothing was on sale — the assertion above proved nothing")

    def test_only_plans_on_sale_carry_a_stripe_price(self):
        self._seed_with_stripe()

        with_price = {p.slug for p in Plan.objects.exclude(stripe_price_id=None).exclude(stripe_price_id="")}
        self.assertFalse(
            with_price - PUBLIC_LINEUP,
            f"plans that are not on sale hold a billable Stripe price: {sorted(with_price - PUBLIC_LINEUP)}",
        )

    def test_only_the_one_live_addon_reaches_stripe(self):
        """Same guard, add-on side — this half was already fixed and must stay fixed."""
        fake_stripe = self._seed_with_stripe()

        seeded = {
            call.kwargs.get("metadata", {}).get("addon_slug") for call in fake_stripe.Product.create.call_args_list
        }
        seeded.discard(None)
        self.assertEqual(seeded, {"extra-establishment"}, "only Extra Farm is sold")
        self.assertEqual(
            {a.slug for a in AddOn.objects.filter(is_active=True)},
            {"extra-establishment"},
        )
