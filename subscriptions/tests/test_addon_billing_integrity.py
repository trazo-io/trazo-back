"""An add-on may only be sold at a price the app can prove.

## The defect class

A Stripe Price is IMMUTABLE: the amount and the recurring interval live on the price
object, not the product, so repricing means minting a NEW price. Migration 0014 repriced
Extra Farm from $30/MONTH to $149/YEAR by updating `AddOn.price` and `AddOn.interval` —
the only thing a data migration can do — and `create_plans` then skipped the row on every
subsequent seed because it "already exists" (i.e. already had a `stripe_price_id`).

The row published $149/year and carried a live $30/month price. The UI, the invoice and
the farmer's bank statement would each have said something different.

That is the same shape as the two add-on defects before it: the blockchain add-on sat
`is_active=False` in data while both UIs rendered a hardcoded $15/mo offer, and
`extra-parcel` / `extra-production` stayed ACTIVE selling capacity the live plans grant
without limit. Each time, one representation of the product drifted from another and
nothing in the test suite compared them.

So these tests compare representations. They do not check that Extra Farm costs $149 —
that is a pricing decision and it will change. They check that whatever it costs, every
surface agrees, and that nothing can be sold through a price the app cannot verify.
"""

from unittest import mock

from django.test import TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from company.models import Company
from subscriptions.management.commands.create_plans import ADDON_DEFINITIONS
from subscriptions.models import AddOn, Plan, Subscription, SubscriptionAddOn
from subscriptions.testing import compliance_plan
from users.models import User, WorksIn

# Capacity the live tiers grant without limit. An ACTIVE add-on selling any of these is a
# billing defect regardless of its price: `/api/subscriptions/addons/` serves whatever is
# active, so the app would offer a grower the chance to pay for what they already have.
UNLIMITED_ON_LIVE_TIERS = {
    "max_parcels_per_establishment": "extra-parcel",
    "max_productions_per_year": "extra-production",
}


class AddOnCatalogIntegrityTests(TestCase):
    """Properties the add-on catalogue must hold, whatever it happens to contain.

    Read from `ADDON_DEFINITIONS`, not from the AddOn table. Migrations never INSERT
    add-on rows — 0006/0010/0013/0014/0016 only UPDATE existing ones — so a freshly
    migrated database has an empty table and a guard written against it would pass by
    iterating nothing. `create_plans` is what a fresh environment actually runs, so its
    definitions are the thing under test. DB rows are checked too, when there are any.
    """

    def test_the_catalog_is_not_empty(self):
        """A negative assertion has to prove it read something."""
        self.assertGreater(len(ADDON_DEFINITIONS), 0, "no add-on definitions — the guards below would vacuously pass")

    def test_every_addon_declares_the_period_it_bills_at(self):
        """A price without a period is not a price.

        `AddOn.interval` did not exist until 2026-08-14: `create_plans` passed an interval
        to `stripe.Price.create` and dropped it on the way into the database, so the app
        rendered a bare "$30.00" beside a plan labelled "/Yearly" and nothing on screen
        distinguished $30 a month from $30 a year.
        """
        for definition in ADDON_DEFINITIONS:
            self.assertIn(
                definition.get("interval"),
                {"month", "year"},
                f"{definition.get('slug')} has interval {definition.get('interval')!r}",
            )

        valid_db = {choice for choice, _ in Plan.INTERVAL_CHOICES}
        for addon in AddOn.objects.all():
            self.assertIn(addon.interval, valid_db, f"{addon.slug} has interval {addon.interval!r}")

    def test_every_addon_declares_a_positive_price(self):
        for definition in ADDON_DEFINITIONS:
            self.assertGreater(float(definition["price"]), 0, definition["slug"])

    def test_slugs_are_unique(self):
        slugs = [d["slug"] for d in ADDON_DEFINITIONS]
        self.assertEqual(len(slugs), len(set(slugs)), f"duplicate add-on slug in {slugs}")

    def test_no_active_addon_sells_capacity_the_live_tiers_give_away(self):
        """An add-on that charges for something the plan already includes is a billing defect.

        `/api/subscriptions/addons/` serves whatever is active, so leaving one of these
        ACTIVE keeps the offer legitimate no matter what the pricing page says.
        """
        active_definitions = {d["slug"] for d in ADDON_DEFINITIONS if d.get("is_active", True)}

        live_values = {}
        for plan in Plan.objects.filter(is_active=True):
            for key, value in (plan.features or {}).items():
                if key in UNLIMITED_ON_LIVE_TIERS:
                    live_values.setdefault(key, []).append(value)

        checked = 0
        for feature_key, addon_slug in UNLIMITED_ON_LIVE_TIERS.items():
            values = live_values.get(feature_key)
            # -1 is unlimited. Only redundant if EVERY plan a customer could be on grants it
            # without limit — one finite live tier is enough to make the add-on meaningful.
            if not values or not all(v == -1 for v in values):
                continue
            checked += 1
            self.assertNotIn(
                addon_slug,
                active_definitions,
                f"{addon_slug} is active but every live plan grants {feature_key} without limit",
            )
            db_row = AddOn.objects.filter(slug=addon_slug).first()
            if db_row is not None:
                self.assertFalse(db_row.is_active, f"{addon_slug} row is active in the database")

        self.assertGreater(checked, 0, "no live plan grants any tracked capacity unlimited — nothing was checked")

    def test_withdrawn_addons_stay_withdrawn(self):
        """Withdrawing a product in DATA is only half of withdrawing it.

        The inverse is what this guards: one reseed is all it takes for a UI to start
        honouring an active row again, so the flag has to hold in the definitions too.
        """
        retired = {"blockchain-verification", "extra-storage", "extra-parcel", "extra-production"}
        for definition in ADDON_DEFINITIONS:
            if definition["slug"] in retired:
                self.assertFalse(definition.get("is_active", True), f"{definition['slug']} must stay retired")
        for addon in AddOn.objects.filter(slug__in=retired):
            self.assertFalse(addon.is_active, f"{addon.slug} row must stay retired")

    def test_extra_farm_costs_less_than_the_plan_it_extends(self):
        """The marginal price of a unit must not exceed the first one.

        At $30/MONTH beside a $249/YEAR plan, farm #2 cost $360/yr — 45% MORE than farm #1 —
        so the price rose with volume and punished the multi-farm grower hardest. This does
        not assert $149; it asserts the DIRECTION, which is what must not regress.
        """
        extra_farm = next((d for d in ADDON_DEFINITIONS if d["slug"] == "extra-establishment"), None)
        self.assertIsNotNone(extra_farm, "Extra Farm is missing from the catalogue")

        compliance = Plan.objects.filter(slug="compliance-yearly").first()
        if compliance is None:
            self.skipTest("compliance-yearly not seeded in this database")

        annual_addon = float(extra_farm["price"]) * (12 if extra_farm["interval"] == "month" else 1)
        annual_plan = float(compliance.price) * (12 if compliance.interval == "monthly" else 1)
        self.assertLess(
            annual_addon,
            annual_plan,
            f"Extra Farm is ${annual_addon}/yr against a ${annual_plan}/yr plan — farm #2 costs more than farm #1",
        )


