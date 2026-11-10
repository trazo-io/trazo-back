"""
Consumer-specific serializers for API responses
"""

from django.contrib.auth import get_user_model
from django.db.models import Count

from rest_framework import serializers

from backend.constants import format_carbon_amount
from certifications.constants import CONSUMER_LISTED_STATUSES

from .models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    HistoryScan,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from .services.claim_authority import _CONSUMER_WITHHELD_PRODUCTION_SUBTYPES, may_publish_production_subtype

User = get_user_model()

# Production subtypes no shopper is ever served (buffer use, seed search, equipment cleanout,
# transport). A count shown to a shopper counts what the public payload serves, the same rule
# as `PublicHistorySerializer.get_events_count`; otherwise the number advertises records the
# page then does not show.
_WITHHELD_PRODUCTION_TYPES = tuple(_CONSUMER_WITHHELD_PRODUCTION_SUBTYPES)


def _served_production_events(queryset):
    return queryset.exclude(type__in=_WITHHELD_PRODUCTION_TYPES)


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
    total += _served_production_events(ProductionEvent.objects.filter(history=history)).count()
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
        queryset = EventModel.objects.filter(history_id__in=history_ids)
        if EventModel is ProductionEvent:
            queryset = _served_production_events(queryset)
        counts = queryset.values("history_id").annotate(count=Count("id"))
        for item in counts:
            event_counts[item["history_id"]] += item["count"]

    return event_counts


def season_recorded_emissions(history_id):
    """The season's recorded-basis emissions, or None (carbon.services.calculator_service)."""
    if history_id is None:
        return None
    from carbon.services.calculator_service import CarbonCalculatorService

    return CarbonCalculatorService().recorded_emissions_kg(history_id)


