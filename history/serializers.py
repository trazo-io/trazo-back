from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers

from common.models import Gallery
from common.serializers import GallerySerializer
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
from .custom_fields import (
    extract_custom_fields_for_display,
    merge_custom_fields_into_extra_data,
    validate_custom_fields,
)
from .models import (
    BusinessEvent,
    BuyerDocRequest,
    ChemicalEvent,
    CommonEvent,
    EquipmentEvent,
    GeneralEvent,
    History,
    HistoryScan,
    PestManagementEvent,
    ProductionEvent,
    SalesRecord,
    SoilManagementEvent,
    WeatherEvent,
)
from .services.claim_resolver import resolve_input_status
from .services.privacy import public_free_text, public_parcel_geo


def _drop_unset(event_dict):
    """Strip keys the farmer never filled from a CONSUMER event payload.

    Each consumer event dict is hand-built per event category and carries the UNION of
    every field any subtype in that category might use, so an irrigation set shipped
    `sanitizer_nop_reference`, `cleaning_materials_used`, `seed_certification_status`,
    `equipment_operation_type` … all null. Measured on a realistic 258-event season
    (24 irrigation sets logged individually, 6 sprays, 12 trap checks, 3 shakes):

        events block = 100% of the payload; 105 keys null on every event = 316 KB
        payload 493 KB -> 194 KB (61% smaller) with ZERO information removed

    That matters because this is the QR page — the most mobile-critical surface in the
    product, with a <500 ms budget, opened on a phone in a shop or a field on cell data.
    Trimming empty keys is strictly better than paginating or capping the timeline:
    capping would drop documented practices, and the documented-practice COUNT is the
    consumer claim (see transparency-first rules), so evidence must not be silently lost.

    Only ``None`` and ``""`` are dropped. ``False`` and ``0`` are REAL ANSWERS —
    "no photos", "not shared with conventional", "zero catch" — and are preserved.

    Safe for the frontend: the event registry reads values as
    ``event[field.name] ?? extraData[field.name]``, and ``??`` treats a missing key
    exactly like a null one. No consumer component branches on key presence
    (no ``hasOwnProperty`` / ``Object.keys(event)`` over event objects).
    """
    if not isinstance(event_dict, dict):
        return event_dict
    out = {}
    for key, value in event_dict.items():
        if value is None or value == "":
            continue
        out[key] = _drop_unset(value) if isinstance(value, dict) else value
    return out


def _public_unit(event, field_name):
    """Resolve a unit of measure for the CONSUMER payload. Model column wins.

    ``volume_unit`` / ``area_unit`` are real columns on ChemicalEvent; ``extra_data``
    retains a legacy mirror written by older clients. Reading the mirror first — and
    falling back to a hardcoded ``"ha"`` / ``"L"`` when it was absent — mislabelled the
    basis on rows created after the columns landed. Because the consumer card converts
    hectares to acres for US shoppers, a value entered in acres and served as ``"ha"``
    was displayed at 2.47x the real treated area.

    Returns ``None`` when no unit is recorded. That is deliberate: the registry
    formatters emit a bare number when the unit field is empty, which is honest, whereas
    a guessed unit is an unverifiable claim about how much was applied to food. See
    ``_drop_unset`` — a ``None`` here is dropped from the payload entirely.
    """
    column_value = getattr(event, field_name, None)
    if isinstance(column_value, str) and column_value.strip():
        return column_value.strip()

    extra = getattr(event, "extra_data", None)
    if isinstance(extra, dict):
        mirrored = extra.get(field_name)
        if isinstance(mirrored, str) and mirrored.strip():
            return mirrored.strip()

    return None


def ensure_event_description(data, default_label):
    """F01 fix (2026-06): CommonEvent.description is a non-blank TextField, so any
    event saved with the (clearly "Optional") Observations/notes field empty returned
    {"description":["This field may not be blank."]} as a SILENT 400 — no toast, the
    save button looked dead. Affected Chemical/Production/Weather/Soil/General (Pest
    already had its own fallback). Default a blank description from the event
    name/type so the save succeeds and the consumer card shows something sensible.
    Mutates ``data`` in place; call at the top of to_internal_value after data.copy().
    """
    if not str(data.get("description") or "").strip():
        name = str(data.get("name") or data.get("commercial_name") or data.get("event_name") or "").strip()
        data["description"] = f"{default_label}: {name}" if name else default_label


def coerce_blank_nullable_dates(serializer, data):
    """The add-event form posts EVERY field for EVERY subtype, so a date column that is
    irrelevant to the chosen subtype arrives as "" — and DRF's Date/DateTimeField rejects ""
    ("Date has wrong format"), 400ing the whole event with no user-facing error. This is the
    class behind the seed_purchase_date (production), cleaning_date (production HA/PH/EM) and
    purchase_date / ca_dpr_permit_expires (chemical) bugs. Introspect the serializer's declared
    fields and coerce blank -> None for every nullable date field, so no hand-maintained list can
    miss one. Only touches fields that explicitly accept null (allow_null=True), so a genuinely
    required date still errors correctly. Mutates ``data`` in place; call before super()."""
    from rest_framework import serializers as _drf

    for name, field in serializer.fields.items():
        if isinstance(field, (_drf.DateField, _drf.DateTimeField)) and field.allow_null:
            if name in data and data[name] in ("", None):
                data[name] = None


class CustomFieldsMixin:
    """
    Mixin for event serializers to handle custom fields.

    Custom fields allow farmers to add additional information to events
    that will be displayed alongside standard fields in both preview and
    consumer views.

    Usage:
        class MyEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
            ...
    """

    def handle_custom_fields_input(self, data):
        """
        Extract and validate custom_fields from incoming data.

        Call this in to_internal_value() before processing other fields.
        Returns the validated custom_fields list (or None if not provided).
        """
        custom_fields = data.pop("custom_fields", None)
        if custom_fields is not None:
            return validate_custom_fields(custom_fields)
        return None

    def merge_custom_fields(self, extra_data, custom_fields, instance=None):
        """
        Merge custom_fields into extra_data, preserving existing data.

        Call this after building extra_data in to_internal_value().
        """
        existing_extra_data = instance.extra_data if instance else None
        return merge_custom_fields_into_extra_data(extra_data, custom_fields, existing_extra_data)

    def add_custom_fields_to_representation(self, data, instance):
        """
        Add custom_fields to the serialized output for frontend display.

        Call this in to_representation() to include custom_fields in response.
        """
        extra_data = getattr(instance, "extra_data", None) or {}

        # Extract custom fields if they exist
        if "custom_fields" in extra_data:
            data["custom_fields"] = extra_data.get("custom_fields", [])

        return data


def serialize_event_album(event, request=None):
    """
    Helper function to serialize album with images for event objects.
    Used by Update serializers to return full album data instead of just ID.
    """
    if not event.album:
        return None

    try:
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
                    "caption": f"Farming practice photo {image.id}",
                    "created_at": image.created_at.isoformat() if image.created_at else None,
                }
            )

        return {"id": event.album.id, "images": images} if images else None
    except Exception as e:
        # Return None if there's any issue with album serialization
        return None


class EventSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    carbon_data = serializers.SerializerMethodField()
    album = serializers.SerializerMethodField()
    verification_level = serializers.SerializerMethodField()

    class Meta:
        model = CommonEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "image",
            "carbon_data",
            "verification_level",
        ]
        read_only_fields = ["id", "index", "created_by"]

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
        Read-only carbon data lookup from CarbonEntry records.

        Carbon calculations happen ONCE at event creation/update time via Django
        signals (history/signals.py). This serializer method only READS the stored
        results — it never recalculates.

        Lookup order:
        1. CarbonEntry table (authoritative, created by signals)
        2. extra_data['carbon_calculation'] (backward compat for pre-CarbonEntry events)
        3. None (no data available — signals will create it on next event save)
        """
        try:
            from carbon.models import CarbonEntry

            if hasattr(event, "history") and event.history:
                event_class_name = event.__class__.__name__
                event_id_pattern = f"{event_class_name}(ID={event.id})"
                carbon_entry = None

                # Use prefetched carbon entries when available (avoids N+1)
                if (
                    hasattr(event.history, "_prefetched_objects_cache")
                    and "carbonentry_set" in event.history._prefetched_objects_cache
                ):
                    for entry in event.history.carbonentry_set.all():
                        if entry.description and event_id_pattern in entry.description:
                            carbon_entry = entry
                            break
                    # Legacy fallback: entries without event ID in description
                    if not carbon_entry:
                        for entry in event.history.carbonentry_set.all():
                            if (
                                entry.description
                                and event_class_name in entry.description
                                and "(ID=" not in entry.description
                            ):
                                carbon_entry = entry
                                break
                else:
                    # DB query when not prefetched
                    carbon_entry = (
                        CarbonEntry.objects.filter(production=event.history, description__icontains=event_id_pattern)
                        .order_by("-created_at")
                        .first()
                    )

                    if not carbon_entry:
                        carbon_entry = (
                            CarbonEntry.objects.filter(
                                production=event.history, description__icontains=event_class_name
                            )
                            .exclude(description__contains="(ID=")
                            .order_by("-created_at")
                            .first()
                        )

                if carbon_entry:
                    return {
                        "co2e": float(carbon_entry.co2e_amount or carbon_entry.amount),
                        "efficiency_score": 90.0 if carbon_entry.usda_factors_based else 75.0,
                        "usda_factors_based": carbon_entry.usda_factors_based,
                        "verification_status": "epa_usda_sourced" if carbon_entry.usda_factors_based else "calculated",
                        "calculation_method": carbon_entry.data_source or "EPA/USDA Emission Factors",
                        "data_source": carbon_entry.data_source or "CarbonEntry",
                        "recommendations": [],
                        "event_type": event_class_name.lower().replace("event", ""),
                        "timestamp": carbon_entry.created_at.isoformat() if carbon_entry.created_at else None,
                    }

            # Backward compat: older events may have carbon in extra_data
            if hasattr(event, "extra_data") and event.extra_data and "carbon_calculation" in event.extra_data:
                return event.extra_data["carbon_calculation"]

            # No stored carbon data — this is normal for weather/general events
            # or events whose signal hasn't fired yet. Never recalculate here.
            return None

        except Exception:
            return None

    def _check_valid_agricultural_content(self, event) -> bool:
        """
        MVP Photo Verification: Check if event photos contain valid agricultural content.

        Returns True if:
        - Photos are validated as agricultural content via Vision API, OR
        - Validation was bypassed in development mode, OR
        - No photos exist (skip this check)

        Returns False if:
        - Photos exist but Vision API marked them as invalid/non-agricultural
        """
        if not event.album or not event.album.images.exists():
            # No photos - don't downgrade verification based on content
            return True

        for image in event.album.images.all():
            # Check Vision API content validation results
            # BUGFIX: Check that extra_data is a dict before calling .get()
            if hasattr(image, "extra_data") and image.extra_data and isinstance(image.extra_data, dict):
                content_validation = image.extra_data.get("content_validation")
                content_bypassed = image.extra_data.get("content_bypassed", False)

                # Accept images that are:
                # - Valid agricultural content
                # - Likely agricultural content
                # - Validation was bypassed (dev mode)
                if content_validation in ["valid_agricultural", "likely_agricultural"] or content_bypassed:
                    return True
                elif content_validation in ["ai_generated", "stock_photo", "not_agricultural", "uncertain"]:
                    # If ANY photo is invalid, the whole event is downgraded
                    return False

        # Default to True if no content validation data exists (for backward compatibility)
        return True

    def get_verification_level(self, event):
        """
        Determine the verification level for an event based on MVP tiered system:
        - self_reported: No photo evidence (50% trust)
        - photo_documented: Has photos without GPS/timestamp validation (65% trust)
        - photo_verified: Has photos with GPS + timestamp verification (80% trust)
        - data_verified: Reserved for future use when actual external data cross-referencing is implemented
        - certified: Third-party or blockchain verified (100% trust)

        MVP Photo Verification: Photos with invalid content (AI-generated, stock images)
        are downgraded to self_reported level.
        """
        # Check for photos
        has_photos = event.album is not None and event.album.images.exists()

        # MVP Photo Verification: Check if photos contain valid agricultural content
        has_valid_agricultural_content = self._check_valid_agricultural_content(event)

        # Check for GPS data (from album images or event metadata)
        has_gps_data = False
        if has_photos:
            for image in event.album.images.all():
                # Check if image has location metadata in extra_data
                # BUGFIX: Check that extra_data is a dict before calling .get()
                if hasattr(image, "extra_data") and image.extra_data and isinstance(image.extra_data, dict):
                    if image.extra_data.get("gps_latitude") or image.extra_data.get("latitude"):
                        has_gps_data = True
                        break

        # Check for timestamp validation (events always have dates)
        has_timestamp = event.date is not None

        # Check for blockchain verification
        # BUGFIX: Check that extra_data is a dict before calling .get()
        has_blockchain_verification = False
        if hasattr(event, "extra_data") and event.extra_data and isinstance(event.extra_data, dict):
            has_blockchain_verification = event.extra_data.get("blockchain_verified", False)

        # Determine verification level using tiered logic
        # Blockchain verification is shown via the BLOCKCHAIN SECURED badge.
        # "certified" tier is reserved for actual third-party certification bodies.
        if has_blockchain_verification:
            return "data_verified"

        if has_photos:
            # MVP Photo Verification: Downgrade if content is invalid
            if not has_valid_agricultural_content:
                return "self_reported"

            if has_gps_data and has_timestamp:
                return "photo_verified"
            else:
                return "photo_documented"

        return "self_reported"


class UpdateChemicalEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
    # 🚨 FIELD ALIASING: Accept frontend field names and map to backend model fields
    # This allows the frontend to send consistent field names while the backend
    # continues to use the existing database schema
    # Frontend sends: volume_applied, area_treated, application_method
    # Backend model expects: volume, area, way_of_application
    volume_applied = serializers.CharField(source="volume", allow_blank=True, allow_null=True, required=False)
    area_treated = serializers.CharField(source="area", allow_blank=True, allow_null=True, required=False)
    application_method = serializers.CharField(
        source="way_of_application", allow_blank=True, allow_null=True, required=False
    )

    class Meta:
        model = ChemicalEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "chemical_subtype",
            "commercial_name",
            "volume",
            "concentration",
            "area",
            "way_of_application",
            "time_period",
            "observation",
            "extra_data",
            "name",
            "nitrogen_percentage",
            "phosphorus_percentage",
            "potassium_percentage",
            "nitrogen_source",
            # §E-3 — micronutrients (FE), § 205.601(j)(6)
            "micronutrient_type",
            "micronutrient_rate",
            "micronutrient_rate_unit",
            "application_method_structured",
            "application_fuel_type",
            "application_fuel_consumed",
            "application_fuel_unit",
            "weather_conditions",
            "application_timing",
            "target_pest_disease",
            "organic_approved",
            "buffer_zone_meters",
            "applicator_name",
            "epa_registration_number",
            "restricted_use_pesticide",
            "applicator_certification",
            "rei_hours",
            "phi_days",
            "volume_numeric",
            "volume_unit",
            "area_numeric",
            "area_unit",
            "is_fertigation",
            # Aliased frontend field names (mapped via source above)
            "volume_applied",
            "area_treated",
            "application_method",
            # NOP compliance — supplier & purchase traceability
            "supplier_name",
            "purchase_date",
            "purchase_invoice",
            "quantity_purchased",
            "quantity_purchased_unit",
            "chemical_lot_number",
            # P0-3 — CA DPR Restricted Materials Permit (CA state law)
            "ca_dpr_permit_number",
            "ca_dpr_permit_county",
            "ca_dpr_permit_expires",
            # F20 — legal spray-record completeness (GLOBALG.A.P. + CA PUR / DPR-PML-017C)
            "manufacturer",
            "application_start",
            "application_end",
            "planted_area",
            "planted_area_unit",
            "operator_id",
            "site_id",
            "application_county",
            "mtrs_section",
            "mtrs_township",
            "mtrs_range",
            "mtrs_base_meridian",
            "ffm_code",
            "tank_mix_partners",
            # F21 — supervisor review (FSMA 112.161(b)) + GG authorizer (FV-GFS 32.02.01 #10)
            "authorizer_name",
            "reviewed",
            "reviewer_name",
            "review_date",
            # Sprint 3 — OMRI / National List cross-reference (7 CFR 205.601/602)
            "omri_product",
            "national_list_substance",
        ]
        read_only_fields = ["id"]
        # Allow both old and new field names by making old fields optional
        extra_kwargs = {
            "volume": {"required": False, "allow_blank": True, "allow_null": True},
            "area": {"required": False, "allow_blank": True, "allow_null": True},
            "way_of_application": {"required": False, "allow_blank": True, "allow_null": True},
        }

    def to_internal_value(self, data):
        """
        Handle custom fields AND field name aliasing for chemical events.
        Accepts BOTH old field names (volume, area, way_of_application)
        AND new field names (volume_applied, area_treated, application_method).
        This ensures backward compatibility while supporting modern frontend conventions.
        """
        data = data.copy()

        # F01 fix (2026-06): CommonEvent.description is a non-blank TextField, so a
        # chemical event saved with the (clearly "Optional") Observations field empty
        # returned {"description":["This field may not be blank."]} as a SILENT 400 —
        # no toast, button looked dead. Mirror the Pest serializer's fallback: when
        # description is blank, derive a meaningful one from the product/name/type so
        # the save succeeds and the consumer card shows something sensible.
        if not str(data.get("description") or "").strip():
            chem_type = (data.get("type") or "").upper()
            type_label = {
                "FE": "Fertilizer application",
                "PE": "Pesticide application",
                "FU": "Fungicide application",
                "HE": "Herbicide application",
            }.get(chem_type, "Chemical application")
            product = str(data.get("commercial_name") or data.get("name") or "").strip()
            data["description"] = f"{type_label}: {product}" if product else type_label

        # 🚨 FIELD NAME NORMALIZATION: Map frontend names → backend model names
        # This allows frontend to send new names while backend uses existing model fields
        # Priority: If new field name is provided, use it; otherwise fall back to old name
        if "volume_applied" in data and "volume" not in data:
            data["volume"] = data.pop("volume_applied")
        elif "volume_applied" in data and "volume" in data:
            # If both provided, prefer the explicitly named frontend field
            data["volume"] = data.pop("volume_applied")

        if "area_treated" in data and "area" not in data:
            data["area"] = data.pop("area_treated")
        elif "area_treated" in data and "area" in data:
            data["area"] = data.pop("area_treated")

        if "application_method" in data and "way_of_application" not in data:
            data["way_of_application"] = data.pop("application_method")
        elif "application_method" in data and "way_of_application" in data:
            data["way_of_application"] = data.pop("application_method")

        # volume_unit and area_unit are now proper model fields on ChemicalEvent
        # (volume_numeric, volume_unit, area_numeric, area_unit).
        # We no longer pop them — they flow through super() directly as model fields.
        # Keep backward-compat: if only legacy extra_data style was sent, store there too.
        volume_unit = data.get("volume_unit", None)
        area_unit = data.get("area_unit", None)

        # SPRINT 6 FIX (2025-12-24): Extract frontend's extra_data BEFORE super() call
        # Frontend sends fields like active_ingredient, application_details, weather_conditions, etc.
        # These need to be preserved and merged with existing extra_data

        frontend_extra_data = data.pop("extra_data", {}) or {}

        # Extract fields that DON'T have model columns into extra_data.
        # IMPORTANT: weather_conditions, application_timing, target_pest_disease
        # ARE model columns - do NOT pop them from data or they won't save to DB.
        extra_data_only_fields = [
            "active_ingredient",
            "application_details",
        ]
        for field_name in extra_data_only_fields:
            if field_name in data:
                value = data.pop(field_name)
                # Use empty string to allow clearing (not just truthy values)
                frontend_extra_data[field_name] = value if value is not None else ""

        # Promote model-column fields that arrived NESTED inside extra_data.
        # The event form posts target_pest_disease (and friends) inside its extra_data
        # blob rather than at the top level, so the block above never saw them and the
        # real DB column stayed NULL — while a copy sat in extra_data. Read paths fall
        # back to extra_data so the UI looked correct, but the audit-export PDF reads the
        # column directly (audit_export_service: `ev.target_pest_disease`), so the
        # certifier packet showed a blank "target pest" for every event logged in the UI.
        for field_name in ("weather_conditions", "application_timing", "target_pest_disease"):
            if field_name not in data and field_name in frontend_extra_data:
                nested_value = frontend_extra_data.get(field_name)
                if nested_value not in (None, ""):
                    data[field_name] = nested_value

        # Handle custom fields (user-defined additional information)
        custom_fields = self.handle_custom_fields_input(data)

        # Coerce blank nullable date fields (purchase_date, ca_dpr_permit_expires, cleaning_date)
        # to None — the form posts them "" on subtypes that don't use them, which 400s the event.
        coerce_blank_nullable_dates(self, data)

        internal_value = super().to_internal_value(data)

        # Get existing extra_data from instance (for updates)
        instance = getattr(self, "instance", None)
        existing_extra_data = instance.extra_data if instance and instance.extra_data else {}

        # SPRINT 6 FIX: Merge frontend extra_data with existing extra_data
        # This preserves fields like carbon_calculation while adding new fields
        merged_extra_data = {**existing_extra_data, **frontend_extra_data}

        # SPRINT 6 FIX: Handle custom_fields directly to avoid merge_custom_fields overwriting our merged_extra_data
        # The merge_custom_fields function prioritizes existing_extra_data which would overwrite our merged data
        # So we handle custom_fields inline here
        if custom_fields:
            # New custom_fields provided - use them
            merged_extra_data["custom_fields"] = custom_fields
        elif instance and instance.extra_data and "custom_fields" in instance.extra_data:
            # No new custom_fields - preserve existing
            merged_extra_data["custom_fields"] = instance.extra_data["custom_fields"]

        internal_value["extra_data"] = merged_extra_data

        # Also mirror volume_unit/area_unit into extra_data for legacy frontend compatibility.
        # The canonical values are now model columns (volume_unit, area_unit on ChemicalEvent)
        # but older frontend code may still read from extra_data.
        if volume_unit is not None:
            internal_value["extra_data"]["volume_unit"] = volume_unit
        if area_unit is not None:
            internal_value["extra_data"]["area_unit"] = area_unit

        # Auto-detect fertigation from application method text.
        # `is None`, NOT falsiness: `not False` is True, so a farmer who explicitly answered
        # "no" was indistinguishable from one who left it blank, and the answer was overwritten
        # to True. Only infer when the caller said nothing. (Same defect class as the
        # action_threshold_met promotion.) The flag suppresses application emissions in the
        # carbon calculation, so a wrong True also understates the event's footprint.
        way_of_app = internal_value.get("way_of_application", "") or ""
        if "fertigation" in way_of_app.lower() and internal_value.get("is_fertigation") is None:
            internal_value["is_fertigation"] = True

        return internal_value

    # NOTE: Single to_representation method below (after validate) handles all field extraction

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

    def to_representation(self, instance):
        """
        Extract fields from extra_data so the frontend can read them at top level
        when loading an event for editing. Handles:
        - Unit fields (volume_unit, area_unit)
        - Environmental context fields
        - Fields without model columns (active_ingredient, application_details)
        - Album serialization
        """
        data = super().to_representation(instance)

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # Include custom fields in response for frontend display
        data = self.add_custom_fields_to_representation(data, instance)

        # Guard: instance may be an OrderedDict (validated data) during create, not a model instance
        extra_data = (
            getattr(instance, "extra_data", None)
            or (instance.get("extra_data") if isinstance(instance, dict) else {})
            or {}
        )

        # Extract unit fields from extra_data for frontend form compatibility
        data["volume_unit"] = extra_data.get("volume_unit", "L")
        data["area_unit"] = extra_data.get("area_unit", "ha")

        # Environmental context: model columns with extra_data fallback for legacy events
        data["weather_conditions"] = extra_data.get("weather_conditions", "") or data.get("weather_conditions") or ""
        data["application_timing"] = extra_data.get("application_timing", "") or data.get("application_timing") or ""
        data["target_pest_disease"] = (
            extra_data.get("target_pest_disease", "")
            or extra_data.get("target_pest", "")
            or data.get("target_pest_disease")
            or ""
        )

        # Fields without model columns - always from extra_data
        data["active_ingredient"] = extra_data.get("active_ingredient", "") or data.get("active_ingredient") or ""
        data["application_details"] = extra_data.get("application_details", "") or data.get("application_details") or ""

        return data


class ChemicalEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    chemical_type = serializers.SerializerMethodField()  # Add raw chemical type for frontend
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = ChemicalEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "chemical_type",
            "event_type",
            "chemical_subtype",
            "commercial_name",
            "volume",
            "concentration",
            "area",
            "way_of_application",
            "time_period",
            "observation",
            "extra_data",
            "name",
            "nitrogen_percentage",
            "phosphorus_percentage",
            "potassium_percentage",
            "nitrogen_source",
            # §E-3 — micronutrients (FE), § 205.601(j)(6)
            "micronutrient_type",
            "micronutrient_rate",
            "micronutrient_rate_unit",
            "application_method_structured",
            "application_fuel_type",
            "application_fuel_consumed",
            "application_fuel_unit",
            "weather_conditions",
            "application_timing",
            "target_pest_disease",
            "organic_approved",
            "buffer_zone_meters",
            "applicator_name",
            "epa_registration_number",
            "restricted_use_pesticide",
            "applicator_certification",
            "rei_hours",
            "phi_days",
            "volume_numeric",
            "volume_unit",
            "area_numeric",
            "area_unit",
            "is_fertigation",
            "image",
            "carbon_data",
            "verification_level",
            # NOP compliance — supplier & purchase traceability
            "supplier_name",
            "purchase_date",
            "purchase_invoice",
            "quantity_purchased",
            "quantity_purchased_unit",
            "chemical_lot_number",
            # P0-3 — CA DPR Restricted Materials Permit (CA state law)
            "ca_dpr_permit_number",
            "ca_dpr_permit_county",
            "ca_dpr_permit_expires",
            # F20 — legal spray-record completeness (GLOBALG.A.P. + CA PUR / DPR-PML-017C)
            "manufacturer",
            "application_start",
            "application_end",
            "planted_area",
            "planted_area_unit",
            "operator_id",
            "site_id",
            "application_county",
            "mtrs_section",
            "mtrs_township",
            "mtrs_range",
            "mtrs_base_meridian",
            "ffm_code",
            "tank_mix_partners",
            # F21 — supervisor review (FSMA 112.161(b)) + GG authorizer (FV-GFS 32.02.01 #10)
            "authorizer_name",
            "reviewed",
            "reviewer_name",
            "review_date",
            # Sprint 3 — OMRI / National List cross-reference
            "omri_product",
            "national_list_substance",
            # Sprint 5.1 — OSP ↔ events drift detector finding (null when in-OSP)
            "drift_warning",
        ]
        read_only_fields = ["id", "index", "created_by", "drift_warning"]

    @staticmethod
    def _parse_value_with_unit(raw_value, default_unit=""):
        """
        Parse a value that may be a combined string like "400 kg/ha" or a plain number.
        Returns (numeric_value, unit_string).

        Examples:
            "400 kg/ha" -> (400.0, "kg/ha")
            "15.5 L" -> (15.5, "L")
            400 -> (400.0, default_unit)
            "400" -> (400.0, default_unit)
        """
        import re

        if raw_value is None or raw_value == "":
            return (None, default_unit)

        if isinstance(raw_value, (int, float)):
            return (float(raw_value), default_unit)

        raw_str = str(raw_value).strip()
        if not raw_str:
            return (None, default_unit)

        # Try to extract numeric part and unit using regex
        # Match: optional spaces, number (with optional decimals), optional spaces, unit text
        match = re.match(r"^\s*([\d.]+)\s*(.*)$", raw_str)
        if match:
            try:
                numeric_part = float(match.group(1))
                unit_part = match.group(2).strip() if match.group(2) else default_unit
                return (numeric_part, unit_part if unit_part else default_unit)
            except ValueError:
                pass

        # Fallback: try to convert whole string to float
        try:
            return (float(raw_str), default_unit)
        except ValueError:
            # Last resort: return None with default unit
            return (None, default_unit)

    def to_representation(self, instance):
        """
        Override to ensure aliased field names are included and old names are removed.
        This provides clean API responses with consistent field naming.

        🔧 CRITICAL FIX: Parse combined strings like "400 kg/ha" into separate
        numeric value and unit fields that the frontend form expects.

        The unit information may come from:
        1. Parsed from combined string (e.g., "400 kg/ha" → unit="kg/ha")
        2. Stored in extra_data (for template-created events)
        3. Default value (L for volume, ha for area)
        """
        data = super().to_representation(instance)

        # Get extra_data for unit fallbacks (template events store units here)
        extra_data = instance.extra_data or {}

        # Default units from extra_data or fallbacks
        default_volume_unit = extra_data.get("volume_unit", "L")
        default_area_unit = extra_data.get("area_unit", "ha")

        # Parse volume - may be combined string like "400 kg/ha"
        volume_raw = instance.volume
        volume_numeric, parsed_volume_unit = self._parse_value_with_unit(volume_raw, default_volume_unit)
        data["volume_applied"] = volume_numeric
        # Use parsed unit if it was extracted from the string, otherwise use default
        data["volume_unit"] = parsed_volume_unit if parsed_volume_unit else default_volume_unit

        # Parse area - may be combined string like "10 ha"
        area_raw = instance.area
        area_numeric, parsed_area_unit = self._parse_value_with_unit(area_raw, default_area_unit)
        data["area_treated"] = area_numeric
        # Use parsed unit if it was extracted from the string, otherwise use default
        data["area_unit"] = parsed_area_unit if parsed_area_unit else default_area_unit

        # Map application method
        data["application_method"] = instance.way_of_application or ""

        # weather_conditions, application_timing, target_pest_disease are model columns.
        # Use extra_data as fallback only for legacy events that stored them there.
        if not data.get("weather_conditions"):
            data["weather_conditions"] = extra_data.get("weather_conditions", "")
        if not data.get("application_timing"):
            data["application_timing"] = extra_data.get("application_timing", "")
        if not data.get("target_pest_disease"):
            data["target_pest_disease"] = extra_data.get("target_pest_disease", "") or extra_data.get("target_pest", "")

        # active_ingredient and application_details have NO model columns - always from extra_data
        data["active_ingredient"] = extra_data.get("active_ingredient", "")
        data["application_details"] = extra_data.get("application_details", "")

        # Remove old backend field names to avoid confusion in frontend
        # Frontend should only see: volume_applied, area_treated, application_method
        data.pop("volume", None)
        data.pop("area", None)
        data.pop("way_of_application", None)

        return data

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


class UpdateWeatherEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = WeatherEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "observation",
            "extra_data",
        ]
        read_only_fields = ["id"]

    def to_internal_value(self, data):
        event_type = data.get("type", None)
        if event_type is None:
            raise serializers.ValidationError({"type": ["This field is required."]}, code="required")
        data = data.copy()
        ensure_event_description(data, "Weather event")  # F01: avoid silent 400 on blank notes

        # Handle custom fields (user-defined additional information)
        custom_fields = self.handle_custom_fields_input(data)

        extra_data = {}

        # WeatherEvent has NO meteorological columns — `extra_data` IS the record. The merge
        # below is `{**instance.extra_data, **extra_data}`, so this dict WINS. Writing a key
        # unconditionally therefore DESTROYS the stored value whenever the payload omits it:
        # a description-only edit turned `highest_temperature: 111` into `null` and, because
        # `temperature_unit` carried a literal default, silently rewrote a recorded "F" to "C".
        # Only touch keys the caller actually sent.
        def take(key, create_default=None):
            if key in data:
                extra_data[key] = data.pop(key)
            elif create_default is not None and not getattr(self, "instance", None):
                # Defaults belong to creation only. On update, absence means "unchanged",
                # and the existing stored value must survive the merge.
                extra_data[key] = create_default

        # Preserve custom event name if provided by the frontend
        event_name = data.pop("name", None)
        if event_name:
            extra_data["event_name"] = event_name

        if event_type == WeatherEvent.FROST:
            take("lower_temperature")
            take("temperature_unit", "C")
            take("way_of_protection")
        elif event_type == WeatherEvent.DROUGHT:
            take("water_deficit")
        elif event_type == WeatherEvent.HAILSTORM:
            # Sprint 2 Epic 2.1.3: Removed weight and diameter fields (excessive detail)
            # Only keep duration and way_of_protection
            take("duration")
            take("way_of_protection")
        elif event_type == WeatherEvent.HIGH_TEMPERATURE:
            take("highest_temperature")
            take("temperature_unit", "C")
            take("start_date")
            take("end_date")
        elif event_type == WeatherEvent.TROPICAL_STORM:
            take("wind_speed")
            take("precipitation_amount")
            take("duration")
            take("damage_assessment")
        elif event_type == WeatherEvent.HIGH_WINDS:
            take("wind_speed")
            take("duration")
            take("protection_measures")
        elif event_type == WeatherEvent.HIGH_HUMIDITY:
            take("humidity_level")
            take("duration")
            take("crop_impact")
        elif event_type == WeatherEvent.LOW_HUMIDITY:
            take("humidity_level")
            take("duration")
            take("crop_impact")

        internal_value = super().to_internal_value(data)

        # Merge with existing extra_data to preserve carbon_calculation and other fields
        if hasattr(self, "instance") and self.instance and self.instance.extra_data:
            merged_extra_data = {**self.instance.extra_data, **extra_data}
        else:
            merged_extra_data = extra_data

        # Merge custom fields into extra_data (preserves existing custom_fields if not provided)
        instance = getattr(self, "instance", None)
        internal_value["extra_data"] = self.merge_custom_fields(merged_extra_data, custom_fields, instance)

        # Meteorological-magnitude plausibility gate. Runs at serializer
        # level so API writes catch unit-of-measure typos (°C in °F field,
        # etc.) before they land in the DB. The same bounds are enforced
        # by WeatherEvent.clean() for admin/manage.py writes.
        self._validate_weather_magnitudes(internal_value["extra_data"])

        return internal_value

    def _validate_weather_magnitudes(self, extra_data):
        """Run WeatherEvent's plausibility bounds against proposed extra_data."""
        if not extra_data:
            return
        probe = WeatherEvent(extra_data=extra_data)
        try:
            probe.clean()
        except DjangoValidationError as exc:
            # Convert Django ValidationError → DRF ValidationError so the
            # API returns a 400 with a structured body rather than a 500.
            raise serializers.ValidationError({"extra_data": exc.messages})

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
            data["temperature_unit"] = extra_data.get("temperature_unit", "C")
            data["way_of_protection"] = extra_data.get("way_of_protection", "")
        elif type == WeatherEvent.DROUGHT:
            data["water_deficit"] = extra_data.get("water_deficit", 0)
        elif type == WeatherEvent.HAILSTORM:
            # Sprint 2 Epic 2.1.3: Removed weight and diameter fields (excessive detail)
            # Only expose duration and way_of_protection
            data["duration"] = extra_data.get("duration", 0)
            data["way_of_protection"] = extra_data.get("way_of_protection", "")
        elif type == WeatherEvent.HIGH_TEMPERATURE:
            data["highest_temperature"] = extra_data.get("highest_temperature", 0)
            data["temperature_unit"] = extra_data.get("temperature_unit", "C")
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

        # Extract event_name from extra_data if present (custom name set by seed/user)
        event_name = extra_data.get("event_name")
        if event_name:
            data["name"] = event_name

        data.pop("extra_data", None)  # Use pop with default to avoid KeyError if key doesn't exist

        # Calculate production-level USDA verification status
        # Only calculate carbon data if instance is a model instance with an ID
        if hasattr(instance, "id") and instance.id:
            try:
                from carbon.models import CarbonEntry

                carbon_entries = CarbonEntry.objects.filter(production=instance)
                total_entries = carbon_entries.count()

                if total_entries > 0:
                    usda_factors_based_entries = carbon_entries.filter(usda_factors_based=True).count()

                    # Production is USDA factors used if majority of entries are factors-based
                    production_usda_factors_used = usda_factors_based_entries >= (total_entries * 0.5)

                    # Add to extra_data for frontend
                    if data.get("extra_data") is None:
                        data["extra_data"] = {}

                    data["extra_data"]["usda_factors_used"] = production_usda_factors_used
                    data["extra_data"]["usda_verification_details"] = {
                        "total_entries": total_entries,
                        "usda_factors_based_entries": usda_factors_based_entries,
                        "verification_percentage": (
                            round((usda_factors_based_entries / total_entries * 100), 1) if total_entries > 0 else 0
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
                                    usda_factors_used=True,
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
                    # No carbon entries, so USDA factors not used
                    if data.get("extra_data") is None:
                        data["extra_data"] = {}
                    data["extra_data"]["usda_factors_used"] = False
                    data["extra_data"]["total_emissions"] = 0.0
                    data["extra_data"]["total_offsets"] = 0.0
                    data["extra_data"]["carbon_score"] = 50

            except Exception as e:
                instance_id = getattr(instance, "id", "unknown")
                print(f"Error calculating USDA verification for production {instance_id}: {e}")
                # Fallback to existing logic
                if data.get("extra_data") is None:
                    data["extra_data"] = {}
                data["extra_data"]["usda_factors_used"] = False
                data["extra_data"]["total_emissions"] = 0.0
                data["extra_data"]["total_offsets"] = 0.0
                data["extra_data"]["carbon_score"] = 50

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # Include custom fields in response for frontend display
        data = self.add_custom_fields_to_representation(data, instance)

        return data

    def update(self, instance, validated_data):
        # CRITICAL FIX: Set history and created_by from request (same as ViewSet logic)
        request = self.context.get("request")
        if request and not instance.history:
            from product.models import Parcel

            parcels = request.POST.getlist("parcels", None) or request.data.get("parcels", [])

            if parcels:
                parcel_id = parcels[0] if isinstance(parcels, list) else parcels
                try:
                    parcel = Parcel.objects.select_related("current_history").get(id=int(parcel_id))
                    if parcel.current_history:
                        validated_data["history"] = parcel.current_history
                        validated_data["created_by"] = request.user

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
                except Exception as e:
                    print(f"[UpdateWeatherEventSerializer.update] Error setting history: {e}")

        # NOTE: Album images (add/delete) are handled in EventViewSet.update
        # This ensures consistent behavior across all event types

        # Call parent update
        updated_instance = super().update(instance, validated_data)

        return updated_instance

    def create(self, validated_data):
        # Handle album images from S3 URLs (modern approach)
        request = self.context.get("request")
        album_images = request.data.get("album_images", []) if request else []

        if album_images:
            gallery = Gallery.objects.create()

            # Create GalleryImage records from S3 URLs
            for image_url in album_images:
                # Extract S3 key from URL if possible
                s3_key = image_url.split("/")[-1] if "/" in image_url else None
                gallery_image = gallery.images.create(image_url=image_url, s3_key=s3_key)

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

            if parcels:
                # Get the first parcel's current_history (matching ViewSet logic)
                parcel_id = parcels[0] if isinstance(parcels, list) else parcels
                try:
                    parcel = Parcel.objects.select_related("current_history").get(id=int(parcel_id))
                    if parcel.current_history:
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
                except (Parcel.DoesNotExist, ValueError) as e:
                    print(f"[UpdateWeatherEventSerializer.create] ERROR: Could not find parcel {parcel_id}: {e}")

        return super().create(validated_data)


class WeatherEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()
    weather_type = serializers.SerializerMethodField()

    class Meta:
        model = WeatherEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "event_type",
            "weather_type",
            "observation",
            "extra_data",
            "image",
            "carbon_data",
            "verification_level",
        ]
        read_only_fields = ["id", "index", "created_by"]

    def get_type(self, weather_event):
        type_display = weather_event.get_type_display()
        if type_display is None:
            return "event.weather.unknown"
        return f"event.weather.{type_display.lower().replace(' ', '_')}"

    def get_weather_type(self, weather_event):
        """Return raw weather type code (FR, DR, HL, HT, LT, HW, TS, FL, HH, LH) for frontend registry"""
        return weather_event.type

    def get_event_type(self, weather_event):
        return WEATHER_EVENT_TYPE

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Extract event_name from extra_data so frontend can access it as event.name
        extra_data = instance.extra_data or {} if hasattr(instance, "extra_data") else {}
        if extra_data.get("event_name"):
            data["name"] = extra_data["event_name"]

        # Flatten subtype-specific fields from extra_data to top level so the
        # timeline card, detail modal, and field registry can read them without
        # reaching into extra_data. Mirrors UpdateWeatherEventSerializer so list
        # and edit paths return the same shape.
        raw_type = instance.type if hasattr(instance, "type") else None
        if raw_type == WeatherEvent.FROST:
            data["lower_temperature"] = extra_data.get("lower_temperature")
            data["temperature_unit"] = extra_data.get("temperature_unit", "C")
            data["way_of_protection"] = extra_data.get("way_of_protection", "")
        elif raw_type == WeatherEvent.DROUGHT:
            data["water_deficit"] = extra_data.get("water_deficit")
        elif raw_type == WeatherEvent.HAILSTORM:
            data["duration"] = extra_data.get("duration")
            data["way_of_protection"] = extra_data.get("way_of_protection", "")
        elif raw_type == WeatherEvent.HIGH_TEMPERATURE:
            data["highest_temperature"] = extra_data.get("highest_temperature")
            data["temperature_unit"] = extra_data.get("temperature_unit", "C")
            data["start_date"] = extra_data.get("start_date", "")
            data["end_date"] = extra_data.get("end_date", "")
        elif raw_type == WeatherEvent.TROPICAL_STORM:
            data["wind_speed"] = extra_data.get("wind_speed")
            data["precipitation_amount"] = extra_data.get("precipitation_amount")
            data["duration"] = extra_data.get("duration")
            data["damage_assessment"] = extra_data.get("damage_assessment", "")
        elif raw_type == WeatherEvent.HIGH_WINDS:
            data["wind_speed"] = extra_data.get("wind_speed")
            data["duration"] = extra_data.get("duration")
            data["protection_measures"] = extra_data.get("protection_measures", "")
        elif raw_type in (WeatherEvent.HIGH_HUMIDITY, WeatherEvent.LOW_HUMIDITY):
            data["humidity_level"] = extra_data.get("humidity_level")
            data["duration"] = extra_data.get("duration")
            data["crop_impact"] = extra_data.get("crop_impact", "")

        # NOTE on description vs observation:
        # The frontend save path (NewEvent.jsx) renames observation → description
        # to satisfy CommonEvent's required description column. We intentionally
        # do NOT mirror description back to observation here — doing so makes the
        # EventDetailsModal render both fields (identical content) side by side.
        # Frontend renderers that need the farmer notes fall back to description:
        #   - EnhancedTimelineRow.getEnhancedDescription checks both
        #   - eventDataNormalizer mirrors description→observation for Consumer card
        # Leaving observation empty here keeps the detail modal from duplicating.

        return data


class UpdateProductionEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = ProductionEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "observation",
            "extra_data",
            "name",
            "area_covered",
            "area_unit",
            "yield_quantity",
            "yield_unit",
            "fuel_consumed",
            "fuel_unit",
            "fuel_type",
            "equipment_hours",
            "transportation_distance",
            "transportation_unit",
            "production_efficiency",
            "seeds_source",
            "water_source",
            "irrigation_method",
            "irrigation_depth",
            "irrigation_depth_unit",
            "brix_level",
            "equipment_type",
            "equipment_operation_type",
            "harvest_quality_grade",
            "grain_moisture",
            "dry_matter_percentage",
            "pump_depth_ft",
            "electricity_source",
            "water_test_date",
            "water_test_lab",
            "water_test_results",
            # NOP compliance — seed sourcing & equipment cleaning
            "seed_search_attempts",
            # NOP 7 CFR 205.204 — seed traceability (planting subtype)
            "seed_supplier_name",
            "seed_purchase_date",
            "seed_purchase_invoice",
            "seed_lot_number",
            "seed_certification_status",
            "seed_treatment",
            "cleaning_date",
            "cleaning_method",
            "cleaning_materials_used",
            "cleaned_by",
            "shared_with_conventional",
            "cleaning_protocol_reference",
            # §E-5 — custom operator + the cleaning that covers this operation (§ 205.272)
            "operator_is_custom",
            "equipment_cleaning_event",
            # NOP Compliance: Post-Harvest Sanitizer Detail (7 CFR 205.272 + § 205.605)
            "sanitizer_name",
            "sanitizer_ppm",
            "sanitizer_residual_ppm_at_discharge",
            "rinse_step_documented",
            "sanitizer_nop_reference",
            # Sprint 3.2 — Post-harvest storage (NOP 205.272 / FSMA 204 KDE)
            "storage_location",
            "storage_temperature_f",
        ]
        read_only_fields = ["id"]

    # Fields captured from Quick Add forms that are stored in extra_data
    # (not model fields on ProductionEvent, but valuable for consumer display)
    # NOTE: equipment_type and equipment_operation_type were removed from here —
    # they are top-level model fields on ProductionEvent (EM subtype), not extra_data.
    # Having them here caused them to be popped from data before model save,
    # resulting in NULL model columns after save.
    EXTRA_DATA_FIELDS = [
        "harvest_method",
        "brix_levels",
        "native_species_planted",
        "habitat_area_hectares",
        # Post-Harvest Processing (PH subtype) — form fields with no model columns
        "processing_type",
        "processing_duration_hours",
        "temperature_control",
        # F42 fix (2026-06): Canopy Management (CM subtype) — form fields with no
        # model columns. Previously persisted only via the tab's nested extra_data;
        # a flat submission would silently drop them. Listing here ensures both the
        # nested and flat shapes round-trip.
        "canopy_operation",
        "pass_number",
        # Batch 3 (2026-06): Frost Protection (FP) + Mowing (MO) subtype fields with
        # no model columns. Fuel/equipment/area use existing ProductionEvent columns.
        "protection_method",  # FP: wind_machine / orchard_heater / under_tree_sprinkler
        "low_temperature",  # FP: low temp that triggered protection
        "floor_management_type",  # MO: mow / mulch / cover_crop_mgmt / flame_weed
        # A9 fix (2026-07): `method` was in the READ serializer's EXTRA_DATA_FIELDS but
        # missing here, so a flat `method=` POST was silently discarded and only a nested
        # extra_data.method survived. That single omission disabled the manual-operation
        # carbon short-circuit (_is_manual_method in event_carbon_calculator): a hand
        # harvest, hand thinning or hand pruning was billed the USDA MECHANICAL average
        # (0.7 gal/ha for HA) instead of the ~0.1 kg/acre manual figure. Hand work is
        # standard practice in a California organic orchard, so the labour-intensive
        # grower was over-charged for the operation precisely because it was manual.
        "method",
    ]

    def to_internal_value(self, data):
        """Handle custom fields and extra_data fields for production events."""
        data = data.copy()
        ensure_event_description(data, "Production activity")  # F01: avoid silent 400 on blank notes

        # Map EM-specific operation_efficiency → production_efficiency (model field)
        if "operation_efficiency" in data and "production_efficiency" not in data:
            data["production_efficiency"] = data.pop("operation_efficiency")

        # Extract frontend's extra_data BEFORE super() call
        # Frontend sends summary mode fields (is_summary, date_start, event_count, etc.)
        # inside extra_data
        frontend_extra_data = data.pop("extra_data", {}) or {}

        # Handle custom fields (user-defined additional information)
        custom_fields = self.handle_custom_fields_input(data)

        # Extract fields that should go into extra_data (not model fields)
        extra_fields = {}
        for field_name in self.EXTRA_DATA_FIELDS:
            value = data.pop(field_name, None)
            if value is not None and value != "":
                extra_fields[field_name] = value

        # Extract summary-only fields (NOT model fields) sent at top level
        summary_only_fields = [
            "is_summary",
            "date_start",
            "date_end",
            "event_count",
            "water_volume_total",
            "water_volume_unit",
            # Harvest summary fields
            "yield_total",
            "yield_total_unit",
        ]
        for field_name in summary_only_fields:
            if field_name in data:
                value = data.pop(field_name)
                if value is not None and value != "":
                    frontend_extra_data[field_name] = value

        # Move model fields that frontend packed into extra_data back to data
        # so ModelSerializer processes them into model columns
        model_irrigation_fields = [
            "water_source",
            "irrigation_method",
            "irrigation_depth",
            "irrigation_depth_unit",
        ]
        for field_name in model_irrigation_fields:
            if field_name in frontend_extra_data and field_name not in data:
                data[field_name] = frontend_extra_data.pop(field_name)

        # Convert empty strings to None for optional DATE fields. The form posts EVERY production
        # field for every subtype, so a non-planting event (irrigation, pruning, etc.) sends
        # seed_purchase_date="", the pollination dates="", and a non-cleaning event sends
        # cleaning_date="" — DRF's DateField rejects "" and the whole event 400s. Introspect every
        # nullable date field so no hand-maintained list can miss one (cleaning_date was missed).
        coerce_blank_nullable_dates(self, data)

        internal_value = super().to_internal_value(data)

        # Get existing extra_data from instance (for updates)
        instance = getattr(self, "instance", None)
        existing_extra_data = instance.extra_data if instance and instance.extra_data else {}

        # Merge: existing + frontend extra_data + Quick Add extra fields
        merged_extra_data = {**existing_extra_data, **frontend_extra_data}

        # Merge Quick Add extra fields into extra_data
        if extra_fields:
            merged_extra_data.update(extra_fields)

        # Handle custom_fields
        if custom_fields:
            merged_extra_data["custom_fields"] = custom_fields
        elif instance and instance.extra_data and "custom_fields" in instance.extra_data:
            merged_extra_data["custom_fields"] = instance.extra_data["custom_fields"]

        internal_value["extra_data"] = merged_extra_data

        return internal_value

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
        # Equipment Maintenance (EM), Pollination (PO), and Post-Harvest Processing (PH)
        # events can legitimately have area_covered=0 (facility/equipment-based, not field-based).
        production_type = data.get("type", "")
        # FP (Frost Protection) is equipment-hours-driven (wind machines/heaters) like
        # EM — area protected may legitimately be left at 0. MO (Mowing) keeps the >0
        # rule since orchard-floor area is meaningful.
        area_zero_allowed_types = ["EM", "PO", "PH", "FP"]
        if area_covered is not None and area_covered <= 0 and production_type not in area_zero_allowed_types:
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
        # UPDATED: Allow realistic multi-day agricultural operations (e.g., 120 hours pruning)
        # Max 1000 hours = ~125 days of 8-hour work, reasonable for seasonal operations
        if equipment_hours is not None and equipment_hours > 1000:
            raise serializers.ValidationError(
                {
                    "equipment_hours": [
                        f"Equipment hours ({equipment_hours}h) exceeds maximum for a single event.",
                        "Maximum allowed is 1000 hours per event.",
                        "Tip: For very long operations, consider creating separate seasonal events.",
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

        # Brix level validation
        brix_level = data.get("brix_level")
        if brix_level is not None and brix_level < 0:
            raise serializers.ValidationError({"brix_level": "Brix level cannot be negative."})
        if brix_level is not None and brix_level > 45:
            raise serializers.ValidationError({"brix_level": "Brix level cannot exceed 45."})

        # NOP 5029 / 7 CFR 205.204(a)(1): non-organic seed/planting stock on a planting (PL)
        # event requires a documented commercial-availability search of >= 3 suppliers. The
        # planting form now ships the seed-search widget (ProductionTab.jsx, gated on a
        # non-organic seed certification status), so the farmer CAN satisfy this — enforce it on
        # the API save path too (DRF does not call the model's clean()). This serializer handles
        # both create and update; fall back to the instance on partial updates.
        seed_cert_status = data.get("seed_certification_status")
        if seed_cert_status is None and self.instance is not None:
            seed_cert_status = getattr(self.instance, "seed_certification_status", None)
        pl_type = production_type or (getattr(self.instance, "type", "") if self.instance else "")
        if pl_type == "PL" and seed_cert_status in ("non_organic_untreated", "non_organic_treated"):
            attempts = data.get("seed_search_attempts")
            if attempts is None and self.instance is not None:
                attempts = getattr(self.instance, "seed_search_attempts", None)
            attempts = attempts or []
            if len(attempts) < 3:
                raise serializers.ValidationError(
                    {
                        "seed_search_attempts": [
                            "NOP 5029 (7 CFR 205.204(a)(1)) requires documentation of at least 3 "
                            "supplier searches when using non-organic seed or planting stock.",
                            f"Current search attempts: {len(attempts)}. Add more suppliers before saving.",
                        ]
                    }
                )

        return data

    def to_representation(self, instance):
        """Override to serialize album with images and extract extra_data fields"""
        data = super().to_representation(instance)

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # Include custom fields in response for frontend display
        data = self.add_custom_fields_to_representation(data, instance)

        # Extract EXTRA_DATA_FIELDS from extra_data back to top level
        # so the frontend form can populate them when editing
        extra_data = getattr(instance, "extra_data", None) or {}
        for field_name in self.EXTRA_DATA_FIELDS:
            if field_name in extra_data and field_name not in data:
                data[field_name] = extra_data[field_name]

        # Backward compat: recover equipment fields from extra_data if model column is empty
        for field_name in ("equipment_type", "equipment_operation_type"):
            if not data.get(field_name) and field_name in extra_data:
                data[field_name] = extra_data[field_name]

        # Map production_efficiency back to operation_efficiency for frontend form
        if data.get("production_efficiency"):
            data["operation_efficiency"] = data["production_efficiency"]

        return data


class ProductionEventSerializer(CustomFieldsMixin, EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()
    production_type = serializers.SerializerMethodField()  # NEW: Actual type code for frontend logic

    class Meta:
        model = ProductionEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "event_type",
            "production_type",
            "observation",
            "extra_data",
            "name",
            "area_covered",
            "area_unit",
            "yield_quantity",
            "yield_unit",
            "fuel_consumed",
            "fuel_unit",
            "fuel_type",
            "equipment_hours",
            "transportation_distance",
            "transportation_unit",
            "production_efficiency",
            "seeds_source",
            "water_source",
            "irrigation_method",
            "irrigation_depth",
            "irrigation_depth_unit",
            "brix_level",
            "equipment_type",
            "equipment_operation_type",
            "harvest_quality_grade",
            "grain_moisture",
            "dry_matter_percentage",
            "pump_depth_ft",
            "electricity_source",
            "water_test_date",
            "water_test_lab",
            "water_test_results",
            "image",
            "carbon_data",
            "verification_level",
            # NOP compliance — seed sourcing & equipment cleaning
            "seed_search_attempts",
            # NOP 7 CFR 205.204 — seed traceability (planting subtype)
            "seed_supplier_name",
            "seed_purchase_date",
            "seed_purchase_invoice",
            "seed_lot_number",
            "seed_certification_status",
            "seed_treatment",
            "cleaning_date",
            "cleaning_method",
            "cleaning_materials_used",
            "cleaned_by",
            "shared_with_conventional",
            "cleaning_protocol_reference",
            # §E-5 — custom operator + the cleaning that covers this operation (§ 205.272)
            "operator_is_custom",
            "equipment_cleaning_event",
            # NOP Compliance: Post-Harvest Sanitizer Detail (7 CFR 205.272 + § 205.605)
            "sanitizer_name",
            "sanitizer_ppm",
            "sanitizer_residual_ppm_at_discharge",
            "rinse_step_documented",
            "sanitizer_nop_reference",
            # Sprint 3.2 — Post-harvest storage
            "storage_location",
            "storage_temperature_f",
        ]
        read_only_fields = ["id", "index", "created_by"]

    def get_type(self, production_event):
        type_display = production_event.get_type_display()
        if type_display is None:
            return "event.production.unknown"
        return f"event.production.{type_display.lower().replace(' ', '_')}"

    def get_event_type(self, production_event):
        return PRODUCTION_EVENT_TYPE

    def get_production_type(self, production_event):
        """Return the actual production type code (PL, HA, TR, etc.) for frontend conditionals"""
        return production_event.type or ""

    # Same EXTRA_DATA_FIELDS as UpdateProductionEventSerializer for consistent extraction
    # NOTE: equipment_type and equipment_operation_type removed — they are model fields.
    EXTRA_DATA_FIELDS = [
        "harvest_method",
        "brix_levels",
        "native_species_planted",
        "habitat_area_hectares",
        # Post-Harvest Processing (PH subtype) — form fields with no model columns
        "processing_type",
        "processing_duration_hours",
        "temperature_control",
        # Operation method free-text (drives manual-labor carbon detection). Stored as
        # extra_data.method; promoted to top-level so the Event Details Modal's registry
        # resolver finds it without needing the formatter's extra_data fallback.
        "method",
        # F42 fix (2026-06): Canopy Management (CM subtype) fields — see the matching
        # note on UpdateProductionEventSerializer.EXTRA_DATA_FIELDS above.
        "canopy_operation",
        "pass_number",
        # Batch 3 (2026-06): Frost Protection (FP) + Mowing (MO) subtype fields.
        "protection_method",
        "low_temperature",
        "floor_management_type",
    ]

    def to_representation(self, instance):
        """Override to include custom fields and serialize album with images"""
        data = super().to_representation(instance)

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # CRITICAL FIX: Include custom fields in response for frontend display (ProductDetail needs this)
        data = self.add_custom_fields_to_representation(data, instance)

        # Extract EXTRA_DATA_FIELDS from extra_data back to top level
        extra_data = getattr(instance, "extra_data", None) or {}
        for field_name in self.EXTRA_DATA_FIELDS:
            if field_name in extra_data and field_name not in data:
                data[field_name] = extra_data[field_name]

        # Backward compat: equipment_type/equipment_operation_type were previously
        # stored in extra_data due to EXTRA_DATA_FIELDS bug. Recover them if the
        # model column is empty but extra_data has the value.
        for field_name in ("equipment_type", "equipment_operation_type"):
            if not data.get(field_name) and field_name in extra_data:
                data[field_name] = extra_data[field_name]

        # Map production_efficiency back to operation_efficiency for frontend form
        if data.get("production_efficiency"):
            data["operation_efficiency"] = data["production_efficiency"]

        return data


class UpdateGeneralEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = GeneralEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "name",
            "observation",
            "activity_type",
            "activity_name",
            "duration",
            "people_involved",
            "extra_data",
            # NOP Compliance: Contamination Incident Reporting
            "is_contamination_incident",
            "contamination_source",
            "contamination_affected_area",
            "corrective_action_taken",
            "corrective_action_date",
            "certifier_notified",
            "certifier_notification_date",
        ]
        read_only_fields = ["id"]

    def to_internal_value(self, data):
        """Handle custom fields and field name remapping for general events."""
        data = data.copy()
        ensure_event_description(data, "Farm activity")  # F01: avoid silent 400 on blank notes

        # Convert empty strings to None for nullable fields (contamination incident fields)
        nullable_fields = [
            "contamination_source",
            "contamination_affected_area",
            "corrective_action_taken",
            "corrective_action_date",
            "certifier_notification_date",
            "people_involved",
        ]
        for field_name in nullable_fields:
            if field_name in data and data[field_name] in ("", None):
                data[field_name] = None

        # Handle custom fields (user-defined additional information)
        custom_fields = self.handle_custom_fields_input(data)

        # Extract frontend's extra_data BEFORE super() call
        frontend_extra_data = data.pop("extra_data", {}) or {}

        # Remap frontend field names to model field names (safety net for any
        # frontend that hasn't been updated yet - primary remapping is in NewEvent.jsx)
        field_remapping = {
            "duration_hours": "duration",
            "participants": "people_involved",
            "type": "activity_type",
        }
        for form_name, model_name in field_remapping.items():
            if form_name in data and model_name not in data:
                data[model_name] = data.pop(form_name)

        internal_value = super().to_internal_value(data)

        # Merge: existing extra_data + frontend extra_data (frontend wins on conflicts)
        instance = getattr(self, "instance", None)
        existing_extra_data = instance.extra_data if instance and instance.extra_data else {}
        merged_extra_data = {**existing_extra_data, **frontend_extra_data}

        # Handle custom_fields inline
        if custom_fields:
            merged_extra_data["custom_fields"] = custom_fields
        elif instance and instance.extra_data and "custom_fields" in instance.extra_data:
            merged_extra_data["custom_fields"] = instance.extra_data["custom_fields"]

        internal_value["extra_data"] = merged_extra_data

        return internal_value

    def to_representation(self, instance):
        """Override to serialize album with images instead of just ID"""
        data = super().to_representation(instance)

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # Include custom fields in response for frontend display
        data = self.add_custom_fields_to_representation(data, instance)

        return data


class GeneralEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = GeneralEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "event_type",
            "name",
            "observation",
            "activity_type",
            "activity_name",
            "duration",
            "people_involved",
            "extra_data",
            # NOP Compliance: Contamination Incident Reporting
            "is_contamination_incident",
            "contamination_source",
            "contamination_affected_area",
            "corrective_action_taken",
            "corrective_action_date",
            "certifier_notified",
            "certifier_notification_date",
            "image",
            "carbon_data",
            "verification_level",
        ]
        read_only_fields = ["id", "index", "created_by"]

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
    events_count = serializers.IntegerField(source="total_events_count", read_only=True, default=0)

    class Meta:
        model = History
        fields = [
            "id",
            "public_id",
            "start_date",
            "expected_harvest",
            "finish_date",
            "name",
            "type",
            "published",
            "production_method",
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
            "events_count",  # Annotated count of all events
            "extra_data",  # Include for carbon data
        ]
        read_only_fields = ["id", "public_id"]

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
                usda_factors_based_entries = carbon_entries.filter(usda_factors_based=True).count()

                # Production is USDA factors used if majority of entries are factors-based
                production_usda_factors_used = usda_factors_based_entries >= (total_entries * 0.5)

                # Add to extra_data for frontend
                if data.get("extra_data") is None:
                    data["extra_data"] = {}

                data["extra_data"]["usda_factors_used"] = production_usda_factors_used
                data["extra_data"]["usda_verification_details"] = {
                    "total_entries": total_entries,
                    "usda_factors_based_entries": usda_factors_based_entries,
                    "verification_percentage": (
                        round((usda_factors_based_entries / total_entries * 100), 1) if total_entries > 0 else 0
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
                                usda_factors_used=True,
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
                # No carbon entries, so USDA factors not used
                if data.get("extra_data") is None:
                    data["extra_data"] = {}
                data["extra_data"]["usda_factors_used"] = False
                data["extra_data"]["total_emissions"] = 0.0
                data["extra_data"]["total_offsets"] = 0.0
                data["extra_data"]["carbon_score"] = 50

        except Exception as e:
            print(f"Error calculating USDA verification for production {instance.id}: {e}")
            # Fallback to existing logic
            if data.get("extra_data") is None:
                data["extra_data"] = {}
            data["extra_data"]["usda_factors_used"] = False
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


class HistoryWriteSerializer(serializers.ModelSerializer):
    """Lean serializer for create/update — no nested events/images/members."""

    product = serializers.SerializerMethodField()
    parcel = serializers.SerializerMethodField()
    crop_type = serializers.SerializerMethodField()

    class Meta:
        model = History
        fields = [
            "id",
            "public_id",
            "start_date",
            "expected_harvest",
            "finish_date",
            "name",
            "type",
            "published",
            "production_method",
            "parcel",
            "product",
            "crop_type",
            "is_outdoor",
            "age_of_plants",
            "number_of_plants",
            "soil_ph",
            "lot_id",
            "production_amount",
            "production_unit",
            "quality_grade",
            "harvest_method",
            "description",
            "events_status",
            # Consumer QR hero/cover override (see PublicHistorySerializer.get_images)
            "cover_image_url",
            # Post-harvest traceability (§ 205.103 + SOE 2024 non-retail invoice)
            "sold_to",
            "sale_date",
            "quantity_sold",
            "quantity_sold_unit",
            "box_weight_lb",
            "organic_on_invoice",
            "transport_method",
            "destination",
            "transport_vehicle_id",
            "transport_affidavit_on_file",
            "transport_affidavit_document",
            "retention_until",
        ]
        read_only_fields = ["id", "public_id", "events_status", "retention_until"]

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
            "public_id",
            "start_date",
            "expected_harvest",
            "finish_date",
            "name",
            "type",
            "published",
            "production_method",
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
            "events_status",
            # NOP compliance — post-finish sales & traceability
            "sold_to",
            "sale_date",
            "quantity_sold",
            "quantity_sold_unit",
            "box_weight_lb",
            "organic_on_invoice",
            "transport_method",
            "destination",
            "transport_vehicle_id",
            "transport_affidavit_on_file",
            "transport_affidavit_document",
            "retention_until",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "created_at",
            "updated_at",
            "certificate_percentage",
            "events_status",
            "retention_until",
        ]

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

            # Explicit hero/cover override (set by staff in the admin or the finish-production
            # flow). Surfaced FIRST so it becomes images[0] -> the consumer hero background and
            # the lead gallery photo. The dedup pass below keeps it at index 0 even if the same
            # URL also appears in the album/events. Blank -> auto-pick (album then timeline).
            cover_url = getattr(history, "cover_image_url", None)
            if cover_url:
                images.append(cover_url)

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
        location = history_scan.get_location_display()
        return location or "-"

    def get_parcel(self, history_scan):
        return history_scan.history.parcel.name if history_scan.history.parcel else None


class PublicProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "name"]


class PublicEstablishmentSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    company_name = serializers.CharField(source="company.name", read_only=True)
    # Same redaction the transparency endpoint applies — this is the second public payload
    # shape, and it was publishing "45% premium pricing" from the same free-text field.
    description = serializers.SerializerMethodField()

    class Meta:
        model = Establishment
        fields = ["id", "name", "description", "location", "company_name"]

    def get_description(self, establishment):
        return public_free_text(establishment.description)

    def get_location(self, establishment):
        return establishment.get_location()


class PublicParcelSerializer(serializers.ModelSerializer):
    establishment = PublicEstablishmentSerializer()
    # Phase 3 privacy — geo fields gated by Parcel.location_disclosure_level
    # (see history/services/privacy.py; a public field polygon is a
    # theft/scouting exposure unless the farmer opted in to exact).
    polygon = serializers.SerializerMethodField()
    map_metadata = serializers.SerializerMethodField()
    location_disclosure_level = serializers.CharField(read_only=True)

    class Meta:
        model = Parcel
        fields = [
            "id",
            "name",
            "polygon",
            "map_metadata",
            "location_disclosure_level",
            "establishment",
            "agricultural_details",
        ]

    def get_polygon(self, parcel):
        return public_parcel_geo(parcel)["polygon"]

    def get_map_metadata(self, parcel):
        return public_parcel_geo(parcel)["map_metadata"]


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
    events_count = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    product = PublicProductSerializer(read_only=True)
    parcel = PublicParcelSerializer(read_only=True)
    qr_code = serializers.SerializerMethodField()
    operator = BasicUserSerializer(read_only=True)

    class Meta:
        model = History
        fields = [
            "public_id",
            "name",
            "start_date",
            "finish_date",
            "published",
            "product",
            "parcel",
            "qr_code",
            "reputation",
            "is_outdoor",
            "events",
            "events_count",
            "images",
            "cover_image_url",
            "operator",
            "lot_id",
            "production_amount",
            "production_unit",
            "description",
            "type",
            "transparency_score",
            "production_method",
            # Post-harvest traceability (§ 205.103 + SOE 2024 non-retail invoice).
            # These are B2B-sensitive (buyer name, delivery address, sale quantity)
            # and MUST be hidden from public QR viewers — to_representation below
            # strips them for any non-owner caller.
            "sold_to",
            "sale_date",
            "quantity_sold",
            "quantity_sold_unit",
            "box_weight_lb",
            "organic_on_invoice",
            "transport_method",
            "destination",
            "retention_until",
        ]

    # Fields only the production's owning company may see in this serializer's
    # response. Any consumer hitting /public_history/ via QR code is NOT the
    # owner, so these get stripped before serialization returns.
    _OWNER_ONLY_FIELDS = (
        # operator is a BasicUserSerializer — it carries the grower's email, phone,
        # is_superuser, user_type, and worksin_set (EVERY other company and
        # establishment that user runs). On an anonymous QR payload that is a direct
        # PII exposure plus a cross-farm disclosure: scanning one product would reveal
        # the grower's contact details and their unrelated operations. The consumer
        # page never reads it — farm identity comes from parcel.establishment (and
        # transparency_views' own farmer block) — so stripping costs no consumer content.
        "operator",
        "sold_to",
        "sale_date",
        "quantity_sold",
        "quantity_sold_unit",
        "box_weight_lb",
        "organic_on_invoice",
        "transport_method",
        "destination",
        "retention_until",
    )

    # NOP-alignment audit (2026-06) — event-level fields that are certifier/audit-only
    # or self-graded and MUST NOT reach the public consumer payload. Every field here
    # remains fully available to the certifier through the NOP audit PDF, which reads the
    # event models directly (audit_export_service), so this strip does not reduce
    # certifier coverage by one byte.
    #   • REI / PHI / RUP / EPA-reg / CA-DPR protect FARM WORKERS or are enforcement
    #     identifiers — on a consumer page they falsely imply a CONSUMER hazard (EPA 2024)
    #     and carry no consumer meaning.
    #   • concentration / volume / NPK% / buffer_zone_meters / is_fertigation are agronomic
    #     audit data with no consumer value.
    #   • applicator_name is additionally a worker-name privacy exposure (CCPA).
    # NOTE: verification_level (a documentation-evidence tier) is intentionally NOT in this
    # set. The consumer card couples it to photo-evidence display (ConsumerEventCard.tsx
    # ~1093/~1822 gate the photo gallery + photo-count chip on it), and its values
    # ("Self-Reported"/"Photo-Verified") are honest factual documentation labels, not the
    # numeric self-graded sustainability score that ECGT/FTC target. Stripping it here would
    # hide the photos (evidence-first content we must KEEP). The grade-like-badge concern is
    # deferred to a paired backend+frontend change; transparency_score below is the
    # unambiguous self-graded metric and IS stripped.
    _CERTIFIER_ONLY_EVENT_FIELDS = (
        "rei_hours",
        "phi_days",
        "restricted_use_pesticide",
        "epa_registration_number",
        "ca_dpr_permit_number",
        "ca_dpr_permit_county",
        "ca_dpr_permit_expires",
        "applicator_name",
        "applicator_certification",
        "concentration",
        "volume",
        "volume_unit",
        "nitrogen_percentage",
        "phosphorus_percentage",
        "potassium_percentage",
        # §E-3 — an application RATE is a certifier detail (same class as the NPK percentages);
        # micronutrient_type stays consumer-visible because "zinc" is plain language.
        "micronutrient_rate",
        "micronutrient_rate_unit",
        "is_fertigation",
        "buffer_zone_meters",
        # --- Added 2026-07-31 (consumer editorial review) -------------------------------
        # These were briefly DELETED from get_events() outright, which silently broke the
        # producer's own dashboard: PublicHistorySerializer also feeds the ProfileProduction
        # timeline (via carbon complete_summary, which passes request context), and
        # DriftFindingsBanner reads `drift_warning` from exactly that data. Owner-gating is
        # the correct mechanism — it keeps the producer whole and the consumer clean.
        #
        # `drift_warning`: internal OSP nonconformance narrative + osp_id/osp_version + CFR
        # citation; also nests an optional ca_dpr_permit_status.permit_number.
        "drift_warning",
        # `cleaned_by`: free-text worker name — the same class `_public_performer()` masks
        # and `applicator_name` strips.
        "cleaned_by",
        # Internal operator document references / raw regulatory citations.
        "cleaning_protocol_reference",
        "sanitizer_nop_reference",
        # Raw soil-lab JSONField (whole panel + lab identity). The curated §E-2 facts
        # (sample_matrix / lab_name / lab_report_date) are separate keys and stay public.
        "test_results",
        # --- Added 2026-08-01 (consumer editorial review, round 2) ----------------------
        # `verification_status` is FARMER-ENTERED on a business/certification event. It
        # rendered on the public card as a Key Detail reading "Verification Status: Verified"
        # — directly above the card's own "Self Reported" chip. A self-attested "Verified"
        # on a consumer surface is the EU ECGT 2024/825 self-created-label risk and an FTC
        # 16 CFR 260.6 problem; the certificate number and certifier name (which a buyer can
        # actually check) stay public, so nothing checkable is lost.
        #
        # NOT the same field as Certification.verification_status on the FARM, which backs
        # the "Verified via USDA Organic Integrity Database" badge — that one is a database
        # cross-reference Trazo performs, not a claim the farmer types.
        "verification_status",
        # --- Added 2026-08-03 -----------------------------------------------------------
        # `photo_content_flag` is the INTERNAL anti-gaming verdict from the Vision check
        # (`not_agricultural` / `ai_generated` / `stock_photo`). Reproduced live on an
        # anonymous payload: timeline[1].photo_content_flag == "not_agricultural".
        #
        # It is moderation state about the FARMER, published to shoppers — the same
        # "self-incriminating audit data" class as `drift_warning` above, and arguably worse
        # because it reads as Trazo accusing its own customer on the customer's public page.
        # The transparency calculator already consumes it internally to withhold photo credit;
        # nothing consumer-facing needs it.
        "photo_content_flag",
    )

    # The transparency SCORE is a PRODUCER-dashboard KPI only. A self-assigned grade on a
    # consumer surface is the EU ECGT 2024/825 / FTC 16 CFR 260.6 self-created-label risk,
    # so it is stripped for every non-owner caller (Trazo Test #5).
    _SELF_GRADED_FIELDS = ("transparency_score",)

    def _is_owner(self, obj):
        # `force_public_view` makes the owner exemption inapplicable. Set it on any surface
        # that IS the consumer page, so the producer sees exactly what a shopper sees.
        # Without it, a logged-in grower scanning their own QR link got the UNSTRIPPED
        # payload — REI, PHI, applicator name, EPA registration number rendered on their
        # own product page — and had no way to tell that the public version differs.
        # Pairs with EventPreviewModal's `toConsumerVisibleEvent` on the frontend.
        context = getattr(self, "context", None) or {}
        if context.get("force_public_view"):
            return False
        request = context.get("request")
        if not request or not getattr(request, "user", None):
            return False
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        company = obj.parcel.establishment.company if obj.parcel and obj.parcel.establishment else None
        if company is None:
            return False
        return user.companies.filter(id=company.id).exists()

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if not self._is_owner(obj):
            for field in self._OWNER_ONLY_FIELDS:
                data.pop(field, None)
            # B0 — strip the self-graded production-level score for anonymous consumers.
            for field in self._SELF_GRADED_FIELDS:
                data.pop(field, None)
            # B0/B1 — strip certifier/audit-only and self-graded fields from every event
            # dict. pop() is no-op when a key is absent, so this applies uniformly across
            # all event types without per-type branching.
            events = data.get("events")
            if isinstance(events, list):
                for event in events:
                    if isinstance(event, dict):
                        for field in self._CERTIFIER_ONLY_EVENT_FIELDS:
                            event.pop(field, None)
                        # Defense-in-depth: the same certifier/worker-safety keys can also ride
                        # inside event["extra_data"] (the V2 templates write REI/PHI there).
                        # get_events already routes extra_data through the allow-list sanitizer,
                        # but scrub here too so any event-dict path is covered.
                        nested = event.get("extra_data")
                        if isinstance(nested, dict):
                            for field in self._CERTIFIER_ONLY_EVENT_FIELDS:
                                nested.pop(field, None)
        return data

    def get_events_count(self, obj):
        """Total count of documented farming events for this production."""
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
            manager = getattr(obj, attr, None)
            if manager is not None:
                try:
                    # Use prefetched cache if available, else query
                    count += len(manager.all())
                except Exception:
                    pass
        return count

    @staticmethod
    def _public_performer(event, show_full_names):
        """
        Consent-gated performer display for the public consumer payload.

        Worker full names on a public page paired with the farm's location are
        a CCPA exposure and a doxing vector. Unless the establishment opted in
        (Establishment.show_full_performer_names), mask to "Farm team (A.T.)".
        Mirrors the frontend's maskPerformerName so both layers agree.
        """
        name = getattr(event, "performed_by", None)
        if not name:
            return name
        if show_full_names:
            return name
        parts = [p for p in str(name).strip().split() if p]
        initials = ".".join(p[0].upper() for p in parts[:2])
        return f"Farm team ({initials}.)" if initials else "Farm team"

    # ALLOW-LIST for the PUBLIC consumer payload's free-form extra_data JSON.
    #
    # extra_data is an open dict — a deny-list there is whack-a-mole (the 2026-06 audit found
    # buyer identity, pricing/margin, invoices, logistics, audit findings, inspector PII, and
    # supplier identities leaking under ~30 different key names, several aliasing past the old
    # deny-list: auditor / audit_score / inspected_by / major_nc, cost_vs_conventional /
    # hive_rental_per_colony / premium_market_percentage, nursery / bee_source / processor /
    # lab_name, and original_extra_data which re-embedded the whole unsanitized blob).
    #
    # This is the durable fix: ONLY keys on this allow-list reach the consumer. Any unknown key
    # — including every future one — is dropped by default (safe). The set was derived empirically
    # from the union of agronomic/consumer-transparency keys present across all published
    # productions, with commercial / PII / audit / logistics / internal-debug keys removed.
    #
    # TOUCHPOINT: a NEW consumer-facing extra_data key will NOT display until added here. That is
    # the intended trade-off (silent-drop of a benign field beats silent-leak of a sensitive one).
    # Sensitive keys deliberately EXCLUDED: cost*/price*/premium*/revenue, buyer_*/invoice/PO/BOL,
    # *supplier*/nursery/bee_source/processor/lab_name/source/manure_source/compost_source,
    # auditor/audit_*/inspector/inspected_by/*_nc/control_points, carrier/trailer*/destination*/
    # transit*/departure*, original_*/ui_*/migrated_from/test_production/*_template_id, attestations.
    ALLOWED_EXTRA_DATA_KEYS = frozenset(
        {
            "acid_ratio",
            "acre_feet_per_acre",
            "action_recommended",
            "active_ingredient",
            "active_ingredient_total_kg",
            "amount",
            "application_conditions",
            "application_details",
            "application_fuel",
            "application_fuel_consumed",
            "application_fuel_type",
            "application_fuel_unit",
            "application_method",
            "application_rate",
            "application_rate_oz_acre",
            "application_rate_range",
            "application_rate_tons_acre",
            "application_timing",
            "area_covered_total",
            "area_hectares",
            "area_treated",
            "area_treated_total",
            "area_unit",
            "average_pest_pressure",
            "avg_fruit_weight_oz",
            "avg_mites_per_trap",
            "band_distance_m",
            "beneficial_insect_presence",
            "beneficial_insects_released",
            "beneficial_insects_supported",
            "bins_filled",
            "biocontrol_target",
            "biodiversity_enhancement",
            "biodiversity_score_improvement",
            "biomass_chipped_tons",
            "biomass_disposition",
            "biomass_production",
            "biomass_removed_kg",
            "blockchain_block_number",
            "blockchain_hash",
            "blockchain_transaction",
            "blockchain_verified",
            "blocks",
            "bloom_end",
            "bloom_peak",
            "bloom_start",
            "brix_avg",
            "brix_level",
            "brix_levels",
            "buffer_zone_meters",
            "c_n_ratio",
            "c_to_n_ratio",
            "calcium_content_percent",
            "canopy_operation",
            "canopy_removed_pct",
            "canopy_target_height_ft",
            "carbon_impact",
            "carbon_score",
            "carton_weight_lbs",
            "cartons_packed",
            "cartons_shipped",
            "chemical_free_period_days",
            "chemical_subtype",
            "chemical_treatments_avoided",
            "cimis_et0_inches_day",
            "cimis_station",
            "cleaning_protocol",
            "clipping_disposition",
            "cn_ratio",
            "cold_storage_days",
            "colonies_per_acre",
            "colonies_placed",
            "colonies_removed",
            "colony_strength",
            "color_break_percent",
            "compost_age_months",
            "compost_ph",
            "compost_temperature_reached_131f",
            "composted",
            "consumer_ready",
            "cooler_humidity_pct",
            "cooling_methods",
            "copper_metallic_pct",
            "cover_crop_species",
            "coverage_pattern",
            # Biodiversity / habitat (HD / NS) — consumer-safe documented facts, no PII
            "species_planted",
            "wildlife_observed",
            "structure_notes",
            "crew_size",
            "crop_damage_prevented",
            "crop_growth_stage",
            "crop_impact",
            "crop_safety",
            "custom_fields",
            "damage_assessment",
            "data_integrity_score",
            "date_end",
            "date_start",
            "diameter",
            "dilution_rate",
            "dilution_ratio",
            "direction",
            "drought_severity",
            "dry_matter_pct",
            "dry_matter_tons_acre",
            "duration",
            "duration_days",
            "duration_hours",
            "earliest_safe_harvest",
            "economic_threshold",
            "economic_threshold_met",
            "effectiveness",
            "emitter_height_m",
            "emitters_deployed",
            "emitters_per_acre",
            "emitters_replaced",
            "end_date",
            "environmental_impact",
            "environmental_safeguards",
            "equipment",
            "equipment_cleaned",
            "equipment_efficiency",
            "equipment_harvester",
            "equipment_hours",
            "equipment_name",
            "equipment_operation_type",
            "equipment_sweeper",
            "establishment_success",
            "event_count",
            "event_name",
            "expected_benefits",
            "expected_biomass_tons_ha",
            "expected_parasitism_rate",
            "expiry_date",
            "export_percentage",
            "extra_irrigation_gal",
            "fertigation_duration_hours",
            "field_to_packhouse_hours",
            "final_season_harvest",
            "floor_management_type",
            "flow_rate_test",
            "forecast_low_celsius",
            "frac_group",
            "frost_damage",
            "frost_duration",
            "fruit_drop_pct",
            "fruit_removed_lbs",
            "fruit_size_mm",
            "fuel_consumed_total",
            "fuel_consumption_total",
            "fuel_liters",
            "fuel_type",
            "fuel_unit",
            "grade_a_pct",
            "grade_b_pct",
            "grade_pct",
            "grain_quality",
            "ground_dry_days_target",
            "growth_stage",
            "habitat_area_hectares",
            "harvest_days",
            "harvest_duration_days",
            "harvest_efficiency",
            "harvest_method",
            "heat_index",
            "heat_stress_prevention",
            "highest_temperature",
            "hive_count",
            "hlb_detections",
            "hlb_prevention_program",
            "hlb_status",
            "hull_split_delay_days",
            "hull_split_pct",
            "hull_split_timing",
            "hull_weight_tons",
            "humidity",
            "humidity_level",
            "imp_strategy",
            "irac_group",
            "irrigation_depth",
            "irrigation_depth_unit",
            "irrigation_efficiency",
            "irrigation_increase",
            "irrigation_method",
            "irrigation_reduced",
            "irrigation_schedule",
            "irrigation_type",
            "is_summary",
            "juice_content_pct",
            "k2o_content_kg",
            "kernel_moisture_pct",
            "kernel_weight_kg",
            "kg_per_bin",
            "lab_tested",
            "leaf_tissue_analysis_triggered",
            "lot_id",
            "low_temperature",
            "lower_temperature",
            "maintenance_tasks",
            "maturity_level",
            "max_score",
            "method",
            "micronutrients",
            "min_dry_matter_pct",
            "minimum_temperature",
            "minimum_temperature_celsius",
            "mist_water_gallons",
            "mode_of_action",
            "moisture_content",
            "moisture_pct",
            "monitoring_method",
            "monitoring_period",
            "mowing_height_inches",
            "n_applied_lbs_acre",
            "n_budget_pct",
            "n_content_kg",
            "n_fixation_lbs_acre",
            "name",
            "native_species_planted",
            "net_weight_kg",
            "net_weight_lbs",
            "next_service_hours",
            "nitrogen_fixation",
            "nitrogen_fixation_potential",
            "nitrogen_ppm",
            "nitrogen_total_kg",
            "nitrogen_use_efficiency",
            "now_damage_pct",
            "nozzle_type",
            "nozzles_replaced",
            "nozzles_tested",
            "npk_k",
            "npk_n",
            "npk_p",
            "nutrient_timing",
            "observation",
            "observations",
            "observations_summary",
            "odometer_hours",
            "oil_content_pct",
            "omri_listed",
            "organic_approved",
            "organic_certification",
            "organic_matter_content",
            "organic_system_plan",
            "organic_treatments",
            "p2o5_content_kg",
            "packaging_materials_kg",
            "palmer_drought_index",
            "parasitism_rate_target",
            "parasitoid_species",
            "pass_number",
            "pathogen_reduction",
            "pest_pressure_at_application",
            "pest_reduction_achieved",
            "pest_reduction_percentage",
            "pest_species_observed",
            "pesticide_reduction",
            "phi_days",
            "phosphorus_ppm",
            "phosphorus_total_kg",
            "pickers_count",
            "placement",
            "placement_date",
            "planting_depth",
            "planting_method",
            "planting_population",
            "pollinator_type",
            "pollinizer_varieties",
            "potassium_ppm",
            "potassium_total_kg",
            "pre_cool_temp_f",
            "pre_cool_time_hours",
            "pre_dawn_application",
            "pre_sodium_ppm",
            "precipitation",
            "precipitation_amount",
            "precision_technology",
            "previous_use",
            "processing_energy_kwh",
            "processing_method",
            "product",
            "production_efficiency",
            "program",
            "prohibited_substances",
            "protection_measures",
            "protection_measures_available",
            "protection_method",
            "protein_content",
            "pruning_type",
            "prunings_disposal",
            "prunings_tons",
            "pump_efficiency_pct",
            "pump_pressure_psi",
            "qr_stickers_applied",
            "quality_grade",
            "quality_grade_distribution",
            "quality_rejection_rate",
            "rate_L_ha",
            "rate_fl_oz_acre",
            "rate_g_ha",
            "rate_kg_ha",
            "rate_lbs_acre",
            "rate_oz_acre",
            "recommendation",
            "rei_hours",
            "reject_threshold_pct",
            "release_method",
            "release_quantity",
            "release_rate_eggs_acre",
            "release_timing",
            "remaining_yield_lbs_est",
            "removal_date",
            "replant_reason",
            "residual_control",
            "residue_free",
            "residue_management",
            "resistance_management",
            "restricted_use_pesticide",
            "result",
            "rootstock",
            "rotation_note",
            "row_position",
            "row_spacing",
            "sample_trees",
            "samples_collected",
            "sampling_depth",
            "sampling_method",
            "sampling_pattern",
            "sanitizer_chlorine_ppm",
            "scheduling_method",
            "score",
            "scouting_frequency",
            "season_coverage",
            "seed_lot_number",
            "seed_mix",
            "seed_treatment",
            "seed_variety",
            "seeding_rate",
            "seeding_rate_kg_ha",
            "sensor_count",
            "shake_passes",
            "shell_weight_tons",
            "shielded_application",
            "skirt_clearance_inches",
            "slow_release",
            "soil_carbon_target",
            "soil_moisture",
            "soil_moisture_after",
            "soil_moisture_at_application",
            "soil_moisture_before",
            "soil_moisture_deficit",
            "soil_moisture_depletion_days",
            "soil_moisture_vwc_pct",
            "soil_moisture_vwc_pct_start",
            "soil_test_based",
            "solar_energy_percentage",
            "solubor_rate_kg_ha",
            "spacing_m",
            "species",
            "species_count",
            "spray_equipment",
            "spray_number",
            "spray_volume",
            "spray_volume_L_ha",
            "standard",
            "start_date",
            "storage_duration_months",
            "supplemental_microsprinklers",
            "system_pressure_psi",
            "system_types",
            "tank_capacity_gal",
            "tank_mix",
            "target",
            "target_count_per_carton",
            "target_pest_disease",
            "target_sodium_ppm",
            "target_weeds",
            "tasks",
            "temperature",
            "test_weight",
            "thinning_pct",
            "threshold",
            "threshold_trigger",
            "threshold_vwc_pct",
            "thrips_per_leaf_avg",
            "thrips_per_leaf_trigger",
            "thrips_threshold",
            "tillage_direction",
            "tillage_intensity",
            "tillage_type",
            "timing",
            "total_eggs",
            "total_season_yield_kg",
            "total_wasps",
            "total_water_gallons_est",
            "traceability_score",
            "transparency_benefit",
            "transparency_testing",
            "trap_density",
            "trap_type",
            "traps_installed",
            "traps_per_ha",
            "treated_or_untreated",
            "treatment_threshold",
            "tree_size",
            "trees_damaged",
            "trees_per_hour",
            "trees_planted",
            "trees_replanted",
            "trees_shaken",
            "trigger",
            "trust_impact",
            "unit",
            "usda_grade",
            "verification_confidence",
            "verification_timestamp",
            "volume_applied_total",
            "volume_unit",
            "wasps_per_ha",
            "wasps_released",
            "water_amount",
            "water_applied",
            "water_deficit",
            "water_efficiency",
            "water_sensitive_cards",
            "water_source",
            "water_volume",
            "water_volume_L",
            "water_volume_L_ha",
            "water_volume_gal_acre",
            "water_volume_total",
            "water_volume_unit",
            "way_of_protection",
            "weather_conditions",
            "weather_influence",
            "weight",
            "well_capacity_gpm",
            "well_depth_ft",
            "wind_machines",
            "wind_speed",
            "yield_average",
            "yield_kg_ha",
            "yield_lbs_acre",
            "yield_revision_lbs",
            "zinc_content_pct",
            "zinc_sulfate_rate_kg_ha",
        }
    )

    # Defense-in-depth: even an allow-listed key is dropped if it matches one of these
    # unambiguously-commercial substrings (guards against a future maintainer mistakenly
    # adding a sensitive key to the allow-list). Deliberately narrow — none of these match
    # any current allow-listed agronomic key.
    EXTRA_DATA_SENSITIVE_SUBSTRINGS = (
        # --- Commercial ---------------------------------------------------------------
        "invoice",
        "purchase_order",
        "bill_of_lading",
        "buyer_",
        "_cost",
        "cost_per",
        "cost_vs",
        "premium_pct",
        "_supplier",
        "supplier_",
        "trailer_",
        "original_",
        "ui_",
        # --- Self-graded / unsubstantiated claim shapes (added 2026-08-03) ------------
        # ALLOWED_EXTRA_DATA_KEYS had grown to 447 entries and had explicitly admitted
        # `traceability_score` (live on 14 published productions), `pesticide_reduction`
        # ("90%"), `biodiversity_score_improvement` ("+35%"), `pest_reduction_percentage`,
        # `max_score` and `data_integrity_score` onto the ANONYMOUS consumer payload.
        #
        # Two separate problems, both P0:
        #   * a self-assigned SCORE on a consumer surface is the exact thing the 2026-06
        #     demotion removed and Trazo Test #5 forbids — the producer dashboard owns the
        #     score, shoppers get facts;
        #   * "90% pesticide reduction" / "+35% biodiversity improvement" are quantified
        #     comparative benefit claims with no stated baseline and no third-party
        #     verification — FTC 16 CFR 260.6, and the self-created-label class EU ECGT
        #     2024/825 bans from 2026-09-27.
        #
        # Shape-matching rather than key-listing on purpose: an allow-list this large cannot
        # be audited by eye, and seed/template data keeps inventing new claim-shaped keys.
        # `test_consumer_extra_data_claim_shapes.py` fails the build if any of these ever
        # reaches an anonymous payload again.
        "score",
        "_reduction",
        "reduction_",
        "_improvement",
        "_rating",
        "yield_vs_",
        "revenue",
        "_roi",
        "roi_",
    )

    def _sanitize_extra_data_for_public(self, event):
        """Allow-list extra_data for the public consumer API.

        ONLY keys in ALLOWED_EXTRA_DATA_KEYS reach the consumer; unknown keys are dropped by
        default (safe). A secondary commercial-substring guard catches any sensitive key that
        is ever mistakenly added to the allow-list. NOTE: free-text narrative fields (event
        ``description``/notes and the company bio) are serialized elsewhere and can still embed
        vendor names / unqualified green claims — that is a separate product-level decision
        (2026-06 audit P0-2 / P1-7), not handled here.
        """
        raw = getattr(event, "extra_data", None)
        if not raw or not isinstance(raw, dict):
            return None

        def is_safe(key):
            if key not in self.ALLOWED_EXTRA_DATA_KEYS:
                return False
            # Certifier/worker-safety keys (REI/PHI/RUP/buffer_zone_meters/volume/etc.) are
            # stripped at the top level of each event dict, but some are ALSO allow-listed for
            # extra_data (and the standard V2 templates write rei_hours/phi_days into
            # extra_data). Subtract the certifier-only set here so the nested path can never
            # leak a worker-safety field to an anonymous consumer (EPA 2024 / ECGT / FTC).
            if key in self._CERTIFIER_ONLY_EVENT_FIELDS:
                return False
            lk = str(key).lower()
            return not any(sub in lk for sub in self.EXTRA_DATA_SENSITIVE_SUBSTRINGS)

        def scrub_nested(value, depth=0):
            """Apply the substring guard INSIDE nested dicts/lists.

            The allow-list only ever gated TOP-LEVEL keys, so once a key like
            `quality_grade_distribution` was allowed its whole sub-object shipped verbatim.
            That is benign for a grade split ({"Premium": 85}) — nested keys are data values,
            not field names, which is why the allow-list is deliberately NOT applied here — but
            it meant a seed or template writing {"impact": {"pesticide_reduction": "90%"}} would
            publish the claim untouched. Shape-guard every level instead.
            """
            if depth > 4:  # runaway/self-referential JSON guard
                return None
            if isinstance(value, dict):
                out = {}
                for k, v in value.items():
                    if any(sub in str(k).lower() for sub in self.EXTRA_DATA_SENSITIVE_SUBSTRINGS):
                        continue
                    if k in self._CERTIFIER_ONLY_EVENT_FIELDS:
                        continue
                    out[k] = scrub_nested(v, depth + 1)
                return out
            if isinstance(value, list):
                return [scrub_nested(v, depth + 1) for v in value]
            return value

        sanitized = {k: scrub_nested(v) for k, v in raw.items() if is_safe(k)}

        # Filter custom_fields to consumer visibility only. Runs AFTER the scrub so the
        # visibility filter sees the original structure it expects.
        if "custom_fields" in sanitized:
            sanitized["custom_fields"] = extract_custom_fields_for_display(raw, visibility_filter="consumer")

        return sanitized if sanitized else None

    # Subtype codes that always matter to a shopper's story: planting/harvest,
    # every crop-input application, core soil practices, pest interventions.
    ALWAYS_HIGHLIGHT_TYPES = frozenset(
        {
            "PL",  # planting
            "HA",  # harvest
            "FE",  # fertilizer
            "PE",  # pesticide
            "FU",  # fungicide
            "HE",  # herbicide
            "CC",  # cover crop
            "OM",  # organic matter / compost
            "PA",  # soil amendment
            "TM",  # pest treatment
            "BR",  # beneficial release
            "PI",  # pest identification
            "FP",  # frost protection (infrequent, notable crop defense)
        }
    )
    # First occurrence only — one soil test / one scouting trip tells the
    # story; ten of them is the audit log (proof view). Mowing (MO) recurs
    # through the season, so one mowing tells the consumer story.
    FIRST_OCCURRENCE_HIGHLIGHT_TYPES = frozenset({"ST", "SC", "IR", "MO"})

    def _consumer_subtype_code(self, ev):
        """
        The public event dicts store the subtype code in family-specific keys:
        chemical → chemical_type (FE/PE/FU/HE), soil → soil_management_type
        (ST/PA/OM/CC/TI/CO), pest → pest_management_type (SC/TM/BR/PI/TA/IP).
        Production and weather events carry their code directly in "type"
        (PL/HA/IR/… and FR/DR/…). Equipment/general/business are never
        consumer highlights.
        """
        family = ev.get("type")
        if family == "chemical":
            return ev.get("chemical_type")
        if family == "soil_management":
            return ev.get("soil_management_type")
        if family == "pest_management":
            return ev.get("pest_management_type")
        if family in ("equipment", "general", "business"):
            return None
        return family

    def _annotate_consumer_highlights(self, events_data):
        """
        Tag each public event with is_highlight for the consumer QR page's
        curated journey view (Phase 2 plan, Section G). Rule-based, computed
        at serialization time — no model change. The proof view ignores the
        flag and shows every event.
        """
        seen_first = set()
        for ev in events_data:
            code = self._consumer_subtype_code(ev)
            if code in self.ALWAYS_HIGHLIGHT_TYPES:
                ev["is_highlight"] = True
            elif code in self.FIRST_OCCURRENCE_HIGHLIGHT_TYPES and code not in seen_first:
                seen_first.add(code)
                ev["is_highlight"] = True
            else:
                ev["is_highlight"] = False

    def _get_chemical_type_with_fallback(self, event):
        """
        Get chemical type with multiple fallback strategies.
        1. Use event.type if set (FE, PE, FU, HE)
        2. Infer from commercial_name (most reliable for incorrectly typed events)
        3. Extract from extra_data carbon calculation breakdown (for old events)

        NOTE: CarbonEntry stores calculated co2e values but not detailed breakdown data.
        Breakdown details (including chemical_type) remain in extra_data for backward compatibility.
        Future enhancement: Consider storing breakdown details in CarbonEntry JSONField.
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

        # Fallback 2: Extract from extra_data carbon breakdown (backward compatibility)
        # CarbonEntry doesn't store breakdown details, only consolidated co2e values
        # This fallback handles old events that still have extra_data['carbon_calculation']
        # BUGFIX: Check that extra_data is a dict before calling .get()
        if hasattr(event, "extra_data") and event.extra_data and isinstance(event.extra_data, dict):
            carbon_data = event.extra_data.get("carbon_calculation", {})
            breakdown = carbon_data.get("breakdown", {}) if isinstance(carbon_data, dict) else {}
            carbon_chemical_type = breakdown.get("chemical_type")
            if carbon_chemical_type and carbon_chemical_type in ["FE", "PE", "FU", "HE"]:
                return carbon_chemical_type

        # Final fallback: return None (will show as generic "chemical application")
        return None

    def _analyze_event_photos(self, event):
        """
        Single-pass analysis of all photos on an event.
        Returns a dict with GPS, content flags, and image count.
        Avoids N+1 queries by iterating images only once (uses prefetch_related from view).
        """
        result = {
            "has_gps_data": False,
            "all_flagged": True,  # Assume flagged until we find a clean photo
            "content_flag": None,  # Worst flag found (for farmer warning)
            "image_count": 0,
        }
        flagged_values = ("not_agricultural", "ai_generated", "stock_photo")

        if not hasattr(event, "album") or not event.album:
            return result

        try:
            for image in event.album.images.all():
                result["image_count"] += 1
                ed = getattr(image, "extra_data", None)
                is_dict = isinstance(ed, dict) if ed else False

                # GPS check
                if is_dict and (ed.get("gps_latitude") or ed.get("latitude")):
                    result["has_gps_data"] = True

                # Content validation check
                if is_dict:
                    flag = ed.get("content_validation", "")
                    if flag in flagged_values:
                        # Track worst flag for farmer warning
                        if result["content_flag"] is None:
                            result["content_flag"] = flag
                    else:
                        # At least one photo is NOT flagged
                        result["all_flagged"] = False
                else:
                    # No extra_data = assume legitimate (demo data, legacy uploads)
                    result["all_flagged"] = False
        except Exception:
            result["all_flagged"] = False

        # If no images were found, nothing is flagged
        if result["image_count"] == 0:
            result["all_flagged"] = False

        return result

    def _get_verification_level_for_event(self, event, has_photos=False, blockchain_verified=False):
        """
        Determine verification level for an event in public history view.
        Evidence-based tiered system:
        - self_reported: No photo evidence (50% trust)
        - photo_documented: Has photos without GPS validation (65% trust)
        - photo_verified: Has photos with GPS + timestamp (80% trust)
        - data_verified: Blockchain verified (85% trust)
        - certified: Third-party verified (100% trust, reserved for future)
        """
        if blockchain_verified:
            return "data_verified"

        if has_photos:
            analysis = self._analyze_event_photos(event)

            # All photos flagged as AI/stock/non-agricultural = no trust credit
            if analysis["all_flagged"]:
                return "self_reported"

            has_timestamp = event.date is not None
            if analysis["has_gps_data"] and has_timestamp:
                return "photo_verified"
            else:
                return "photo_documented"

        return "self_reported"

    def _get_photo_content_flag(self, event):
        """
        Check if any photo on this event was flagged by Vision API.
        Returns the worst flag found, or None if all photos are clean.
        Used by frontend to show warnings to farmers.
        """
        analysis = self._analyze_event_photos(event)
        return analysis["content_flag"]

    def _serialize_prefetched_images(self, album):
        """
        ⚡ OPTIMIZATION: Safely access prefetched images without triggering new queries.
        Uses the prefetched images from view's prefetch_related setup.

        This prevents N+1 queries on album.images.all() calls.
        """
        if not album:
            return []

        try:
            # The view's prefetch_related() already loaded all images,
            # so accessing them here won't trigger database queries
            images = album.images.all()
            return [
                {
                    "id": img.id,
                    "image": img.image_url if img.image_url else (img.image.url if img.image else ""),
                    "caption": getattr(img, "caption", "") or "",
                    "created_at": (img.created_at.isoformat() if hasattr(img, "created_at") and img.created_at else ""),
                }
                for img in images
            ]
        except Exception:
            return []

    def get_events(self, history):
        """
        OPTIMIZED: Get events without triggering carbon calculations.
        This prevents USDA API calls for public history display.

        ⚡ PERFORMANCE OPTIMIZATION: Uses prefetched data from transparency_views.py
        instead of creating new querysets. This reduces 232 queries to ~15.
        """
        try:
            # Get basic event data without expensive carbon calculations
            events_data = []

            # Extract blockchain verification data from production extra_data
            # BUGFIX: Check that extra_data is a dict before calling .get()
            # Ask the claim authority instead of trusting a flag stored in extra_data.
            # `blockchain_verified` was whatever had been written into the blob — it did not
            # require an actual transaction hash or an active add-on, and "verified" is the
            # word compliance.md marks UNSAFE regardless. See history/services/claim_authority.
            from history.services.claim_authority import may_claim_blockchain, public_certifier_name

            blockchain_decision = may_claim_blockchain(history)
            blockchain_verified = blockchain_decision.allowed
            blockchain_transaction = None
            if blockchain_decision.allowed and isinstance(history.extra_data, dict):
                blockchain_transaction = history.extra_data.get("blockchain_transaction")

            # ⚡ OPTIMIZATION: Use prefetched event data directly instead of creating new querysets
            # The view's prefetch_related() already optimized these queries, so we use:
            # - .all() to access prefetched events (uses cache, NOT database)
            # - No .only() because prefetch already selected the right fields
            # This reduces queries from 232 → ~15 (90% reduction)
            chemical_events = history.history_chemicalevent_events.all()
            production_events = history.history_productionevent_events.all()
            weather_events = history.history_weatherevent_events.all()
            equipment_events = history.history_equipmentevent_events.all()
            soil_events = history.history_soilmanagementevent_events.all()
            pest_events = history.history_pestmanagementevent_events.all()
            general_events = history.history_generalevent_events.all()
            business_events = history.history_businessevent_events.all()

            # Phase 3 — consent-gated worker names (CCPA; name + farm geo is a
            # doxing vector). Masked at the source so no public payload ever
            # carries a full name unless the establishment opted in.
            show_full_names = bool(
                history.parcel
                and history.parcel.establishment
                and getattr(history.parcel.establishment, "show_full_performer_names", False)
            )

            # Create lightweight event data without carbon calculations
            for i, event in enumerate(chemical_events):
                # Get serialized images from prefetched data (no additional queries)
                image_list = self._serialize_prefetched_images(event.album if hasattr(event, "album") else None)
                photo_count = len(image_list)
                album_data = None
                if hasattr(event, "album") and event.album and image_list:
                    album_data = {
                        "images": image_list,
                    }

                events_data.append(
                    {
                        "id": f"chemical_{i}",
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Chemical Application",
                        "observation": getattr(event, "observation", ""),
                        "performed_by": self._public_performer(event, show_full_names),
                        "type": "chemical",
                        "chemical_type": self._get_chemical_type_with_fallback(
                            event
                        ),  # Expose raw chemical type (FE, PE, FU, HE) for frontend processing
                        "certified": getattr(event, "certified", False),
                        "index": getattr(event, "index", 0),
                        "volume": event.volume,
                        # Unit fields: the MODEL COLUMN is canonical (see the note at
                        # to_internal_value — volume_unit/area_unit became real columns on
                        # ChemicalEvent; extra_data only keeps a legacy mirror for old rows).
                        #
                        # This block previously read extra_data first and fell back to a
                        # hardcoded "L"/"ha". Rows written after the columns landed have no
                        # extra_data mirror, so 141 of 215 chemical events served area_unit
                        # "ha" for values the farmer entered in ACRES — the consumer page then
                        # ran its ha->acres conversion and displayed 2.47x the treated area
                        # (an 85-acre copper application rendered as "210 acres"). Never fall
                        # back to a literal unit: an unknown unit must stay unknown so the
                        # frontend renders a bare number instead of inventing a basis.
                        "volume_unit": _public_unit(event, "volume_unit"),
                        "concentration": event.concentration,
                        "area": getattr(event, "area", None),
                        "area_unit": _public_unit(event, "area_unit"),
                        "equipment": event.commercial_name,
                        "photo_count": photo_count,
                        "commercial_name": event.commercial_name,
                        "album": album_data,
                        # Additional transparency fields
                        "name": getattr(event, "name", None),
                        "variety": getattr(event, "variety", None),
                        "block_id": getattr(event, "block_id", None),
                        "growth_stage": getattr(event, "growth_stage", None),
                        "way_of_application": getattr(event, "way_of_application", None),
                        "weather_conditions": getattr(event, "weather_conditions", None),
                        "application_timing": getattr(event, "application_timing", None),
                        "target_pest_disease": getattr(event, "target_pest_disease", None),
                        "chemical_subtype": getattr(event, "chemical_subtype", None),
                        # Application fuel fields for carbon transparency
                        "application_fuel_type": getattr(event, "application_fuel_type", None),
                        "application_fuel_consumed": (
                            str(event.application_fuel_consumed)
                            if getattr(event, "application_fuel_consumed", None) is not None
                            else None
                        ),
                        "application_fuel_unit": getattr(event, "application_fuel_unit", None),
                        # NPK nutrient percentages
                        "nitrogen_percentage": (
                            str(event.nitrogen_percentage)
                            if getattr(event, "nitrogen_percentage", None) is not None
                            else None
                        ),
                        "phosphorus_percentage": (
                            str(event.phosphorus_percentage)
                            if getattr(event, "phosphorus_percentage", None) is not None
                            else None
                        ),
                        "potassium_percentage": (
                            str(event.potassium_percentage)
                            if getattr(event, "potassium_percentage", None) is not None
                            else None
                        ),
                        # §E-3 — micronutrients (§ 205.601(j)(6)). WHICH nutrient is plain
                        # language a consumer follows ("zinc"); the RATE is the same
                        # application-detail class as the NPK percentages above and is stripped
                        # for non-owners by _CERTIFIER_ONLY_EVENT_FIELDS.
                        "micronutrient_type": getattr(event, "micronutrient_type", None),
                        "micronutrient_rate": (
                            str(event.micronutrient_rate)
                            if getattr(event, "micronutrient_rate", None) is not None
                            else None
                        ),
                        "micronutrient_rate_unit": getattr(event, "micronutrient_rate_unit", None),
                        # EPA compliance fields
                        "applicator_name": getattr(event, "applicator_name", None),
                        "applicator_certification": getattr(event, "applicator_certification", None),
                        "epa_registration_number": getattr(event, "epa_registration_number", None),
                        "restricted_use_pesticide": getattr(event, "restricted_use_pesticide", False),
                        "rei_hours": (str(event.rei_hours) if getattr(event, "rei_hours", None) is not None else None),
                        "phi_days": (str(event.phi_days) if getattr(event, "phi_days", None) is not None else None),
                        "buffer_zone_meters": (
                            float(event.buffer_zone_meters)
                            if getattr(event, "buffer_zone_meters", None) is not None
                            else None
                        ),
                        "is_fertigation": getattr(event, "is_fertigation", None),
                        "organic_approved": (
                            getattr(event, "organic_approved", None)
                            or (
                                (
                                    event.extra_data.get("organic_certification")
                                    or event.extra_data.get("organic_approved")
                                )
                                if isinstance(getattr(event, "extra_data", None), dict)
                                else None
                            )
                        ),
                        # NOP traceability fields (7 CFR 205.103) — supplier_name,
                        # purchase_date, purchase_invoice, quantity_purchased(_unit) are
                        # commercially sensitive and intentionally excluded from the public
                        # consumer endpoint. They surface only in the certifier-facing NOP
                        # PDF (audit_export_service mass-balance section). The codebase's
                        # _sanitize_extra_data_for_public() already blocks "supplier" in
                        # extra_data; this comment documents the equivalent policy for
                        # top-level model fields. See AUDIT_INSTRUCTIONS Standard Fix #5.
                        # P0-3 — CA DPR Restricted Materials Permit (CA state law).
                        "ca_dpr_permit_number": getattr(event, "ca_dpr_permit_number", None),
                        "ca_dpr_permit_county": getattr(event, "ca_dpr_permit_county", None),
                        "ca_dpr_permit_expires": (
                            event.ca_dpr_permit_expires.isoformat()
                            if getattr(event, "ca_dpr_permit_expires", None)
                            else None
                        ),
                        # Sprint 3 — OMRI / National List verification status (7 CFR 205.601/602).
                        # We expose the IDs + human-readable names; consumer card shows as badges.
                        "omri_product_id": event.omri_product.omri_id if getattr(event, "omri_product", None) else None,
                        "omri_product_name": (
                            event.omri_product.product_name if getattr(event, "omri_product", None) else None
                        ),
                        "national_list_substance_name": (
                            event.national_list_substance.substance_name
                            if getattr(event, "national_list_substance", None)
                            else None
                        ),
                        "national_list_status": (
                            event.national_list_substance.status
                            if getattr(event, "national_list_substance", None)
                            else None
                        ),
                        "national_list_cfr_section": (
                            event.national_list_substance.cfr_section
                            if getattr(event, "national_list_substance", None)
                            else None
                        ),
                        # Phase 3 — server-resolved input status. Single source of
                        # truth for the consumer "Crop Inputs" chips; frontend should
                        # prefer this over re-deriving from organic_approved/RUP.
                        "input_status": resolve_input_status(event),
                        "extra_data": self._sanitize_extra_data_for_public(event),
                        # Blockchain verification fields from production
                        "blockchain_verified": blockchain_verified,
                        "blockchain_transaction": blockchain_transaction,
                        "photo_content_flag": self._get_photo_content_flag(event),
                        "verification_level": self._get_verification_level_for_event(
                            event, photo_count > 0, blockchain_verified
                        ),
                        # Sprint 5.1 — OSP ↔ events drift detector finding. Shape documented in
                        # certifications.services.drift_detector.
                        # OWNER-ONLY: listed in _CERTIFIER_ONLY_EVENT_FIELDS, so to_representation
                        # strips it for every non-owner (and for the owner on the consumer page,
                        # via force_public_view). It is an internal nonconformance narrative
                        # ("<input> not in active OSP approved inputs") with osp_id/osp_version and
                        # a 7 CFR citation — self-incriminating audit data that shipped on the
                        # anonymous QR payload until 2026-07-31.
                        # It must stay HERE (not be deleted) because this serializer also feeds the
                        # producer's ProfileProduction timeline, where DriftFindingsBanner renders
                        # it — that banner is the whole reason it is safe to withhold from shoppers.
                        "drift_warning": getattr(event, "drift_warning", None),
                    }
                )

            for i, event in enumerate(production_events):
                # Get serialized images from prefetched data (no additional queries)
                image_list = self._serialize_prefetched_images(event.album if hasattr(event, "album") else None)
                photo_count = len(image_list)
                album_data = None
                if hasattr(event, "album") and event.album and image_list:
                    album_data = {
                        "images": image_list,
                    }

                events_data.append(
                    {
                        "id": f"production_{i}",
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Production Activity",
                        "observation": event.observation or "",
                        "performed_by": self._public_performer(event, show_full_names),
                        "type": getattr(event, "type", "production"),
                        "event_type": PRODUCTION_EVENT_TYPE,
                        "production_type": getattr(event, "type", ""),
                        "certified": getattr(event, "certified", False),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": None,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                        # Production-specific fields for detailed display
                        "name": getattr(event, "name", None),
                        "variety": getattr(event, "variety", None),
                        "block_id": getattr(event, "block_id", None),
                        "growth_stage": getattr(event, "growth_stage", None),
                        "area_covered": float(getattr(event, "area_covered", None) or 0) or None,
                        "area_unit": getattr(event, "area_unit", "ha"),
                        "yield_quantity": float(getattr(event, "yield_quantity", None) or 0) or None,
                        "yield_unit": getattr(event, "yield_unit", "kg"),
                        "fuel_consumed": float(getattr(event, "fuel_consumed", None) or 0) or None,
                        "fuel_unit": getattr(event, "fuel_unit", "L"),
                        "fuel_type": getattr(event, "fuel_type", None),
                        "equipment_hours": float(getattr(event, "equipment_hours", None) or 0) or None,
                        "transportation_distance": float(getattr(event, "transportation_distance", None) or 0) or None,
                        "transportation_unit": getattr(event, "transportation_unit", "km"),
                        "production_efficiency": getattr(event, "production_efficiency", "normal"),
                        "operation_efficiency": getattr(event, "production_efficiency", "normal"),
                        "seeds_source": getattr(event, "seeds_source", None),
                        # Irrigation fields (model field with extra_data fallback)
                        "irrigation_method": (
                            getattr(event, "irrigation_method", None)
                            or (
                                event.extra_data.get("irrigation_method")
                                if isinstance(getattr(event, "extra_data", None), dict)
                                else None
                            )
                        ),
                        "irrigation_depth": float(getattr(event, "irrigation_depth", None) or 0) or None,
                        "irrigation_depth_unit": getattr(event, "irrigation_depth_unit", None),
                        "water_source": (
                            getattr(event, "water_source", None)
                            or (
                                event.extra_data.get("water_source")
                                if isinstance(getattr(event, "extra_data", None), dict)
                                else None
                            )
                        ),
                        # Irrigation pump fields (IR subtype) — registry declares both
                        # with consumer_card: 'details'. Without these on the public
                        # payload, ConsumerEventCard's registry resolver has nothing
                        # to render, so "Pump Depth" / "Electricity Source" silently
                        # disappear on the product-detail QR page.
                        "pump_depth_ft": float(getattr(event, "pump_depth_ft", None) or 0) or None,
                        "electricity_source": getattr(event, "electricity_source", None),
                        # NOTE: Equipment cleaning fields (cleaning_date, cleaning_method,
                        # cleaning_materials_used, cleaned_by, cleaning_protocol_reference,
                        # shared_with_conventional) are intentionally serialized only in the
                        # EM subtype block further down (after equipment_operation_type).
                        # Python dict-literal duplicate keys silently overwrite, which had
                        # previously masked drift between two blocks of the same fields
                        # (e.g., shared_with_conventional default disagreement).
                        # Post-harvest sanitizer detail (7 CFR 205.272 + § 205.605).
                        "sanitizer_name": getattr(event, "sanitizer_name", None),
                        "sanitizer_ppm": (
                            str(event.sanitizer_ppm) if getattr(event, "sanitizer_ppm", None) is not None else None
                        ),
                        "rinse_step_documented": getattr(event, "rinse_step_documented", None),
                        # OWNER-ONLY (_CERTIFIER_ONLY_EVENT_FIELDS): the value is a raw CFR
                        # citation ("§ 205.605(b) - Sodium hypochlorite"). transparency-first.md
                        # bans raw regulatory citations on consumer surfaces — certifier
                        # vocabulary, not a shopper's. sanitizer_name/sanitizer_ppm still ship
                        # to consumers, so the substance used on the food is still disclosed.
                        "sanitizer_nop_reference": getattr(event, "sanitizer_nop_reference", None),
                        # Harvest fields (model field + extra_data for consumer trust)
                        "harvest_quality_grade": getattr(event, "harvest_quality_grade", None),
                        "grain_moisture": float(getattr(event, "grain_moisture", None) or 0) or None,
                        "harvest_method": (
                            getattr(event, "harvest_method", None)
                            or (
                                event.extra_data.get("harvest_method")
                                if isinstance(getattr(event, "extra_data", None), dict)
                                else None
                            )
                        ),
                        "brix_levels": (
                            (event.extra_data.get("brix_levels") or event.extra_data.get("brix_level"))
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        # Brix as model field (ProductionEvent.brix_level is a DecimalField).
                        # Registry reads `brix_level` (singular); `brix_levels` above is legacy.
                        "brix_level": float(getattr(event, "brix_level", None) or 0) or None,
                        # F43: tree-crop maturity (avocado/nut) — the correct vocabulary for the ICP
                        "dry_matter_percentage": (
                            float(getattr(event, "dry_matter_percentage", None))
                            if getattr(event, "dry_matter_percentage", None) is not None
                            else None
                        ),
                        # Operation method (free-text "production_method") — consumer trust signal
                        # for hand-labor documentation. Lives in extra_data.method; promoted to
                        # top-level so the registry's `method` field resolves on the consumer card
                        # without needing the formatter's extra_data fallback.
                        "method": (
                            event.extra_data.get("method")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        # Post-Harvest Processing (PH subtype) fields stored in extra_data.
                        # Registry reads these with extra_data fallback, but promoting them
                        # keeps the API response consistent with other production fields.
                        "processing_type": (
                            event.extra_data.get("processing_type")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "processing_duration_hours": (
                            event.extra_data.get("processing_duration_hours")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "temperature_control": (
                            event.extra_data.get("temperature_control")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        # Equipment maintenance fields (extra_data)
                        "equipment_type": (
                            getattr(event, "equipment_type", None)
                            or (
                                event.extra_data.get("equipment_type")
                                if isinstance(getattr(event, "extra_data", None), dict)
                                else None
                            )
                        ),
                        "equipment_operation_type": (
                            getattr(event, "equipment_operation_type", None)
                            or (
                                event.extra_data.get("equipment_operation_type")
                                if isinstance(getattr(event, "extra_data", None), dict)
                                else None
                            )
                        ),
                        # NOP 7 CFR 205.272 — Equipment cleaning logs (EM/CL subtype).
                        # Registry gates these on equipment_operation_type === 'CL'; the
                        # consumer card is the canonical surface for split-operation
                        # transparency ("equipment was shared with a conventional farm,
                        # here is our cleaning evidence"). Without these on the public
                        # payload, the registry resolver has nothing to render even
                        # though the read serializer exposes them to authenticated views.
                        "cleaning_date": (
                            event.cleaning_date.isoformat() if getattr(event, "cleaning_date", None) else None
                        ),
                        "cleaning_method": getattr(event, "cleaning_method", None),
                        "cleaning_materials_used": getattr(event, "cleaning_materials_used", None),
                        # OWNER-ONLY (both in _CERTIFIER_ONLY_EVENT_FIELDS).
                        #
                        # `cleaned_by` is free text for "person who performed or verified the
                        # cleaning" and holds real worker names ("Miguel Ramirez (Farm Manager)"
                        # in live data). It rendered on the consumer card until 2026-07-31, which
                        # contradicted the two protections already in place for exactly this
                        # class: `performed_by` is masked to initials by `_public_performer()`
                        # and `applicator_name` is stripped as certifier-only. A worker did not
                        # consent to being named on a public product page.
                        #
                        # `cleaning_protocol_reference` is an internal SOP identifier
                        # ("SOP-CLEAN-001 (NOP 205.272 Compliance)") — an operator document
                        # reference, meaningless to a shopper.
                        #
                        # Kept in the payload (not deleted) because this serializer also feeds the
                        # producer's ProfileProduction timeline; the owner gate is what makes them
                        # consumer-safe.
                        "cleaned_by": getattr(event, "cleaned_by", None),
                        "cleaning_protocol_reference": getattr(event, "cleaning_protocol_reference", None),
                        "shared_with_conventional": getattr(event, "shared_with_conventional", False),
                        # NOP 7 CFR 205.204 seed traceability (PL subtype). seed_supplier_name,
                        # seed_purchase_date, seed_purchase_invoice, and seed_search_attempts (NOP 5029
                        # commercial-availability search docs, which embed contacted-supplier identities)
                        # are commercially sensitive vendor/purchase records and are INTENTIONALLY
                        # EXCLUDED from the public consumer endpoint. They surface only on the
                        # certifier-facing NOP PDF (audit_export_service). Same policy and class as the
                        # chemical supplier_name/purchase_* fields above (see L3103-3110) and Standard
                        # Fix #5 in AUDIT_INSTRUCTIONS. Regression: test_public_serializer_leakage.py.
                        # seed_lot_number / seed_certification_status / seed_treatment are legitimate
                        # consumer transparency (what was planted, not who sold it) and remain public.
                        "seed_lot_number": getattr(event, "seed_lot_number", None),
                        "seed_certification_status": getattr(event, "seed_certification_status", None),
                        "seed_treatment": getattr(event, "seed_treatment", None),
                        # Sprint 3.2 — Post-harvest storage (NOP 205.272 / FSMA 204 KDE prep)
                        "storage_location": getattr(event, "storage_location", None),
                        "storage_temperature_f": (
                            float(event.storage_temperature_f)
                            if getattr(event, "storage_temperature_f", None) is not None
                            else None
                        ),
                        # Custom fields stored in extra_data (e.g., custom_fields, carbon_calculation)
                        "extra_data": self._sanitize_extra_data_for_public(event),
                        # Aggregate event fields (Sprint 4) - extracted from extra_data for normalizer
                        "is_summary": (
                            event.extra_data.get("is_summary", False)
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else False
                        ),
                        "date_start": (
                            event.extra_data.get("date_start")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "date_end": (
                            event.extra_data.get("date_end")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "event_count": (
                            event.extra_data.get("event_count")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "water_volume_total": (
                            event.extra_data.get("water_volume_total")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "water_volume_unit": (
                            event.extra_data.get("water_volume_unit")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "yield_total": (
                            event.extra_data.get("yield_total")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "yield_total_unit": (
                            event.extra_data.get("yield_total_unit")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        # Blockchain verification fields from production
                        "blockchain_verified": blockchain_verified,
                        "blockchain_transaction": blockchain_transaction,
                        "photo_content_flag": self._get_photo_content_flag(event),
                        "verification_level": self._get_verification_level_for_event(
                            event, photo_count > 0, blockchain_verified
                        ),
                    }
                )

            for i, event in enumerate(weather_events):
                # Count photos from event album
                photo_count = 0
                album_data = None
                # Get serialized images from prefetched data (no additional queries)

                image_list = self._serialize_prefetched_images(event.album if hasattr(event, "album") else None)

                photo_count = len(image_list)

                album_data = None

                if hasattr(event, "album") and event.album and image_list:

                    album_data = {
                        "images": image_list,
                    }

                events_data.append(
                    {
                        "id": f"weather_{i}",
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Weather Event",
                        "observation": event.observation or "",
                        "performed_by": self._public_performer(event, show_full_names),
                        "type": getattr(
                            event, "type", "weather"
                        ),  # 🌦️ PRESERVE WEATHER TYPE: Use actual weather type (FR, DR, etc.) instead of generic "weather"
                        "event_type": WEATHER_EVENT_TYPE,
                        "certified": getattr(event, "certified", False),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": None,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                        "name": (event.extra_data or {}).get("event_name") or (event.extra_data or {}).get("name"),
                        "variety": getattr(event, "variety", None),
                        "block_id": getattr(event, "block_id", None),
                        "growth_stage": getattr(event, "growth_stage", None),
                        # 🌦️ WEATHER FIELDS: Add missing extra_data for weather-specific fields unification
                        "extra_data": self._sanitize_extra_data_for_public(event),
                        # Blockchain verification fields from production
                        "blockchain_verified": blockchain_verified,
                        "blockchain_transaction": blockchain_transaction,
                        "photo_content_flag": self._get_photo_content_flag(event),
                        "verification_level": self._get_verification_level_for_event(
                            event, photo_count > 0, blockchain_verified
                        ),
                    }
                )

            for i, event in enumerate(equipment_events):
                # Count photos from event album
                photo_count = 0
                album_data = None
                # Get serialized images from prefetched data (no additional queries)

                image_list = self._serialize_prefetched_images(event.album if hasattr(event, "album") else None)

                photo_count = len(image_list)

                album_data = None

                if hasattr(event, "album") and event.album and image_list:

                    album_data = {
                        "images": image_list,
                    }

                events_data.append(
                    {
                        "id": f"equipment_{i}",
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Equipment Use",
                        "observation": getattr(event, "observation", ""),
                        "performed_by": self._public_performer(event, show_full_names),
                        "type": "equipment",  # FIXED: Always return "equipment" as main type for Equipment events
                        "certified": getattr(event, "certified", False),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": event.equipment_name,
                        # CRITICAL: Add Equipment subtype and operation name for frontend display
                        "operation_type": getattr(event, "type", None),  # Equipment subtype (MN, RE, CA, FC, BD, EI)
                        "name": getattr(event, "name", None),  # Operation name for title display
                        "operation_name": getattr(event, "name", None),  # Frontend compatibility alias
                        "variety": getattr(event, "variety", None),
                        "block_id": getattr(event, "block_id", None),
                        "growth_stage": getattr(event, "growth_stage", None),
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
                        # Blockchain verification fields from production
                        "blockchain_verified": blockchain_verified,
                        "blockchain_transaction": blockchain_transaction,
                        "photo_content_flag": self._get_photo_content_flag(event),
                        "verification_level": self._get_verification_level_for_event(
                            event, photo_count > 0, blockchain_verified
                        ),
                    }
                )

            for i, event in enumerate(soil_events):
                # Count photos from event album
                photo_count = 0
                album_data = None
                # Get serialized images from prefetched data (no additional queries)

                image_list = self._serialize_prefetched_images(event.album if hasattr(event, "album") else None)

                photo_count = len(image_list)

                album_data = None

                if hasattr(event, "album") and event.album and image_list:

                    album_data = {
                        "images": image_list,
                    }

                events_data.append(
                    {
                        "id": f"soil_{i}",
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Soil Management",
                        "observation": getattr(event, "observation", ""),
                        "performed_by": self._public_performer(event, show_full_names),
                        "type": "soil_management",
                        "event_type": SOIL_MANAGEMENT_EVENT_TYPE,
                        "certified": getattr(event, "certified", False),
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
                        "variety": getattr(event, "variety", None),
                        "block_id": getattr(event, "block_id", None),
                        "growth_stage": getattr(event, "growth_stage", None),
                        "soil_management_type": getattr(
                            event, "type", None
                        ),  # Raw type (ST, PA, OM, etc.) - frontend handles mapping
                        "amendment_type": getattr(event, "amendment_type", None),  # Type of amendment used
                        "amendment_amount": getattr(event, "amendment_amount", None),  # Amount of amendment
                        "soil_ph": getattr(event, "soil_ph", None),  # Soil pH measurement
                        "organic_matter_percentage": getattr(
                            event, "organic_matter_percentage", None
                        ),  # Organic matter %
                        # OWNER-ONLY (_CERTIFIER_ONLY_EVENT_FIELDS). A free-form blob written by
                        # the producer soil-test form (SoilManagementTab.jsx is its only writer),
                        # it carried the whole lab panel plus the lab's identity to consumers —
                        # contradicting the §E-2 policy stated immediately below and inconsistent
                        # with `water_test_results`, which is withheld and regression-tested.
                        # An unfiltered JSON blob on a public endpoint is the same structural
                        # mistake as the old extra_data deny-list: whatever the form adds next
                        # ships automatically. The producer keeps the blob (their own data); the
                        # three consumer-relevant facts are extracted explicitly below.
                        "test_results": getattr(event, "test_results", None),
                        # §E-2 — the consumer-facing FACTS of a lab analysis: what was sampled,
                        # which independent lab tested it, and when. An outside lab is real
                        # third-party evidence, so it belongs on the consumer surface; the
                        # numeric results (N/P/K, CEC, ppm) stay on the producer/certifier
                        # surfaces — they are the jargon class transparency-first.md excludes.
                        "sample_matrix": getattr(event, "sample_matrix", None),
                        "lab_name": (
                            (event.test_results or {}).get("lab_name")
                            if isinstance(getattr(event, "test_results", None), dict)
                            else None
                        ),
                        "lab_report_date": (
                            (event.test_results or {}).get("report_date")
                            if isinstance(getattr(event, "test_results", None), dict)
                            else None
                        ),
                        "carbon_sequestration_potential": (
                            float(event.carbon_sequestration_potential)
                            if getattr(event, "carbon_sequestration_potential", None) is not None
                            else None
                        ),
                        # Raw values only - no fallbacks
                        "area_covered": getattr(event, "area_covered", None),  # Numeric area covered
                        "area_unit": getattr(event, "area_unit", None),  # ha, acres, m2, km2 (raw)
                        "fuel_consumed": getattr(event, "fuel_consumed", None),  # Fuel amount
                        "fuel_unit": getattr(event, "fuel_unit", None),  # L, gal, kg (raw)
                        "fuel_type": getattr(event, "fuel_type", None),  # diesel, gasoline, electric
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
                        # 🐄 GRAZING FIELDS
                        "animal_type": getattr(event, "animal_type", None),
                        "animal_count": getattr(event, "animal_count", None),
                        "grazing_duration_days": getattr(event, "grazing_duration_days", None),
                        "grazing_purpose": getattr(event, "grazing_purpose", None),
                        # 🦉 BIODIVERSITY / HABITAT FIELDS (HD / NS subtypes) — facts only, no score
                        "habitat_type": getattr(event, "habitat_type", None),
                        "habitat_structure_count": getattr(event, "habitat_structure_count", None),
                        # habitat maturity is a positive consumer story (an 8-yr-old hedgerow vs new)
                        "habitat_install_date": (
                            event.habitat_install_date.isoformat()
                            if getattr(event, "habitat_install_date", None)
                            else None
                        ),
                        # 📏 AMENDMENT NUMERIC FIELDS
                        "amendment_amount_numeric": (
                            str(event.amendment_amount_numeric)
                            if getattr(event, "amendment_amount_numeric", None) is not None
                            else None
                        ),
                        "amendment_amount_unit": getattr(event, "amendment_amount_unit", None),
                        # 🌿 NOP Compliance fields (7 CFR 205.203) — Amendment approval + Compost tracking + Manure timing
                        "amendment_organic_approved": getattr(event, "amendment_organic_approved", None),
                        "compost_peak_temp_f": (
                            str(event.compost_peak_temp_f)
                            if getattr(event, "compost_peak_temp_f", None) is not None
                            else None
                        ),
                        "compost_duration_days_at_temp": getattr(event, "compost_duration_days_at_temp", None),
                        "compost_turning_count": getattr(event, "compost_turning_count", None),
                        "compost_method": getattr(event, "compost_method", None),
                        "compost_initial_cn_ratio": (
                            str(event.compost_initial_cn_ratio)
                            if getattr(event, "compost_initial_cn_ratio", None) is not None
                            else None
                        ),
                        # F24: compost feedstock + temperature log are NOP-5021 certifier/agronomic
                        # detail — surfaced in the audit PDF only, not the consumer payload (no
                        # consumer registry entry, and the consumer story is "compost applied", not
                        # the feedstock recipe). Keeps the anonymous payload lean + consistent.
                        "manure_harvest_interval": getattr(event, "manure_harvest_interval", None),
                        "manure_application_date": (
                            event.manure_application_date.isoformat()
                            if getattr(event, "manure_application_date", None)
                            else None
                        ),
                        "extra_data": self._sanitize_extra_data_for_public(event),  # Additional soil management data
                        # Blockchain verification fields from production
                        "blockchain_verified": blockchain_verified,
                        "blockchain_transaction": blockchain_transaction,
                        "photo_content_flag": self._get_photo_content_flag(event),
                        "verification_level": self._get_verification_level_for_event(
                            event, photo_count > 0, blockchain_verified
                        ),
                        # OSP drift finding — OWNER-ONLY via _CERTIFIER_ONLY_EVENT_FIELDS.
                        # See the note in the chemical block above.
                        "drift_warning": getattr(event, "drift_warning", None),
                    }
                )

            for i, event in enumerate(pest_events):
                # Count photos from event album
                photo_count = 0
                album_data = None
                # Get serialized images from prefetched data (no additional queries)

                image_list = self._serialize_prefetched_images(event.album if hasattr(event, "album") else None)

                photo_count = len(image_list)

                album_data = None

                if hasattr(event, "album") and event.album and image_list:

                    album_data = {
                        "images": image_list,
                    }

                events_data.append(
                    {
                        "id": f"pest_{i}",
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.description or "Pest Management",
                        "observation": getattr(event, "observation", ""),
                        "performed_by": self._public_performer(event, show_full_names),
                        "type": "pest_management",
                        "event_type": PEST_MANAGEMENT_EVENT_TYPE,
                        "certified": getattr(event, "certified", False),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": event.pest_species,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                        # Pest management specific fields for consumer display
                        "name": getattr(event, "name", None) or (event.extra_data or {}).get("name"),
                        "variety": getattr(event, "variety", None),
                        "block_id": getattr(event, "block_id", None),
                        "growth_stage": getattr(event, "growth_stage", None),
                        "pest_management_type": getattr(event, "type", None),
                        # §E-4 — the preventive practice (7 CFR 205.206(a)). Removing overwintering
                        # pest sites INSTEAD of spraying is the most legible organic practice on
                        # the page and a plain fact about work done, not a claim about outcomes.
                        # Missing here, a winter-sanitation event reached the consumer as a
                        # generic pest record with nothing to say — which is the opposite of why
                        # the subtype exists.
                        "cultural_practice": getattr(event, "cultural_practice", None),
                        "pest_species": getattr(event, "pest_species", None),
                        "pest_pressure_level": getattr(event, "pest_pressure_level", None),
                        # F44: quantitative monitoring count (e.g. 5 mites/leaf) — consumer-visible
                        # IPM evidence behind the spray decision
                        "monitoring_count": (
                            float(getattr(event, "monitoring_count", None))
                            if getattr(event, "monitoring_count", None) is not None
                            else None
                        ),
                        "monitoring_unit": getattr(event, "monitoring_unit", None),
                        "beneficial_species": getattr(event, "beneficial_species", None),
                        "release_quantity": getattr(event, "release_quantity", None),
                        # BR organic-approval IS a consumer transparency positive (like chemical
                        # organic-approved). Supplier + lot are deliberately NOT exposed here —
                        # commercially sensitive, audit-PDF only.
                        "beneficial_organic_approved": getattr(event, "beneficial_organic_approved", None),
                        "trap_count": getattr(event, "trap_count", None),
                        # TM real IPM pressure data — consumer-visible (trap kind + actual catch)
                        "trap_type": getattr(event, "trap_type", None),
                        "pest_catch_count": getattr(event, "pest_catch_count", None),
                        "damage_percentage": float(getattr(event, "damage_percentage", None) or 0) or None,
                        "action_threshold_met": getattr(event, "action_threshold_met", None),
                        "ipm_strategy": getattr(event, "ipm_strategy", None),
                        # NOP 7 CFR 205.206(e): threshold rationale + pest ID verification
                        "threshold_rationale": getattr(event, "threshold_rationale", None),
                        "identification_method": getattr(event, "identification_method", None),
                        "identified_by": getattr(event, "identified_by", None),
                        # Consumer trust fields
                        "beneficial_insects_used": getattr(event, "beneficial_insects_used", None),
                        "chemical_free_period_days": getattr(event, "chemical_free_period_days", None),
                        # Fuel/Equipment fields
                        "area_covered": float(getattr(event, "area_covered", None) or 0) or None,
                        "area_unit": getattr(event, "area_unit", "ha"),
                        "fuel_consumed": float(getattr(event, "fuel_consumed", None) or 0) or None,
                        "fuel_unit": getattr(event, "fuel_unit", "L"),
                        "fuel_type": getattr(event, "fuel_type", None),
                        "equipment_hours": float(getattr(event, "equipment_hours", None) or 0) or None,
                        "production_efficiency": getattr(event, "production_efficiency", "normal"),
                        "extra_data": self._sanitize_extra_data_for_public(event),
                        # Aggregate event fields (Sprint 5) - extracted from extra_data for normalizer
                        "is_summary": (
                            event.extra_data.get("is_summary", False)
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else False
                        ),
                        "date_start": (
                            event.extra_data.get("date_start")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "date_end": (
                            event.extra_data.get("date_end")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        "event_count": (
                            event.extra_data.get("event_count")
                            if isinstance(getattr(event, "extra_data", None), dict)
                            else None
                        ),
                        # Blockchain verification fields from production
                        "blockchain_verified": blockchain_verified,
                        "blockchain_transaction": blockchain_transaction,
                        "photo_content_flag": self._get_photo_content_flag(event),
                        "verification_level": self._get_verification_level_for_event(
                            event, photo_count > 0, blockchain_verified
                        ),
                    }
                )

            for i, event in enumerate(general_events):
                # Count photos from event album
                photo_count = 0
                album_data = None
                # Get serialized images from prefetched data (no additional queries)

                image_list = self._serialize_prefetched_images(event.album if hasattr(event, "album") else None)

                photo_count = len(image_list)

                album_data = None

                if hasattr(event, "album") and event.album and image_list:

                    album_data = {
                        "images": image_list,
                    }

                events_data.append(
                    {
                        "id": f"general_{i}",
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.name or event.description or "General Event",
                        "observation": event.observation or "",
                        "performed_by": self._public_performer(event, show_full_names),
                        "type": "general",
                        "event_type": GENERAL_EVENT_TYPE,
                        "certified": getattr(event, "certified", False),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": None,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                        # General event name for title generation
                        "name": getattr(event, "name", None),
                        "variety": getattr(event, "variety", None),
                        "block_id": getattr(event, "block_id", None),
                        "growth_stage": getattr(event, "growth_stage", None),
                        # NEW ACTIVITY FIELDS for complete transparency
                        "activity_type": getattr(event, "activity_type", None),
                        "activity_name": getattr(event, "activity_name", None),
                        "duration": getattr(event, "duration", None),
                        "people_involved": getattr(event, "people_involved", None),
                        # NOP 7 CFR 205.201(b): contamination incident reporting + remediation
                        "is_contamination_incident": getattr(event, "is_contamination_incident", False),
                        "contamination_source": getattr(event, "contamination_source", None),
                        "contamination_affected_area": (
                            float(getattr(event, "contamination_affected_area", None) or 0) or None
                        ),
                        # `corrective_action_taken` is the operator's narrative and routinely
                        # names third parties — the certifier ("Notified CCOF inspector"), the
                        # lab, and the neighbouring farm the drift came from. Owner-gated: the
                        # producer and the certifier PDF keep it; the public page does not
                        # publish a nonconformance filing about someone else's operation.
                        "corrective_action_taken": (
                            getattr(event, "corrective_action_taken", None) if self._is_owner(history) else None
                        ),
                        "corrective_action_date": (
                            event.corrective_action_date.isoformat()
                            if getattr(event, "corrective_action_date", None)
                            else None
                        ),
                        # Whether and when a CERTIFIER was notified is the regulator-facing
                        # half of the filing (7 CFR 205.201(b)) and identifies the certifying
                        # body. Same owner gate. What stays public is the fact that an incident
                        # was recorded, its source and area, and the date it was resolved — the
                        # disclosure a shopper is entitled to, without the paperwork.
                        "certifier_notified": (
                            getattr(event, "certifier_notified", False) if self._is_owner(history) else None
                        ),
                        "certifier_notification_date": (
                            event.certifier_notification_date.isoformat()
                            if self._is_owner(history) and getattr(event, "certifier_notification_date", None)
                            else None
                        ),
                        # Blockchain verification fields from production
                        "blockchain_verified": blockchain_verified,
                        "blockchain_transaction": blockchain_transaction,
                        "photo_content_flag": self._get_photo_content_flag(event),
                        "verification_level": self._get_verification_level_for_event(
                            event,
                            photo_count > 0,
                            blockchain_verified,
                        ),
                    }
                )

            for i, event in enumerate(business_events):
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
                # Get serialized images from prefetched data (no additional queries)

                image_list = self._serialize_prefetched_images(event.album if hasattr(event, "album") else None)

                photo_count = len(image_list)

                album_data = None

                if hasattr(event, "album") and event.album and image_list:

                    album_data = {
                        "images": image_list,
                    }

                events_data.append(
                    {
                        "id": f"business_{i}",
                        "date": event.date.isoformat() if event.date else None,
                        "description": event.name or event.description or f"Business Event - {business_display}",
                        "observation": event.observation or "",
                        "performed_by": self._public_performer(event, show_full_names),
                        "type": "business",
                        "event_type": BUSINESS_EVENT_TYPE,
                        "certified": getattr(event, "certified", False),
                        "index": getattr(event, "index", 0),
                        "volume": None,
                        "concentration": None,
                        "area": getattr(event, "area", None),
                        "equipment": certification_display or business_display,
                        "photo_count": photo_count,
                        "commercial_name": None,
                        "album": album_data,
                        # Business specific fields for consumer display
                        "name": getattr(event, "name", None),
                        "variety": getattr(event, "variety", None),
                        "block_id": getattr(event, "block_id", None),
                        "growth_stage": getattr(event, "growth_stage", None),
                        "business_type": getattr(event, "business_type", None),
                        "business_event_type": getattr(event, "type", None),
                        "certification_type": getattr(event, "certification_type", None),
                        "certification_type_display": certification_display,
                        "certificate_number": getattr(event, "certificate_number", None),
                        "verification_status": getattr(event, "verification_status", None),
                        "sustainability_practice": getattr(event, "sustainability_practice", None),
                        # Gate carbon_credits_unit on truthy carbon_credits_earned to prevent
                        # an orphan "Carbon Credits Unit: tCO2e" card on the consumer QR when
                        # business_type changed from 'carbon_credits' to 'certification' but the
                        # model's default 'tCO2e' unit value persisted on the row. Bug class:
                        # stale conditional field surfaces when parent context changes. Fix
                        # mechanism mirrors Standard Fix #5 (gate in hand-rolled get_events()
                        # dict), even though the field is not commercially sensitive.
                        "carbon_credits_earned": float(getattr(event, "carbon_credits_earned", None) or 0) or None,
                        "carbon_credits_unit": (
                            getattr(event, "carbon_credits_unit", None)
                            if (getattr(event, "carbon_credits_earned", None) or 0)
                            else None
                        ),
                        # FARMER-TYPED free text — the `verified_` prefix is a naming lie.
                        # Published beside a certificate number it reads as third-party
                        # attestation. Withheld unless a USDA Organic Integrity Database match
                        # backs it (ECGT 2024/825, FTC 16 CFR 260.6).
                        "verified_certifier_name": public_certifier_name(
                            getattr(event, "verified_certifier_name", None),
                            getattr(getattr(history, "parcel", None), "establishment", None),
                            getattr(event, "certification_type", None),
                        ),
                        "extra_data": self._sanitize_extra_data_for_public(event),
                        # Blockchain verification fields from production
                        "blockchain_verified": blockchain_verified,
                        "blockchain_transaction": blockchain_transaction,
                        "photo_content_flag": self._get_photo_content_flag(event),
                        "verification_level": self._get_verification_level_for_event(
                            event,
                            photo_count > 0,
                            blockchain_verified,
                        ),
                    }
                )

            # Sort by date first, then by index (for same-day events, preserve creation order)
            events_data.sort(key=lambda x: (x.get("date", ""), x.get("index", 0)))

            self._annotate_consumer_highlights(events_data)

            return [_drop_unset(e) for e in events_data]

        except Exception as e:
            print(f"Error getting optimized events: {e}")
            # Return empty list if there's an error
            return []

    def get_qr_code(self, history):
        if history.qr_code:
            request = self.context.get("request")
            return request.build_absolute_uri(history.qr_code.url) if request else history.qr_code.url
        return None

    def get_images(self, history):
        try:
            request = self.context.get("request")
            images = []

            # Explicit hero/cover override (set by staff in the admin or the finish-production
            # flow). Surfaced FIRST so it becomes images[0] -> the consumer hero background and
            # the lead gallery photo. The dedup pass below keeps it at index 0 even if the same
            # URL also appears in the album/events. Blank -> auto-pick (album then timeline).
            cover_url = getattr(history, "cover_image_url", None)
            if cover_url:
                images.append(cover_url)

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


class HistoryListOptionsSerializer(serializers.ModelSerializer):
    period = serializers.SerializerMethodField()

    class Meta:
        model = History
        fields = ["id", "period"]

    def get_period(self, history):
        return f"{history.start_date.strftime('%m/%d/%Y')} - {history.finish_date.strftime('%m/%d/%Y')}"


# Equipment Event Serializers
class UpdateEquipmentEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = EquipmentEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "equipment_name",
            "fuel_amount",
            "fuel_type",
            "maintenance_cost",
            "hours_used",
            "area_covered",
            "extra_data",
            "name",
            "equipment_type_structured",
            "fuel_consumed",
            "fuel_unit",
            "hours_operated",
            "area_worked",
            "area_unit",
            "operation_efficiency",
            "observation",
        ]
        read_only_fields = ["id"]

    def to_internal_value(self, data):
        """
        Map frontend field names to backend database field names.
        Handles field name mapping and value mapping for equipment events.
        """
        # Create a copy to avoid modifying the original
        data = data.copy()
        ensure_event_description(data, "Equipment activity")  # F01: avoid silent 400 on blank notes

        # Handle custom fields (user-defined additional information)
        custom_fields = self.handle_custom_fields_input(data)

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

        # Call the parent method to handle the rest
        internal_value = super().to_internal_value(data)

        # Get existing extra_data from instance (for updates)
        instance = getattr(self, "instance", None)
        existing_extra_data = instance.extra_data if instance and instance.extra_data else {}

        # Merge custom fields into extra_data
        internal_value["extra_data"] = self.merge_custom_fields(existing_extra_data, custom_fields, instance)

        return internal_value

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

        # Reasonable maximum hours validation
        # UPDATED: Allow realistic multi-day agricultural operations
        # Max 1000 hours = ~125 days of 8-hour work, reasonable for seasonal operations
        if hours_operated is not None and hours_operated > 1000:
            raise serializers.ValidationError(
                {
                    "hours_operated": [
                        f"Hours operated ({hours_operated}h) exceeds maximum for a single event.",
                        "Maximum allowed is 1000 hours per event.",
                        "Tip: For very long operations, consider creating separate seasonal events.",
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

    def to_representation(self, instance):
        """Override to serialize album with images instead of just ID"""
        data = super().to_representation(instance)

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # Include custom fields in response for frontend display
        data = self.add_custom_fields_to_representation(data, instance)

        return data


class EquipmentEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()

    class Meta:
        model = EquipmentEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "event_type",
            "equipment_name",
            "fuel_amount",
            "fuel_type",
            "maintenance_cost",
            "hours_used",
            "area_covered",
            "extra_data",
            "name",
            "equipment_type_structured",
            "fuel_consumed",
            "fuel_unit",
            "hours_operated",
            "area_worked",
            "area_unit",
            "operation_efficiency",
            "observation",
            "image",
            "carbon_data",
            "verification_level",
        ]
        read_only_fields = ["id", "index", "created_by"]

    def get_type(self, equipment_event):
        type_display = equipment_event.get_type_display()
        if type_display is None:
            return "event.equipment.unknown"
        return f"event.equipment.{type_display.lower().replace(' ', '_')}"

    def get_event_type(self, equipment_event):
        return EQUIPMENT_EVENT_TYPE


# Soil Management Event Serializers
class UpdateSoilManagementEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
    # Grazing fields are optional - only relevant for grazing management subtype
    animal_count = serializers.IntegerField(required=False, allow_null=True, default=None)
    grazing_duration_days = serializers.IntegerField(required=False, allow_null=True, default=None)

    class Meta:
        model = SoilManagementEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "soil_ph",
            "organic_matter_percentage",
            "amendment_type",
            "amendment_amount",
            "amendment_product_name",
            "amendment_manufacturer",
            "test_results",
            # §E-2 — lab analysis (LA)
            "sample_matrix",
            "carbon_sequestration_potential",
            "observation",
            "extra_data",
            "name",
            "area_covered",
            "area_unit",
            "fuel_consumed",
            "fuel_unit",
            "fuel_type",
            "equipment_hours",
            "transportation_distance",
            "transportation_unit",
            "production_efficiency",
            "working_depth",
            "depth_unit",
            "soil_texture",
            "soil_moisture",
            "weather_conditions",
            "temperature_range",
            "equipment_used",
            "animal_type",
            "animal_count",
            "grazing_duration_days",
            "grazing_purpose",
            "amendment_amount_numeric",
            "amendment_amount_unit",
            # NOP Compliance: Amendment approval + Compost tracking + Manure timing
            "amendment_organic_approved",
            # Nitrogen content: field N2O + the CA ILRP total-nitrogen-applied figure.
            "amendment_nitrogen_percentage",
            "compost_peak_temp_f",
            "compost_duration_days_at_temp",
            "compost_turning_count",
            "compost_method",
            "compost_initial_cn_ratio",
            "compost_feedstock",
            "compost_temperature_log",
            "manure_harvest_interval",
            "manure_application_date",
            # NOP 5006 — processed animal manure (interval-exempt when documented)
            "manure_treatment",
            "processed_manure_temp_f",
            "processed_manure_attestation",
            # Biodiversity / habitat (HD / NS subtypes)
            "habitat_type",
            "habitat_structure_count",
            "habitat_install_date",
        ]
        read_only_fields = ["id"]

    def to_internal_value(self, data):
        """
        Custom processing to handle Decimal field serialization for JSON storage.
        Ensures all numeric values are properly serialized for extra_data JSONField.
        Also handles custom fields (user-defined additional information).
        """
        import decimal
        from decimal import Decimal, InvalidOperation

        # Create a copy to avoid modifying the original
        data = data.copy()
        ensure_event_description(data, "Soil management")  # F01: avoid silent 400 on blank notes

        # Convert empty strings to None for optional integer fields
        integer_fields = [
            "animal_count",
            "grazing_duration_days",
            "equipment_hours",
            "compost_duration_days_at_temp",
            "compost_turning_count",
            "habitat_structure_count",
        ]
        for field_name in integer_fields:
            if field_name in data and data[field_name] in ("", None):
                data[field_name] = None

        # Convert empty strings to None for optional decimal fields
        # Form sends "" for unfilled numeric inputs; DRF DecimalField rejects empty strings.
        # area_covered is "" for habitat structures (NS) and optional for HD — coerce to null.
        decimal_null_fields = [
            "compost_peak_temp_f",
            "amendment_amount_numeric",
            "compost_initial_cn_ratio",
            "processed_manure_temp_f",
            "area_covered",
        ]
        for field_name in decimal_null_fields:
            if field_name in data and data[field_name] in ("", None):
                data[field_name] = None

        # Convert empty strings to None for optional date fields
        date_fields = ["manure_application_date", "habitat_install_date"]
        for field_name in date_fields:
            if field_name in data and data[field_name] in ("", None):
                data[field_name] = None

        # Handle custom fields (user-defined additional information)
        custom_fields = self.handle_custom_fields_input(data)

        # Extract frontend's extra_data BEFORE super() call
        frontend_extra_data = data.pop("extra_data", {}) or {}

        # Extract fields that don't have model columns into extra_data
        # Biodiversity / habitat (HD / NS): species_planted / wildlife_observed / structure_notes are
        # free-text with no model column — route them into extra_data. cover_crop_species (CC subtype,
        # NOP §205.203) is the same shape: no model column, read back by the audit export from extra_data.
        extra_data_only_fields = [
            "amendment_unit",
            "species_planted",
            "wildlife_observed",
            "structure_notes",
            "cover_crop_species",
        ]
        for field_name in extra_data_only_fields:
            if field_name in data:
                value = data.pop(field_name)
                frontend_extra_data[field_name] = value if value is not None else ""

        # Grazing Summary Mode (GTM-v3): the frontend sends summary fields (is_summary + the
        # rotation totals) at top level; none are model columns, so route them into extra_data —
        # mirroring the production/pest summary pattern. Lets a grazing rotation be one event.
        summary_only_fields = [
            "is_summary",
            "date_start",
            "date_end",
            "event_count",
            "total_grazing_days",
            "area_covered_total",
        ]
        for field_name in summary_only_fields:
            if field_name in data:
                value = data.pop(field_name)
                if value is not None and value != "":
                    frontend_extra_data[field_name] = value

        # Bridge amendment_amount (string from form) → amendment_amount_numeric (Decimal)
        # Bridge amendment_unit (form) → amendment_amount_unit (model column)
        if "amendment_amount" in data and data["amendment_amount"] not in ("", None):
            try:
                data["amendment_amount_numeric"] = Decimal(str(data["amendment_amount"]))
            except (ValueError, InvalidOperation):
                pass
        if "amendment_unit" in frontend_extra_data and frontend_extra_data["amendment_unit"]:
            data["amendment_amount_unit"] = frontend_extra_data["amendment_unit"]

        # Process the data through parent first
        internal_value = super().to_internal_value(data)

        # Convert any Decimal fields to strings for JSON serialization
        decimal_fields = [
            "soil_ph",
            "organic_matter_percentage",
            "area_covered",
            "fuel_consumed",
            "carbon_sequestration_potential",
            "amendment_amount_numeric",
            "compost_peak_temp_f",
            "compost_initial_cn_ratio",
            "processed_manure_temp_f",
        ]

        for field_name in decimal_fields:
            if field_name in internal_value and internal_value[field_name] is not None:
                if isinstance(internal_value[field_name], Decimal):
                    # Convert Decimal to string to ensure JSON serialization works
                    internal_value[field_name] = str(internal_value[field_name])

        # Handle extra_data field specifically - ensure all nested Decimal objects are converted
        if frontend_extra_data:

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

            frontend_extra_data = convert_decimals_in_dict(frontend_extra_data)

        # Merge: existing extra_data + frontend extra_data (frontend wins on conflicts)
        instance = getattr(self, "instance", None)
        existing_extra_data = instance.extra_data if instance and instance.extra_data else {}
        merged_extra_data = {**existing_extra_data, **frontend_extra_data}

        # Handle custom_fields inline
        if custom_fields:
            merged_extra_data["custom_fields"] = custom_fields
        elif instance and instance.extra_data and "custom_fields" in instance.extra_data:
            merged_extra_data["custom_fields"] = instance.extra_data["custom_fields"]

        internal_value["extra_data"] = merged_extra_data

        return internal_value

    def to_representation(self, instance):
        """Override to serialize album with images instead of just ID"""
        data = super().to_representation(instance)

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # Include custom fields in response for frontend display
        data = self.add_custom_fields_to_representation(data, instance)

        return data

    def validate(self, attrs):
        """Enforce the NOP raw-manure pre-harvest interval (7 CFR 205.203(c)(1)) on the API write
        path. SoilManagementEvent.clean() carries these rules, but DRF never calls full_clean() on
        objects.create()/update(), so without this a farmer could log a manure application via the
        API with a missing or crop-mismatched harvest interval — a record-keeping failure a CCOF
        inspector reads under § 205.103. Scoped to the manure rules only (we deliberately do NOT run
        the full clean(), which also hard-errors on transportation/fuel bounds and would change
        unrelated behavior). Mirrors the WeatherEvent probe.clean() enforcement pattern.
        """
        attrs = super().validate(attrs)
        instance = getattr(self, "instance", None)

        def _field(name):
            if name in attrs:
                return attrs.get(name)
            return getattr(instance, name, None)

        manure_date = _field("manure_application_date")
        interval = _field("manure_harvest_interval")

        if manure_date and not interval:
            raise serializers.ValidationError(
                {
                    "manure_harvest_interval": "Harvest interval (90 or 120 days) is required when a "
                    "manure application date is specified."
                }
            )

        # Interval must match the crop's edible-portion soil contact when the crop type carries an
        # authoritative flag; otherwise defer (the PDF-side linter handles unknown crops).
        if interval in ("90", "120"):
            history = attrs.get("history") or (instance.history if instance else None)
            crop_type = None
            try:
                crop_type = history.crop_type if history else None
            except Exception:  # noqa: BLE001 — FK may be unpopulated
                crop_type = None
            has_contact = getattr(crop_type, "has_soil_contact", None) if crop_type else None
            if has_contact is not None:
                has_contact = bool(has_contact)
                if has_contact and interval == "90":
                    raise serializers.ValidationError(
                        {
                            "manure_harvest_interval": "This crop's edible portion has direct soil "
                            "contact, so 7 CFR 205.203(c)(1)(ii) requires a 120-day pre-harvest "
                            "interval. Selecting 90 days is a record-keeping mismatch."
                        }
                    )
                if not has_contact and interval == "120":
                    raise serializers.ValidationError(
                        {
                            "manure_harvest_interval": "This crop's edible portion does NOT contact "
                            "soil (tree / canopy crop), so 7 CFR 205.203(c)(1)(iii) requires a "
                            "90-day pre-harvest interval. The 120-day choice is for root/leafy crops."
                        }
                    )

        return attrs


class SoilManagementEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()
    soil_management_type = serializers.SerializerMethodField()

    # §E-2 — lab results have always been WRITTEN into the `test_results` JSONField by the soil
    # form, but nothing ever read them back out by name: the display registry resolves a field
    # from the top level or from `extra_data` only, so every lab value was write-only. Flattening
    # them here (rather than promoting them to columns) keeps the historical ST rows readable
    # with no migration and no backfill, and gives the registry and the PDF real field names.
    # Read-only on purpose — the write path stays the `test_results` JSON the form already sends.
    LAB_RESULT_FIELDS = {
        "lab_name": "lab_name",
        "lab_sample_id": "sample_id",
        "lab_report_date": "report_date",
        "lab_nitrogen": "nitrogen",
        "lab_phosphorus": "phosphorus",
        "lab_potassium": "potassium",
        "lab_cec": "cec",
        # Micronutrient results — the deficiency record that § 205.601(j)(6) requires before a
        # micronutrient application (see ChemicalEvent.micronutrient_type).
        "lab_zinc_ppm": "zinc_ppm",
        "lab_boron_ppm": "boron_ppm",
        "lab_manganese_ppm": "manganese_ppm",
        "lab_iron_ppm": "iron_ppm",
    }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        results = instance.test_results if isinstance(instance.test_results, dict) else {}
        for out_key, json_key in self.LAB_RESULT_FIELDS.items():
            data[out_key] = results.get(json_key)
        return data

    class Meta:
        model = SoilManagementEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "event_type",
            "soil_management_type",
            "soil_ph",
            "organic_matter_percentage",
            "amendment_type",
            "amendment_amount",
            "amendment_product_name",
            "amendment_manufacturer",
            "test_results",
            # §E-2 — lab analysis (LA)
            "sample_matrix",
            "carbon_sequestration_potential",
            "observation",
            "extra_data",
            "name",
            "area_covered",
            "area_unit",
            "fuel_consumed",
            "fuel_unit",
            "fuel_type",
            "equipment_hours",
            "transportation_distance",
            "transportation_unit",
            "production_efficiency",
            "working_depth",
            "depth_unit",
            "soil_texture",
            "soil_moisture",
            "weather_conditions",
            "temperature_range",
            "equipment_used",
            "animal_type",
            "animal_count",
            "grazing_duration_days",
            "grazing_purpose",
            "amendment_amount_numeric",
            "amendment_amount_unit",
            # NOP Compliance: Amendment approval + Compost tracking + Manure timing
            "amendment_organic_approved",
            # Nitrogen content: field N2O + the CA ILRP total-nitrogen-applied figure.
            "amendment_nitrogen_percentage",
            "compost_peak_temp_f",
            "compost_duration_days_at_temp",
            "compost_turning_count",
            "compost_method",
            "compost_initial_cn_ratio",
            "compost_feedstock",
            "compost_temperature_log",
            "manure_harvest_interval",
            "manure_application_date",
            # Biodiversity / habitat (HD / NS) — needed so the producer edit form pre-fills them
            "habitat_type",
            "habitat_structure_count",
            "habitat_install_date",
            "image",
            "carbon_data",
            "verification_level",
            # Sprint 5.1 — OSP ↔ events drift detector finding (null when in-OSP)
            "drift_warning",
        ]
        read_only_fields = ["id", "index", "created_by", "drift_warning"]

    def get_type(self, soil_event):
        type_display = soil_event.get_type_display()
        if type_display is None:
            return "event.soil.unknown"
        return f"event.soil.{type_display.lower().replace(' ', '_')}"

    def get_soil_management_type(self, soil_event):
        """Return raw soil management type code (ST, PA, OM, CC, TI, CO, GR) for frontend registry"""
        return soil_event.type

    def get_event_type(self, soil_event):
        return SOIL_MANAGEMENT_EVENT_TYPE


# Pest Management Event Serializers
class UpdatePestManagementEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = PestManagementEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "pest_species",
            "pest_pressure_level",
            "monitoring_count",
            "monitoring_unit",
            "beneficial_species",
            "release_quantity",
            # Beneficial-release traceability (BR) — NOP 205.206
            "beneficial_supplier",
            "beneficial_lot_number",
            "beneficial_organic_approved",
            "trap_count",
            # Trap monitoring (TM) detail
            "trap_type",
            "pest_catch_count",
            "damage_percentage",
            "action_threshold_met",
            "ipm_strategy",
            "observation",
            "extra_data",
            "beneficial_insects_used",
            "chemical_free_period_days",
            "area_covered",
            "area_unit",
            "fuel_consumed",
            "fuel_unit",
            "fuel_type",
            "equipment_hours",
            "production_efficiency",
            # NOP Compliance: Pest ID verification + Threshold rationale
            "identified_by",
            "identification_method",
            "threshold_rationale",
            # §E-4 — cultural / sanitation control (§ 205.206(a))
            "cultural_practice",
        ]
        read_only_fields = ["id"]

    def to_internal_value(self, data):
        """
        Handle custom fields and frontend extra_data for pest management events.
        Frontend sends summary mode fields (is_summary, pest_species_observed,
        average_pest_pressure, event_count, area_covered_total, etc.) inside extra_data.
        These must be extracted BEFORE super() and merged with existing extra_data.
        """
        # Create a copy to avoid modifying the original
        data = data.copy()

        # Convert empty strings to appropriate values for integer/boolean fields
        nullable_int_fields = [
            "trap_count",
            "chemical_free_period_days",
            "release_quantity_number",
        ]
        for field in nullable_int_fields:
            if field in data and data[field] == "":
                data[field] = None

        # F17 fix (2026-06): a blank threshold answer is "not assessed" (None), NOT a definitive
        # "below threshold" (False). Coercing "" -> False fabricated a NOP 205.206(e) record.
        if "action_threshold_met" in data and data["action_threshold_met"] in ("", None):
            data["action_threshold_met"] = None

        # The form's only threshold control is "Economic Threshold Status", which posts
        # `economic_threshold_met` — an extra_data-only key. Nothing posts
        # `action_threshold_met`, so that column stayed NULL on every UI-logged event and the
        # certifier PDF printed "Not assessed" even for a grower who had explicitly answered
        # "threshold not met". Promote the answer onto its real column; keep the extra_data
        # copy for back-compat. Absence still means not assessed (F17) — only an affirmative
        # yes/no is recorded, never inferred.
        # `is None`, not falsiness: an explicit action_threshold_met=False is a real "assessed,
        # below threshold" answer, and `not False` would have let the form key overwrite it.
        # By this point the block above has already normalised a blank "" to None, so None here
        # means "the caller did not answer on the column".
        if data.get("action_threshold_met") is None and data.get("economic_threshold_met") not in ("", None):
            raw_threshold = data.get("economic_threshold_met")
            if isinstance(raw_threshold, bool):
                data["action_threshold_met"] = raw_threshold
            elif str(raw_threshold).strip().lower() in ("true", "yes", "1"):
                data["action_threshold_met"] = True
            elif str(raw_threshold).strip().lower() in ("false", "no", "0"):
                data["action_threshold_met"] = False

        if "damage_percentage" in data and data["damage_percentage"] == "":
            data["damage_percentage"] = None

        # Ensure description is not blank - use observations_summary or event_name as fallback
        if not data.get("description"):
            fallback = data.get("observations_summary") or data.get("event_name") or "Pest management activity"
            data["description"] = fallback

        # Extract frontend's extra_data BEFORE super() call
        # Frontend sends summary fields (is_summary, pest_species_observed, etc.) inside extra_data
        frontend_extra_data = data.pop("extra_data", {}) or {}

        # Extract fields that don't have model columns into extra_data
        extra_data_only_fields = [
            "name",
            "observations_summary",
            "crop_growth_stage",
            "economic_threshold_met",
            "action_recommended",
        ]
        for field_name in extra_data_only_fields:
            if field_name in data:
                value = data.pop(field_name)
                # F32 fix (2026-06): don't clobber a real value already in extra_data
                # with an empty top-level field. The frontend copies observation ->
                # extra_data.observations_summary for summary events, while the
                # never-rendered top-level field submits "" — overwriting wiped the
                # real summary (consumer card showed blank). Only take the top-level
                # value when it is non-empty or extra_data doesn't already carry it.
                if (value not in (None, "")) or (field_name not in frontend_extra_data):
                    frontend_extra_data[field_name] = value if value is not None else ""

        # Handle custom fields (user-defined additional information)
        custom_fields = self.handle_custom_fields_input(data)

        # Call the parent method to handle the rest
        internal_value = super().to_internal_value(data)

        # Get existing extra_data from instance (for updates)
        instance = getattr(self, "instance", None)
        existing_extra_data = instance.extra_data if instance and instance.extra_data else {}

        # Merge: existing extra_data + frontend extra_data (frontend wins on conflicts)
        merged_extra_data = {**existing_extra_data, **frontend_extra_data}

        # Handle custom_fields inline to avoid merge_custom_fields overwriting merged data
        if custom_fields:
            merged_extra_data["custom_fields"] = custom_fields
        elif instance and instance.extra_data and "custom_fields" in instance.extra_data:
            merged_extra_data["custom_fields"] = instance.extra_data["custom_fields"]

        internal_value["extra_data"] = merged_extra_data

        return internal_value

    def to_representation(self, instance):
        """Override to serialize album with images instead of just ID"""
        data = super().to_representation(instance)

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # Include custom fields in response for frontend display
        data = self.add_custom_fields_to_representation(data, instance)

        # Extract name from extra_data if present (no model column for name)
        extra_data = instance.extra_data or {} if hasattr(instance, "extra_data") else {}
        if extra_data.get("name"):
            data["name"] = extra_data["name"]

        return data


class PestManagementEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()
    pest_management_type = serializers.SerializerMethodField()

    class Meta:
        model = PestManagementEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "event_type",
            "pest_management_type",
            "pest_species",
            "pest_pressure_level",
            "monitoring_count",
            "monitoring_unit",
            "beneficial_species",
            "release_quantity",
            # Beneficial-release traceability (BR) — NOP 205.206
            "beneficial_supplier",
            "beneficial_lot_number",
            "beneficial_organic_approved",
            "trap_count",
            # Trap monitoring (TM) detail
            "trap_type",
            "pest_catch_count",
            "damage_percentage",
            "action_threshold_met",
            "ipm_strategy",
            "observation",
            "extra_data",
            "beneficial_insects_used",
            "chemical_free_period_days",
            "area_covered",
            "area_unit",
            "fuel_consumed",
            "fuel_unit",
            "fuel_type",
            "equipment_hours",
            "production_efficiency",
            # NOP Compliance: Pest ID verification + Threshold rationale
            "identified_by",
            "identification_method",
            "threshold_rationale",
            # §E-4 — cultural / sanitation control (§ 205.206(a))
            "cultural_practice",
            "image",
            "carbon_data",
            "verification_level",
        ]
        read_only_fields = ["id", "index", "created_by"]

    def get_type(self, pest_event):
        type_display = pest_event.get_type_display()
        if type_display is None:
            return "event.pest.unknown"
        return f"event.pest.{type_display.lower().replace(' ', '_')}"

    def get_pest_management_type(self, pest_event):
        """Return raw pest management type code (SC, BR, TM, PI, TA, IP) for frontend registry"""
        return pest_event.type

    def get_event_type(self, pest_event):
        return PEST_MANAGEMENT_EVENT_TYPE

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Extract name from extra_data so frontend can access it as event.name
        extra_data = instance.extra_data or {} if hasattr(instance, "extra_data") else {}
        if extra_data.get("name"):
            data["name"] = extra_data["name"]
        return data


# Business Event Serializers
class UpdateBusinessEventSerializer(CustomFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = BusinessEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "name",
            "business_type",
            "certification_type",
            "carbon_credits_earned",
            "carbon_credits_unit",
            "verification_status",
            "sustainability_practice",
            "verified_certifier_name",
            "certificate_number",
            "observation",
            "extra_data",
        ]
        read_only_fields = ["id"]

    def to_internal_value(self, data):
        """
        Handle custom fields and non-model fields for business events.
        trust_impact and transparency_benefit have no model columns and must be
        stored in extra_data.
        """
        # Create a copy to avoid modifying the original
        data = data.copy()
        ensure_event_description(data, "Business event")  # F01: avoid silent 400 on blank notes

        # Handle custom fields (user-defined additional information)
        custom_fields = self.handle_custom_fields_input(data)

        # Extract frontend's extra_data BEFORE super() call
        frontend_extra_data = data.pop("extra_data", {}) or {}

        # Extract fields that don't have model columns into extra_data
        extra_data_only_fields = ["trust_impact", "transparency_benefit"]
        for field_name in extra_data_only_fields:
            if field_name in data:
                value = data.pop(field_name)
                frontend_extra_data[field_name] = value if value is not None else ""

        # Call the parent method to handle the rest
        internal_value = super().to_internal_value(data)

        # Merge: existing extra_data + frontend extra_data (frontend wins on conflicts)
        instance = getattr(self, "instance", None)
        existing_extra_data = instance.extra_data if instance and instance.extra_data else {}
        merged_extra_data = {**existing_extra_data, **frontend_extra_data}

        # Handle custom_fields inline
        if custom_fields:
            merged_extra_data["custom_fields"] = custom_fields
        elif instance and instance.extra_data and "custom_fields" in instance.extra_data:
            merged_extra_data["custom_fields"] = instance.extra_data["custom_fields"]

        internal_value["extra_data"] = merged_extra_data

        return internal_value

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

    def to_representation(self, instance):
        """Override to serialize album with images instead of just ID"""
        data = super().to_representation(instance)

        # Serialize album with images instead of just returning ID
        if hasattr(instance, "album") and instance.album:
            request = self.context.get("request")
            data["album"] = serialize_event_album(instance, request)

        # Include custom fields in response for frontend display
        data = self.add_custom_fields_to_representation(data, instance)

        return data


class BusinessEventSerializer(EventSerializer):
    type = serializers.SerializerMethodField()
    event_type = serializers.SerializerMethodField()
    business_event_type = serializers.SerializerMethodField()

    # Add display fields for better readability
    business_type_display = serializers.SerializerMethodField()
    certification_type_display = serializers.SerializerMethodField()
    verification_status_display = serializers.SerializerMethodField()
    sustainability_practice_display = serializers.SerializerMethodField()

    class Meta:
        model = BusinessEvent
        fields = [
            "id",
            "description",
            "date",
            "album",
            "history",
            "index",
            "created_by",
            "performed_by",
            "variety",
            "block_id",
            "growth_stage",
            "type",
            "event_type",
            "business_event_type",
            "name",
            "business_type",
            "business_type_display",
            "certification_type",
            "certification_type_display",
            "carbon_credits_earned",
            "carbon_credits_unit",
            "verification_status",
            "verification_status_display",
            "sustainability_practice",
            "sustainability_practice_display",
            "verified_certifier_name",
            "certificate_number",
            "observation",
            "extra_data",
            "image",
            "carbon_data",
            "verification_level",
        ]
        read_only_fields = ["id", "index", "created_by"]

    def get_type(self, business_event):
        type_display = business_event.get_type_display()
        if type_display is None:
            return "event.business.unknown"
        return f"event.business.{type_display.lower().replace(' ', '_')}"

    def get_business_event_type(self, business_event):
        """Return raw business event type code (CE, AU, TR, IN, CC) for frontend registry"""
        return business_event.type

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


class BuyerDocRequestCreateSerializer(serializers.ModelSerializer):
    """Public create — consumer proof view buyer CTA. Production resolved
    from public_id in the view (never expose integer IDs publicly)."""

    class Meta:
        model = BuyerDocRequest
        fields = ["requester_name", "requester_email", "organization", "message"]

    def validate_message(self, value):
        if value and len(value) > 1000:
            raise serializers.ValidationError("Message too long (max 1000 characters)")
        return value


class BuyerDocRequestSerializer(serializers.ModelSerializer):
    """Owner-facing lead list row."""

    production_public_id = serializers.UUIDField(source="production.public_id", read_only=True)
    production_name = serializers.CharField(source="production.name", read_only=True)
    product_name = serializers.CharField(source="production.product.name", read_only=True, default=None)
    lot_id = serializers.CharField(source="production.lot_id", read_only=True, default=None)

    class Meta:
        model = BuyerDocRequest
        fields = [
            "id",
            "production_public_id",
            "production_name",
            "product_name",
            "lot_id",
            "requester_name",
            "requester_email",
            "organization",
            "message",
            "status",
            "created_at",
        ]
        read_only_fields = [f for f in fields if f != "status"]


class SalesRecordSerializer(serializers.ModelSerializer):
    """Owner-facing sales record (SOE traceback). Never on public endpoints."""

    class Meta:
        model = SalesRecord
        fields = [
            "id",
            "sale_date",
            "buyer_name",
            "quantity",
            "quantity_unit",
            "invoice_number",
            "organic_on_invoice",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
