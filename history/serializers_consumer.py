"""
Consumer-specific serializers for API responses
"""

from django.contrib.auth import get_user_model
from django.db.models import Count

from rest_framework import serializers

from backend.constants import format_carbon_amount
from carbon.models import CarbonEntry

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
from .models_consumer import (
    UserFavorite,
    UserImpactSummary,
    UserLocalRecommendation,
    UserShoppingGoal,
    UserShoppingInsight,
)

User = get_user_model()


def count_events_for_history(history):
    """
    Count all agricultural events documented for a production/history.
    This is the PRIMARY transparency metric - more events = higher transparency.

    Uses all 8 concrete event models since CommonEvent is abstract.

    NOTE: For bulk operations, use get_bulk_event_counts() instead to avoid N+1 queries.
    """
    if not history:
        return 0

    total = 0
    total += WeatherEvent.objects.filter(history=history).count()
    total += ChemicalEvent.objects.filter(history=history).count()
    total += ProductionEvent.objects.filter(history=history).count()
    total += GeneralEvent.objects.filter(history=history).count()
    total += EquipmentEvent.objects.filter(history=history).count()
    total += SoilManagementEvent.objects.filter(history=history).count()
    total += PestManagementEvent.objects.filter(history=history).count()
    total += BusinessEvent.objects.filter(history=history).count()
    return total


def get_bulk_event_counts(history_ids):
    """
    OPTIMIZED: Get event counts for multiple histories in bulk using aggregated queries.
    Returns a dictionary mapping history_id -> total_event_count.

    This replaces N+1 queries with 8 aggregated queries (one per event type).
    For 18 scans: 288 queries → 8 queries (97% reduction)
    """
    if not history_ids:
        return {}

    # Initialize counts dictionary
    event_counts = {history_id: 0 for history_id in history_ids}

    # Query each event type once and aggregate counts
    event_models = [
        WeatherEvent,
        ChemicalEvent,
        ProductionEvent,
        GeneralEvent,
        EquipmentEvent,
        SoilManagementEvent,
        PestManagementEvent,
        BusinessEvent,
    ]

    for EventModel in event_models:
        # Single query per event type with aggregation
        counts = EventModel.objects.filter(history_id__in=history_ids).values("history_id").annotate(count=Count("id"))
        for item in counts:
            event_counts[item["history_id"]] += item["count"]

    return event_counts


class UserFavoriteSerializer(serializers.ModelSerializer):
    """Serialize user favorites with product details"""

    product_name = serializers.CharField(source="production.product", read_only=True)
    farm_name = serializers.CharField(source="production.parcel.establishment.name", read_only=True)
    location = serializers.SerializerMethodField()
    # `carbon_score` (an A+-to-F letter grade) was removed 2026-08-04 — see backend/constants.py.
    # `carbon_footprint` carries the measured figure and is what consumers see.
    carbon_footprint = serializers.SerializerMethodField()
    production_public_id = serializers.UUIDField(source="production.public_id", read_only=True)

    class Meta:
        model = UserFavorite
        fields = [
            "id",
            "production_public_id",
            "product_name",
            "farm_name",
            "location",
            "carbon_footprint",
            "created_at",
        ]

    def get_location(self, obj):
        if obj.production.parcel and obj.production.parcel.establishment:
            establishment = obj.production.parcel.establishment
            return (
                f"{establishment.city}, {establishment.state}"
                if establishment.city and establishment.state
                else "Location unavailable"
            )
        return "Location unavailable"

    def get_carbon_footprint(self, obj):
        """Get formatted carbon footprint"""
        carbon_entry = CarbonEntry.objects.filter(production=obj.production).order_by("-created_at").first()

        if carbon_entry:
            # Use co2e_amount if available and non-zero, otherwise fall back to amount
            co2e = (
                carbon_entry.co2e_amount
                if carbon_entry.co2e_amount and carbon_entry.co2e_amount > 0
                else carbon_entry.amount
            )
            if co2e and co2e > 0:
                # Shared formatter so the consumer wording cannot drift between surfaces.
                return format_carbon_amount(co2e)
        return "Data unavailable"


