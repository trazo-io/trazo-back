"""The billing dashboard must answer for ONE company — the one the caller names.

MEASURED FAILURE (2026-08-19). A demo account belonging to two companies opened
/admin/dashboard/subscription and read:

    Corporate  Active   $149.00/Monthly   4/1/2026 - 5/1/2026
    Farms 1/4        Parcels 3/16

...while every other surface in the app correctly said Compliance ($249/yr, 1 farm,
unlimited parcels). Corporate is a RETIRED tier (deactivated as a product in migrations
0009/0012, never cancelled as a contract) held by an unrelated, older company of the same
user. The endpoint was:

    Subscription.objects.filter(company__in=user.companies.all()).first()

No ordering, no company. `.first()` on an unordered queryset is whatever Postgres returns
from the heap — so the page rendered a foreign company's plan, price and LIMITS beside the
active company's COUNTS. `3/16` is `max_establishments(4) x max_parcels_per_establishment(4)`
from a plan the active farm is not on, with `3` counted from the active farm's parcels.

That mismatch is not cosmetic: the numbers a farmer reads to decide whether to buy another
farm slot came from a contract they do not hold, and `paymentMethods`/`invoices` listed every
card and invoice across all their companies on one company's billing page.

`Company.subscription` is a OneToOne, so "which subscription" is decided entirely by "which
company". The caller must say which. These tests pin that.
"""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company
from subscriptions.models import Invoice, PaymentMethod, Plan, Subscription
from users.models import User, WorksIn

DASHBOARD_URL = reverse("subscription-dashboard")


def _plan(slug, name, price, features):
    """Plans this module OWNS, on slugs nothing ships.

    Two traps avoided. Migrations 0009/0011 seed the real slugs, so
    `Plan.objects.create(slug="compliance-yearly")` raises UniqueViolation against a migrated
    database — and `update_or_create` on the real slug would instead REWRITE a shipped row's
    price and features, so the assertions below would be reading values this file had just
    invented into the product's own row.

    The endpoint under test has no slug logic at all: scoping is by company. So the tiers here
    only need to be two DISTINGUISHABLE plans, and owning them outright means every number the
    tests assert is a number this file put there.
    """
    return Plan.objects.create(
        name=name,
        slug=slug,
        description=name,
        price=price,
        features=features,
    )


