import logging
from datetime import datetime

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
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
    """Reset scan_count for all active subscriptions. Scheduled for 1st of each month."""
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
    """Expire Starter trials past their trial_end date. Scheduled daily."""
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

    Schedule: daily at 8 AM.

    Email windows (relative to trial_end):
      - Day 11  (3 days before expiry)  status=trialing,  trial_end in 3 days
      - Day 14  (day of expiry)         status=canceled,  trial_end today
      - Day 17  (3 days after expiry)   status=canceled,  trial_end 3 days ago

    Deduplication is handled via Subscription.email_notifications_sent so
    re-running the task is safe.  The task retries up to 3 times with
    exponential backoff (capped at 600 s) on any unhandled exception.
    """
    from subscriptions.models import Subscription

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    sent_day11 = sent_day14 = sent_day17 = 0

    # --- Day 11: trial expires in exactly 3 days (still trialing) -----------
    day11_start = today_start + timezone.timedelta(days=3)
    day11_end = today_end + timezone.timedelta(days=3)

    day11_subs = Subscription.objects.filter(
        status="trialing",
        trial_end__gte=day11_start,
        trial_end__lte=day11_end,
    ).select_related("company")

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
    day14_subs = Subscription.objects.filter(
        Q(status="canceled") | Q(status="trialing"),
        trial_end__gte=today_start,
        trial_end__lte=today_end,
    ).select_related("company")

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

    day17_subs = Subscription.objects.filter(
        status="canceled",
        trial_end__gte=day17_start,
        trial_end__lte=day17_end,
    ).select_related("company")

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
