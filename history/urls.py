from django.urls import include, path

from rest_framework import routers

from .claim_preview_views import input_status_preview
from .transparency_views import production_transparency_detail, verify_blockchain
from .views import (
    BuyerDocRequestViewSet,
    EventViewSet,
    HistoryScanViewSet,
    HistoryViewSet,
    PublicHistoryScanViewSet,
    SalesRecordViewSet,
    audit_export_by_uuid,
)

router = routers.DefaultRouter()

# History is Production since history 0264. The API served it as `histories/` until 2026-11-15, when
# `productions/` was added beside it; `histories/` was removed once the app had moved over.
router.register(r"productions", HistoryViewSet, basename="productions")
router.register(r"events", EventViewSet, basename="events")
router.register(r"scans", HistoryScanViewSet, basename="scans")
router.register(r"public_scans", PublicHistoryScanViewSet, basename="public-scans")
router.register(r"buyer_doc_requests", BuyerDocRequestViewSet, basename="buyer-doc-requests")
router.register(r"sales_records", SalesRecordViewSet, basename="sales-records")

urlpatterns = [
    # Audit export by UUID — MUST be before router include
    # (router's regex productions/(?P<pk>[^/.]+) would match UUIDs first)
    path(
        "productions/<uuid:public_id>/audit-export/",
        audit_export_by_uuid,
        name="production-audit-export-by-uuid",
    ),
    # Dry run of the buyer-page input claim for a draft the wizard has not saved yet.
    # BEFORE the router include: `events/<pk>/` would otherwise swallow any path under it, and
    # this deliberately sits outside the events route for that reason.
    path(
        "input-status-preview/",
        input_status_preview,
        name="input-status-preview",
    ),
    path("", include(router.urls)),
    # Transparency API Endpoints
    path(
        "transparency/<uuid:production_public_id>/",
        production_transparency_detail,
        name="production-transparency-detail",
    ),
    path(
        "transparency/<uuid:production_public_id>/verify-blockchain/",
        verify_blockchain,
        name="verify-blockchain",
    ),
]
