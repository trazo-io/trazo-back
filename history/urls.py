from django.urls import include, path

from rest_framework import routers

from .mock_transparency_views import mock_transparency_detail, mock_transparency_explanation, mock_transparency_summary
from .transparency_views import (
    production_instant_trust,
    production_transparency_detail,
    production_transparency_summary,
    transparency_explanation,
)
from .views import EventViewSet, HistoryScanViewSet, HistoryViewSet, PublicHistoryScanViewSet

router = routers.DefaultRouter()

router.register(r"histories", HistoryViewSet, basename="histories")
router.register(r"events", EventViewSet, basename="events")
router.register(r"scans", HistoryScanViewSet, basename="scans")
router.register(r"public_scans", PublicHistoryScanViewSet, basename="public-scans")

urlpatterns = [
    path("", include(router.urls)),
    # New Transparency API Endpoints (Trazo 2.0 - Solves farmer incentive problem)
    path("transparency/<int:production_id>/", production_transparency_detail, name="production-transparency-detail"),
    path(
        "transparency/<int:production_id>/summary/",
        production_transparency_summary,
        name="production-transparency-summary",
    ),
    path("transparency/quick/<int:production_id>/", production_instant_trust, name="production-instant-trust"),
    path("transparency/explanation/", transparency_explanation, name="transparency-explanation"),
    # Mock endpoints for testing (REMOVE IN PRODUCTION)
    path("mock/transparency/<int:production_id>/", mock_transparency_detail, name="mock-transparency-detail"),
    path("mock/transparency/<int:production_id>/summary/", mock_transparency_summary, name="mock-transparency-summary"),
    path("mock/transparency/explanation/", mock_transparency_explanation, name="mock-transparency-explanation"),
]
