"""Cancelling is a DOWNGRADE, never a lockout.

Until 2026-08-22 the end of a paid subscription set `status="canceled"` and stopped there, and
`Company.subscription_plan` resolved for no status but active/trialing. None cascades: no
parcels, no productions, no photo or document upload, no voice, and 403 on all seven
compliance-export doors. A farmer who paid $249 and chose not to renew ended up strictly worse
off than a stranger signing up that morning — who lands on Starter, free forever.

The old behaviour was PINNED by a test (`test_creation_limits.py`), so this is a deliberate
reversal of a documented decision rather than a bug fix, and these are the assertions that
replace it.

⚠️ EVERY TEST HERE SEEDS STARTER EXPLICITLY. The fallback resolves through
`Plan.objects.filter(slug="starter", is_active=True)`, so on a database where Starter is absent
it returns None and the OLD lockout assertions still pass — vacuously, for the wrong reason.
That is not hypothetical: it is exactly what happened to the pre-existing
`test_a_canceled_subscription_blocks_everything` the first time this change was run against it.
A test in this file that forgets `_starter()` is testing nothing.
"""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from product.models import Parcel
from subscriptions.models import Plan, Subscription, SubscriptionEvent

STARTER_FEATURES = {
    "max_establishments": 1,
    "max_parcels_per_establishment": -1,
    "max_productions_per_year": -1,
    "storage_limit_gb": 10,
    "compliance_exports": False,
    "voice_recording": True,
}

PAID_FEATURES = {
    "max_establishments": 1,
    "max_parcels_per_establishment": -1,
    "max_productions_per_year": -1,
    "storage_limit_gb": 25,
    "compliance_exports": True,
    "voice_recording": True,
}


def _starter():
    plan, _ = Plan.objects.update_or_create(
        slug="starter",
        defaults={
            "name": "Trazo Starter",
            "description": "Free forever",
            "price": 0,
            "interval": "monthly",
            "is_active": True,
            "features": STARTER_FEATURES,
        },
    )
    return plan


def _paid(slug="compliance-yearly", price=249, interval="yearly", **feature_overrides):
    features = {**PAID_FEATURES, **feature_overrides}
    plan, _ = Plan.objects.update_or_create(
        slug=slug,
        defaults={
            "name": slug,
            "description": slug,
            "price": price,
            "interval": interval,
            "is_active": True,
            "features": features,
        },
    )
    return plan


def _subscribed(plan, *, status="active", name="Blue Oak Orchards", **extra):
    company = Company.objects.create(name=name)
    defaults = {
        "company": company,
        "plan": plan,
        "status": status,
        "current_period_start": timezone.now() - timedelta(days=5),
        "current_period_end": timezone.now() + timedelta(days=25),
        "stripe_subscription_id": "sub_test_123",
        "stripe_customer_id": "cus_test_123",
    }
    defaults.update(extra)
    Subscription.objects.create(**defaults)
    company.refresh_from_db()
    return company


def _farm(company):
    return Establishment.objects.create(name="Home Ranch", company=company, country="US", state="CA")


