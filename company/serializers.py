from datetime import timedelta

from django.db.models import Avg, Q
from django.utils import timezone

from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from common.models import Gallery
from common.serializers import GallerySerializer
from product.serializers import ParcelBasicSerializer
from subscriptions.serializers import SubscriptionSerializer
from users.models import WorksIn

from .models import Company, Establishment


class EstablishmentSerializer(ModelSerializer):
    parcels = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta:
        model = Establishment
        fields = (
            "id",
            "name",
            "description",
            "address",
            "city",
            "zone",
            "state",
            "image",
            "parcels",
            "image",
            "country",
            "location",
            "type",
            "latitude",
            "longitude",
            "contact_person",
            "contact_phone",
            "contact_email",
            "certifications",
            "about",
            "main_activities",
            "location_highlights",
            "custom_message",
            "images",
            "email",
            "phone",
            "zip_code",
            "is_active",
            "crops_grown",
            "sustainability_practices",
            "employee_count",
            "total_acreage",
            "year_established",
            "establishment_type",
            "farming_method",
            # New operational fields
            "water_sources",
            "climate_zone",
            "soil_types",
            "conservation_practices",
            "irrigation_methods",
        )

    def get_parcels(self, establishment):
        return ParcelBasicSerializer(establishment.parcels.all(), many=True, context=self.context).data

    def get_image(self, establishment):
        try:
            if not establishment.album or not establishment.album.images.exists():
                return None

            image_obj = establishment.album.images.first()
            if not image_obj:
                return None

            # Use the url property which handles image, image_url, and s3_key
            image_url = image_obj.url
            if not image_url:
                return None

            request = self.context.get("request")
            if request and not image_url.startswith(("http://", "https://")):
                return request.build_absolute_uri(image_url)
            return image_url
        except Exception as e:
            print(f"Error getting image: {str(e)}")
            return None

    def get_location(self, establishment):
        return establishment.get_location()

    def get_images(self, establishment):
        try:
            if not establishment.album:
                return []
            request = self.context.get("request")
            image_list = []
            for image_obj in establishment.album.images.all():
                image_url = image_obj.url
                if image_url:
                    if request and not image_url.startswith(("http://", "https://")):
                        image_url = request.build_absolute_uri(image_url)
                    image_list.append({"id": image_obj.id, "url": image_url})
            return image_list
        except Exception as e:
            print(f"Error getting images: {str(e)}")
            return []


