import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from subscriptions.models import Subscription

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Reset monthly scan counts for all active subscriptions. Run on the 1st of each month."

    def handle(self, *args, **options):
        now = timezone.now()
        active_subscriptions = Subscription.objects.filter(
            status__in=["active", "trialing"],
            scan_count__gt=0,
        )
        count = active_subscriptions.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No subscriptions with scan counts to reset."))
            return

        active_subscriptions.update(scan_count=0)

        logger.info("Reset scan_count for %d subscriptions at %s", count, now.isoformat())
        self.stdout.write(self.style.SUCCESS(f"Successfully reset scan_count for {count} subscriptions."))
