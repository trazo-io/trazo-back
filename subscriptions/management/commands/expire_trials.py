import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from subscriptions.models import Subscription

logger = logging.getLogger(__name__)

# Plans this command may cancel. Starter is NOT one of them.
#
# 2026-08-13: this used to filter `plan__slug="starter"` and flip expired Starter subscriptions to
# "canceled". Starter is free FOREVER (October plan: "Actually free. Starter free forever, pilot
# free, no card"), and the COG Pro migration page's whole anti-lock-in answer is "Starter is free
# permanently, not a trial". At the time, cancelling it nulled `Company.subscription_plan` and
# 403'd every creation in the app — i.e. it silently locked out the exact COG Pro refugees
# October targets. Since 2026-08-22 a lapsed subscription falls back to Starter instead, so
# that particular blast radius is gone; expiring the free-forever tier would still be wrong.
#
# Nothing self-serve carries a trial now: Starter is free forever, Compliance is paid, and Pilot
# is hand-provisioned with `trial_no_card_days: 0`. The command is kept (the beat schedule and
# `subscriptions.tasks.expire_trials` reference it, and Stripe-side trials on a future plan would
# need it) but it can only act on plans listed here — add a slug deliberately, never a catch-all.
EXPIRABLE_TRIAL_PLAN_SLUGS: list[str] = []


class Command(BaseCommand):
    help = "Expire trials that have passed their trial_end date. Run daily. Never touches Starter."

    def handle(self, *args, **options):
        if not EXPIRABLE_TRIAL_PLAN_SLUGS:
            self.stdout.write(
                self.style.SUCCESS("No plans are trial-expirable (Starter is free forever). Nothing to do.")
            )
            return

        now = timezone.now()
        expired_trials = Subscription.objects.filter(
            status="trialing",
            trial_end__lte=now,
            plan__slug__in=EXPIRABLE_TRIAL_PLAN_SLUGS,
        )
        count = expired_trials.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No expired trials found."))
            return

        expired_trials.update(status="canceled")

        logger.info("Expired %d trials at %s", count, now.isoformat())
        self.stdout.write(self.style.SUCCESS(f"Expired {count} trial(s)."))