class DashboardScopesToNamedCompanyTests(TestCase):
    """One user, two companies, two live subscriptions on different tiers."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="two-companies@test.com", password="x")

        self.retired_plan = _plan(
            "test-scope-retired-monthly",
            "Corporate",
            149.00,
            {"max_establishments": 4, "max_parcels_per_establishment": 4},
        )
        self.live_plan = _plan(
            "test-scope-live-yearly",
            "Compliance",
            249.00,
            {"max_establishments": 1, "max_parcels_per_establishment": -1},
        )

        self.old_company = Company.objects.create(name="Old Farm", country="USA")
        self.new_company = Company.objects.create(name="New Farm", country="USA")
        for company in (self.old_company, self.new_company):
            WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)

        # SUBSCRIPTION creation order is the one that matters, not the plans': the retired one
        # is inserted FIRST so it holds the lower id, which is both the row an unordered
        # `.first()` tends to return from the heap (the reported bug) and the row the `-id`
        # contract must NOT return.
        self.old_sub = Subscription.objects.create(company=self.old_company, plan=self.retired_plan, status="active")
        self.new_sub = Subscription.objects.create(company=self.new_company, plan=self.live_plan, status="active")

        self.client.force_authenticate(user=self.user)

    def _get(self, company=None):
        params = {"company_id": company.id} if company else {}
        return self.client.get(DASHBOARD_URL, params)

    def test_returns_the_named_companys_subscription(self):
        response = self._get(self.new_company)
        self.assertEqual(response.status_code, 200)

        subscription = response.data["subscription"]
        self.assertIsNotNone(subscription, "scoped dashboard returned no subscription")
        self.assertEqual(
            subscription["plan"]["slug"],
            "test-scope-live-yearly",
            "dashboard returned another company's plan — this is the Corporate/Compliance bug",
        )
        self.assertEqual(subscription["id"], self.new_sub.id)

    def test_returns_the_other_companys_subscription_when_asked_for_it(self):
        """The scoping is real in both directions, not a filter that happens to prefer the newer row."""
        response = self._get(self.old_company)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["subscription"]["plan"]["slug"], "test-scope-retired-monthly")
        self.assertEqual(response.data["subscription"]["id"], self.old_sub.id)

    def test_limits_and_plan_come_from_the_same_row(self):
        """The usage meters read `effective_limits`/`features` off this payload.

        A Compliance farm must never be told it has 4 farms and 4 parcels each. That reading
        is what sends an operator to buy capacity they already have, or stops them logging a
        parcel they are entitled to.
        """
        response = self._get(self.new_company)
        features = response.data["subscription"]["plan"]["features"]
        self.assertEqual(features["max_establishments"], 1)
        self.assertEqual(features["max_parcels_per_establishment"], -1)

    def test_unknown_company_is_not_readable(self):
        stranger_company = Company.objects.create(name="Someone Else Farm", country="USA")
        stranger = User.objects.create_user(email="stranger@test.com", password="x")
        WorksIn.objects.create(user=stranger, company=stranger_company, role=WorksIn.COMPANY_ADMIN)
        Subscription.objects.create(company=stranger_company, plan=self.live_plan, status="active")

        response = self._get(stranger_company)
        self.assertEqual(
            response.status_code,
            404,
            "company_id is a caller-supplied id — it must be validated against the caller's own companies",
        )

    def test_unscoped_call_returns_the_newest_subscription(self):
        """No `company_id` still has to name a row, and WHICH row must be stated, not emergent.

        This deliberately asserts the documented `-id` contract rather than "the same answer
        twice". Repeating an identical query in a quiet test database returns the same heap
        order under the OLD unordered code too, so a two-call stability check passes on the
        very bug it is named after — coverage that cannot fail is worse than none, because it
        reads as protection.
        """
        response = self.client.get(DASHBOARD_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["subscription"]["id"],
            self.new_sub.id,
            "unscoped dashboard must return the newest subscription, per the `-id` ordering",
        )
        self.assertGreater(self.new_sub.id, self.old_sub.id, "test setup assumption: new_sub is newer")

    def test_unscoped_payload_describes_a_single_company(self):
        """Plan from one company and cards from all of them is the same defect, half-fixed.

        The scoped branch cannot show this — it has one company by construction. Unscoped, the
        endpoint still has to pick, and everything in the response must describe whatever it
        picked. Otherwise the billing tab lists a card that cannot pay the plan shown above it.
        """
        PaymentMethod.objects.create(
            company=self.old_company,
            stripe_payment_method_id="pm_old_company",
            card_brand="visa",
            last_4="1111",
            exp_month=12,
            exp_year=2030,
        )
        Invoice.objects.create(company=self.old_company, amount=149, status="paid", invoice_date=timezone.now())

        response = self.client.get(DASHBOARD_URL)
        self.assertEqual(response.data["subscription"]["id"], self.new_sub.id)
        self.assertEqual(
            response.data["paymentMethods"],
            [],
            "unscoped payload returned the OTHER company's card beside this company's plan",
        )
        self.assertEqual(response.data["invoices"], [], "unscoped payload returned the OTHER company's invoice")

    def test_non_numeric_company_id_is_a_bad_request_not_a_crash(self):
        """`Company.id` is an AutoField, so `filter(id="undefined")` raises ValueError.

        Inside the view's blanket `except Exception` that became a 500 plus an ERROR-level
        traceback in the logs — for a malformed query string. `?company_id=undefined` is one
        JavaScript template literal away from happening for real.
        """
        response = self.client.get(DASHBOARD_URL, {"company_id": "undefined"})
        self.assertEqual(response.status_code, 400, "a malformed company_id must not surface as a server error")


class DashboardBillingArtifactsAreScopedTests(TestCase):
    """Cards and invoices belong to a company, not to a user's whole portfolio."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="billing-scope@test.com", password="x")
        self.plan = _plan("test-artifacts-live-yearly", "Compliance", 249.00, {"max_establishments": 1})

        self.company_a = Company.objects.create(name="Farm A", country="USA")
        self.company_b = Company.objects.create(name="Farm B", country="USA")
        for company in (self.company_a, self.company_b):
            WorksIn.objects.create(user=self.user, company=company, role=WorksIn.COMPANY_ADMIN)
            Subscription.objects.create(company=company, plan=self.plan, status="active")

        self.cards = {}
        self.invoices = {}
        for company, last_4 in ((self.company_a, "1111"), (self.company_b, "2222")):
            self.cards[company.id] = PaymentMethod.objects.create(
                company=company,
                stripe_payment_method_id=f"pm_{last_4}",
                card_brand="visa",
                last_4=last_4,
                exp_month=12,
                exp_year=2030,
            )
            self.invoices[company.id] = Invoice.objects.create(
                company=company,
                amount=249,
                status="paid",
                invoice_date=timezone.now(),
            )

        self.client.force_authenticate(user=self.user)

    def test_payment_methods_and_invoices_are_limited_to_the_named_company(self):
        response = self.client.get(DASHBOARD_URL, {"company_id": self.company_a.id})
        self.assertEqual(response.status_code, 200)

        # By id, not by last_4: the serializer does not expose the Stripe id, and two test
        # cards could plausibly share a brand.
        self.assertEqual(
            [pm["id"] for pm in response.data["paymentMethods"]],
            [self.cards[self.company_a.id].id],
            "another company's card was listed on this company's billing page",
        )
        self.assertEqual(
            [inv["id"] for inv in response.data["invoices"]],
            [self.invoices[self.company_a.id].id],
            "another company's invoice was listed on this company's billing page",
        )
