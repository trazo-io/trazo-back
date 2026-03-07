import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class SubscriptionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "subscriptions"
    verbose_name = "Subscription Management"

    def ready(self):
        from django.conf import settings

        if not settings.DEBUG:
            key = getattr(settings, "STRIPE_SECRET_KEY", "")
            if key.startswith("sk_test_"):
                logger.warning(
                    "STRIPE_SECRET_KEY is a test key but DEBUG=False. "
                    "Payment features will use Stripe test mode. "
                    "Set a live key before accepting real payments."
                )
            if not key:
                logger.warning("STRIPE_SECRET_KEY is empty. Payment features will not work.")