class ConsumerImpactSerializer(serializers.Serializer):
    """What a signed-in shopper did, counted live from their scans. Serializes a User.

    Replaces `UserImpactSummarySerializer`, which served a stored `UserImpactSummary` row
    refreshed at most hourly. Besides these counts that row carried `total_carbon_offset_kg`
    (the scanned seasons' EMISSIONS labelled as an offset), `miles_driving_offset`,
    `trees_equivalent`, `sustainable_farms_found`, `better_choices_made` and a points, level and
    achievements system. No screen rendered any of them; they left the payload on 2026-11-10
    and the model goes in history 0256.

    Every number here is a count of the shopper's own scans, never a verdict on a farm.
    """

    # ⛔ NO SCORE. `transparency_score` and `transparency_score_avg` were served to signed-in
    # consumers until 2026-09-08: a self-graded 0-100 number, computed by a FOURTH independent
    # formula (10 events = 100, 7 = 85, 5 = 70, 3 = 50), on a payload a shopper receives.
    # `authenticated-consumer-score-leak-2026-08-06` is the same incident: LOGGING IN DOES NOT
    # MAKE A CLAIM SAFE. These factual counts are the whole replacement.
    total_scans = serializers.SerializerMethodField()
    verified_farms_scanned = serializers.SerializerMethodField()
    farming_events_viewed = serializers.SerializerMethodField()
    documented_products = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._event_counts_cache = None

    def _scans(self, user):
        return HistoryScan.objects.counted().filter(user=user)

    def _get_event_counts(self, user):
        """Served event count per scanned production, computed once and shared.

        `farming_events_viewed` and `documented_products` both read it: 8 aggregated queries
        instead of 8 per scanned production.
        """
        if self._event_counts_cache is None:
            history_ids = set(self._scans(user).exclude(history_id=None).values_list("history_id", flat=True))
            self._event_counts_cache = get_bulk_event_counts(sorted(history_ids))
        return self._event_counts_cache

    def get_total_scans(self, user):
        return self._scans(user).count()

    def get_verified_farms_scanned(self, user):
        """Distinct scanned farms holding a certification in a consumer-listed status.

        The name is the wire contract; both tiles that render it say "Farms Discovered" and their
        tooltips state it is not a statement that anyone verified the farm.
        """
        from certifications.models import Certification

        certified_est_ids = Certification.objects.filter(
            verification_status__in=CONSUMER_LISTED_STATUSES,
        ).values_list("establishment_id", flat=True)
        return (
            self._scans(user)
            .filter(history__parcel__establishment__in=certified_est_ids)
            .values("history__parcel__establishment")
            .distinct()
            .count()
        )

    def get_farming_events_viewed(self, user):
        """Served events across the distinct productions the shopper scanned."""
        return sum(self._get_event_counts(user).values())

    def get_documented_products(self, user):
        """Distinct scanned productions with at least one served event.

        The "Documented Products" tile rendered `quick_stats.better_choices` until 2026-11-10, and
        that number was something else: scans of farms holding a listed certification or, when
        there were none, scans of seasons with USDA-factor carbon entries. The tile's tooltip
        promises products whose producer recorded their farming activities; this is that count.
        """
        return sum(1 for count in self._get_event_counts(user).values() if count)


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
            "date",
            "comment",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._carbon_entry_cache = {}

    def _season_emissions(self, history):
        """Cached season total (recorded basis), shared by the footprint and tracked fields."""
        if history.id not in self._carbon_entry_cache:
            self._carbon_entry_cache[history.id] = season_recorded_emissions(history.id)
        return self._carbon_entry_cache[history.id]

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
                    events = manager.all()
                    if attr == "history_productionevent_events":
                        # Same rule as the shopper payload: withheld subtypes are not served.
                        events = [
                            ev for ev in events if may_publish_production_subtype(getattr(ev, "type", None)).allowed
                        ]
                    count += len(events)
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
        """The season's recorded emissions (see ScanSerializer.get_carbon_footprint)."""
        co2e = self._season_emissions(obj.history)
        if co2e and co2e > 0:
            # Shared formatter so the consumer wording cannot drift between surfaces.
            return format_carbon_amount(co2e)
        return "Data unavailable"

    def get_carbon_saved(self, obj):
        """The season's tracked emissions, never "savings"."""
        co2e = self._season_emissions(obj.history)
        if co2e and co2e > 0:
            return f"{co2e:.1f} kg CO₂e tracked"
        return "Carbon data pending"

    def get_sustainability_practices(self, obj):
        """Get real sustainability practices from actual data"""
        practices = []

        # Check for certifications from establishment-level data.
        #
        # 🔴 2026-09-16 — this filtered `verification_status="verified"` and appended
        # "(verified)" straight off it. `verification_status` is NOT evidence of a registry
        # check: `Certification.consumer_display_status` exists precisely because "a row marked
        # verified by a manual admin edit, a data import, or a fixture asserted a database match
        # that never happened" (certifications/models.py). And nothing here asked whether the
        # operation was a specimen at all, so an invented farm published "USDA Organic
        # (verified)" on the signed-in shopper payload.
        #
        # `consumer_certification_status` is the one authority every consumer surface reads. It
        # answers verified_via_database / self_reported / inactive / pending and refuses the
        # first for a specimen. Only that answer may carry the word "verified".
        if obj.history.parcel and obj.history.parcel.establishment:
            try:
                from certifications.models import Certification
                from certifications.services.consumer_claim_validator import consumer_certification_status

                rows = Certification.objects.filter(
                    establishment=obj.history.parcel.establishment,
                ).select_related("establishment")
                database_verified = [c for c in rows if consumer_certification_status(c) == "verified_via_database"]
                for cert in database_verified[:2]:
                    practices.append(f"{cert.get_certification_type_display()} (verified)")

                if not database_verified:
                    self_reported = [c for c in rows if consumer_certification_status(c) == "self_reported"]
                    for cert in self_reported[:2]:
                        practices.append(cert.get_certification_type_display())
            except Exception:
                pass

        # An emission factor's provenance is not a farming practice, and "EPA/USDA emission
        # factors" is the blanket wording compliance.md forbids: not listed (2026-11-05).

        # Only return actual verified practices, not mock data
        return practices[:3] if practices else []

    def get_is_verified(self, obj):
        """True only when a certificate was actually matched against the USDA registry.

        Same correction as `get_sustainability_practices` above: `verification_status` is the
        raw column an admin edit, an import or a fixture can set, and it says nothing about
        whether a registry check happened or whether the operation is real.
        """
        if not obj.history.parcel or not obj.history.parcel.establishment:
            return False
        try:
            from certifications.models import Certification
            from certifications.services.consumer_claim_validator import consumer_certification_status

            rows = Certification.objects.filter(
                establishment=obj.history.parcel.establishment,
            ).select_related("establishment")
            return any(consumer_certification_status(c) == "verified_via_database" for c in rows)
        except Exception:
            return False

    # Removed: price, distance, sustainability_rating (no real data available)
