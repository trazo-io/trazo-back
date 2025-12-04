from rest_framework import serializers

from common.models import Gallery
from company.models import Establishment
from product.models import Parcel, Product
from users.models import User
from users.serializers import BasicUserSerializer

from .constants import (
    BUSINESS_EVENT_TYPE,
    CHEMICAL_EVENT_TYPE,
    EQUIPMENT_EVENT_TYPE,
    GENERAL_EVENT_TYPE,
    PEST_MANAGEMENT_EVENT_TYPE,
    PRODUCTION_EVENT_TYPE,
    SOIL_MANAGEMENT_EVENT_TYPE,
    WEATHER_EVENT_TYPE,
)
from .models import (
    BusinessEvent,
    ChemicalEvent,
    CommonEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    HistoryScan,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)


class EventSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    carbon_data = serializers.SerializerMethodField()
    album = serializers.SerializerMethodField()

    class Meta:
        model = CommonEvent
        fields = "__all__"

    def get_image(self, event):
        if event.album is not None and event.album.images.exists():
            first_image = event.album.images.first()
            # Prefer image_url (S3 URL) over file field
            if first_image.image_url:
                return first_image.image_url
            elif first_image.image:
                return first_image.image.url
        return None

    def get_album(self, event):
        """
        Get album data with images for photo verification in Production Journey
        """
        if not event.album:
            return None

        try:
            request = self.context.get("request")
            images = []

            for image in event.album.images.all():
                # Prefer image_url (S3 URL) over file field
                if image.image_url:
                    image_url = image.image_url
                elif image.image:
                    image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                else:
                    # Use placeholder image for testing
                    image_url = "https://via.placeholder.com/400x300/4CAF50/FFFFFF?text=Farming+Practice+Photo"

                images.append(
                    {
                        "id": image.id,
                        "image": image_url,
                        "caption": f"Farming practice photo {image.id}",  # Basic caption
                        "created_at": image.created_at.isoformat() if image.created_at else None,
                    }
                )

            return {"id": event.album.id, "images": images} if images else None
        except Exception as e:
            # Return None if there's any issue with album serialization
            return None

    def get_carbon_data(self, event):
        """
        Get carbon calculation data for the event.
        First check if it's stored in extra_data, otherwise calculate it.
        OPTIMIZATION: Skip expensive calculations for list views.
        """
        try:
            # Check if carbon calculation is already stored in extra_data
            if hasattr(event, "extra_data") and event.extra_data and "carbon_calculation" in event.extra_data:
                return event.extra_data["carbon_calculation"]

            # OPTIMIZATION: Check if this is being called from a list view context
            # If so, return minimal data to avoid expensive USDA API calls
            request = self.context.get("request")
            if request and hasattr(request, "resolver_match"):
                view_name = getattr(request.resolver_match, "url_name", "")
                if "list" in view_name or request.method == "GET" and "/history/" in request.path:
                    # Return minimal carbon data for list views
                    return {
                        "co2e": 0.0,
                        "efficiency_score": 50.0,
                        "usda_factors_based": False,
                        "verification_status": "not_calculated",
                        "calculation_method": "list_view_minimal",
                        "data_source": "Cached",
                        "recommendations": [],
                        "event_type": event.__class__.__name__.lower().replace("event", ""),
                        "timestamp": event.date.isoformat() if event.date else None,
                        "note": "Full calculation available in detail view",
                    }

            # Full calculation only for detail views or when explicitly requested
            from carbon.services.event_carbon_calculator import EventCarbonCalculator

            calculator = EventCarbonCalculator()

            # Determine event type and calculate accordingly
            if isinstance(event, ChemicalEvent):
                result = calculator.calculate_chemical_event_impact(event)
            elif isinstance(event, ProductionEvent):
                result = calculator.calculate_production_event_impact(event)
            elif isinstance(event, WeatherEvent):
                result = calculator.calculate_weather_event_impact(event)
            elif isinstance(event, EquipmentEvent):
                result = calculator.calculate_equipment_event_impact(event)
            elif isinstance(event, SoilManagementEvent):
                result = calculator.calculate_soil_management_event_impact(event)
            elif isinstance(event, PestManagementEvent):
                result = calculator.calculate_pest_management_event_impact(event)
            elif isinstance(event, BusinessEvent):
                result = calculator.calculate_business_event_impact(event)
            elif isinstance(event, GeneralEvent):
                # For general events, use standard minimal calculation
                result = {
                    "co2e": 0.1,
                    "efficiency_score": 50.0,
                    "usda_factors_based": False,
                    "verification_status": "estimated",
                    "calculation_method": "general_event_standard",
                    "data_source": "Industry Standards",
                    "recommendations": [],
                    "event_type": "general",
                    "timestamp": event.date.isoformat() if event.date else None,
                }
            else:
                # Fallback for unknown event types
                result = {
                    "co2e": 0.0,
                    "efficiency_score": 50.0,
                    "usda_factors_based": False,
                    "verification_status": "unknown",
                    "calculation_method": "unknown_event_type",
                    "data_source": "Unknown",
                    "recommendations": [],
                    "event_type": "unknown",
                    "timestamp": event.date.isoformat() if event.date else None,
                }

            return result

        except Exception as e:
            # Return fallback data if calculation fails
            return {
                "co2e": 0.0,
                "efficiency_score": 50.0,
                "usda_factors_based": False,
                "verification_status": "calculation_error",
                "calculation_method": "calculation_error",
                "data_source": "Error",
                "recommendations": [],
                "event_type": "error",
                "timestamp": event.date.isoformat() if event.date else None,
                "error": str(e),
            }


class UpdateChemicalEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChemicalEvent
        fields = "__all__"

    def validate(self, data):
        """
        Enhanced validation for chemical event structured fields with helpful error messages
        """
        # Get NPK percentages, handling None values
        nitrogen = data.get("nitrogen_percentage")
        phosphorus = data.get("phosphorus_percentage")
        potassium = data.get("potassium_percentage")

        # Individual field validation with detailed error messages
        if nitrogen is not None:
            if nitrogen < 0:
                raise serializers.ValidationError(
                    {
                        "nitrogen_percentage": "Nitrogen percentage cannot be negative. Please enter a value between 0-100."
                    }
                )
            if nitrogen > 100:
                raise serializers.ValidationError(
                    {
                        "nitrogen_percentage": "Nitrogen percentage cannot exceed 100%. Most fertilizers have nitrogen content between 0-46%."
                    }
                )

        if phosphorus is not None:
            if phosphorus < 0:
                raise serializers.ValidationError(
                    {
                        "phosphorus_percentage": "Phosphorus percentage cannot be negative. Please enter a value between 0-100."
                    }
                )
            if phosphorus > 100:
                raise serializers.ValidationError(
                    {
                        "phosphorus_percentage": "Phosphorus percentage cannot exceed 100%. Most fertilizers have phosphorus content between 0-20%."
                    }
                )

        if potassium is not None:
            if potassium < 0:
                raise serializers.ValidationError(
                    {
                        "potassium_percentage": "Potassium percentage cannot be negative. Please enter a value between 0-100."
                    }
                )
            if potassium > 100:
                raise serializers.ValidationError(
                    {
                        "potassium_percentage": "Potassium percentage cannot exceed 100%. Most fertilizers have potassium content between 0-60%."
                    }
                )

        # Validate total NPK only if all three values are provided
        if nitrogen is not None and phosphorus is not None and potassium is not None:
            total_npk = nitrogen + phosphorus + potassium
            if total_npk > 100:
                raise serializers.ValidationError(
                    {
                        "non_field_errors": [
                            f"Total NPK percentages cannot exceed 100%. Current total: {total_npk:.1f}%",
                            f"Breakdown: N={nitrogen}%, P={phosphorus}%, K={potassium}%",
                            "Tip: Common fertilizers like 20-10-10 have totals of 40%. Check your fertilizer label.",
                        ]
                    }
                )

            # Warning for suspiciously low totals (might indicate input error)
            if total_npk < 5 and total_npk > 0:
                # Note: This is a warning, not an error. We'll just add it to the response
                data["_validation_warning"] = (
                    f"Very low NPK total ({total_npk:.1f}%). Please verify the values are correct."
                )

        # EPA WPS Compliance Validation - 40 CFR 170.309
        restricted_use = data.get("restricted_use_pesticide", False)
        applicator_cert = data.get("applicator_certification")
        rei_hours = data.get("rei_hours")
        phi_days = data.get("phi_days")

        # Restricted Use Pesticides (RUPs) require certified applicator
        if restricted_use and not applicator_cert:
            raise serializers.ValidationError(
                {
                    "applicator_certification": (
                        "Applicator certification is required for Restricted Use Pesticides (RUPs) "
                        "per EPA Worker Protection Standard 40 CFR 170.309"
                    )
                }
            )

        # REI validation - must be non-negative
        if rei_hours is not None and rei_hours < 0:
            raise serializers.ValidationError({"rei_hours": "Restricted Entry Interval (REI) cannot be negative"})

        # PHI validation - must be non-negative
        if phi_days is not None and phi_days < 0:
            raise serializers.ValidationError({"phi_days": "Pre-Harvest Interval (PHI) cannot be negative"})

        return data


class ChemicalEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    chemical_type = serializers.SerializerMethodField()  # Add raw chemical type for frontend
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = ChemicalEvent
        fields = "__all__"

    def get_type(self, chemical_event):
        type_display = chemical_event.get_type_display()
        if type_display is None:
            return "event.chemical.unknown"
        return f"event.chemical.{type_display.lower().replace(' ', '_')}"

    def get_chemical_type(self, chemical_event):
        """Return raw chemical type code (FE, PE, FU, HE) for frontend processing"""
        return chemical_event.type  # Return raw database value: 'FU', 'PE', etc.

    def get_event_type(self, chemical_event):
        return CHEMICAL_EVENT_TYPE


class UpdateWeatherEventSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        print(f"🔥🔥 [UpdateWeatherEventSerializer.__init__] Serializer initialized! 🔥🔥")
        super().__init__(*args, **kwargs)

    class Meta:
        model = WeatherEvent
        fields = "__all__"

    def to_internal_value(self, data):
        # DEBUG: Log incoming data
        print(f"[UpdateWeatherEventSerializer.to_internal_value] Incoming data keys: {data.keys()}")
        print(f"[UpdateWeatherEventSerializer.to_internal_value] weather type: {data.get('type')}")
        if "water_deficit" in data:
            print(
                f"[UpdateWeatherEventSerializer.to_internal_value] water_deficit in data: {data.get('water_deficit')} (python type: {type(data.get('water_deficit')).__name__})"
            )

        event_type = data.get("type", None)
        if event_type is None:
            raise serializers.ValidationError({"type": ["This field is required."]}, code="required")
        data = data.copy()
        extra_data = {}
        if event_type == WeatherEvent.FROST:
            extra_data["lower_temperature"] = data.pop("lower_temperature", None)
            extra_data["way_of_protection"] = data.pop("way_of_protection", None)
        elif event_type == WeatherEvent.DROUGHT:
            water_deficit_value = data.pop("water_deficit", None)
            print(
                f"[UpdateWeatherEventSerializer.to_internal_value] DROUGHT - water_deficit popped: {water_deficit_value} (python type: {type(water_deficit_value).__name__})"
            )
            extra_data["water_deficit"] = water_deficit_value
        elif event_type == WeatherEvent.HAILSTORM:
            extra_data["weight"] = data.pop("weight", None)
            extra_data["diameter"] = data.pop("diameter", None)
            extra_data["duration"] = data.pop("duration", None)
            extra_data["way_of_protection"] = data.pop("way_of_protection", None)
        elif event_type == WeatherEvent.HIGH_TEMPERATURE:
            extra_data["highest_temperature"] = data.pop("highest_temperature", None)
            extra_data["start_date"] = data.pop("start_date", None)
            extra_data["end_date"] = data.pop("end_date", None)
        elif event_type == WeatherEvent.TROPICAL_STORM:
            extra_data["wind_speed"] = data.pop("wind_speed", None)
            extra_data["precipitation_amount"] = data.pop("precipitation_amount", None)
            extra_data["duration"] = data.pop("duration", None)
            extra_data["damage_assessment"] = data.pop("damage_assessment", None)
        elif event_type == WeatherEvent.HIGH_WINDS:
            extra_data["wind_speed"] = data.pop("wind_speed", None)
            extra_data["duration"] = data.pop("duration", None)
            extra_data["protection_measures"] = data.pop("protection_measures", None)
        elif event_type == WeatherEvent.HIGH_HUMIDITY:
            extra_data["humidity_level"] = data.pop("humidity_level", None)
            extra_data["duration"] = data.pop("duration", None)
            extra_data["crop_impact"] = data.pop("crop_impact", None)
        elif event_type == WeatherEvent.LOW_HUMIDITY:
            extra_data["humidity_level"] = data.pop("humidity_level", None)
            extra_data["duration"] = data.pop("duration", None)
            extra_data["crop_impact"] = data.pop("crop_impact", None)
        print(f"[UpdateWeatherEventSerializer.to_internal_value] extra_data before merge: {extra_data}")

        internal_value = super().to_internal_value(data)

        # Merge with existing extra_data to preserve carbon_calculation and other fields
        if hasattr(self, "instance") and self.instance and self.instance.extra_data:
            # Updating existing event - merge with current extra_data
            print(
                f"[UpdateWeatherEventSerializer.to_internal_value] Existing instance.extra_data: {self.instance.extra_data}"
            )
            merged_extra_data = {**self.instance.extra_data, **extra_data}
            print(f"[UpdateWeatherEventSerializer.to_internal_value] Merged extra_data: {merged_extra_data}")
            internal_value["extra_data"] = merged_extra_data
        else:
            # Creating new event - use new extra_data
            print(f"[UpdateWeatherEventSerializer.to_internal_value] No existing instance - using new extra_data")
            internal_value["extra_data"] = extra_data

        print(
            f"[UpdateWeatherEventSerializer.to_internal_value] Final internal_value['extra_data']: {internal_value['extra_data']}"
        )
        return internal_value

    def to_representation(self, instance):
        data = super().to_representation(instance)
        type = data.get("type", None)

        # Handle both model instances and dictionaries (during serialization)
        if hasattr(instance, "extra_data"):
            # Model instance case
            extra_data = instance.extra_data or {}
        else:
            # Dictionary/OrderedDict case (during serialization)
            extra_data = data.get("extra_data", {}) or {}

        if type == WeatherEvent.FROST:
            data["lower_temperature"] = extra_data.get("lower_temperature", 0)
            data["way_of_protection"] = extra_data.get("way_of_protection", "")
        elif type == WeatherEvent.DROUGHT:
            data["water_deficit"] = extra_data.get("water_deficit", 0)
        elif type == WeatherEvent.HAILSTORM:
            data["weight"] = extra_data.get("weight", 0)
            data["diameter"] = extra_data.get("diameter", 0)
            data["duration"] = extra_data.get("duration", 0)
            data["way_of_protection"] = extra_data.get("way_of_protection", "")
        elif type == WeatherEvent.HIGH_TEMPERATURE:
            data["highest_temperature"] = extra_data.get("highest_temperature", 0)
            # Convert date strings to datetime-local format for frontend datetime-local inputs
            start_date = extra_data.get("start_date", "")
            end_date = extra_data.get("end_date", "")
            # If dates are in YYYY-MM-DD format, add time component for datetime-local
            if start_date and len(start_date) == 10:  # YYYY-MM-DD format
                data["start_date"] = f"{start_date}T00:00"
            else:
                data["start_date"] = start_date
            if end_date and len(end_date) == 10:  # YYYY-MM-DD format
                data["end_date"] = f"{end_date}T00:00"
            else:
                data["end_date"] = end_date
        elif type == WeatherEvent.TROPICAL_STORM:
            data["wind_speed"] = extra_data.get("wind_speed", 0)
            data["precipitation_amount"] = extra_data.get("precipitation_amount", 0)
            data["duration"] = extra_data.get("duration", 0)
            data["damage_assessment"] = extra_data.get("damage_assessment", "")
        elif type == WeatherEvent.HIGH_WINDS:
            data["wind_speed"] = extra_data.get("wind_speed", 0)
            data["duration"] = extra_data.get("duration", 0)
            data["protection_measures"] = extra_data.get("protection_measures", "")
        elif type == WeatherEvent.HIGH_HUMIDITY:
            data["humidity_level"] = extra_data.get("humidity_level", 0)
            data["duration"] = extra_data.get("duration", 0)
            data["crop_impact"] = extra_data.get("crop_impact", "")
        elif type == WeatherEvent.LOW_HUMIDITY:
            data["humidity_level"] = extra_data.get("humidity_level", 0)
            data["duration"] = extra_data.get("duration", 0)
            data["crop_impact"] = extra_data.get("crop_impact", "")

        data.pop("extra_data", None)  # Use pop with default to avoid KeyError if key doesn't exist

        # Calculate production-level USDA verification status
        # Only calculate carbon data if instance is a model instance with an ID
        if hasattr(instance, "id") and instance.id:
            try:
                from carbon.models import CarbonEntry

                carbon_entries = CarbonEntry.objects.filter(production=instance)
                total_entries = carbon_entries.count()

                if total_entries > 0:
                    usda_verified_entries = carbon_entries.filter(usda_verified=True).count()
                    usda_factors_based_entries = carbon_entries.filter(usda_factors_based=True).count()

                    # Production is USDA verified if majority of entries are USDA verified or factors-based
                    production_usda_verified = usda_verified_entries > 0 or usda_factors_based_entries >= (
                        total_entries * 0.5
                    )

                    # Add to extra_data for frontend
                    if data.get("extra_data") is None:
                        data["extra_data"] = {}

                    data["extra_data"]["usda_verified"] = production_usda_verified
                    data["extra_data"]["usda_verification_details"] = {
                        "total_entries": total_entries,
                        "usda_verified_entries": usda_verified_entries,
                        "usda_factors_based_entries": usda_factors_based_entries,
                        "verification_percentage": (
                            round((usda_verified_entries / total_entries * 100), 1) if total_entries > 0 else 0
                        ),
                    }

                    # Calculate and add carbon totals for dashboard display
                    from django.db.models import Sum

                    total_emissions = (
                        carbon_entries.filter(type="emission").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0
                    )
                    total_offsets = (
                        carbon_entries.filter(type="offset").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0
                    )
                    carbon_score = 50  # Default score

                    # Calculate carbon score using the model method with industry benchmark
                    if total_emissions > 0 or total_offsets > 0:
                        from carbon.models import CarbonBenchmark, CarbonEntry

                        # Get industry benchmark for the production
                        industry_benchmark = None
                        try:
                            # Get crop type from product name
                            product_name = instance.product.name.lower() if instance.product else None
                            crop_type = None

                            if product_name:
                                # Map product names to benchmark crop types
                                crop_mapping = {
                                    "citrus (oranges)": "orange",
                                    "citrus (lemons)": "lemon",
                                    "strawberries": "strawberry",
                                    "almonds": "almond",
                                    "grapes": "grape",
                                    "apples": "apple",
                                    "avocados": "avocado",
                                    "tomatoes": "tomato",
                                    "corn": "corn",
                                    "soybeans": "soybean",
                                }

                                crop_type = crop_mapping.get(product_name, product_name.split()[0])

                            # Look for crop-specific benchmark
                            if crop_type:
                                benchmark = CarbonBenchmark.objects.filter(
                                    crop_type=crop_type,
                                    year=instance.start_date.year if instance.start_date else 2025,
                                    usda_verified=True,
                                ).first()

                                if benchmark:
                                    # Convert per-kg benchmark to total production benchmark
                                    # Estimate production weight (default 1000kg if unknown)
                                    estimated_production_kg = 1000  # Default estimate
                                    industry_benchmark = benchmark.average_emissions * estimated_production_kg

                        except Exception as e:
                            print(f"Error getting benchmark for production {instance.id}: {e}")

                        carbon_score = CarbonEntry.calculate_carbon_score(
                            total_emissions, total_offsets, industry_benchmark
                        )

                    data["extra_data"]["total_emissions"] = float(total_emissions)
                    data["extra_data"]["total_offsets"] = float(total_offsets)
                    data["extra_data"]["carbon_score"] = carbon_score
                else:
                    # No carbon entries, so not USDA verified
                    if data.get("extra_data") is None:
                        data["extra_data"] = {}
                    data["extra_data"]["usda_verified"] = False
                    data["extra_data"]["total_emissions"] = 0.0
                    data["extra_data"]["total_offsets"] = 0.0
                    data["extra_data"]["carbon_score"] = 50

            except Exception as e:
                instance_id = getattr(instance, "id", "unknown")
                print(f"Error calculating USDA verification for production {instance_id}: {e}")
                # Fallback to existing logic
                if data.get("extra_data") is None:
                    data["extra_data"] = {}
                data["extra_data"]["usda_verified"] = False
                data["extra_data"]["total_emissions"] = 0.0
                data["extra_data"]["total_offsets"] = 0.0
                data["extra_data"]["carbon_score"] = 50

        return data

    def update(self, instance, validated_data):
        # DEBUG: Log what we're about to save
        print(f"[UpdateWeatherEventSerializer.update] Instance ID: {instance.id}")
        print(f"[UpdateWeatherEventSerializer.update] validated_data type: {type(validated_data)}")
        print(f"[UpdateWeatherEventSerializer.update] validated_data keys: {validated_data.keys()}")
        if "extra_data" in validated_data:
            print(f"[UpdateWeatherEventSerializer.update] validated_data['extra_data']: {validated_data['extra_data']}")

        # CRITICAL FIX: Set history and created_by from request (same as ViewSet logic)
        request = self.context.get("request")
        if request and not instance.history:
            from product.models import Parcel

            parcels = request.POST.getlist("parcels", None) or request.data.get("parcels", [])
            print(f"[UpdateWeatherEventSerializer.update] parcels from request: {parcels}")

            if parcels:
                parcel_id = parcels[0] if isinstance(parcels, list) else parcels
                try:
                    parcel = Parcel.objects.select_related("current_history").get(id=int(parcel_id))
                    if parcel.current_history:
                        validated_data["history"] = parcel.current_history
                        validated_data["created_by"] = request.user
                        print(f"[UpdateWeatherEventSerializer.update] Set history to: {parcel.current_history.id}")
                        print(f"[UpdateWeatherEventSerializer.update] Set created_by to: {request.user}")

                        # Calculate index matching ViewSet logic (only if not already set)
                        if not instance.index:
                            history = parcel.current_history
                            index = (
                                history.history_weatherevent_events.count()
                                + history.history_chemicalevent_events.count()
                                + history.history_generalevent_events.count()
                                + history.history_productionevent_events.count()
                                + history.history_equipmentevent_events.count()
                                + history.history_soilmanagementevent_events.count()
                                + history.history_pestmanagementevent_events.count()
                                + history.history_businessevent_events.count()
                            ) + 1
                            validated_data["index"] = index
                            print(f"[UpdateWeatherEventSerializer.update] Set index to: {index}")
                except Exception as e:
                    print(f"[UpdateWeatherEventSerializer.update] Error setting history: {e}")

        # Handle album images from S3 URLs (modern approach)
        album_images = request.data.get("album_images", []) if request else []

        if album_images:
            print(f"[UpdateWeatherEventSerializer.update] Processing {len(album_images)} album images from S3 URLs")
            gallery = instance.album
            if gallery is None:
                gallery = Gallery.objects.create()
                print(f"[UpdateWeatherEventSerializer.update] Created new gallery: {gallery.id}")

            # Create GalleryImage records from S3 URLs
            for image_url in album_images:
                # Extract S3 key from URL if possible
                s3_key = image_url.split("/")[-1] if "/" in image_url else None
                gallery_image = gallery.images.create(image_url=image_url, s3_key=s3_key)
                print(
                    f"[UpdateWeatherEventSerializer.update] Created gallery image {gallery_image.id} with URL: {image_url}"
                )

            validated_data["album"] = gallery

        # Legacy support: Handle file uploads (will be deprecated)
        elif request and request.FILES:
            album_data = request.FILES
            gallery = instance.album
            if gallery is None:
                gallery = Gallery.objects.create()
            for image_data in album_data.getlist("album[images]"):
                gallery_image = gallery.images.create(image=image_data)
                gallery_image.save()
            validated_data["album"] = gallery

        # Call parent update
        updated_instance = super().update(instance, validated_data)

        # DEBUG: Log what was saved
        print(f"[UpdateWeatherEventSerializer.update] After save, extra_data: {updated_instance.extra_data}")

        return updated_instance

    def create(self, validated_data):
        print(f"🚨🚨 [UpdateWeatherEventSerializer.create] SERIALIZER CREATE METHOD CALLED 🚨🚨")
        print(f"[UpdateWeatherEventSerializer.create] Starting custom create method")
        # Handle album images from S3 URLs (modern approach)
        request = self.context.get("request")
        album_images = request.data.get("album_images", []) if request else []

        if album_images:
            print(f"[UpdateWeatherEventSerializer.create] Processing {len(album_images)} album images from S3 URLs")
            gallery = Gallery.objects.create()

            # Create GalleryImage records from S3 URLs
            for image_url in album_images:
                # Extract S3 key from URL if possible
                s3_key = image_url.split("/")[-1] if "/" in image_url else None
                gallery_image = gallery.images.create(image_url=image_url, s3_key=s3_key)
                print(
                    f"[UpdateWeatherEventSerializer.create] Created gallery image {gallery_image.id} with URL: {image_url}"
                )

            validated_data["album"] = gallery

        # Legacy support: Handle file uploads (will be deprecated)
        elif request and request.FILES:
            album_data = request.FILES
            gallery = Gallery.objects.create()
            for image_data in album_data.getlist("album[images]"):
                gallery_image = gallery.images.create(image=image_data)
                gallery_image.save()
            validated_data["album"] = gallery

        # CRITICAL FIX: Set history and created_by from ViewSet logic
        # This was previously done in ViewSet.perform_create but custom serializer.create bypasses that
        if request:
            from product.models import Parcel

            parcels = request.POST.getlist("parcels", None) or request.data.get("parcels", [])
            print(f"[UpdateWeatherEventSerializer.create] parcels from request: {parcels}")

            if parcels:
                # Get the first parcel's current_history (matching ViewSet logic)
                parcel_id = parcels[0] if isinstance(parcels, list) else parcels
                try:
                    parcel = Parcel.objects.select_related("current_history").get(id=int(parcel_id))
                    if parcel.current_history:
                        print(
                            f"[UpdateWeatherEventSerializer.create] Setting history to {parcel.current_history.id} and created_by to {request.user.id}"
                        )
                        validated_data["history"] = parcel.current_history
                        validated_data["created_by"] = request.user

                        # Calculate index (matching ViewSet logic)
                        history = parcel.current_history
                        index = (
                            history.history_weatherevent_events.count()
                            + history.history_chemicalevent_events.count()
                            + history.history_generalevent_events.count()
                            + history.history_productionevent_events.count()
                            + history.history_equipmentevent_events.count()
                            + history.history_soilmanagementevent_events.count()
                            + history.history_pestmanagementevent_events.count()
                            + history.history_businessevent_events.count()
                        ) + 1
                        validated_data["index"] = index
                        print(f"[UpdateWeatherEventSerializer.create] Set index to {index}")
                    else:
                        print(
                            f"[UpdateWeatherEventSerializer.create] WARNING: Parcel {parcel_id} has no current_history"
                        )
                except (Parcel.DoesNotExist, ValueError) as e:
                    print(f"[UpdateWeatherEventSerializer.create] ERROR: Could not find parcel {parcel_id}: {e}")

        return super().create(validated_data)


class WeatherEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = WeatherEvent
        fields = "__all__"

    def get_type(self, weather_event):
        type_display = weather_event.get_type_display()
        if type_display is None:
            return "event.weather.unknown"
        return f"event.weather.{type_display.lower().replace(' ', '_')}"

    def get_event_type(self, weather_event):
        return WEATHER_EVENT_TYPE


class UpdateProductionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductionEvent
        fields = "__all__"

    def validate(self, data):
        """
        Enhanced validation for production event structured fields with helpful error messages
        """
        area_covered = data.get("area_covered")
        yield_quantity = data.get("yield_quantity")
        fuel_consumed = data.get("fuel_consumed")
        equipment_hours = data.get("equipment_hours")
        transportation_distance = data.get("transportation_distance")
        area_unit = data.get("area_unit", "ha")
        yield_unit = data.get("yield_unit", "kg")

        # Enhanced area_covered validation
        if area_covered is not None and area_covered <= 0:
            raise serializers.ValidationError(
                {
                    "area_covered": [
                        "Area covered must be greater than 0.",
                        "Please enter the actual area where the production activity took place.",
                        f"Tip: Small plots are typically 0.1-1 {area_unit}, medium farms 1-10 {area_unit}, large farms 10+ {area_unit}.",
                    ]
                }
            )

        # Enhanced yield_quantity validation
        if yield_quantity is not None and yield_quantity < 0:
            raise serializers.ValidationError(
                {
                    "yield_quantity": [
                        "Yield quantity cannot be negative.",
                        "Please enter the actual amount produced or harvested.",
                        f"Tip: If no yield yet (e.g., planting), you can leave this field empty.",
                    ]
                }
            )

        # Enhanced fuel_consumed validation
        if fuel_consumed is not None and fuel_consumed < 0:
            raise serializers.ValidationError(
                {
                    "fuel_consumed": [
                        "Fuel consumed cannot be negative.",
                        "Please enter the actual fuel used during the production activity.",
                        "Tip: Small tractors typically use 5-15L/hr, large tractors 20-40L/hr.",
                    ]
                }
            )

        # Enhanced equipment_hours validation
        if equipment_hours is not None and equipment_hours < 0:
            raise serializers.ValidationError(
                {
                    "equipment_hours": [
                        "Equipment hours cannot be negative.",
                        "Please enter the actual time equipment was operating.",
                        "Tip: Enter decimal hours (e.g., 1.5 for 1 hour 30 minutes).",
                    ]
                }
            )

        # Enhanced transportation_distance validation
        if transportation_distance is not None and transportation_distance < 0:
            raise serializers.ValidationError(
                {
                    "transportation_distance": [
                        "Transportation distance cannot be negative.",
                        "Please enter the distance from farm to processing/market.",
                        "Tip: Local markets 0-50km, regional 50-200km, long distance 200+ km.",
                    ]
                }
            )

        # Enhanced maximum hours validation
        if equipment_hours is not None and equipment_hours > 24:
            raise serializers.ValidationError(
                {
                    "equipment_hours": [
                        "Equipment hours cannot exceed 24 hours per day for a single event.",
                        "Please enter hours for this specific operation only.",
                        "Tip: For multi-day operations, create separate events for each day.",
                    ]
                }
            )

        # Business logic validation with farmer-friendly messages
        if area_covered and area_covered > 500:  # Very large area
            raise serializers.ValidationError(
                {
                    "area_covered": [
                        f"Area coverage ({area_covered} {area_unit}) is very large.",
                        "Please verify this is correct for a single production event.",
                        "Tip: Consider breaking large areas into smaller, manageable sections.",
                    ]
                }
            )

        # Yield efficiency check
        if yield_quantity and area_covered and yield_quantity > 0 and area_covered > 0:
            yield_per_hectare = float(yield_quantity) / float(area_covered)
            if yield_unit in ["kg", "tons"] and yield_per_hectare > 50000:  # 50 tons per hectare
                raise serializers.ValidationError(
                    {
                        "yield_quantity": [
                            f"Yield rate ({yield_per_hectare:.1f} {yield_unit}/ha) seems very high.",
                            "Please verify the yield quantity and area are correct.",
                            "Tip: Average yields vary by crop - check local agricultural statistics.",
                        ]
                    }
                )

        return data


class ProductionEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = ProductionEvent
        fields = "__all__"

    def get_type(self, production_event):
        type_display = production_event.get_type_display()
        if type_display is None:
            return "event.production.unknown"
        return f"event.production.{type_display.lower().replace(' ', '_')}"

    def get_event_type(self, production_event):
        return PRODUCTION_EVENT_TYPE


class UpdateGeneralEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralEvent
        fields = "__all__"


class GeneralEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = GeneralEvent
        fields = "__all__"

    def get_type(self, general_event):
        return f"event.general.{general_event.name.lower().replace(' ', '_')}"

    def get_event_type(self, general_event):
        return GENERAL_EVENT_TYPE


class OptimizedHistoryListSerializer(serializers.ModelSerializer):
    """
    Optimized serializer for dashboard list view that avoids expensive operations
    like get_events() and get_members() that cause N+1 queries.
    """

    product = serializers.SerializerMethodField()
    parcel = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    crop_type = serializers.SerializerMethodField()

    class Meta:
        model = History
        fields = [
            "id",
            "start_date",
            "finish_date",
            "name",
            "published",
            "earning",
            "parcel",
            "members",
            "product",
            "qr_code",
            "reputation",
            "is_outdoor",
            "age_of_plants",
            "number_of_plants",
            "soil_ph",
            "crop_type",
            "transparency_score",  # Include for transparency calculations
            "extra_data",  # Include for carbon data
        ]
        read_only_fields = ["id"]

    def get_product(self, history):
        return history.product.name if history.product else None

    def get_parcel(self, history):
        return history.parcel.name if history.parcel else None

    def get_crop_type(self, history):
        if history.crop_type:
            return {
                "id": history.crop_type.id,
                "name": history.crop_type.name,
                "category": history.crop_type.category,
                "slug": history.crop_type.slug,
            }
        return None

    def get_members(self, history):
        """
        Lightweight members list that checks cached members first, then falls back to involved users.
        Returns cached members from extra_data if available, otherwise gets involved users.
        """
        # Check if we have cached member data in extra_data
        if history.extra_data and isinstance(history.extra_data, dict):
            cached_members = history.extra_data.get("cached_members", [])
            if cached_members:
                return [
                    {
                        "id": member.get("id"),
                        "first_name": member.get("first_name", ""),
                        "last_name": member.get("last_name", ""),
                        "image": member.get("image"),
                    }
                    for member in cached_members[:3]  # Limit to 3 members
                ]

        # Fallback to involved users when no cached members
        try:
            from users.serializers import BasicUserSerializer

            user_ids = history.get_involved_users()
            if user_ids:
                from users.models import User

                members = User.objects.filter(id__in=user_ids).order_by("first_name")[:3]
                return BasicUserSerializer(members, many=True).data
        except Exception as e:
            # Log error but don't fail the serialization
            print(f"Error getting members for history {history.id}: {str(e)}")

        return []

    def to_representation(self, instance):
        """
        Override to add computed USDA verification status and enhanced production info
        """
        data = super().to_representation(instance)

        # Calculate production-level USDA verification status
        try:
            from carbon.models import CarbonEntry

            carbon_entries = CarbonEntry.objects.filter(production=instance)
            total_entries = carbon_entries.count()

            if total_entries > 0:
                usda_verified_entries = carbon_entries.filter(usda_verified=True).count()
                usda_factors_based_entries = carbon_entries.filter(usda_factors_based=True).count()

                # Production is USDA verified if majority of entries are USDA verified or factors-based
                production_usda_verified = usda_verified_entries > 0 or usda_factors_based_entries >= (
                    total_entries * 0.5
                )

                # Add to extra_data for frontend
                if data.get("extra_data") is None:
                    data["extra_data"] = {}

                data["extra_data"]["usda_verified"] = production_usda_verified
                data["extra_data"]["usda_verification_details"] = {
                    "total_entries": total_entries,
                    "usda_verified_entries": usda_verified_entries,
                    "usda_factors_based_entries": usda_factors_based_entries,
                    "verification_percentage": (
                        round((usda_verified_entries / total_entries * 100), 1) if total_entries > 0 else 0
                    ),
                }

                # Calculate and add carbon totals for dashboard display
                from django.db.models import Sum

                total_emissions = (
                    carbon_entries.filter(type="emission").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0
                )
                total_offsets = (
                    carbon_entries.filter(type="offset").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0
                )
                carbon_score = 50  # Default score

                # Calculate carbon score using the model method with industry benchmark
                if total_emissions > 0 or total_offsets > 0:
                    from carbon.models import CarbonBenchmark, CarbonEntry

                    # Get industry benchmark for the production
                    industry_benchmark = None
                    try:
                        # Get crop type from product name
                        product_name = instance.product.name.lower() if instance.product else None
                        crop_type = None

                        if product_name:
                            # Map product names to benchmark crop types
                            crop_mapping = {
                                "citrus (oranges)": "orange",
                                "citrus (lemons)": "lemon",
                                "strawberries": "strawberry",
                                "almonds": "almond",
                                "grapes": "grape",
                                "apples": "apple",
                                "avocados": "avocado",
                                "tomatoes": "tomato",
                                "corn": "corn",
                                "soybeans": "soybean",
                            }

                            crop_type = crop_mapping.get(product_name, product_name.split()[0])

                        # Look for crop-specific benchmark
                        if crop_type:
                            benchmark = CarbonBenchmark.objects.filter(
                                crop_type=crop_type,
                                year=instance.start_date.year if instance.start_date else 2025,
                                usda_verified=True,
                            ).first()

                            if benchmark:
                                # Convert per-kg benchmark to total production benchmark
                                # Estimate production weight (default 1000kg if unknown)
                                estimated_production_kg = 1000  # Default estimate
                                industry_benchmark = benchmark.average_emissions * estimated_production_kg

                    except Exception as e:
                        print(f"Error getting benchmark for production {instance.id}: {e}")

                    carbon_score = CarbonEntry.calculate_carbon_score(
                        total_emissions, total_offsets, industry_benchmark
                    )

                data["extra_data"]["total_emissions"] = float(total_emissions)
                data["extra_data"]["total_offsets"] = float(total_offsets)
                data["extra_data"]["carbon_score"] = carbon_score
            else:
                # No carbon entries, so not USDA verified
                if data.get("extra_data") is None:
                    data["extra_data"] = {}
                data["extra_data"]["usda_verified"] = False
                data["extra_data"]["total_emissions"] = 0.0
                data["extra_data"]["total_offsets"] = 0.0
                data["extra_data"]["carbon_score"] = 50

        except Exception as e:
            print(f"Error calculating USDA verification for production {instance.id}: {e}")
            # Fallback to existing logic
            if data.get("extra_data") is None:
                data["extra_data"] = {}
            data["extra_data"]["usda_verified"] = False
            data["extra_data"]["total_emissions"] = 0.0
            data["extra_data"]["total_offsets"] = 0.0
            data["extra_data"]["carbon_score"] = 50

        # Enhance production name to be more descriptive and unique
        try:
            if data.get("extra_data") is None:
                data["extra_data"] = {}

            # Generate a more meaningful production name
            product_name = instance.product.name if instance.product else "Agricultural Product"
            year = instance.start_date.year if instance.start_date else "2025"

            # Get production method from extra_data
            production_method = data["extra_data"].get("production_method", "conventional")

            # Create unique name based on product and method (only if not conventional)
            if production_method != "conventional":
                enhanced_name = f"{production_method.title()} {product_name} {year}"
            else:
                enhanced_name = f"{product_name} {year}"

            # Override the name field with enhanced version
            data["name"] = enhanced_name

            # Store original name in extra_data for reference
            data["extra_data"]["original_name"] = instance.name

        except Exception as e:
            print(f"Error enhancing production name for {instance.id}: {e}")

        return data


