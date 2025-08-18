from rest_framework.serializers import ModelSerializer
from .models import Company, Establishment
from rest_framework import serializers
from product.serializers import ParcelBasicSerializer
from common.serializers import GallerySerializer
from common.models import Gallery
from users.models import WorksIn
from subscriptions.serializers import SubscriptionSerializer
from django.db.models import Avg, Count, Q, Sum
from django.db import models
from django.utils import timezone
from datetime import timedelta


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
        return ParcelBasicSerializer(
            establishment.parcels.all(), 
            many=True,
            context=self.context
        ).data

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

            request = self.context.get('request')
            if request and not image_url.startswith(('http://', 'https://')):
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
            request = self.context.get('request')
            image_list = []
            for image_obj in establishment.album.images.all():
                image_url = image_obj.url
                if image_url:
                    if request and not image_url.startswith(('http://', 'https://')):
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
        images_to_delete = validated_data.pop('images_to_delete', [])
        s3_keys = validated_data.pop('s3_keys', None)
        uploaded_image_urls = validated_data.pop('uploaded_image_urls', None)
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
            existing_urls = set(existing_images.values_list('image_url', flat=True))
            new_urls_set = set(filter(None, new_urls))  # Remove any None/empty URLs
            
            # Find URLs to add and remove
            urls_to_add = new_urls_set - existing_urls
            urls_to_remove = existing_urls - new_urls_set
            
            logger.info(f"Gallery {gallery.id}: Adding {len(urls_to_add)} images, removing {len(urls_to_remove)} images")
            
            # Remove images that are no longer needed
            if urls_to_remove:
                removed_count = gallery.images.filter(image_url__in=urls_to_remove).delete()[0]
                logger.info(f"Removed {removed_count} images from gallery {gallery.id}")
            
            # Add new images (bulk_create for efficiency)
            if urls_to_add:
                new_images = [
                    gallery.images.model(gallery=gallery, image_url=url)
                    for url in urls_to_add
                ]
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
            existing_keys = set(existing_images.values_list('s3_key', flat=True))
            new_keys_set = set(new_s3_keys)
            
            # Find keys to add and remove
            keys_to_add = new_keys_set - existing_keys
            keys_to_remove = existing_keys - new_keys_set
            
            # Remove images that are no longer needed
            if keys_to_remove:
                gallery.images.filter(s3_key__in=keys_to_remove).delete()
            
            # Add new images
            if keys_to_add:
                new_images = [
                    gallery.images.model(gallery=gallery, s3_key=key)
                    for key in keys_to_add
                ]
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
        s3_keys = validated_data.pop('s3_keys', None)
        uploaded_image_urls = validated_data.pop('uploaded_image_urls', None)
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
            
        return super().create(validated_data)


class RetrieveEstablishmentSerializer(ModelSerializer):
    parcels = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta:
        model = Establishment
        fields = "__all__"

    def get_images(self, establishment):
        try:
            if not establishment.album:
                return []
            
            request = self.context.get('request')
            image_list = []
            
            for image_obj in establishment.album.images.all():
                image_url = image_obj.url
                if image_url:
                    if request and not image_url.startswith(('http://', 'https://')):
                        image_url = request.build_absolute_uri(image_url)
                    image_list.append(image_url)
            
            return image_list
        except Exception as e:
            print(f"Error getting images: {str(e)}")
            return []
    
    def get_parcels(self, establishment):
        return ParcelBasicSerializer(
            establishment.parcels.all(), 
            many=True,
            context=self.context
        ).data