class PlanResolutionTests(TestCase):
    """`Company.subscription_plan` answers "entitled to", not "subscribed to"."""

    def test_active_paid_subscription_resolves_its_own_plan(self):
        starter = _starter()
        paid = _paid()
        company = _subscribed(paid)
        self.assertEqual(company.subscription_plan, paid)
        self.assertNotEqual(company.subscription_plan, starter)

    def test_canceled_subscription_falls_back_to_starter_instead_of_nothing(self):
        # THE regression. Previously `assertIsNone`.
        _starter()
        company = _subscribed(_paid(), status="canceled")

        self.assertIsNotNone(company.subscription_plan, "a canceled subscription must not null the plan")
        self.assertEqual(company.subscription_plan.slug, "starter")

    def test_canceled_farm_can_still_log_its_own_records(self):
        """The point of the whole change: §205.103(b)(3) records must not become unreachable."""
        _starter()
        company = _subscribed(_paid(), status="canceled")
        farm = _farm(company)

        self.assertTrue(company.can_create_parcel(farm), "a lapsed farm must still be able to add a parcel")
        self.assertTrue(company.can_create_production(), "a lapsed farm must still be able to start a season")

    def test_canceled_farm_loses_the_certifier_outputs_and_only_those(self):
        _starter()
        company = _subscribed(_paid(), status="canceled")

        self.assertFalse(company.has_feature("compliance_exports"), "exports are what the paid tier buys")
        self.assertTrue(company.has_feature("voice_recording"), "logging tools are not what lapses")
        self.assertEqual(company.get_feature_limit("storage_limit_gb"), 10, "Starter's 10 GB, not zero")

    def test_past_due_keeps_the_paid_plan_for_the_whole_retry_window(self):
        """A declined card must not read as a permissions failure.

        Stripe Smart Retries run for three to four weeks. Dropping the plan on the first failed
        charge locked a paying, still-contracted customer out of a season's records and told
        them "your subscription plan does not allow creating more parcels".
        """
        _starter()
        paid = _paid()
        company = _subscribed(paid, status="past_due")

        self.assertEqual(company.subscription_plan, paid)
        self.assertTrue(company.has_feature("compliance_exports"))

    def test_past_due_is_still_counted_as_revenue(self):
        """Consistency check: access and MRR must agree about who is a customer."""
        from company.models import PAID_PLAN_STATUSES
        from subscriptions.models import MRR_STATUSES

        self.assertIn("past_due", PAID_PLAN_STATUSES)
        self.assertIn("past_due", MRR_STATUSES)

    def test_unpaid_falls_back_to_starter(self):
        """`unpaid` means Stripe gave up collecting — keep them logging, stop the paid features."""
        _starter()
        company = _subscribed(_paid(), status="unpaid")

        self.assertEqual(company.subscription_plan.slug, "starter")
        self.assertFalse(company.has_feature("compliance_exports"))

    def test_an_unknown_status_degrades_to_starter_rather_than_locking_out(self):
        """Fail-SAFE, not fail-closed, for a status this code has never heard of."""
        _starter()
        company = _subscribed(_paid())
        Subscription.objects.filter(company=company).update(status="paused")
        company = Company.objects.get(pk=company.pk)

        self.assertEqual(company.subscription_plan.slug, "starter")

    def test_no_subscription_row_still_fails_closed(self):
        """A company with no subscription is corruption, not a tier. Preserved deliberately."""
        _starter()
        company = Company.objects.create(name="No subscription")

        self.assertIsNone(company.subscription_plan)
        self.assertFalse(company.can_create_parcel(_farm(company)))

    def test_missing_starter_row_fails_closed_rather_than_inventing_an_allowance(self):
        """`create_plans` is the only thing that creates plan rows. No Starter = broken install."""
        company = _subscribed(_paid(), status="canceled")  # no _starter() on purpose
        self.assertIsNone(company.subscription_plan)

    def test_an_inactive_starter_row_is_not_a_fallback(self):
        starter = _starter()
        starter.is_active = False
        starter.save(update_fields=["is_active"])
        company = _subscribed(_paid(), status="canceled")

        self.assertIsNone(company.subscription_plan)


class LapsedAddOnTests(TestCase):
    """Add-on rows outlive the subscription that bought them. Entitlement must not."""

    def _with_extra_farms(self, status, quantity=3):
        from subscriptions.models import AddOn, SubscriptionAddOn

        company = _subscribed(_paid(), status=status)
        addon, _ = AddOn.objects.get_or_create(
            slug="extra-establishment",
            defaults={
                "name": "Extra Farm",
                "description": "One more farm",
                "price": 149,
                "interval": "yearly",
                "is_active": True,
            },
        )
        SubscriptionAddOn.objects.create(subscription=company.subscription, addon=addon, quantity=quantity)
        return Company.objects.get(pk=company.pk)

    def test_paid_subscription_counts_its_add_ons(self):
        _starter()
        company = self._with_extra_farms("active")
        # 1 base + 3 purchased, and no farms created yet.
        self.assertTrue(company.can_create_establishment())
        self.assertEqual(company._addon_quantity("extra-establishment"), 3)

    def test_a_lapsed_subscription_stops_counting_its_add_ons(self):
        """Otherwise three Extra Farms bought once become a permanent free allowance of four."""
        _starter()
        company = self._with_extra_farms("canceled")

        self.assertEqual(company._addon_quantity("extra-establishment"), 0)
        _farm(company)  # Starter's single farm is now used
        self.assertFalse(company.can_create_establishment())

    def test_existing_farms_are_never_taken_away(self):
        """A downgrade caps what you can CREATE. It never destroys what exists."""
        _starter()
        company = self._with_extra_farms("canceled")
        for i in range(4):
            Establishment.objects.create(name=f"Farm {i}", company=company, country="US", state="CA")

        self.assertEqual(company.establishment_set.count(), 4)
        self.assertFalse(company.can_create_establishment(), "no NEW farm")
        # ...and every existing one is still fully usable.
        farm = company.establishment_set.first()
        self.assertTrue(company.can_create_parcel(farm))