class UserImpactSummarySerializer(serializers.ModelSerializer):
    """Serialize user impact summary for dashboard - transparency-first approach"""

    # Transparency-first fields
    # ⛔ NO SCORE. `transparency_score` and `transparency_score_avg` were served here to
    # signed-in consumers until 2026-09-08 — a self-graded 0-100 number, computed by a
    # FOURTH independent formula (10 events = 100, 7 = 85, 5 = 70, 3 = 50), on a payload a
    # shopper receives. `authenticated-consumer-score-leak-2026-08-06` is the same incident:
    # LOGGING IN DOES NOT MAKE A CLAIM SAFE. The factual counts below (`events_viewed`,
    # `farming_events_viewed`, `verified_farms_scanned`) are the whole replacement.
    verified_farms_scanned = serializers.SerializerMethodField()
    farming_events_viewed = serializers.SerializerMethodField()

    # Cache for bulk event counts to avoid N+1 queries
    _event_counts_cache = None

    class Meta:
        model = UserImpactSummary
        fields = [
            "total_scans",
            "total_reviews",
            # Transparency-first metrics (primary)
            "verified_farms_scanned",
            "farming_events_viewed",
            # Legacy fields (secondary)
            "total_carbon_offset_kg",
            "miles_driving_offset",
            "trees_equivalent",
            "sustainable_farms_found",
            "local_farms_found",
            "better_choices_made",
            "achievements_earned",
            "current_level",
            "points_earned",
            "first_scan_date",
            "last_scan_date",
        ]

    def _get_event_counts(self, obj):
        """
        OPTIMIZED: Get all event counts in bulk using a single set of queries.
        Caches result to avoid re-querying for farming_events_viewed.
        """
        if self._event_counts_cache is not None:
            return self._event_counts_cache

        user = obj.user
        scans = HistoryScan.objects.counted().filter(user=user).select_related("history")

        # Get all history IDs in one query
        history_ids = [scan.history_id for scan in scans if scan.history_id]

        # Bulk fetch event counts - 8 queries instead of 8 * N queries
        self._event_counts_cache = get_bulk_event_counts(history_ids)
        return self._event_counts_cache

    def get_verified_farms_scanned(self, obj):
        """Count farms with verified certifications"""
        from .models import HistoryScan

        user = obj.user if obj.user else None
        if not user:
            return 0
        try:
            from certifications.models import Certification

            certified_est_ids = set(
                Certification.objects.filter(
                    verification_status__in=["verified", "self_reported"],
                ).values_list("establishment_id", flat=True)
            )
            return (
                HistoryScan.objects.counted()
                .filter(user=user)
                .filter(history__parcel__establishment__in=certified_est_ids)
                .values("history__parcel__establishment")
                .distinct()
                .count()
            )
        except Exception:
            return 0

    def get_farming_events_viewed(self, obj):
        """
        Count total farming events user has explored.

        OPTIMIZED: Uses bulk event counts instead of N+1 queries.
        """
        # Get bulk event counts (cached)
        event_counts = self._get_event_counts(obj)

        # Sum all event counts
        return sum(event_counts.values())


