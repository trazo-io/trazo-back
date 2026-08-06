from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from company.models import Company


class Plan(models.Model):
    """Subscription plan model"""

    INTERVAL_CHOICES = [
        ("monthly", "Monthly"),
        ("yearly", "Yearly"),
    ]

    name = models.CharField(max_length=50)  # Basic, Standard, Corporate, Enterprise
    slug = models.SlugField(unique=True)  # basic, standard, corporate, enterprise
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    interval = models.CharField(max_length=20, choices=INTERVAL_CHOICES, default="monthly")
    features = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    stripe_price_id = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Plan")
        verbose_name_plural = _("Plans")

    def __str__(self):
        return f"{self.name} ({self.get_interval_display()})"

    def get_absolute_url(self):
        return reverse("plan-detail", kwargs={"slug": self.slug})


class Subscription(models.Model):
    """User subscription model"""

    STATUS_CHOICES = [
        ("active", "Active"),
        ("canceled", "Canceled"),
        ("past_due", "Past Due"),
        ("trialing", "Trialing"),
        ("unpaid", "Unpaid"),
        ("incomplete", "Incomplete"),
    ]

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    pending_plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="pending_subscriptions",
        help_text="Plan scheduled for downgrade at end of billing period",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    stripe_subscription_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    stripe_customer_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField(default=False)

    # Usage tracking
    used_productions = models.IntegerField(default=0)
    used_storage_gb = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    scan_count = models.IntegerField(default=0)

    # Trial information
    trial_end = models.DateTimeField(blank=True, null=True)

    # Tracks which trial lifecycle emails have been sent to avoid duplicates.
    # Keys: "day_11", "day_14", "day_17". Values: ISO-8601 timestamp of send.
    email_notifications_sent = models.JSONField(
        default=dict,
        blank=True,
        help_text="Tracks sent trial lifecycle emails. Keys: day_11, day_14, day_17.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Subscription")
        verbose_name_plural = _("Subscriptions")

    def __str__(self):
        return f"{self.company.name} - {self.plan.name}"

    def is_active(self):
        return self.status in ["active", "trialing"]

    def is_trial(self):
        return self.status == "trialing"


