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
    effective_limits = serializers.SerializerMethodField()

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
            "effective_limits",
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

        Prefers the file_size field (populated on upload) for accuracy.
        Falls back to 3 MB estimate for S3/URL images without file_size,
        or reads .size from local storage backend.
        """
        try:
            from history.models import History

            company = obj.company
            if not company:
                return Decimal("0.00")

            ESTIMATED_IMAGE_SIZE = 3 * 1024 * 1024  # 3 MB fallback for images without file_size

            # --- Step 1: collect gallery IDs across all tiers ---
            est_gallery_ids = list(
                company.establishment_set.exclude(album__isnull=True).values_list("album_id", flat=True)
            )

            parcel_gallery_ids = list(
                company.establishment_set.prefetch_related("parcels")
                .exclude(parcels__album__isnull=True)
                .values_list("parcels__album_id", flat=True)
            )

            history_qs = History.objects.filter(parcel__establishment__company=company).exclude(album__isnull=True)
            history_gallery_ids = list(history_qs.values_list("album_id", flat=True))

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

            # --- Step 2: compute total bytes ---
            from django.db.models import Q, Sum

            all_images_qs = GalleryImage.objects.filter(gallery_id__in=all_gallery_ids)

            # Sum known file sizes (populated on upload)
            known_size_result = all_images_qs.filter(file_size__isnull=False).aggregate(total=Sum("file_size"))
            known_bytes = known_size_result["total"] or 0

            # Count remote images WITHOUT file_size (need estimate)
            remote_unknown_count = (
                all_images_qs.filter(file_size__isnull=True)
                .filter(Q(s3_key__isnull=False) | Q(image_url__isnull=False))
                .count()
            )

            # Local images WITHOUT file_size — read actual .size
            local_images = list(
                all_images_qs.filter(file_size__isnull=True)
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

            total_bytes = known_bytes + (remote_unknown_count * ESTIMATED_IMAGE_SIZE) + local_bytes

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

    def _get_effective_limits(self, obj):
        """
        Compute effective limits = base plan limits + purchased add-ons.
        This ensures the dashboard displays the true limits the user has paid for.
        """
        cache_attr = f"_effective_limits_cache_{obj.pk}"
        if hasattr(self, cache_attr):
            return getattr(self, cache_attr)

        features = obj.plan.features if obj.plan else {}

        def base(key, default=0):
            return features.get(key, default)

        def addon_qty(slug):
            try:
                # Use .all() + Python filter to leverage prefetch_related cache
                # (.filter() would bypass the prefetch and hit the DB)
                return sum(a.quantity for a in obj.addons.all() if a.addon and a.addon.slug == slug)
            except Exception:
                return 0

        def add_if_not_unlimited(base_val, extra):
            if base_val == -1:
                return -1
            return max(0, base_val) + extra

        result = {
            "max_establishments": add_if_not_unlimited(
                base("max_establishments", 0),
                addon_qty("extra-establishment"),
            ),
            "max_parcels_per_establishment": add_if_not_unlimited(
                base("max_parcels_per_establishment", 0),
                addon_qty("extra-parcel"),
            ),
            "max_productions_per_year": add_if_not_unlimited(
                base("max_productions_per_year", 0),
                addon_qty("extra-production") * 10,
            ),
            "monthly_scan_limit": base("monthly_scan_limit", 0),
            "storage_limit_gb": add_if_not_unlimited(
                base("storage_limit_gb", 0),
                addon_qty("extra-storage"),
            ),
            "support_response_time": base("support_response_time", 48),
            "priority_support": base("priority_support", False),
            "voice_recording": base("voice_recording", False),
            "ai_event_templates": base("ai_event_templates", True),
        }
        setattr(self, cache_attr, result)
        return result

    def get_effective_limits(self, obj):
        if not obj.plan:
            return {}
        return self._get_effective_limits(obj)

    def get_usage_warnings(self, obj):
        """
        Return warnings for resources approaching plan limits.
        Uses effective limits (base + add-ons) and cached usage values.
        """
        warnings = []
        if not obj.plan or not obj.plan.features:
            return warnings

        limits = self._get_effective_limits(obj)
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
            limits.get("max_productions_per_year", 0),
            "Productions this year",
        )
        check_limit(
            "scans",
            usage["scans"],
            limits.get("monthly_scan_limit", 0),
            "QR scans this month",
        )
        check_limit(
            "storage",
            float(usage["storage"]),
            limits.get("storage_limit_gb", 0),
            "Storage (GB)",
        )
        check_limit(
            "establishments",
            usage["establishments"],
            limits.get("max_establishments", 0),
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
