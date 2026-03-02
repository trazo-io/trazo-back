from django.urls import include, path

from rest_framework import routers

from .transparency_views import (
    production_instant_trust,
    production_transparency_detail,
    production_transparency_summary,
    transparency_explanation,
    verify_blockchain,
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
    # UUID-based public endpoints (primary)
    path(
        "transparency/<uuid:production_public_id>/",
        production_transparency_detail,
        name="production-transparency-detail",
    ),
    path(
        "transparency/<uuid:production_public_id>/summary/",
        production_transparency_summary,
        name="production-transparency-summary",
    ),
    path("transparency/quick/<uuid:production_public_id>/", production_instant_trust, name="production-instant-trust"),
    path("transparency/explanation/", transparency_explanation, name="transparency-explanation"),
    # Public blockchain verification endpoint (UUID only)
    path(
        "transparency/<uuid:production_public_id>/verify-blockchain/",
        verify_blockchain,
        name="verify-blockchain",
    ),
]