class AddOn(models.Model):
    """Add-on product model"""

    name = models.CharField(max_length=50)  # Extra Production, Extra Parcel, etc.
    slug = models.SlugField(unique=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    stripe_price_id = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Add-on")
        verbose_name_plural = _("Add-ons")

    def __str__(self):
        return self.name


class SubscriptionAddOn(models.Model):
    """Tracks add-ons purchased by a subscription"""

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="addons")
    addon = models.ForeignKey(AddOn, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    stripe_item_id = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Subscription Add-on")
        verbose_name_plural = _("Subscription Add-ons")

    def __str__(self):
        return f"{self.subscription.company.name} - {self.addon.name} x{self.quantity}"


class Invoice(models.Model):
    """Invoice model for tracking payments"""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("paid", "Paid"),
        ("open", "Open"),
        ("uncollectible", "Uncollectible"),
        ("void", "Void"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="invoices")
    subscription = models.ForeignKey(Subscription, on_delete=models.SET_NULL, null=True)
    stripe_invoice_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Human-readable invoice number from Stripe (e.g. INV-0042)",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    invoice_date = models.DateTimeField()
    due_date = models.DateTimeField(blank=True, null=True)
    invoice_pdf = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Invoice")
        verbose_name_plural = _("Invoices")

    def __str__(self):
        return f"Invoice {self.stripe_invoice_id} for {self.company.name}"


class PaymentMethod(models.Model):
    """Payment method model"""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payment_methods")
    stripe_payment_method_id = models.CharField(max_length=100, unique=True, db_index=True)
    card_brand = models.CharField(max_length=20)  # visa, mastercard, etc.
    last_4 = models.CharField(max_length=4)  # Last 4 digits of card
    exp_month = models.IntegerField()
    exp_year = models.IntegerField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Payment Method")
        verbose_name_plural = _("Payment Methods")

    def __str__(self):
        return f"{self.card_brand} **** **** **** {self.last_4}"


class ProcessedWebhookEvent(models.Model):
    """Tracks processed Stripe webhook events for idempotency."""

    stripe_event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = _("Processed Webhook Event")
        verbose_name_plural = _("Processed Webhook Events")

    def __str__(self):
        return f"{self.event_type} ({self.stripe_event_id})"


# Statuses that represent contracted, billable revenue. Deliberately EXCLUDES:
#   trialing   — Trazo's trial is 14 days with no card; nothing is charged
#   canceled   — churned
#   unpaid     — collection failed and given up on
#   incomplete — checkout never finished, so no commitment exists
# `past_due` is included: the customer is still contracted and is normally counted in
# MRR until the subscription actually terminates.
#
# Single definition shared by the lifecycle signal and the monthly snapshot command so
# the two can never disagree about what revenue means.
MRR_STATUSES = ("active", "past_due")


def mrr_for(plan, status):
    """MRR attributable to `plan` while in `status` — zero when the status is not billable."""
    if plan is None or status not in MRR_STATUSES:
        return Decimal("0")
    return plan.price


class SubscriptionEvent(models.Model):
    """
    Append-only lifecycle log for subscriptions.

    `Subscription` is a OneToOne holding CURRENT state only: `plan` and `status` are
    overwritten in place on every upgrade, downgrade, cancel and reactivation, and
    `updated_at` is auto_now so it is clobbered by the next unrelated save. Cohort
    retention and MRR movement therefore cannot be reconstructed from it after the fact.

    This table is the durable record — one immutable row per state transition. Rows are
    INSERTed and never updated or deleted. Written automatically by a post_save signal
    on Subscription (see signals.py) so no write path can bypass it.

    `mrr_before` / `mrr_after` are snapshots of the plan price at transition time rather
    than a join to Plan.price. A later price change must not silently rewrite historical
    revenue. `from_plan_slug` / `to_plan_slug` serve the same purpose for plan identity.
    """

    EVENT_TYPE_CHOICES = [
        ("created", "Subscription created"),
        ("trial_started", "Trial started"),
        ("trial_converted", "Trial converted to paid"),
        ("upgraded", "Upgraded"),
        ("downgraded", "Downgraded"),
        ("plan_changed", "Plan changed (no MRR movement)"),
        ("canceled", "Canceled"),
        ("reactivated", "Reactivated"),
        ("past_due", "Payment past due"),
        ("unpaid", "Unpaid"),
        ("status_changed", "Status changed (other)"),
    ]

    SOURCE_CHOICES = [
        ("stripe_webhook", "Stripe webhook"),
        ("self_serve", "Self-serve UI"),
        ("admin", "Admin / staff action"),
        ("system", "System (signal-derived)"),
        ("backfill", "Backfill / import"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="subscription_events")

    event_type = models.CharField(max_length=30, choices=EVENT_TYPE_CHOICES, db_index=True)

    # SET_NULL (not PROTECT) so retiring a Plan never blocks the write path; the slug
    # snapshots below keep the record readable even if the Plan row is gone.
    from_plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    to_plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    from_plan_slug = models.CharField(max_length=50, blank=True, default="")
    to_plan_slug = models.CharField(max_length=50, blank=True, default="")

    from_status = models.CharField(max_length=20, blank=True, default="")
    to_status = models.CharField(max_length=20, blank=True, default="")

    mrr_before = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    mrr_after = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # When the transition actually happened (may come from a Stripe event timestamp),
    # kept distinct from created_at = when Trazo recorded it.
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="system")
    stripe_event_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("Subscription Event")
        verbose_name_plural = _("Subscription Events")
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["company", "occurred_at"]),
            models.Index(fields=["event_type", "occurred_at"]),
        ]
        constraints = [
            # One Stripe event may legitimately produce a plan change AND a status change,
            # so idempotency is per (event, type) rather than per event. Blank ids are
            # exempt — signal-derived rows have no Stripe event to dedupe against.
            models.UniqueConstraint(
                fields=["stripe_event_id", "event_type", "company"],
                condition=models.Q(stripe_event_id__gt=""),
                name="unique_stripe_event_per_type_company",
            ),
        ]

    def __str__(self):
        return f"{self.company_id}: {self.event_type} @ {self.occurred_at:%Y-%m-%d}"

    @property
    def mrr_delta(self):
        return self.mrr_after - self.mrr_before


class SubscriptionMonthlySnapshot(models.Model):
    """
    One row per company per month — the shape cohort analysis actually needs.

    SubscriptionEvent records transitions; this records STATE at a point in time. With
    both, "of the companies that signed up in month M, how many were still active in
    month M+n" is a GROUP BY instead of an event-replay exercise.

    Written by `python manage.py snapshot_subscriptions` (idempotent — safe to re-run
    for a past month, and to backfill from month zero).

    NOTE: engagement counts here are deliberately limited to establishments and active
    productions, both single queries. A true events-logged-per-farm metric is a union
    across the eight event tables and belongs in its own rollup, not bolted on here.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="subscription_snapshots")
    # Always the first day of the month, in UTC.
    month = models.DateField(db_index=True)

    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    plan_slug = models.CharField(max_length=50, blank=True, default="")
    status = models.CharField(max_length=20, blank=True, default="")

    mrr = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=False)
    is_trialing = models.BooleanField(default=False)

    # Cohort anchor: the month the company's subscription was created. Denormalised so a
    # cohort query needs no join back to Subscription (whose created_at survives, but
    # whose row may not).
    cohort_month = models.DateField(null=True, blank=True, db_index=True)

    establishments_count = models.IntegerField(default=0)
    active_productions = models.IntegerField(default=0)

    # True when plan/status could not be derived from the event log and were inferred
    # from the subscription's CURRENT state — i.e. the row is an approximation, not an
    # observation. Only happens for months predating the event log. Analytics must
    # exclude or caveat these rather than treat them as measured history.
    is_reconstructed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Subscription Monthly Snapshot")
        verbose_name_plural = _("Subscription Monthly Snapshots")
        ordering = ["-month", "company_id"]
        constraints = [
            models.UniqueConstraint(fields=["company", "month"], name="unique_company_month_snapshot"),
        ]
        indexes = [
            models.Index(fields=["month", "is_active"]),
            models.Index(fields=["cohort_month", "month"]),
        ]

    def __str__(self):
        return f"{self.company_id} @ {self.month:%Y-%m} ({self.plan_slug or 'none'})"
