import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from subscriptions.models import Subscription

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Expire Starter trials that have passed their trial_end date. Run daily."

    def handle(self, *args, **options):
        now = timezone.now()

        expired_trials = Subscription.objects.filter(
            status="trialing",
            trial_end__lte=now,
            plan__slug="starter",
        )
        count = expired_trials.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No expired trials found."))
            return

        expired_trials.update(status="canceled")

        logger.info("Expired %d starter trials at %s", count, now.isoformat())
        self.stdout.write(self.style.SUCCESS(f"Expired {count} starter trial(s)."))