class AddOnSaleRequiresVerifiedPriceTests(TestCase):
    """`add_addon` must refuse rather than bill through an unverified Stripe price."""

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Addon Sale Farm")
        self.user = User.objects.create_user(email="addonsale@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.subscription = Subscription.objects.create(
            company=self.company,
            plan=compliance_plan(),
            status="active",
            stripe_subscription_id="sub_test_addon",
            stripe_customer_id="cus_test_addon",
        )
        self.client.force_authenticate(user=self.user)

    def _post(self, addon):
        # `reverse`, not a literal path: the router mounts under /api/subscriptions/ and the
        # viewset registers "subscriptions" again, so the real URL has the segment twice. A
        # hardcoded path here 404s and the 404 reads like a permissions failure.
        url = reverse("subscription-add-addon", args=[self.subscription.id])
        return self.client.post(url, {"addon_id": addon.id, "quantity": 1}, format="json")

    def test_addon_without_stripe_price_is_refused_not_sold(self):
        """Migration 0016 NULLs Extra Farm's stale id; this is what that NULL buys.

        Without the guard, the request hands Stripe a missing price and either errors
        opaquely or — with the pre-0016 stale id — silently bills the OLD amount.
        """
        addon = AddOn.objects.create(
            name="Priceless Farm",
            slug="test-addon-no-price",
            description="fixture",
            price=149,
            interval="yearly",
            stripe_price_id=None,
            is_active=True,
        )
        r = self._post(addon)
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(r.json()["code"], "ADDON_PRICE_UNAVAILABLE")
        # Refused means refused: no entitlement may be granted on the way out.
        self.assertFalse(SubscriptionAddOn.objects.filter(subscription=self.subscription, addon=addon).exists())

    def test_stripe_is_billed_the_same_quantity_that_is_granted(self):
        """The number sent to Stripe must equal the number stored locally.

        The create branch sent the INCREMENT while storing `previous + increment`. Those only
        agree when no local row exists — and a row with no `stripe_item_id` is exactly what the
        legacy webhook path and any half-finished attempt leave behind. A farm holding 3 extra
        farms who bought 1 more was billed for 1 and granted 4.
        """
        addon = AddOn.objects.create(
            name="Quantity Guard",
            slug="test-addon-quantity",
            description="fixture",
            price=149,
            interval="yearly",
            stripe_price_id="price_qty_guard",
            is_active=True,
        )
        # A pre-existing entitlement with NO Stripe item — the state that exposed the bug.
        SubscriptionAddOn.objects.create(subscription=self.subscription, addon=addon, quantity=3, stripe_item_id=None)

        with mock.patch("subscriptions.views.stripe") as fake_stripe:
            fake_stripe.SubscriptionItem.create.return_value = mock.Mock(id="si_new")
            r = self.client.post(
                reverse("subscription-add-addon", args=[self.subscription.id]),
                {"addon_id": addon.id, "quantity": 1},
                format="json",
            )

        self.assertEqual(r.status_code, 200, r.content)
        billed = fake_stripe.SubscriptionItem.create.call_args.kwargs["quantity"]
        granted = SubscriptionAddOn.objects.get(subscription=self.subscription, addon=addon).quantity
        self.assertEqual(granted, 4, "the local entitlement should be 3 + 1")
        self.assertEqual(billed, granted, f"Stripe billed {billed} while the farm was granted {granted}")

    def test_quantity_is_bounded(self):
        """This endpoint bills. An unbounded quantity is an unbounded charge."""
        addon = AddOn.objects.create(
            name="Bound Guard",
            slug="test-addon-bound",
            description="fixture",
            price=149,
            interval="yearly",
            stripe_price_id="price_bound_guard",
            is_active=True,
        )
        with mock.patch("subscriptions.views.stripe") as fake_stripe:
            r = self.client.post(
                reverse("subscription-add-addon", args=[self.subscription.id]),
                {"addon_id": addon.id, "quantity": 10000},
                format="json",
            )
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json()["code"], "ADDON_QUANTITY_TOO_LARGE")
        fake_stripe.SubscriptionItem.create.assert_not_called()

    def test_a_failed_entitlement_write_does_not_leave_the_farm_billed(self):
        """Billed-but-not-entitled is the one outcome that must never survive a response."""
        addon = AddOn.objects.create(
            name="Rollback Guard",
            slug="test-addon-rollback",
            description="fixture",
            price=149,
            interval="yearly",
            stripe_price_id="price_rollback_guard",
            is_active=True,
        )
        with mock.patch("subscriptions.views.stripe") as fake_stripe:
            fake_stripe.SubscriptionItem.create.return_value = mock.Mock(id="si_rollback")
            with mock.patch(
                "subscriptions.views.SubscriptionAddOn.objects.update_or_create",
                side_effect=RuntimeError("db down"),
            ):
                r = self.client.post(
                    reverse("subscription-add-addon", args=[self.subscription.id]),
                    {"addon_id": addon.id, "quantity": 1},
                    format="json",
                )

        self.assertEqual(r.status_code, 400, r.content)
        fake_stripe.SubscriptionItem.delete.assert_called_once_with("si_rollback")
        self.assertFalse(SubscriptionAddOn.objects.filter(subscription=self.subscription, addon=addon).exists())

    def test_one_row_per_subscription_and_addon(self):
        """Quantity is the multiplier; a second row is never how you hold two of something.

        `Company.can_create_establishment()` SUMS every matching row, so a duplicate does not
        show up as a double entry in an admin list — it grants capacity nobody bought. Both
        writers (the webhook's `get_or_create`, `add_addon`'s `update_or_create`) are
        SELECT-then-INSERT and neither can guarantee this on its own.
        """
        from django.db import IntegrityError, transaction

        addon = AddOn.objects.create(
            name="Dup Guard",
            slug="test-addon-dup-guard",
            description="fixture",
            price=149,
            interval="yearly",
            is_active=True,
        )
        SubscriptionAddOn.objects.create(subscription=self.subscription, addon=addon, quantity=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SubscriptionAddOn.objects.create(subscription=self.subscription, addon=addon, quantity=1)

    def test_inactive_addon_cannot_be_purchased(self):
        addon = AddOn.objects.create(
            name="Retired Thing",
            slug="test-addon-retired",
            description="fixture",
            price=15,
            interval="monthly",
            stripe_price_id="price_fake",
            is_active=False,
        )
        r = self._post(addon)
        self.assertEqual(r.status_code, 404, r.content)

    def test_addon_checkout_session_route_is_gone(self):
        """The duplicate path that opened a SECOND Stripe subscription.

        Two code paths that bill differently for the same purchase is worse than either of
        them; this one is retired in favour of `add_addon`, which attaches an item to the
        subscription that already exists.
        """
        r = self.client.post(
            reverse("checkout-create-session"),
            {"addon_type": "extraEstablishment", "company_id": str(self.company.id)},
            format="json",
        )
        self.assertEqual(r.status_code, 410, r.content)
        self.assertEqual(r.json()["code"], "USE_ADD_ADDON_ENDPOINT")
