"""`create_plans` must never mint a Stripe price for a product Trazo does not sell.

The blockchain add-on was withdrawn on 2026-08-03 and seeded `is_active=False`. But that flag was
only applied at the `update_or_create` — AFTER `stripe.Product.create` and `stripe.Price.create`
had already run. So seeding any fresh environment created a live, recurring **$15/mo** price in
Stripe for a product that had been withdrawn four months earlier.

Related, and the reason this matters beyond tidiness: withdrawing a product in DATA is not the
same as withdrawing it from the world. That add-on sat `is_active=False` while both UIs still
rendered a hardcoded $15 offer for months.
"""

from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings


# The Stripe branch is what this module guards, so it pins a key of its own. Reading the runner's
# environment made the active add-on test fail wherever STRIPE_SECRET_KEY is blank: `create_plans`
# then seeds local rows only and calls Stripe for nothing. Every Stripe entry point is patched below,
# so the key is never sent anywhere.
@override_settings(STRIPE_SECRET_KEY="sk_test_not_a_real_key")
class WithdrawnAddOnsNeverReachStripeTests(TestCase):
    def setUp(self):
        # Every Stripe entry point is patched: a test that reached the network would be both
        # flaky and, with a live key, genuinely destructive.
        self.product_create = patch("stripe.Product.create").start()
        self.price_create = patch("stripe.Price.create").start()
        self.product_create.return_value = type("P", (), {"id": "prod_test"})()
        self.price_create.return_value = type("Pr", (), {"id": "price_test"})()
        self.addCleanup(patch.stopall)

    def _stripe_products_created(self):
        return [call.kwargs.get("name", "") for call in self.product_create.call_args_list]

    def _stripe_metadata_slugs(self):
        return [call.kwargs.get("metadata", {}).get("addon_slug") for call in self.price_create.call_args_list]

    def test_blockchain_addon_gets_no_stripe_product_or_price(self):
        call_command("create_plans")

        self.assertNotIn(
            "blockchain-verification",
            self._stripe_metadata_slugs(),
            "the withdrawn blockchain add-on minted a Stripe price",
        )
        blockchain_products = [name for name in self._stripe_products_created() if "Blockchain" in name]
        self.assertEqual(
            blockchain_products, [], f"Stripe products created for a withdrawn add-on: {blockchain_products}"
        )

    def test_the_local_row_is_still_seeded_so_references_do_not_dangle(self):
        call_command("create_plans")

        from subscriptions.models import AddOn

        addon = AddOn.objects.filter(slug="blockchain-verification").first()
        self.assertIsNotNone(addon, "the row must still exist; only Stripe is skipped")
        self.assertFalse(addon.is_active)
        self.assertFalse(addon.stripe_price_id, "a withdrawn add-on must carry no Stripe price id")

    def test_active_addons_are_unaffected(self):
        call_command("create_plans")

        # extra-establishment is the only add-on Trazo still sells. A second farm is genuinely
        # more product under per-farm pricing, so it keeps its Stripe path.
        self.assertIn("extra-establishment", self._stripe_metadata_slugs())

    def test_capacity_addons_superseded_by_unlimited_never_reach_stripe(self):
        """extra-parcel and extra-production sell capacity the live tiers already grant.

        Both were withdrawn on 2026-08-07 (migration 0010) when Starter gained unlimited parcels
        and Compliance gained unlimited parcels AND productions. Charging for capacity the plan
        already includes is a billing defect, not stale copy.

        This asserts the flag lives in `create_plans` and not only in the migration. The migration
        fixes the database that exists; `create_plans` is what builds the NEXT one, and a reseed
        that re-activated these would silently undo the withdrawal — the exact way the $15/mo
        blockchain offer survived its own withdrawal for four months.
        """
        call_command("create_plans")

        from subscriptions.models import AddOn

        slugs = self._stripe_metadata_slugs()
        for withdrawn in ("extra-parcel", "extra-production"):
            with self.subTest(slug=withdrawn):
                self.assertNotIn(withdrawn, slugs, f"{withdrawn} minted a Stripe price after withdrawal")
                addon = AddOn.objects.filter(slug=withdrawn).first()
                self.assertIsNotNone(addon, "the row must still exist; only the offer is withdrawn")
                self.assertFalse(addon.is_active, f"{withdrawn} is still offered for sale")

    def test_free_plans_never_touch_stripe(self):
        # Starter and Pilot are both priced 0. A Stripe product for a free plan would be noise at
        # best and a billable artefact at worst.
        call_command("create_plans")

        plan_slugs = [call.kwargs.get("metadata", {}).get("plan_slug") for call in self.price_create.call_args_list]
        self.assertNotIn("starter", plan_slugs)
        self.assertNotIn("pilot", plan_slugs)

    def test_the_pilot_plan_is_seeded_locally(self):
        call_command("create_plans")

        from subscriptions.models import Plan

        pilot = Plan.objects.filter(slug="pilot").first()
        self.assertIsNotNone(pilot)
        self.assertEqual(pilot.price, 0)
        self.assertIsNone(pilot.stripe_price_id)
        self.assertIs(pilot.features.get("is_pilot"), True)