class HistorySerializer(serializers.ModelSerializer):
    events = serializers.SerializerMethodField()
    certificate_percentage = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    product = serializers.SerializerMethodField()
    parcel = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    operator = BasicUserSerializer(read_only=True)
    crop_type = serializers.SerializerMethodField()

    class Meta:
        model = History
        fields = [
            "id",
            "start_date",
            "finish_date",
            "name",
            "published",
            "events",
            "earning",
            "parcel",
            "members",
            "certificate_percentage",
            "product",
            "qr_code",
            "reputation",
            "images",
            "is_outdoor",
            "age_of_plants",
            "number_of_plants",
            "soil_ph",
            "operator",
            "crop_type",
            # Harvest details for consumer transparency
            "lot_id",
            "production_amount",
            "production_unit",
            "quality_grade",
            "harvest_method",
            "description",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "certificate_percentage"]

    def get_product(self, history):
        return history.product.name if history.product else None

    def get_events(self, history):
        return history.get_events()

    def get_parcel(self, history):
        return history.parcel.name if history.parcel else None

    def get_certificate_percentage(self, history):
        return history.certificate_percentage

    def get_crop_type(self, history):
        if history.crop_type:
            return {
                "id": history.crop_type.id,
                "name": history.crop_type.name,
                "category": history.crop_type.category,
                "slug": history.crop_type.slug,
            }
        return None

    def get_images(self, history):
        try:
            request = self.context.get("request")
            images = []

            # Get images from production's own album
            if history.album:
                for image in history.album.images.all():
                    # Prefer image_url (S3 URL) over file field
                    if image.image_url:
                        images.append(image.image_url)
                    elif image.image:
                        image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                        images.append(image_url)

            # Get images from all associated events
            # Chemical Events
            for event in history.history_chemicalevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Production Events
            for event in history.history_productionevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Weather Events
            for event in history.history_weatherevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # General Events
            for event in history.history_generalevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Equipment Events
            for event in history.history_equipmentevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Soil Management Events
            for event in history.history_soilmanagementevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Pest Management Events
            for event in history.history_pestmanagementevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Business Events
            for event in history.history_businessevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Remove duplicates while preserving order
            unique_images = []
            for img in images:
                if img not in unique_images:
                    unique_images.append(img)

            return unique_images

        except Exception as e:
            print(f"Error getting images: {str(e)}")
            return []

    def get_members(self, history):
        """
        Get production members from involved users, with proper serialization.
        """
        try:
            # First check if we have cached members in extra_data
            if history.extra_data and isinstance(history.extra_data, dict):
                cached_members = history.extra_data.get("cached_members", [])
                if cached_members:
                    return cached_members[:3]  # Limit to 3 members

            # Fallback to querying involved users
            user_ids = history.get_involved_users()
            if user_ids:
                members = User.objects.filter(id__in=user_ids).order_by("first_name")[:3]
                return BasicUserSerializer(members, many=True).data

            return []
        except Exception as e:
            print(f"Error getting members for history {history.id}: {str(e)}")
            return []


class ListHistoryClassSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    parcel = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()

    class Meta:
        model = HistoryScan
        fields = [
            "id",
            "date",
            "product",
            "location",
            "parcel",
            "comment",
        ]

    def get_date(self, history_scan):
        return history_scan.date.strftime("%m/%d/%Y")

    def get_product(self, history_scan):
        return history_scan.history.product.name if history_scan.history.product else None

    def get_location(self, history_scan):
        if history_scan.city is None and history_scan.country is None:
            return "-"
        elif history_scan.city is not None:
            return f"{history_scan.city}"
        elif history_scan.country is not None:
            return f"{history_scan.country}"
        return f"{history_scan.city if history_scan.city is not None else '-'}, {history_scan.country if history_scan.country is not None else '-'}"

    def get_parcel(self, history_scan):
        return history_scan.history.parcel.name if history_scan.history.parcel else None


class PublicProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["name"]


class PublicEstablishmentSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()

    class Meta:
        model = Establishment
        fields = ["name", "description", "location"]

    def get_location(self, establishment):
        return establishment.get_location()


class PublicParcelSerializer(serializers.ModelSerializer):
    establishment = PublicEstablishmentSerializer()

    class Meta:
        model = Parcel
        fields = ["name", "polygon", "map_metadata", "establishment", "agricultural_details"]


class PublicHistoryListSerializer(serializers.ModelSerializer):
    product = PublicProductSerializer()
    image = serializers.SerializerMethodField()

    class Meta:
        model = History
        fields = ["id", "name", "product", "reputation", "image"]

    def get_image(self, history):
        if history.album is None or history.album.images.first() is None:
            return None
        request = self.context.get("request")
        image = history.album.images.first() if history.album else None
        return request.build_absolute_uri(image.image.url) if request else image.image.url