class UpdateEstablishmentSerializer(ModelSerializer):
    album = GallerySerializer(required=False)
    s3_keys = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)
    uploaded_image_urls = serializers.ListField(child=serializers.URLField(), required=False, write_only=True)
    images_to_delete = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)

    class Meta:
        model = Establishment
        fields = (
            "id",
            "name",
            "city",
            "zone",
            "album",
            "state",
            "company",
            "description",
            "country",
            "s3_keys",
            "uploaded_image_urls",
            "images_to_delete",
            "type",
            "latitude",
            "longitude",
            "contact_person",
            "contact_phone",
            "contact_email",
            "certifications",
            "about",
            "main_activities",
            "location_highlights",
            "custom_message",
            "address",
            "email",
            "phone",
            "zip_code",
            "is_active",
            "crops_grown",
            "sustainability_practices",
            "employee_count",
            "total_acreage",
            "year_established",
            "establishment_type",
            "farming_method",
            # New operational fields
            "water_sources",
            "climate_zone",
            "soil_types",
            "conservation_practices",
            "irrigation_methods",
        )

    def to_representation(self, instance):
        return EstablishmentSerializer(instance).data

    def update(self, instance, validated_data):
        images_to_delete = validated_data.pop("images_to_delete", [])
        s3_keys = validated_data.pop("s3_keys", None)
        uploaded_image_urls = validated_data.pop("uploaded_image_urls", None)
        album_data = self.context.get("request").FILES

        # Create or get the gallery
        gallery = instance.album
        if gallery is None:
            gallery = Gallery.objects.create()

        # Delete images from the gallery
        if images_to_delete and instance.album:
            for image_id in images_to_delete:
                instance.album.images.filter(id=image_id).delete()

        # Handle S3 keys from production environment
        if s3_keys:
            self._update_gallery_images_by_s3_keys(gallery, s3_keys)
            validated_data["album"] = gallery

        # Handle uploaded image URLs (for both environments)
        elif uploaded_image_urls:
            self._update_gallery_images_by_urls(gallery, uploaded_image_urls)
            validated_data["album"] = gallery

        # Handle direct file uploads from form (development environment)
        elif album_data:
            self._update_gallery_images_by_files(gallery, album_data)
            validated_data["album"] = gallery

        return super().update(instance, validated_data)

    def _update_gallery_images_by_urls(self, gallery, new_urls):
        """
        Update gallery images using differential approach - Django best practice.
        Only creates/deletes what's actually changed.
        """
        import logging

        from django.db import transaction

        logger = logging.getLogger(__name__)

        with transaction.atomic():
            # Validate input
            if not new_urls:
                logger.warning(f"Empty URL list provided for gallery {gallery.id}")
                return

            # Get current image URLs
            existing_images = gallery.images.filter(image_url__isnull=False)
            existing_urls = set(existing_images.values_list("image_url", flat=True))
            new_urls_set = set(filter(None, new_urls))  # Remove any None/empty URLs

            # Find URLs to add and remove
            urls_to_add = new_urls_set - existing_urls
            urls_to_remove = existing_urls - new_urls_set

            logger.info(
                f"Gallery {gallery.id}: Adding {len(urls_to_add)} images, removing {len(urls_to_remove)} images"
            )

            # Remove images that are no longer needed
            if urls_to_remove:
                removed_count = gallery.images.filter(image_url__in=urls_to_remove).delete()[0]
                logger.info(f"Removed {removed_count} images from gallery {gallery.id}")

            # Add new images (bulk_create for efficiency)
            if urls_to_add:
                new_images = [gallery.images.model(gallery=gallery, image_url=url) for url in urls_to_add]
                created_images = gallery.images.bulk_create(new_images)
                logger.info(f"Added {len(created_images)} images to gallery {gallery.id}")

    def _update_gallery_images_by_s3_keys(self, gallery, new_s3_keys):
        """
        Update gallery images by S3 keys using differential approach.
        """
        from django.db import transaction

        with transaction.atomic():
            # Get current S3 keys
            existing_images = gallery.images.filter(s3_key__isnull=False)
            existing_keys = set(existing_images.values_list("s3_key", flat=True))
            new_keys_set = set(new_s3_keys)

            # Find keys to add and remove
            keys_to_add = new_keys_set - existing_keys
            keys_to_remove = existing_keys - new_keys_set

            # Remove images that are no longer needed
            if keys_to_remove:
                gallery.images.filter(s3_key__in=keys_to_remove).delete()

            # Add new images
            if keys_to_add:
                new_images = [gallery.images.model(gallery=gallery, s3_key=key) for key in keys_to_add]
                gallery.images.bulk_create(new_images)

    def _update_gallery_images_by_files(self, gallery, album_data):
        """
        Update gallery images by direct file uploads.
        Note: File-based comparison is more complex, using simpler approach for now.
        """
        from django.db import transaction

        with transaction.atomic():
            # For file uploads, we need to replace all since we can't easily compare files
            # This is acceptable for file uploads as they represent a complete replacement
            gallery.images.filter(image__isnull=False).delete()

            # Add new file-based images
            for image_data in album_data.values():
                gallery.images.create(image=image_data)

    def create(self, validated_data):
        s3_keys = validated_data.pop("s3_keys", None)
        uploaded_image_urls = validated_data.pop("uploaded_image_urls", None)
        album_data = self.context.get("request").FILES

        if s3_keys:
            gallery = Gallery.objects.create()

            for s3_key in s3_keys:
                gallery_image = gallery.images.create(s3_key=s3_key)
                gallery_image.save()

            validated_data["album"] = gallery
        elif uploaded_image_urls:
            gallery = Gallery.objects.create()

            for url in uploaded_image_urls:
                gallery_image = gallery.images.create(image_url=url)
                gallery_image.save()

            validated_data["album"] = gallery
        elif album_data:
            gallery = Gallery.objects.create()
            for image_data in album_data.getlist("album[images]"):
                gallery_image = gallery.images.create(image=image_data)
                gallery_image.save()
            validated_data["album"] = gallery

        establishment = super().create(validated_data)

        # Auto-assign new establishment to all company admins
        company = establishment.company
        admin_works_in = WorksIn.objects.filter(
            company=company, role=WorksIn.COMPANY_ADMIN
        )
        for works_in in admin_works_in:
            works_in.establishments_in_charge.add(establishment)

        return establishment


