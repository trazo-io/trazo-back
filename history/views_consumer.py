"""
Consumer-specific API ViewSets for dynamic dashboard data
"""

from datetime import datetime

from django.db.models import Max, Min

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import HistoryScan
from .serializers_consumer import ConsumerImpactSerializer, EnhancedHistoryScanSerializer


class ConsumerDashboardViewSet(viewsets.ViewSet):
    """
    Main consumer dashboard API providing aggregated data for all consumer features
    """

    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=["get"])
    def impact_dashboard(self, request):
        """The signed-in shopper's own counts and their three most recent scans.

        Counted live; nothing is stored. Until 2026-11-10 this read and refreshed a
        `UserImpactSummary` row (history 0256 retires the model), and the response also carried
        `recommendations` (always empty) and `achievements` (milestone badges, one titled
        "Sustainability Detective"), neither rendered.
        """
        user = request.user
        impact_metrics = ConsumerImpactSerializer(user).data

        # Deduplicated by production, then the three most recent.
        latest_per_production = (
            HistoryScan.objects.counted().filter(user=user).order_by("history_id", "-date").distinct("history_id")
        )
        recent_scan_ids = list(latest_per_production.values_list("id", flat=True))
        recent_scans = (
            HistoryScan.objects.filter(id__in=recent_scan_ids)
            .select_related("history", "history__parcel__establishment")
            .order_by("-date")[:3]
        )

        return Response(
            {
                "impact_metrics": impact_metrics,
                "recent_scans": EnhancedHistoryScanSerializer(
                    recent_scans, many=True, context={"request": request}
                ).data,
                "quick_stats": {
                    "documented_products": impact_metrics["documented_products"],
                    # The key the deployed app reads until it switches to `documented_products`.
                    # Same honest count; it leaves with history 0256.
                    "better_choices": impact_metrics["documented_products"],
                },
            }
        )

    @action(detail=False, methods=["get"])
    def shopping_history(self, request):
        """Get enhanced shopping history with filtering"""
        user = request.user

        # Get query parameters for filtering
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        # A `carbon_score` filter ("A+, A, B, ...") was read here and never applied to the
        # queryset — dead since it was written. Removed 2026-08-04 with the letter grade itself
        # (see backend/constants.py); there is no grade left to filter on.

        # Base queryset
        queryset = (
            HistoryScan.objects.counted()
            .filter(user=user)
            .select_related("history", "history__parcel__establishment")
            .order_by("-date")
        )

        # Apply date filters
        if date_from:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d").date()
                queryset = queryset.filter(date__gte=date_from)
            except ValueError:
                pass

        if date_to:
            try:
                date_to = datetime.strptime(date_to, "%Y-%m-%d").date()
                queryset = queryset.filter(date__lte=date_to)
            except ValueError:
                pass

        # Pagination
        page_size = int(request.query_params.get("page_size", 20))
        page = int(request.query_params.get("page", 1))
        start = (page - 1) * page_size
        end = start + page_size

        paginated_scans = queryset[start:end]
        total_count = queryset.count()

        # Summary statistics
        summary_stats = {
            "total_scans": queryset.count(),
            "date_range": {
                "earliest": queryset.aggregate(earliest=Min("date"))["earliest"],
                "latest": queryset.aggregate(latest=Max("date"))["latest"],
            },
            "farms_scanned": queryset.values("history__parcel__establishment").distinct().count(),
        }

        return Response(
            {
                "scans": EnhancedHistoryScanSerializer(paginated_scans, many=True, context={"request": request}).data,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": (total_count + page_size - 1) // page_size,
                },
                "summary": summary_stats,
            }
        )