class EnhancedHistoryScanSerializer(serializers.ModelSerializer):
    """Enhanced serializer for shopping history with rich data - transparency-first approach"""

    # Production UUID for navigation links (History.public_id for consumer URLs)
    production_public_id = serializers.UUIDField(source="history.public_id", read_only=True)
    product_name = serializers.CharField(source="history.product", read_only=True)
    farm_name = serializers.CharField(source="history.parcel.establishment.name", read_only=True)
    location = serializers.SerializerMethodField()
    # Transparency-first fields (primary)
    # ⛔ NO SCORE. `transparency_score` and `transparency_score_avg` were served here to
    # signed-in consumers until 2026-09-08 — a self-graded 0-100 number, computed by a
    # FOURTH independent formula (10 events = 100, 7 = 85, 5 = 70, 3 = 50), on a payload a
    # shopper receives. `authenticated-consumer-score-leak-2026-08-06` is the same incident:
    # LOGGING IN DOES NOT MAKE A CLAIM SAFE. The factual counts below (`events_viewed`,
    # `farming_events_viewed`, `verified_farms_scanned`) are the whole replacement.
    events_viewed = serializers.SerializerMethodField()
    # Carbon fields (secondary - available but not primary)
    # `carbon_score` (A+-to-F letter grade) removed 2026-08-04 — see backend/constants.py.
    carbon_footprint = serializers.SerializerMethodField()
    carbon_saved = serializers.SerializerMethodField()
    sustainability_practices = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()

    class Meta:
        model = HistoryScan
        fields = [
            "id",
            "production_public_id",  # History.public_id for consumer URLs
            "product_name",
            "farm_name",
            "location",
            # Transparency-first fields (primary)
            "events_viewed",
            # Carbon fields (secondary)
            "carbon_footprint",
            "carbon_saved",
            "sustainability_practices",
            "is_verified",
            "is_favorite",
            "date",
            "comment",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._carbon_entry_cache = {}

    def _get_carbon_entry(self, history):
        """Cached CarbonEntry lookup to avoid redundant queries across methods."""
        history_id = history.id
        if history_id not in self._carbon_entry_cache:
            self._carbon_entry_cache[history_id] = (
                CarbonEntry.objects.filter(production=history).order_by("-created_at").first()
            )
        return self._carbon_entry_cache[history_id]

    def _count_events_prefetched(self, history):
        """Count events using prefetched managers when available, falling back to queries."""
        count = 0
        for attr in [
            "history_weatherevent_events",
            "history_chemicalevent_events",
            "history_productionevent_events",
            "history_generalevent_events",
            "history_equipmentevent_events",
            "history_soilmanagementevent_events",
            "history_pestmanagementevent_events",
            "history_businessevent_events",
        ]:
            manager = getattr(history, attr, None)
            if manager is not None:
                try:
                    count += len(manager.all())
                except Exception:
                    pass
        return count

    def get_location(self, obj):
        if obj.history.parcel and obj.history.parcel.establishment:
            establishment = obj.history.parcel.establishment
            return (
                f"{establishment.city}, {establishment.state}"
                if establishment.city and establishment.state
                else "Location unavailable"
            )
        return "Location unavailable"

    def get_events_viewed(self, obj):
        """
        Count farming events documented for this production.
        This is the PRIMARY transparency metric.
        """
        return self._count_events_prefetched(obj.history)

    def get_carbon_footprint(self, obj):
        """Get formatted carbon footprint"""
        carbon_entry = self._get_carbon_entry(obj.history)

        if carbon_entry:
            # Use co2e_amount if available and non-zero, otherwise fall back to amount
            co2e = (
                carbon_entry.co2e_amount
                if carbon_entry.co2e_amount and carbon_entry.co2e_amount > 0
                else carbon_entry.amount
            )
            if co2e and co2e > 0:
                # Shared formatter so the consumer wording cannot drift between surfaces.
                return format_carbon_amount(co2e)
        return "Data unavailable"

    def get_carbon_saved(self, obj):
        """Show carbon footprint tracking instead of fake savings"""
        carbon_entry = self._get_carbon_entry(obj.history)

        if carbon_entry:
            # Use co2e_amount if available and non-zero, otherwise fall back to amount
            co2e = (
                carbon_entry.co2e_amount
                if carbon_entry.co2e_amount and carbon_entry.co2e_amount > 0
                else carbon_entry.amount
            )
            if co2e and co2e > 0:
                co2e = float(co2e)
                # For MVP: Show the actual footprint being tracked rather than fake "savings"
                return f"{co2e:.1f} kg CO₂e tracked"
        return "Carbon data pending"

    def get_sustainability_practices(self, obj):
        """Get real sustainability practices from actual data"""
        practices = []

        # Check for verified certifications from establishment-level data
        if obj.history.parcel and obj.history.parcel.establishment:
            try:
                from certifications.models import Certification

                verified_certs = Certification.objects.filter(
                    establishment=obj.history.parcel.establishment,
                    verification_status="verified",
                )
                for cert in verified_certs[:2]:
                    practices.append(f"{cert.get_certification_type_display()} (verified)")

                if not verified_certs.exists():
                    self_reported = Certification.objects.filter(
                        establishment=obj.history.parcel.establishment,
                        verification_status="self_reported",
                    )
                    for cert in self_reported[:2]:
                        practices.append(cert.get_certification_type_display())
            except Exception:
                pass

        # Check for carbon calculation using EPA/USDA emission factors
        carbon_entry = self._get_carbon_entry(obj.history)

        if carbon_entry and carbon_entry.usda_factors_based:
            practices.append("EPA/USDA emission factors")

        # Only return actual verified practices, not mock data
        return practices[:3] if practices else []

    def get_is_verified(self, obj):
        """Check if production has verified certifications"""
        if not obj.history.parcel or not obj.history.parcel.establishment:
            return False
        try:
            from certifications.models import Certification

            return Certification.objects.filter(
                establishment=obj.history.parcel.establishment,
                verification_status="verified",
            ).exists()
        except Exception:
            return False

    def get_is_favorite(self, obj):
        """Check if user has favorited this product"""
        user = self.context.get("request").user if self.context.get("request") else None
        if user and user.is_authenticated:
            return UserFavorite.objects.filter(user=user, production=obj.history).exists()
        return False


class ProductComparisonSerializer(serializers.Serializer):
    """Serializer for product comparison data"""

    products = serializers.ListField(child=serializers.UUIDField(), max_length=5, min_length=2)

    def validate_products(self, value):
        """Validate that all products exist"""
        existing_products = History.objects.filter(public_id__in=value).count()
        if existing_products != len(value):
            raise serializers.ValidationError("One or more products not found")
        return value


class ProductComparisonResultSerializer(serializers.Serializer):
    """Serializer for comparison results"""

    public_id = serializers.UUIDField()
    name = serializers.CharField()
    farm = serializers.CharField()
    location = serializers.CharField()
    # `carbon_score` (A+-to-F) removed 2026-08-04 — see backend/constants.py. Comparison is on the
    # measured figure: `carbon_footprint` for display, `carbon_kg_co2e` for ranking.
    carbon_footprint = serializers.CharField()
    carbon_kg_co2e = serializers.FloatField(allow_null=True, required=False)
    farming_method = serializers.CharField()
    certifications = serializers.ListField()
    # Removed: price, distance, sustainability_rating (no real data available)


class UserShoppingGoalSerializer(serializers.ModelSerializer):
    """Serialize user shopping goals"""

    progress_percentage = serializers.ReadOnlyField()
    is_completed = serializers.ReadOnlyField()
    days_remaining = serializers.SerializerMethodField()

    class Meta:
        model = UserShoppingGoal
        fields = [
            "id",
            "goal_type",
            "title",
            "description",
            "target_value",
            "current_value",
            "unit",
            "start_date",
            "target_date",
            "status",
            "progress_percentage",
            "is_completed",
            "days_remaining",
        ]

    def get_days_remaining(self, obj):
        """Calculate days remaining to target date"""
        from django.utils import timezone

        today = timezone.now().date()
        if obj.target_date > today:
            return (obj.target_date - today).days
        return 0


class UserShoppingInsightSerializer(serializers.ModelSerializer):
    """Serialize user shopping insights"""

    class Meta:
        model = UserShoppingInsight
        fields = ["id", "insight_type", "title", "description", "data", "is_read", "created_at", "expires_at"]


class UserLocalRecommendationSerializer(serializers.ModelSerializer):
    """Serialize local recommendations"""

    establishment_name = serializers.CharField(source="establishment.name", read_only=True)
    establishment_address = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = UserLocalRecommendation
        fields = [
            "id",
            "establishment_name",
            "establishment_address",
            "distance_miles",
            "carbon_score",
            "recommendation_score",
            "product_count",
            "is_favorited",
        ]

    def get_establishment_address(self, obj):
        """Get establishment address"""
        if obj.establishment.parcel_set.exists():
            parcel = obj.establishment.parcel_set.first()
            return f"{parcel.city}, {parcel.state}" if parcel.city and parcel.state else "Address unavailable"
        return "Address unavailable"

    def get_product_count(self, obj):
        """Get number of recommended products"""
        return obj.recommended_products.count()