class PublicHistorySerializer(serializers.ModelSerializer):
    events = serializers.SerializerMethodField()
    certificate_percentage = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()
    parcel = PublicParcelSerializer()
    product = PublicProductSerializer()
    history_scan = serializers.SerializerMethodField()
    similar_histories = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    qr_code = serializers.SerializerMethodField()

    class Meta:
        model = History
        fields = [
            "id",
            "start_date",
            "finish_date",
            "name",
            "events",
            "certificate_percentage",
            "product",
            "reputation",
            "company",
            "parcel",
            "history_scan",
            "qr_code",
            "images",
            "similar_histories",
            # Harvest details for consumer transparency
            "lot_id",
            "production_amount",
            "production_unit",
            "quality_grade",
            "harvest_method",
        ]

    def _get_chemical_type_with_fallback(self, event):
        """
        Get chemical type with multiple fallback strategies.
        1. Use event.type if set (FE, PE, FU, HE)
        2. Infer from commercial_name (most reliable for incorrectly typed events)
        3. Extract from carbon calculation data if available
        """
        # Primary: Use database type field if set
        if event.type and event.type in ["FE", "PE", "FU", "HE"]:
            return event.type

        # Fallback 1: Infer from commercial name (prioritized over carbon calc due to data quality)
        commercial_name = (event.commercial_name or "").lower()

        # Check most specific terms first to avoid mismatches
        if any(word in commercial_name for word in ["fungicide", "copper"]):
            return "FU"
        elif any(word in commercial_name for word in ["pesticide", "insecticide", "neem"]):
            return "PE"
        elif any(word in commercial_name for word in ["herbicide", "weed", "glyphosate"]):
            return "HE"
        elif "roundup" in commercial_name and "pesticide" in commercial_name:
            return "PE"  # Pesticide Roundup should be pesticide, not herbicide
        elif any(
            word in commercial_name for word in ["fertilizer", "nutrient", "npk", "nitrogen", "phosphorus", "potassium"]
        ):
            return "FE"
        elif "roundup" in commercial_name:
            return "HE"  # Pure roundup is typically herbicide

        # Fallback 2: Extract from carbon calculation data (if name inference fails)
        if hasattr(event, "extra_data") and event.extra_data:
            carbon_data = event.extra_data.get("carbon_calculation", {})
            breakdown = carbon_data.get("breakdown", {})
            carbon_chemical_type = breakdown.get("chemical_type")
            if carbon_chemical_type and carbon_chemical_type in ["FE", "PE", "FU", "HE"]:
                return carbon_chemical_type

        # Final fallback: return None (will show as generic "chemical application")
        return None

    def get_events(self, history):
        """
        OPTIMIZED: Get events without triggering carbon calculations.
        This prevents USDA API calls for public history display.
        """
        try:
            # Get basic event data without expensive carbon calculations
            events_data = []

            # Get events using minimal queries with correct related names
            chemical_events = history.history_chemicalevent_events.only(
                "id",
                "date",
                "description",
                "commercial_name",
                "volume",
                "concentration",
                "type",
                "area",
                "way_of_application",
                "weather_conditions",
                "application_timing",
                "target_pest_disease",
                "extra_data",
            )
            production_events = history.history_productionevent_events.only(
                "id", "date", "description", "type", "observation"
            )
            weather_events = history.history_weatherevent_events.only(
                "id", "date", "description", "type", "observation", "extra_data"
            )
            equipment_events = history.history_equipmentevent_events.only(
                "id", "date", "description", "type", "equipment_name"
            )
            soil_events = history.history_soilmanagementevent_events.only(
                "id",
                "date",
                "description",
                "type",
                "amendment_type",
                "name",
                "soil_ph",
                "organic_matter_percentage",
                "amendment_amount",
                "test_results",
                "area_covered",
                "area_unit",
                "fuel_consumed",
                "fuel_unit",
                "equipment_hours",
                "extra_data",
                "working_depth",
                "depth_unit",
                # 🚨 CRITICAL FIX: Add missing fields that preview shows but ProductDetail was missing
                "transportation_distance",
                "transportation_unit",
                "production_efficiency",
                "soil_texture",
                "soil_moisture",
                "weather_conditions",
                "temperature_range",
                "equipment_used",
            )
            pest_events = history.history_pestmanagementevent_events.only(
                "id", "date", "description", "type", "pest_species"
            )
            general_events = history.history_generalevent_events.only(
                "id",
                "date",
                "description",
                "name",
                "observation",
                "activity_type",
                "activity_name",
                "duration",
                "people_involved",
            )
            business_events = history.history_businessevent_events.only(
                "id", "date", "description", "name", "observation", "business_type", "certification_type"
            )

            # Create lightweight event data without carbon calculations
            for event in chemical_events:
                # Count photos from event album
                photo_count = 0
                album_data = None
                if hasattr(event, "album") and event.album:
                    photo_count = event.album.images.count()
                    # Serialize album data for frontend
                    album_data = {
                        "id": event.album.id,
                        "images": [
                            {
                                "id": img.id,
                                "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                                "caption": getattr(img, "caption", "") or "",
                                "created_at": (
                                    img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""
                                ),
                            }
                            for img in event.album.images.all()
                        ],
                    }

                events_data.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Chemical Application",
                        "observation": getattr(event, "observation", ""),
                        "type": "chemical",
                        "chemical_type": self._get_chemical_type_with_fallback(
                            event
                        ),  # Expose raw chemical type (FE, PE, FU, HE) for frontend processing
                        "certified": getattr(event, "certified", True),
                        "index": getattr(event, "index", 0),
                        "volume": event.volume,
                        "concentration": event.concentration,
                        "area": getattr(event, "area", None),
                        "equipment": event.commercial_name,
                        "photo_count": photo_count,
                        "commercial_name": event.commercial_name,
                        "album": album_data,
                        # Additional transparency fields
                        "way_of_application": getattr(event, "way_of_application", None),
                        "weather_conditions": getattr(event, "weather_conditions", None),
                        "application_timing": getattr(event, "application_timing", None),
                        "target_pest_disease": getattr(event, "target_pest_disease", None),
                        "extra_data": getattr(event, "extra_data", None),
                    }
                )

            for event in production_events:
                # Count photos from event album
                photo_count = 0
                album_data = None
                if hasattr(event, "album") and event.album:
                    photo_count = event.album.images.count()
                    # Serialize album data for frontend
                    album_data = {
                        "id": event.album.id,
                        "images": [
                            {
                                "id": img.id,
                                "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                                "caption": getattr(img, "caption", "") or "",
                                "created_at": (
                                    img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""
                                ),
                            }
                            for img in event.album.images.all()
                        ],
                    }

                events_data.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Production Activity",
                        "observation": event.observation or "",
                        "type": "production",
                        "certified": getattr(event, "certified", True),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": None,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                    }
                )

            for event in weather_events:
                # Count photos from event album
                photo_count = 0
                album_data = None
                if hasattr(event, "album") and event.album:
                    photo_count = event.album.images.count()
                    # Serialize album data for frontend
                    album_data = {
                        "id": event.album.id,
                        "images": [
                            {
                                "id": img.id,
                                "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                                "caption": getattr(img, "caption", "") or "",
                                "created_at": (
                                    img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""
                                ),
                            }
                            for img in event.album.images.all()
                        ],
                    }

                events_data.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Weather Event",
                        "observation": event.observation or "",
                        "type": getattr(
                            event, "type", "weather"
                        ),  # 🌦️ PRESERVE WEATHER TYPE: Use actual weather type (FR, DR, etc.) instead of generic "weather"
                        "certified": getattr(event, "certified", True),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": None,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                        # 🌦️ WEATHER FIELDS: Add missing extra_data for weather-specific fields unification
                        "extra_data": getattr(event, "extra_data", None),
                    }
                )

            for event in equipment_events:
                # Count photos from event album
                photo_count = 0
                album_data = None
                if hasattr(event, "album") and event.album:
                    photo_count = event.album.images.count()
                    # Serialize album data for frontend
                    album_data = {
                        "id": event.album.id,
                        "images": [
                            {
                                "id": img.id,
                                "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                                "caption": getattr(img, "caption", "") or "",
                                "created_at": (
                                    img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""
                                ),
                            }
                            for img in event.album.images.all()
                        ],
                    }

                events_data.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Equipment Use",
                        "observation": getattr(event, "observation", ""),
                        "type": "equipment",  # FIXED: Always return "equipment" as main type for Equipment events
                        "certified": getattr(event, "certified", True),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": event.equipment_name,
                        # CRITICAL: Add Equipment subtype and operation name for frontend display
                        "operation_type": getattr(event, "type", None),  # Equipment subtype (MN, RE, CA, FC, BD, EI)
                        "name": getattr(event, "name", None),  # Operation name for title display
                        "operation_name": getattr(event, "name", None),  # Frontend compatibility alias
                        # COMPLETE EQUIPMENT FIELDS - Handle both legacy and new field names
                        "equipment_type": getattr(event, "equipment_type_structured", None)
                        or getattr(event, "equipment_name", None),  # tractor, harvester, etc.
                        "fuel_consumed": getattr(event, "fuel_consumed", None)
                        or getattr(event, "fuel_amount", None),  # Check both new and legacy
                        "fuel_type": getattr(event, "fuel_type", None),  # diesel, gasoline, etc.
                        "fuel_unit": getattr(event, "fuel_unit", "L"),  # L, gal, kg, kWh
                        "hours_operated": getattr(event, "hours_operated", None)
                        or getattr(event, "hours_used", None),  # Check both new and legacy
                        "area_worked": getattr(event, "area_worked", None)
                        or getattr(event, "area_covered", None),  # Check both new and legacy (string to numeric)
                        "area_unit": getattr(event, "area_unit", "ha"),  # ha, ac, m2
                        "operation_efficiency": getattr(event, "operation_efficiency", None),  # high, normal, low
                        # 🚨 CRITICAL FIX: Add name field for equipment operation name
                        "name": getattr(event, "name", None) or getattr(event, "equipment_name", None),
                        # Add operation_type to map Equipment subtype for description generation
                        "operation_type": getattr(event, "type", None),  # FC, MN, RE, etc.
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                    }
                )

            for event in soil_events:
                # Count photos from event album
                photo_count = 0
                album_data = None
                if hasattr(event, "album") and event.album:
                    photo_count = event.album.images.count()
                    # Serialize album data for frontend
                    album_data = {
                        "id": event.album.id,
                        "images": [
                            {
                                "id": img.id,
                                "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                                "caption": getattr(img, "caption", "") or "",
                                "created_at": (
                                    img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""
                                ),
                            }
                            for img in event.album.images.all()
                        ],
                    }

                events_data.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Soil Management",
                        "observation": "",  # Soil management events don't have observation field
                        "type": "soil_management",
                        "certified": getattr(event, "certified", True),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area_covered", None),
                        "equipment": event.amendment_type,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                        # 🌱 SOIL MANAGEMENT SPECIFIC FIELDS - Raw data for frontend processing
                        "name": getattr(event, "name", None),  # Event name for display titles
                        "soil_management_name": getattr(event, "name", None),  # Compatibility with TimelineService
                        "soil_management_type": getattr(
                            event, "type", None
                        ),  # Raw type (ST, PA, OM, etc.) - frontend handles mapping
                        "amendment_type": getattr(event, "amendment_type", None),  # Type of amendment used
                        "amendment_amount": getattr(event, "amendment_amount", None),  # Amount of amendment
                        "soil_ph": getattr(event, "soil_ph", None),  # Soil pH measurement
                        "organic_matter_percentage": getattr(
                            event, "organic_matter_percentage", None
                        ),  # Organic matter %
                        "test_results": getattr(event, "test_results", None),  # JSONField test data
                        # Raw values only - no fallbacks
                        "area_covered": getattr(event, "area_covered", None),  # Numeric area covered
                        "area_unit": getattr(event, "area_unit", None),  # ha, acres, m2, km2 (raw)
                        "fuel_consumed": getattr(event, "fuel_consumed", None),  # Fuel amount
                        "fuel_unit": getattr(event, "fuel_unit", None),  # L, gal, kg (raw)
                        "equipment_hours": getattr(event, "equipment_hours", None),  # Operating hours
                        "working_depth": getattr(event, "working_depth", None),  # Working depth for operations
                        "depth_unit": getattr(event, "depth_unit", None),  # cm, m, inches (raw)
                        # 🚨 CRITICAL FIX: Add missing Additional Information & Technical Details fields
                        "transportation_distance": getattr(
                            event, "transportation_distance", None
                        ),  # Transportation distance
                        "transportation_unit": getattr(event, "transportation_unit", None),  # km, miles
                        "operation_efficiency": getattr(
                            event, "production_efficiency", None
                        ),  # high, normal, low (mapped from production_efficiency field)
                        # Technical Details fields
                        "soil_texture": getattr(event, "soil_texture", None),  # Clay, Sandy Loam, etc.
                        "soil_moisture": getattr(event, "soil_moisture", None),  # wet, moderate, dry
                        "weather_conditions": getattr(event, "weather_conditions", None),  # Weather during operation
                        "temperature_range": getattr(event, "temperature_range", None),  # Temperature range
                        "equipment_used": getattr(event, "equipment_used", None),  # Equipment type used
                        "extra_data": getattr(event, "extra_data", None),  # Additional soil management data
                    }
                )

            for event in pest_events:
                # Count photos from event album
                photo_count = 0
                album_data = None
                if hasattr(event, "album") and event.album:
                    photo_count = event.album.images.count()
                    # Serialize album data for frontend
                    album_data = {
                        "id": event.album.id,
                        "images": [
                            {
                                "id": img.id,
                                "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                                "caption": getattr(img, "caption", "") or "",
                                "created_at": (
                                    img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""
                                ),
                            }
                            for img in event.album.images.all()
                        ],
                    }

                events_data.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Pest Management",
                        "observation": getattr(event, "observation", ""),
                        "type": "pest_management",
                        "certified": getattr(event, "certified", True),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": event.pest_species,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                    }
                )

            for event in general_events:
                # Count photos from event album
                photo_count = 0
                album_data = None
                if hasattr(event, "album") and event.album:
                    photo_count = event.album.images.count()
                    # Serialize album data for frontend
                    album_data = {
                        "id": event.album.id,
                        "images": [
                            {
                                "id": img.id,
                                "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                                "caption": getattr(img, "caption", "") or "",
                                "created_at": (
                                    img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""
                                ),
                            }
                            for img in event.album.images.all()
                        ],
                    }

                events_data.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.name or event.description or "General Event",
                        "observation": event.observation or "",
                        "type": "general",
                        "certified": getattr(event, "certified", True),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": None,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                        # NEW ACTIVITY FIELDS for complete transparency
                        "activity_type": getattr(event, "activity_type", None),
                        "activity_name": getattr(event, "activity_name", None),
                        "duration": getattr(event, "duration", None),
                        "people_involved": getattr(event, "people_involved", None),
                    }
                )

            for event in business_events:
                business_display = (
                    event.get_business_type_display()
                    if hasattr(event, "get_business_type_display")
                    else event.business_type
                )
                certification_display = (
                    event.get_certification_type_display()
                    if hasattr(event, "get_certification_type_display") and event.certification_type
                    else None
                )

                # Count photos from event album
                photo_count = 0
                album_data = None
                if hasattr(event, "album") and event.album:
                    photo_count = event.album.images.count()
                    # Serialize album data for frontend
                    album_data = {
                        "id": event.album.id,
                        "images": [
                            {
                                "id": img.id,
                                "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                                "caption": getattr(img, "caption", "") or "",
                                "created_at": (
                                    img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""
                                ),
                            }
                            for img in event.album.images.all()
                        ],
                    }

                events_data.append(
                    {
                        "id": event.id,
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.name or event.description or f"Business Event - {business_display}",
                        "observation": event.observation or "",
                        "type": "business",
                        "certified": getattr(event, "certified", True),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": certification_display or business_display,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                    }
                )

            # Sort by index first, then by date
            events_data.sort(key=lambda x: (x.get("index", 0), x.get("date", "")))

            return events_data

        except Exception as e:
            print(f"Error getting optimized events: {e}")
            # Return empty list if there's an error
            return []

    def get_certificate_percentage(self, history):
        return history.certificate_percentage

    def get_similar_histories(self, history):
        return PublicHistoryListSerializer(
            self.context.get("similar_histories", []), many=True, context={"request": self.context.get("request")}
        ).data

    def get_company(self, history):
        return history.parcel.establishment.company.name if history.parcel else None

    def get_parcel(self, history):
        return history.parcel.name if history.parcel else None

    def get_history_scan(self, history):
        return self.context.get("history_scan", None)

    def get_qr_code(self, history):
        if history.qr_code:
            request = self.context.get("request")
            return request.build_absolute_uri(history.qr_code.url) if request else history.qr_code.url
        return None

    def get_images(self, history):
        print(f"DEBUG: PublicHistorySerializer.get_images called for history {history.id}")
        try:
            request = self.context.get("request")
            images = []

            # Get images from production's own album
            if history.album:
                for image in history.album.images.all():
                    # Prefer image_url (S3 URL) over file field
                    if image.image_url:
                        images.append(image.image_url)
                    elif image.image:
                        image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                        images.append(image_url)

            # Get images from all associated events
            # Chemical Events
            for event in history.history_chemicalevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Production Events
            for event in history.history_productionevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Weather Events
            for event in history.history_weatherevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # General Events
            for event in history.history_generalevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Equipment Events
            for event in history.history_equipmentevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Soil Management Events
            for event in history.history_soilmanagementevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Pest Management Events
            for event in history.history_pestmanagementevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Business Events
            for event in history.history_businessevent_events.all():
                if event.album:
                    for image in event.album.images.all():
                        if image.image_url:
                            images.append(image.image_url)
                        elif image.image:
                            image_url = request.build_absolute_uri(image.image.url) if request else image.image.url
                            images.append(image_url)

            # Remove duplicates while preserving order
            unique_images = []
            for img in images:
                if img not in unique_images:
                    unique_images.append(img)

            print(f"PublicHistorySerializer.get_images for history {history.id}: Found {len(unique_images)} images")
            return unique_images

        except Exception as e:
            print(f"Error getting images: {str(e)}")
            return []


class HistoryListOptionsSerializer(serializers.ModelSerializer):
    period = serializers.SerializerMethodField()

    class Meta:
        model = History
        fields = ["id", "period"]

    def get_period(self, history):
        return f"{history.start_date.strftime('%m/%d/%Y')} - {history.finish_date.strftime('%m/%d/%Y')}"


# Equipment Event Serializers
class UpdateEquipmentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = EquipmentEvent
        fields = "__all__"

    def to_internal_value(self, data):
        """
        Map frontend field names to backend database field names.
        Handles field name mapping and value mapping for equipment events.
        """
        print(f"[UpdateEquipmentEventSerializer.to_internal_value] Input data: {data}")

        # Create a copy to avoid modifying the original
        data = data.copy()

        # Map equipment_type (frontend) to equipment_type_structured (backend/database)
        if "equipment_type" in data:
            equipment_type = data.pop("equipment_type")

            # EQUIPMENT VALUE MAPPING: Handle generic frontend values to specific backend values
            # Frontend sends generic "tractor", backend expects specific tractor size
            equipment_type_mapping = {
                "tractor": "tractor_medium",  # Default to medium tractor for generic "tractor"
                "harvester": "harvester",
                "sprayer": "sprayer",
                "cultivator": "cultivator",
                "transport": "transport",
                "irrigation_pump": "irrigation_pump",
                # Backend values that should pass through unchanged
                "tractor_small": "tractor_small",
                "tractor_medium": "tractor_medium",
                "tractor_large": "tractor_large",
            }

            # Map the equipment type, fallback to original value if not in mapping
            mapped_equipment_type = equipment_type_mapping.get(equipment_type, equipment_type)
            data["equipment_type_structured"] = mapped_equipment_type

            if mapped_equipment_type != equipment_type:
                print(
                    f"[UpdateEquipmentEventSerializer] Mapped equipment_type '{equipment_type}' → '{mapped_equipment_type}' → equipment_type_structured"
                )
            else:
                print(
                    f"[UpdateEquipmentEventSerializer] Mapped equipment_type '{equipment_type}' → equipment_type_structured (no value mapping needed)"
                )

        # Call the parent method to handle the rest
        return super().to_internal_value(data)

    def validate(self, data):
        """
        Enhanced validation for equipment event structured fields with helpful error messages
        """
        fuel_consumed = data.get("fuel_consumed")
        hours_operated = data.get("hours_operated")
        area_worked = data.get("area_worked")
        maintenance_cost = data.get("maintenance_cost")
        equipment_type = data.get("equipment_type_structured")

        # Validate positive values with detailed error messages
        if fuel_consumed is not None and fuel_consumed < 0:
            raise serializers.ValidationError(
                {
                    "fuel_consumed": [
                        "Fuel consumed cannot be negative.",
                        "Please enter the actual fuel consumed during the operation.",
                        "Tip: Small tractors typically consume 5-15L/hr, large tractors 20-40L/hr.",
                    ]
                }
            )

        if hours_operated is not None and hours_operated < 0:
            raise serializers.ValidationError(
                {
                    "hours_operated": [
                        "Hours operated cannot be negative.",
                        "Please enter the actual operating time for this equipment.",
                    ]
                }
            )

        if area_worked is not None and area_worked < 0:
            raise serializers.ValidationError(
                {
                    "area_worked": [
                        "Area worked cannot be negative.",
                        "Please enter the actual area covered during the operation.",
                    ]
                }
            )

        if maintenance_cost is not None and maintenance_cost < 0:
            raise serializers.ValidationError(
                {
                    "maintenance_cost": [
                        "Maintenance cost cannot be negative.",
                        "Please enter the actual cost incurred for maintenance or repairs.",
                    ]
                }
            )

        # Business logic validation with farmer-friendly messages

        # If fuel consumption is provided, encourage hours operated for accurate carbon calculations
        if fuel_consumed and fuel_consumed > 0 and not hours_operated:
            raise serializers.ValidationError(
                {
                    "hours_operated": [
                        "Hours operated should be provided when fuel consumption is recorded.",
                        "This helps calculate accurate carbon emissions and fuel efficiency.",
                        "Even an approximate value is better than none.",
                    ]
                }
            )

        # Reasonable maximum hours per day validation
        if hours_operated is not None and hours_operated > 24:
            raise serializers.ValidationError(
                {
                    "hours_operated": [
                        f"Hours operated cannot exceed 24 hours per day for a single event. Current: {hours_operated}h",
                        "If this operation took multiple days, please create separate events for each day.",
                        "For multi-day operations: Day 1 = 8h, Day 2 = 6h, etc.",
                    ]
                }
            )

        # Fuel efficiency sanity check (if both fuel and hours are provided)
        if fuel_consumed and fuel_consumed > 0 and hours_operated and hours_operated > 0:
            fuel_per_hour = float(fuel_consumed) / float(hours_operated)

            # Reasonable fuel consumption: 0.5L/hr to 50L/hr
            if fuel_per_hour > 50:
                raise serializers.ValidationError(
                    {
                        "fuel_consumed": [
                            f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unusually high.",
                            "Please double-check your fuel consumption and hours operated values.",
                            "Typical ranges: Small equipment 2-10L/hr, Large tractors 15-40L/hr.",
                        ]
                    }
                )
            elif fuel_per_hour < 0.5:
                raise serializers.ValidationError(
                    {
                        "fuel_consumed": [
                            f"Fuel consumption ({fuel_per_hour:.1f}L/hr) seems unusually low.",
                            "Please verify your fuel consumption and hours operated values.",
                            "Even small equipment typically consumes at least 1L/hr.",
                        ]
                    }
                )

        # Equipment type specific validations
        if equipment_type and fuel_consumed:
            if equipment_type in ["tractor_large"] and fuel_consumed and fuel_consumed < 10:
                raise serializers.ValidationError(
                    {
                        "fuel_consumed": [
                            "Large tractors typically consume more than 10L for significant operations.",
                            "Please verify the fuel consumption or consider changing equipment type.",
                        ]
                    }
                )
            elif equipment_type in ["irrigation_pump"] and fuel_consumed and fuel_consumed > 20:
                raise serializers.ValidationError(
                    {
                        "fuel_consumed": [
                            "Irrigation pumps typically consume less than 20L per operation.",
                            "Please verify the fuel consumption or operating duration.",
                        ]
                    }
                )

        return data


class EquipmentEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = EquipmentEvent
        fields = "__all__"

    def get_type(self, equipment_event):
        type_display = equipment_event.get_type_display()
        if type_display is None:
            return "event.equipment.unknown"
        return f"event.equipment.{type_display.lower().replace(' ', '_')}"

    def get_event_type(self, equipment_event):
        return EQUIPMENT_EVENT_TYPE


# Soil Management Event Serializers
class UpdateSoilManagementEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = SoilManagementEvent
        fields = "__all__"

    def to_internal_value(self, data):
        """
        Custom processing to handle Decimal field serialization for JSON storage.
        Ensures all numeric values are properly serialized for extra_data JSONField.
        """
        import decimal
        from decimal import Decimal

        print(f"[UpdateSoilManagementEventSerializer.to_internal_value] Input data: {data}")

        # Create a copy to avoid modifying the original
        data = data.copy()

        # Process the data through parent first
        internal_value = super().to_internal_value(data)

        # Convert any Decimal fields to strings for JSON serialization
        decimal_fields = [
            "soil_ph",
            "organic_matter_percentage",
            "area_covered",
            "fuel_consumed",
            "carbon_sequestration_potential",
        ]

        for field_name in decimal_fields:
            if field_name in internal_value and internal_value[field_name] is not None:
                if isinstance(internal_value[field_name], Decimal):
                    # Convert Decimal to string to ensure JSON serialization works
                    internal_value[field_name] = str(internal_value[field_name])
                    print(
                        f"[UpdateSoilManagementEventSerializer] Converted {field_name} from Decimal to string: {internal_value[field_name]}"
                    )

        # Handle extra_data field specifically - ensure all nested Decimal objects are converted
        if "extra_data" in internal_value and internal_value["extra_data"]:

            def convert_decimals_in_dict(obj):
                """Recursively convert Decimal objects to strings in nested dictionaries"""
                if isinstance(obj, dict):
                    return {key: convert_decimals_in_dict(value) for key, value in obj.items()}
                elif isinstance(obj, list):
                    return [convert_decimals_in_dict(item) for item in obj]
                elif isinstance(obj, Decimal):
                    return str(obj)
                else:
                    return obj

            internal_value["extra_data"] = convert_decimals_in_dict(internal_value["extra_data"])
            print(f"[UpdateSoilManagementEventSerializer] Processed extra_data: {internal_value['extra_data']}")

        print(f"[UpdateSoilManagementEventSerializer.to_internal_value] Final internal_value: {internal_value}")
        return internal_value


class SoilManagementEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = SoilManagementEvent
        fields = "__all__"

    def get_type(self, soil_event):
        type_display = soil_event.get_type_display()
        if type_display is None:
            return "event.soil.unknown"
        return f"event.soil.{type_display.lower().replace(' ', '_')}"

    def get_event_type(self, soil_event):
        return SOIL_MANAGEMENT_EVENT_TYPE


# Pest Management Event Serializers
class UpdatePestManagementEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PestManagementEvent
        fields = "__all__"


class PestManagementEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = PestManagementEvent
        fields = "__all__"

    def get_type(self, pest_event):
        type_display = pest_event.get_type_display()
        if type_display is None:
            return "event.pest.unknown"
        return f"event.pest.{type_display.lower().replace(' ', '_')}"

    def get_event_type(self, pest_event):
        return PEST_MANAGEMENT_EVENT_TYPE


# Business Event Serializers
class UpdateBusinessEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessEvent
        fields = "__all__"

    def validate(self, data):
        """
        Enhanced validation for business event structured fields with helpful error messages
        """
        business_type = data.get("business_type")
        certification_type = data.get("certification_type")
        carbon_credits_earned = data.get("carbon_credits_earned")
        verification_status = data.get("verification_status")

        # Validate carbon_credits_earned - must be non-negative
        if carbon_credits_earned is not None and carbon_credits_earned < 0:
            raise serializers.ValidationError(
                {
                    "carbon_credits_earned": [
                        "Carbon credits earned cannot be negative.",
                        "Carbon credits represent positive environmental impact.",
                        "If no credits were earned, leave this field empty or enter 0.",
                    ]
                }
            )

        # Business logic validation: reasonable carbon credit amounts
        if carbon_credits_earned is not None and carbon_credits_earned > 10000:
            raise serializers.ValidationError(
                {
                    "carbon_credits_earned": [
                        f"Carbon credits amount ({carbon_credits_earned}) seems unusually large.",
                        "Typical farm operations generate 0.1-100 credits per event.",
                        "Please verify this amount is correct.",
                    ]
                }
            )

        # Validate business_type is not empty
        if not business_type or len(business_type.strip()) == 0:
            raise serializers.ValidationError(
                {
                    "business_type": [
                        "Business type is required.",
                        "Please select the type of business activity (certification, carbon credits, etc.)",
                    ]
                }
            )

        # Business logic: certification events should have certification_type
        if business_type == "certification" and not certification_type:
            raise serializers.ValidationError(
                {
                    "certification_type": [
                        "Certification type is required for certification events.",
                        "Please specify what type of certification was obtained.",
                        "Examples: USDA Organic, Carbon Neutral, Rainforest Alliance",
                    ]
                }
            )

        # Business logic: carbon_credits events should have carbon_credits_earned
        if business_type == "carbon_credits" and not carbon_credits_earned:
            raise serializers.ValidationError(
                {
                    "carbon_credits_earned": [
                        "Carbon credits amount is required for carbon credit transactions.",
                        "Please enter the number of credits generated or traded.",
                        "If no credits were generated, consider using a different business type.",
                    ]
                }
            )

        # Business logic: verification events should have verified status
        if business_type == "verification" and verification_status in ["pending", "not_applicable"]:
            raise serializers.ValidationError(
                {
                    "verification_status": [
                        "Verification events should have a definitive verification status.",
                        'Please update the status to "verified", "in_progress", or "failed".',
                    ]
                }
            )

        return data


class BusinessEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    # Add display fields for better readability
    business_type_display = serializers.SerializerMethodField()
    certification_type_display = serializers.SerializerMethodField()
    verification_status_display = serializers.SerializerMethodField()
    sustainability_practice_display = serializers.SerializerMethodField()

    class Meta:
        model = BusinessEvent
        fields = "__all__"

    def get_type(self, business_event):
        type_display = business_event.get_type_display()
        if type_display is None:
            return "event.business.unknown"
        return f"event.business.{type_display.lower().replace(' ', '_')}"

    def get_event_type(self, business_event):
        return BUSINESS_EVENT_TYPE

    def get_business_type_display(self, business_event):
        return business_event.get_business_type_display()

    def get_certification_type_display(self, business_event):
        return business_event.get_certification_type_display() if business_event.certification_type else None

    def get_verification_status_display(self, business_event):
        return business_event.get_verification_status_display()

    def get_sustainability_practice_display(self, business_event):
        return business_event.get_sustainability_practice_display() if business_event.sustainability_practice else None