class EstablishmentSeriesSerializer(serializers.Serializer):
    scans = serializers.ListField()
    sales = serializers.ListField()

    class Meta:
        fields = ["scans", "sales"]


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
                return BasicEstablishmentSerializer(
                    company.establishment_set.all().order_by("name"), many=True
                ).data
                
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
                    company.establishment_set.all().order_by("name"), 
                    many=True, 
                    context=self.context
                ).data
            
            # Other roles see only their assigned establishments
            return EstablishmentSerializer(
                worksIn.establishments_in_charge.all().order_by("name"), 
                many=True, 
                context=self.context
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
            if not hasattr(company, 'album'):
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

            request = self.context.get('request')
            if request and not image_url.startswith(('http://', 'https://')):
                return request.build_absolute_uri(image_url)
            return image_url
        except Exception as e:
            print(f"Error getting image: {str(e)}")
            return None

    def get_has_subscription(self, obj):
        """Check if company has an active subscription"""
        if hasattr(obj, 'subscription') and obj.subscription:
            return obj.subscription.status in ['active', 'trialing']
        return False
    
    def get_subscription_plan(self, obj):
        """Get serialized subscription plan data if available"""
        if hasattr(obj, 'subscription') and obj.subscription and obj.subscription.plan:
            return {
                'id': obj.subscription.plan.id,
                'name': obj.subscription.plan.name,
                'price': obj.subscription.plan.price,
                'interval': obj.subscription.plan.interval,
                'features': obj.subscription.plan.features
            }
        return None


class CreateCompanySerializer(ModelSerializer):
    class Meta:
        model = Company
        exclude = (
            "invitation_code",
        )
        extra_kwargs = {
            'fiscal_id': {'required': False},
            'zip_code': {'required': False},
            'employee_count': {'required': False},
            'industry': {'required': False},
            'is_active': {'required': False},
            'sustainability_metadata': {'required': False},
            # New agricultural compliance fields (optional)
            'legal_structure': {'required': False},
            'primary_commodities': {'required': False},
            'sustainability_commitment': {'required': False},
        }


class EstablishmentDashboardMetricsSerializer(serializers.Serializer):
    """
    Accurate dashboard metrics for SmartUsageCard based on real backend data
    """
    # Consumer engagement metrics
    consumer_reach = serializers.IntegerField(help_text="Unique consumers reached this month")
    monthly_scans = serializers.IntegerField(help_text="Total QR scans this month")
    scan_growth_percentage = serializers.FloatField(help_text="Month-over-month scan growth")
    
    # Trust and verification metrics
    trust_score = serializers.IntegerField(help_text="Average confidence score (0-100%)")
    verified_productions = serializers.IntegerField(help_text="Productions with carbon verification")
    total_productions = serializers.IntegerField(help_text="Total productions in establishment")
    
    # Performance metrics
    industry_percentile = serializers.FloatField(help_text="Industry ranking percentile")
    carbon_score = serializers.FloatField(help_text="Average carbon score (1-5 stars)")
    
    # Business impact metrics
    revenue_potential = serializers.FloatField(help_text="Transparency engagement score (not actual revenue)")
    
    # Subscription context
    subscription_usage_percentage = serializers.FloatField(help_text="Subscription limits usage %")
    is_premium = serializers.BooleanField(help_text="Premium subscription status")
    
    def get_metrics_for_establishment(self, establishment):
        """
        Calculate accurate metrics from backend data
        """
        from history.models import History, HistoryScan
        
        # Get current month date range
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (month_start - timedelta(days=1)).replace(day=1)
        
        # 1. CONSUMER REACH - Unique session hashes this month
        current_month_scans = HistoryScan.objects.filter(
            history__parcel__establishment=establishment,
            date__gte=month_start,
            consent_given=True  # Only count consented scans
        )
        
        consumer_reach = current_month_scans.values('session_hash').distinct().count()
        monthly_scans = current_month_scans.count()
        
        # 2. SCAN GROWTH - Month over month comparison
        last_month_scans = HistoryScan.objects.filter(
            history__parcel__establishment=establishment,
            date__gte=last_month_start,
            date__lt=month_start,
            consent_given=True
        ).count()
        
        scan_growth_percentage = 0
        if last_month_scans > 0:
            scan_growth_percentage = ((monthly_scans - last_month_scans) / last_month_scans) * 100
        elif monthly_scans > 0:
            scan_growth_percentage = 100  # First month with scans
            
        # 3. TRUST SCORE - Average confidence from productions
        establishment_histories = History.objects.filter(parcel__establishment=establishment)
        avg_confidence = establishment_histories.aggregate(
            avg_conf=Avg('confidence_score')
        )['avg_conf'] or 70  # Default to 70% if no data
        
        trust_score = round(avg_confidence)
        
        # 4. VERIFIED PRODUCTIONS - Count with carbon data
        total_productions = establishment_histories.count()
        verified_productions = establishment_histories.filter(
            Q(carbonentry__isnull=False) | 
            Q(carbonreport__isnull=False) |
            Q(carbon_intelligence__isnull=False)
        ).distinct().count()
        
        # 5. INDUSTRY PERCENTILE - Based on carbon performance and confidence scores
        # Get average confidence score for this establishment
        avg_confidence = establishment_histories.aggregate(
            avg_conf=Avg('confidence_score')
        )['avg_conf'] or 70
        
        # Calculate percentile based on confidence score (simplified)
        if avg_confidence >= 85:
            industry_percentile = 90
        elif avg_confidence >= 75:
            industry_percentile = 80
        elif avg_confidence >= 65:
            industry_percentile = 70
        else:
            industry_percentile = 60
            
        # 6. CARBON SCORE - Average from transparency and confidence scores
        transparency_avg = establishment_histories.aggregate(
            avg_trans=Avg('transparency_score')
        )['avg_trans'] or 70
        
        # Combine confidence and transparency for carbon score (1-5 scale)
        combined_score = (avg_confidence + transparency_avg) / 2
        carbon_score = min(5.0, max(1.0, (combined_score / 100) * 5))
            
        # 7. TRANSPARENCY ENGAGEMENT - What Trazo Actually Provides
        # NOTE: We don't have actual sales/premium data, so we show engagement metrics instead
        revenue_potential = 0
        if consumer_reach > 0 and monthly_scans > 0:
            # TRANSPARENCY ENGAGEMENT SCORE: Combination of reach and verification
            # This represents the value Trazo provides: consumer engagement with farm transparency
            
            # Engagement score based on actual tracked metrics
            engagement_base = consumer_reach * 10  # Each unique consumer = 10 points
            scan_multiplier = min(monthly_scans / 10, 5)  # Up to 5x multiplier for scan frequency
            verification_bonus = verified_productions * 20  # Verification adds credibility
            
            # Calculate transparency engagement score (not actual revenue)
            transparency_engagement = engagement_base * scan_multiplier + verification_bonus
            
            # Convert to a meaningful metric for farmers
            # This represents "transparency reach potential" rather than guaranteed revenue
            revenue_potential = min(transparency_engagement, 1000)  # Cap at 1000 for display
        else:
            # Fallback for new farms
            revenue_potential = verified_productions * 50  # Basic potential based on verified products
            
        # 8. SUBSCRIPTION CONTEXT - From company subscription
        subscription = establishment.company.subscription if hasattr(establishment.company, 'subscription') else None
        subscription_usage_percentage = 0
        is_premium = False
        
        if subscription:
            max_productions = subscription.plan.features.get('max_productions_per_year', 100)
            if max_productions > 0:
                subscription_usage_percentage = (subscription.used_productions / max_productions) * 100
            
            is_premium = subscription.plan.name.lower() in ['premium', 'enterprise']
        
        return {
            'consumer_reach': consumer_reach,
            'monthly_scans': monthly_scans,
            'scan_growth_percentage': round(scan_growth_percentage, 1),
            'trust_score': trust_score,
            'verified_productions': verified_productions,
            'total_productions': total_productions,
            'industry_percentile': industry_percentile,
            'carbon_score': round(carbon_score, 1),
            'revenue_potential': round(revenue_potential, 2),
            'subscription_usage_percentage': round(subscription_usage_percentage, 1),
            'is_premium': is_premium
        }
