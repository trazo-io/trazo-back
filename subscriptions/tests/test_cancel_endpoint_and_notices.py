"""The cancel ENDPOINT, and the notices a cancellation is supposed to produce.

Three separate classes of defect are pinned here, all found on 2026-08-22:

  1. RENDER GATE != PAYLOAD GATE. `UnifiedSubscription` hid the Cancel button for Starter and
     pilot, and the endpoint accepted both. A stale tab or a direct POST stamped
     `cancel_at_period_end=True` on a row whose `current_period_end` is None, which renders as
     "Your subscription will cancel on -" on the free-forever tier.

  2. A GUARD THAT READS SOURCE PROVES NOTHING ABOUT WHAT RENDERS. `subscriptions/utils.py`
     rendered a `subscription_emails/` template namespace that has never existed in this repo.
     `render_to_string` raised `TemplateDoesNotExist` on the first line of every function and
     the one caller swallowed it, so the post-cancellation acknowledgement California's ARL
     requires was never sent to anybody. Grepping for the call would have found it and called it
     healthy. These tests RENDER.

  3. A STATUTORY DEADLINE WIRED TO SOMEONE ELSE'S SETTING. The renewal reminder is computed from
     data this repo owns rather than from Stripe's `invoice.upcoming` lead time, whose default
     is 3 days — outside the 15-45 day window California requires for an annual term.
"""

from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company
from subscriptions.models import Plan, Subscription
from users.models import User, WorksIn


def _plan(slug, price, interval="yearly", **features):
    base = {
        "max_establishments": 1,
        "max_parcels_per_establishment": -1,
        "max_productions_per_year": -1,
        "storage_limit_gb": 25,
        "compliance_exports": price > 0,
    }
    base.update(features)
    plan, _ = Plan.objects.update_or_create(
        slug=slug,
        defaults={
            "name": slug.replace("-", " ").title(),
            "description": slug,
            "price": price,
            "interval": interval,
            "is_active": True,
            "features": base,
        },
    )
    return plan


def _starter():
    return _plan("starter", 0, "monthly", storage_limit_gb=10, compliance_exports=False)


class _CancelEndpointBase(TestCase):
    def setUp(self):
        _starter()
        self.company = Company.objects.create(name="Blue Oak Orchards")
        self.user = User.objects.create_user(email="grower@example.com", password="pw-for-test-only", first_name="Sam")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _subscribe(self, plan, **extra):
        defaults = {
            "company": self.company,
            "plan": plan,
            "status": "active",
            "current_period_start": timezone.now() - timedelta(days=5),
            "current_period_end": timezone.now() + timedelta(days=25),
        }
        defaults.update(extra)
        sub, _ = Subscription.objects.update_or_create(company=self.company, defaults=defaults)
        return sub

    def _cancel(self, sub, **body):
        return self.client.post(f"/api/subscriptions/subscriptions/{sub.id}/cancel/", body, format="json")