class LandOnFreeTierTests(TestCase):
    """`views.land_on_free_tier` — what the Stripe `customer.subscription.deleted` webhook does."""

    def _land(self, **kwargs):
        from subscriptions.views import land_on_free_tier

        _starter()
        company = _subscribed(_paid(), **kwargs)
        land_on_free_tier(company.subscription)
        return Subscription.objects.get(company=company)

    def test_the_row_is_repointed_at_starter_and_left_active(self):
        sub = self._land()
        self.assertEqual(sub.plan.slug, "starter")
        self.assertEqual(sub.status, "active", "the customer is a Starter customer, not a dead row")

    def test_the_dead_stripe_subscription_id_is_cleared(self):
        """Any later `Subscription.modify` against a deleted Stripe subscription 404s."""
        self.assertIsNone(self._land().stripe_subscription_id)

    def test_the_stripe_customer_id_survives_for_win_back(self):
        """The customer still exists in Stripe and still owns the cards and invoice history."""
        self.assertEqual(self._land().stripe_customer_id, "cus_test_123")

    def test_starter_carries_no_period_end_because_it_never_renews(self):
        """Otherwise the billing page prints a "next billing date" for a plan that never bills."""
        sub = self._land()
        self.assertIsNone(sub.current_period_end)
        self.assertIsNone(sub.trial_end)

    def test_a_pending_cancellation_flag_is_cleared(self):
        sub = self._land(cancel_at_period_end=True)
        self.assertFalse(sub.cancel_at_period_end)

    def test_the_company_can_immediately_log_again(self):
        from subscriptions.views import land_on_free_tier

        _starter()
        company = _subscribed(_paid())
        land_on_free_tier(company.subscription)

        company = Company.objects.get(pk=company.pk)
        self.assertTrue(company.can_create_parcel(_farm(company)))

    def test_it_refuses_rather_than_half_finishing_when_starter_is_missing(self):
        """No Starter row means a broken install. Leaving the paid plan in place is safer than
        writing a state nothing can resolve — and the error log is the only thing that says so."""
        from subscriptions.views import land_on_free_tier

        paid = _paid()
        company = _subscribed(paid)
        with self.assertLogs("subscriptions.views", level="ERROR"):
            land_on_free_tier(company.subscription)

        self.assertEqual(Subscription.objects.get(company=company).plan, paid)


class ChurnIsRecordedAsChurnTests(TestCase):
    """The event log has to keep calling this a cancellation once it looks like a downgrade."""

    def test_moving_to_a_free_plan_is_logged_as_canceled_not_downgraded(self):
        _starter()
        company = _subscribed(_paid())
        from subscriptions.views import land_on_free_tier

        land_on_free_tier(company.subscription)

        events = SubscriptionEvent.objects.filter(company=company)
        self.assertEqual(events.filter(event_type="canceled").count(), 1)
        self.assertEqual(events.filter(event_type="downgraded").count(), 0, "churn must not hide in downgrades")

    def test_the_full_mrr_loss_is_booked(self):
        _starter()
        company = _subscribed(_paid())
        from subscriptions.views import land_on_free_tier

        land_on_free_tier(company.subscription)

        ev = SubscriptionEvent.objects.get(company=company, event_type="canceled")
        self.assertEqual(ev.mrr_before, Decimal("249"))
        self.assertEqual(ev.mrr_after, Decimal("0"))
        self.assertEqual(ev.mrr_delta, Decimal("-249"))

    def test_a_paid_to_paid_drop_is_still_a_downgrade(self):
        """The new rule keys off MRR reaching ZERO. A cheaper PAID plan is unaffected."""
        _starter()
        expensive = _paid("operation-yearly", price=1200)
        cheaper = _paid("compliance-yearly", price=249)
        company = _subscribed(expensive)

        sub = company.subscription
        sub.plan = cheaper
        sub.save()

        self.assertEqual(SubscriptionEvent.objects.filter(company=company, event_type="downgraded").count(), 1)
        self.assertEqual(SubscriptionEvent.objects.filter(company=company, event_type="canceled").count(), 0)

    def test_the_cancellation_reason_is_snapshotted_onto_the_event(self):
        """`Subscription` is overwritten in place; the append-only log is where this lives."""
        _starter()
        company = _subscribed(_paid())
        sub = company.subscription
        sub.cancellation_reason = "seasonal"
        sub.cancellation_feedback = "Back for next season's almonds"
        sub.save(update_fields=["cancellation_reason", "cancellation_feedback"])

        from subscriptions.views import land_on_free_tier

        land_on_free_tier(Subscription.objects.get(pk=sub.pk))

        ev = SubscriptionEvent.objects.get(company=company, event_type="canceled")
        self.assertEqual(ev.metadata.get("cancellation_reason"), "seasonal")
        self.assertIn("almonds", ev.metadata.get("cancellation_feedback", ""))


