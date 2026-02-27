from decimal import Decimal

from django.utils import timezone

from rest_framework import serializers

from common.models import GalleryImage

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
    pending_plan = PlanSerializer(read_only=True)
    addons = SubscriptionAddOnSerializer(many=True, read_only=True)

    # Dynamic calculations instead of cached fields
    used_productions = serializers.SerializerMethodField()
    used_storage_gb = serializers.SerializerMethodField()
    scan_count = serializers.SerializerMethodField()
    usage_warnings = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id",
            "plan",
            "pending_plan",
            "status",
            "current_period_start",
            "current_period_end",
            "cancel_at_period_end",
            "used_productions",
            "used_storage_gb",
            "scan_count",
            "trial_end",
            "addons",
            "usage_warnings",
        ]

    def _get_cached_usage(self, obj):
        """Compute all usage metrics once per serialization and cache on the instance."""
        cache_attr = f"_usage_cache_{obj.pk}"
        if hasattr(self, cache_attr):
            return getattr(self, cache_attr)

        productions = self._compute_used_productions(obj)
        storage = self._compute_used_storage_gb(obj)
        scans = self._compute_scan_count(obj)

        try:
            est_count = obj.company.establishment_set.count() if obj.company else 0
        except Exception:
            est_count = 0

        result = {
            "productions": productions,
            "storage": storage,
            "scans": scans,
            "establishments": est_count,
        }
        setattr(self, cache_attr, result)
        return result

    def _compute_used_productions(self, obj):
        try:
            from history.models import History

            company = obj.company
            if not company:
                return 0

            start_of_year = timezone.now().replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            return History.objects.filter(
                parcel__establishment__company=company,
                start_date__gte=start_of_year,
            ).count()
        except Exception:
            return 0

    def _compute_used_storage_gb(self, obj):
        """
        Compute total storage used across all galleries for a company's
        establishments, parcels, histories, and events.

        Uses a single aggregated query for S3/URL-backed images (estimated at
        2 MB each) combined with prefetch_related to batch-load local image
        objects and avoid N+1 queries.
        """
        try:
            from history.models import History

            company = obj.company
            if not company:
                return Decimal("0.00")

            ESTIMATED_IMAGE_SIZE = 2 * 1024 * 1024  # 2 MB per S3/URL image

            # --- Step 1: count S3/URL images via a single aggregated query ---
            # All galleries reachable from this company share the same Gallery
            # model, so we collect gallery IDs across each object tier and run
            # one COUNT query per tier.  This avoids the deeply nested loop
            # while keeping the two-path logic (local file.size vs estimate).

            # Gather all gallery IDs in one pass per tier using values_list
            # (no Python-side loops over individual rows).

            # Establishment albums
            est_gallery_ids = list(
                company.establishment_set.exclude(album__isnull=True).values_list("album_id", flat=True)
            )

            # Parcel albums
            parcel_gallery_ids = list(
                company.establishment_set.prefetch_related("parcels")
                .exclude(parcels__album__isnull=True)
                .values_list("parcels__album_id", flat=True)
            )

            # History albums
            history_qs = History.objects.filter(parcel__establishment__company=company).exclude(album__isnull=True)
            history_gallery_ids = list(history_qs.values_list("album_id", flat=True))

            # Event albums — the event tables all have an album FK and a
            # history FK, so we can traverse history -> events in one query
            # per event type.
            event_related_names = [
                "history_productionevent_events",
                "history_chemicalevent_events",
                "history_weatherevent_events",
                "history_generalevent_events",
                "history_equipmentevent_events",
                "history_soilevent_events",
                "history_pestevent_events",
                "history_businessevent_events",
            ]

            history_ids = list(
                History.objects.filter(parcel__establishment__company=company).values_list("id", flat=True)
            )

            event_gallery_ids = []
            if history_ids:
                for related_name in event_related_names:
                    # Derive the model class from the manager on History
                    try:
                        manager = getattr(History, related_name, None)
                        if manager is None:
                            continue
                        related_model = manager.rel.related_model
                        event_gallery_ids.extend(
                            list(
                                related_model.objects.filter(history_id__in=history_ids)
                                .exclude(album__isnull=True)
                                .values_list("album_id", flat=True)
                            )
                        )
                    except Exception:
                        pass

            all_gallery_ids = est_gallery_ids + parcel_gallery_ids + history_gallery_ids + event_gallery_ids

            if not all_gallery_ids:
                return Decimal("0.00")

            # --- Step 2: single batch query for all GalleryImage rows ---
            # Split into S3/URL images (estimated size) vs local images
            # (need to read actual .size from storage).

            # Count images that have s3_key or image_url (estimated size)
            from django.db.models import Q

            remote_image_count = (
                GalleryImage.objects.filter(
                    gallery_id__in=all_gallery_ids,
                )
                .filter(Q(s3_key__isnull=False) | Q(image_url__isnull=False))
                .count()
            )

            # For local images (no s3_key and no image_url) we must iterate
            # to call .size on the storage backend — kept minimal via
            # prefetch on only those rows.
            local_images = list(
                GalleryImage.objects.filter(
                    gallery_id__in=all_gallery_ids,
                )
                .exclude(Q(s3_key__isnull=False) | Q(image_url__isnull=False))
                .exclude(image="")
                .only("id", "image")
            )

            local_bytes = 0
            for img in local_images:
                try:
                    local_bytes += img.image.size
                except Exception:
                    local_bytes += ESTIMATED_IMAGE_SIZE

            total_bytes = (remote_image_count * ESTIMATED_IMAGE_SIZE) + local_bytes

            gb = Decimal(total_bytes) / Decimal(1024 * 1024 * 1024)
            return round(gb, 2)
        except Exception:
            return Decimal("0.00")

    def _compute_scan_count(self, obj):
        try:
            from history.models import HistoryScan

            company = obj.company
            if not company:
                return 0

            if obj.current_period_start:
                period_start = obj.current_period_start
            else:
                now = timezone.now()
                period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            return HistoryScan.objects.filter(
                history__parcel__establishment__company=company,
                date__gte=period_start,
            ).count()
        except Exception:
            return 0

    def get_used_productions(self, obj):
        return self._get_cached_usage(obj)["productions"]

    def get_used_storage_gb(self, obj):
        return self._get_cached_usage(obj)["storage"]

    def get_scan_count(self, obj):
        return self._get_cached_usage(obj)["scans"]

    def get_usage_warnings(self, obj):
        """
        Return warnings for resources approaching plan limits.
        Uses cached usage values to avoid duplicate queries.
        """
        warnings = []
        if not obj.plan or not obj.plan.features:
            return warnings

        features = obj.plan.features
        usage = self._get_cached_usage(obj)

        def check_limit(metric_name, used, limit, label):
            if limit == -1:  # unlimited
                return
            if limit <= 0:
                return
            pct = (used / limit) * 100
            if pct >= 95:
                warnings.append(
                    {
                        "metric": metric_name,
                        "label": label,
                        "used": used,
                        "limit": limit,
                        "percentage": round(pct, 1),
                        "level": "critical",
                    }
                )
            elif pct >= 80:
                warnings.append(
                    {
                        "metric": metric_name,
                        "label": label,
                        "used": used,
                        "limit": limit,
                        "percentage": round(pct, 1),
                        "level": "warning",
                    }
                )

        check_limit(
            "productions",
            usage["productions"],
            features.get("max_productions_per_year", 0),
            "Productions this year",
        )
        check_limit(
            "scans",
            usage["scans"],
            features.get("monthly_scan_limit", 0),
            "QR scans this month",
        )
        check_limit(
            "storage",
            float(usage["storage"]),
            features.get("storage_limit_gb", 0),
            "Storage (GB)",
        )
        check_limit(
            "establishments",
            usage["establishments"],
            features.get("max_establishments", 0),
            "Establishments",
        )

        return warnings


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = ["id", "card_brand", "last_4", "exp_month", "exp_year", "is_default"]


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "amount", "status", "invoice_date", "due_date", "invoice_pdf"]
