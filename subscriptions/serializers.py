from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from .models import AddOn, Invoice, PaymentMethod, Plan, Subscription, SubscriptionAddOn


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["id", "name", "slug", "description", "price", "interval", "features", "is_active"]


class AddOnSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddOn
        fields = ["id", "name", "slug", "description", "price", "is_active"]


class SubscriptionAddOnSerializer(serializers.ModelSerializer):
    addon = AddOnSerializer(read_only=True)

    class Meta:
        model = SubscriptionAddOn
        fields = ["id", "addon", "quantity"]


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    addons = SubscriptionAddOnSerializer(many=True, read_only=True)

    # Dynamic calculations instead of cached fields
    used_productions = serializers.SerializerMethodField()
    used_storage_gb = serializers.SerializerMethodField()
    scan_count = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "plan",
            "status",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "used_productions",
            "used_storage_gb",
            "scan_count",
            "trial_end",
            "addons",
        ]

    def get_used_productions(self, obj):
        """
        Dynamic calculation: Count History (productions) created this year
        for all parcels belonging to this company.
        """
        try:
            from history.models import History

            company = obj.company
            if not company:
                return 0

            # Get start of current year
            start_of_year = timezone.now().replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )

            # Count productions (History objects) for this company in current year
            # History -> Parcel -> Establishment -> Company
            count = History.objects.filter(
                parcel__establishment__company=company,
                start_date__gte=start_of_year,
            ).count()

            return count
        except Exception:
            return 0

    def get_used_storage_gb(self, obj):
        """
        Dynamic calculation: Sum file sizes for all images belonging to this company.
        Includes images from establishments, parcels, productions (History), and events.
        For S3-stored images, uses an estimated average size of 2MB.
        """
        try:
            from common.models import GalleryImage
            from history.models import History

            company = obj.company
            if not company:
                return Decimal("0.00")

            total_bytes = 0
            # Average image size estimate for S3 images (2MB)
            ESTIMATED_IMAGE_SIZE = 2 * 1024 * 1024  # 2MB in bytes

            def get_album_size(album):
                """Calculate size for all images in an album."""
                if not album:
                    return 0
                album_bytes = 0
                images = GalleryImage.objects.filter(gallery=album)
                for img in images:
                    # Try to get actual file size
                    if img.image:
                        try:
                            album_bytes += img.image.size
                            continue
                        except Exception:
                            pass
                    # For S3 or URL images, use estimated size
                    if img.s3_key or img.image_url:
                        album_bytes += ESTIMATED_IMAGE_SIZE
                return album_bytes

            # Get all establishments for this company
            establishments = company.establishment_set.all()

            for establishment in establishments:
                # Establishment album
                total_bytes += get_album_size(establishment.album)

                # Parcel albums
                for parcel in establishment.parcels.all():
                    total_bytes += get_album_size(parcel.album)

                    # History (production) albums for each parcel
                    histories = History.objects.filter(parcel=parcel)
                    for history in histories:
                        total_bytes += get_album_size(history.album)

                        # Event albums - iterate through all event types
                        event_types = [
                            "history_productionevent_events",
                            "history_chemicalevent_events",
                            "history_weatherevent_events",
                            "history_generalevent_events",
                            "history_equipmentevent_events",
                            "history_soilevent_events",
                            "history_pestevent_events",
                            "history_businessevent_events",
                        ]
                        for event_type in event_types:
                            try:
                                events = getattr(history, event_type, None)
                                if events:
                                    for event in events.all():
                                        total_bytes += get_album_size(event.album)
                            except Exception:
                                pass

            # Convert bytes to GB (1 GB = 1024^3 bytes)
            gb = Decimal(total_bytes) / Decimal(1024 * 1024 * 1024)
            return round(gb, 2)
        except Exception:
            return Decimal("0.00")

    def get_scan_count(self, obj):
        """
        Dynamic calculation: Count QR scans for this company in current billing period.
        Uses HistoryScan model for accurate tracking.
        """
        try:
            from history.models import HistoryScan

            company = obj.company
            if not company:
                return 0

            # Use current billing period, or fall back to current month
            if obj.current_period_start:
                period_start = obj.current_period_start
            else:
                now = timezone.now()
                period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            # Count scans for productions belonging to this company in current period
            # HistoryScan -> History -> Parcel -> Establishment -> Company
            count = HistoryScan.objects.filter(
                history__parcel__establishment__company=company,
                date__gte=period_start,
            ).count()

            return count
        except Exception:
            return 0


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["id", "card_brand", "last_4", "exp_month", "exp_year", "is_default"]


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "amount", "status", "invoice_date", "due_date", "invoice_pdf"]
