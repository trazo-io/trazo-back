from datetime import datetime, timedelta

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone

from dateutil import parser as date_parser
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from backend.permissions import CompanyNestedViewSet
from notifications.services import notification_service
from product.models import Parcel, Product
from reviews.models import Review

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
from .models import BusinessEvent, ChemicalEvent, GeneralEvent, History, HistoryScan, ProductionEvent
from .serializers import (
    BusinessEventSerializer,
    ChemicalEventSerializer,
    EquipmentEventSerializer,
    GeneralEventSerializer,
    HistorySerializer,
    ListHistoryClassSerializer,
    OptimizedHistoryListSerializer,
    PestManagementEventSerializer,
    ProductionEventSerializer,
    PublicHistorySerializer,
    SoilManagementEventSerializer,
    UpdateChemicalEventSerializer,
    UpdateEquipmentEventSerializer,
    UpdateGeneralEventSerializer,
    UpdatePestManagementEventSerializer,
    UpdateProductionEventSerializer,
    UpdateSoilManagementEventSerializer,
    UpdateWeatherEventSerializer,
    WeatherEventSerializer,
)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class HistoryViewSet(viewsets.ModelViewSet):
    serializer_class = HistorySerializer
    filter_backends = [filters.OrderingFilter]

    def get_serializer_class(self):
        if self.action == "create" or self.action == "update" or self.action == "partial_update":
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
            return History.objects.filter(published=True)
        elif self.action == "my_scans":
            return (
                History.objects.filter(history_scans__user=self.request.user)
                .select_related("product", "parcel__establishment")
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
        queryset = (
            History.objects.select_related("product", "parcel", "crop_type")
            .only(
                # Only fetch absolutely essential fields for the dashboard
                "id",
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
                "product__id",
                "product__name",
                "parcel__id",
                "parcel__name",
                "crop_type__id",
                "crop_type__name",
                "crop_type__category",
                "crop_type__slug",
            )
            .order_by("-start_date")
        )

        # Filter by parcel if parcel_pk is provided
        if parcel_pk:
            queryset = queryset.filter(parcel_id=parcel_pk)

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
            print(f"Slow history query detected: {query_time:.2f}s for parcel {self.kwargs.get('parcel_pk')}")

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """Override update to invalidate cache."""
        response = super().update(request, *args, **kwargs)

        # Invalidate cache for this parcel's history list
        parcel_id = self.kwargs.get("parcel_pk")
        if parcel_id:
            cache_key = f"history_list_parcel_{parcel_id}_v3"
            cache.delete(cache_key)

        return response

    def destroy(self, request, *args, **kwargs):
        """Override destroy to invalidate cache."""
        # Get parcel_id before deletion
        parcel_id = self.kwargs.get("parcel_pk")

        response = super().destroy(request, *args, **kwargs)

        # Invalidate cache for this parcel's history list
        if parcel_id:
            cache_key = f"history_list_parcel_{parcel_id}_v3"
            cache.delete(cache_key)

        return response

    def create(self, request):
        data = request.data
        parcel = Parcel.objects.get(id=data["parcel"])
        product = data["product"]
        obj, created = Product.objects.get_or_create(name=product["name"])
        type = data["type"]
        age_of_plants = data["age_of_plants"]
        number_of_plants = data["number_of_plants"]
        soil_ph = data["soil_ph"]
        is_outdoor = data["is_outdoor"]
        extra_data = {
            "age_of_plants": age_of_plants,
            "number_of_plants": number_of_plants,
            "soil_ph": soil_ph,
            "is_outdoor": is_outdoor,
        }
        history = History.objects.create(
            start_date=data["start_date"],
            parcel=parcel,
            product=obj,
            extra_data=extra_data,
            type=type,
        )
        parcel.current_history = history
        parcel.save()
        serializer = HistorySerializer(history)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="start-production", permission_classes=[IsAuthenticated])
    def start_production(self, request):
        """
        Enhanced production creation endpoint with crop selection and blockchain integration.
        Supports Step 7 implementation from TRAZO_FOCUSED_IMPLEMENTATION_PLAN_FINAL.md
        """
        try:
            data = request.data

            # Validate required fields
            required_fields = ["name", "parcel_id", "crop_type", "start_date"]
            for field in required_fields:
                if field not in data:
                    return Response({"error": f"Missing required field: {field}"}, status=status.HTTP_400_BAD_REQUEST)

            # Get parcel and validate ownership
            try:
                parcel = Parcel.objects.get(id=data["parcel_id"])
                # Add permission check here if needed
                # if not user has access to this parcel...
            except Parcel.DoesNotExist:
                return Response({"error": "Parcel not found"}, status=status.HTTP_404_NOT_FOUND)

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
                "production_method": data.get("production_method", "conventional"),
                "estimated_yield": data.get("estimated_yield"),
                "irrigation_method": data.get("irrigation_method"),
                "created_via": "production_start_form",
                "blockchain_enabled": True,  # Enable blockchain for new productions
            }

            # Add optional fields to extra_data
            optional_fields = ["age_of_plants", "number_of_plants", "soil_ph", "is_outdoor", "notes"]
            for field in optional_fields:
                if data.get(field):
                    extra_data[field] = data[field]

            history = History.objects.create(
                name=data["name"],
                start_date=start_date,
                finish_date=expected_harvest,
                parcel=parcel,
                product=product,
                crop_type=crop_type,  # Assign the CropType instance
                extra_data=extra_data,
                type=data.get("type", "OR"),  # Default to Orchard
                description=data.get("description", ""),
                operator=request.user if request.user.is_authenticated else None,
            )

            # Update parcel's current history
            parcel.current_history = history
            parcel.save()

            # Invalidate cache for this parcel's history list
            cache_key = f"history_list_parcel_{parcel.id}_v3"
            cache.delete(cache_key)

            # Process template events if provided
            if data.get("template_events"):
                self._create_template_events(history, data["template_events"])

            # Create initial blockchain record for this production
            try:
                from carbon.services.blockchain import blockchain_service

                initial_carbon_data = {
                    "production_id": history.id,
                    "total_emissions": 0.0,
                    "total_offsets": 0.0,
                    "crop_type": crop_type.name,
                    "calculation_method": "initial_production_setup",
                    "usda_verified": False,
                    "timestamp": int(start_date.timestamp()),
                    "carbon_score": 50,  # Initial neutral score
                    "industry_percentile": 50,
                }

                blockchain_result = blockchain_service.create_carbon_record(history.id, initial_carbon_data)

                # Store blockchain reference in extra_data
                history.extra_data["blockchain_transaction"] = blockchain_result.get("transaction_hash")
                history.extra_data["blockchain_verified"] = blockchain_result.get("blockchain_verified", False)
                history.save()

            except Exception as e:
                print(f"Error creating initial blockchain record: {e}")
                # Continue without blockchain - not critical for production creation

            # Serialize and return the created production
            serializer = HistorySerializer(history)
            response_data = serializer.data

            # Add additional metadata for the frontend
            response_data.update(
                {
                    "crop_category": extra_data.get("crop_category"),
                    "blockchain_enabled": extra_data.get("blockchain_enabled", False),
                    "blockchain_transaction": extra_data.get("blockchain_transaction"),
                    "qr_code_url": history.qr_code.url if history.qr_code else None,
                    "establishment": {
                        "id": parcel.establishment.id,
                        "name": parcel.establishment.name,
                        "location": parcel.establishment.get_location(),
                    },
                    "parcel": {"id": parcel.id, "name": parcel.name, "area": parcel.area},
                }
            )

            return Response(response_data, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response({"error": f"Invalid date format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            print(f"Error creating production: {e}")
            import traceback

            traceback.print_exc()
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

    def _create_template_events(self, history, template_events):
        """Helper method to create events from template data"""
        from datetime import datetime

        from django.utils import timezone

        # Get current event count once
        current_event_count = 0

        for event_data in template_events:
            if not event_data.get("enabled", True):
                continue

            try:
                # Parse the scheduled date
                scheduled_date_str = event_data.get("scheduled_date")
                if scheduled_date_str:
                    scheduled_date = datetime.fromisoformat(scheduled_date_str.replace("Z", "+00:00"))
                    if scheduled_date.tzinfo is None:
                        scheduled_date = timezone.make_aware(scheduled_date)
                else:
                    scheduled_date = timezone.now()

                # Increment index for each event
                current_event_count += 1

                # Determine event type based on name
                event_name = event_data.get("name", "").lower()

                # Create appropriate event type
                if "pruning" in event_name:
                    ProductionEvent.objects.create(
                        history=history,
                        description=f"{event_data.get('name', 'Production Event')}: {event_data.get('efficiency_tips', '')}",
                        date=scheduled_date,
                        type=ProductionEvent.PRUNING,
                        index=current_event_count,
                        created_by=history.operator,
                    )
                elif "harvest" in event_name:
                    ProductionEvent.objects.create(
                        history=history,
                        description=f"{event_data.get('name', 'Production Event')}: {event_data.get('efficiency_tips', '')}",
                        date=scheduled_date,
                        type=ProductionEvent.HARVESTING,
                        index=current_event_count,
                        created_by=history.operator,
                    )
                elif "irrigation" in event_name:
                    ProductionEvent.objects.create(
                        history=history,
                        description=f"{event_data.get('name', 'Production Event')}: {event_data.get('efficiency_tips', '')}",
                        date=scheduled_date,
                        type=ProductionEvent.IRRIGATION,
                        index=current_event_count,
                        created_by=history.operator,
                    )
                elif "fertiliz" in event_name:
                    # Create as Chemical Event for fertilization
                    ChemicalEvent.objects.create(
                        history=history,
                        description=f"{event_data.get('name', 'Chemical Event')}: {event_data.get('efficiency_tips', '')}",
                        date=scheduled_date,
                        type=ChemicalEvent.FERTILIZER,
                        commercial_name=(
                            event_data.get("carbon_sources", ["Unknown"])[0]
                            if event_data.get("carbon_sources")
                            else "Unknown"
                        ),
                        volume=event_data.get("typical_amounts", {}).get("fertilizer", "Unknown"),
                        index=current_event_count,
                        created_by=history.operator,
                    )
                else:
                    # Create as General Event for other types
                    GeneralEvent.objects.create(
                        history=history,
                        name=event_data.get("name", "General Event"),
                        description=f"{event_data.get('name', 'General Event')}: {event_data.get('efficiency_tips', '')}",
                        date=scheduled_date,
                        index=current_event_count,
                        created_by=history.operator,
                    )

            except Exception as e:
                print(f"Error creating template event {event_data.get('name', 'Unknown')}: {e}")
                # Continue with other events even if one fails
                continue

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def public_history(self, request, pk=None):
        queryset = self.get_queryset()
        history = get_object_or_404(queryset, pk=pk)
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(",")[0]
        else:
            ip_address = request.META.get("HTTP_X_REAL_IP")

        city = None
        country = None

        # Get city and country from IP using free API (no GDAL required)
        if ip_address:
            try:
                import requests

                # Using ipapi.co - free tier allows 1000 requests/day
                response = requests.get(f"https://ipapi.co/{ip_address}/json/", timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    city = data.get("city")
                    country = data.get("country_name")
            except Exception as e:
                # If geolocation fails, continue without it
                print(f"IP geolocation failed: {e}")

        history_scan = HistoryScan.objects.create(
            history=history,
            user=request.user if request.user.is_authenticated else None,
            ip_address=ip_address,
            city=city,
            country=country,
        )

        # Send notification to product owner about the scan
        try:
            # Get the company and find company admins via WorksIn relationship
            company = history.parcel.establishment.company
            scanner = request.user if request.user.is_authenticated else None

            # Get company admins (users with 'CA' role)
            from users.models import WorksIn

            company_admins = WorksIn.objects.filter(company=company, role="CA").select_related(  # Company Admin role
                "user"
            )

            # Send notification to all company admins who are not the scanner
            for admin_relation in company_admins:
                product_owner = admin_relation.user

                # Only send notification if scanner is different from product owner
                if scanner != product_owner:
                    # Get product name
                    product_name = history.product.name if history.product else f"Production {history.id}"

                    # Get scan location
                    scan_location = None
                    if city and country:
                        scan_location = f"{city}, {country}"
                    elif country:
                        scan_location = country

                    # Create notification
                    notification_service.create_product_scan_notification(
                        product_owner=product_owner,
                        scanner=scanner,
                        product_name=product_name,
                        scan_location=scan_location,
                    )
        except Exception as e:
            # Log error but don't break the scan functionality
            print(f"Error creating scan notification: {e}")
        similar_histories = (
            History.objects.filter(
                parcel__establishment__company=history.parcel.establishment.company,
                published=True,
            )
            .exclude(id=history.id)
            .select_related("product", "parcel__establishment")
            .order_by("-id")[:5]
        )
        serializer = PublicHistorySerializer(
            history,
            context={"history_scan": history_scan.id, "similar_histories": similar_histories, "request": request},
        )
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def my_scans(self, request):
        queryset = self.get_queryset()
        scans_data = []
        for history in queryset:
            latest_scan = history.history_scans.filter(user=request.user).order_by("-date").first()
            if latest_scan:
                scans_data.append(PublicHistorySerializer(history, context={"history_scan": latest_scan.id}).data)
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

        # Get scans for the establishment
        scans_queryset = (
            HistoryScan.objects.filter(
                history__parcel__establishment_id=establishment_id,
                history__parcel__establishment__company_id=company_id,
            )
            .select_related("history", "history__product", "history__parcel", "history__parcel__establishment", "user")
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

        # Apply search filtering if provided
        search = request.query_params.get("search")
        if search:
            from django.db.models import Q

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
                    "location": (
                        f"{scan.city}, {scan.country}"
                        if scan.city and scan.country
                        else scan.country or scan.city or "Unknown"
                    ),
                    "parcel": scan.history.parcel.name if scan.history.parcel else None,
                    "parcel_id": scan.history.parcel.id if scan.history.parcel else None,
                    "comment": getattr(scan, "comment", ""),
                    "user": scan.user.get_full_name() if scan.user else "Anonymous",
                    "ip_address": scan.ip_address,
                    "qr_code": scan.history.qr_code.url if scan.history.qr_code else None,
                    "carbon_score": getattr(scan.history, "carbon_score", 0),
                    "production_period": scan.history.period if hasattr(scan.history, "period") else None,
                }
                scans_data.append(scan_data)

            return paginator.get_paginated_response(scans_data)

        return Response([])

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
        Generate secure presigned URL for QR code download.
        Enterprise-grade solution following 2025 best practices.
        """
        from django.conf import settings

        from common.aws_utils import SecureAWSClient

        try:
            # Get the history object
            history = self.get_object()

            # Check if QR code exists
            if not history.qr_code or not history.qr_code.name:
                return Response({"error": "QR code not found for this production"}, status=status.HTTP_404_NOT_FOUND)

            # Generate presigned URL (expires in 1 hour)
            s3_client = SecureAWSClient.get_s3_client()
            presigned_url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": history.qr_code.name},
                ExpiresIn=3600,  # 1 hour expiration
            )

            # Generate friendly filename
            filename = f"{history.name.replace(' ', '_')}_QR.png"

            return Response(
                {
                    "download_url": presigned_url,
                    "filename": filename,
                    "expires_in": 3600,
                    "expires_at": (timezone.now() + timedelta(seconds=3600)).isoformat(),
                    "production_name": history.name,
                    "message": "Secure download URL generated successfully",
                }
            )

        except Exception as e:
            return Response(
                {"error": f"Error generating download URL: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PublicHistoryScanViewSet(viewsets.ModelViewSet):
    """
    Enhanced public scan endpoint with 2025 security, privacy & performance standards
    Handles QR scans, page views, and consumer feedback with GDPR compliance
    """

    queryset = HistoryScan.objects.select_related(
        "history", "history__product", "history__parcel", "history__parcel__establishment", "user"
    ).all()
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
        print(f"🚀 SCAN CREATE METHOD CALLED - VERY START")
        print(f"  - Method: {request.method}")
        print(f"  - Path: {request.path}")
        print(f"  - User-Agent: {request.META.get('HTTP_USER_AGENT', 'None')}")
        print(f"  - Request data: {request.data}")
        print(f"  - Cookies: {request.COOKIES}")
        print(f"  - Headers: {request.META.keys()}")

        try:
            # Input validation
            validation_result = self._validate_scan_request(request)
            if validation_result:
                return validation_result

            production_id = request.data.get("production_id")

            # Get the production/history with validation
            try:
                history = History.objects.select_related("parcel__establishment__company", "product").get(
                    id=production_id
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

            # Process privacy and consent data with comprehensive debugging
            print(f"🔍 Backend consent validation for request:")
            print(f"  - Request cookies: {request.COOKIES}")
            print(f"  - All headers: {dict(request.META)}")
            print(f"  - Request data: {request.data}")

            privacy_data = self.privacy_service.process_scan_consent(request)
            print(f"🔍 Privacy service returned: {privacy_data}")

            # Check for consent requirement
            consent_required = self.privacy_service.is_consent_required(request)
            consent_given = privacy_data["consent_given"]

            print(f"🔍 Consent validation:")
            print(f"  - Consent required: {consent_required}")
            print(f"  - Consent given: {consent_given}")
            print(f"  - Will block: {consent_required and not consent_given}")

            if consent_required and not consent_given:
                print(f"🚫 Blocking request - consent required but not given")
                return Response(
                    {
                        "error": "Analytics consent required",
                        "consent_required": True,
                        "message": "To help improve carbon transparency, please allow analytics tracking",
                    },
                    status=status.HTTP_428_PRECONDITION_REQUIRED,
                )

            print(f"✅ Consent validation passed - proceeding with scan creation")

            # Session deduplication check
            is_duplicate, original_scan, dedup_method = self.deduplication_service.check_comprehensive_duplicate(
                privacy_data["session_hash"], privacy_data["ip_hash"], production_id
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

        # Validate production_id format
        try:
            int(production_id)
        except (ValueError, TypeError):
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
        history_scans = HistoryScan.objects.filter(
            history__parcel__establishment=self.establishment,
            **date_kwargs,
        ).order_by("-date")
        if parcel is not None:
            history_scans = history_scans.filter(history__parcel__id=parcel)
        if product is not None:
            history_scans = history_scans.filter(history__product__id=product)
        if production is not None:
            history_scans = history_scans.filter(history__id=production)
        return Response(ListHistoryClassSerializer(history_scans[0:9], many=True, context={"history_scan": True}).data)


class EventViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    filter_backends = [filters.OrderingFilter]

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

        is_mutation = self.action in ["create", "update", "partial_update"]

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
            return BusinessEventSerializer  # Same serializer for read/write operations
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
        Override retrieve to handle event_type determination
        """
        instance = self.get_object()

        # If we determined the event type during get_object, update the serializer
        if hasattr(self, "_determined_event_type"):
            # Force re-evaluation of serializer class with correct event type
            event_type = self._determined_event_type

            # Get the correct serializer class
            if event_type == WEATHER_EVENT_TYPE:
                serializer_class = WeatherEventSerializer
            elif event_type == PRODUCTION_EVENT_TYPE:
                serializer_class = ProductionEventSerializer
            elif event_type == CHEMICAL_EVENT_TYPE:
                serializer_class = ChemicalEventSerializer
            elif event_type == EQUIPMENT_EVENT_TYPE:
                serializer_class = EquipmentEventSerializer
            elif event_type == SOIL_MANAGEMENT_EVENT_TYPE:
                serializer_class = SoilManagementEventSerializer
            elif event_type == PEST_MANAGEMENT_EVENT_TYPE:
                serializer_class = PestManagementEventSerializer
            elif event_type == BUSINESS_EVENT_TYPE:
                serializer_class = BusinessEventSerializer
            else:  # GENERAL_EVENT_TYPE
                serializer_class = GeneralEventSerializer

            serializer = serializer_class(instance)
            return Response(serializer.data)

        # Default behavior
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        parcels = self.request.POST.getlist("parcels", None)
        event_type = self.request.data.get("event_type", None)
        if event_type is None:
            raise Exception("Event type is required")
        if parcels is None or parcels is []:
            raise Exception("Parcel is required")
        
        # Enhanced validation for structured fields
        self._validate_structured_fields(int(event_type), serializer.validated_data)
        
        parcels = Parcel.objects.filter(id__in=[int(parcel) for parcel in parcels]).select_related("current_history")

        for parcel in parcels:
            if parcel.current_history is not None:
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

                event_model = EVENT_TYPE_TO_MODEL.get(int(event_type), GeneralEvent)
                event = event_model.objects.create(
                    history=history,
                    index=index,
                    created_by=self.request.user,
                    **serializer.validated_data,
                )
                event.save()

    def update(self, request, *args, **kwargs):
        """
        Override update to prevent changing event types after creation
        """
        # Get the current instance first to determine its type
        instance = self.get_object()

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

        # If event types match, proceed with normal update
        return super().update(request, *args, **kwargs)

    def _validate_structured_fields(self, event_type, validated_data):
        """
        Enhanced validation for structured fields based on event type
        """
        from rest_framework.serializers import ValidationError
        
        if event_type == CHEMICAL_EVENT_TYPE:
            # Validate NPK percentages don't exceed 100%
            nitrogen = validated_data.get('nitrogen_percentage', 0) or 0
            phosphorus = validated_data.get('phosphorus_percentage', 0) or 0
            potassium = validated_data.get('potassium_percentage', 0) or 0
            
            total_npk = nitrogen + phosphorus + potassium
            if total_npk > 100:
                raise ValidationError(
                    f"Total NPK percentages cannot exceed 100%. Current total: {total_npk}%"
                )
            
            # Validate application method is valid if provided
            app_method = validated_data.get('application_method_structured')
            if app_method and app_method not in ['broadcast', 'injection', 'foliar', 'drip', 'banding']:
                raise ValidationError(
                    f"Invalid application method: {app_method}. Must be one of: broadcast, injection, foliar, drip, banding"
                )
                
        elif event_type == EQUIPMENT_EVENT_TYPE:
            # Validate fuel consumed is positive
            fuel_consumed = validated_data.get('fuel_consumed')
            if fuel_consumed is not None and fuel_consumed < 0:
                raise ValidationError("Fuel consumed cannot be negative")
            
            # Validate hours operated is positive
            hours_operated = validated_data.get('hours_operated')
            if hours_operated is not None and hours_operated < 0:
                raise ValidationError("Hours operated cannot be negative")
            
            # Validate efficiency rating
            efficiency = validated_data.get('operation_efficiency')
            if efficiency and efficiency not in ['high', 'normal', 'low']:
                raise ValidationError(
                    f"Invalid efficiency rating: {efficiency}. Must be one of: high, normal, low"
                )
                
        elif event_type == PRODUCTION_EVENT_TYPE:
            # Validate area covered is positive
            area_covered = validated_data.get('area_covered')
            if area_covered is not None and area_covered <= 0:
                raise ValidationError("Area covered must be greater than 0")
            
            # Validate yield amount is positive
            yield_amount = validated_data.get('yield_amount')
            if yield_amount is not None and yield_amount < 0:
                raise ValidationError("Yield amount cannot be negative")
            
            # Validate transportation distance is not negative
            transport_distance = validated_data.get('transportation_distance')
            if transport_distance is not None and transport_distance < 0:
                raise ValidationError("Transportation distance cannot be negative")
                
        elif event_type == BUSINESS_EVENT_TYPE:
            # Validate carbon credits earned is not negative
            carbon_credits = validated_data.get('carbon_credits_earned')
            if carbon_credits is not None and carbon_credits < 0:
                raise ValidationError("Carbon credits earned cannot be negative")
            
            # Validate investment amount is not negative
            investment = validated_data.get('investment_amount')
            if investment is not None and investment < 0:
                raise ValidationError("Investment amount cannot be negative")
            
            # Validate business type
            business_type = validated_data.get('business_type')
            valid_business_types = [
                'certification', 'carbon_credits', 'sustainability_audit', 'green_investment',
                'supply_chain', 'consumer_engagement', 'regulatory_compliance', 'carbon_offset',
                'sustainability_training', 'eco_certification'
            ]
            if business_type and business_type not in valid_business_types:
                raise ValidationError(
                    f"Invalid business type: {business_type}. Must be one of: {', '.join(valid_business_types)}"
                )

    @action(detail=False, methods=['get'], url_path='structured-field-options')
    def structured_field_options(self, request):
        """
        API endpoint to get available options for structured fields
        """
        options = {
            'chemical_event': {
                'application_methods': [
                    {'value': 'broadcast', 'label': 'Broadcast/Spread'},
                    {'value': 'injection', 'label': 'Injection/Banding'},
                    {'value': 'foliar', 'label': 'Foliar Spray'},
                    {'value': 'drip', 'label': 'Drip/Fertigation'},
                    {'value': 'banding', 'label': 'Banding/Placement'},
                ]
            },
            'equipment_event': {
                'efficiency_ratings': [
                    {'value': 'high', 'label': 'High Efficiency'},
                    {'value': 'normal', 'label': 'Normal Efficiency'},
                    {'value': 'low', 'label': 'Low Efficiency'},
                ],
                'fuel_units': [
                    {'value': 'L', 'label': 'Liters'},
                    {'value': 'gal', 'label': 'Gallons'},
                ]
            },
            'production_event': {
                'area_units': [
                    {'value': 'ha', 'label': 'Hectares'},
                    {'value': 'acre', 'label': 'Acres'},
                ],
                'yield_units': [
                    {'value': 'kg', 'label': 'Kilograms'},
                    {'value': 'lb', 'label': 'Pounds'},
                    {'value': 'ton', 'label': 'Tons'},
                ],
                'efficiency_ratings': [
                    {'value': 'high', 'label': 'High Efficiency'},
                    {'value': 'normal', 'label': 'Normal Efficiency'},
                    {'value': 'low', 'label': 'Low Efficiency'},
                ]
            },
            'business_event': {
                'business_types': [
                    {'value': 'certification', 'label': 'Certification Event (Organic, Carbon, etc.)'},
                    {'value': 'carbon_credits', 'label': 'Carbon Credits Transaction'},
                    {'value': 'sustainability_audit', 'label': 'Sustainability Audit/Assessment'},
                    {'value': 'green_investment', 'label': 'Green Technology Investment'},
                    {'value': 'supply_chain', 'label': 'Supply Chain Optimization'},
                    {'value': 'consumer_engagement', 'label': 'Consumer Engagement Initiative'},
                    {'value': 'regulatory_compliance', 'label': 'Regulatory Compliance'},
                    {'value': 'carbon_offset', 'label': 'Carbon Offset Purchase'},
                    {'value': 'sustainability_training', 'label': 'Sustainability Training'},
                    {'value': 'eco_certification', 'label': 'Eco-Certification Process'},
                ]
            }
        }
        return Response(options)
