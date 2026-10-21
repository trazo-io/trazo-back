from datetime import timedelta

from django.db.models import Avg, Q
from django.utils import timezone

from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from common.models import Gallery
from common.serializers import GallerySerializer
from common.validators import USContactFieldsMixin, USStateFieldMixin
from product.serializers import ParcelBasicSerializer, parcel_members_map, with_open_season_count
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
            "ca_operator_id",
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
            # NOP compliance — OFPP fraud prevention plan
            "fraud_prevention_plan_uploaded",
            "ofpp_on_file",
            "ofpp_filename_suspicious",
            "fraud_prevention_plan_date",
            "fraud_prevention_plan_document",
            "ofpp_responsible_person",
            # NOP compliance — Split operation tracking (7 CFR 205.272)
            "has_split_operation",
            "split_operation_plan",
        )

    def get_parcels(self, establishment):
        # One query for the parcels with their product and album, one batch for every parcel's
        # members (see `parcel_members_map`), instead of ~8 queries per parcel.
        parcels = list(
            with_open_season_count(establishment.parcels.all())
            # `current_history__product`: ParcelBasicSerializer.get_product names the season's crop.
            .select_related("product", "album", "current_history__product")
            # `crop_history` / `landowner_affidavits`: parcel_application_status reads them per parcel.
            .prefetch_related("album__images", "crop_history", "landowner_affidavits")
        )
        context = {**self.context, "parcel_members": parcel_members_map(parcels)}
        return ParcelBasicSerializer(parcels, many=True, context=context).data

    def get_image(self, establishment):
        try:
            if not establishment.album_id:
                return None
            images = list(establishment.album.images.all())  # `album__images` prefetch, see get_establishments
            if not images:
                return None
            image_obj = min(images, key=lambda image: image.pk)  # the row `.first()` returned

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


class UpdateEstablishmentSerializer(USContactFieldsMixin, USStateFieldMixin, ModelSerializer):
    US_PHONE_FIELDS = ("contact_phone", "phone")
    US_ZIP_FIELDS = ("zip_code",)
    US_STATE_FIELDS = ("state",)

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
            "ca_operator_id",
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
            # NOP compliance — OFPP fraud prevention plan
            "fraud_prevention_plan_uploaded",
            "ofpp_on_file",
            "ofpp_filename_suspicious",
            "fraud_prevention_plan_date",
            "fraud_prevention_plan_document",
            "ofpp_responsible_person",
            # NOP compliance — Split operation tracking (7 CFR 205.272)
            "has_split_operation",
            "split_operation_plan",
        )
        # 🔴 2026-08-21 (F25) — READ-ONLY, deliberately. The § 205.201(a)(5) split-operation
        # declaration has exactly one editor: OSP module G6.0, which writes through to these
        # columns (certifications/osp_modules/bindings.py). They stayed writable here for the
        # farm-profile checkbox, and that made the profile a second editor of a regulated
        # fact — a farm that answered "yes" in the OSP filed a packet whose § 205.272 row
        # said "Split Operation: No". Serialized OUT (the profile still displays the
        # declaration), never IN.
        read_only_fields = ("has_split_operation", "split_operation_plan")

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
        admin_works_in = WorksIn.objects.filter(company=company, role=WorksIn.COMPANY_ADMIN)
        for works_in in admin_works_in:
            works_in.establishments_in_charge.add(establishment)

        return establishment


class RetrieveEstablishmentSerializer(ModelSerializer):
    parcels = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    # F25 — "yes" / "no" / "unanswered". `has_split_operation` is a boolean column and so
    # cannot tell a declared "no" apart from a field nobody has touched; the farm profile
    # needs that difference, because rendering the default as a declaration is the same
    # manufactured-statement bug the packet was fixed for.
    split_operation_declaration = serializers.SerializerMethodField()

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
            "ca_operator_id",
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
            # NOP compliance — OFPP fraud prevention plan
            "fraud_prevention_plan_uploaded",
            "ofpp_on_file",
            "ofpp_filename_suspicious",
            "fraud_prevention_plan_date",
            "fraud_prevention_plan_document",
            "ofpp_responsible_person",
            # NOP compliance — Split operation tracking (7 CFR 205.272)
            "has_split_operation",
            "split_operation_plan",
            "split_operation_declaration",
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
        return ParcelBasicSerializer(
            with_open_season_count(establishment.parcels.all()), many=True, context=self.context
        ).data

    def get_split_operation_declaration(self, establishment):
        """Resolved through the ONE definition (certifications.services.split_operation).

        Computed on the DETAIL view only. `EstablishmentViewSet.get_serializer_class` hands
        this same serializer to `list`, and the resolver costs up to two OSP queries per
        establishment — on the farm switcher of an Operation-tier company that is 2N queries
        for a value no list surface renders. `None` here means "not computed on this view",
        and the farm profile (the only reader) always arrives through `retrieve`.
        """
        view = self.context.get("view")
        if getattr(view, "action", None) == "list":
            return None

        from certifications.services.split_operation import split_operation_declaration

        return split_operation_declaration(establishment)


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
            # `state` decides which state-specific compliance surfaces render (the CA
            # PUR fields, the CDFA registration card). RetrieveCompanySerializer falls
            # back to this serializer when there is no request in context, and without
            # `state` a real California grower would silently lose the PUR fields on
            # their spray form. Both call sites are authenticated staff-facing, never
            # the anonymous consumer payload.
            "state",
            # PUR box 3 default for the spray form's placeholder (California farms only).
            "ca_operator_id",
        )


