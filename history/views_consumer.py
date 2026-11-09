"""
Consumer-specific API ViewSets for dynamic dashboard data
"""

import logging
import time
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Max, Min
from django.utils import timezone

from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

logger = logging.getLogger(__name__)

from backend.constants import EngagementMilestones
from certifications.constants import CONSUMER_LISTED_STATUSES

from .models import HistoryScan
from .models_consumer import UserImpactSummary
from .serializers_consumer import EnhancedHistoryScanSerializer, UserImpactSummarySerializer

User = get_user_model()


class ConsumerDashboardViewSet(viewsets.ViewSet):
    """
    Main consumer dashboard API providing aggregated data for all consumer features
    """

    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=["get"])
    def impact_dashboard(self, request):
        """Get comprehensive impact dashboard data"""
        total_start = time.time()
        user = request.user
        timings = {}

        # Get or create user impact summary
        t0 = time.time()
        impact_summary, created = UserImpactSummary.objects.get_or_create(
            user=user,
            defaults={
                "total_scans": 0,
                "total_reviews": 0,
                "total_carbon_offset_kg": 0.0,
                "sustainable_farms_found": 0,
                "local_farms_found": 0,
                "better_choices_made": 0,
            },
        )
        timings["get_or_create_summary"] = time.time() - t0

        # Update impact summary with latest data if needed
        t0 = time.time()
        if created or impact_summary.last_updated < timezone.now() - timedelta(hours=1):
            self._update_impact_summary(user, impact_summary)
            timings["update_impact_summary"] = time.time() - t0
        else:
            timings["update_impact_summary"] = "skipped (cached)"

        # Get recent scans for timeline (deduplicated by production)
        t0 = time.time()
        recent_scans = (
            HistoryScan.objects.counted()
            .filter(user=user)
            .select_related("history", "history__parcel__establishment")
            .order_by("history_id", "-date")
            .distinct("history_id")
        )
        # Re-sort by date descending and limit to 3
        recent_scan_ids = list(recent_scans.values_list("id", flat=True)[:3])
        recent_scans = (
            HistoryScan.objects.filter(id__in=recent_scan_ids)
            .select_related("history", "history__parcel__establishment")
            .order_by("-date")
        )
        timings["query_recent_scans"] = time.time() - t0

        # Serialize data
        t0 = time.time()
        impact_metrics_data = UserImpactSummarySerializer(impact_summary).data
        timings["serialize_impact_metrics"] = time.time() - t0

        t0 = time.time()
        recent_scans_data = EnhancedHistoryScanSerializer(recent_scans, many=True, context={"request": request}).data
        timings["serialize_recent_scans"] = time.time() - t0

        t0 = time.time()
        recommendations = self._get_retailer_recommendations()
        timings["get_recommendations"] = time.time() - t0

        t0 = time.time()
        achievements = self._get_recent_achievements(user)
        timings["get_achievements"] = time.time() - t0

        # Prepare response data
        dashboard_data = {
            "impact_metrics": impact_metrics_data,
            "recent_scans": recent_scans_data,
            "quick_stats": {
                "better_choices": impact_summary.better_choices_made,
                "local_farms": impact_summary.local_farms_found,
            },
            "recommendations": recommendations,
            "achievements": achievements,
        }

        total_time = time.time() - total_start
        print(f"[IMPACT_DASHBOARD] Total time: {total_time:.3f}s | " f"Timings: {timings}", flush=True)

        return Response(dashboard_data)

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

    def _update_impact_summary(self, user, impact_summary):
        """Update user impact summary with latest data"""
        update_timings = {}
        total_start = time.time()

        # Count scans
        t0 = time.time()
        total_scans = HistoryScan.objects.counted().filter(user=user).count()
        update_timings["count_scans"] = time.time() - t0

        # Count reviews
        t0 = time.time()
        from reviews.models import Review

        total_reviews = Review.objects.filter(user=user).count()
        update_timings["count_reviews"] = time.time() - t0

        # NOT an offset: this sum is the scanned seasons' EMISSIONS, and it was stored and served
        # as `total_carbon_offset_kg` (2026-11-05 audit). Offsets are a retired concept and no
        # screen renders the field, so it is no longer populated; the column goes with the
        # carbon slimming slice.
        carbon_offset = 0.0

        # Count unique establishments with verified certifications
        t0 = time.time()
        try:
            from certifications.models import Certification

            certified_est_ids = set(
                Certification.objects.filter(
                    verification_status__in=CONSUMER_LISTED_STATUSES,
                ).values_list("establishment_id", flat=True)
            )
            scanned_est_ids = set(
                HistoryScan.objects.counted().filter(user=user).values_list("history__parcel__establishment", flat=True)
            )
            sustainable_farms = len(certified_est_ids & scanned_est_ids)
        except Exception:
            sustainable_farms = 0
        update_timings["count_sustainable_farms"] = time.time() - t0

        # Count local farms based on real data (disable for now until location logic is implemented)
        # For MVP: only count farms with verified local indicators or disable this metric
        local_farms = 0  # Will implement proper location-based calculation later

        # Count better choices based on real data
        # For MVP: Count scans where user chose certified/sustainable options
        t0 = time.time()
        # Count scans where user chose farms with verified certifications
        scanned_with_cert = (
            HistoryScan.objects.counted()
            .filter(user=user)
            .filter(history__parcel__establishment__in=certified_est_ids)
            .count()
            if certified_est_ids
            else 0
        )
        better_choices = scanned_with_cert

        # If no certified data available, count scans with verified carbon entries
        if better_choices == 0:
            better_choices = (
                HistoryScan.objects.counted().filter(user=user, history__carbonentry__usda_factors_based=True).count()
            )
        update_timings["count_better_choices"] = time.time() - t0

        # Update impact summary
        impact_summary.total_scans = total_scans
        impact_summary.total_reviews = total_reviews
        impact_summary.total_carbon_offset_kg = carbon_offset
        impact_summary.sustainable_farms_found = sustainable_farms
        impact_summary.local_farms_found = local_farms
        impact_summary.better_choices_made = better_choices

        # Calculate US-friendly metrics
        t0 = time.time()
        impact_summary.calculate_us_friendly_metrics()
        update_timings["calculate_us_metrics"] = time.time() - t0

        # Update timestamps
        t0 = time.time()
        first_scan = HistoryScan.objects.counted().filter(user=user).order_by("date").first()
        last_scan = HistoryScan.objects.counted().filter(user=user).order_by("-date").first()

        if first_scan:
            impact_summary.first_scan_date = first_scan.date
        if last_scan:
            impact_summary.last_scan_date = last_scan.date
        update_timings["get_scan_timestamps"] = time.time() - t0

        t0 = time.time()
        impact_summary.save()
        update_timings["save_summary"] = time.time() - t0

        total_update_time = time.time() - total_start
        print(
            f"[IMPACT_DASHBOARD] _update_impact_summary total: {total_update_time:.3f}s | "
            f"Details: {update_timings}",
            flush=True,
        )

    def _get_retailer_recommendations(self):
        """Get retailer recommendations based on user's actual scan history"""
        # For MVP: Disable hardcoded recommendations
        # Future: Generate recommendations based on user's scanned establishments
        return []

    def _get_recent_achievements(self, user):
        """Get recent achievements for the user"""
        achievements = []

        # Check for scan milestones using configurable thresholds
        scan_count = HistoryScan.objects.counted().filter(user=user).count()
        milestones = EngagementMilestones.SCAN_MILESTONES

        if scan_count >= milestones["EXPLORER"] and scan_count < milestones["EXPLORER"] + 5:
            achievements.append(
                {
                    "title": "Scan Explorer",
                    "description": f'Scanned {milestones["EXPLORER"]} products!',
                    "icon": "scan",
                    "earned_date": timezone.now().date(),
                }
            )

        if scan_count >= milestones["COMMITTED"] and scan_count < milestones["COMMITTED"] + 5:
            achievements.append(
                {
                    "title": "Sustainability Detective",
                    "description": f'Scanned {milestones["COMMITTED"]} products!',
                    "icon": "detective",
                    "earned_date": timezone.now().date(),
                }
            )

        return achievements
