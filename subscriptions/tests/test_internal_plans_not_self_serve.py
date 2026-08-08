"""The `pilot` plan must never be selectable without a human in the loop.

`pilot` is free with unlimited farms, unlimited parcels and unlimited productions. It is granted
by `provision_pilot` during white-glove onboarding. `/api/subscriptions/plans/` is `AllowAny`, so
for as long as pilot appeared there the API was publicly offering a free unlimited plan sitting
directly beside the $249/yr Compliance tier.

This was masked while the $69-299/mo ladder existed — pilot looked like one row among many. The
2026-08-07 restructure retired that ladder, which left pilot as the obviously best free option on
a two-tier page.
"""

from django.test import TestCase
from django.urls import reverse

from subscriptions.models import Plan
from subscriptions.views import internal_plans, self_serve_plans


class InternalPlansAreNotSelfServeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pilot = Plan.objects.create(
            name="Pilot",
            slug="pilot",
            price=0,
            interval="monthly",
            is_active=True,
            features={
                "is_pilot": True,
                "max_establishments": -1,
                "max_parcels_per_establishment": -1,
                "max_productions_per_year": -1,
            },
        )
        cls.starter = Plan.objects.create(
            name="Starter",
            slug="starter",
            price=0,
            interval="monthly",
            is_active=True,
            features={"max_establishments": 1, "max_parcels_per_establishment": -1},
        )
        cls.compliance = Plan.objects.create(
            name="Compliance",
            slug="compliance-yearly",
            price=249,
            interval="yearly",
            is_active=True,
            features={"max_establishments": 1, "max_parcels_per_establishment": -1},
        )

    def test_pilot_is_not_in_the_public_plan_list(self):
        response = self.client.get(reverse("plan-list"))
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        slugs = {row["slug"] for row in rows}

        self.assertNotIn("pilot", slugs, "a free unlimited plan is publicly listed")

    def test_the_sellable_plans_are_still_listed(self):
        """The guard must hide ONE plan, not empty the catalogue."""
        response = self.client.get(reverse("plan-list"))

        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("results", [])
        slugs = {row["slug"] for row in rows}

        self.assertEqual(slugs, {"starter", "compliance-yearly"})

    def test_exclude_on_a_missing_json_key_would_have_emptied_the_catalogue(self):
        """Pins WHY the guard excludes by primary key instead of the obvious expression.

        `.exclude(features__is_pilot=True)` reads as "every plan but pilot". On a JSONField it is
        not: rows without the key compare NULL, `NOT NULL` is not true, and every one of them is
        dropped. The natural-looking filter returns nothing at all, which would have taken the
        pricing and upgrade screens blank rather than merely hiding pilot.
        """
        active = Plan.objects.filter(is_active=True)

        naive = active.exclude(features__is_pilot=True)
        self.assertEqual(list(naive), [], "JSON exclude semantics changed; re-check self_serve_plans")

        correct = self_serve_plans()
        self.assertCountEqual(
            [p.slug for p in correct],
            ["starter", "compliance-yearly"],
        )

    def test_internal_plans_identifies_only_the_pilot_plan(self):
        self.assertCountEqual([p.slug for p in internal_plans()], ["pilot"])

    def test_pilot_stays_active_so_provisioned_companies_keep_their_entitlements(self):
        """The fix must hide pilot, not deactivate it.

        Deactivating would strip already-provisioned pilot farms of the plan their subscription
        points at, which is the opposite of the intent.
        """
        self.pilot.refresh_from_db()
        self.assertTrue(self.pilot.is_active)