class RetrieveCompanySerializer(USContactFieldsMixin, USStateFieldMixin, ModelSerializer):
    US_PHONE_FIELDS = ("contact_phone",)
    US_ZIP_FIELDS = ("zip_code",)
    US_STATE_FIELDS = ("state",)

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
                    company.establishment_set.all()
                    .select_related("album")
                    .prefetch_related("album__images")
                    .order_by("name"),
                    many=True,
                    context=self.context,
                ).data

            # Other roles see only their assigned establishments
            return EstablishmentSerializer(
                worksIn.establishments_in_charge.all()
                .select_related("album")
                .prefetch_related("album__images")
                .order_by("name"),
                many=True,
                context=self.context,
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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # The join code grants Viewer access to every farm in the company, so only a company
        # admin sees it. Anyone else who holds it could forward it without the admin knowing.
        request = self.context.get("request")
        user = getattr(request, "user", None)
        is_admin = bool(
            user
            and user.is_authenticated
            and (user.is_superuser or instance.company_workers.filter(user=user, role=WorksIn.COMPANY_ADMIN).exists())
        )
        if not is_admin:
            data["invitation_code"] = None
        return data

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


class CreateCompanySerializer(USContactFieldsMixin, USStateFieldMixin, ModelSerializer):
    US_PHONE_FIELDS = ("contact_phone",)
    US_ZIP_FIELDS = ("zip_code",)
    US_STATE_FIELDS = ("state",)

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

        now = timezone.now()
        # A rolling 30-day window, not calendar month-to-date. On the 2nd of a month the
        # month-to-date version showed two days of scans and "1 unique visitor" on a farm with
        # a hundred, and the other scan surface (`_calculate_transparency_analytics`) already
        # uses the last 30 days — one window, so the two never disagree.
        month_start = now - timedelta(days=30)
        last_month_start = now - timedelta(days=60)

        # --- 1. CONSUMER ENGAGEMENT (2 queries) ---
        current_month_scans = HistoryScan.objects.counted().filter(
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
        last_month_count = (
            HistoryScan.objects.counted()
            .filter(
                history__parcel__establishment=establishment,
                date__gte=last_month_start,
                date__lt=month_start,
            )
            .count()
        )

        if last_month_count > 0:
            scan_growth_percentage = ((monthly_scans - last_month_count) / last_month_count) * 100
        else:
            # No previous window: show 0 instead of a misleading 100%
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

        # --- 4. FINISHED SEASONS (a COUNT, never a score) ---
        # Until 2026-09-05 this section averaged a TransparencyCalculator run over every finished,
        # published season (282 SQL queries, ~3 s in production on every dashboard load) into a
        # farm-level `transparency_score` + `transparency_tier`. Nothing rendered either: the
        # only reader used the score as a gate behind 1,000 monthly scans. The one fact the card
        # shows is a count of seasons closed out.
        #
        # Every finished season, published or not (2026-10-18). Until then this counted finished
        # AND published, so a pilot whose season was finished with the buyer page left unpublished
        # (the default in assisted setup) read "0 · No finished season yet" while the season page
        # said "Finished". Publishing is a buyer-page choice; the certifier packet and dossier
        # cover the season either way.
        scored_productions = establishment_histories.filter(finish_date__isnull=False).count()
        # Literally "no finish date yet". Deliberately NOT `total - scored`: that would also
        # sweep in a season the farmer finished but has not published, which is not underway.
        productions_in_progress = establishment_histories.filter(finish_date__isnull=True).count()

        # --- 5. BLOCKCHAIN COUNT (bulk, from extra_data JSON) ---
        blockchain_verified_count = 0
        for h in establishment_histories.only("extra_data"):
            if h.extra_data and isinstance(h.extra_data, dict):
                if h.extra_data.get("blockchain_verified", False):
                    blockchain_verified_count += 1
                elif isinstance(h.extra_data.get("blockchain"), dict):
                    if h.extra_data["blockchain"].get("verified", False):
                        blockchain_verified_count += 1

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
            # Finished seasons, published or not (count). The farm-level score left this payload 2026-09-05.
            "scored_productions": scored_productions,
            "total_documented_events": total_documented_events,
            # Production counts
            "total_productions": total_productions,
            "productions_in_progress": productions_in_progress,
            "blockchain_verified_count": blockchain_verified_count,
            # Subscription
            "subscription_usage_percentage": round(subscription_usage_percentage, 1),
        }