class RetrieveEstablishmentSerializer(ModelSerializer):
    parcels = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta:
        model = Establishment
        fields = [
            "id",
            "public_id",
            "name",
            "address",
            "city",
            "zone",
            "state",
            "company",
            "album",
            "description",
            "country",
            "type",
            "latitude",
            "longitude",
            "contact_person",
            "contact_phone",
            "contact_email",
            "certifications",
            "about",
            "main_activities",
            "location_highlights",
            "custom_message",
            "email",
            "phone",
            "zip_code",
            "is_active",
            "crops_grown",
            "sustainability_practices",
            "employee_count",
            "total_acreage",
            "year_established",
            "establishment_type",
            "farming_method",
            "water_sources",
            "climate_zone",
            "soil_types",
            "conservation_practices",
            "irrigation_methods",
            # SerializerMethodFields
            "parcels",
            "images",
        ]
        read_only_fields = ["id", "public_id"]

    def get_images(self, establishment):
        try:
            if not establishment.album:
                return []

            request = self.context.get("request")
            image_list = []

            for image_obj in establishment.album.images.all():
                image_url = image_obj.url
                if image_url:
                    if request and not image_url.startswith(("http://", "https://")):
                        image_url = request.build_absolute_uri(image_url)
                    image_list.append(image_url)

            return image_list
        except Exception as e:
            print(f"Error getting images: {str(e)}")
            return []

    def get_parcels(self, establishment):
        return ParcelBasicSerializer(establishment.parcels.all(), many=True, context=self.context).data


class EstablishmentSeriesSerializer(serializers.Serializer):
    scans = serializers.ListField()
    reviews = serializers.ListField()

    class Meta:
        fields = ["scans", "reviews"]


class EstablishmentChartSerializer(serializers.Serializer):
    series = EstablishmentSeriesSerializer()
    options = serializers.SerializerMethodField()

    class Meta:
        model = Establishment
        fields = ["series", "options"]

    def get_options(self, establishment):
        period = self.context["period"]
        if period == "week":
            week_days = [
                "Sun",
                "Mon",
                "Tue",
                "Wed",
                "Thu",
                "Fri",
                "Sat",
            ]
            return [week_days[day - 1] for day in self.context["days"]]
        elif period == "month":
            return self.context["days"]
        elif period == "year":
            return [
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ]
        return []


class EstablishmentProductsReputationSerializer(serializers.Serializer):
    series = serializers.ListField()
    options = serializers.ListField()

    class Meta:
        model = Establishment
        fields = ["series", "options"]


class BasicEstablishmentSerializer(ModelSerializer):
    class Meta:
        model = Establishment
        fields = (
            "id",
            "name",
        )


