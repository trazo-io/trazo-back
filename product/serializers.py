from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from common.models import Gallery
from common.serializers import GallerySerializer
from users.models import User
from users.serializers import BasicUserSerializer

from .models import Parcel, Product


class ParcelBasicSerializer(ModelSerializer):
    product = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    has_current_production = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()

    class Meta:
        model = Parcel
        fields = (
            "id",
            "name",
            "description",
            "product",
            "image",
            "has_current_production",
            "members",
            "soil_type",
            "unique_code",
            "certification_type",
            "contact_person",
            "contact_phone",
            "contact_email",
        )

    def get_product(self, parcel):
        return (
            parcel.current_history.product.name if parcel.current_history and parcel.current_history.product else None
        )

    def get_has_current_production(self, parcel):
        return parcel.current_history is not None

    def get_image(self, parcel):
        try:
            if not parcel.album or not parcel.album.images.exists():
                return None

            image_obj = parcel.album.images.first()
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

    def get_members(self, parcel):
        members_ids = []
        for history in parcel.histories.all():
            members_ids += history.get_involved_users()
        members_ids = list(set(members_ids))
        members = User.objects.filter(id__in=members_ids)[0:2]
        return BasicUserSerializer(members, many=True).data


class RetrieveParcelSerializer(ModelSerializer):
    product = serializers.SerializerMethodField()
    establishment = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    productions_completed = serializers.SerializerMethodField()

    # 🎯 TRANSPARENCY FIELDS for consumer display
    transparency_description = serializers.SerializerMethodField()
    sustainability_practices = serializers.SerializerMethodField()
    consumer_story = serializers.SerializerMethodField()
    primary_crop = serializers.SerializerMethodField()
    transparency_score = serializers.SerializerMethodField()
    transparency_ready = serializers.SerializerMethodField()

    class Meta:
        model = Parcel
        exclude = ("album",)

    def get_product(self, parcel):
        return parcel.product.name if parcel.product else None

    def get_establishment(self, parcel):
        return parcel.establishment.name if parcel.establishment else None

    def get_image(self, parcel):
        try:
            if not parcel.album or not parcel.album.images.exists():
                return None

            image_obj = parcel.album.images.first()
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

    def get_images(self, parcel):
        try:
            if not parcel.album:
                return []

            request = self.context.get("request")
            image_list = []

            for image_obj in parcel.album.images.all():
                image_url = image_obj.url
                if image_url:
                    if request and not image_url.startswith(("http://", "https://")):
                        image_url = request.build_absolute_uri(image_url)
                    image_list.append(image_url)

            return image_list
        except Exception as e:
            print(f"Error getting images: {str(e)}")
            return []

    def get_productions_completed(self, parcel):
        return parcel.productions_completed

    # 🎯 TRANSPARENCY FIELD GETTERS
    def get_transparency_description(self, parcel):
        """Get consumer-facing parcel description"""
        return parcel.get_transparency_description()

    def get_sustainability_practices(self, parcel):
        """Get sustainability practices narrative for consumers"""
        return parcel.get_sustainability_practices()

    def get_consumer_story(self, parcel):
        """Get consumer story explaining why this parcel matters"""
        return parcel.get_consumer_story()

    def get_primary_crop(self, parcel):
        """Get primary crop focus for this parcel"""
        return parcel.get_primary_crop()

    def get_transparency_score(self, parcel):
        """Get transparency readiness score (0-100)"""
        return parcel.get_transparency_score()

    def get_transparency_ready(self, parcel):
        """Check if parcel is ready for consumer transparency"""
        return parcel.is_transparency_ready()


