"""
Cohort/MRR instrumentation (2026-07).

`Subscription` holds current state only — plan and status are overwritten in place — so
retention and MRR movement cannot be reconstructed after the fact. SubscriptionEvent is
the append-only record and SubscriptionMonthlySnapshot is the point-in-time state.

These tests pin the two properties that make that data trustworthy:
  1. every lifecycle transition produces exactly one event, whatever code path wrote it
  2. a snapshot of a PAST month reflects that month, not today's subscription row
"""

from datetime import date, timedelta

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from company.models import Company
from subscriptions.models import Plan, Subscription, SubscriptionEvent, SubscriptionMonthlySnapshot


def _add_months(value: date, months: int) -> date:
    total = value.month - 1 + months
    return date(value.year + total // 12, total % 12 + 1, 1)


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Event Farm", country="USA")
        self.basic = Plan.objects.create(name="Basic", slug="basic", description="b", price=69, interval="monthly")
        self.standard = Plan.objects.create(
            name="Standard", slug="standard", description="s", price=119, interval="monthly"
        )

    def _events(self, **filters):
        return SubscriptionEvent.objects.filter(company=self.company, **filters)


class SubscriptionEventEmissionTests(_Base):
    def test_creation_emits_created_event(self):
        Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        ev = self._events().get()
        self.assertEqual(ev.event_type, "created")
        self.assertEqual(ev.to_plan_slug, "basic")
        self.assertEqual(ev.mrr_after, 69)

    def test_trial_creation_emits_trial_started(self):
        Subscription.objects.create(company=self.company, plan=self.basic, status="trialing")
        self.assertEqual(self._events().get().event_type, "trial_started")

    def test_upgrade_records_mrr_movement(self):
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        sub.plan = self.standard
        sub.save()

        ev = self._events(event_type="upgraded").get()
        self.assertEqual(ev.from_plan_slug, "basic")
        self.assertEqual(ev.to_plan_slug, "standard")
        self.assertEqual(ev.mrr_before, 69)
        self.assertEqual(ev.mrr_after, 119)
        self.assertEqual(ev.mrr_delta, 50)

    def test_downgrade_is_classified_separately_from_upgrade(self):
        sub = Subscription.objects.create(company=self.company, plan=self.standard, status="active")
        sub.plan = self.basic
        sub.save()
        self.assertEqual(self._events(event_type="downgraded").count(), 1)

    def test_cancel_then_reactivate(self):
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        sub.status = "canceled"
        sub.save()
        sub.status = "active"
        sub.save()

        self.assertEqual(self._events(event_type="canceled").count(), 1)
        self.assertEqual(self._events(event_type="reactivated").count(), 1)

    def test_trial_conversion_is_distinct_from_reactivation(self):
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="trialing")
        sub.status = "active"
        sub.save()
        self.assertEqual(self._events(event_type="trial_converted").count(), 1)

    def test_cancel_with_plan_drop_is_a_cancel_not_a_downgrade(self):
        """A cancellation that also drops the plan must not be logged as churn-by-downgrade."""
        sub = Subscription.objects.create(company=self.company, plan=self.standard, status="active")
        sub.plan = self.basic
        sub.status = "canceled"
        sub.save()

        self.assertEqual(self._events(event_type="canceled").count(), 1)
        self.assertEqual(self._events(event_type="downgraded").count(), 0)

    def test_unrelated_save_emits_nothing(self):
        """Usage counters and trial-email bookkeeping must not pollute the lifecycle log."""
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        baseline = self._events().count()

        sub.used_productions = 5
        sub.scan_count = 42
        sub.save()

        self.assertEqual(self._events().count(), baseline)

    def test_cancellation_records_the_mrr_loss(self):
        """
        A cancel must land mrr_after at 0. Reading the price off the still-attached plan
        would make churn look like zero revenue lost.
        """
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        sub.status = "canceled"
        sub.save()

        ev = self._events(event_type="canceled").get()
        self.assertEqual(ev.mrr_before, 69)
        self.assertEqual(ev.mrr_after, 0)
        self.assertEqual(ev.mrr_delta, -69)

    def test_trial_contributes_no_mrr_until_it_converts(self):
        """Trazo's trial is 14 days with no card — counting it as revenue inflates MRR."""
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="trialing")
        self.assertEqual(self._events(event_type="trial_started").get().mrr_after, 0)

        sub.status = "active"
        sub.save()
        conv = self._events(event_type="trial_converted").get()
        self.assertEqual(conv.mrr_before, 0)
        self.assertEqual(conv.mrr_after, 69)

    def test_abandoned_checkout_is_not_booked_as_an_upgrade(self):
        """An incomplete checkout alongside a plan change must not book expansion MRR."""
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        sub.plan = self.standard
        sub.status = "incomplete"
        sub.save()

        self.assertEqual(self._events(event_type="upgraded").count(), 0)
        ev = self._events(event_type="status_changed").get()
        self.assertEqual(ev.mrr_after, 0)

    def test_mrr_snapshot_survives_a_later_price_change(self):
        """
        The whole reason mrr_* are stored rather than joined: repricing a Plan in 2027
        must not rewrite what a 2026 customer actually paid.
        """
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        sub.plan = self.standard
        sub.save()

        self.basic.price = 99
        self.basic.save()

        ev = self._events(event_type="upgraded").get()
        self.assertEqual(ev.mrr_before, 69)