class RetrieveCompanySerializer(ModelSerializer):
    establishments = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    subscription = SubscriptionSerializer(read_only=True)
    has_subscription = serializers.SerializerMethodField()
    subscription_plan = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = (
            "id",
            "name",
            "tradename",
            "address",
            "city",
            "state",
            "country",
            "fiscal_id",
            "logo",
            "description",
            "invitation_code",
            "contact_email",
            "contact_phone",
            "website",
            "facebook",
            "instagram",
            "certifications",
            "zip_code",
            "employee_count",
            "industry",
            "is_active",
            "sustainability_metadata",
            "blockchain_subscription_status",
            # New agricultural compliance fields
            "legal_structure",
            "primary_commodities",
            "sustainability_commitment",
            "establishments",
            "image",
            "subscription",
            "has_subscription",
            "subscription_plan",
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_establishments(self, company):
        try:
            if "request" not in self.context:
                # Return basic establishment data without user-specific filtering
                return BasicEstablishmentSerializer(company.establishment_set.all().order_by("name"), many=True).data

            user = self.context["request"].user

            # Get user's WorksIn relationship for this company
            try:
                worksIn = WorksIn.objects.get(user=user, company=company)
            except WorksIn.DoesNotExist:
                # User doesn't work in this company - return empty list
                return []
            except WorksIn.MultipleObjectsReturned:
                # Multiple relationships (shouldn't happen) - get the first one
                worksIn = WorksIn.objects.filter(user=user, company=company).first()

            # Company Admins see all establishments
            if worksIn.role == "CA":
                return EstablishmentSerializer(
                    company.establishment_set.all().order_by("name"), many=True, context=self.context
                ).data

            # Other roles see only their assigned establishments
            return EstablishmentSerializer(
                worksIn.establishments_in_charge.all().order_by("name"), many=True, context=self.context
            ).data

        except Exception as e:
            # Log detailed error for debugging
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error getting establishments for user {user.email} in company {company.name}: {str(e)}")

            # For safety, return empty list instead of all establishments
            return []

    def get_image(self, company):
        try:
            if not hasattr(company, "album"):
                return None

            if not company.album or not company.album.images.exists():
                return None

            image_obj = company.album.images.first()
            if not image_obj:
                return None

            # Use the url property which handles image, image_url, and s3_key
            image_url = image_obj.url
            if not image_url:
                return None

            request = self.context.get("request")
            if request and not image_url.startswith(("http://", "https://")):
                return request.build_absolute_uri(image_url)
            return image_url
        except Exception as e:
            print(f"Error getting image: {str(e)}")
            return None

    def get_has_subscription(self, obj):
        """Check if company has an active subscription"""
        if hasattr(obj, "subscription") and obj.subscription:
            return obj.subscription.status in ["active", "trialing"]
        return False

    def get_subscription_plan(self, obj):
        """Get serialized subscription plan data if available"""
        if hasattr(obj, "subscription") and obj.subscription and obj.subscription.plan:
            return {
                "id": obj.subscription.plan.id,
                "name": obj.subscription.plan.name,
                "price": obj.subscription.plan.price,
                "interval": obj.subscription.plan.interval,
                "features": obj.subscription.plan.features,
            }
        return None


class CreateCompanySerializer(ModelSerializer):
    class Meta:
        model = Company
        exclude = ("invitation_code",)
        extra_kwargs = {
            "fiscal_id": {"required": False},
            "zip_code": {"required": False},
            "employee_count": {"required": False},
            "industry": {"required": False},
            "is_active": {"required": False},
            "sustainability_metadata": {"required": False},
            # New agricultural compliance fields (optional)
            "legal_structure": {"required": False},
            "primary_commodities": {"required": False},
            "sustainability_commitment": {"required": False},
        }


class EstablishmentDashboardMetricsSerializer(serializers.Serializer):
    """
    Transparency-first dashboard metrics for SmartUsageCard.
    Optimized: uses bulk queries instead of per-production loops.
    """

    def get_metrics_for_establishment(self, establishment):
        """
        Calculate dashboard metrics using bulk DB queries (no N+1).
        Returns transparency-first metrics aligned with Trazo's mission.
        """
        from django.db.models import Count, Sum
        from django.utils import timezone

        from carbon.models import CarbonEntry
        from history.models import History, HistoryScan
        from history.services.transparency_calculator import TransparencyCalculator

        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (month_start - timedelta(days=1)).replace(day=1)

        # --- 1. CONSUMER ENGAGEMENT (2 queries) ---
        current_month_scans = HistoryScan.objects.filter(
            history__parcel__establishment=establishment,
            date__gte=month_start,
        )
        monthly_scans = current_month_scans.count()

        # Consumer reach: unique sessions > unique IPs > estimate
        session_reach = current_month_scans.exclude(session_hash="").values("session_hash").distinct().count()
        if session_reach > 0:
            consumer_reach = session_reach
        else:
            ip_reach = current_month_scans.exclude(ip_hash="").values("ip_hash").distinct().count()
            consumer_reach = ip_reach if ip_reach > 0 else (max(1, monthly_scans // 30) if monthly_scans > 0 else 0)

        # --- 2. SCAN GROWTH (1 query) ---
        last_month_count = HistoryScan.objects.filter(
            history__parcel__establishment=establishment,
            date__gte=last_month_start,
            date__lt=month_start,
        ).count()

        if last_month_count > 0:
            scan_growth_percentage = ((monthly_scans - last_month_count) / last_month_count) * 100
        else:
            # First month: show 0 instead of misleading 100%
            scan_growth_percentage = 0

        # --- 3. PRODUCTIONS + EVENT COUNTS (bulk, no N+1) ---
        establishment_histories = History.objects.filter(parcel__establishment=establishment)
        total_productions = establishment_histories.count()

        # Count total documented events across all event types in bulk
        from history.models import (
            BusinessEvent,
            ChemicalEvent,
            EquipmentEvent,
            GeneralEvent,
            PestManagementEvent,
            ProductionEvent,
            SoilManagementEvent,
            WeatherEvent,
        )

        history_ids = list(establishment_histories.values_list("id", flat=True))

        total_documented_events = 0
        if history_ids:
            event_models = [
                ProductionEvent,
                ChemicalEvent,
                SoilManagementEvent,
                PestManagementEvent,
                WeatherEvent,
                BusinessEvent,
                GeneralEvent,
                EquipmentEvent,
            ]
            for model in event_models:
                total_documented_events += model.objects.filter(history_id__in=history_ids).count()

        # --- 4. TRANSPARENCY SCORES (per-production, required by calculator) ---
        transparency_calc = TransparencyCalculator()
        transparency_scores = []

        for history in establishment_histories.select_related("crop_type").prefetch_related(
            "history_productionevent_events__album__images",
            "history_chemicalevent_events__album__images",
            "history_soilmanagementevent_events__album__images",
            "history_pestmanagementevent_events__album__images",
            "history_weatherevent_events",
            "history_businessevent_events",
            "history_generalevent_events",
            "history_equipmentevent_events__album__images",
        ):
            t_data = transparency_calc.calculate_transparency_score(history)
            transparency_scores.append(t_data.get("transparency_percentage", 0))

        transparency_score = sum(transparency_scores) / len(transparency_scores) if transparency_scores else 0

        # --- 5. BLOCKCHAIN COUNT (bulk, from extra_data JSON) ---
        blockchain_verified_count = 0
        for h in establishment_histories.only("extra_data"):
            if h.extra_data and isinstance(h.extra_data, dict):
                if h.extra_data.get("blockchain_verified", False):
                    blockchain_verified_count += 1
                elif isinstance(h.extra_data.get("blockchain"), dict):
                    if h.extra_data["blockchain"].get("verified", False):
                        blockchain_verified_count += 1

        # --- 6. TRANSPARENCY PERCENTILE (based on transparency score, NOT carbon) ---
        # Rank this farm's transparency against platform average
        # This aligns with transparency-first: more documentation = better ranking
        if transparency_score >= 90:
            transparency_percentile = 95
        elif transparency_score >= 80:
            transparency_percentile = 85
        elif transparency_score >= 70:
            transparency_percentile = 75
        elif transparency_score >= 60:
            transparency_percentile = 60
        elif transparency_score >= 40:
            transparency_percentile = 40
        else:
            transparency_percentile = max(5, int(transparency_score))

        # --- 7. SUBSCRIPTION CONTEXT ---
        subscription = establishment.company.subscription if hasattr(establishment.company, "subscription") else None
        subscription_usage_percentage = 0
        if subscription:
            max_productions = subscription.plan.features.get("max_productions_per_year", 100)
            if max_productions > 0:
                subscription_usage_percentage = (subscription.used_productions / max_productions) * 100

        return {
            # Consumer engagement
            "consumer_reach": consumer_reach,
            "monthly_scans": monthly_scans,
            "scan_growth_percentage": round(scan_growth_percentage, 1),
            # Transparency (PRIMARY)
            "transparency_score": round(transparency_score, 1),
            "total_documented_events": total_documented_events,
            # Production counts
            "total_productions": total_productions,
            "blockchain_verified_count": blockchain_verified_count,
            # Transparency-based ranking
            "transparency_percentile": transparency_percentile,
            # Subscription
            "subscription_usage_percentage": round(subscription_usage_percentage, 1),
        }
