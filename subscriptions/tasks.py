import logging
from datetime import datetime

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from celery import shared_task

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_frontend_url():
    """Return frontend URL at runtime (not import time) so prod settings are respected."""
    return getattr(settings, "FRONTEND_URL", "https://app.trazo.io")


def _get_pricing_url():
    return _get_frontend_url() + "/admin/dashboard/pricing"


def _get_support_email():
    return getattr(settings, "SUPPORT_EMAIL", "hello@trazo.io")


def _resolve_recipient(subscription) -> str | None:
    """
    Return the best available email for a subscription's company.

    Priority:
      1. company.contact_email (set by the business owner)
      2. Email of the first Company Admin user linked to the company
    """
    company = subscription.company

    if company.contact_email:
        return company.contact_email

    # Fall back to the first Company Admin via the WorksIn through-table.
    from users.models import WorksIn

    admin_email = (
        WorksIn.objects.filter(company=company, role=WorksIn.COMPANY_ADMIN)
        .select_related("user")
        .values_list("user__email", flat=True)
        .first()
    )
    if admin_email:
        return admin_email

    logger.warning(
        "No recipient email found for subscription id=%s company=%s",
        subscription.pk,
        company.name,
    )
    return None


def _build_context(subscription) -> dict:
    """Return the template context shared by all trial emails."""
    trial_end = subscription.trial_end
    return {
        "company_name": subscription.company.name,
        "trial_end_date": trial_end.strftime("%B %d, %Y") if trial_end else "N/A",
        "pricing_url": _get_pricing_url(),
        "app_url": _get_frontend_url(),
        "support_email": _get_support_email(),
        "current_year": timezone.now().year,
        "BASE_URL": getattr(settings, "BASE_URL", "http://localhost:8000/"),
    }


def _send_trial_email(
    subscription,
    notification_key: str,
    subject: str,
    template_name: str,
) -> bool:
    """
    Render and send a single trial lifecycle email.

    Returns True if the email was dispatched, False if it was skipped
    (already sent or no recipient).  Updates email_notifications_sent on success.
    """
    sent_map: dict = subscription.email_notifications_sent or {}

    if notification_key in sent_map:
        logger.debug(
            "Trial email '%s' already sent for subscription id=%s, skipping.",
            notification_key,
            subscription.pk,
        )
        return False

    recipient = _resolve_recipient(subscription)
    if not recipient:
        return False

    context = _build_context(subscription)
    html_body = render_to_string(
        f"subscriptions/emails/{template_name}",
        context,
    )
    # Plain-text fallback with full context
    pricing_url = context["pricing_url"]
    support_email = context["support_email"]
    text_body = (
        f"Hi {context['company_name']},\n\n"
        f"{subject}\n\n"
        f"Your trial end date: {context['trial_end_date']}\n\n"
        f"Upgrade your plan at: {pricing_url}\n\n"
        f"Questions? Contact us at {support_email}."
    )

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@trazo.io")
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=[recipient],
    )
    msg.attach_alternative(html_body, "text/html")

    try:
        msg.send()
    except Exception:
        logger.exception(
            "Failed to send trial email '%s' to %s for subscription id=%s",
            notification_key,
            recipient,
            subscription.pk,
        )
        return False

    # Record the send timestamp so we never send this email twice.
    sent_map[notification_key] = timezone.now().isoformat()
    subscription.email_notifications_sent = sent_map
    subscription.save(update_fields=["email_notifications_sent", "updated_at"])

    logger.info(
        "Sent trial email '%s' to %s for subscription id=%s (company: %s)",
        notification_key,
        recipient,
        subscription.pk,
        subscription.company.name,
    )
    return True


# ---------------------------------------------------------------------------
# Scheduled tasks
# ---------------------------------------------------------------------------


@shared_task
def reset_monthly_scan_counts():
    """Reset scan_count for all active subscriptions.

    NOT SCHEDULED, deliberately, since 2026-09-30. `Subscription.scan_count` is not what the API
    serves: `SubscriptionSerializer._compute_scan_count` counts `HistoryScan` rows from
    `current_period_start`, so the stored column has no reader, and `monthly_scan_limit` is listed
    in `create_plans.RETIRED_FEATURE_KEYS`. Nothing enforces a cap on it and nothing displays it.
    Kept callable by hand; the real dead thing is the column, and dropping it is a migration.
    """
    logger.info("Running monthly scan count reset task")
    call_command("reset_monthly_scan_counts")


@shared_task
def cleanup_processed_webhook_events():
    """Purge ProcessedWebhookEvent records older than 90 days. Scheduled weekly."""
    from subscriptions.models import ProcessedWebhookEvent

    cutoff = timezone.now() - timezone.timedelta(days=90)
    count, _ = ProcessedWebhookEvent.objects.filter(processed_at__lt=cutoff).delete()
    logger.info("Cleaned up %d processed webhook events older than 90 days", count)


