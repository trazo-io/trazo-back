"""A subscription row is read through the API and changed only through actions that validate.

Overall review 2026-11, OV-SEC-C07. `SubscriptionViewSet` was a ModelViewSet whose serializer left
`status` and the period fields writable, and `IsCompanyAdminForSubscription` let a Company Admin
of the company PUT, PATCH or DELETE it. Entitlement is computed from `status`, so a past-due paid
company could mark itself active, extend its own period, or delete the row. Every legitimate change
goes through `cancel`, `reactivate`, `change_plan`, `add_addon` or Stripe's webhook.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company
from subscriptions.models import Subscription
from subscriptions.tests.test_cancel_endpoint_and_notices import _plan, _starter
from users.models import User, WorksIn


class _Base(TestCase):
    def setUp(self):
        _starter()
        self.company = Company.objects.create(name="Blue Oak Orchards")
        self.admin = User.objects.create_user(email="admin@blueoak.example", password="pw-for-test-only")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.period_end = timezone.now() - timedelta(days=3)
        self.sub = Subscription.objects.create(
            company=self.company,
            plan=_plan("compliance-yearly", 249),
            status="past_due",
            current_period_start=timezone.now() - timedelta(days=368),
            current_period_end=self.period_end,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.url = f"/api/subscriptions/subscriptions/{self.sub.id}/"


class ACompanyAdminCannotRewriteTheirSubscriptionTests(_Base):
    def test_a_past_due_company_cannot_mark_itself_active(self):
        for method in ("patch", "put"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    {"status": "active", "current_period_end": (timezone.now() + timedelta(days=365)).isoformat()},
                    format="json",
                )
                self.assertEqual(response.status_code, 405, response.content)
                self.sub.refresh_from_db()
                self.assertEqual(self.sub.status, "past_due")
                self.assertEqual(self.sub.current_period_end, self.period_end)

    def test_the_row_cannot_be_deleted_or_created_through_the_api(self):
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertTrue(Subscription.objects.filter(pk=self.sub.pk).exists())
        response = self.client.post(
            "/api/subscriptions/subscriptions/", {"status": "active", "company": self.company.id}, format="json"
        )
        self.assertEqual(response.status_code, 405, response.content)

    def test_the_admin_still_reads_it_and_the_actions_still_answer(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["status"], "past_due")
        self.assertEqual(self.client.get("/api/subscriptions/subscriptions/").status_code, 200)
        # The validated write path is untouched: cancel answers for a paid plan.
        cancel = self.client.post(f"{self.url}cancel/", {}, format="json")
        self.assertNotEqual(cancel.status_code, 405)

    def test_the_serializer_writes_none_of_the_entitlement_fields(self):
        from subscriptions.serializers import SubscriptionSerializer

        serializer = SubscriptionSerializer(
            self.sub,
            data={"status": "active", "current_period_end": timezone.now().isoformat(), "trial_end": None},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data, {})


class AnOutsiderCannotReadAnotherCompanysSubscriptionTests(_Base):
    def test_a_member_of_another_company_gets_404(self):
        other = Company.objects.create(name="Other Farm")
        outsider = User.objects.create_user(email="admin@other.example", password="pw-for-test-only")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        client = APIClient()
        client.force_authenticate(user=outsider)
        self.assertEqual(client.get(self.url).status_code, 404)
        self.assertEqual(client.post(f"{self.url}cancel/", {}, format="json").status_code, 404)
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.cancel_at_period_end)


class AChangeOfPlanIsNotAFreeUpgradeTests(TestCase):
    """Independent review of PR 494. With no Stripe subscription (every Starter row, which
    `start_trial` creates locally), `change_plan` wrote the new plan straight onto the row: a Starter
    Company Admin could POST the Compliance plan's id and get paid features for nothing. A paid plan
    now starts at checkout; a move to a free plan still works without Stripe."""

    def setUp(self):
        self.starter = _starter()
        self.compliance = _plan("compliance-yearly", 249)
        self.company = Company.objects.create(name="Blue Oak Orchards")
        self.admin = User.objects.create_user(email="admin@blueoak.example", password="pw-for-test-only")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _subscribe(self, plan, **extra):
        return Subscription.objects.create(company=self.company, plan=plan, status="active", **extra)

    def _change(self, sub, plan):
        return self.client.post(
            f"/api/subscriptions/subscriptions/{sub.id}/change_plan/", {"plan_id": plan.id}, format="json"
        )

    def test_a_starter_company_cannot_change_itself_onto_a_paid_plan(self):
        sub = self._subscribe(self.starter)
        response = self._change(sub, self.compliance)
        self.assertEqual(response.status_code, 402, response.content)
        self.assertEqual(response.data["code"], "checkout_required")
        sub.refresh_from_db()
        self.assertEqual(sub.plan, self.starter)
        self.assertIsNone(sub.pending_plan)
        self.company.refresh_from_db()
        self.assertFalse(self.company.has_feature("compliance_exports"))

    def test_a_move_to_the_free_plan_still_works_without_stripe(self):
        sub = self._subscribe(self.compliance)
        response = self._change(sub, self.starter)
        self.assertEqual(response.status_code, 200, response.content)

    def test_a_stripe_backed_upgrade_still_goes_through_stripe(self):
        from unittest import mock

        operation = _plan("operation-yearly", 1200, max_establishments=-1)
        sub = self._subscribe(self.compliance, stripe_subscription_id="sub_test_123")
        with mock.patch("subscriptions.views.stripe") as fake_stripe:
            fake_stripe.Subscription.retrieve.return_value = {"items": {"data": [{"id": "si_1"}]}}
            response = self._change(sub, operation)
        self.assertEqual(response.status_code, 200, response.content)
        fake_stripe.Subscription.modify.assert_called_once()
        sub.refresh_from_db()
        self.assertEqual(sub.plan, operation)