class GetActiveCompanyTests(TestCase):
    """`User.get_active_company` — the SECOND lockout path, and previously untested.

    It filtered `subscription__status__in=["active", "trialing"]`, the same two-status list that
    gated `Company.subscription_plan`. So a declined card did not merely cost a farm its plan —
    it made the company stop existing as far as this method was concerned, and it returned None.
    That is worse, because this is the fallback that resolves the company for photo and document
    uploads, voice recording, support tickets and three creation permissions.

    ⚠️ The only existing test of this method (`users/tests/test_models.py::test_get_active_company`)
    raises `TypeError` in its own `setUp` — `Establishment(created_by=...)` is not a field and has
    not been for some time — so it has been failing for reasons unrelated to what it claims to
    check, and could not have caught any of this.
    """

    def setUp(self):
        from users.models import User, WorksIn

        _starter()
        self.paid = _paid()
        self.user = User.objects.create_user(email="grower@example.com", password="pw-for-test-only")
        self.WorksIn = WorksIn

    def _company(self, name, status, plan=None):
        company = Company.objects.create(name=name)
        Subscription.objects.create(
            company=company,
            plan=plan or self.paid,
            status=status,
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=25),
        )
        self.WorksIn.objects.create(user=self.user, company=company, role=self.WorksIn.COMPANY_ADMIN)
        return company

    def test_a_past_due_company_is_still_the_active_company(self):
        """THE regression. Previously None, which reads to the app as "belongs to nobody"."""
        company = self._company("Declined Card Farm", "past_due")
        self.assertEqual(self.user.get_active_company(), company)

    def test_a_lapsed_company_is_still_the_active_company(self):
        company = self._company("Lapsed Farm", "canceled")
        self.assertEqual(self.user.get_active_company(), company)

    def test_the_paying_company_wins_when_a_user_works_in_two(self):
        """A user with a lapsed farm and a paying one must land on the paying one."""
        self._company("Lapsed Farm", "canceled")
        paying = self._company("Paying Farm", "active")
        self.assertEqual(self.user.get_active_company(), paying)

    def test_the_answer_does_not_depend_on_insertion_order(self):
        """Ordering is explicit. `.first()` with no `order_by` returns whatever Postgres has to
        hand, which already produced a billing page mixing two companies' data."""
        paying = self._company("Paying Farm", "active")
        self._company("Lapsed A", "canceled")
        self._company("Lapsed B", "unpaid")
        for _ in range(3):
            self.assertEqual(self.user.get_active_company(), paying)

    def test_a_trialing_company_still_counts(self):
        company = self._company("Trial Farm", "trialing")
        self.assertEqual(self.user.get_active_company(), company)

    def test_a_user_who_works_nowhere_gets_none(self):
        self.assertIsNone(self.user.get_active_company())

    def test_a_company_with_no_subscription_is_returned_and_fails_closed_downstream(self):
        """Returned here so the app knows which company it is; refused at the PLAN gate, which
        is where that decision belongs and where it produces an actionable error."""
        company = Company.objects.create(name="No subscription")
        self.WorksIn.objects.create(user=self.user, company=company, role=self.WorksIn.COMPANY_ADMIN)

        self.assertEqual(self.user.get_active_company(), company)
        self.assertIsNone(company.subscription_plan)
