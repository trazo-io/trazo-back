from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from common.models import Gallery
from common.serializers import GallerySerializer
from common.validators import USContactFieldsMixin
from product.services.buffer_zones import BufferZoneError, normalize_buffer_rows
from users.models import User
from users.serializers import BasicUserSerializer

from .models import Parcel, ParcelCropHistory, Product


def parcel_members_map(parcels):
    """{parcel_id: [User, …]} — up to two most recently created users who authored an event on any
    of the parcel's seasons, for a whole list of parcels at once.

    Replaces the per-parcel path in `ParcelBasicSerializer.get_members` (one query for the
    seasons, one eight-way UNION per season, one User query per parcel, then the User
    serializer's WorksIn/company/establishment lookups per member). For the company payload that
    was ~50 of its 82 queries; this is eight + one, whatever the farm size. Same selection rule:
    `User.objects.filter(id__in=…)[0:2]` under the model's `-created_at` ordering.
    """
    from collections import defaultdict

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

    parcel_ids = [p.id for p in parcels]
    if not parcel_ids:
        return {}
    ids_by_parcel = defaultdict(set)
    for model in (
        WeatherEvent,
        ChemicalEvent,
        ProductionEvent,
        GeneralEvent,
        EquipmentEvent,
        SoilManagementEvent,
        PestManagementEvent,
        BusinessEvent,
    ):
        rows = (
            model.objects.filter(history__parcel_id__in=parcel_ids, created_by__isnull=False)
            .values_list("history__parcel_id", "created_by_id")
            .distinct()
        )
        for parcel_id, user_id in rows:
            ids_by_parcel[parcel_id].add(user_id)
    all_ids = set().union(*ids_by_parcel.values()) if ids_by_parcel else set()
    users = {
        u.id: u
        for u in User.objects.filter(id__in=all_ids).prefetch_related(
            # Everything BasicUserSerializer.companies reads, so serializing a member is query-free.
            "worksin_set__company__establishment_set",
            "worksin_set__establishments_in_charge",
        )
    }
    return {
        parcel_id: sorted((users[i] for i in ids if i in users), key=lambda u: (u.created_at, u.id), reverse=True)[:2]
        for parcel_id, ids in ids_by_parcel.items()
    }


class ParcelBasicSerializer(ModelSerializer):
    product = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    has_current_production = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    # WS-5 quick-add: lets the parcel card show "Add details" without shipping the
    # full polygon payload in every establishment response.
    has_boundaries = serializers.SerializerMethodField()
    # WS-5 Parcel Application: live completion state for the card chip / list column.
    application_status = serializers.SerializerMethodField()

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
            "has_boundaries",
            "application_status",
            # Hectares (see Parcel.area help_text). Served so the OSP editor can show
            # the farmer their own acreage while they write the § 205.201(a) narrative,
            # instead of leaving them to describe their operation from memory.
            # NOT public: `parcels` is absent from the public_fields allow-list in
            # company/views.py's anonymous establishment endpoint.
            "area",
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

    def get_has_boundaries(self, parcel):
        return bool(parcel.polygon)

    def get_application_status(self, parcel):
        from product.services.parcel_application_status import parcel_application_status

        return parcel_application_status(parcel)["state"]

    def get_has_current_production(self, parcel):
        # The FK id answers this; `parcel.current_history is not None` loaded the whole
        # History row, once per parcel.
        return parcel.current_history_id is not None

    def get_image(self, parcel):
        try:
            if not parcel.album_id:
                return None
            # From the `album__images` prefetch when the caller set one up; `.exists()` and
            # `.first()` each went back to the database per parcel.
            images = list(parcel.album.images.all())
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

    def get_members(self, parcel):
        batched = self.context.get("parcel_members")
        if batched is not None:
            # Built once per establishment by `parcel_members_map` (see EstablishmentSerializer).
            members = batched.get(parcel.id, [])
        else:
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
    primary_crop = serializers.SerializerMethodField()
    # `transparency_score` / `transparency_ready` removed 2026-09-09 with the two Parcel
    # methods behind them — a 0-100 self-grade and its boolean verdict. `application_status`
    # and `application_missing` below are the factual replacement: they name WHICH § 205.202
    # blocks are missing instead of scoring the parcel out of 100.

    # Vocabulary for the block_id autocomplete on every event form. Served with the parcel the
    # form already loads, so offering it costs no extra request.
    known_block_ids = serializers.SerializerMethodField()

    # WS-5: live Parcel Application state for the parcel page's entry button.
    application_status = serializers.SerializerMethodField()
    application_missing = serializers.SerializerMethodField()
    # ⛔ Ship these WITH `application_status`, never instead of it. A surface that renders the
    # answers verdict alone is the "complete" badge that printed above "[REVIEW] no map
    # attached"; a surface that renders evidence alone hides the half that is done.
    evidence_status = serializers.SerializerMethodField()
    evidence_missing = serializers.SerializerMethodField()
    evidence_detail = serializers.SerializerMethodField()

    class Meta:
        model = Parcel
        exclude = ("album",)

    def get_application_status(self, parcel):
        from product.services.parcel_application_status import parcel_application_status

        return parcel_application_status(parcel)["state"]

    def get_application_missing(self, parcel):
        # The service always computed WHICH of the §205.202 blocks are missing, but this
        # serializer stripped it to the bare state — so the UI could only say "In progress",
        # never what was left (found in the 2026-08-10 signposting audit).
        from product.services.parcel_application_status import parcel_application_status

        return parcel_application_status(parcel)["missing"]

    def get_evidence_status(self, parcel):
        """Is the supporting EVIDENCE on file — a different question from "are the questions
        answered", and the one a "complete" badge used to answer by accident.

        ⛔ Never an adequacy verdict. It reports what the map IS (an operator upload, a
        schematic from recorded geometry, geometry that disagrees with the stated area, or
        nothing). Whether that satisfies a given certifying agent is the agent's call.
        """
        from product.services.parcel_application_status import parcel_application_status

        return parcel_application_status(parcel)["evidence_state"]

    def get_evidence_missing(self, parcel):
        from product.services.parcel_application_status import parcel_application_status

        return parcel_application_status(parcel)["evidence_missing"]

    def get_evidence_detail(self, parcel):
        from product.services.parcel_application_status import parcel_application_status

        return parcel_application_status(parcel)["evidence_detail"]

    def get_known_block_ids(self, parcel):
        """Blocks already recorded on this parcel, so the grower picks instead of retyping.

        Free text plus no vocabulary is how "Block 3", "block 3" and "Blk 3" become three blocks
        that no certifier query can reconcile. Imported COG Pro "Row/Section ID" values populate
        this automatically, which is what keeps a migration's block structure intact the first
        time the farmer logs a new event against it.
        """
        from history.services.block_ids import known_block_ids_for_parcel

        return known_block_ids_for_parcel(parcel)

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

    def get_primary_crop(self, parcel):
        """Get primary crop focus for this parcel"""
        return parcel.get_primary_crop()