class SubscriptionSnapshotTests(_Base):
    def test_snapshot_is_idempotent(self):
        Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        call_command("snapshot_subscriptions")
        call_command("snapshot_subscriptions")

        self.assertEqual(SubscriptionMonthlySnapshot.objects.filter(company=self.company).count(), 1)

    def test_snapshot_records_plan_and_cohort(self):
        Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        call_command("snapshot_subscriptions")

        snap = SubscriptionMonthlySnapshot.objects.get(company=self.company)
        self.assertEqual(snap.plan_slug, "basic")
        self.assertEqual(snap.mrr, 69)
        self.assertTrue(snap.is_active)
        self.assertEqual(snap.cohort_month, date.today().replace(day=1))
        self.assertFalse(snap.is_reconstructed)

    def test_past_month_reflects_that_month_not_todays_row(self):
        """
        The bug this guards: snapshotting a past month by reading Subscription directly
        writes TODAY's plan into a historical row. State must come from the event log.
        """
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        # Upgrade first: sub.save() writes every field from memory, so backdating before
        # this would be undone by the stale in-memory created_at.
        sub.plan = self.standard
        sub.save()

        last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
        back_then = timezone.make_aware(timezone.datetime(last_month.year, last_month.month, 2, 12, 0))
        # Only the creation event moves back; the upgrade stays in the current month.
        SubscriptionEvent.objects.filter(company=self.company, event_type="created").update(occurred_at=back_then)
        Subscription.objects.filter(pk=sub.pk).update(created_at=back_then)

        call_command("snapshot_subscriptions", "--month", f"{last_month:%Y-%m}")

        snap = SubscriptionMonthlySnapshot.objects.get(company=self.company, month=last_month)
        self.assertEqual(snap.plan_slug, "basic", "past month must not inherit today's plan")
        self.assertEqual(snap.mrr, 69)
        self.assertFalse(snap.is_reconstructed)

    def test_past_month_mrr_survives_a_later_price_change(self):
        """
        Snapshots must take MRR from the event's own `mrr_after`, never from the live
        Plan.price. Otherwise re-running the command after a repricing rewrites history —
        the exact failure SubscriptionEvent exists to prevent.
        """
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
        back_then = timezone.make_aware(timezone.datetime(last_month.year, last_month.month, 2, 12, 0))
        SubscriptionEvent.objects.filter(company=self.company).update(occurred_at=back_then)
        Subscription.objects.filter(pk=sub.pk).update(created_at=back_then)

        # Reprice AFTER the fact, then snapshot the historical month.
        self.basic.price = 199
        self.basic.save()
        call_command("snapshot_subscriptions", "--month", f"{last_month:%Y-%m}")

        snap = SubscriptionMonthlySnapshot.objects.get(company=self.company, month=last_month)
        self.assertEqual(snap.mrr, 69, "historical MRR must not follow a later price change")

    def test_future_month_is_refused(self):
        Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        next_month = _add_months(date.today().replace(day=1), 1)
        with self.assertRaises(CommandError):
            call_command("snapshot_subscriptions", "--month", f"{next_month:%Y-%m}")

    def test_month_predating_the_event_log_is_flagged_reconstructed(self):
        sub = Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        old_month = date.today().replace(day=1) - timedelta(days=90)
        old_month = old_month.replace(day=1)
        Subscription.objects.filter(pk=sub.pk).update(
            created_at=timezone.make_aware(timezone.datetime(old_month.year, old_month.month, 2, 12, 0))
        )
        # No events exist that far back — state can only be inferred.
        SubscriptionEvent.objects.filter(company=self.company).delete()

        call_command("snapshot_subscriptions", "--month", f"{old_month:%Y-%m}")

        snap = SubscriptionMonthlySnapshot.objects.get(company=self.company, month=old_month)
        self.assertTrue(snap.is_reconstructed)

    def test_company_that_did_not_exist_yet_is_not_snapshotted(self):
        """Inventing a customer in a month they had not signed up corrupts that cohort."""
        Subscription.objects.create(company=self.company, plan=self.basic, status="active")
        last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)

        call_command("snapshot_subscriptions", "--month", f"{last_month:%Y-%m}")

        self.assertFalse(SubscriptionMonthlySnapshot.objects.filter(company=self.company, month=last_month).exists())