class CancelPayloadGateTests(_CancelEndpointBase):
    """The endpoint enforces the rule the UI only *displays*."""

    def test_a_paid_subscription_can_be_cancelled(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        response = self._cancel(sub)

        self.assertEqual(response.status_code, 200, response.data)
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)

    def test_starter_is_refused_by_the_endpoint_not_only_hidden_by_the_ui(self):
        sub = self._subscribe(_starter(), current_period_end=None)
        response = self._cancel(sub)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data.get("code"), "not_cancellable")
        sub.refresh_from_db()
        self.assertFalse(
            sub.cancel_at_period_end,
            "the free-forever tier must never be stamped with a pending cancellation",
        )

    def test_a_pilot_is_refused(self):
        sub = self._subscribe(_plan("pilot", 0, "monthly", is_pilot=True, compliance_exports=True))
        response = self._cancel(sub)

        self.assertEqual(response.status_code, 400)
        sub.refresh_from_db()
        self.assertFalse(sub.cancel_at_period_end)

    def test_a_plan_flagged_is_pilot_under_another_slug_is_also_refused(self):
        """The frontend accepts either signal, so the server must too."""
        sub = self._subscribe(_plan("pilot-2027", 0, "monthly", is_pilot=True))
        self.assertEqual(self._cancel(sub).status_code, 400)

    def test_a_non_admin_member_cannot_cancel(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        member = User.objects.create_user(email="hand@example.com", password="pw-for-test-only")
        WorksIn.objects.create(user=member, company=self.company, role=WorksIn.VIEWER)
        client = APIClient()
        client.force_authenticate(user=member)

        response = client.post(f"/api/subscriptions/subscriptions/{sub.id}/cancel/", {}, format="json")
        self.assertIn(response.status_code, (403, 404))
        sub.refresh_from_db()
        self.assertFalse(sub.cancel_at_period_end)


class CancelReasonCaptureTests(_CancelEndpointBase):
    """Optional, validated, and never able to fail the cancellation."""

    def test_a_valid_reason_is_stored_with_the_feedback(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        response = self._cancel(sub, reason="seasonal", feedback="Back for next season's almonds")

        self.assertEqual(response.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.cancellation_reason, "seasonal")
        self.assertIn("almonds", sub.cancellation_feedback)
        self.assertIsNotNone(sub.cancellation_requested_at)

    def test_no_reason_still_cancels(self):
        """ARL: answering "why" can never be a precondition for leaving."""
        sub = self._subscribe(_plan("compliance-yearly", 249))
        response = self._cancel(sub)

        self.assertEqual(response.status_code, 200)
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)
        self.assertEqual(sub.cancellation_reason, "")

    def test_an_unrecognised_reason_is_dropped_not_rejected(self):
        """Telemetry must never be able to fail a billing action."""
        sub = self._subscribe(_plan("compliance-yearly", 249))
        response = self._cancel(sub, reason="because_mercury_is_retrograde")

        self.assertEqual(response.status_code, 200, "the cancellation still goes through")
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)
        self.assertEqual(sub.cancellation_reason, "", "an unknown bucket is worse than no bucket")

    def test_feedback_is_truncated_rather_than_rejected(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        response = self._cancel(sub, reason="other", feedback="x" * 5000)

        self.assertEqual(response.status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(len(sub.cancellation_feedback), 2000)

    def test_reactivating_clears_the_reason(self):
        """Otherwise the reason a customer once gave gets attached to the NEXT cancellation."""
        sub = self._subscribe(_plan("compliance-yearly", 249))
        self._cancel(sub, reason="too_expensive", feedback="Tight year")

        response = self.client.post(f"/api/subscriptions/subscriptions/{sub.id}/reactivate/", {}, format="json")
        self.assertEqual(response.status_code, 200)

        sub.refresh_from_db()
        self.assertFalse(sub.cancel_at_period_end)
        self.assertEqual(sub.cancellation_reason, "")
        self.assertEqual(sub.cancellation_feedback, "")
        self.assertIsNone(sub.cancellation_requested_at)

    def test_the_reason_cannot_be_rewritten_through_a_patch(self):
        """The write path is the cancel action, which validates. PATCH must not be a back door."""
        sub = self._subscribe(_plan("compliance-yearly", 249))
        self._cancel(sub, reason="seasonal")

        self.client.patch(
            f"/api/subscriptions/subscriptions/{sub.id}/",
            {"cancellation_reason": "too_expensive"},
            format="json",
        )
        sub.refresh_from_db()
        self.assertEqual(sub.cancellation_reason, "seasonal")


class CancellationNoticesRenderTests(_CancelEndpointBase):
    """These RENDER. A guard that only reads source called the broken version healthy."""

    def test_cancelling_actually_sends_the_arl_acknowledgement(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        mail.outbox = []

        response = self._cancel(sub, reason="seasonal")
        self.assertEqual(response.status_code, 200)

        self.assertEqual(len(mail.outbox), 1, "a cancellation with no acknowledgement is the original defect")
        message = mail.outbox[0]
        self.assertEqual(message.to, ["grower@example.com"], "addressed to whoever clicked")
        self.assertTrue(message.alternatives, "an HTML alternative must render, not just the text part")

    def test_the_acknowledgement_states_the_end_date_and_what_survives(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        mail.outbox = []
        self._cancel(sub)

        body = mail.outbox[0].body
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn(sub.current_period_end.strftime("%B %d, %Y"), body, "ARL: say when access ends")
        for fragment in ("Starter", "free forever"):
            self.assertIn(fragment, body)
        self.assertIn("Starter", html)

    def test_the_plain_text_part_is_not_html_escaped(self):
        """Rendering a `.txt` template turns an apostrophe into `&#x27;` in a message with no
        HTML to escape for. The text part is built in Python precisely to avoid that."""
        self.company.name = "O'Brien & Sons Orchard"
        self.company.save(update_fields=["name"])
        sub = self._subscribe(_plan("compliance-yearly", 249))
        mail.outbox = []
        self._cancel(sub)

        body = mail.outbox[0].body
        self.assertIn("O'Brien & Sons Orchard", body)
        self.assertNotIn("&#x27;", body)
        self.assertNotIn("&amp;", body)

    def test_the_end_of_the_subscription_sends_the_you_are_on_starter_notice(self):
        from subscriptions.views import land_on_free_tier

        sub = self._subscribe(_plan("compliance-yearly", 249))
        mail.outbox = []
        land_on_free_tier(sub)

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("Starter", body)
        self.assertIn("Nothing was deleted", body)

    def test_a_declined_card_notice_renders_and_says_nothing_is_switched_off(self):
        from subscriptions.views import _notify_payment_failed

        sub = self._subscribe(_plan("compliance-yearly", 249), status="past_due")
        mail.outbox = []
        _notify_payment_failed(sub, {"amount_due": 24900})

        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("NOTHING HAS BEEN SWITCHED OFF", body)
        self.assertIn("249", body)

    def test_every_subscription_email_template_on_disk_renders(self):
        """Walked off disk, never a hand-typed list.

        A hand-written tuple of template names is how three live emails kept selling a withdrawn
        add-on: the tuple never named the directory they were in.
        """
        from pathlib import Path

        from django.template.loader import render_to_string

        template_dir = Path(__file__).resolve().parents[1] / "templates" / "subscriptions" / "emails"
        templates = sorted(template_dir.glob("*.html"))
        self.assertGreaterEqual(len(templates), 4, "the walk found nothing — wrong directory?")

        context = {
            "username": "Sam",
            "company_name": "Blue Oak Orchards",
            "plan_name": "Compliance",
            "previous_plan_name": "Compliance",
            "end_date": "September 15, 2026",
            "renewal_date": "September 15, 2026",
            "amount": 249,
            "amount_due": 249,
            "trial_end_date": "September 15, 2026",
            "app_url": "https://app.trazo.io",
            "billing_url": "https://app.trazo.io/admin/dashboard/subscription",
            "pricing_url": "https://app.trazo.io/admin/dashboard/pricing",
            "support_email": "support@trazo.io",
            "current_year": 2026,
            "BASE_URL": "https://api.trazo.io/",
        }
        for template in templates:
            with self.subTest(template=template.name):
                html = render_to_string(f"subscriptions/emails/{template.name}", context)
                self.assertIn("Trazo", html)
                self.assertNotIn(
                    "#4CAF50",
                    html,
                    "green.500 is a decorative fill — never a background for white text",
                )


class RenewalReminderTests(TestCase):
    """California ARL: 15-45 days before an annual auto-renewal, in a retainable form."""

    def setUp(self):
        _starter()
        self.plan = _plan("compliance-yearly", 249)

    def _company(self, name, *, days_out, **extra):
        company = Company.objects.create(name=name)
        user = User.objects.create_user(
            email=f"{name.replace(' ', '').lower()}@example.com", password="pw-for-test-only"
        )
        WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
        defaults = {
            "company": company,
            "plan": self.plan,
            "status": "active",
            "current_period_start": timezone.now() - timedelta(days=340),
            "current_period_end": timezone.now() + timedelta(days=days_out),
        }
        defaults.update(extra)
        Subscription.objects.create(**defaults)
        return company

    def _run(self):
        from subscriptions.tasks import send_renewal_reminders

        mail.outbox = []
        return send_renewal_reminders()

    def test_a_renewal_inside_the_window_is_reminded(self):
        self._company("Inside Window", days_out=25)
        self.assertEqual(self._run(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("249", mail.outbox[0].body)

    def test_a_renewal_far_out_is_not_reminded_yet(self):
        self._company("Far Out", days_out=200)
        self.assertEqual(self._run(), 0)

    def test_a_renewal_next_week_is_outside_the_window(self):
        """T-7 is too late to be the statutory notice, so it is not sent as one."""
        self._company("Too Close", days_out=7)
        self.assertEqual(self._run(), 0)

    def test_the_same_renewal_is_never_reminded_twice(self):
        """The task runs daily; the customer gets one notice per renewal, not thirty."""
        self._company("Repeat Runner", days_out=25)
        self.assertEqual(self._run(), 1)
        self.assertEqual(self._run(), 0)

    def test_a_subscription_already_cancelling_is_not_reminded(self):
        """ "Your plan renews automatically" is false for a subscription that will not renew."""
        self._company("Leaving", days_out=25, cancel_at_period_end=True)
        self.assertEqual(self._run(), 0)

    def test_starter_is_never_reminded_because_it_never_renews(self):
        company = Company.objects.create(name="Free Forever Farm")
        Subscription.objects.create(
            company=company,
            plan=Plan.objects.get(slug="starter"),
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=25),
        )
        self.assertEqual(self._run(), 0)

    def test_a_pilot_is_never_reminded(self):
        company = Company.objects.create(name="Pilot Farm")
        Subscription.objects.create(
            company=company,
            plan=_plan("pilot", 0, "yearly", is_pilot=True),
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=25),
        )
        self.assertEqual(self._run(), 0)

    def test_a_monthly_plan_is_not_in_scope(self):
        """The ARL reminder obligation attaches to terms of a year or longer."""
        company = Company.objects.create(name="Monthly Farm")
        user = User.objects.create_user(email="monthly@example.com", password="pw-for-test-only")
        WorksIn.objects.create(user=user, company=company, role=WorksIn.COMPANY_ADMIN)
        Subscription.objects.create(
            company=company,
            plan=_plan("legacy-monthly", 69, "monthly"),
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=25),
        )
        self.assertEqual(self._run(), 0)


class DowngradePreviewTests(TestCase):
    """What a farm ALREADY OVER the free tier's ceilings is told before it cancels.

    A downgrade never deletes anything — `land_on_free_tier` moves the plan and touches no
    farms, parcels, productions or photos. What changes is the CEILING, and a farm above the
    new one finds additions refused the moment the subscription ends.

    Nothing warned them. Worse, the cancel screen's "what you keep" panel lists "10 GB of photo
    storage", which reads as a promise to somebody currently using 42 GB. Misstating what
    cancelling costs is the FTC §5 / ROSCA exposure in a negative-option flow, and it is simply
    inaccurate.
    """

    def setUp(self):
        self.starter = _starter()
        self.operation = _plan("operation-yearly", 1200, "yearly", max_establishments=-1)
        self.company = Company.objects.create(name="Big Orchard")
        self.subscription = Subscription.objects.create(
            company=self.company,
            plan=self.operation,
            status="active",
            current_period_start=timezone.now(),
            current_period_end=timezone.now() + timedelta(days=25),
        )

    def _preview(self):
        from subscriptions.serializers import SubscriptionSerializer

        return SubscriptionSerializer(Subscription.objects.get(pk=self.subscription.pk)).data["downgrade_preview"]

    def _farms(self, n):
        from company.models import Establishment

        for i in range(n):
            Establishment.objects.create(name=f"Farm {i}", company=self.company, country="US", state="CA")

    def test_a_farm_within_every_starter_limit_is_told_nothing(self):
        self._farms(1)
        self.assertIsNone(self._preview(), "a needless warning is its own defect")

    def test_more_farms_than_starter_allows_is_surfaced(self):
        self._farms(5)
        preview = self._preview()

        self.assertIsNotNone(preview)
        self.assertEqual(preview["target_plan_slug"], "starter")
        farms = [e for e in preview["exceeds"] if e["metric"] == "establishments"]
        self.assertEqual(len(farms), 1)
        self.assertEqual(farms[0]["used"], 5)
        self.assertEqual(farms[0]["limit"], 1)

    def test_photo_storage_over_the_starter_ceiling_is_surfaced(self):
        from unittest.mock import patch

        self._farms(1)
        # 42 GB of MEDIA, patched at the accounting boundary rather than by writing 42 GB of
        # fixtures. `storage_breakdown` is where the serializer reads from.
        with patch(
            "subscriptions.storage_accounting.storage_breakdown",
            return_value={
                "media_gb": Decimal("42.10"),
                "documents_gb": Decimal("0.00"),
                "total_gb": Decimal("42.10"),
                "media_bytes": 45_200_000_000,
                "documents_bytes": 0,
                "total_bytes": 45_200_000_000,
            },
        ):
            preview = self._preview()

        self.assertIsNotNone(preview)
        storage = [e for e in preview["exceeds"] if e["metric"] == "media_storage_gb"]
        self.assertEqual(len(storage), 1)
        self.assertAlmostEqual(storage[0]["used"], 42.10, places=2)
        self.assertEqual(storage[0]["limit"], 10)

    def test_documents_alone_never_trigger_the_warning(self):
        """Documents are counted but NEVER refused, so a big document shelf is not a consequence
        of cancelling. Scoring the total here would warn about something that cannot happen —
        the same mistake `storage_utils` avoids by measuring media alone."""
        from unittest.mock import patch

        self._farms(1)
        with patch(
            "subscriptions.storage_accounting.storage_breakdown",
            return_value={
                "media_gb": Decimal("1.00"),
                "documents_gb": Decimal("80.00"),
                "total_gb": Decimal("81.00"),
                "media_bytes": 1_073_741_824,
                "documents_bytes": 85_899_345_920,
                "total_bytes": 86_973_087_744,
            },
        ):
            self.assertIsNone(self._preview())

    def test_a_company_already_on_a_free_plan_gets_no_preview(self):
        self.subscription.plan = self.starter
        self.subscription.save()
        self._farms(5)
        self.assertIsNone(self._preview(), "there is no downgrade to preview from Starter")

    def test_an_unlimited_starter_metric_never_appears(self):
        """Starter is unlimited on parcels and productions (migration 0014), so neither is a
        consequence of downgrading and neither may be listed."""
        self._farms(3)
        preview = self._preview()
        metrics = {e["metric"] for e in (preview or {}).get("exceeds", [])}
        self.assertNotIn("productions", metrics)
        self.assertNotIn("parcels_per_farm", metrics)


class BillingIsScopedToTheCompanyBeingBilledTests(_CancelEndpointBase):
    """Company Admin **of this company**, not of some other one.

    `IsCompanyAdminForSubscription` only asked "is this user a Company Admin ANYWHERE", and
    `SubscriptionViewSet.get_queryset()` returns every subscription of every company the user
    belongs to in ANY role. Together those let an admin of farm A cancel farm B's subscription
    by id, with no membership escalation. Same family as the 2026-08-19 creation-quota bypass:
    a billing question must be asked of the subscription being acted on.
    """

    def test_an_admin_of_another_company_cannot_cancel_this_one(self):
        from users.models import User, WorksIn

        other = Company.objects.create(name="Neighbour Farm")
        # Admin here — which is what made the old check pass.
        intruder = User.objects.create_user(email="neighbour@example.com", password="pw-for-test-only")
        WorksIn.objects.create(user=intruder, company=other, role=WorksIn.COMPANY_ADMIN)
        # ...and only a Viewer on the company that actually owns the subscription.
        WorksIn.objects.create(user=intruder, company=self.company, role=WorksIn.VIEWER)

        sub = self._subscribe(_plan("compliance-yearly", 249))
        client = APIClient()
        client.force_authenticate(user=intruder)

        response = client.post(f"/api/subscriptions/subscriptions/{sub.id}/cancel/", {}, format="json")

        self.assertEqual(response.status_code, 403, response.data)
        sub.refresh_from_db()
        self.assertFalse(sub.cancel_at_period_end, "another company's admin ended this subscription")

    def test_the_real_admin_is_unaffected(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        self.assertEqual(self._cancel(sub).status_code, 200)


class RepeatCancellationTests(_CancelEndpointBase):
    """A second cancel request must not erase the first one's answer."""

    def test_a_bare_second_cancel_keeps_the_reason_already_given(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        self._cancel(sub, reason="seasonal", feedback="Back in October")

        self._cancel(sub)  # no reason this time — a stale tab or a direct POST

        sub.refresh_from_db()
        self.assertEqual(sub.cancellation_reason, "seasonal")
        self.assertEqual(sub.cancellation_feedback, "Back in October")

    def test_the_first_request_time_is_the_one_kept(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        self._cancel(sub, reason="seasonal")
        sub.refresh_from_db()
        first = sub.cancellation_requested_at

        self._cancel(sub)
        sub.refresh_from_db()
        self.assertEqual(sub.cancellation_requested_at, first, "the ARL clock must not restart")

    def test_a_second_cancel_may_still_CHANGE_the_reason(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        self._cancel(sub, reason="seasonal")
        self._cancel(sub, reason="too_expensive")

        sub.refresh_from_db()
        self.assertEqual(sub.cancellation_reason, "too_expensive")

    def test_a_malformed_body_does_not_500_a_billing_endpoint(self):
        sub = self._subscribe(_plan("compliance-yearly", 249))
        response = self.client.post(
            f"/api/subscriptions/subscriptions/{sub.id}/cancel/", ["not", "a", "mapping"], format="json"
        )
        self.assertEqual(response.status_code, 200, "a list body must not crash the cancel path")
        sub.refresh_from_db()
        self.assertTrue(sub.cancel_at_period_end)
