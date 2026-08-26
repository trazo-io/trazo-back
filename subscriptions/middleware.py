import logging

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