@shared_task
def expire_trials():
    """Expire trials past their trial_end date.

    NOT SCHEDULED, deliberately, since 2026-09-30, and a documented no-op besides:
    `EXPIRABLE_TRIAL_PLAN_SLUGS` in the command is an empty list with a dated 2026-08-13 rationale.
    Kept for a future Stripe-side trial. NEVER: do not add a catch-all slug.
    """
    logger.info("Running trial expiration task")
    call_command("expire_trials")


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
)
def send_trial_emails(self):
    """
    Send lifecycle emails to companies at three points in the trial journey.

    NOT SCHEDULED, deliberately, since 2026-09-30. Nothing dispatches this. It stays because it is
    LIVE for paid plans: Starter has no trial, but a paid plan can sit in Stripe status 'trialing'
    with a trial_end, and the Starter guard below is pinned by
    `test_starter_never_receives_trial_expiry_emails` with a paid control. If a Stripe-side trial is
    ever sold, give it a cadence in `backend/scheduled_work.py` rather than a schedule here.

    Email windows (relative to trial_end):
      - Day 11  (3 days before expiry)  status=trialing,  trial_end in 3 days
      - Day 14  (day of expiry)         status=canceled,  trial_end today
      - Day 17  (3 days after expiry)   status=canceled,  trial_end 3 days ago

    Deduplication is handled via Subscription.email_notifications_sent so
    re-running the task is safe.  The task retries up to 3 times with
    exponential backoff (capped at 600 s) on any unhandled exception.
    """
    from subscriptions.models import Subscription

    # ⛔ NEVER email a free-forever plan about an expiring trial.
    #
    # Starter has no trial since 2026-08-13 (October plan: "Starter free forever"), so new rows
    # carry `trial_end=None` and fall out of the date windows below on their own. Rows created
    # BEFORE that change still have a `trial_end`, and would otherwise be told their free plan is
    # ending — the precise message the COG Pro migration page promises we will never send.
    FREE_FOREVER_PLAN_SLUGS = ("starter",)

    def trial_email_candidates():
        return Subscription.objects.exclude(plan__slug__in=FREE_FOREVER_PLAN_SLUGS)

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    sent_day11 = sent_day14 = sent_day17 = 0

    # --- Day 11: trial expires in exactly 3 days (still trialing) -----------
    day11_start = today_start + timezone.timedelta(days=3)
    day11_end = today_end + timezone.timedelta(days=3)

    day11_subs = (
        trial_email_candidates()
        .filter(
            status="trialing",
            trial_end__gte=day11_start,
            trial_end__lte=day11_end,
        )
        .select_related("company")
    )

    for sub in day11_subs:
        dispatched = _send_trial_email(
            subscription=sub,
            notification_key="day_11",
            subject="Your Trazo trial expires in 3 days",
            template_name="trial_expiring_soon.html",
        )
        if dispatched:
            sent_day11 += 1

    # --- Day 14: trial expired today (canceled OR still trialing if expire_trials hasn't run) ---
    day14_subs = (
        trial_email_candidates()
        .filter(
            Q(status="canceled") | Q(status="trialing"),
            trial_end__gte=today_start,
            trial_end__lte=today_end,
        )
        .select_related("company")
    )

    for sub in day14_subs:
        dispatched = _send_trial_email(
            subscription=sub,
            notification_key="day_14",
            subject="Your Trazo trial has ended - upgrade to restore access",
            template_name="trial_expired.html",
        )
        if dispatched:
            sent_day14 += 1

    # --- Day 17: trial ended 3 days ago (canceled) --------------------------
    day17_start = today_start - timezone.timedelta(days=3)
    day17_end = today_end - timezone.timedelta(days=3)

    day17_subs = (
        trial_email_candidates()
        .filter(
            status="canceled",
            trial_end__gte=day17_start,
            trial_end__lte=day17_end,
        )
        .select_related("company")
    )

    for sub in day17_subs:
        dispatched = _send_trial_email(
            subscription=sub,
            notification_key="day_17",
            subject="Your Trazo data is still safe - come back anytime",
            template_name="trial_final_nudge.html",
        )
        if dispatched:
            sent_day17 += 1

    logger.info(
        "send_trial_emails complete: day_11=%d day_14=%d day_17=%d",
        sent_day11,
        sent_day14,
        sent_day17,
    )
    return {
        "day_11": sent_day11,
        "day_14": sent_day14,
        "day_17": sent_day17,
    }


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    name="subscriptions.tasks.send_renewal_reminders",
)
def send_renewal_reminders(self):
    """Remind annual subscribers before their plan auto-renews.

    California's Automatic Renewal Law (as amended by AB 2863, in force 2025-07-01) requires a
    clear and conspicuous reminder, in a form the consumer can retain, 15 to 45 days before an
    auto-renewal whose term is a year or longer. Compliance ($249/yr) and Operation ($1,200/yr)
    are both in scope. Trazo's ICP is California and Washington farms, so this is not a
    hypothetical jurisdiction.

    WHY A SCHEDULED TASK AND NOT `invoice.upcoming`
    -----------------------------------------------
    Stripe does emit `invoice.upcoming`, but the lead time is a Stripe dashboard setting whose
    default is 3 days — outside the statutory window. Wiring a legal deadline to a checkbox in
    someone else's admin UI means the obligation silently lapses the day that checkbox changes,
    and nothing in this repo would show it. The window is computed here, from data this repo
    owns, and is covered by a test.

    Sends at T-30 days: comfortably inside 15-45, and tolerant of roughly two weeks of missed
    runs before the deadline is at risk.

    `email_notifications_sent` is keyed by the exact renewal date, so a subscription is reminded
    once per renewal however often this runs SEQUENTIALLY. NEVER read that as concurrency-safe: the
    guard is a check-then-act, and two runs overlapping on the same row would both read the blob,
    both see no key, both send, and both write, so the subscriber is told twice and one run's keys
    are lost to the other's last-write-wins on the JSONField. Two things stop that now, and both
    are needed because they cover different callers:

      * `select_for_update()` inside `transaction.atomic()` below, which serialises any two callers
        on the same subscription row whatever invoked them.
      * A session advisory lock in `manage.py run_due_maintenance`, which stops a cron overrun
        producing a second run at all.
    """
    from datetime import timedelta

    from company.models import PAID_PLAN_STATUSES
    from subscriptions.models import Subscription
    from subscriptions.utils import resolve_billing_recipient, send_renewal_reminder_email

    now = timezone.now()
    window_opens = now + timedelta(days=14)
    window_closes = now + timedelta(days=30)

    due = (
        Subscription.objects.select_related("plan", "company")
        .filter(
            status__in=PAID_PLAN_STATUSES,
            plan__price__gt=0,
            plan__interval="yearly",
            cancel_at_period_end=False,
            current_period_end__gt=window_opens,
            current_period_end__lte=window_closes,
        )
        .exclude(plan__slug="pilot")
    )

    sent = 0
    for subscription in due:
        # Keyed by the renewal DATE, not by a counter: a customer who renews every year needs
        # one reminder per renewal, and the key has to differ between them.
        key = f"renewal_reminder_{subscription.current_period_end:%Y-%m-%d}"

        # NEVER: do not read the key off the row fetched by the queryset above. That read happened
        # before this loop began, so a concurrent run could have sent and written in between. Take
        # the row lock first, re-read inside it, and hold it across the send.
        with transaction.atomic():
            locked = Subscription.objects.select_for_update().get(pk=subscription.pk)
            sent_map = locked.email_notifications_sent or {}
            if key in sent_map:
                continue

            recipient, first_name = resolve_billing_recipient(locked.company)
            if not recipient:
                continue

            if not _send_one_renewal_reminder(locked, key, sent_map, recipient, first_name):
                continue
            sent += 1

    logger.info("Renewal reminders: %d sent, %d in window.", sent, due.count())
    return sent


def _send_one_renewal_reminder(subscription, key, sent_map, recipient, first_name):
    """Send one reminder and record it. MUST be called inside the caller's row lock.

    Returns whether a message actually went out. Split out so the lock block in
    `send_renewal_reminders` stays short enough to read, and so the record-the-key write cannot
    drift away from the send it records.
    """
    from subscriptions.utils import send_renewal_reminder_email

    try:
        send_renewal_reminder_email(
            email=recipient,
            username=first_name,
            company_name=subscription.company.name,
            plan_name=subscription.plan.name,
            amount=subscription.plan.price,
            renewal_date=subscription.current_period_end,
        )
    except Exception:
        # One bad address must not stop the run: the next subscription in the queryset may be the
        # one whose statutory deadline is closest. NOTE: returning False rather than raising also
        # keeps the caller's transaction committable, so a failed send does not roll back a key
        # written for a different subscription.
        logger.exception(
            "Failed to send renewal reminder to %s for subscription id=%s",
            recipient,
            subscription.pk,
        )
        return False

    sent_map[key] = timezone.now().isoformat()
    subscription.email_notifications_sent = sent_map
    subscription.save(update_fields=["email_notifications_sent", "updated_at"])
    return True
