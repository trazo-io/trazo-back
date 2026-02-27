"""
Consumer-specific serializers for API responses
"""

from django.contrib.auth import get_user_model
from django.db.models import Count

from rest_framework import serializers

from backend.constants import get_carbon_score_from_co2e
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
    carbon_score = serializers.SerializerMethodField()
    carbon_footprint = serializers.SerializerMethodField()
    production_id = serializers.IntegerField(source="production.id", read_only=True)

    class Meta:
        model = UserFavorite
        fields = [
            "id",
            "production_id",
            "product_name",
            "farm_name",
            "location",
            "carbon_score",
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

    def get_carbon_score(self, obj):
        """Calculate carbon score (A+ to F scale)"""
        # Get latest carbon entry for this production
        carbon_entry = CarbonEntry.objects.filter(production=obj.production).order_by("-created_at").first()

        if carbon_entry:
            # Use co2e_amount if available and non-zero, otherwise fall back to amount
            co2e = (
                carbon_entry.co2e_amount
                if carbon_entry.co2e_amount and carbon_entry.co2e_amount > 0
                else carbon_entry.amount
            )
            if co2e and co2e > 0:
                co2e = float(co2e)
                return get_carbon_score_from_co2e(co2e)
        return "Not Available"

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
                co2e = float(co2e)
                return f"{co2e:.2f} kg CO₂e/kg"
        return "Data unavailable"


class UserImpactSummarySerializer(serializers.ModelSerializer):
    """Serialize user impact summary for dashboard - transparency-first approach"""

    # Transparency-first fields
    transparency_score_avg = serializers.SerializerMethodField()
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
            "transparency_score_avg",
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
        Caches result to avoid re-querying for transparency_score_avg and farming_events_viewed.
        """
        if self._event_counts_cache is not None:
            return self._event_counts_cache

        user = obj.user
        scans = HistoryScan.objects.filter(user=user).select_related("history")

        # Get all history IDs in one query
        history_ids = [scan.history_id for scan in scans if scan.history_id]

        # Bulk fetch event counts - 8 queries instead of 8 * N queries
        self._event_counts_cache = get_bulk_event_counts(history_ids)
        return self._event_counts_cache

    def get_transparency_score_avg(self, obj):
        """
        Calculate average transparency score based on documented events.
        More events = higher transparency (fixes perverse incentive problem).

        OPTIMIZED: Uses bulk event counts instead of N+1 queries.
        """
        user = obj.user
        scans = HistoryScan.objects.filter(user=user).select_related("history")

        if not scans.exists():
            return None

        # Get bulk event counts (cached)
        event_counts = self._get_event_counts(obj)

        total_transparency = 0
        scans_with_data = 0

        for scan in scans:
            if scan.history_id:
                events_count = event_counts.get(scan.history_id, 0)
                if events_count > 0:
                    # Calculate transparency for this scan
                    # 10 events = 100% transparency (fully documented production cycle)
                    transparency = min(100, events_count * 10)
                    total_transparency += transparency
                    scans_with_data += 1

        if scans_with_data > 0:
            return round(total_transparency / scans_with_data)
        return None

    def get_verified_farms_scanned(self, obj):
        """Count farms with verification or certification"""
        from .models import HistoryScan

        user = obj.user if obj.user else None
        if not user:
            return 0
        return (
            HistoryScan.objects.filter(user=user, history__parcel__certified=True)
            .values("history__parcel__establishment")
            .distinct()
            .count()
        )

    def get_farming_events_viewed(self, obj):
        """
        Count total farming events user has explored.

        OPTIMIZED: Uses bulk event counts instead of N+1 queries.
        """
        # Get bulk event counts (cached from transparency_score_avg call)
        event_counts = self._get_event_counts(obj)

        # Sum all event counts
        return sum(event_counts.values())


class EnhancedHistoryScanSerializer(serializers.ModelSerializer):
    """Enhanced serializer for shopping history with rich data - transparency-first approach"""

    # Production ID for navigation links (History.id, not HistoryScan.id)
    production_id = serializers.IntegerField(source="history.id", read_only=True)
    product_name = serializers.CharField(source="history.product", read_only=True)
    farm_name = serializers.CharField(source="history.parcel.establishment.name", read_only=True)
    location = serializers.SerializerMethodField()
    # Transparency-first fields (primary)
    transparency_score = serializers.SerializerMethodField()
    events_viewed = serializers.SerializerMethodField()
    # Carbon fields (secondary - available but not primary)
    carbon_score = serializers.SerializerMethodField()
    carbon_footprint = serializers.SerializerMethodField()
    carbon_saved = serializers.SerializerMethodField()
    sustainability_practices = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()

    class Meta:
        model = HistoryScan
        fields = [
            "id",
            "production_id",  # History.id for navigation links
            "product_name",
            "farm_name",
            "location",
            # Transparency-first fields (primary)
            "transparency_score",
            "events_viewed",
            # Carbon fields (secondary)
            "carbon_score",
            "carbon_footprint",
            "carbon_saved",
            "sustainability_practices",
            "is_verified",
            "is_favorite",
            "date",
            "comment",
        ]

    def get_location(self, obj):
        if obj.history.parcel and obj.history.parcel.establishment:
            establishment = obj.history.parcel.establishment
            return (
                f"{establishment.city}, {establishment.state}"
                if establishment.city and establishment.state
                else "Location unavailable"
            )
        return "Location unavailable"

    def get_transparency_score(self, obj):
        """
        Calculate transparency score based on documented events.
        Transparency-first philosophy: More documented events = higher transparency score.
        This REWARDS farmers for logging more events, not fewer.
        """
        # Count documented events using the helper function
        events_count = count_events_for_history(obj.history)

        # Calculate transparency score (0-100)
        # Base: 10 events = 100% transparency (fully documented production cycle)
        if events_count >= 10:
            return 100
        elif events_count >= 7:
            return 85
        elif events_count >= 5:
            return 70
        elif events_count >= 3:
            return 50
        elif events_count >= 1:
            return 30
        else:
            # No events documented - check if there's other transparency indicators
            if obj.history.parcel and obj.history.parcel.certified:
                return 20  # Some transparency through certification
            return None  # No transparency data available - don't show fake score

    def get_events_viewed(self, obj):
        """
        Count farming events documented for this production.
        This is the PRIMARY transparency metric.
        """
        # Count documented events using the helper function
        return count_events_for_history(obj.history)

    def get_carbon_score(self, obj):
        """Calculate carbon score grade"""
        carbon_entry = CarbonEntry.objects.filter(production=obj.history).order_by("-created_at").first()

        if carbon_entry:
            # Use co2e_amount if available and non-zero, otherwise fall back to amount
            co2e = (
                carbon_entry.co2e_amount
                if carbon_entry.co2e_amount and carbon_entry.co2e_amount > 0
                else carbon_entry.amount
            )
            if co2e and co2e > 0:
                co2e = float(co2e)
                return get_carbon_score_from_co2e(co2e)
        return "Not Available"

    def get_carbon_footprint(self, obj):
        """Get formatted carbon footprint"""
        carbon_entry = CarbonEntry.objects.filter(production=obj.history).order_by("-created_at").first()

        if carbon_entry:
            # Use co2e_amount if available and non-zero, otherwise fall back to amount
            co2e = (
                carbon_entry.co2e_amount
                if carbon_entry.co2e_amount and carbon_entry.co2e_amount > 0
                else carbon_entry.amount
            )
            if co2e and co2e > 0:
                co2e = float(co2e)
                return f"{co2e:.2f} kg CO₂e/kg"
        return "Data unavailable"

    def get_carbon_saved(self, obj):
        """Show carbon footprint tracking instead of fake savings"""
        carbon_entry = CarbonEntry.objects.filter(production=obj.history).order_by("-created_at").first()

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

        # Check for organic certification from parcel data
        if obj.history.parcel and obj.history.parcel.certified:
            practices.append("Certified sustainable")

        # Check for carbon calculation using EPA/USDA emission factors
        carbon_entry = CarbonEntry.objects.filter(production=obj.history).order_by("-created_at").first()

        if carbon_entry and carbon_entry.usda_factors_based:
            practices.append("EPA/USDA emission factors")

        # Check if establishment has sustainability certifications
        if obj.history.parcel and obj.history.parcel.establishment:
            establishment = obj.history.parcel.establishment
            # Add more specific checks based on actual establishment data
            if hasattr(establishment, "certifications") and establishment.certifications:
                practices.append("Farm certified")

        # Only return actual verified practices, not mock data
        return practices[:3] if practices else []

    def get_is_verified(self, obj):
        """Check if production has verification"""
        return bool(obj.history.parcel and obj.history.parcel.certified)

    def get_is_favorite(self, obj):
        """Check if user has favorited this product"""
        user = self.context.get("request").user if self.context.get("request") else None
        if user and user.is_authenticated:
            return UserFavorite.objects.filter(user=user, production=obj.history).exists()
        return False


class ProductComparisonSerializer(serializers.Serializer):
    """Serializer for product comparison data"""

    products = serializers.ListField(child=serializers.IntegerField(), max_length=5, min_length=2)

    def validate_products(self, value):
        """Validate that all products exist"""
        existing_products = History.objects.filter(id__in=value).count()
        if existing_products != len(value):
            raise serializers.ValidationError("One or more products not found")
        return value


class ProductComparisonResultSerializer(serializers.Serializer):
    """Serializer for comparison results"""

    id = serializers.IntegerField()
    name = serializers.CharField()
    farm = serializers.CharField()
    location = serializers.CharField()
    carbon_score = serializers.CharField()
    carbon_footprint = serializers.CharField()
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
