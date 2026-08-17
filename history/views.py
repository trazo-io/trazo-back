import json
import logging
import threading
import uuid
from datetime import datetime, timedelta

from django.core.cache import cache
from django.db import connections, transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views.decorators.gzip import gzip_page

from dateutil import parser as date_parser
from drf_spectacular.utils import OpenApiParameter, PolymorphicProxySerializer, extend_schema, extend_schema_view
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.decorators import permission_classes as permission_classes_decorator
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from backend.permissions import CompanyNestedViewSet
from common.us_states import resolve_establishment_state
from notifications.services import notification_service
from product.models import Parcel, Product
from reviews.models import Review
from subscriptions.gating import require_compliance_exports
from subscriptions.permissions import HasProductionCreationPermission

from .constants import (
    ALLOWED_PERIODS,
    BUSINESS_EVENT_TYPE,
    CHEMICAL_EVENT_TYPE,
    EQUIPMENT_EVENT_TYPE,
    EVENT_TYPE_TO_MODEL,
    GENERAL_EVENT_TYPE,
    PEST_MANAGEMENT_EVENT_TYPE,
    PRODUCTION_EVENT_TYPE,
    SOIL_MANAGEMENT_EVENT_TYPE,
    WEATHER_EVENT_TYPE,
)
from .models import (
    BusinessEvent,
    BuyerDocRequest,
    ChemicalEvent,
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
from .serializers import (
    BusinessEventSerializer,
    ChemicalEventSerializer,
    EquipmentEventSerializer,
    GeneralEventSerializer,
    HistorySerializer,
    HistoryWriteSerializer,
    ListHistoryClassSerializer,
    OptimizedHistoryListSerializer,
    PestManagementEventSerializer,
    ProductionEventSerializer,
    PublicHistorySerializer,
    SoilManagementEventSerializer,
    UpdateBusinessEventSerializer,
    UpdateChemicalEventSerializer,
    UpdateEquipmentEventSerializer,
    UpdateGeneralEventSerializer,
    UpdatePestManagementEventSerializer,
    UpdateProductionEventSerializer,
    UpdateSoilManagementEventSerializer,
    UpdateWeatherEventSerializer,
    WeatherEventSerializer,
)

logger = logging.getLogger(__name__)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _background_create_events(viewset_instance, history_id, template_events, template_id):
    """
    Create template events and QR code in a background thread.

    Called via transaction.on_commit() after the History is committed to the DB.
    Each thread gets its own DB connection which is cleaned up in finally.

    TODO(celery): When Celery is available, convert to @shared_task and call
    via .delay(). Remove connections.close_all() and transaction.on_commit wrapper.
    """
    try:
        history = History.objects.get(id=history_id)

        # Create events FIRST so they appear in polling immediately (~1s)
        viewset_instance._create_template_events(history, template_events, template_id=template_id)
        History.objects.filter(id=history_id).update(events_status="ready")
        logger.info("Background event creation completed for history %s", history_id)

        # Generate QR code AFTER events (takes ~40s for Pillow + S3 upload)
        history.generate_qr_code(is_new=True)
        logger.info("Background QR code generated for history %s", history_id)
    except Exception as e:
        logger.exception("Background event creation failed for history %s: %s", history_id, e)
        History.objects.filter(id=history_id).update(events_status="failed")
    finally:
        connections.close_all()


def _background_generate_qr(history_id):
    """Generate QR code in background when no template events are needed."""
    try:
        history = History.objects.get(id=history_id)
        history.generate_qr_code(is_new=True)
        logger.info("Background QR code generated for history %s", history_id)
    except Exception as e:
        logger.exception("Background QR generation failed for history %s: %s", history_id, e)
    finally:
        connections.close_all()


def _fit_label_text(canvas_obj, text, font, size, max_width, min_size=7.0, max_lines=2):
    """Fit `text` into `max_width` by shrinking then word-wrapping. Never cuts characters.

    A lot tag is a physical § 205.307 nonretail container label, so a clipped string is a
    defective label rather than a cosmetic issue. The previous code sliced by CHARACTER
    COUNT (`organic_line[:40]`, `farm_name[:32]`), which is blind to glyph width and to
    where the string ends: a CCOF-certified grower's tag printed

        "Certified organic by California Certifie"

    because "Certified organic by California Certified Organic Farmers" is 57 characters.
    Same class of bug as the audit-PDF truncation rule — measure with stringWidth, and
    when it still does not fit, wrap instead of cut.

    Returns (size, lines). Only the final line may be ellipsised, and only if the text
    cannot be made to fit at `min_size` across `max_lines`.
    """
    words = (text or "").split()
    if not words:
        return size, []

    def wrap_at(pt):
        lines, current = [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if canvas_obj.stringWidth(candidate, font, pt) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    pt = size
    while pt >= min_size:
        lines = wrap_at(pt)
        if len(lines) <= max_lines and all(canvas_obj.stringWidth(ln, font, pt) <= max_width for ln in lines):
            return pt, lines
        pt -= 0.5

    lines = wrap_at(min_size)[:max_lines]
    while lines and canvas_obj.stringWidth(lines[-1] + "…", font, min_size) > max_width and len(lines[-1]) > 1:
        lines[-1] = lines[-1][:-1]
    if lines:
        lines[-1] += "…"
    return min_size, lines


class HistoryViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    serializer_class = HistorySerializer
    filter_backends = [filters.OrderingFilter]

    def get_permissions(self):
        if self.action in ["create", "start_production"]:
            return [IsAuthenticated(), HasProductionCreationPermission()]
        return super().get_permissions()

    def get_object(self):
        """
        Resolve the history by either integer pk or UUID (public_id).

        The frontend routes productions by their UUID (public_id) — e.g.
        /production/<uuid>/ — and passes that same identifier to mutations
        like partial_update. Without this override, PATCH /histories/<uuid>/
        would raise 404 because DRF's default lookup tries to coerce the
        UUID into an integer pk.
        """
        import uuid as uuid_module

        lookup_value = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)
        if lookup_value is not None:
            try:
                uuid_module.UUID(str(lookup_value))
                queryset = self.filter_queryset(self.get_queryset())
                obj = get_object_or_404(queryset, public_id=lookup_value)
                self.check_object_permissions(self.request, obj)
                return obj
            except (ValueError, AttributeError):
                pass
        return super().get_object()

    def check_write_permission(self, request, history_obj):
        """Check that the user has write access (CA or FM role) for this history's company."""
        from users.models import WorksIn

        if request.user.is_superuser:
            return
        company = history_obj.parcel.establishment.company if history_obj.parcel else None
        if company is None:
            raise PermissionDenied("Cannot determine company for this production.")
        has_write = WorksIn.objects.filter(
            user=request.user,
            company=company,
            role__in=[WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER],
        ).exists()
        if not has_write:
            raise PermissionDenied("You do not have permission to perform this action.")

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return HistoryWriteSerializer
        elif self.action == "create":
            return HistorySerializer
        elif self.action == "list":
            # Use optimized serializer for dashboard list view
            return OptimizedHistoryListSerializer
        else:
            return HistorySerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def get_queryset(self):
        """
        Optimized queryset with proper database optimizations to prevent N+1 queries.
        """
        if self.action == "public_history":
            # Published productions are visible to anyone; a producer previewing
            # their OWN unpublished (draft/in-progress) production is also allowed
            # so the ProfileProduction page loads before publishing. The per-object
            # owner check below (owns_it) still gates integer-id lookups.
            _user = getattr(self.request, "user", None)
            if _user is not None and _user.is_authenticated:
                _visibility = Q(published=True) | Q(parcel__establishment__company__in=_user.companies.all())
            else:
                _visibility = Q(published=True)
            return (
                History.objects.filter(_visibility)
                .select_related(
                    "product",
                    "parcel__establishment__company",
                    "parcel__establishment",
                    "operator",
                    "album",
                )
                .prefetch_related(
                    Prefetch(
                        "history_weatherevent_events",
                        queryset=WeatherEvent.objects.select_related("album").prefetch_related("album__images"),
                    ),
                    Prefetch(
                        "history_chemicalevent_events",
                        queryset=ChemicalEvent.objects.select_related("album").prefetch_related("album__images"),
                    ),
                    Prefetch(
                        "history_productionevent_events",
                        queryset=ProductionEvent.objects.select_related("album").prefetch_related("album__images"),
                    ),
                    Prefetch(
                        "history_generalevent_events",
                        queryset=GeneralEvent.objects.select_related("album").prefetch_related("album__images"),
                    ),
                    Prefetch(
                        "history_equipmentevent_events",
                        queryset=EquipmentEvent.objects.select_related("album").prefetch_related("album__images"),
                    ),
                    Prefetch(
                        "history_soilmanagementevent_events",
                        queryset=SoilManagementEvent.objects.select_related("album").prefetch_related("album__images"),
                    ),
                    Prefetch(
                        "history_pestmanagementevent_events",
                        queryset=PestManagementEvent.objects.select_related("album").prefetch_related("album__images"),
                    ),
                    Prefetch(
                        "history_businessevent_events",
                        queryset=BusinessEvent.objects.select_related("album").prefetch_related("album__images"),
                    ),
                )
            )
        elif self.action == "my_scans":
            return (
                History.objects.filter(history_scans__user=self.request.user)
                .select_related("product", "parcel__establishment")
                .prefetch_related(
                    "history_weatherevent_events",
                    "history_chemicalevent_events",
                    "history_productionevent_events",
                    "history_generalevent_events",
                    "history_equipmentevent_events",
                    "history_soilmanagementevent_events",
                    "history_pestmanagementevent_events",
                    "history_businessevent_events",
                )
                .order_by("id", "-history_scans__date")
                .distinct("id")
            )
        elif self.action == "my_reviews":
            return (
                Review.objects.filter(user=self.request.user)
                .select_related("production", "production__product", "production__parcel__establishment")
                .order_by("-date")
            )
        elif self.action == "list":
            # Optimized queryset for dashboard list view
            return self.get_optimized_list_queryset()
        else:
            # For other actions, apply parcel filtering if parcel_pk is provided
            queryset = History.objects.all()
            parcel_pk = self.kwargs.get("parcel_pk")
            if parcel_pk:
                queryset = queryset.filter(parcel_id=parcel_pk)
            return queryset

    def get_optimized_list_queryset(self):
        """
        Ultra-optimized queryset for the dashboard list view that completely avoids
        event-related queries and uses minimal data.
        """
        # Get parcel_pk from URL parameters
        parcel_pk = self.kwargs.get("parcel_pk")

        # Ultra-minimal queryset - no events, no complex relationships
        # Note: We don't cache querysets directly as they can't be serialized
        from django.db.models import Count

        queryset = (
            History.objects.select_related("product", "parcel", "crop_type")
            .only(
                # Only fetch absolutely essential fields for the dashboard
                "id",
                "public_id",
                "name",
                "start_date",
                "finish_date",
                "published",
                "earning",
                "reputation",
                "qr_code",
                "is_outdoor",
                "age_of_plants",
                "number_of_plants",
                "soil_ph",
                "extra_data",
                "transparency_score",
                # Traceability: the lot identifier a certifier traces forward from at
                # inspection (§ 205.103(b)(2)). Read-only on the list; the editor is the
                # finish-production form.
                "lot_id",
                # Legacy sale columns — see `sales_record_count` below for why both are read.
                "sale_date",
                "quantity_sold",
                "product__id",
                "product__name",
                "parcel__id",
                "parcel__name",
                "crop_type__id",
                "crop_type__name",
                "crop_type__category",
                "crop_type__slug",
            )
            .annotate(
                total_events_count=(
                    Count("history_productionevent_events", distinct=True)
                    + Count("history_chemicalevent_events", distinct=True)
                    + Count("history_generalevent_events", distinct=True)
                    + Count("history_equipmentevent_events", distinct=True)
                    + Count("history_soilmanagementevent_events", distinct=True)
                    + Count("history_pestmanagementevent_events", distinct=True)
                    + Count("history_businessevent_events", distinct=True)
                    + Count("history_weatherevent_events", distinct=True)
                ),
                # Annotated, not `.exists()` in the serializer: this list renders one card per
                # season, so a per-row existence check is a textbook N+1.
                sales_record_count=Count("sales_records", distinct=True),
            )
            .order_by("-start_date")
        )

        # WS-6: list is always scoped to the caller's companies — before this the
        # top-level /histories/ list had no tenant filter at all (the parcel-nested
        # path masked it because parcel_pk narrowed the rows).
        user = getattr(self.request, "user", None)
        if user is not None and user.is_authenticated:
            queryset = queryset.filter(parcel__establishment__company__in=user.companies.all())

        # Filter by parcel if parcel_pk is provided
        if parcel_pk:
            queryset = queryset.filter(parcel_id=parcel_pk)

        # WS-6 Buyer Page: farm-level production list.
        establishment_id = self.request.query_params.get("establishment")
        if establishment_id:
            queryset = queryset.filter(parcel__establishment_id=establishment_id)

        # Filter by product if provided as query param
        product_id = self.request.query_params.get("product")
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        # Filter to only completed productions if requested
        if self.request.query_params.get("completed") == "true":
            queryset = queryset.filter(finish_date__isnull=False)

        return queryset

    def list(self, request, *args, **kwargs):
        """
        Optimized list method with caching and performance monitoring.
        """
        import time

        start_time = time.time()

        queryset = self.filter_queryset(self.get_queryset())

        # Add performance logging
        query_time = time.time() - start_time
        if query_time > 1.0:  # Log slow queries
            logger.warning("Slow history query detected: %.2fs for parcel %s", query_time, self.kwargs.get("parcel_pk"))

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """Override update to invalidate cache and enforce visibility rules."""
        instance = self.get_object()
        self.check_write_permission(request, instance)

        # BUSINESS RULE: Active (in-progress) productions cannot be made visible to consumers
        # Only completed productions (those with finish_date) can be published
        requested_published = request.data.get("published")

        if requested_published is True and instance.finish_date is None:
            return Response(
                {
                    "error": "Active productions cannot be made visible to consumers",
                    "detail": "Complete the production first by setting a finish_date before making it visible.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        response = super().update(request, *args, **kwargs)

        # Invalidate cache for this parcel's history list
        parcel_id = self.kwargs.get("parcel_pk")
        if parcel_id:
            cache_key = f"history_list_parcel_{parcel_id}_v3"
            cache.delete(cache_key)

        return response

    def partial_update(self, request, *args, **kwargs):
        """Override partial_update to enforce role-based permissions and cache invalidation."""
        instance = self.get_object()
        self.check_write_permission(request, instance)

        response = super().partial_update(request, *args, **kwargs)

        parcel_id = self.kwargs.get("parcel_pk")
        if parcel_id:
            cache_key = f"history_list_parcel_{parcel_id}_v3"
            cache.delete(cache_key)

        return response

    def destroy(self, request, *args, **kwargs):
        """Override destroy to invalidate cache and enforce role-based permissions."""
        instance = self.get_object()
        self.check_write_permission(request, instance)

        # Get parcel_id before deletion
        parcel_id = self.kwargs.get("parcel_pk")

        response = super().destroy(request, *args, **kwargs)

        # Invalidate cache for this parcel's history list
        if parcel_id:
            cache_key = f"history_list_parcel_{parcel_id}_v3"
            cache.delete(cache_key)

        return response

    def create(self, request, *args, **kwargs):
        """
        Create a production on the nested route.

        *args/**kwargs are required: this viewset is mounted under
        /companies/{company_pk}/establishments/{establishment_pk}/parcels/{parcel_pk}/,
        so the router always passes those as keyword arguments. Without them every POST
        raised `create() got an unexpected keyword argument 'company_pk'` — a 500 on the
        whole endpoint. (The UI creates productions through the flat
        `histories/start-production/` action, which is why this went unnoticed.)

        Missing fields are answered with 400 rather than a KeyError 500.
        """
        data = request.data

        required = ["parcel", "product", "start_date"]
        missing = [f for f in required if not data.get(f)]
        if missing:
            return Response(
                {f: ["This field is required."] for f in missing},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parcel = get_object_or_404(Parcel, id=data["parcel"])
        # Scope the parcel to the caller's company — the URL is nested, but this method
        # previously trusted the body's parcel id outright.
        if not request.user.companies.filter(id=parcel.establishment.company_id).exists():
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        product = data["product"]
        product_name = product.get("name") if isinstance(product, dict) else product
        if not product_name:
            return Response({"product": ["A product name is required."]}, status=status.HTTP_400_BAD_REQUEST)
        obj, _created = Product.objects.get_or_create(name=product_name)

        # Parse the timestamp before create(): Django leaves whatever was passed on the
        # in-memory instance, so a raw ISO string survives into History.__str__ /
        # HistorySerializer and blows up there on .strftime().
        start_date = parse_datetime(data["start_date"]) if isinstance(data["start_date"], str) else data["start_date"]
        if start_date is None:
            return Response(
                {"start_date": ["Enter a valid ISO-8601 datetime."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extra_data = {
            "age_of_plants": data.get("age_of_plants"),
            "number_of_plants": data.get("number_of_plants"),
            "soil_ph": data.get("soil_ph"),
            "is_outdoor": data.get("is_outdoor"),
        }
        history = History.objects.create(
            start_date=start_date,
            parcel=parcel,
            product=obj,
            extra_data=extra_data,
            type=data.get("type"),
        )
        parcel.current_history = history
        parcel.save()
        serializer = HistorySerializer(history)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=False,
        methods=["post"],
        url_path="start-production",
        permission_classes=[IsAuthenticated, HasProductionCreationPermission],
    )
    def start_production(self, request):
        """
        Enhanced production creation endpoint with crop selection and blockchain integration.

        Returns the production immediately (<1s). Template events are created in a
        background thread — the frontend polls for progressive event loading.
        """
        import time as _time

        _t0 = _time.monotonic()
        try:
            from users.models import WorksIn

            data = request.data
            _t1 = _time.monotonic()
            logger.info("start_production TIMING: request.data parsed in %.3fs", _t1 - _t0)

            # Validate required fields
            required_fields = ["name", "parcel_id", "crop_type", "start_date"]
            for field in required_fields:
                if field not in data:
                    return Response({"error": f"Missing required field: {field}"}, status=status.HTTP_400_BAD_REQUEST)

            # `production_method` reaches the model through a raw History(...) kwarg below —
            # no serializer, no full_clean() — so Django's `choices` never ran and ANY string
            # was persisted into a choices column. The start-production form offered
            # "sustainable", which is not a model choice, so real rows carry a value that
            # get_production_method_display() can only echo back raw, and that the consumer
            # page and the certifier packet both read. Validate at the door instead.
            submitted_method = data.get("production_method")
            if submitted_method:
                valid_methods = [c[0] for c in History.PRODUCTION_METHOD_CHOICES]
                if submitted_method not in valid_methods:
                    return Response(
                        {
                            "production_method": [
                                f'"{submitted_method}" is not a valid choice. '
                                f'Valid options: {", ".join(valid_methods)}.'
                            ]
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Get parcel
            try:
                parcel = Parcel.objects.select_related("establishment__company").get(id=data["parcel_id"])
            except Parcel.DoesNotExist:
                return Response({"error": "Parcel not found"}, status=status.HTTP_404_NOT_FOUND)

            # Get company for permission and blockchain checks
            company = parcel.establishment.company
            _t2 = _time.monotonic()
            logger.info("start_production TIMING: parcel+company fetched in %.3fs (total %.3fs)", _t2 - _t1, _t2 - _t0)

            # Role-based permission check: only CA/FM can create productions
            if not request.user.is_superuser:
                if not WorksIn.objects.filter(
                    user=request.user,
                    company=company,
                    role__in=[WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER],
                ).exists():
                    raise PermissionDenied("You do not have permission to perform this action.")

            # Get crop type from database
            crop_type_id = data["crop_type"]
            try:
                from carbon.models import CropType

                crop_type = CropType.objects.get(id=crop_type_id)
            except CropType.DoesNotExist:
                return Response({"error": "Invalid crop type"}, status=status.HTTP_400_BAD_REQUEST)

            # Create or get product based on crop type
            product, created = Product.objects.get_or_create(name=crop_type.name)

            # Parse dates with timezone awareness
            start_date_str = data["start_date"].replace("Z", "+00:00")
            start_date = datetime.fromisoformat(start_date_str)
            if start_date.tzinfo is None:
                start_date = timezone.make_aware(start_date)

            expected_harvest = None
            if data.get("expected_harvest"):
                expected_harvest_str = data["expected_harvest"].replace("Z", "+00:00")
                expected_harvest = datetime.fromisoformat(expected_harvest_str)
                if expected_harvest.tzinfo is None:
                    expected_harvest = timezone.make_aware(expected_harvest)

            # Create production with enhanced data
            extra_data = {
                "crop_category": self._categorize_crop(crop_type.name),
                "estimated_yield": data.get("estimated_yield"),
                "irrigation_method": data.get("irrigation_method"),
                "created_via": "production_start_form",
                "blockchain_enabled": bool(company.blockchain_subscription_status),
            }

            # Add optional fields to extra_data.
            # `production_method` MUST be here: the start-production form submits it, and
            # HistorySerializer reads extra_data["production_method"] with a "conventional"
            # default. Omitting it meant a grower could select "Organic" on the form and
            # have it silently discarded, so every production fell back to conventional —
            # which is what surfaced on the consumer page.
            optional_fields = [
                "age_of_plants",
                "number_of_plants",
                "soil_ph",
                "is_outdoor",
                "notes",
                "production_method",
            ]
            for field in optional_fields:
                if data.get(field):
                    extra_data[field] = data[field]

            # Determine if we'll create template events in background
            template_events = data.get("template_events")
            has_templates = bool(template_events)
            _t3 = _time.monotonic()
            logger.info("start_production TIMING: pre-create done in %.3fs (total %.3fs)", _t3 - _t2, _t3 - _t0)

            # Create History + update parcel atomically, then spawn background thread
            # skip_qr=True: QR code generation + S3 upload takes ~30-40s on managed
            # infra. Defer to background thread so the response returns in <1s.
            with transaction.atomic():
                history = History(
                    name=data["name"],
                    start_date=start_date,
                    expected_harvest=expected_harvest,
                    parcel=parcel,
                    product=product,
                    production_method=data.get("production_method", "conventional"),
                    crop_type=crop_type,
                    extra_data=extra_data,
                    type=data.get("type", "OR"),
                    description=data.get("description", ""),
                    operator=request.user if request.user.is_authenticated else None,
                    events_status="pending" if has_templates else "no_events",
                )
                history.save(skip_qr=True)

                # Update parcel's current history
                parcel.current_history = history
                parcel.save(update_fields=["current_history"])

                # Spawn background thread for QR generation + template event creation
                # QR code is deferred here because it takes ~30-40s (image gen + S3 upload)
                # TODO(celery): Replace with create_template_events_task.delay(history.id, ...)
                if has_templates:
                    template_id = data.get("template_id")
                    transaction.on_commit(
                        lambda: threading.Thread(
                            target=_background_create_events,
                            args=(self, history.id, template_events, template_id),
                            daemon=True,
                        ).start()
                    )
                else:
                    # No template events, but still need QR code generated in background
                    transaction.on_commit(
                        lambda: threading.Thread(
                            target=_background_generate_qr,
                            args=(history.id,),
                            daemon=True,
                        ).start()
                    )

            _t4 = _time.monotonic()
            logger.info(
                "start_production TIMING: atomic block (create+save) in %.3fs (total %.3fs)", _t4 - _t3, _t4 - _t0
            )

            # Invalidate cache for this parcel's history list
            cache_key = f"history_list_parcel_{parcel.id}_v3"
            cache.delete(cache_key)

            # Return lightweight response immediately — the frontend navigates to
            # the parcel dashboard which fetches full data via getCurrentHistory.
            # Avoids 24+ DB queries from HistorySerializer on a fresh history.
            response_data = {
                "id": history.id,
                "name": history.name,
                "start_date": history.start_date.isoformat() if history.start_date else None,
                "finish_date": history.finish_date.isoformat() if history.finish_date else None,
                "product": product.name if product else None,
                "events_status": history.events_status,
                "crop_type": (
                    {
                        "id": crop_type.id,
                        "name": crop_type.name,
                    }
                    if crop_type
                    else None
                ),
                "crop_category": extra_data.get("crop_category"),
                "blockchain_enabled": extra_data.get("blockchain_enabled", False),
                "establishment": {
                    "id": parcel.establishment.id,
                    "name": parcel.establishment.name,
                },
                "parcel": {"id": parcel.id, "name": parcel.name},
            }

            _t5 = _time.monotonic()
            logger.info(
                "start_production TIMING: TOTAL %.3fs (data=%.3f, queries=%.3f, pre=%.3f, atomic=%.3f, response=%.3f)",
                _t5 - _t0,
                _t1 - _t0,
                _t2 - _t1,
                _t3 - _t2,
                _t4 - _t3,
                _t5 - _t4,
            )
            return Response(response_data, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response({"error": f"Invalid date format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Error creating production: %s", e)
            return Response({"error": "Failed to create production"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _categorize_crop(self, crop_name: str) -> str:
        """Helper method to categorize crops for the production start form"""
        crop_lower = crop_name.lower()

        fruit_keywords = ["orange", "apple", "grape", "lemon", "lime", "strawberry", "blueberry", "avocado"]
        vegetable_keywords = ["tomato", "lettuce", "carrot", "broccoli", "spinach", "cucumber", "pepper", "onion"]
        grain_keywords = ["corn", "wheat", "rice", "barley", "oats", "soybean"]
        herb_keywords = ["basil", "oregano", "thyme", "rosemary", "mint"]
        legume_keywords = ["bean", "chickpea", "lentil", "pea"]
        nut_keywords = ["almond", "walnut", "pecan", "hazelnut"]

        for keyword in fruit_keywords:
            if keyword in crop_lower:
                return "fruits"
        for keyword in vegetable_keywords:
            if keyword in crop_lower:
                return "vegetables"
        for keyword in grain_keywords:
            if keyword in crop_lower:
                return "grains"
        for keyword in herb_keywords:
            if keyword in crop_lower:
                return "herbs"
        for keyword in legume_keywords:
            if keyword in crop_lower:
                return "legumes"
        for keyword in nut_keywords:
            if keyword in crop_lower:
                return "nuts"

        return "other"

    def _create_template_events(self, history, template_events, template_id=None):
        """
        Helper method to create events from template data.

        IMPORTANT: Template data contains 'backend_event_fields' with all the
        actual field values that should be used for event creation.
        This method properly maps template data to event model fields.

        If backend_event_fields is not in the payload, we look it up from the
        database using template_id and event name for backwards compatibility.
        """
        from datetime import datetime

        from django.utils import timezone

        from carbon.models import EventTemplate

        # Pre-fetch all EventTemplates for this template to avoid N+1 queries
        template_events_db = {}
        if template_id:
            for et in EventTemplate.objects.filter(production_template_id=template_id):
                template_events_db[et.name.lower()] = et.backend_event_fields or {}

        # Get current event count once
        current_event_count = 0

        logger.debug("Processing %d template events", len(template_events))

        for event_data in template_events:
            event_name = event_data.get("name", "Unknown")

            if not event_data.get("enabled", True):
                logger.debug("Skipping disabled event: %s", event_name)
                continue

            logger.debug("Processing event: %s", event_name)

            try:
                # Use a savepoint so that a failure in one event doesn't
                # poison the outer @transaction.atomic block.
                with transaction.atomic():
                    self._create_single_template_event(
                        history,
                        event_data,
                        current_event_count,
                    )

            except Exception as e:
                logger.exception("Error creating template event %s", event_data.get("name", "Unknown"))
                # Continue with other events even if one fails
                continue

    # Map backend_event_type integers to category strings for fallback routing
    _BACKEND_TYPE_TO_CATEGORY = {
        0: "weather",
        1: "production",
        2: "chemical",
        3: "general",
        4: "equipment",
        5: "soil",
        6: "pest",
        7: "business",
    }

    #: Never accepted from a template payload, whatever the model says. Identity, ownership
    #: and audit columns are decided by the server, not by template data.
    _TEMPLATE_FIELD_DENYLIST = frozenset(
        {
            "id",
            "history",
            "created_by",
            "index",
            "date",
            "name",
            "description",
            "performed_by",
            "image",
            "album",
            "created_at",
            "updated_at",
            "commonevent_ptr",
        }
    )

    @staticmethod
    def _drop_nulls_over_model_defaults(model, kwargs):
        """Remove None values aimed at NOT NULL columns so the model's own default applies.

        WHY (2026-08-12): the branches below pass `backend_fields.get("x")` for every column
        they name. When a template does not carry "x" that evaluates to None, and an explicit
        None OVERRIDES a model default — so `transportation_unit` (null=False, default="miles")
        went in as NULL and the insert died on the constraint.

        `_create_template_events` catches per-event exceptions and continues, so the failure
        was INVISIBLE: the grower ticked the event, got no error, and the event simply was not
        there. Measured on the seeded catalogue: **139 of 190 production-category templates
        omit `transportation_unit`**, including "Season Irrigation Program", "Annual Structural
        Pruning" and "Planting / Replanting" — verified failing end to end before this fix.

        Mutates and returns ``kwargs``.
        """
        from django.core.exceptions import FieldDoesNotExist

        for name, value in list(kwargs.items()):
            if value is not None:
                continue
            try:
                field = model._meta.get_field(name)
            except FieldDoesNotExist:
                continue
            # Dropping the key hands the column to Django's own default (an explicit default,
            # or "" for a blank-able string). Nullable columns keep the explicit None, which
            # is a real value there.
            if not field.null:
                del kwargs[name]
        return kwargs

    @classmethod
    def _template_extra_fields(cls, model, backend_fields, already_set):
        """Template fields that map to real model columns but have no explicit kwarg above.

        WHY (2026-08-12): every branch below is a hand-maintained kwarg list, so a field added
        through the 7-step standard in `src/config/events/ADDING_FIELDS.md` reaches the model,
        both serializers, the registry, the form and the packet — and is then silently dropped
        by the template flow, which is the path most growers actually use. Measured at the time
        of writing: **167 concrete fields across production / soil / chemical / pest existed on
        the models and could not be set from a template.** The standard does not mention this
        file, which is why nobody noticed.

        Deliberately conservative rather than a blanket `**backend_fields`:

          * only CONCRETE, EDITABLE fields of that exact model — an unknown key is ignored,
            not passed to `create()` where it would raise
          * never a RELATION, so a template cannot repoint `history` or `created_by`
          * never a name already set explicitly above, so existing defaults keep winning
          * never anything in the denylist, so identity and audit columns stay server-owned

        The result is additive: every call site behaves exactly as before for the fields it
        already named, and stops losing the ones it did not.
        """
        if not isinstance(backend_fields, dict):
            return {}
        concrete = {
            f.name: f
            for f in model._meta.get_fields()
            if getattr(f, "concrete", False) and not f.auto_created and getattr(f, "editable", False)
        }
        extras = {}
        for key, value in backend_fields.items():
            if key in already_set or key in cls._TEMPLATE_FIELD_DENYLIST:
                continue
            field = concrete.get(key)
            if field is None or field.is_relation:
                continue
            extras[key] = value
        return extras

    def _create_single_template_event(self, history, event_data, index):
        """Create a single event from template data. Called inside a savepoint."""
        from datetime import datetime

        from django.utils import timezone

        # Parse the scheduled date
        scheduled_date_str = event_data.get("scheduled_date")
        if scheduled_date_str:
            scheduled_date = datetime.fromisoformat(scheduled_date_str.replace("Z", "+00:00"))
            if scheduled_date.tzinfo is None:
                scheduled_date = timezone.make_aware(scheduled_date)
        else:
            scheduled_date = timezone.now()

        # Extract backend_event_fields
        backend_fields = event_data.get("backend_event_fields", {})

        # Determine event type: prefer explicit backend_event_type over name-parsing
        backend_event_type = event_data.get("backend_event_type")
        if backend_event_type is not None:
            category = self._BACKEND_TYPE_TO_CATEGORY.get(backend_event_type)
            if category is None:
                logger.warning(
                    "Unknown backend_event_type=%s for '%s', falling back to name detection",
                    backend_event_type,
                    event_data.get("name"),
                )
                event_type_info = self._determine_template_event_type(event_data.get("name", "").lower())
                category = event_type_info["category"]
        else:
            # Fallback for legacy templates without backend_event_type
            event_type_info = self._determine_template_event_type(event_data.get("name", "").lower())
            category = event_type_info["category"]
            logger.debug(
                "No backend_event_type for '%s', name-detected category='%s'",
                event_data.get("name"),
                category,
            )

        # Route deprecated Equipment (type 4) to ProductionEvent EM
        if backend_event_type == 4 or category == "equipment":
            logger.info(
                "Routing equipment event '%s' to ProductionEvent EM",
                event_data.get("name"),
            )
            category = "production"
            backend_fields.setdefault("type", "EM")

        logger.debug(
            "Event '%s' → category='%s', backend_event_type=%s",
            event_data.get("name"),
            category,
            backend_event_type,
        )

        # Use template description field; fall back to name if empty
        description = event_data.get("description", "") or event_data.get("name", "Event")

        # Get operator name for performed_by
        operator_name = ""
        if history.operator:
            operator_name = history.operator.get_full_name() or ""

        event_name = event_data.get("name", "")

        # Create appropriate event based on category
        if category == "chemical":
            # Build extra_data: start with template extra_data, add volume/area units
            extra_data = backend_fields.get("extra_data") or {}
            extra_data.setdefault("volume_unit", backend_fields.get("volume_unit", "L"))
            extra_data.setdefault("area_unit", backend_fields.get("area_unit", "ha"))
            _kwargs = dict(
                history=history,
                name=event_name,
                description=description,
                performed_by=operator_name,
                date=scheduled_date,
                type=backend_fields.get("type", "FE"),
                commercial_name=backend_fields.get("commercial_name", ""),
                volume=str(backend_fields.get("volume", "")) if backend_fields.get("volume") else "",
                concentration=backend_fields.get("concentration"),
                area=str(backend_fields.get("area", "")) if backend_fields.get("area") else "",
                way_of_application=backend_fields.get("way_of_application"),
                time_period=backend_fields.get("time_period"),
                observation=backend_fields.get("observation"),
                extra_data=extra_data,
                chemical_subtype=backend_fields.get("chemical_subtype"),
                nitrogen_percentage=backend_fields.get("nitrogen_percentage"),
                phosphorus_percentage=backend_fields.get("phosphorus_percentage"),
                potassium_percentage=backend_fields.get("potassium_percentage"),
                application_method_structured=backend_fields.get("application_method_structured"),
                application_fuel_type=backend_fields.get("application_fuel_type", ""),
                application_fuel_consumed=backend_fields.get("application_fuel_consumed"),
                application_fuel_unit=backend_fields.get("application_fuel_unit", "L"),
                weather_conditions=backend_fields.get("weather_conditions"),
                application_timing=backend_fields.get("application_timing"),
                target_pest_disease=backend_fields.get("target_pest_disease"),
                organic_approved=backend_fields.get("organic_approved"),
                buffer_zone_meters=backend_fields.get("buffer_zone"),
                applicator_name=backend_fields.get("applicator_name"),
                restricted_use_pesticide=backend_fields.get("restricted_use_pesticide"),
                rei_hours=backend_fields.get("rei_hours"),
                phi_days=backend_fields.get("phi_days"),
                index=index,
                created_by=history.operator,
            )
            _kwargs.update(self._template_extra_fields(ChemicalEvent, backend_fields, _kwargs))
            self._drop_nulls_over_model_defaults(ChemicalEvent, _kwargs)
            ChemicalEvent.objects.create(**_kwargs)
        elif category == "weather":
            _kwargs = dict(
                history=history,
                description=description,
                performed_by=operator_name,
                date=scheduled_date,
                type=backend_fields.get("type", "HT"),
                observation=backend_fields.get("observation", ""),
                extra_data=backend_fields.get("extra_data"),
                index=index,
                created_by=history.operator,
            )
            _kwargs.update(self._template_extra_fields(WeatherEvent, backend_fields, _kwargs))
            self._drop_nulls_over_model_defaults(WeatherEvent, _kwargs)
            WeatherEvent.objects.create(**_kwargs)
        elif category == "soil":
            _kwargs = dict(
                history=history,
                name=event_name,
                description=description,
                performed_by=operator_name,
                date=scheduled_date,
                type=backend_fields.get("type", "ST"),
                area_covered=backend_fields.get("area_covered"),
                area_unit=backend_fields.get("area_unit", "ha"),
                working_depth=backend_fields.get("working_depth"),
                depth_unit=backend_fields.get("depth_unit", "cm"),
                soil_texture=backend_fields.get("soil_texture"),
                soil_moisture=backend_fields.get("soil_moisture"),
                soil_ph=backend_fields.get("soil_ph", 7.0),
                organic_matter_percentage=backend_fields.get("organic_matter_percentage")
                or backend_fields.get("organic_matter", 3.5),
                fuel_consumed=backend_fields.get("fuel_consumed"),
                fuel_unit=backend_fields.get("fuel_unit", "L"),
                fuel_type=backend_fields.get("fuel_type", "diesel"),
                amendment_type=backend_fields.get("amendment_type", "organic_mulch"),
                amendment_amount=backend_fields.get("amendment_amount", ""),
                equipment_hours=backend_fields.get("equipment_hours"),
                production_efficiency=backend_fields.get("production_efficiency", "normal"),
                equipment_used=backend_fields.get("equipment_used"),
                test_results=backend_fields.get("test_results"),
                extra_data=backend_fields.get("extra_data"),
                index=index,
                created_by=history.operator,
            )
            _kwargs.update(self._template_extra_fields(SoilManagementEvent, backend_fields, _kwargs))
            self._drop_nulls_over_model_defaults(SoilManagementEvent, _kwargs)
            SoilManagementEvent.objects.create(**_kwargs)
        elif category == "pest":
            _kwargs = dict(
                history=history,
                description=description,
                performed_by=operator_name,
                date=scheduled_date,
                type=backend_fields.get("type", "SC"),
                pest_species=backend_fields.get("pest_species") or backend_fields.get("pest_type", "general pest"),
                pest_pressure_level=backend_fields.get("pest_pressure_level")
                or backend_fields.get("severity_level", "low"),
                beneficial_species=backend_fields.get("beneficial_species") or "",
                release_quantity=backend_fields.get("release_quantity") or "",
                ipm_strategy=backend_fields.get("ipm_strategy", "monitoring"),
                beneficial_insects_used=backend_fields.get("beneficial_insects_used"),
                chemical_free_period_days=backend_fields.get("chemical_free_period_days"),
                trap_count=backend_fields.get("trap_count"),
                damage_percentage=backend_fields.get("damage_percentage"),
                action_threshold_met=backend_fields.get("action_threshold_met", False),
                area_covered=backend_fields.get("area_covered"),
                area_unit=backend_fields.get("area_unit", "ha"),
                fuel_consumed=backend_fields.get("fuel_consumed"),
                fuel_unit=backend_fields.get("fuel_unit"),
                fuel_type=backend_fields.get("fuel_type"),
                equipment_hours=backend_fields.get("equipment_hours"),
                production_efficiency=backend_fields.get("production_efficiency"),
                extra_data=backend_fields.get("extra_data"),
                index=index,
                created_by=history.operator,
            )
            _kwargs.update(self._template_extra_fields(PestManagementEvent, backend_fields, _kwargs))
            self._drop_nulls_over_model_defaults(PestManagementEvent, _kwargs)
            PestManagementEvent.objects.create(**_kwargs)
        elif category == "business":
            _kwargs = dict(
                history=history,
                name=event_name,
                description=description,
                performed_by=operator_name,
                date=scheduled_date,
                type=backend_fields.get("type", "CE"),
                business_type=backend_fields.get("business_type"),
                certification_type=backend_fields.get("certification_type", "organic"),
                verification_status=backend_fields.get("verification_status"),
                verified_certifier_name=backend_fields.get("verified_certifier_name"),
                certificate_number=backend_fields.get("certificate_number"),
                sustainability_practice=backend_fields.get("sustainability_practice"),
                carbon_credits_earned=backend_fields.get("carbon_credits_earned"),
                carbon_credits_unit=backend_fields.get("carbon_credits_unit"),
                observation=backend_fields.get("observation"),
                extra_data=backend_fields.get("extra_data"),
                index=index,
                created_by=history.operator,
            )
            _kwargs.update(self._template_extra_fields(BusinessEvent, backend_fields, _kwargs))
            self._drop_nulls_over_model_defaults(BusinessEvent, _kwargs)
            BusinessEvent.objects.create(**_kwargs)
        elif category == "production":
            _kwargs = dict(
                history=history,
                name=event_name,
                description=description,
                performed_by=operator_name,
                date=scheduled_date,
                type=backend_fields.get("type", "IR"),
                observation=backend_fields.get("observation"),
                area_covered=backend_fields.get("area_covered"),
                area_unit=backend_fields.get("area_unit", "ha"),
                seeds_source=backend_fields.get("seeds_source"),
                yield_quantity=backend_fields.get("yield_quantity"),
                yield_unit=backend_fields.get("yield_unit", "kg"),
                fuel_consumed=backend_fields.get("fuel_consumed"),
                fuel_unit=backend_fields.get("fuel_unit", "L"),
                fuel_type=backend_fields.get("fuel_type", "diesel"),
                equipment_hours=backend_fields.get("equipment_hours"),
                production_efficiency=backend_fields.get("production_efficiency", "normal"),
                water_source=backend_fields.get("water_source"),
                irrigation_method=backend_fields.get("irrigation_method"),
                irrigation_depth=backend_fields.get("irrigation_depth"),
                transportation_distance=backend_fields.get("transportation_distance"),
                transportation_unit=backend_fields.get("transportation_unit"),
                harvest_quality_grade=backend_fields.get("harvest_quality_grade"),
                equipment_type=backend_fields.get("equipment_type"),
                equipment_operation_type=backend_fields.get("equipment_operation_type"),
                extra_data=backend_fields.get("extra_data"),
                index=index,
                created_by=history.operator,
            )
            _kwargs.update(self._template_extra_fields(ProductionEvent, backend_fields, _kwargs))
            self._drop_nulls_over_model_defaults(ProductionEvent, _kwargs)
            ProductionEvent.objects.create(**_kwargs)
        elif category == "general":
            _kwargs = dict(
                history=history,
                name=event_name or "General Event",
                description=description,
                performed_by=operator_name,
                date=scheduled_date,
                observation=backend_fields.get("observation"),
                activity_type=backend_fields.get("activity_type"),
                activity_name=backend_fields.get("activity_name"),
                duration=backend_fields.get("duration"),
                people_involved=backend_fields.get("people_involved"),
                extra_data=backend_fields.get("extra_data"),
                index=index,
                created_by=history.operator,
            )
            _kwargs.update(self._template_extra_fields(GeneralEvent, backend_fields, _kwargs))
            self._drop_nulls_over_model_defaults(GeneralEvent, _kwargs)
            GeneralEvent.objects.create(**_kwargs)
        else:
            # Final fallback — should not normally be reached
            logger.warning(
                "Unrecognized category '%s' for event '%s', creating GeneralEvent",
                category,
                event_name,
            )
            _kwargs = dict(
                history=history,
                name=event_name or "General Event",
                description=description,
                performed_by=operator_name,
                date=scheduled_date,
                index=index,
                created_by=history.operator,
            )
            _kwargs.update(self._template_extra_fields(GeneralEvent, backend_fields, _kwargs))
            self._drop_nulls_over_model_defaults(GeneralEvent, _kwargs)
            GeneralEvent.objects.create(**_kwargs)

    def _determine_template_event_type(self, event_name):
        """
        Legacy name-based event type detection. Only used as fallback when
        backend_event_type is not set on the template data.
        Returns: {"category": str, "sub_type": str}
        """
        name = event_name.lower() if event_name else ""

        # Chemical events (fertilizers, pesticides, herbicides, fungicides)
        if any(term in name for term in ["fertiliz", "nutrient", "nitrogen", "phosphor", "potassium"]):
            return {"category": "chemical", "sub_type": ChemicalEvent.FERTILIZER}
        if any(term in name for term in ["spray", "pesticide", "insecticide", "pest control"]):
            return {"category": "chemical", "sub_type": ChemicalEvent.PESTICIDE}
        if any(term in name for term in ["herbicide", "weed", "glyphosate"]):
            return {"category": "chemical", "sub_type": ChemicalEvent.HERBICIDE}
        if any(term in name for term in ["fungicide", "fungus", "disease control"]):
            return {"category": "chemical", "sub_type": ChemicalEvent.FUNGICIDE}

        # Equipment-like events → route to production EM (Equipment type 4 is deprecated)
        if any(term in name for term in ["maintenance", "repair", "service", "calibration"]):
            return {"category": "production", "sub_type": "EM"}
        if any(term in name for term in ["equipment", "machinery", "tractor", "harvester"]):
            return {"category": "production", "sub_type": "EM"}
        if any(term in name for term in ["fuel", "diesel", "gasoline"]):
            return {"category": "production", "sub_type": "EM"}
        if "field preparation" in name or "planting/seeding" in name:
            return {"category": "production", "sub_type": ProductionEvent.PLANTING}
        if any(term in name for term in ["preparation", "tillage", "cultivation", "plowing"]) and "soil" not in name:
            return {"category": "production", "sub_type": ProductionEvent.CULTIVATION}

        # Pruning and harvest → production events
        if any(term in name for term in ["pruning", "prune", "trimming", "cutting back"]):
            return {"category": "production", "sub_type": ProductionEvent.PRUNING}
        if any(term in name for term in ["harvest", "picking", "collection"]):
            return {"category": "production", "sub_type": ProductionEvent.HARVESTING}

        # Weather events (frost, drought, storms, temperature monitoring)
        if any(term in name for term in ["weather", "climate", "temperature", "monitoring weather"]):
            return {"category": "weather", "sub_type": WeatherEvent.HIGH_TEMPERATURE}
        if any(term in name for term in ["frost", "freeze", "cold protection"]):
            return {"category": "weather", "sub_type": WeatherEvent.FROST}
        if any(term in name for term in ["drought", "water stress", "irrigation need"]):
            return {"category": "weather", "sub_type": WeatherEvent.DROUGHT}
        if any(term in name for term in ["storm", "wind", "hail", "rain"]):
            return {"category": "weather", "sub_type": WeatherEvent.TROPICAL_STORM}

        # Soil events (testing, amendments, management, mulching)
        if "soil" in name and any(term in name for term in ["test", "analysis", "ph"]):
            return {"category": "soil", "sub_type": SoilManagementEvent.SOIL_TEST}
        if any(term in name for term in ["soil amendment", "lime", "compost", "organic matter"]):
            return {"category": "soil", "sub_type": SoilManagementEvent.ORGANIC_MATTER}
        if any(term in name for term in ["soil preparation", "soil management"]):
            return {"category": "soil", "sub_type": SoilManagementEvent.TILLAGE}
        if "soil" in name and "tillage" in name:
            return {"category": "soil", "sub_type": SoilManagementEvent.TILLAGE}
        if any(term in name for term in ["ph management", "ph adjustment", "ph control"]):
            return {"category": "soil", "sub_type": SoilManagementEvent.PH_ADJUSTMENT}
        if any(term in name for term in ["mulch", "mulching", "cover crop"]):
            return {"category": "soil", "sub_type": SoilManagementEvent.ORGANIC_MATTER}

        # Pest management events (scouting, monitoring, biological control)
        if any(term in name for term in ["scout", "monitoring", "inspection", "pest monitoring"]):
            return {"category": "pest", "sub_type": PestManagementEvent.SCOUTING}
        if any(term in name for term in ["biological control", "beneficial", "predator"]):
            return {"category": "pest", "sub_type": PestManagementEvent.BENEFICIAL_RELEASE}
        if any(term in name for term in ["trap", "pheromone", "ipm"]):
            return {"category": "pest", "sub_type": PestManagementEvent.TRAP_MONITORING}

        # Business events (certification, audit, training)
        if any(term in name for term in ["certif", "organic", "audit", "compliance"]):
            return {"category": "business", "sub_type": BusinessEvent.CERTIFICATION}
        if any(term in name for term in ["training", "education", "workshop"]):
            return {"category": "business", "sub_type": BusinessEvent.CERTIFICATION}
        if any(term in name for term in ["record", "documentation", "reporting"]):
            return {"category": "business", "sub_type": BusinessEvent.COMPLIANCE}

        # Production events (biological/manual operations)
        if any(term in name for term in ["irrigation", "watering", "water application"]):
            return {"category": "production", "sub_type": ProductionEvent.IRRIGATION}
        if "planting" in name and not any(term in name for term in ["equipment", "seeding"]):
            return {"category": "production", "sub_type": ProductionEvent.PLANTING}
        if any(term in name for term in ["bloom", "flower", "pollination"]):
            return {"category": "production", "sub_type": ProductionEvent.PLANTING}
        if any(term in name for term in ["thinning", "selective removal", "crop management"]):
            return {"category": "production", "sub_type": ProductionEvent.THINNING}

        # Default fallback to production
        return {"category": "production", "sub_type": ProductionEvent.IRRIGATION}

    # gzip: the QR page is the most mobile-critical surface in the product (<500 ms budget,
    # opened on a phone in a shop or a field on cell data) and this payload grows with the
    # season. Measured on a realistic 258-event CA walnut year: 179.7 KB -> 6.1 KB (97%).
    #
    # Scoped deliberately to the ANONYMOUS consumer endpoints rather than enabling
    # GZipMiddleware globally. Django's docs warn that compressing responses can expose
    # BREACH; that attack needs a secret in the response body alongside attacker-controlled
    # reflected input. This endpoint is unauthenticated, carries no secret, and its only
    # input is a UUID lookup — so it is provably outside that surface. Turning gzip on for
    # authenticated endpoints is a larger decision that deserves its own BREACH review, not
    # a side effect of a performance fix.
    #
    # Belt-and-braces at the edge is fine but not relied on: prod sits behind Cloudflare,
    # which compressed some responses and not others when checked, and dev/staging have no
    # edge compression at all.
    @method_decorator(gzip_page)
    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def public_history(self, request, pk=None):
        import uuid as uuid_module

        queryset = self.get_queryset()
        # UUID-only lookup for anonymous traffic (prevents integer enumeration).
        # The producer app's own routes carry the INTERNAL integer id, so an
        # authenticated user may use it — but only for productions their
        # company owns (the farmer previewing their own page).
        try:
            public_uuid = uuid_module.UUID(str(pk))
            history = get_object_or_404(queryset, public_id=public_uuid)
        except (ValueError, AttributeError):
            if not (request.user.is_authenticated and str(pk).isdigit()):
                return Response(
                    {"error": "Invalid production identifier. UUID required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            history = get_object_or_404(queryset, pk=pk)
            owns_it = (
                history.parcel
                and history.parcel.establishment
                and request.user.companies.filter(id=history.parcel.establishment.company_id).exists()
            )
            if not owns_it:
                return Response(
                    {"error": "Invalid production identifier. UUID required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        # Skip scan tracking for authenticated producers viewing their own production
        is_owner = False
        if request.user.is_authenticated and history.parcel and history.parcel.establishment:
            is_owner = request.user.companies.filter(id=history.parcel.establishment.company_id).exists()

        history_scan = None
        if not is_owner:
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(",")[0]
            else:
                ip_address = request.META.get("REMOTE_ADDR")

            city = None
            country = None

            # Get city and country from IP using free API (no GDAL required)
            if ip_address:
                try:
                    import requests

                    response = requests.get(f"https://ipapi.co/{ip_address}/json/", timeout=2)
                    if response.status_code == 200:
                        data = response.json()
                        if not data.get("reserved"):
                            city = data.get("city")
                            country = data.get("country_name")
                except Exception as e:
                    logger.debug("IP geolocation failed: %s", e)

            history_scan = HistoryScan.objects.create(
                history=history,
                user=request.user if request.user.is_authenticated else None,
                ip_address=ip_address,
                city=city,
                country=country,
            )

            # Send notification to product owner about the scan
            try:
                company = history.parcel.establishment.company
                scanner = request.user if request.user.is_authenticated else None

                from users.models import WorksIn

                company_admins = WorksIn.objects.filter(company=company, role="CA").select_related("user")

                for admin_relation in company_admins:
                    product_owner = admin_relation.user

                    if scanner != product_owner:
                        product_name = history.product.name if history.product else f"Production {history.id}"
                        scan_location = history_scan.get_location_display()

                        notification_service.create_product_scan_notification(
                            product_owner=product_owner,
                            scanner=scanner,
                            product_name=product_name,
                            scan_location=scan_location,
                            production_id=history.id,
                            establishment_id=(
                                history.parcel.establishment.id
                                if history.parcel and history.parcel.establishment
                                else None
                            ),
                            product_id=history.product.id if history.product else None,
                            parcel_id=history.parcel.id if history.parcel else None,
                        )
            except Exception as e:
                logger.error("Error creating scan notification: %s", e)
        serializer = PublicHistorySerializer(
            history,
            context={"history_scan": history_scan.id if history_scan else None, "request": request},
        )
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def my_scans(self, request):
        queryset = self.get_queryset()
        scans_data = []
        for history in queryset:
            latest_scan = history.history_scans.filter(user=request.user).order_by("-date").first()
            if latest_scan:
                data = PublicHistorySerializer(history, context={"history_scan": latest_scan.id}).data
                data["scanned_at"] = latest_scan.date.isoformat() if latest_scan.date else None
                scans_data.append(data)
        return Response(scans_data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def establishment_scans_paginated(self, request):
        """
        Paginated endpoint for establishment scans with filtering.
        Used by the commercial dashboard's "view all scans" functionality.
        """
        establishment_id = request.query_params.get("establishment_id")
        company_id = request.query_params.get("company_id")

        if not establishment_id or not company_id:
            return Response(
                {"error": "establishment_id and company_id are required"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Get scans for the establishment.
        #
        # `.counted()` — the same definition the stat card, the dashboard charts and the billing
        # quota use. This list previously showed every raw row, so a farmer reading "18 scans"
        # under the table and a different total on the metrics screen was seeing two honest
        # answers to two different questions, with nothing on screen saying so.
        #
        # The repeats are not thrown away: each surviving row carries `repeat_count`, the number
        # of scans that were folded into it, so the information is attached to the visit it
        # belongs to instead of inflating the list.
        scans_queryset = (
            HistoryScan.objects.counted()
            .filter(
                history__parcel__establishment_id=establishment_id,
                history__parcel__establishment__company_id=company_id,
            )
            .select_related("history", "history__product", "history__parcel", "history__parcel__establishment", "user")
            .annotate(repeat_count=Count("historyscan", filter=Q(historyscan__is_duplicate=True), distinct=True))
            .order_by("-date")
        )

        # Apply date filtering if provided
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        if date_from:
            try:
                date_from_parsed = date_parser.parse(date_from)
                scans_queryset = scans_queryset.filter(date__gte=date_from_parsed)
            except ValueError:
                pass

        if date_to:
            try:
                date_to_parsed = date_parser.parse(date_to)
                scans_queryset = scans_queryset.filter(date__lte=date_to_parsed)
            except ValueError:
                pass

        # Apply product filtering if provided
        product_id = request.query_params.get("product_id")
        if product_id:
            scans_queryset = scans_queryset.filter(history__product_id=product_id)

        # Apply parcel filtering if provided
        parcel_id = request.query_params.get("parcel_id")
        if parcel_id:
            scans_queryset = scans_queryset.filter(history__parcel_id=parcel_id)

        # Apply production (season) filtering if provided. `production_id` is the internal
        # History pk — the same value this endpoint already emits as `production_id` on each
        # row, so the client filters with a key it was handed rather than one it guessed.
        production_id = request.query_params.get("production_id")
        if production_id:
            scans_queryset = scans_queryset.filter(history_id=production_id)

        # Apply search filtering if provided
        search = request.query_params.get("search")
        if search:
            # `Q` comes from the module-level import. It used to be re-imported HERE, which made
            # `Q` a function-local name for the WHOLE function — so the annotation above, which
            # runs first, raised UnboundLocalError and the endpoint 500'd.
            scans_queryset = scans_queryset.filter(
                Q(history__product__name__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__email__icontains=search)
                | Q(comment__icontains=search)
                | Q(city__icontains=search)
                | Q(country__icontains=search)
                | Q(history__parcel__name__icontains=search)
            )

        # Filter OPTIONS, derived from the scans that exist rather than from the farm's full
        # inventory. A 25-parcel farm with scans on two blocks gets two parcel options, not 25 —
        # a dropdown whose every entry returns rows. Computed from `facet_base` (establishment
        # scope only, before any user filter), so choosing a crop does not erase the parcel
        # options; otherwise each selection would strip the list that produced it.
        # `.counted()` here too, or a production whose only scans were duplicates would offer an
        # option that returns an empty table.
        facet_base = HistoryScan.objects.counted().filter(
            history__parcel__establishment_id=establishment_id,
            history__parcel__establishment__company_id=company_id,
        )
        filter_options = {
            "productions": [
                {"id": row["history_id"], "name": row["history__name"]}
                for row in facet_base.exclude(history__isnull=True)
                .values("history_id", "history__name")
                .distinct()
                .order_by("history__name")
            ],
            "products": [
                {"id": row["history__product_id"], "name": row["history__product__name"]}
                for row in facet_base.exclude(history__product__isnull=True)
                .values("history__product_id", "history__product__name")
                .distinct()
                .order_by("history__product__name")
            ],
            "parcels": [
                {"id": row["history__parcel_id"], "name": row["history__parcel__name"]}
                for row in facet_base.exclude(history__parcel__isnull=True)
                .values("history__parcel_id", "history__parcel__name")
                .distinct()
                .order_by("history__parcel__name")
            ],
        }

        # Paginate results
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(scans_queryset, request)

        if page is not None:
            # Transform to the expected format
            scans_data = []
            for scan in page:
                scan_data = {
                    "id": scan.id,
                    "date": scan.date.strftime("%Y-%m-%d %H:%M:%S") if scan.date else None,
                    "product": scan.history.product.name if scan.history.product else None,
                    "product_id": scan.history.product.id if scan.history.product else None,
                    "location": scan.get_location_display() or "-",
                    "parcel": scan.history.parcel.name if scan.history.parcel else None,
                    "parcel_id": scan.history.parcel.id if scan.history.parcel else None,
                    # The SEASON the scan belongs to. The payload carried product and parcel but
                    # never the production, so a grower reading "Walnuts · North Orchard" twice
                    # could not tell whether both scans were of the same season's page.
                    "production": scan.history.name,
                    "production_id": scan.history.id,
                    "comment": getattr(scan, "comment", ""),
                    "user": scan.user.get_full_name() if scan.user else "Anonymous",
                    "scan_type": scan.scan_type,
                    # How many scans were folded INTO this one by deduplication. Replaces the old
                    # `is_duplicate` flag, which is now always False here because the queryset is
                    # `.counted()` — a duplicate row can no longer reach this serializer, so the
                    # flag could only ever have said "no".
                    "repeat_count": getattr(scan, "repeat_count", 0),
                    "ip_address": scan.ip_address,
                    "qr_code": scan.history.qr_code.url if scan.history.qr_code else None,
                    "carbon_score": getattr(scan.history, "carbon_score", 0),
                    "production_period": scan.history.period if hasattr(scan.history, "period") else None,
                }
                scans_data.append(scan_data)

            response = paginator.get_paginated_response(scans_data)
            response.data["filter_options"] = filter_options
            return response

        return Response({"count": 0, "next": None, "previous": None, "results": [], "filter_options": filter_options})

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def my_reviews(self, request):
        queryset = self.get_queryset()
        reviews_data = []
        for review in queryset:
            reviews_data.append(
                {
                    "id": review.id,
                    "headline": review.headline,
                    "written_review": review.written_review,
                    "date": review.date,
                    "rating": review.rating,
                    "history": HistorySerializer(review.production).data,
                }
            )
        return Response(reviews_data)

    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
    def validate_qr(self, request):
        """
        Validate QR code and return production information if valid.
        Accepts QR code data, URL, or production ID.
        """
        qr_data = request.data.get("qr_data", "").strip()

        if not qr_data:
            return Response({"error": "QR code data is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Try to extract production ID from different formats
            production_id = None

            # Case 1: Direct production ID (numeric)
            if qr_data.isdigit():
                production_id = int(qr_data)

            # Case 2: URL containing production ID
            elif qr_data.startswith(("http://", "https://")):
                from urllib.parse import urlparse

                parsed_url = urlparse(qr_data)
                path_parts = parsed_url.path.strip("/").split("/")

                # Look for /production/{id} pattern
                if "production" in path_parts:
                    prod_index = path_parts.index("production")
                    if prod_index + 1 < len(path_parts):
                        potential_id = path_parts[prod_index + 1]
                        if potential_id.isdigit():
                            production_id = int(potential_id)

            # Case 3: Try to parse as production ID directly
            else:
                try:
                    production_id = int(qr_data)
                except ValueError:
                    # Last attempt: check if it contains digits
                    import re

                    numbers = re.findall(r"\d+", qr_data)
                    if numbers:
                        production_id = int(numbers[0])

            if production_id is None:
                return Response(
                    {"error": "Invalid QR code format. Unable to extract production ID."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Look up the production
            try:
                history = History.objects.select_related("product", "parcel__establishment__company").get(
                    id=production_id, published=True
                )
            except History.DoesNotExist:
                return Response({"error": "Production not found or not published"}, status=status.HTTP_404_NOT_FOUND)

            # Return validation success with basic production info
            return Response(
                {
                    "valid": True,
                    "production_id": history.id,
                    "production_name": history.name,
                    "product_name": history.product.name if history.product else None,
                    "establishment_name": history.parcel.establishment.name if history.parcel else None,
                    "company_name": (
                        history.parcel.establishment.company.name
                        if history.parcel and history.parcel.establishment
                        else None
                    ),
                    "qr_code_url": history.qr_code.url if history.qr_code else None,
                    "redirect_url": f"/scan/production/{history.id}",
                }
            )

        except Exception as e:
            return Response(
                {"error": f"Error validating QR code: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def download_qr_code(self, request, pk=None):
        """
        Generate download URL for QR code.
        Supports both local file storage (dev) and S3 (production).
        Supports both numeric ID and UUID (public_id) lookup.
        """
        import uuid as uuid_module

        from django.conf import settings

        try:
            # Support UUID lookup (frontend uses public_id/UUID)
            try:
                public_uuid = uuid_module.UUID(str(pk))
                history = get_object_or_404(History, public_id=public_uuid)
            except (ValueError, AttributeError):
                history = self.get_object()

            if not history.qr_code or not history.qr_code.name:
                return Response(
                    {"error": "QR code not found for this production"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            filename = f"{history.name.replace(' ', '_')}_QR.png"

            # Check if using S3 storage (production) or local storage (dev)
            if getattr(settings, "AWS_STORAGE_BUCKET_NAME", None):
                from common.aws_utils import SecureAWSClient

                s3_client = SecureAWSClient.get_s3_client()
                download_url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                        "Key": history.qr_code.name,
                    },
                    ExpiresIn=3600,
                )
            else:
                # Local storage: build absolute URI from the file URL
                download_url = request.build_absolute_uri(history.qr_code.url)

            return Response(
                {
                    "download_url": download_url,
                    "filename": filename,
                    "expires_in": 3600,
                    "expires_at": (timezone.now() + timedelta(seconds=3600)).isoformat(),
                    "production_name": history.name,
                    "message": "Download URL generated successfully",
                }
            )

        except Exception as e:
            return Response(
                {"error": f"Error generating download URL: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"], url_path="lot-tag", permission_classes=[IsAuthenticated])
    def lot_tag(self, request, pk=None):
        """
        Printable container/case lot tags (SOE § 205.307 — nonretail containers
        must carry lot-traceable identification). Letter page, 8 identical tags
        (2×4 grid): farm, crop, LOT ID, harvest date, QR to the consumer page,
        and an organic line ONLY when the lot-eligibility resolver passes —
        the same gate the consumer page uses.
        """
        import uuid as uuid_module
        from io import BytesIO

        from django.http import HttpResponse

        from users.models import WorksIn

        try:
            public_uuid = uuid_module.UUID(str(pk))
            history = get_object_or_404(
                History.objects.select_related("product", "parcel__establishment__company"),
                public_id=public_uuid,
            )
        except (ValueError, AttributeError):
            history = self.get_object()

        establishment = history.parcel.establishment if history.parcel else None
        if not (
            establishment
            and WorksIn.objects.filter(user=request.user, company=establishment.company, role__in=["CA", "FM"]).exists()
        ):
            return Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)

        # § 205.307 container-labelling decision. Both halves of the rule live in the claim
        # authority now — (a)(2) lot linkage and (a)(1) organic identification — so this view
        # asks rather than decides, the same way every other public surface does.
        #
        # Previously this printed `LOT —` whenever lot_id was null (63% of published
        # productions, measured 2026-08-10) and silently dropped the organic line on any gate
        # failure. Both produce a non-compliant physical label; neither was visible to the
        # grower, who is the only person able to fix it.
        from .services.claim_authority import may_label_container

        label_decision = may_label_container(history)
        if not label_decision.may_print:
            return Response(
                {"error": label_decision.blocker, "code": "lot_id_required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        organic_line = label_decision.organic_line or None

        from django.conf import settings

        import qrcode
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas as rl_canvas

        consumer_url = f"{settings.BASE_CONSUMER_URL}production/{history.public_id}"
        qr_img = qrcode.make(consumer_url, box_size=6, border=2)
        qr_buf = BytesIO()
        qr_img.save(qr_buf, format="PNG")
        qr_buf.seek(0)
        qr_reader = ImageReader(qr_buf)

        buf = BytesIO()
        page_w, page_h = letter
        c = rl_canvas.Canvas(buf, pagesize=letter)
        cols, rows = 2, 4
        tag_w, tag_h = page_w / cols, page_h / rows

        farm_name = establishment.name if establishment else "Farm"
        crop = history.product.name if history.product else "Crop"
        # Guaranteed non-empty: may_label_container() refuses above when it is not.
        lot = label_decision.lot_id
        harvest = history.finish_date.strftime("%b %d, %Y") if history.finish_date else "In progress"

        # Constant across tags, and needed for the text width budget below: the organic
        # statement is the lowest line and sits beside the QR block, so it gets a narrower
        # column than the lines above it.
        qr_size = 1.05 * inch
        text_inset = 0.25 * inch
        full_w = tag_w - 2 * text_inset
        narrow_w = tag_w - qr_size - 0.22 * inch - text_inset - 6

        for row in range(rows):
            for col in range(cols):
                x0 = col * tag_w
                y0 = page_h - (row + 1) * tag_h
                c.setLineWidth(0.5)
                c.setDash(2, 2)
                c.rect(x0 + 6, y0 + 6, tag_w - 12, tag_h - 12)
                c.setDash()

                text_x = x0 + text_inset
                cursor = y0 + tag_h - 0.45 * inch

                # leading_ratio 1.15 (not 0.82): at 10pt the old value gave 9.2pt of leading, so
                # a wrapped certifying-agent name printed with its two lines almost touching —
                # legible on screen, but on a physical container label it reads as a press fault.
                def draw_fitted(text, font, size, width, max_lines=1, leading_ratio=1.15):
                    """Draw `text` at the running cursor, shrinking/wrapping to fit `width`."""
                    nonlocal cursor
                    pt, lines = _fit_label_text(c, text, font, size, width, max_lines=max_lines)
                    c.setFont(font, pt)
                    for i, line in enumerate(lines):
                        if i:
                            cursor -= pt * leading_ratio + 1
                        c.drawString(text_x, cursor, line)

                draw_fitted(farm_name, "Helvetica-Bold", 13, full_w)
                cursor -= 0.26 * inch
                draw_fitted(crop, "Helvetica", 11, full_w)
                cursor -= 0.3 * inch
                draw_fitted(f"LOT {lot}", "Helvetica-Bold", 14, full_w)
                cursor -= 0.26 * inch
                draw_fitted(f"Harvested {harvest}", "Helvetica", 10, full_w)
                if organic_line:
                    cursor -= 0.24 * inch
                    # § 205.307(a)(1). Two lines allowed: certifying-agent names are long
                    # ("California Certified Organic Farmers") and must print in full.
                    draw_fitted(organic_line, "Helvetica-Bold", 10, narrow_w, max_lines=2)

                c.drawImage(
                    qr_reader,
                    x0 + tag_w - qr_size - 0.22 * inch,
                    y0 + 0.22 * inch,
                    qr_size,
                    qr_size,
                )
                c.setFont("Helvetica", 6.5)
                c.drawString(x0 + 0.25 * inch, y0 + 0.18 * inch, "Scan for the full growing record")
            # one page of 8 identical tags is the default; future: copies param
        c.showPage()
        c.save()
        buf.seek(0)

        # WS-3: file a dated copy in the DMS, then stream the same bytes.
        from documents.services.filing import file_document

        safe_lot = (history.lot_id or str(history.public_id)[:8]).replace("/", "-")
        file_document(
            establishment=history.parcel.establishment,
            source="lot_tag",
            folder="exports",
            title=f"Lot tags — {safe_lot}",
            filename=f"lot-tags-{safe_lot}.pdf",
            content=buf.getvalue(),
            content_type="application/pdf",
            history=history,
            parcel=history.parcel,
            created_by=request.user,
        )
        response = HttpResponse(buf.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="lot-tags-{safe_lot}.pdf"'
        if label_decision.warning:
            # § 205.307(a)(1): the operation holds a certificate but this lot did not clear the
            # organic gate, so the tags ship without organic identification. A file download has
            # no body to put this in, so it rides a header the client surfaces — the previous
            # behaviour was a server log the grower could never see.
            #
            # Force ASCII: Django RFC 2047-encodes any header value containing non-ASCII, so a
            # single em-dash turns the message into `=?utf-8?q?...?=` and the CFR cite stops
            # being readable by either a human or a test.
            response["X-Trazo-Label-Warning"] = (
                label_decision.warning.replace("\n", " ").encode("ascii", "replace").decode("ascii")
            )
        return response

    @action(detail=False, methods=["get"], url_path="recent-inputs", permission_classes=[IsAuthenticated])
    def recent_inputs(self, request):
        """
        Distinct chemical products this establishment has used before —
        powers the "My products" quick-pick that prefills the chemical form
        (farmers reapply the same inputs all season).
        """
        from company.models import Establishment
        from users.models import WorksIn

        establishment_id = request.query_params.get("establishment_id")
        if not establishment_id:
            return Response({"error": "establishment_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            establishment = Establishment.objects.get(id=establishment_id)
        except Establishment.DoesNotExist:
            return Response({"error": "Establishment not found"}, status=status.HTTP_404_NOT_FOUND)
        if not WorksIn.objects.filter(user=request.user, company=establishment.company, role__in=["CA", "FM"]).exists():
            return Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)

        events = (
            ChemicalEvent.objects.filter(history__parcel__establishment=establishment)
            .exclude(commercial_name__isnull=True)
            .exclude(commercial_name="")
            .order_by("-date")[:200]
        )
        seen = set()
        products = []
        for e in events:
            key = e.commercial_name.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            products.append(
                {
                    "commercial_name": e.commercial_name,
                    # F27 fix (2026-06): active_ingredient is NOT a ChemicalEvent model
                    # field (it lands in extra_data) — direct e.active_ingredient raised
                    # AttributeError, 500-ing the whole picker on every chemical form load.
                    "active_ingredient": (
                        getattr(e, "active_ingredient", None) or (e.extra_data or {}).get("active_ingredient", "") or ""
                    ),
                    "concentration": e.concentration or "",
                    "organic_approved": e.organic_approved or "",
                    "epa_registration_number": getattr(e, "epa_registration_number", None) or "",
                    "application_method": getattr(e, "application_method_structured", None) or "",
                    "type": e.type,
                    "last_used": e.date.date().isoformat() if e.date else None,
                }
            )
            if len(products) >= 20:
                break
        return Response(products, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="seed-suppliers")
    def seed_suppliers(self, request):
        """Seed suppliers this farm has recorded before, for the planting form's pickers.

        WHY this shape. USDA Form 10 Part A is a PERSISTENT supplier list — its whole purpose
        is to be referenced again next season, and a free-text string retyped per event cannot
        do that. The Planting teardown called for a supplier entity.

        This derives the list from the records the grower already wrote (the
        `seed_supplier_name` column and the supplier names inside `seed_search_attempts`)
        rather than introducing a curated `SeedSupplier` model with its own CRUD, permissions
        and editor surface. The trade is deliberate and worth stating: a derived list cannot
        hold a supplier the grower has never used, and it cannot carry contact details the
        events do not have. What it does give — last season's suppliers, spelled the way this
        farm spells them, one click away — is the part of Form 10 Part A that actually gets
        used, and it mirrors `recent_inputs`, which solves the identical problem for chemical
        products. A curated entity remains the right answer if suppliers ever need attributes
        of their own (contact, certificate on file, expiry).

        Owner-gated exactly like `recent_inputs`: a supplier list is commercial relationship
        data, and it is the same class of counterparty name the consumer payload scrubs.
        """
        from common.field_registry import SEED_SOURCED_SUBTYPES
        from company.models import Establishment
        from users.models import WorksIn

        establishment_id = request.query_params.get("establishment_id")
        if not establishment_id:
            return Response({"error": "establishment_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            establishment = Establishment.objects.get(id=establishment_id)
        except (Establishment.DoesNotExist, ValueError):
            return Response({"error": "Establishment not found"}, status=status.HTTP_404_NOT_FOUND)
        if not WorksIn.objects.filter(user=request.user, company=establishment.company, role__in=["CA", "FM"]).exists():
            return Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)

        events = ProductionEvent.objects.filter(
            history__parcel__establishment=establishment,
            type__in=SEED_SOURCED_SUBTYPES,
        ).order_by("-date")[:200]

        seen = {}
        for event in events:
            when = event.date.date().isoformat() if event.date else None
            candidates = [(event.seed_supplier_name, "purchase")]
            # The search rows name suppliers the grower CONTACTED but did not buy from. Those
            # are the ones hardest to remember next season and the ones § 205.204(a)(1) asks
            # about, so they belong in the picker just as much as the one they bought from.
            for attempt in getattr(event, "seed_search_attempts", None) or []:
                if isinstance(attempt, dict):
                    candidates.append((attempt.get("supplier_name") or attempt.get("supplier"), "search"))

            for raw, origin in candidates:
                name = (raw or "").strip()
                if not name:
                    continue
                key = name.lower()
                existing = seen.get(key)
                if existing is None:
                    seen[key] = {"supplier_name": name, "last_seen": when, "sources": [origin]}
                else:
                    if origin not in existing["sources"]:
                        existing["sources"].append(origin)
                    # Events are already newest-first, so the first date wins.
                    if existing["last_seen"] is None:
                        existing["last_seen"] = when

        return Response(list(seen.values())[:40], status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="pur-export", permission_classes=[IsAuthenticated])
    def pur_export(self, request):
        """
        California Pesticide Use Report (PUR / DPR-PML-017C) for an establishment + month.

        Generated from logged chemical events (pesticides/fungicides/herbicides) using
        the F20 legal spray-record fields. Due to the County Ag Commissioner by the 10th
        of the following month (3 CCR 6626).

        Query parameters:
          establishment_id  (required)
          month             1-12 (required)
          year              e.g. 2026 (required)
          export_format     json (default, preview + per-row completeness) or csv (download).
                            NOTE: named export_format, not "format" — DRF reserves the
                            "format" query param for content negotiation (a ?format=csv
                            would 404 with no csv renderer registered).
        """
        from django.http import FileResponse

        from company.models import Establishment
        from users.models import WorksIn

        from .services.pur_export_service import PURExportService

        establishment_id = request.query_params.get("establishment_id")
        if not establishment_id:
            return Response({"error": "establishment_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            establishment = Establishment.objects.select_related("company").get(id=establishment_id)
        except (Establishment.DoesNotExist, ValueError):
            return Response({"error": "Establishment not found"}, status=status.HTTP_404_NOT_FOUND)
        # NB: "CA"/"FM" here are WorksIn ROLE codes (company admin / farm manager),
        # not the state — this endpoint had no state check at all.
        if not WorksIn.objects.filter(user=request.user, company=establishment.company, role__in=["CA", "FM"]).exists():
            return Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)

        # The PUR is a California filing (3 CCR 6626) and the CSV embeds CA county
        # codes. Serving it to an out-of-state farm produced a document titled
        # "California Pesticide Use Report" naming a county that does not exist in
        # California — misleading on a regulator-facing artifact. 404, not 403:
        # the report does not exist for this farm, it is not a permission failure.
        if resolve_establishment_state(establishment) != "CA":
            return Response(
                {"error": "The Pesticide Use Report is a California filing and is not available for this farm."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Plan gate, and it goes AFTER the state check on purpose.
        #
        # Ordered the other way, a Florida farm on Starter was told to buy Compliance to unlock the
        # CALIFORNIA Pesticide Use Report — a document that does not exist for their operation at
        # any price. "Does not apply to you" has to win over "costs money", or the upsell is a lie.
        #
        # Resolved from the ESTABLISHMENT's company rather than the caller's active one: a user who
        # works in two companies must not have one farm's plan authorise the other farm's filing.
        # See subscriptions/gating.py.
        require_compliance_exports(establishment.company, user=request.user)

        try:
            month = int(request.query_params.get("month", ""))
            year = int(request.query_params.get("year", ""))
        except (TypeError, ValueError):
            return Response({"error": "month and year are required integers"}, status=status.HTTP_400_BAD_REQUEST)
        if not (1 <= month <= 12):
            return Response({"error": "month must be 1-12"}, status=status.HTTP_400_BAD_REQUEST)

        # "export_format" (NOT "format"): DRF reserves ?format= for content negotiation.
        export_format = request.query_params.get("export_format", "json").lower()
        if export_format not in {"json", "csv"}:
            return Response(
                {"error": "Invalid export_format. Use 'json' or 'csv'."}, status=status.HTTP_400_BAD_REQUEST
            )

        service = PURExportService(establishment, month, year)

        if export_format == "csv":
            buffer = service.to_csv()
            # WS-3: file a dated copy in the DMS, then stream the same bytes.
            from io import BytesIO

            from documents.services.filing import file_document

            data = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer.read()
            if isinstance(data, str):
                data = data.encode("utf-8")
            file_document(
                establishment=establishment,
                source="pur",
                folder="exports",
                title=f"California PUR — {year}-{month:02d}",
                filename=f"trazo-pur-{establishment_id}-{year}-{month:02d}.csv",
                content=data,
                content_type="text/csv",
                created_by=request.user,
            )
            response = FileResponse(BytesIO(data), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = (
                f'attachment; filename="trazo-pur-{establishment_id}-{year}-{month:02d}.csv"'
            )
            return response

        summary = service.summary()
        # Drop the internal _missing_required key from the JSON preview rows (the
        # human-readable gaps are already in each row's "notes").
        for row in summary["rows"]:
            row.pop("_missing_required", None)
        return Response(summary, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], url_path="audit-export", permission_classes=[IsAuthenticated])
    def audit_export(self, request, **kwargs):
        """
        Generate an audit-ready export for a production.

        Query parameters:
          certification  one of: all, organic, globalgap, roc, fsma204, scs  (default: all)
          format         pdf or csv  (default: pdf)

        Returns a downloadable PDF or CSV file.
        """
        from django.http import FileResponse

        from .services.audit_export_service import AuditExportService, OFPPMissingError, PhotoEmbedMisconfigurationError

        production = self.get_object()

        # Verify the requesting user belongs to this production's company
        self.check_write_permission(request, production)

        # Plan gate, from the PRODUCTION's owning company (not the caller's active one).
        require_compliance_exports(production.parcel.establishment.company, user=request.user)

        cert_type = request.query_params.get("certification", "all").lower()
        export_format = request.query_params.get("export_format", "pdf").lower()
        # strict_ofpp=true is an opt-in gate intended for certifier-handoff
        # exports ("Mark as Submitted"). Default is False so farmers can
        # always generate a diagnostic preview and SEE the OFPP [FAIL] row
        # on page 1. Accepts the usual truthy strings.
        # strict_ofpp tri-state: unset → service-side default (True for
        # organic / all-certs exports, False otherwise). Explicit "false"
        # / "0" / "no" → diagnostic preview (caller wants to SEE the FAIL
        # row on page 1). Explicit "true" / "1" / "yes" → force strict
        # even on non-organic cert types.
        _raw_strict = request.query_params.get("strict_ofpp")
        if _raw_strict is None:
            strict_ofpp = None
        elif _raw_strict.lower() in ("1", "true", "yes"):
            strict_ofpp = True
        elif _raw_strict.lower() in ("0", "false", "no"):
            strict_ofpp = False
        else:
            strict_ofpp = None

        valid_certifications = {"all", "organic", "globalgap", "roc", "fsma204", "scs"}
        if cert_type not in valid_certifications:
            return Response(
                {
                    "error": f"Invalid certification type '{cert_type}'.",
                    "valid_options": sorted(valid_certifications),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if export_format not in {"pdf", "csv"}:
            return Response(
                {"error": "Invalid format. Use 'pdf' or 'csv'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Prefetch all event types and their photo albums to avoid N+1 queries
        from django.db.models import Prefetch

        from carbon.models import CarbonEntry

        production = (
            History.objects.select_related(
                "product",
                "parcel__establishment__company",
                "parcel__establishment",
                "crop_type",
                "operator",
            )
            .prefetch_related(
                Prefetch(
                    "history_weatherevent_events",
                    queryset=WeatherEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_chemicalevent_events",
                    queryset=ChemicalEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_productionevent_events",
                    queryset=ProductionEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_generalevent_events",
                    queryset=GeneralEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_equipmentevent_events",
                    queryset=EquipmentEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_soilmanagementevent_events",
                    queryset=SoilManagementEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_pestmanagementevent_events",
                    queryset=PestManagementEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "history_businessevent_events",
                    queryset=BusinessEvent.objects.select_related("album").prefetch_related("album__images"),
                ),
                Prefetch(
                    "carbonentry_set",
                    queryset=CarbonEntry.objects.select_related("source").order_by("-timestamp"),
                ),
            )
            .get(pk=production.pk)
        )

        try:
            service = AuditExportService(production, certification_type=cert_type)

            # WS-3: file a dated copy in the DMS, then stream the same bytes.
            from io import BytesIO

            from documents.services.filing import file_document

            if export_format == "csv":
                buffer = service.generate_csv()
                data = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer.read()
                if isinstance(data, str):
                    data = data.encode("utf-8")
                file_document(
                    establishment=production.parcel.establishment,
                    source="dossier",
                    folder="exports",
                    title=f"Audit export CSV — {production.name} ({cert_type})",
                    filename=f"trazo-audit-{production.public_id}.csv",
                    content=data,
                    content_type="text/csv",
                    history=production,
                    parcel=production.parcel,
                    created_by=request.user,
                )
                response = FileResponse(BytesIO(data), content_type="text/csv; charset=utf-8")
                response["Content-Disposition"] = f'attachment; filename="trazo-audit-{production.public_id}.csv"'
            else:
                buffer = service.generate_pdf(strict_ofpp=strict_ofpp)
                data = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer.read()
                file_document(
                    establishment=production.parcel.establishment,
                    source="dossier",
                    folder="exports",
                    title=f"Audit dossier — {production.name} ({cert_type})",
                    filename=f"trazo-audit-{production.public_id}.pdf",
                    content=data,
                    content_type="application/pdf",
                    history=production,
                    parcel=production.parcel,
                    created_by=request.user,
                )
                response = FileResponse(BytesIO(data), content_type="application/pdf")
                response["Content-Disposition"] = f'attachment; filename="trazo-audit-{production.public_id}.pdf"'

            return response

        except PhotoEmbedMisconfigurationError as exc:
            # Deliberate gate — we refuse to ship an inspector-grade audit
            # PDF whose photo-evidence layer is empty or broken. Returns
            # 503 so the frontend can surface a "server not audit-ready"
            # banner instead of a generic 500.
            logger.error(
                "Audit PDF emission refused for production %s (photo-evidence gate): %s",
                production.pk,
                exc,
            )
            return Response(
                {
                    "error": "audit_pdf_photo_evidence_unavailable",
                    "detail": str(exc),
                    "mode": exc.mode,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except OFPPMissingError as exc:
            # strict_ofpp=true was requested but the establishment's OFPP
            # is a FAIL. Return 422 (Unprocessable Entity) — the request
            # was well-formed but the business precondition isn't met.
            # Frontend should surface an actionable "upload OFPP before
            # submitting" prompt rather than a generic 500.
            logger.warning(
                "Strict-OFPP export refused for production %s: %s",
                production.pk,
                exc,
            )
            return Response(
                {
                    "error": "audit_pdf_ofpp_missing",
                    "detail": exc.reason,
                    "doc_name": exc.doc_name,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception as exc:
            logger.exception("Audit export failed for production %s: %s", production.pk, exc)
            return Response(
                {"error": "Export generation failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"], url_path="audit-trail", permission_classes=[IsAuthenticated])
    def audit_trail(self, request, **kwargs):
        """
        Return the chronological edit history (django-auditlog) for this production
        and all its child events. NOP / 21 CFR Part 11 trustworthy-records support.

        Response:
          { "entries": [{ "timestamp": "...", "actor": "...", "action": "create|update|delete",
                          "model": "ProductionEvent", "object_id": "...", "changes": {...} }, ...],
            "production_finalized": bool,  # finish_date is set
            "finish_date": "..." | null,
            "warning": "..." | null }       # post-finalization edit warning
        """
        from auditlog.models import LogEntry

        production = self.get_object()
        self.check_write_permission(request, production)

        # Gather LogEntries for the History row plus all its child events.
        history_entries = LogEntry.objects.get_for_object(production)

        event_querysets = [
            production.history_productionevent_events.all(),
            production.history_chemicalevent_events.all(),
            production.history_soilmanagementevent_events.all(),
            production.history_pestmanagementevent_events.all(),
            production.history_businessevent_events.all(),
            production.history_weatherevent_events.all(),
            production.history_generalevent_events.all(),
        ]
        event_log_entries = []
        for qs in event_querysets:
            for ev in qs:
                event_log_entries.extend(LogEntry.objects.get_for_object(ev))

        all_entries = list(history_entries) + event_log_entries
        all_entries.sort(key=lambda le: le.timestamp, reverse=True)

        action_map = {
            LogEntry.Action.CREATE: "create",
            LogEntry.Action.UPDATE: "update",
            LogEntry.Action.DELETE: "delete",
            LogEntry.Action.ACCESS: "access",
        }

        finalize_warning = None
        if production.finish_date:
            post_finalize = [
                le
                for le in all_entries
                if le.action == LogEntry.Action.UPDATE and le.timestamp.date() > production.finish_date.date()
            ]
            if post_finalize:
                finalize_warning = (
                    f"This production was finalized on {production.finish_date.date()}. "
                    f"{len(post_finalize)} edit(s) recorded after finalization. "
                    f"Inspector should review these changes."
                )

        return Response(
            {
                "entries": [
                    {
                        "timestamp": le.timestamp.isoformat(),
                        "actor": le.actor.email if le.actor else "system",
                        "action": action_map.get(le.action, "unknown"),
                        "model": le.content_type.model_class().__name__ if le.content_type else "Unknown",
                        "object_id": str(le.object_pk),
                        "object_repr": le.object_repr,
                        "changes": le.changes_dict,
                    }
                    for le in all_entries
                ],
                "production_finalized": bool(production.finish_date),
                "finish_date": production.finish_date.isoformat() if production.finish_date else None,
                "warning": finalize_warning,
            }
        )


@api_view(["GET"])
@permission_classes_decorator([IsAuthenticated])
def audit_export_by_uuid(request, public_id):
    """
    Standalone audit export endpoint that accepts production UUID.

    This supplements the HistoryViewSet action (which uses numeric pk)
    so frontends can call with the UUID visible in the URL bar.
    """
    from django.http import FileResponse

    from .services.audit_export_service import AuditExportService, OFPPMissingError, PhotoEmbedMisconfigurationError

    production = get_object_or_404(History, public_id=public_id)

    # Permission check: user must belong to the production's company
    from users.models import WorksIn

    if not request.user.is_superuser:
        company = production.parcel.establishment.company
        if not WorksIn.objects.filter(user=request.user, company=company).exists():
            raise PermissionDenied("You do not have access to this production.")

    # Plan gate. This is the UUID twin of HistoryViewSet.audit_export and produces the identical
    # document, so it must carry the identical gate — a second door onto one artifact is exactly
    # how a paywall ends up being enforced on only one of them.
    require_compliance_exports(production.parcel.establishment.company, user=request.user)

    cert_type = request.query_params.get("certification", "all").lower()
    export_format = request.query_params.get("export_format", "pdf").lower()
    # strict_ofpp tri-state: unset → service-side default (True for
    # organic / all-certs, False otherwise). Explicit "false" → diagnostic
    # preview. Explicit "true" → force strict on non-organic too.
    _raw_strict = request.query_params.get("strict_ofpp")
    if _raw_strict is None:
        strict_ofpp = None
    elif _raw_strict.lower() in ("1", "true", "yes"):
        strict_ofpp = True
    elif _raw_strict.lower() in ("0", "false", "no"):
        strict_ofpp = False
    else:
        strict_ofpp = None

    valid_certifications = {"all", "organic", "globalgap", "roc", "fsma204", "scs"}
    if cert_type not in valid_certifications:
        return Response(
            {"error": f"Invalid certification type '{cert_type}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if export_format not in {"pdf", "csv"}:
        return Response(
            {"error": "Invalid format. Use 'pdf' or 'csv'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Prefetch all event types for efficient export
    from django.db.models import Prefetch

    from carbon.models import CarbonEntry

    production = (
        History.objects.select_related(
            "product",
            "parcel__establishment__company",
            "parcel__establishment",
            "crop_type",
            "operator",
        )
        .prefetch_related(
            Prefetch(
                "history_weatherevent_events",
                queryset=WeatherEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_chemicalevent_events",
                queryset=ChemicalEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_productionevent_events",
                queryset=ProductionEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_generalevent_events",
                queryset=GeneralEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_equipmentevent_events",
                queryset=EquipmentEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_soilmanagementevent_events",
                queryset=SoilManagementEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_pestmanagementevent_events",
                queryset=PestManagementEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "history_businessevent_events",
                queryset=BusinessEvent.objects.select_related("album").prefetch_related("album__images"),
            ),
            Prefetch(
                "carbonentry_set",
                queryset=CarbonEntry.objects.select_related("source").order_by("-timestamp"),
            ),
        )
        .get(pk=production.pk)
    )

    try:
        service = AuditExportService(production, certification_type=cert_type)

        # File a dated copy in the DMS, then stream the same bytes — same
        # behavior as the numeric-pk route above. This UUID route is the one
        # the production "Export for Audit" button actually hits (the frontend
        # passes public_id), so without this call the app's most prominent
        # export was the only one that never appeared in Documents.
        from io import BytesIO

        from documents.services.filing import file_document

        if export_format == "csv":
            buffer = service.generate_csv()
            data = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer.read()
            if isinstance(data, str):
                data = data.encode("utf-8")
            file_document(
                establishment=production.parcel.establishment,
                source="dossier",
                folder="exports",
                title=f"Audit export CSV — {production.name} ({cert_type})",
                filename=f"trazo-audit-{production.public_id}.csv",
                content=data,
                content_type="text/csv",
                history=production,
                parcel=production.parcel,
                created_by=request.user if request.user.is_authenticated else None,
            )
            response = FileResponse(BytesIO(data), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="trazo-audit-{production.public_id}.csv"'
        else:
            buffer = service.generate_pdf(strict_ofpp=strict_ofpp)
            data = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer.read()
            file_document(
                establishment=production.parcel.establishment,
                source="dossier",
                folder="exports",
                title=f"Audit dossier — {production.name} ({cert_type})",
                filename=f"trazo-audit-{production.public_id}.pdf",
                content=data,
                content_type="application/pdf",
                history=production,
                parcel=production.parcel,
                created_by=request.user if request.user.is_authenticated else None,
            )
            response = FileResponse(BytesIO(data), content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="trazo-audit-{production.public_id}.pdf"'

        return response

    except PhotoEmbedMisconfigurationError as exc:
        logger.error(
            "Audit PDF emission refused for production %s (photo-evidence gate): %s",
            production.pk,
            exc,
        )
        return Response(
            {
                "error": "audit_pdf_photo_evidence_unavailable",
                "detail": str(exc),
                "mode": exc.mode,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except OFPPMissingError as exc:
        logger.warning(
            "Strict-OFPP export refused for production %s: %s",
            production.pk,
            exc,
        )
        return Response(
            {
                "error": "audit_pdf_ofpp_missing",
                "detail": exc.reason,
                "doc_name": exc.doc_name,
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except Exception as exc:
        logger.exception("Audit export failed for production %s: %s", production.pk, exc)
        return Response(
            {"error": "Export generation failed. Please try again."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class PublicHistoryScanViewSet(viewsets.ModelViewSet):
    """
    Enhanced public scan endpoint with 2025 security, privacy & performance standards
    Handles QR scans, page views, and consumer feedback with GDPR compliance
    """

    queryset = HistoryScan.objects.select_related(
        "history", "history__product", "history__parcel", "history__parcel__establishment", "user"
    ).all()
    # Use default auth (CustomAuthentication) so logged-in users are detected via cookies.
    # AllowAny still lets anonymous users through — CustomAuthentication returns None
    # gracefully when no credentials are present.
    permission_classes = [AllowAny]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Import services here to avoid circular imports
        from .services.bot_detection_service import BotDetectionService
        from .services.deduplication_service import DeduplicationService
        from .services.privacy_service import PrivacyService

        self.privacy_service = PrivacyService
        self.deduplication_service = DeduplicationService
        self.bot_detection_service = BotDetectionService

    def create(self, request):
        """
        Enhanced scan creation with 2025 privacy, security & performance standards
        Supports: QR scans, feedback collection, bot detection, deduplication
        """
        try:
            # Input validation
            validation_result = self._validate_scan_request(request)
            if validation_result:
                return validation_result

            production_id = request.data.get("production_id")

            # Get the production/history with validation (supports integer ID or UUID public_id)
            try:
                try:
                    pid = int(production_id)
                    history = History.objects.select_related("parcel__establishment__company", "product").get(id=pid)
                except (ValueError, TypeError):
                    history = History.objects.select_related("parcel__establishment__company", "product").get(
                        public_id=production_id
                    )

                # Check if production is publicly accessible
                if not history.published:
                    return Response({"error": "Production not publicly accessible"}, status=status.HTTP_403_FORBIDDEN)

            except History.DoesNotExist:
                return Response({"error": "Production not found"}, status=status.HTTP_404_NOT_FOUND)

            # Bot detection and security checks
            should_block, block_reason = self.bot_detection_service.should_block_request(request, request.data)

            if should_block:
                return Response(
                    {"error": "Request rejected", "reason": block_reason}, status=status.HTTP_429_TOO_MANY_REQUESTS
                )

            # Process privacy and consent data
            privacy_data = self.privacy_service.process_scan_consent(request)

            # Check for consent requirement
            # User-submitted feedback (comments) is allowed without analytics
            # consent — it's a user-initiated action under GDPR Art. 6(1)(b),
            # not passive tracking.  The privacy_service already returns minimal
            # data (empty hashes, no geolocation) when consent is not given.
            consent_required = self.privacy_service.is_consent_required(request)
            consent_given = privacy_data["consent_given"]
            has_comment = bool(request.data.get("comment", "").strip())

            # Privacy-first: if the visitor hasn't consented to analytics (and
            # isn't leaving a comment), still record an ANONYMOUS aggregate scan
            # rather than rejecting it with 428. privacy_data is already minimal
            # here (empty session/IP hashes, no geolocation), so this is an
            # anonymous count — not personal-data processing — and needs no
            # consent under GDPR. Full analytics + session dedup remain gated on
            # consent below. (Previously this returned 428, so non-consenting
            # scans were never counted, undercounting QR engagement and surfacing
            # a console error on every load.)
            anonymous_mode = consent_required and not consent_given and not has_comment

            # Session deduplication check (use history.id, not the UUID
            # production_id). Skip in anonymous_mode — with empty session/IP
            # hashes there is no identity to dedup against, and forcing it would
            # collapse every anonymous scan into a single "duplicate".
            if anonymous_mode:
                is_duplicate, original_scan, dedup_method = False, None, None
            else:
                is_duplicate, original_scan, dedup_method = self.deduplication_service.check_comprehensive_duplicate(
                    privacy_data["session_hash"], privacy_data["ip_hash"], history.id
                )

            # Calculate bot score and engagement
            bot_score = self.bot_detection_service.calculate_bot_score(request, request.data)
            is_verified_human = self.bot_detection_service.is_verified_human(request, request.data)

            # Calculate engagement score
            engagement_score = self._calculate_engagement_score(request.data)

            # Determine scan type
            scan_type = self._determine_scan_type(request.data)

            # Determine referrer type
            referrer_type = self._determine_referrer_type(request)

            # Get authenticated user
            user = request.user if request.user.is_authenticated else None

            # Create enhanced scan with all new fields
            scan_data = {
                "history": history,
                "user": user,
                "comment": request.data.get("comment", ""),
                # Privacy & GDPR fields
                **privacy_data,
                # Deduplication fields
                "is_duplicate": is_duplicate,
                "original_scan": original_scan,
                # Bot detection & quality fields
                "bot_score": bot_score,
                "is_verified_human": is_verified_human,
                # Analytics & engagement fields
                "scan_type": scan_type,
                "engagement_score": engagement_score,
                "referrer_type": referrer_type,
            }

            # Create the scan
            scan = HistoryScan.objects.create(**scan_data)

            # Mark as duplicate if needed
            if is_duplicate and original_scan:
                self.deduplication_service.mark_as_duplicate(original_scan, scan)

            # Trigger notifications (only for high-quality, non-duplicate scans)
            if not is_duplicate and bot_score < 0.5:
                self.create_scan_notification(history, user, scan)

            # Return success response with minimal data
            response_data = {
                "id": scan.id,
                "claim_token": scan.claim_token,
                "message": "Scan recorded successfully",
                "is_duplicate": is_duplicate,
                "deduplication_method": dedup_method if is_duplicate else None,
            }

            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            # Log error for monitoring (don't expose internal details)
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Enhanced scan creation failed: {str(e)}", exc_info=True)

            return Response({"error": "Failed to record scan"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _validate_scan_request(self, request):
        """
        Validate scan request data and headers
        """
        # Required fields validation
        production_id = request.data.get("production_id")
        if not production_id:
            return Response({"error": "production_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate production_id format (accepts integer ID or UUID public_id)
        try:
            int(production_id)
        except (ValueError, TypeError):
            # Not an integer - check if it's a valid UUID
            try:
                uuid.UUID(str(production_id))
            except ValueError:
                return Response({"error": "Invalid production_id format"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate comment length
        comment = request.data.get("comment", "")
        if comment and len(comment) > 1000:  # Reasonable limit
            return Response({"error": "Comment too long (max 1000 characters)"}, status=status.HTTP_400_BAD_REQUEST)

        # Basic content validation
        if comment and self._contains_suspicious_content(comment):
            return Response({"error": "Comment contains inappropriate content"}, status=status.HTTP_400_BAD_REQUEST)

        return None

    def _contains_suspicious_content(self, text):
        """
        Basic content filtering for obvious spam/malicious content
        """
        if not text:
            return False

        text_lower = text.lower()

        # Check for obvious spam patterns
        spam_indicators = [
            "http://",
            "https://",
            "www.",  # URLs
            "click here",
            "buy now",
            "free money",  # Spam phrases
            "<script",
            "<?php",
            "javascript:",  # Code injection attempts
        ]

        return any(indicator in text_lower for indicator in spam_indicators)

    def _determine_scan_type(self, data):
        """
        Determine the type of scan based on request data
        """
        comment = data.get("comment", "")

        if comment and len(comment.strip()) > 0:
            # Check if it looks like structured feedback
            if any(keyword in comment.lower() for keyword in ["reaction:", "rating:", "score:"]):
                return "feedback"
            else:
                return "review"

        # Check for social sharing indicators
        if data.get("shared", False) or data.get("referrer_type") == "social":
            return "share"

        return "qr"

    def _determine_referrer_type(self, request):
        """
        Determine how the user reached the page
        """
        referrer = request.META.get("HTTP_REFERER", "")

        if not referrer:
            return "direct"

        referrer_lower = referrer.lower()

        # Social media platforms
        social_platforms = ["facebook", "twitter", "instagram", "linkedin", "whatsapp", "telegram"]
        if any(platform in referrer_lower for platform in social_platforms):
            return "social"

        # Search engines
        search_engines = ["google", "bing", "yahoo", "duckduckgo"]
        if any(engine in referrer_lower for engine in search_engines):
            return "search"

        # Email clients (limited detection)
        if "mail" in referrer_lower or "email" in referrer_lower:
            return "email"

        # If from same domain, likely QR code or direct link
        if "trazo" in referrer_lower:
            return "qr"

        return "other"

    def _calculate_engagement_score(self, data):
        """
        Calculate engagement score based on available data
        """
        score = 0.0

        # Time on page (if provided by frontend)
        time_on_page = data.get("time_on_page", 0)
        try:
            time_on_page = float(time_on_page)
            if time_on_page >= 30:  # 30+ seconds
                score += 0.3
            elif time_on_page >= 10:  # 10+ seconds
                score += 0.2
            elif time_on_page >= 5:  # 5+ seconds
                score += 0.1
        except (ValueError, TypeError):
            pass

        # Comment engagement
        comment = data.get("comment", "")
        if comment and len(comment.strip()) > 0:
            if len(comment) > 50:  # Substantial comment
                score += 0.4
            elif len(comment) > 20:  # Medium comment
                score += 0.3
            else:  # Short comment
                score += 0.2

        # Interaction count (if provided by frontend)
        interactions = data.get("interactions", 0)
        try:
            interactions = int(interactions)
            if interactions >= 5:
                score += 0.3
            elif interactions >= 2:
                score += 0.2
            elif interactions >= 1:
                score += 0.1
        except (ValueError, TypeError):
            pass

        return min(score, 1.0)

    def create_scan_notification(self, history, scanner, scan):
        """
        Enhanced notification creation with scan quality filtering
        """
        try:
            if history.parcel and history.parcel.establishment:
                # Get the company and find company admins via WorksIn relationship
                company = history.parcel.establishment.company

                # Get company admins (users with 'CA' role)
                from users.models import WorksIn

                company_admins = WorksIn.objects.filter(
                    company=company, role="CA"  # Company Admin role
                ).select_related("user")

                # Send notification to all company admins who are not the scanner
                for admin_relation in company_admins:
                    product_owner = admin_relation.user

                    # Only send notification if scanner is different from product owner
                    if scanner != product_owner:
                        # Get product name
                        product_name = history.product.name if history.product else f"Production {history.id}"

                        # Privacy-safe location
                        scan_location = scan.get_location_display() if scan else None

                        # Create notification with enhanced context
                        notification_service.create_product_scan_notification(
                            product_owner=product_owner,
                            scanner=scanner,
                            product_name=product_name,
                            scan_location=scan_location,
                            production_id=history.id,
                            establishment_id=(
                                history.parcel.establishment.id
                                if history.parcel and history.parcel.establishment
                                else None
                            ),
                            product_id=history.product.id if history.product else None,
                            parcel_id=history.parcel.id if history.parcel else None,
                        )
        except Exception as e:
            # Log error but don't break the scan functionality
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error creating scan notification: {e}", exc_info=True)

    @action(detail=True, methods=["post"], permission_classes=[AllowAny])
    def comment(self, request, pk=None):
        """
        Enhanced comment endpoint with validation and bot protection
        """
        try:
            history_scan = get_object_or_404(HistoryScan, pk=pk)

            # Bot detection for comment updates
            should_block, block_reason = self.bot_detection_service.should_block_request(request, request.data)

            if should_block:
                return Response(
                    {"error": "Request rejected", "reason": block_reason}, status=status.HTTP_429_TOO_MANY_REQUESTS
                )

            comment = request.data.get("comment", None)
            if comment is None:
                return Response({"error": "Comment is required"}, status=status.HTTP_400_BAD_REQUEST)

            # SECURITY: Prevent overwriting existing comments (IDOR protection)
            # Anonymous consumers can only set a comment once per scan
            if history_scan.comment and history_scan.comment.strip():
                return Response(
                    {"error": "Comment already exists for this scan"},
                    status=status.HTTP_409_CONFLICT,
                )

            # Validate comment
            if len(comment) > 1000:
                return Response({"error": "Comment too long (max 1000 characters)"}, status=status.HTTP_400_BAD_REQUEST)

            if self._contains_suspicious_content(comment):
                return Response({"error": "Comment contains inappropriate content"}, status=status.HTTP_400_BAD_REQUEST)

            # Update comment and recalculate engagement score
            history_scan.comment = comment

            # Recalculate engagement based on comment
            if comment and len(comment.strip()) > 0:
                if len(comment) > 50:
                    history_scan.engagement_score = max(history_scan.engagement_score, 0.4)
                elif len(comment) > 20:
                    history_scan.engagement_score = max(history_scan.engagement_score, 0.3)
                else:
                    history_scan.engagement_score = max(history_scan.engagement_score, 0.2)

            history_scan.save()

            return Response({"message": "Comment updated successfully"}, status=status.HTTP_200_OK)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Comment update failed: {str(e)}", exc_info=True)

            return Response({"error": "Failed to update comment"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["post"], url_path="claim", permission_classes=[IsAuthenticated])
    def claim_scans(self, request):
        """
        Claim anonymous scans after authentication.
        Accepts opaque claim tokens (not sequential IDs) to prevent IDOR.
        Only claims scans that are unclaimed (user=None), consented, and < 24h old.
        """
        tokens = request.data.get("claim_tokens", [])

        if not isinstance(tokens, list) or not tokens:
            return Response(
                {"error": "claim_tokens must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(tokens) > 50:
            return Response(
                {"error": "Too many tokens (max 50)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Sanitise: only allow non-empty strings, cap length
        tokens = [str(t)[:64] for t in tokens if isinstance(t, str) and t.strip()]
        if not tokens:
            return Response(
                {"error": "No valid tokens provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cutoff = timezone.now() - timedelta(hours=24)
        claimed_count = HistoryScan.objects.filter(
            claim_token__in=tokens,
            user__isnull=True,
            date__gte=cutoff,
            consent_given=True,
        ).update(user=request.user)

        return Response(
            {"claimed": claimed_count},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def roi_summary(self, request):
        """
        Phase 4 — farmer ROI card data: scans trend (30d vs prior 30d),
        engagement rate, reviews count/rating, certification views.
        Same access rule as analytics_insights (CA/FM on the establishment).
        """
        establishment_id = request.query_params.get("establishment_id")
        if not establishment_id:
            return Response({"error": "establishment_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        from company.models import Establishment
        from users.models import WorksIn

        try:
            establishment = Establishment.objects.get(id=establishment_id)
        except Establishment.DoesNotExist:
            return Response({"error": "Establishment not found"}, status=status.HTTP_404_NOT_FOUND)

        has_access = WorksIn.objects.filter(
            user=request.user,
            company=establishment.company,
            role__in=["CA", "FM"],
        ).exists()
        if not has_access:
            return Response({"error": "Access denied to this establishment"}, status=status.HTTP_403_FORBIDDEN)

        from .services.analytics_service import AnalyticsService

        try:
            return Response(AnalyticsService.get_roi_summary(establishment.id), status=status.HTTP_200_OK)
        except Exception:
            logger.error("ROI summary failed", exc_info=True)
            return Response({"error": "Failed to generate ROI summary"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def analytics_insights(self, request):
        """
        Get privacy-safe analytics insights for producers
        Requires authentication and establishment ownership
        """
        try:
            establishment_id = request.query_params.get("establishment_id")
            if not establishment_id:
                return Response({"error": "establishment_id is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Verify user has access to this establishment
            from company.models import Establishment
            from users.models import WorksIn

            try:
                establishment = Establishment.objects.get(id=establishment_id)

                # Check if user has access to this establishment's company
                has_access = WorksIn.objects.filter(
                    user=request.user,
                    company=establishment.company,
                    role__in=["CA", "FM"],  # Company Admin or Farm Manager
                ).exists()

                if not has_access:
                    return Response({"error": "Access denied to this establishment"}, status=status.HTTP_403_FORBIDDEN)

            except Establishment.DoesNotExist:
                return Response({"error": "Establishment not found"}, status=status.HTTP_404_NOT_FOUND)

            # Get date range
            days = int(request.query_params.get("days", 30))
            days = min(days, 365)  # Limit to 1 year

            # Generate privacy-safe analytics
            from .services.analytics_service import AnalyticsService

            insights = AnalyticsService.get_establishment_insights(establishment_id, days)

            return Response(insights, status=status.HTTP_200_OK)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Analytics insights failed: {str(e)}", exc_info=True)

            return Response({"error": "Failed to generate insights"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HistoryScanViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    queryset = HistoryScan.objects.select_related(
        "history", "history__product", "history__parcel", "history__parcel__establishment", "user"
    ).all()
    serializer_class = ListHistoryClassSerializer

    @action(detail=False, methods=["get"])
    def list_scans_by_establishment(self, request, parcel_pk=None, company_pk=None, establishment_pk=None):
        parcel = request.query_params.get("parcel", None)
        product = request.query_params.get("product", None)
        period = request.query_params.get("period", None)
        production = request.query_params.get("production", None)
        if period is None or period not in ALLOWED_PERIODS:
            return Response(
                {"error": "Period is required and must be week, month or year"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if self.establishment is None:
            return Response(
                {"error": "Establishment is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get date kwargs for filter by period
        date_kwargs = {}
        if period == "week":
            date_kwargs["date__gte"] = datetime.now() - timedelta(days=7)
        elif period == "month":
            date_kwargs["date__gte"] = datetime.now() - timedelta(days=30)
        elif period == "year":
            date_kwargs["date__gte"] = datetime.now() - timedelta(days=365)

        # Get last 9 scans from the establishment
        history_scans = (
            HistoryScan.objects.counted()
            .filter(
                history__parcel__establishment=self.establishment,
                **date_kwargs,
            )
            .order_by("-date")
        )
        if parcel is not None:
            history_scans = history_scans.filter(history__parcel__id=parcel)
        if product is not None:
            history_scans = history_scans.filter(history__product__id=product)
        if production is not None:
            history_scans = history_scans.filter(history__id=production)
        return Response(ListHistoryClassSerializer(history_scans[0:9], many=True, context={"history_scan": True}).data)


# Polymorphic event serializer mapping for drf-spectacular schema generation.
# Maps event_type integer codes to their corresponding serializer classes.
# Used by PolymorphicProxySerializer to tell OpenAPI consumers which shape to expect
# based on the event_type field in the request/response.
EVENT_POLYMORPHIC_SERIALIZERS = [
    WeatherEventSerializer,  # event_type = 0
    ProductionEventSerializer,  # event_type = 1
    ChemicalEventSerializer,  # event_type = 2
    GeneralEventSerializer,  # event_type = 3
    EquipmentEventSerializer,  # event_type = 4
    SoilManagementEventSerializer,  # event_type = 5
    PestManagementEventSerializer,  # event_type = 6
    BusinessEventSerializer,  # event_type = 7
]

EVENT_UPDATE_POLYMORPHIC_SERIALIZERS = [
    UpdateWeatherEventSerializer,
    UpdateProductionEventSerializer,
    UpdateChemicalEventSerializer,
    UpdateGeneralEventSerializer,
    UpdateEquipmentEventSerializer,
    UpdateSoilManagementEventSerializer,
    UpdatePestManagementEventSerializer,
    UpdateBusinessEventSerializer,
]


@extend_schema_view(
    list=extend_schema(
        summary="List agricultural events",
        description=(
            "Returns events filtered by event_type. Response shape varies based on "
            "event_type (0=Weather, 1=Production, 2=Chemical, 3=General, 4=Equipment, "
            "5=SoilManagement, 6=PestManagement, 7=Business)."
        ),
        parameters=[
            OpenApiParameter(
                name="event_type",
                type=int,
                location=OpenApiParameter.QUERY,
                description="Event type code (0-7). Determines response serializer.",
                required=True,
                enum=[0, 1, 2, 3, 4, 5, 6, 7],
            ),
        ],
        responses=PolymorphicProxySerializer(
            component_name="Event",
            serializers=EVENT_POLYMORPHIC_SERIALIZERS,
            resource_type_field_name="event_type",
        ),
    ),
    retrieve=extend_schema(
        summary="Get event detail",
        responses=PolymorphicProxySerializer(
            component_name="EventDetail",
            serializers=EVENT_UPDATE_POLYMORPHIC_SERIALIZERS,
            resource_type_field_name="event_type",
        ),
    ),
    create=extend_schema(
        summary="Create agricultural event",
        request=PolymorphicProxySerializer(
            component_name="CreateEvent",
            serializers=EVENT_UPDATE_POLYMORPHIC_SERIALIZERS,
            resource_type_field_name="event_type",
        ),
        responses=PolymorphicProxySerializer(
            component_name="CreatedEvent",
            serializers=EVENT_UPDATE_POLYMORPHIC_SERIALIZERS,
            resource_type_field_name="event_type",
        ),
    ),
    update=extend_schema(
        summary="Update event (full)",
        request=PolymorphicProxySerializer(
            component_name="UpdateEvent",
            serializers=EVENT_UPDATE_POLYMORPHIC_SERIALIZERS,
            resource_type_field_name="event_type",
        ),
        responses=PolymorphicProxySerializer(
            component_name="UpdatedEvent",
            serializers=EVENT_UPDATE_POLYMORPHIC_SERIALIZERS,
            resource_type_field_name="event_type",
        ),
    ),
    partial_update=extend_schema(
        summary="Update event (partial)",
        request=PolymorphicProxySerializer(
            component_name="PartialUpdateEvent",
            serializers=EVENT_UPDATE_POLYMORPHIC_SERIALIZERS,
            resource_type_field_name="event_type",
        ),
        responses=PolymorphicProxySerializer(
            component_name="PartialUpdatedEvent",
            serializers=EVENT_UPDATE_POLYMORPHIC_SERIALIZERS,
            resource_type_field_name="event_type",
        ),
    ),
)
class EventViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    filter_backends = [filters.OrderingFilter]

    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        self._attach_completeness_gaps(response, getattr(self, "_completeness_event", None))
        return response

    def _attach_completeness_gaps(self, response, event):
        """Echo certifier-required fields still missing on a just-saved event.

        Non-blocking by design: the farmer logs what they know standing in the orchard, so an
        incomplete record must still save — but the response tells the UI what an inspector will
        ask for (record_completeness.py, § 205.103(b)(2) / § 205.206(a) / § 205.204).

        Covers ChemicalEvent and the seed-sourced production subtypes (PL/TR) as of 2026-08-15.
        The registry itself decides — an event type with no registry returns no gaps, so the key
        is simply omitted rather than asserting a record is complete.
        """
        if not isinstance(response.data, dict):
            return
        from .services.record_completeness import completeness_gap_keys

        gaps = completeness_gap_keys(event)
        if gaps or isinstance(event, ChemicalEvent):
            # Chemical keeps emitting an empty list (the UI treats [] as "record complete");
            # other types stay silent unless there is something to say.
            response.data["completeness_gaps"] = gaps

    def get_serializer_class(self):
        event_type = (
            self.request.data.get("event_type")
            if "event_type" in self.request.data
            else self.request.query_params.get("event_type", None)
        )

        # For retrieve actions without event_type, we'll determine it in get_object
        # and store it for later use
        if event_type is None and self.action == "retrieve":
            # Check if we've already determined the event type
            if hasattr(self, "_determined_event_type"):
                event_type = self._determined_event_type
            else:
                # Default to general for now, will be corrected in retrieve method
                event_type = GENERAL_EVENT_TYPE

        if event_type is None:
            raise Exception("Event type is required")
        event_type = int(event_type)

        # Use Update serializers for retrieve action to ensure proper field flattening for editing
        is_mutation = self.action in ["create", "update", "partial_update", "retrieve"]

        if event_type == WEATHER_EVENT_TYPE:
            return UpdateWeatherEventSerializer if is_mutation else WeatherEventSerializer
        elif event_type == PRODUCTION_EVENT_TYPE:
            return UpdateProductionEventSerializer if is_mutation else ProductionEventSerializer
        elif event_type == CHEMICAL_EVENT_TYPE:
            return UpdateChemicalEventSerializer if is_mutation else ChemicalEventSerializer
        elif event_type == EQUIPMENT_EVENT_TYPE:
            return UpdateEquipmentEventSerializer if is_mutation else EquipmentEventSerializer
        elif event_type == SOIL_MANAGEMENT_EVENT_TYPE:
            return UpdateSoilManagementEventSerializer if is_mutation else SoilManagementEventSerializer
        elif event_type == PEST_MANAGEMENT_EVENT_TYPE:
            return UpdatePestManagementEventSerializer if is_mutation else PestManagementEventSerializer
        elif event_type == BUSINESS_EVENT_TYPE:
            return UpdateBusinessEventSerializer if is_mutation else BusinessEventSerializer
        else:  # GENERAL_EVENT_TYPE
            return UpdateGeneralEventSerializer if is_mutation else GeneralEventSerializer

    def get_queryset(self):
        event_type = (
            self.request.data.get("event_type")
            if "event_type" in self.request.data
            else self.request.query_params.get("event_type", None)
        )

        # For retrieve actions without event_type, return a special marker
        if event_type is None and self.action == "retrieve":
            # We'll handle this in get_object method
            return None

        if event_type is not None:
            event_type = int(event_type)

        event_model = EVENT_TYPE_TO_MODEL.get(event_type)
        if event_model:
            queryset = event_model.objects.all()
        else:
            queryset = GeneralEvent.objects.all()

        # Filter by company and establishment if they are set
        # Events are connected through: Event -> History -> Parcel -> Establishment -> Company
        if hasattr(self, "company") and self.company is not None:
            queryset = queryset.filter(history__parcel__establishment__company=self.company)

        if hasattr(self, "establishment") and self.establishment is not None:
            queryset = queryset.filter(history__parcel__establishment=self.establishment)

        return queryset

    def get_object(self):
        """
        Override get_object to handle cross-model lookups when event_type is not specified
        """
        event_type = self.request.query_params.get("event_type", None)
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        event_id = self.kwargs[lookup_url_kwarg]

        # If event_type is specified, only search in that specific event type
        if event_type is not None:
            try:
                event_type = int(event_type)
                event_model = EVENT_TYPE_TO_MODEL.get(event_type)

                if event_model:
                    queryset = event_model.objects.all()

                    # Apply the same filtering as in get_queryset
                    if hasattr(self, "company") and self.company is not None:
                        queryset = queryset.filter(history__parcel__establishment__company=self.company)

                    if hasattr(self, "establishment") and self.establishment is not None:
                        queryset = queryset.filter(history__parcel__establishment=self.establishment)

                    obj = queryset.get(pk=event_id)
                    # Check permissions
                    self.check_object_permissions(self.request, obj)
                    # Store the determined event type for serializer selection
                    self._determined_event_type = event_type
                    return obj

            except (ValueError, event_model.DoesNotExist):
                # If the specified event_type doesn't contain this event, raise 404
                from django.http import Http404

                raise Http404(f"Event with ID {event_id} not found in event type {event_type}")

        # For actions without event_type parameter, search across all event types
        if self.action in ["update", "partial_update", "retrieve"]:
            # Try to find the event across all event types

            # Apply company/establishment filtering to each model
            for event_type_id, event_model in EVENT_TYPE_TO_MODEL.items():
                try:
                    queryset = event_model.objects.all()

                    # Apply the same filtering as in get_queryset
                    if hasattr(self, "company") and self.company is not None:
                        queryset = queryset.filter(history__parcel__establishment__company=self.company)

                    if hasattr(self, "establishment") and self.establishment is not None:
                        queryset = queryset.filter(history__parcel__establishment=self.establishment)

                    obj = queryset.get(pk=event_id)
                    # Check permissions
                    self.check_object_permissions(self.request, obj)
                    # Store the determined event type for serializer selection
                    self._determined_event_type = event_type_id
                    return obj
                except event_model.DoesNotExist:
                    continue

            # If not found in any event type, raise 404
            from django.http import Http404

            raise Http404("Event not found")

        # Use default behavior for other cases
        return super().get_object()

    def retrieve(self, request, *args, **kwargs):
        """
        Override retrieve to handle event_type determination and use Update serializers for editing
        """
        instance = self.get_object()

        # If we determined the event type during get_object, update the serializer
        if hasattr(self, "_determined_event_type"):
            # Force re-evaluation of serializer class with correct event type
            event_type = self._determined_event_type

            # Get the correct Update serializer class for editing (to flatten fields)
            if event_type == WEATHER_EVENT_TYPE:
                serializer_class = UpdateWeatherEventSerializer
            elif event_type == PRODUCTION_EVENT_TYPE:
                serializer_class = UpdateProductionEventSerializer
            elif event_type == CHEMICAL_EVENT_TYPE:
                serializer_class = UpdateChemicalEventSerializer
            elif event_type == EQUIPMENT_EVENT_TYPE:
                serializer_class = UpdateEquipmentEventSerializer
            elif event_type == SOIL_MANAGEMENT_EVENT_TYPE:
                serializer_class = UpdateSoilManagementEventSerializer
            elif event_type == PEST_MANAGEMENT_EVENT_TYPE:
                serializer_class = UpdatePestManagementEventSerializer
            elif event_type == BUSINESS_EVENT_TYPE:
                serializer_class = BusinessEventSerializer
            else:  # GENERAL_EVENT_TYPE
                serializer_class = UpdateGeneralEventSerializer

            serializer = serializer_class(instance)
            return Response(serializer.data)

        # Default behavior
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        parcels_post = self.request.POST.getlist("parcels", None)
        parcels_data = self.request.data.get("parcels", [])
        event_type = self.request.data.get("event_type", None)
        explicit_history_id = self.request.data.get("history", None)

        # Use data.get instead of POST.getlist for JSON requests
        parcels = parcels_data if parcels_data else parcels_post

        if event_type is None:
            raise ValidationError({"event_type": ["Event type is required."]})

        # `parcels is []` was an identity comparison against a fresh list literal, so it
        # was ALWAYS False. An absent/empty `parcels` therefore slipped past the guard,
        # `Parcel.objects.filter(id__in=[])` matched nothing, the loop below never ran,
        # and DRF still returned 201 with the (unsaved) serializer data — a silent
        # data-loss contract for any caller that isn't the web UI.
        #
        # When only `history` is supplied — which this endpoint accepts and echoes back —
        # derive the parcel from it rather than discarding the event.
        if not parcels and explicit_history_id:
            history_parcel_id = (
                History.objects.filter(id=explicit_history_id).values_list("parcel_id", flat=True).first()
            )
            if history_parcel_id:
                parcels = [history_parcel_id]

        if not parcels:
            raise ValidationError({"parcels": ["A parcel (or a history to derive it from) is required."]})

        # Enhanced validation for structured fields
        self._validate_structured_fields(int(event_type), serializer.validated_data)

        parcels = Parcel.objects.filter(id__in=[int(parcel) for parcel in parcels]).select_related("current_history")
        if not parcels:
            raise ValidationError({"parcels": ["No matching parcel found."]})

        # Tracks whether anything was actually written. A parcel with no current_history
        # skips the body below, and without this the request would still answer 201 while
        # persisting nothing.
        created_event = None

        for parcel in parcels:
            if parcel.current_history is not None:
                # Use explicitly provided history ID if available (from Quick Add on specific production)
                # Otherwise fall back to parcel.current_history
                if explicit_history_id:
                    try:
                        history = History.objects.get(id=int(explicit_history_id), parcel=parcel)
                    except History.DoesNotExist:
                        history = parcel.current_history
                else:
                    history = parcel.current_history

                # Immutability guard: prevent adding events to completed productions
                if history.finish_date is not None or history.published:
                    raise PermissionDenied(
                        "Cannot add events to a completed production. "
                        "A finished production is a closed record; reopen it to add events."
                    )

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

                event_model = EVENT_TYPE_TO_MODEL.get(int(event_type), GeneralEvent)

                # Remove history and created_by from validated_data to prevent override
                validated_data = serializer.validated_data.copy()
                validated_data.pop("history", None)
                validated_data.pop("created_by", None)

                event = event_model.objects.create(
                    history=history,
                    index=index,
                    created_by=self.request.user,
                    **validated_data,
                )
                created_event = event

                # Handle album images from S3 URLs
                album_images = self.request.data.get("album_images", [])

                if album_images:
                    from .models import Gallery

                    gallery = Gallery.objects.create()

                    # Create GalleryImage records from S3 URLs with Vision API validation
                    for idx, image_url in enumerate(album_images, 1):
                        # SECURITY: Validate image URL against allowed S3 domains to prevent SSRF
                        from urllib.parse import urlparse

                        # The later `from django.conf import settings` inside the
                        # Vision try-block makes `settings` function-local, so it
                        # must be imported before THIS first use or the whole
                        # branch raises UnboundLocalError.
                        from django.conf import settings

                        parsed_url = urlparse(image_url)
                        allowed_hosts = set()
                        if hasattr(settings, "AWS_STORAGE_BUCKET_NAME") and settings.AWS_STORAGE_BUCKET_NAME:
                            bucket = settings.AWS_STORAGE_BUCKET_NAME
                            region = getattr(settings, "AWS_S3_REGION_NAME", "us-east-1")
                            allowed_hosts.update(
                                {
                                    f"{bucket}.s3.amazonaws.com",
                                    f"{bucket}.s3.{region}.amazonaws.com",
                                    f"s3.amazonaws.com",
                                    f"s3.{region}.amazonaws.com",
                                }
                            )
                        # Allow local dev URLs (http://localhost) but enforce HTTPS + S3 hosts in production
                        is_local_dev = parsed_url.hostname in ("localhost", "127.0.0.1")
                        if not is_local_dev and (
                            parsed_url.scheme != "https" or (allowed_hosts and parsed_url.hostname not in allowed_hosts)
                        ):
                            logger.warning("Rejected image URL (SSRF protection): %s", image_url)
                            continue

                        # Extract S3 key from URL if possible
                        s3_key = image_url.split("/")[-1] if "/" in image_url else None

                        # MVP Photo Verification: Run Vision API validation on event photos
                        extra_data = {}
                        try:
                            from django.conf import settings

                            import requests

                            from carbon.services.photo_evidence_service import PhotoEvidenceService

                            # Download image from URL for Vision API analysis
                            response = requests.get(image_url, timeout=10)
                            if response.status_code == 200:
                                photo_service = PhotoEvidenceService()
                                # Use content-type header to infer extension if s3_key lacks one
                                filename = s3_key or "photo.jpg"
                                if "." not in filename.rsplit("/", 1)[-1]:
                                    content_type = response.headers.get("Content-Type", "")
                                    ext_map = {
                                        "image/jpeg": ".jpg",
                                        "image/png": ".png",
                                        "image/webp": ".webp",
                                        "image/heic": ".heic",
                                    }
                                    ext = ext_map.get(content_type.split(";")[0].strip(), ".jpg")
                                    filename = f"{filename}{ext}"
                                validation_result = photo_service.validate_and_analyze_photo(
                                    file_data=response.content, filename=filename
                                )
                                # Store Vision API + EXIF metadata in extra_data
                                extra_data = {
                                    "content_validation": validation_result.get("content_validation", "uncertain"),
                                    "content_confidence": validation_result.get("content_confidence", 0),
                                    "agricultural_labels": validation_result.get("agricultural_labels", []),
                                    "content_bypassed": validation_result.get("content_bypassed", False),
                                }
                                # Include EXIF GPS data for verification level upgrade
                                exif = validation_result.get("metadata", {}).get("exif", {})
                                if exif:
                                    if exif.get("gps_latitude"):
                                        extra_data["gps_latitude"] = exif["gps_latitude"]
                                        extra_data["gps_longitude"] = exif.get("gps_longitude")
                                    if exif.get("has_gps"):
                                        extra_data["has_gps"] = True
                                    if exif.get("DateTimeOriginal"):
                                        extra_data["photo_datetime"] = exif["DateTimeOriginal"]
                            else:
                                extra_data = {"content_validation": "uncertain", "content_confidence": 0}
                        except Exception as e:
                            # Default to uncertain if validation fails
                            extra_data = {"content_validation": "uncertain", "content_confidence": 0}

                        gallery_image = gallery.images.create(
                            image_url=image_url, s3_key=s3_key, extra_data=extra_data if extra_data else None
                        )

                    # Associate album with event
                    event.album = gallery

                event.save()

                # Update transparency score after adding event
                try:
                    history.update_trust_metrics()
                except Exception:
                    pass  # Non-fatal: score will update on next calculation

        if created_event is None:
            # Every parcel matched but none had an active production. Answering 201 here
            # would tell the grower their record was saved when nothing was written.
            raise ValidationError(
                {"detail": ["No active production found for the selected parcel. Start a production first."]}
            )

        # Bind the created row to the serializer so the 201 body carries the real id.
        # Without this the response serialises an unsaved instance and returns "id": null.
        serializer.instance = created_event
        # create() cannot reach the serializer after super().create() returns, so stash the row
        # for the completeness-gaps echo on the 201 body.
        self._completeness_event = created_event

    def update(self, request, *args, **kwargs):
        """
        Override update to prevent changing event types after creation
        and to enforce immutability on completed productions.
        """
        # Get the current instance first to determine its type
        instance = self.get_object()

        # Immutability guard: prevent modification of events on completed productions
        history = instance.history
        if history.finish_date is not None or history.published:
            return Response(
                {
                    "error": "Event is locked",
                    "detail": "Events cannot be modified after a production has been completed. "
                    "A finished production is a closed record; reopen it to add events.",
                    "production_id": history.id,
                    "production_finished": history.finish_date is not None,
                    "production_published": history.published,
                },
                status=status.HTTP_423_LOCKED,
            )

        # Audit log for event modification on active production
        try:
            from carbon.models import CarbonAuditLog

            CarbonAuditLog.objects.create(
                user=request.user,
                action="update",
                details=json.dumps(
                    {
                        "event_id": instance.id,
                        "event_type": instance.__class__.__name__,
                        "production_id": history.id,
                    }
                ),
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        except Exception as e:
            logger.warning("Event audit log failed: %s", e)

        # Determine the current event type based on the model
        current_event_type = None
        for event_type_id, event_model in EVENT_TYPE_TO_MODEL.items():
            if isinstance(instance, event_model):
                current_event_type = event_type_id
                break

        # Get the requested event type
        requested_event_type = (
            self.request.data.get("event_type")
            if "event_type" in self.request.data
            else self.request.query_params.get("event_type", None)
        )

        if requested_event_type is not None:
            requested_event_type = int(requested_event_type)

            # Check if user is trying to change the event type
            if current_event_type != requested_event_type:
                return Response(
                    {
                        "error": "Cannot change event type after creation",
                        "detail": f"This event is a {instance.__class__.__name__} and cannot be changed to event type {requested_event_type}",
                        "current_event_type": current_event_type,
                        "requested_event_type": requested_event_type,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Handle deletion of existing images BEFORE the update
        delete_image_ids = request.data.get("delete_image_ids", [])
        if delete_image_ids and hasattr(instance, "album") and instance.album:
            deleted_count = instance.album.images.filter(id__in=delete_image_ids).delete()
            logger.debug("Deleted %d images from album", deleted_count[0])

        # Handle adding NEW images (S3 URLs) - handled here for ALL event types
        album_images = request.data.get("album_images", [])
        if album_images:
            from urllib.parse import urlparse

            from django.conf import settings

            from .models import Gallery

            # Create album if doesn't exist
            if not hasattr(instance, "album") or not instance.album:
                instance.album = Gallery.objects.create()
                instance.save(update_fields=["album"])

            # Add new images to album
            for image_url in album_images:
                # SECURITY: Validate image URL against allowed S3 domains to prevent SSRF
                parsed_url = urlparse(image_url)
                allowed_hosts = set()
                if hasattr(settings, "AWS_STORAGE_BUCKET_NAME") and settings.AWS_STORAGE_BUCKET_NAME:
                    bucket = settings.AWS_STORAGE_BUCKET_NAME
                    region = getattr(settings, "AWS_S3_REGION_NAME", "us-east-1")
                    allowed_hosts.update(
                        {
                            f"{bucket}.s3.amazonaws.com",
                            f"{bucket}.s3.{region}.amazonaws.com",
                            f"s3.amazonaws.com",
                            f"s3.{region}.amazonaws.com",
                        }
                    )
                # Allow local dev URLs (http://localhost) but enforce HTTPS + S3 hosts in production
                is_local_dev = parsed_url.hostname in ("localhost", "127.0.0.1")
                if not is_local_dev and (
                    parsed_url.scheme != "https" or (allowed_hosts and parsed_url.hostname not in allowed_hosts)
                ):
                    logger.warning("Rejected image URL (SSRF protection): %s", image_url)
                    continue

                s3_key = image_url.split("/")[-1] if "/" in image_url else None

                # MVP Photo Verification: Run Vision API validation on event photos
                extra_data = {}
                try:
                    import requests

                    from carbon.services.photo_evidence_service import PhotoEvidenceService

                    # Download image from URL for Vision API analysis
                    response = requests.get(image_url, timeout=10)
                    if response.status_code == 200:
                        photo_service = PhotoEvidenceService()
                        # Use content-type header to infer extension if s3_key lacks one
                        filename = s3_key or "photo.jpg"
                        if "." not in filename.rsplit("/", 1)[-1]:
                            content_type = response.headers.get("Content-Type", "")
                            ext_map = {
                                "image/jpeg": ".jpg",
                                "image/png": ".png",
                                "image/webp": ".webp",
                                "image/heic": ".heic",
                            }
                            ext = ext_map.get(content_type.split(";")[0].strip(), ".jpg")
                            filename = f"{filename}{ext}"
                        validation_result = photo_service.validate_and_analyze_photo(
                            file_data=response.content, filename=filename
                        )
                        # Store Vision API + EXIF metadata in extra_data
                        extra_data = {
                            "content_validation": validation_result.get("content_validation", "uncertain"),
                            "content_confidence": validation_result.get("content_confidence", 0),
                            "agricultural_labels": validation_result.get("agricultural_labels", []),
                            "content_bypassed": validation_result.get("content_bypassed", False),
                        }
                        # Include EXIF GPS data for verification level upgrade
                        # (photo_documented → photo_verified when GPS present)
                        exif = validation_result.get("metadata", {}).get("exif", {})
                        if exif:
                            if exif.get("gps_latitude"):
                                extra_data["gps_latitude"] = exif["gps_latitude"]
                                extra_data["gps_longitude"] = exif.get("gps_longitude")
                            if exif.get("has_gps"):
                                extra_data["has_gps"] = True
                            if exif.get("DateTimeOriginal"):
                                extra_data["photo_datetime"] = exif["DateTimeOriginal"]
                except Exception as e:
                    logger.debug("Vision API validation failed for %s: %s", image_url, e)
                    # Default to uncertain if validation fails
                    extra_data = {"content_validation": "uncertain", "content_confidence": 0}

                instance.album.images.create(
                    image_url=image_url, s3_key=s3_key, extra_data=extra_data if extra_data else None
                )

        # If event types match, proceed with normal update
        response = super().update(request, *args, **kwargs)

        # Update transparency score after modifying event
        try:
            instance.history.update_trust_metrics()
        except Exception:
            pass  # Non-fatal: score will update on next calculation

        if isinstance(instance, ChemicalEvent):
            # `instance` predates super().update()'s save — DRF re-fetched and saved its own
            # copy — so re-read before judging completeness of the row as it now stands.
            instance.refresh_from_db()
        self._attach_completeness_gaps(response, instance)

        return response

    def destroy(self, request, *args, **kwargs):
        """Prevent deletion of events on completed productions."""
        instance = self.get_object()
        history = instance.history
        if history.finish_date is not None or history.published:
            return Response(
                {
                    "error": "Event is locked",
                    "detail": "Events cannot be deleted after a production has been completed. "
                    "A finished production is a closed record; reopen it to add events.",
                    "production_id": history.id,
                },
                status=status.HTTP_423_LOCKED,
            )

        # Audit log for event deletion on active production
        try:
            from carbon.models import CarbonAuditLog

            CarbonAuditLog.objects.create(
                user=request.user,
                action="delete",
                details=json.dumps(
                    {
                        "event_id": instance.id,
                        "event_type": instance.__class__.__name__,
                        "production_id": history.id,
                    }
                ),
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        except Exception as e:
            logger.warning("Event audit log failed: %s", e)

        response = super().destroy(request, *args, **kwargs)

        # Update transparency score after deleting event
        try:
            history.update_trust_metrics()
        except Exception:
            pass  # Non-fatal: score will update on next calculation

        return response

    def _validate_structured_fields(self, event_type, validated_data):
        """
        Enhanced validation for structured fields based on event type
        """
        from rest_framework.serializers import ValidationError

        if event_type == CHEMICAL_EVENT_TYPE:
            # Validate NPK percentages don't exceed 100%
            nitrogen = validated_data.get("nitrogen_percentage", 0) or 0
            phosphorus = validated_data.get("phosphorus_percentage", 0) or 0
            potassium = validated_data.get("potassium_percentage", 0) or 0

            total_npk = nitrogen + phosphorus + potassium
            if total_npk > 100:
                raise ValidationError(f"Total NPK percentages cannot exceed 100%. Current total: {total_npk}%")

            # Validate application method is valid if provided
            app_method = validated_data.get("application_method_structured")
            if app_method and app_method not in ["broadcast", "injection", "foliar", "drip", "banding"]:
                raise ValidationError(
                    f"Invalid application method: {app_method}. Must be one of: broadcast, injection, foliar, drip, banding"
                )

        elif event_type == EQUIPMENT_EVENT_TYPE:
            # Validate fuel consumed is positive
            fuel_consumed = validated_data.get("fuel_consumed")
            if fuel_consumed is not None and fuel_consumed < 0:
                raise ValidationError("Fuel consumed cannot be negative")

            # Validate hours operated is positive
            hours_operated = validated_data.get("hours_operated")
            if hours_operated is not None and hours_operated < 0:
                raise ValidationError("Hours operated cannot be negative")

            # Validate efficiency rating
            efficiency = validated_data.get("operation_efficiency")
            if efficiency and efficiency not in ["high", "normal", "low"]:
                raise ValidationError(f"Invalid efficiency rating: {efficiency}. Must be one of: high, normal, low")

        elif event_type == PRODUCTION_EVENT_TYPE:
            # Validate area covered is positive
            # Equipment Maintenance (EM), Pollination (PO), and Post-Harvest Processing (PH)
            # can legitimately have area_covered=0 (facility/equipment-based, not field-based).
            production_type = validated_data.get("type", "")
            area_covered = validated_data.get("area_covered")
            if area_covered is not None and area_covered <= 0 and production_type not in ("EM", "PO", "PH"):
                raise ValidationError("Area covered must be greater than 0")

            # Validate yield amount is positive
            yield_amount = validated_data.get("yield_amount")
            if yield_amount is not None and yield_amount < 0:
                raise ValidationError("Yield amount cannot be negative")

            # Validate transportation distance is not negative
            transport_distance = validated_data.get("transportation_distance")
            if transport_distance is not None and transport_distance < 0:
                raise ValidationError("Transportation distance cannot be negative")

        elif event_type == BUSINESS_EVENT_TYPE:
            # Validate carbon credits earned is not negative
            carbon_credits = validated_data.get("carbon_credits_earned")
            if carbon_credits is not None and carbon_credits < 0:
                raise ValidationError("Carbon credits earned cannot be negative")

            # Validate investment amount is not negative
            investment = validated_data.get("investment_amount")
            if investment is not None and investment < 0:
                raise ValidationError("Investment amount cannot be negative")

            # Validate business type.
            #
            # This list used to be hardcoded here and had drifted from the model: it omitted
            # `verification`, `compliance` and `transparency`, which are three of the six options
            # BusinessTab actually offers and are all present in
            # BusinessEvent.BUSINESS_ACTIVITY_CHOICES. A farmer choosing "Third-Party
            # Verification Completed", "Regulatory Compliance Achieved" or "Transparency
            # Initiative Launched" got a 400 and could not save at all — half the business event
            # types were unusable through the UI, while seed commands writing the model directly
            # bypassed this check and produced rows the form could never have created.
            #
            # Derive from the model so the two cannot drift again, and keep the extra legacy
            # values this endpoint has always accepted so any other client stays working.
            business_type = validated_data.get("business_type")
            _LEGACY_BUSINESS_TYPES = [
                "green_investment",
                "supply_chain",
                "consumer_engagement",
                "regulatory_compliance",
                "carbon_offset",
                "sustainability_training",
                "eco_certification",
            ]
            valid_business_types = [
                code for code, _label in BusinessEvent.BUSINESS_ACTIVITY_CHOICES
            ] + _LEGACY_BUSINESS_TYPES
            if business_type and business_type not in valid_business_types:
                raise ValidationError(
                    f"Invalid business type: {business_type}. Must be one of: {', '.join(valid_business_types)}"
                )

    @action(detail=False, methods=["get"], url_path="structured-field-options")
    def structured_field_options(self, request):
        """
        API endpoint to get available options for structured fields
        """
        options = {
            "chemical_event": {
                "application_methods": [
                    {"value": "broadcast", "label": "Broadcast/Spread"},
                    {"value": "injection", "label": "Injection/Banding"},
                    {"value": "foliar", "label": "Foliar Spray"},
                    {"value": "drip", "label": "Drip/Fertigation"},
                    {"value": "banding", "label": "Banding/Placement"},
                ]
            },
            "equipment_event": {
                "efficiency_ratings": [
                    {"value": "high", "label": "High Efficiency"},
                    {"value": "normal", "label": "Normal Efficiency"},
                    {"value": "low", "label": "Low Efficiency"},
                ],
                "fuel_units": [
                    {"value": "L", "label": "Liters"},
                    {"value": "gal", "label": "Gallons"},
                ],
            },
            "production_event": {
                "area_units": [
                    {"value": "ha", "label": "Hectares"},
                    {"value": "acre", "label": "Acres"},
                ],
                "yield_units": [
                    {"value": "kg", "label": "Kilograms"},
                    {"value": "lb", "label": "Pounds"},
                    {"value": "ton", "label": "Tons"},
                ],
                "efficiency_ratings": [
                    {"value": "high", "label": "High Efficiency"},
                    {"value": "normal", "label": "Normal Efficiency"},
                    {"value": "low", "label": "Low Efficiency"},
                ],
            },
            "business_event": {
                "business_types": [
                    {"value": "certification", "label": "Certification Event (Organic, Carbon, etc.)"},
                    {"value": "carbon_credits", "label": "Carbon Credits Transaction"},
                    {"value": "sustainability_audit", "label": "Sustainability Audit/Assessment"},
                    {"value": "green_investment", "label": "Green Technology Investment"},
                    {"value": "supply_chain", "label": "Supply Chain Optimization"},
                    {"value": "consumer_engagement", "label": "Consumer Engagement Initiative"},
                    {"value": "regulatory_compliance", "label": "Regulatory Compliance"},
                    {"value": "carbon_offset", "label": "Carbon Offset Purchase"},
                    {"value": "sustainability_training", "label": "Sustainability Training"},
                    {"value": "eco_certification", "label": "Eco-Certification Process"},
                ]
            },
        }
        return Response(options)

    @action(detail=False, methods=["post"], url_path="validate-structured-fields")
    def validate_structured_fields(self, request):
        """
        Validate structured field data without creating an event.
        Useful for real-time form validation in the frontend.
        """
        try:
            event_type = request.data.get("event_type")
            if event_type is None:
                return Response({"error": "event_type is required"}, status=status.HTTP_400_BAD_REQUEST)

            # Validate the structured fields
            try:
                self._validate_structured_fields(int(event_type), request.data)
                return Response({"valid": True, "message": "All structured fields are valid"})
            except Exception as e:
                return Response(
                    {
                        "valid": False,
                        "error": str(e),
                        "field_errors": getattr(e, "detail", {}) if hasattr(e, "detail") else {},
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            return Response({"error": f"Validation error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BuyerDocRequestViewSet(viewsets.GenericViewSet):
    """
    Phase 4 — buyer documentation requests ("leads").

    create: PUBLIC (proof-view CTA). Body: production_id (public UUID),
            requester_name, requester_email, organization?, message?.
            Bot-checked, deduplicated (same email + production within 24h
            returns the existing request), IP stored as hash only.
    list:   OWNER (CA/FM via WorksIn). ?establishment_id= required.
    partial_update: OWNER. Status transitions only (new/contacted/closed).
    """

    queryset = BuyerDocRequest.objects.select_related(
        "production", "production__product", "production__parcel__establishment"
    )

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsAuthenticated()]

    def create(self, request):
        from django.core.exceptions import ValidationError as DjangoValidationError

        from .serializers import BuyerDocRequestCreateSerializer
        from .services.bot_detection_service import BotDetectionService
        from .services.privacy_service import PrivacyService

        production_public_id = request.data.get("production_id")
        if not production_public_id:
            return Response({"error": "production_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        should_block, reason = BotDetectionService.should_block_request(request, request.data)
        if should_block:
            return Response({"error": "Request blocked"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        try:
            production = History.objects.select_related("parcel__establishment__company").get(
                public_id=production_public_id, published=True
            )
        except (History.DoesNotExist, DjangoValidationError, ValueError):
            return Response({"error": "Production not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = BuyerDocRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["requester_email"].strip().lower()

        # Idempotency: same buyer asking about the same lot within 24h is one
        # lead, not N notifications.
        existing = BuyerDocRequest.objects.filter(
            production=production,
            requester_email__iexact=email,
            created_at__gte=timezone.now() - timedelta(hours=24),
        ).first()
        if existing:
            return Response(
                {"id": existing.id, "message": "Request already received", "duplicate": True},
                status=status.HTTP_200_OK,
            )

        raw_ip = PrivacyService.get_client_ip(request)
        doc_request = serializer.save(
            production=production,
            requester_email=email,
            ip_hash=PrivacyService.hash_ip(raw_ip) if raw_ip else "",
        )

        self._notify_company_admins(doc_request, production)

        return Response(
            {"id": doc_request.id, "message": "Request received", "duplicate": False},
            status=status.HTTP_201_CREATED,
        )

    def _notify_company_admins(self, doc_request, production):
        """In-app notification to company admins — failure must not break the lead."""
        try:
            from notifications.services import NotificationService
            from users.models import WorksIn

            company = production.parcel.establishment.company
            admins = WorksIn.objects.filter(company=company, role="CA").select_related("user")
            product_name = production.product.name if production.product else "your product"
            org = f" ({doc_request.organization})" if doc_request.organization else ""
            service = NotificationService()
            for works_in in admins:
                service.create_notification(
                    recipient=works_in.user,
                    notification_type="system_alert",
                    title="Buyer documentation request",
                    message=(
                        f"{doc_request.requester_name}{org} requested supplier documentation " f"for {product_name}."
                    ),
                    priority="high",
                    related_object=doc_request,
                    extra_data={
                        "buyer_email": doc_request.requester_email,
                        "organization": doc_request.organization,
                        "production_id": production.id,
                        "production_public_id": str(production.public_id),
                        "establishment_id": production.parcel.establishment_id,
                    },
                )
        except Exception:
            logger.error("Buyer doc-request notification failed", exc_info=True)

    def list(self, request):
        from company.models import Establishment
        from users.models import WorksIn

        from .serializers import BuyerDocRequestSerializer

        establishment_id = request.query_params.get("establishment_id")
        if not establishment_id:
            return Response({"error": "establishment_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            establishment = Establishment.objects.get(id=establishment_id)
        except Establishment.DoesNotExist:
            return Response({"error": "Establishment not found"}, status=status.HTTP_404_NOT_FOUND)

        has_access = WorksIn.objects.filter(
            user=request.user, company=establishment.company, role__in=["CA", "FM"]
        ).exists()
        if not has_access:
            return Response({"error": "Access denied to this establishment"}, status=status.HTTP_403_FORBIDDEN)

        leads = self.get_queryset().filter(production__parcel__establishment=establishment)
        status_filter = request.query_params.get("status")
        if status_filter in {"new", "contacted", "closed"}:
            leads = leads.filter(status=status_filter)

        return Response(BuyerDocRequestSerializer(leads[:200], many=True).data, status=status.HTTP_200_OK)

    def partial_update(self, request, pk=None):
        from users.models import WorksIn

        from .serializers import BuyerDocRequestSerializer

        try:
            lead = self.get_queryset().get(pk=pk)
        except BuyerDocRequest.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        has_access = WorksIn.objects.filter(
            user=request.user,
            company=lead.production.parcel.establishment.company,
            role__in=["CA", "FM"],
        ).exists()
        if not has_access:
            return Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)

        new_status = request.data.get("status")
        if new_status not in {"new", "contacted", "closed"}:
            return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)

        lead.status = new_status
        lead.save(update_fields=["status"])
        return Response(BuyerDocRequestSerializer(lead).data, status=status.HTTP_200_OK)


class SalesRecordViewSet(viewsets.GenericViewSet):
    """
    Owner-gated sales records per production lot (SOE traceback:
    "crop and quantity sold, date of sale, buyer" — verified at every
    annual inspection). list/create/destroy only; never public.
    """

    permission_classes = [IsAuthenticated]
    queryset = SalesRecord.objects.select_related("production__parcel__establishment__company")

    def _production_for(self, request, production_public_id):
        from django.core.exceptions import ValidationError as DjangoValidationError

        from users.models import WorksIn

        try:
            production = History.objects.select_related("parcel__establishment__company").get(
                public_id=production_public_id
            )
        except (History.DoesNotExist, ValueError, DjangoValidationError):
            # ValueError/ValidationError cover malformed UUID strings.
            return None, Response({"error": "Production not found"}, status=status.HTTP_404_NOT_FOUND)

        has_access = WorksIn.objects.filter(
            user=request.user,
            company=production.parcel.establishment.company,
            role__in=["CA", "FM"],
        ).exists()
        if not has_access:
            return None, Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)
        return production, None

    def list(self, request):
        from .serializers import SalesRecordSerializer

        production_public_id = request.query_params.get("production_id")
        if not production_public_id:
            return Response({"error": "production_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        production, err = self._production_for(request, production_public_id)
        if err:
            return err
        records = self.get_queryset().filter(production=production)
        return Response(SalesRecordSerializer(records, many=True).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="harvest_lots")
    def harvest_lots(self, request):
        """The production's harvest passes, so a sale can name the lot(s) it drew from.

        Lives here rather than on the public history payload because the lot code is an
        OWNER-side identifier: it links a buyer to a block and a date (7 CFR 205.103(b)(2)),
        which is a record for the operator and their certifier, not a consumer claim — the
        public serializer deliberately omits it, so the sales editor had no source for the
        picker until this existed.

        Reuses `_production_for`, i.e. the same CA/FM company-role gate as the sales list. A
        second, looser path to the same rows is how a lot list becomes a farm directory.
        """
        production_public_id = request.query_params.get("production_id")
        if not production_public_id:
            return Response({"error": "production_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        production, err = self._production_for(request, production_public_id)
        if err:
            return err

        lots = [
            {
                "id": event.id,
                "lot_code": event.harvest_lot_code,
                "date": event.date,
                "yield_quantity": event.yield_quantity,
                "yield_unit": event.yield_unit,
            }
            # A harvest with no code is one whose crop AND block are both blank — nothing an
            # inspector could trace to, and nothing worth offering as a link target.
            for event in production.history_productionevent_events.filter(type="HA")
            .exclude(harvest_lot_code__isnull=True)
            .exclude(harvest_lot_code="")
            .order_by("date", "id")
        ]
        return Response(lots, status=status.HTTP_200_OK)

    def create(self, request):
        from .serializers import SalesRecordSerializer

        production_public_id = request.data.get("production_id")
        if not production_public_id:
            return Response({"error": "production_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        production, err = self._production_for(request, production_public_id)
        if err:
            return err
        serializer = SalesRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save(production=production)
        return Response(SalesRecordSerializer(record).data, status=status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        try:
            record = self.get_queryset().get(pk=pk)
        except SalesRecord.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        from users.models import WorksIn

        has_access = WorksIn.objects.filter(
            user=request.user,
            company=record.production.parcel.establishment.company,
            role__in=["CA", "FM"],
        ).exists()
        if not has_access:
            return Response({"error": "Access denied"}, status=status.HTTP_403_FORBIDDEN)
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