class CreateParcelSerializer(USContactFieldsMixin, ModelSerializer):
    US_PHONE_FIELDS = ("contact_phone",)

    product = serializers.SerializerMethodField()
    album = GallerySerializer(required=False)
    image = serializers.SerializerMethodField()
    uploaded_image_urls = serializers.ListField(child=serializers.URLField(), required=False, write_only=True)
    s3_keys = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)

    # ✅ AGRICULTURAL DATA FIELDS - Accept all advanced fields
    agricultural_details = serializers.JSONField(required=False)

    # Per-boundary buffer-zone / adjoining-land / drift-prevention records
    # (7 CFR 205.202(c); 205.400(f)(1)). Writable so a real pilot farmer can record
    # buffers — previously buffer_zones was a model JSONField with no write path, so
    # the audit export fired the empty-state REVIEW flag on every non-seeded parcel.
    buffer_zones = serializers.JSONField(required=False, allow_null=True)

    # §E-6 irrigation pumping plant. Declared explicitly with allow_null so a STALE pump test
    # can be cleared: the parcel-compliance card PATCHes multipart/form-data, which cannot
    # carry a real null, so it sends "" — and DRF's DecimalField/DateField reject "" by
    # default. `_BLANKABLE_MULTIPART_FIELDS` in to_internal_value coerces "" -> None. Being able to
    # clear matters because an out-of-date efficiency is weaker evidence than none.
    pump_efficiency_pct = serializers.DecimalField(max_digits=4, decimal_places=1, required=False, allow_null=True)
    system_pressure_psi = serializers.DecimalField(max_digits=5, decimal_places=1, required=False, allow_null=True)
    pump_test_date = serializers.DateField(required=False, allow_null=True)

    # Schoolsite proximity (3 CCR 6691; DPR ENF 25-16). Declared with allow_null for the same
    # multipart reason as the pump fields above, and for a second one that matters more: THREE
    # states. True, False and "never asked" are different facts on a PUR, so clearing the answer
    # back to unknown has to stay possible. An unanswered parcel is reported as a gap; it is
    # never asserted to be clear of a schoolsite.
    ca_near_schoolsite = serializers.BooleanField(required=False, allow_null=True)

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
        required=False, write_only=True, help_text="Parcel description (stored as Parcel.description)"
    )
    sustainability_practices = serializers.CharField(
        required=False, write_only=True, help_text="Soil and conservation practices (7 CFR 205.203)"
    )
    # `consumer_story` write field removed 2026-08-07 — the parcel form no longer collects
    # it and no surface renders it. See product/models.py where the getter was removed.
    # The model carries MinValueValidator(0.0001) on `area`, but DRF calls full_clean() on
    # neither create() nor update(), so a model validator alone guards nothing on the API path
    # — the same gap that let a cultural-control pest event save without its practice. Declared
    # here so the floor actually holds where parcels are actually written.
    area = serializers.FloatField(min_value=0.0001, help_text="Parcel area in hectares")

    crop_focus = serializers.CharField(required=False, write_only=True, help_text="Primary crop grown for transparency")
    # `transparency_ready` (write-only boolean, stashed into agricultural_details) removed
    # 2026-09-09. It was a self-graded verdict accepted from the client for a field the parcel
    # form stopped sending on 2026-08-17 — so the API's only remaining behaviour here was to
    # let any caller assert its own readiness. The score is retired as a concept, and a
    # payload may only carry fields its UI renders.

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
            # Read-only here on purpose. The value is WRITTEN through
            # `ParcelViewSet.location_disclosure`, so the one-question prompt that collects it
            # does not have to send a whole parcel payload to answer it. Exposed for reading
            # because the prompt has to know whether to appear at all.
            "location_disclosure_level",
            "location_disclosure_choice_made",
            "buffer_zones",
            "container_production",
            "apn",
            "section_township_range",
            "ca_site_id",
            # 3 CCR 6691 via 6434(6)(A) and 6626(c); DPR ENF 25-16, effective 2026-01-01.
            # Writable here because the PUR export reads it to decide whether an application
            # owes a method code, and with no writer the field can only ever stay unanswered.
            "ca_near_schoolsite",
            "date_began_managing",
            "treated_lumber_present",
            "treated_lumber_description",
            "treated_lumber_install_date",
            # §E-6 irrigation pumping plant — feeds the irrigation carbon calculation.
            "pump_efficiency_pct",
            "system_pressure_psi",
            "pump_test_date",
            "pump_test_provider",
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
            "crop_focus",
            # SerializerMethodField
            "image",
        ]
        # Disclosure is read here and written ONLY through
        # `ParcelViewSet.location_disclosure`. Leaving it writable on this serializer would let
        # the parcel form carry it in a payload whose UI never renders it — and a field that can
        # be written by a form that does not show it is exactly how a farm ends up publishing a
        # boundary nobody chose, which is the defect this whole change exists to close.
        read_only_fields = ["id", "location_disclosure_level", "location_disclosure_choice_made"]

    def get_product(self, parcel):
        return None

    # Nullable non-string fields that the multipart parcel-compliance PATCH may send as "".
    # Renamed from _BLANKABLE_MULTIPART_FIELDS on 2026-09-18: it stopped being pump-only when the
    # schoolsite answer joined it, and a name that lies about its contents is how the next
    # nullable field gets left out.
    _BLANKABLE_MULTIPART_FIELDS = (
        "pump_efficiency_pct",
        "system_pressure_psi",
        "pump_test_date",
        "ca_near_schoolsite",
    )

    def to_internal_value(self, data):
        """Coerce "" -> None for nullable numeric/date fields sent over multipart form data.

        Mirrors coerce_blank_nullable_dates() in history/serializers.py. Without this a farmer
        could set a pump test but never clear one, because the only way multipart can express
        "empty" is an empty string, which DRF rejects for Decimal and Date fields.
        """
        if hasattr(data, "copy"):
            data = data.copy()
            for field in self._BLANKABLE_MULTIPART_FIELDS:
                if field in data and data.get(field) in ("", "null", None):
                    data[field] = None
        return super().to_internal_value(data)

    def validate_buffer_zones(self, value):
        """Validate + normalize the per-boundary buffer-zone records (7 CFR 205.202(c)).

        Delegates to `product.services.buffer_zones`, which is the single owner of the
        row vocabulary. This method used to rebuild each row from its own whitelist,
        which destroyed every key the OSP Parcel Application wizard wrote — see that
        module's docstring for the full failure.
        """
        if value is None:
            return value
        try:
            return normalize_buffer_rows(value)
        except BufferZoneError as exc:
            raise serializers.ValidationError(str(exc))

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
        transparency_fields = ["sustainability_practices"]

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


class ParcelCropHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ParcelCropHistory
        fields = [
            "id",
            "parcel",
            "year",
            "crop_grown",
            "cover_crop",
            # Distinguishes the rows of a SPLIT FIELD — two crops on one parcel in one year.
            # Without it the API cannot set or show which part of the field grew what.
            "block_id",
            "production_method",
            "substances_applied",
            # USDA Field History form #1: per-material rows (material / manufacturer / dates)
            "substance_applications",
            "last_prohibited_substance",
            "date_last_prohibited",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def to_internal_value(self, data):
        """Coerce "" -> None for nullable date fields.

        The field-history form posts every field it renders, so a grower who leaves "Date
        Applied" blank sends "" — and DRF's DateField rejects that with "Date has wrong
        format", 400ing the whole entry over a field the form itself calls optional. This is
        the same class as the seed_purchase_date / cleaning_date / ca_dpr_permit_expires bugs.

        Uses the introspective helper rather than naming `date_last_prohibited`: a
        hand-maintained list is exactly what lets the next nullable date slip through.
        """
        from history.serializers import coerce_blank_nullable_dates

        if hasattr(data, "copy"):
            data = data.copy()
            coerce_blank_nullable_dates(self, data)
        return super().to_internal_value(data)
