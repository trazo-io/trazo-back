"""
Consumer-specific API ViewSets for dynamic dashboard data
"""

import logging
import time
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Max, Min, Prefetch
from django.utils import timezone

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

logger = logging.getLogger(__name__)

from backend.constants import EngagementMilestones, format_carbon_amount

from .models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    HistoryScan,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from .models_consumer import UserFavorite, UserImpactSummary, UserProductComparison, UserShoppingGoal
from .serializers_consumer import (
    EnhancedHistoryScanSerializer,
    ProductComparisonSerializer,
    UserFavoriteSerializer,
    UserImpactSummarySerializer,
    UserShoppingGoalSerializer,
)

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
        favorite_count = UserFavorite.objects.filter(user=user).count()
        timings["query_favorite_count"] = time.time() - t0

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
                "favorite_count": favorite_count,
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
        is_favorite = request.query_params.get("is_favorite", "").lower() == "true"

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

        # Apply favorite filter
        if is_favorite:
            favorite_production_ids = UserFavorite.objects.filter(user=user).values_list("production_id", flat=True)
            queryset = queryset.filter(history_id__in=favorite_production_ids)

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

    @action(detail=False, methods=["post"])
    def compare_products(self, request):
        """Compare multiple products side-by-side"""
        serializer = ProductComparisonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product_ids = serializer.validated_data["products"]

        # Get products with carbon data and optimized event queries.
        #
        # Filter on `public_id`, not `id` (fixed 2026-08-04). `ProductComparisonSerializer`
        # validates the incoming values as UUIDs against `public_id__in`, then this queryset
        # matched them against the integer primary key — so a request that passed validation
        # always selected ZERO rows and the endpoint returned an empty comparison to everyone.
        # Pre-existing; surfaced when the carbon letter grade was removed and the path was
        # finally exercised end to end.
        products = (
            History.objects.filter(public_id__in=product_ids)
            .select_related("parcel__establishment")
            .prefetch_related(
                "carbonentry_set",
                # Prefetch all 8 event types with albums and images
                Prefetch(
                    "history_weatherevent_events",
                    queryset=WeatherEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_chemicalevent_events",
                    queryset=ChemicalEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_productionevent_events",
                    queryset=ProductionEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_generalevent_events",
                    queryset=GeneralEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_equipmentevent_events",
                    queryset=EquipmentEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_soilmanagementevent_events",
                    queryset=SoilManagementEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_pestmanagementevent_events",
                    queryset=PestManagementEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_businessevent_events",
                    queryset=BusinessEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
            )
        )

        comparison_results = []

        for product in products:
            # Get latest carbon entry
            carbon_entry = product.carbonentry_set.order_by("-created_at").first()

            # Distance removed - no real location data available
            # Will implement when user location and establishment coordinates are available

            # Get establishment location
            location = "Location unavailable"
            if product.parcel and product.parcel.establishment:
                establishment = product.parcel.establishment
                if establishment.city and establishment.state:
                    location = f"{establishment.city}, {establishment.state}"

            # The measured amount, not a grade. `carbon_kg` is the number the comparison ranks
            # on; `carbon_footprint` is the same value formatted for display.
            carbon_kg = None
            carbon_footprint = "Data unavailable"

            if carbon_entry:
                # Use co2e_amount if available and non-zero, otherwise fall back to amount
                co2e = (
                    carbon_entry.co2e_amount
                    if carbon_entry.co2e_amount and carbon_entry.co2e_amount > 0
                    else carbon_entry.amount
                )
                if co2e and co2e > 0:
                    carbon_kg = float(co2e)
                    carbon_footprint = format_carbon_amount(carbon_kg)

            # Get certifications from establishment-level verified data
            certifications = []
            farming_method = "Conventional"
            if product.parcel and product.parcel.establishment:
                try:
                    from certifications.models import Certification

                    # 🔴 2026-09-24 — THE SIBLING. `serializers_consumer.py` was corrected on
                    # 2026-09-16 and this view, which does the same job for the compare screen,
                    # was not. Both defects were here:
                    #
                    #   * "(verified)" was appended from `cert.verification_status == "verified"`,
                    #     the RAW column an admin edit, a CSV import or a fixture can set. It is
                    #     not evidence a USDA Organic Integrity Database match ever happened —
                    #     `Certification.consumer_display_status` exists to say so.
                    #   * the comment below claimed "Only a DATABASE-VERIFIED organic certificate"
                    #     while the filter underneath it read that same raw column. A comment is
                    #     not a gate.
                    #
                    # Neither path asked whether the OPERATION was fabricated, so a specimen farm
                    # published "USDA Organic (verified)" and "Farming Method: Organic" to a
                    # signed-in shopper. `consumer_certification_status` is the one authority that
                    # answers both questions, and it is what every other consumer surface reads.
                    from certifications.services.consumer_claim_validator import consumer_certification_status

                    est_certs = list(
                        Certification.objects.filter(
                            establishment=product.parcel.establishment,
                            verification_status__in=["verified", "self_reported"],
                        ).select_related("establishment")
                    )
                    consumer_status = {c.pk: consumer_certification_status(c) for c in est_certs}
                    for cert in est_certs:
                        label = cert.get_certification_type_display()
                        if consumer_status[cert.pk] == "verified_via_database":
                            label += " (verified)"
                        certifications.append(label)
                    # The bare word "Organic" is a flat assertion with no qualifier attached, so
                    # it is reserved for a certificate Trazo actually matched against the
                    # registry — never a farmer-typed one, and never a fabricated operation.
                    if any(
                        c.certification_type == "usda_organic" and consumer_status[c.pk] == "verified_via_database"
                        for c in est_certs
                    ):
                        farming_method = "Organic"
                except Exception:
                    pass
            if carbon_entry and carbon_entry.usda_factors_based:
                certifications.append("EPA/USDA-Sourced Data")

            comparison_results.append(
                {
                    "public_id": str(product.public_id),
                    # `History.product` is a FK to Product, not a string — this put a model
                    # INSTANCE into the response dict and into the `comparison_data` JSONField,
                    # so the endpoint 500'd on json.dumps as soon as it actually found products.
                    "name": product.product.name if product.product else "Unknown Product",
                    "farm": (
                        product.parcel.establishment.name
                        if product.parcel and product.parcel.establishment
                        else "Unknown Farm"
                    ),
                    "location": location,
                    "carbon_footprint": carbon_footprint,
                    "carbon_kg_co2e": carbon_kg,
                    "farming_method": farming_method,
                    "certifications": certifications,
                }
            )

        # Save comparison for analytics.
        #
        # `product_ids` are UUID objects out of `validated_data`, and `comparison_data` is a
        # JSONField — `json.dumps` raises "Object of type UUID is not JSON serializable", so this
        # endpoint returned a 500 for every authenticated caller, which is every caller
        # (permission_classes = IsAuthenticated). Pre-existing; found 2026-08-04 when the carbon
        # letter grade was removed from this response and the path was exercised end to end.
        if request.user.is_authenticated:
            comparison = UserProductComparison.objects.create(
                user=request.user,
                comparison_data={
                    "product_ids": [str(pid) for pid in product_ids],
                    "results": comparison_results,
                    "timestamp": timezone.now().isoformat(),
                },
            )
            comparison.products.set(products)

        # Rank on the MEASURED intensity. This previously did `min()` over letter-grade strings,
        # which compares them alphabetically: "A" sorts before "A+", and the ordering only
        # resembled a ranking because the alphabet happens to run A, B, C, D, F. The grade is gone
        # (see backend/constants.py) and the comparison now uses the number it was derived from.
        valid_intensities = [
            result["carbon_kg_co2e"] for result in comparison_results if result["carbon_kg_co2e"] is not None
        ]

        return Response(
            {
                "comparison_id": comparison.id if request.user.is_authenticated else None,
                "products": comparison_results,
                "comparison_summary": {
                    "lowest_carbon_kg_co2e": (min(valid_intensities) if valid_intensities else None),
                    "lowest_carbon_footprint": (
                        format_carbon_amount(min(valid_intensities)) if valid_intensities else None
                    ),
                    "total_products": len(comparison_results),
                    "epa_usda_sourced_products": len(
                        [r for r in comparison_results if "EPA/USDA-Sourced Data" in r.get("certifications", [])]
                    ),
                },
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

        # Calculate real carbon offset based on actual carbon entries
        # OPTIMIZED: Use single query with aggregation instead of N+1 queries
        t0 = time.time()
        from django.db.models import Case, DecimalField, F, Sum, When

        from carbon.models import CarbonEntry

        # Get all production IDs from user's scans
        production_ids = HistoryScan.objects.counted().filter(user=user).values_list("history_id", flat=True)
        update_timings["get_production_ids"] = time.time() - t0

        # Single aggregated query for carbon totals
        t0 = time.time()
        carbon_total = (
            CarbonEntry.objects.filter(production_id__in=production_ids)
            .annotate(
                effective_co2e=Case(
                    When(co2e_amount__gt=0, then=F("co2e_amount")),
                    default=F("amount"),
                    output_field=DecimalField(),
                )
            )
            .aggregate(total=Sum("effective_co2e"))
        )
        update_timings["carbon_aggregation"] = time.time() - t0

        total_carbon_offset = float(carbon_total["total"] or 0)

        # Convert to awareness metric rather than false "savings"
        carbon_offset = total_carbon_offset

        # Count unique establishments with verified certifications
        t0 = time.time()
        try:
            from certifications.models import Certification

            certified_est_ids = set(
                Certification.objects.filter(
                    verification_status__in=["verified", "self_reported"],
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


class UserFavoriteViewSet(viewsets.ModelViewSet):
    """Manage user favorites"""

    serializer_class = UserFavoriteSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserFavorite.objects.filter(user=self.request.user).select_related(
            "production", "production__parcel__establishment"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["post"])
    def toggle_favorite(self, request):
        """Toggle favorite status for a product"""
        production_id = request.data.get("production_id")

        if not production_id:
            return Response({"error": "production_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            production = History.objects.get(id=production_id)
        except History.DoesNotExist:
            return Response({"error": "Product not found"}, status=status.HTTP_404_NOT_FOUND)

        favorite, created = UserFavorite.objects.get_or_create(user=request.user, production=production)

        if not created:
            favorite.delete()
            return Response({"is_favorite": False, "message": "Removed from favorites"})
        else:
            return Response({"is_favorite": True, "message": "Added to favorites"})


class UserShoppingGoalViewSet(viewsets.ModelViewSet):
    """Manage user shopping goals"""

    serializer_class = UserShoppingGoalSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserShoppingGoal.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
