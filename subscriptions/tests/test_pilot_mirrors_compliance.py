"""A pilot must experience exactly the product it will later be asked to pay for.

`pilot` used to grant unlimited farms, 50 GB and 12hr support while Compliance — the only plan for
sale — grants 1 farm, 25 GB and 24hr support. Converting therefore meant starting to pay AND
losing three things in the same conversation.

The storage half was a hard blocker rather than a bad feeling: `storage_utils` refuses uploads
past the limit, so a pilot who logged 40 GB of photo evidence could not move to Compliance's 25 GB
without deleting their own records — during renewal season.

It also invalidated the Apr 30 conversion verdict, which is meant to measure willingness to pay
for Trazo and instead measured willingness to pay for a tier that is not sold.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from subscriptions.models import Plan, Subscription, mrr_for

# The limits that are actually ENFORCED at runtime. A mismatch in any of these is a capability the
# grower loses on the day they start paying.
ENFORCED_LIMITS = (
    "max_establishments",
    "max_parcels_per_establishment",
    "max_productions_per_year",
    "storage_limit_gb",
    # Added 2026-08-14 and now the load-bearing one. Starter grants the same capacity limits as
    # Compliance, so `compliance_exports` is the ONLY entitlement separating free from paid: a
    # pilot without it would spend the season unable to produce the certifier packet, the audit
    # exports, the PUR export or a certifier link — a pilot of a product nobody is being asked
    # to buy.
    "compliance_exports",
)


class PilotMirrorsComplianceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_plans", stdout=StringIO(), stderr=StringIO())

    def test_pilot_grants_exactly_the_compliance_limits(self):
        pilot = Plan.objects.get(slug="pilot").features
        compliance = Plan.objects.get(slug="compliance-yearly").features

        for key in ENFORCED_LIMITS:
            with self.subTest(limit=key):
                self.assertEqual(
                    pilot.get(key),
                    compliance.get(key),
                    f"a pilot would lose {key} on conversion",
                )

    def test_pilot_storage_does_not_exceed_what_a_customer_can_buy(self):
        """The specific trap: storage is enforced, so extra headroom becomes undeletable data."""
        pilot = Plan.objects.get(slug="pilot").features
        compliance = Plan.objects.get(slug="compliance-yearly").features

        self.assertLessEqual(
            pilot["storage_limit_gb"],
            compliance["storage_limit_gb"],
            "a pilot can fill storage they cannot keep, and uploads hard-block over quota",
        )

    def test_pilot_is_still_free_and_still_books_no_revenue(self):
        """Mirroring Compliance must not mirror its PRICE."""
        pilot = Plan.objects.get(slug="pilot")

        self.assertEqual(pilot.price, 0)
        self.assertEqual(mrr_for(pilot, "active"), 0, "a comped pilot would report revenue that does not exist")

    def test_pilot_keeps_the_flag_that_hides_it_from_the_public_list(self):
        self.assertIs(Plan.objects.get(slug="pilot").features.get("is_pilot"), True)

    def test_pilot_carries_no_trial_timer(self):
        """A pilot ends by agreement on a real renewal date, not by expire_trials."""
        pilot = Plan.objects.get(slug="pilot").features

        self.assertEqual(pilot.get("trial_no_card_days"), 0)
        self.assertEqual(pilot.get("trial_with_card_days"), 0)


class ProvisionPilotRecordsATermTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from users.models import User

        call_command("create_plans", stdout=StringIO(), stderr=StringIO())
        User.objects.create_user(email="operator@trazo.test", password="x", is_active=True)

    def _provision(self, renewal_date, company="Sierra Nut Co"):
        call_command(
            "provision_pilot",
            "--company",
            company,
            "--email",
            "maria@sierranut.test",
            "--farm",
            "Home Ranch",
            "--state",
            "CA",
            "--operator-email",
            "operator@trazo.test",
            "--renewal-date",
            renewal_date,
            "--commit",
            stdout=StringIO(),
            stderr=StringIO(),
        )
        return Subscription.objects.get(company__name=company)

    def test_the_renewal_date_becomes_the_end_of_the_comp_period(self):
        subscription = self._provision("2027-01-01")

        self.assertIsNotNone(subscription.current_period_end)
        self.assertEqual(subscription.current_period_end.date().isoformat(), "2027-01-01")

    def test_a_past_renewal_date_is_refused(self):
        past = (timezone.now() - timedelta(days=30)).date().isoformat()

        with self.assertRaises(CommandError) as ctx:
            self._provision(past)
        self.assertIn("past", str(ctx.exception))

    def test_an_unparseable_renewal_date_is_refused(self):
        with self.assertRaises(CommandError) as ctx:
            self._provision("next tuesday")
        self.assertIn("YYYY-MM-DD", str(ctx.exception))

    def test_the_provisioned_pilot_can_still_do_the_work(self):
        """The 1-farm cap must not break the things a pilot actually needs."""
        subscription = self._provision("2027-01-01")
        company = subscription.company
        farm = company.establishment_set.first()

        self.assertIsNotNone(company.subscription_plan)
        self.assertTrue(company.can_create_parcel(farm))
        self.assertTrue(company.can_create_production())

    def test_the_comp_period_does_not_gate_access(self):
        """`current_period_end` is a conversation trigger, not a kill switch.

        Nothing in the codebase denies access on it, and `expire_trials` only touches
        plan__slug="starter". If that ever changes, a pilot would be locked out mid-season on a
        date chosen for a sales conversation — so this pins the intent.
        """
        subscription = self._provision("2027-01-01")
        subscription.current_period_end = timezone.now() - timedelta(days=1)
        subscription.save(update_fields=["current_period_end"])

        call_command("expire_trials", stdout=StringIO(), stderr=StringIO())

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, "active", "an expired comp period cancelled a pilot")
        self.assertIsNotNone(subscription.company.subscription_plan)