class CreateParcelSerializer(ModelSerializer):
    product = serializers.SerializerMethodField()
    album = GallerySerializer(required=False)
    image = serializers.SerializerMethodField()
    uploaded_image_urls = serializers.ListField(child=serializers.URLField(), required=False, write_only=True)
    s3_keys = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)

    # ✅ AGRICULTURAL DATA FIELDS - Accept all advanced fields
    agricultural_details = serializers.JSONField(required=False)

    # Individual agricultural fields for backward compatibility and easy access
    soil_ph = serializers.FloatField(required=False, write_only=True)
    soil_organic_matter = serializers.FloatField(required=False, write_only=True)
    soil_nitrogen = serializers.FloatField(required=False, write_only=True)
    soil_phosphorus = serializers.FloatField(required=False, write_only=True)
    soil_potassium = serializers.FloatField(required=False, write_only=True)
    cover_crop_management = serializers.CharField(required=False, write_only=True)
    irrigation_efficiency = serializers.FloatField(required=False, write_only=True)
    organic_certification_status = serializers.CharField(required=False, write_only=True)
    nrcs_practices = serializers.CharField(required=False, write_only=True)
    carbon_sequestration_practices = serializers.CharField(required=False, write_only=True)

    # 🎯 TRANSPARENCY-FOCUSED FIELDS for consumer-facing narratives
    transparency_description = serializers.CharField(
        required=False, write_only=True, help_text="Consumer-facing parcel description"
    )
    sustainability_practices = serializers.CharField(
        required=False, write_only=True, help_text="Sustainability practices for consumers"
    )
    consumer_story = serializers.CharField(
        required=False, write_only=True, help_text="Why consumers should care about this parcel"
    )
    crop_focus = serializers.CharField(required=False, write_only=True, help_text="Primary crop grown for transparency")
    transparency_ready = serializers.BooleanField(
        required=False, write_only=True, help_text="Parcel ready for consumer transparency"
    )

    class Meta:
        model = Parcel
        fields = [
            # Model fields
            "id",
            "name",
            "description",
            "album",
            "establishment",
            "product",
            "area",
            "certified",
            "current_history",
            "polygon",
            "map_metadata",
            "soil_type",
            "unique_code",
            "certification_type",
            "contact_person",
            "contact_phone",
            "contact_email",
            "address",
            "agricultural_details",
            "carbon_calculation_enabled",
            "usda_compliance_eligible",
            # Extra write-only fields declared above
            "uploaded_image_urls",
            "s3_keys",
            "soil_ph",
            "soil_organic_matter",
            "soil_nitrogen",
            "soil_phosphorus",
            "soil_potassium",
            "cover_crop_management",
            "irrigation_efficiency",
            "organic_certification_status",
            "nrcs_practices",
            "carbon_sequestration_practices",
            "transparency_description",
            "sustainability_practices",
            "consumer_story",
            "crop_focus",
            "transparency_ready",
            # SerializerMethodField
            "image",
        ]
        read_only_fields = ["id"]

    def get_product(self, parcel):
        return None

    def _handle_agricultural_data(self, instance, validated_data):
        """Handle agricultural data fields and store in agricultural_details JSONField"""
        agricultural_fields = [
            "soil_ph",
            "soil_organic_matter",
            "soil_nitrogen",
            "soil_phosphorus",
            "soil_potassium",
            "cover_crop_management",
            "irrigation_efficiency",
            "organic_certification_status",
            "nrcs_practices",
            "carbon_sequestration_practices",
        ]

        # 🎯 TRANSPARENCY FIELDS for consumer-facing narratives
        transparency_fields = ["sustainability_practices", "consumer_story", "transparency_ready"]

        # Get existing agricultural_details or create new dict
        agricultural_details = validated_data.get("agricultural_details", instance.agricultural_details or {})

        # Move individual agricultural fields to agricultural_details
        for field in agricultural_fields:
            if field in validated_data:
                agricultural_details[field] = validated_data.pop(field)

        # Move transparency fields to agricultural_details for consumer display
        for field in transparency_fields:
            if field in validated_data:
                agricultural_details[field] = validated_data.pop(field)

        # 🎯 Handle transparency_description → description mapping
        if "transparency_description" in validated_data:
            validated_data["description"] = validated_data.pop("transparency_description")

        # 🎯 Handle crop_focus for current production (store in agricultural_details for reference)
        if "crop_focus" in validated_data:
            agricultural_details["primary_crop"] = validated_data.pop("crop_focus")

        # Store updated agricultural_details
        validated_data["agricultural_details"] = agricultural_details

        # Update carbon calculation flags if we have enough data
        if instance.pk:  # Only for existing instances
            instance.agricultural_details = agricultural_details
            instance.update_usda_compliance_status()
            validated_data["usda_compliance_eligible"] = instance.usda_compliance_eligible

            # 🎯 Enable carbon calculations for transparency parcels
            has_transparency_data = bool(
                agricultural_details.get("sustainability_practices")
                or agricultural_details.get("carbon_sequestration_practices")
            )
            validated_data["carbon_calculation_enabled"] = (
                instance.calculate_carbon_readiness_score() > 60 or has_transparency_data
            )

    def update(self, instance, validated_data):
        s3_keys = validated_data.pop("s3_keys", None)
        uploaded_image_urls = validated_data.pop("uploaded_image_urls", None)
        album_data = self.context.get("request").FILES

        # Debug logging
        print(f"🖼️ UPDATE: uploaded_image_urls = {uploaded_image_urls}")
        print(f"🖼️ UPDATE: s3_keys = {s3_keys}")
        print(f"🖼️ UPDATE: album_data = {album_data}")
        print(f"🖼️ UPDATE: instance.album = {instance.album}")

        # ✅ HANDLE AGRICULTURAL DATA
        self._handle_agricultural_data(instance, validated_data)

        # Create or get the gallery
        gallery = instance.album
        if gallery is None:
            gallery = Gallery.objects.create()
            print(f"🖼️ UPDATE: Created new gallery with id={gallery.id}")

        # ✅ NEW APPROACH: If we receive a complete list of URLs, we should sync the gallery
        # This handles both additions and removals
        if uploaded_image_urls is not None and isinstance(uploaded_image_urls, list):
            print(f"🖼️ UPDATE: Syncing gallery with {len(uploaded_image_urls)} URLs")

            # Get current images
            current_images = list(gallery.images.all())
            current_urls = {img.image_url for img in current_images if img.image_url}
            new_urls = set(uploaded_image_urls)

            # Remove images that are no longer in the list
            urls_to_remove = current_urls - new_urls
            if urls_to_remove:
                print(f"🖼️ UPDATE: Removing {len(urls_to_remove)} images no longer in list")
                gallery.images.filter(image_url__in=urls_to_remove).delete()

            # Add new images
            urls_to_add = new_urls - current_urls
            for url in urls_to_add:
                if url and isinstance(url, str) and url.startswith("http"):
                    gallery_image = gallery.images.create(image_url=url)
                    gallery_image.save()
                    print(f"🖼️ UPDATE: Added NEW image: {url}")

            validated_data["album"] = gallery
            return super().update(instance, validated_data)

        # Handle S3 keys from production environment
        if s3_keys:
            # Get existing S3 keys to avoid duplicates
            existing_s3_keys = set(gallery.images.values_list("s3_key", flat=True))
            print(f"🖼️ UPDATE: Existing S3 keys in gallery: {existing_s3_keys}")

            for s3_key in s3_keys:
                if s3_key and s3_key not in existing_s3_keys:
                    gallery_image = gallery.images.create(s3_key=s3_key)
                    gallery_image.save()
                    print(f"🖼️ UPDATE: Added NEW S3 key: {s3_key}")
                else:
                    print(f"🖼️ UPDATE: Skipped DUPLICATE S3 key: {s3_key}")
            validated_data["album"] = gallery

        # Handle uploaded image URLs (for both environments)
        elif uploaded_image_urls:
            print(f"🖼️ UPDATE: Processing {len(uploaded_image_urls)} uploaded URLs")

            # Get existing image URLs to avoid duplicates
            existing_urls = set(gallery.images.values_list("image_url", flat=True))
            print(f"🖼️ UPDATE: Existing URLs in gallery: {existing_urls}")

            for url in uploaded_image_urls:
                if url and isinstance(url, str) and url.startswith("http"):
                    # Only add if not already in gallery
                    if url not in existing_urls:
                        gallery_image = gallery.images.create(image_url=url)
                        gallery_image.save()
                        print(f"🖼️ UPDATE: Added NEW image from URL: {url}")
                    else:
                        print(f"🖼️ UPDATE: Skipped DUPLICATE image URL: {url}")
            validated_data["album"] = gallery

        # Handle direct file uploads from form (development environment)
        elif album_data:
            print(f"🖼️ UPDATE: Processing {len(album_data.getlist('album[images]'))} file uploads")
            for image_data in album_data.getlist("album[images]"):
                gallery_image = gallery.images.create(image=image_data)
                gallery_image.save()
                print(f"🖼️ UPDATE: Added image file: {image_data.name}")
            validated_data["album"] = gallery

        # Always ensure gallery is assigned if it exists
        if gallery and gallery.id:
            validated_data["album"] = gallery
            print(f"🖼️ UPDATE: Assigned gallery {gallery.id} to parcel")

        return super().update(instance, validated_data)

    def create(self, validated_data):
        s3_keys = validated_data.pop("s3_keys", None)
        uploaded_image_urls = validated_data.pop("uploaded_image_urls", None)
        album_data = self.context.get("request").FILES

        # ✅ HANDLE AGRICULTURAL DATA (for create, we'll create a temporary instance to use the helper)
        temp_instance = type("TempInstance", (), {"agricultural_details": {}, "pk": None})()
        self._handle_agricultural_data(temp_instance, validated_data)

        if s3_keys:
            gallery = Gallery.objects.create()

            for s3_key in s3_keys:
                gallery_image = gallery.images.create(s3_key=s3_key)
                gallery_image.save()

            validated_data["album"] = gallery
        elif uploaded_image_urls:
            gallery = Gallery.objects.create()

            for url in uploaded_image_urls:
                if url and isinstance(url, str) and url.startswith("http"):
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

    def get_image(self, parcel):
        try:
            if not parcel.album or not parcel.album.images.exists():
                return None

            image_obj = parcel.album.images.first()
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


class ProductListOptionsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name"]


class ProductListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name", "description", "image"]
