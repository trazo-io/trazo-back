"""Starter is FREE FOREVER — no trial, no clock, no cancellation.

The October plan says it in four places ("Actually free. Starter free forever, pilot free, no
card"), and the COG Pro migration page's entire anti-lock-in answer is "Starter is free
permanently, not a trial" — aimed at refugees from a product that shuts down 2026-12-31.

Until 2026-08-13 the app did the opposite: `CompanyViewSet.create` and `start_trial` both wrote
`status="trialing"` with a 14-day `trial_end`, and `expire_trials` flipped it to "canceled" on day
14. Cancelling nulls `Company.subscription_plan`, which 403s every creation in the app — so a COG
Pro migrant read the promise, signed up, and was locked out two weeks later.

These tests pin the promise, not the implementation detail, so they survive a refactor of where
the subscription is created.
"""

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from company.models import Company
from subscriptions.models import Plan, Subscription


class StarterHasNoTrialClockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # `update_or_create`, not `create`: migrations 0009/0011 SEED the starter, pilot and
        # compliance-yearly rows, so a plain create raises UniqueViolation on `slug` the moment
        # the test DB is built fresh. That is exactly how this suite hides breakage — it passes
        # under `--keepdb` against a database whose plan rows were already reconciled, and errors
        # on the clean build CI would do. (`InternalPlansAreNotSelfServeTests` has the same bug.)
        cls.starter, _ = Plan.objects.update_or_create(
            slug="starter",
            defaults={
                "name": "Starter",
                "price": 0,
                "interval": "monthly",
                "is_active": True,
                "features": {
                    "max_establishments": 1,
                    "max_parcels_per_establishment": -1,
                    "max_productions_per_year": 1,
                },
            },
        )

    def test_the_plan_advertises_no_trial(self):
        """`trial_*` keys are what the pricing page renders "14-day free trial included" from.

        A free-forever tier that still declares trial days will re-grow the claim on the page the
        moment someone reads the feature flags.
        """
        features = Plan.objects.get(slug="starter").features or {}
        offenders = [k for k in features if "trial" in k.lower()]
        self.assertEqual(
            offenders,
            [],
            f"Starter still declares trial config {offenders} — the pricing page renders its "
            f"trial line from these keys",
        )

    def test_expire_trials_never_cancels_starter(self):
        """The regression that locked out COG Pro migrants on day 14.

        The subscription here is deliberately in the worst possible state — `trialing` with a
        `trial_end` a month in the past — because that is exactly what a row created by the old
        code looks like after the change. Legacy rows must survive too, not just new ones.
        """
        company = Company.objects.create(name="Migrant Orchard")
        subscription = Subscription.objects.create(
            company=company,
            plan=self.starter,
            status="trialing",
            trial_end=timezone.now() - timedelta(days=30),
        )

        call_command("expire_trials")

        subscription.refresh_from_db()
        self.assertNotEqual(
            subscription.status,
            "canceled",
            "expire_trials cancelled a Starter subscription — Starter is free forever, and "
            "cancelling nulls Company.subscription_plan and 403s every creation in the app",
        )
        self.assertIsNotNone(
            subscription.company.subscription_plan,
            "the company lost its plan, which is the lockout this test exists to prevent",
        )

    def test_starter_never_receives_trial_expiry_emails(self):
        """Telling a free-forever user their trial ends is the message we promise never to send.

        Both subscriptions sit in the day-11 window (`trialing`, `trial_end` in 3 days) — the
        state a legacy Starter row can still be in — so the guard is exercised rather than
        bypassed by `trial_end=None`.

        The PAID control is load-bearing. `_send_trial_email` also returns False when the company
        has no resolvable recipient, so a Starter-only assertion passes whether or not the guard
        exists: verified by deleting the guard, at which point the first version of this test
        still passed. `contact_email` is set on both companies for the same reason.
        """
        from subscriptions.tasks import send_trial_emails

        paid, _ = Plan.objects.update_or_create(
            slug="compliance-yearly",
            defaults={
                "name": "Compliance",
                "price": 249,
                "interval": "yearly",
                "is_active": True,
                "features": {},
            },
        )

        free_company = Company.objects.create(name="Free Forever Orchard", contact_email="free@example.test")
        Subscription.objects.create(
            company=free_company,
            plan=self.starter,
            status="trialing",
            trial_end=timezone.now() + timedelta(days=3),
        )
        paid_company = Company.objects.create(name="Paying Orchard", contact_email="paid@example.test")
        Subscription.objects.create(
            company=paid_company,
            plan=paid,
            status="trialing",
            trial_end=timezone.now() + timedelta(days=3),
        )

        sent = send_trial_emails()

        self.assertEqual(
            sent["day_11"],
            1,
            "the paid control received no email, so this test cannot prove the Starter guard "
            f"does anything — check _resolve_recipient and the day-11 window. Got {sent}",
        )
        starter_notifications = Subscription.objects.get(company=free_company).email_notifications_sent or {}
        self.assertEqual(
            starter_notifications,
            {},
            f"a Starter subscription was sent trial lifecycle email(s): {starter_notifications}",
        )
