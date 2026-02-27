import logging

from django.db.models import F
from django.utils.functional import SimpleLazyObject

logger = logging.getLogger(__name__)


class SubscriptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Add subscription features to the request
        if hasattr(request, "user") and request.user.is_authenticated:

            def get_subscription_features():
                active_company = getattr(request.user, "active_company", None)
                if active_company:
                    if hasattr(active_company, "subscription_plan") and active_company.subscription_plan:
                        return active_company.subscription_plan.features
                return {}

            request.subscription_features = SimpleLazyObject(get_subscription_features)
        else:
            request.subscription_features = {}

        response = self.get_response(request)
        return response


class UsageTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Track scan usage for QR code scans
        if request.path.startswith("/api/scan/") and hasattr(request, "user") and request.user.is_authenticated:
            try:
                company = request.user.active_company
                if company and hasattr(company, "subscription"):
                    subscription = company.subscription
                    plan_features = {}
                    if hasattr(subscription, "plan") and subscription.plan:
                        plan_features = subscription.plan.features or {}

                    monthly_limit = plan_features.get("monthly_scan_limit", -1)

                    # Only increment if under the limit (-1 = unlimited)
                    if monthly_limit == -1 or subscription.scan_count < monthly_limit:
                        from subscriptions.models import Subscription

                        Subscription.objects.filter(
                            id=subscription.id,
                        ).update(scan_count=F("scan_count") + 1)
                    else:
                        logger.info(
                            "Scan limit reached for company %s (limit=%d, count=%d). "
                            "Analytics paused, QR page still accessible.",
                            company.name,
                            monthly_limit,
                            subscription.scan_count,
                        )
            except Exception as e:
                logger.error("Error tracking scan usage: %s", str(e))

        return response
