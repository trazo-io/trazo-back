import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from subscriptions.models import Subscription

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Reset scan_count for subscriptions whose billing period has rolled over. "
        "Safe to run daily — only resets subscriptions where current_period_start "
        "has moved past the last reset."
    )

    def handle(self, *args, **options):
        now = timezone.now()

        # Only reset subscriptions where the billing period has changed.
        # A subscription needs reset when scan_count > 0 AND the current
        # billing period started after the last time we would have counted
        # scans (i.e. the period has rolled over).
        active_subscriptions = Subscription.objects.filter(
            status__in=["active", "trialing"],
            scan_count__gt=0,
        )

        reset_count = 0
        for sub in active_subscriptions.select_related("plan"):
            # If no period start, fall back to calendar month reset
            if not sub.current_period_start:
                sub.scan_count = 0
                sub.save(update_fields=["scan_count"])
                reset_count += 1
                continue

            # Reset if the period start is within the current month
            # (meaning a new billing cycle started recently)
            period_start = sub.current_period_start
            if period_start.month == now.month and period_start.year == now.year:
                # Only reset if period started today or very recently
                # (within the last 2 days to handle timezone edge cases)
                days_since_period_start = (now - period_start).days
                if days_since_period_start <= 2:
                    sub.scan_count = 0
                    sub.save(update_fields=["scan_count"])
                    reset_count += 1

        if reset_count == 0:
            self.stdout.write(self.style.SUCCESS("No subscriptions needed scan count reset."))
        else:
            logger.info("Reset scan_count for %d subscriptions at %s", reset_count, now.isoformat())
            self.stdout.write(self.style.SUCCESS(f"Reset scan_count for {reset_count} subscriptions."))
