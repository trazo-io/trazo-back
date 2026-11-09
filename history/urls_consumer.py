"""
Consumer-specific URL patterns for API endpoints
"""

from django.urls import include, path

from rest_framework.routers import DefaultRouter

from .views_consumer import ConsumerDashboardViewSet

# Create router for consumer APIs
consumer_router = DefaultRouter()
consumer_router.register(r"dashboard", ConsumerDashboardViewSet, basename="consumer-dashboard")
# favorites/ and goals/ were retired with their models in history 0254 (2026-11-09).

urlpatterns = [
    # Consumer API endpoints
    path("consumer/", include(consumer_router.urls)),
]
