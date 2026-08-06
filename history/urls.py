from django.urls import include, path

from rest_framework import routers

from .transparency_views import production_transparency_detail, transparency_explanation, verify_blockchain
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

router.register(r"histories", HistoryViewSet, basename="histories")
router.register(r"events", EventViewSet, basename="events")
router.register(r"scans", HistoryScanViewSet, basename="scans")
router.register(r"public_scans", PublicHistoryScanViewSet, basename="public-scans")
router.register(r"buyer_doc_requests", BuyerDocRequestViewSet, basename="buyer-doc-requests")
router.register(r"sales_records", SalesRecordViewSet, basename="sales-records")

urlpatterns = [
    # Audit export by UUID — MUST be before router include
    # (router's regex histories/(?P<pk>[^/.]+) would match UUIDs first)
    path(
        "histories/<uuid:public_id>/audit-export/",
        audit_export_by_uuid,
        name="audit-export-by-uuid",
    ),
    path("", include(router.urls)),
    # Transparency API Endpoints
    path(
        "transparency/<uuid:production_public_id>/",
        production_transparency_detail,
        name="production-transparency-detail",
    ),
    path("transparency/explanation/", transparency_explanation, name="transparency-explanation"),
    path(
        "transparency/<uuid:production_public_id>/verify-blockchain/",
        verify_blockchain,
        name="verify-blockchain",
    ),
]
