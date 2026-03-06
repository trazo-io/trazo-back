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
                from django.core.exceptions import ImproperlyConfigured

                raise ImproperlyConfigured(
                    "STRIPE_SECRET_KEY is a test key but DEBUG=False. " "Use a live key in production."
                )
            if not key:
                logger.warning("STRIPE_SECRET_KEY is empty. Payment features will not work.")
