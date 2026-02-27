import json
import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.permissions import CompanyNestedViewSet
from history.serializers import HistorySerializer
from subscriptions.permissions import HasParcelCreationPermission

from .models import Parcel, Product
from .serializers import CreateParcelSerializer, ProductListSerializer, RetrieveParcelSerializer

logger = logging.getLogger(__name__)


class ParcelViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    queryset = (
        Parcel.objects.select_related("establishment", "establishment__company", "album", "product")
        .prefetch_related("histories")
        .all()
    )
    filter_backends = [filters.OrderingFilter]
    parser_classes = (MultiPartParser, FormParser)

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), HasParcelCreationPermission()]
        return super().get_permissions()

    def partial_update(self, request, *args, **kwargs):
        """Override to handle indexed image URLs from FormData"""
        # Handle indexed image URLs from FormData

        # Handle indexed uploaded_image_urls
        uploaded_urls = []
        i = 0
        while f"uploaded_image_urls[{i}]" in request.data:
            url = request.data.get(f"uploaded_image_urls[{i}]")
            if url:
                uploaded_urls.append(url)
            i += 1

        if uploaded_urls:
            # Process indexed URLs
            # Convert to mutable QueryDict and update
            request.data._mutable = True
            # Remove indexed entries
            for j in range(i):
                request.data.pop(f"uploaded_image_urls[{j}]", None)
            # Add as list
            request.data.setlist("uploaded_image_urls", uploaded_urls)
            request.data._mutable = False

        return super().partial_update(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action == "create" or self.action == "update" or self.action == "partial_update":
            return CreateParcelSerializer
        return RetrieveParcelSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    @action(detail=True, methods=["get"])
    def current_history(self, request, pk=None, parcel_pk=None, company_pk=None, establishment_pk=None):
        """
        OPTIMIZED: Get current history with prefetched related data.
        Performance fix: Avoid N+1 queries by prefetching events, albums, and carbon entries.
        """
        from django.db.models import Prefetch

        from carbon.models import CarbonEntry
        from history.models import History

        establishments = self.company.establishment_set.all()
        parcel = get_object_or_404(
            Parcel,
            id=pk,
            establishment__in=establishments.all(),
        )

        if not parcel.current_history:
            return Response(None)

        # Optimized query with prefetch to avoid N+1 queries
        current_history = (
            History.objects.select_related("product", "operator", "crop_type", "parcel", "album")
            .prefetch_related(
                # Prefetch all event types with their albums
                "history_productionevent_events__album__images",
                "history_productionevent_events__created_by",
                "history_chemicalevent_events__album__images",
                "history_chemicalevent_events__created_by",
                "history_equipmentevent_events__album__images",
                "history_equipmentevent_events__created_by",
                "history_weatherevent_events__album__images",
                "history_weatherevent_events__created_by",
                "history_soilmanagementevent_events__album__images",
                "history_soilmanagementevent_events__created_by",
                "history_pestmanagementevent_events__album__images",
                "history_pestmanagementevent_events__created_by",
                "history_businessevent_events__album__images",
                "history_businessevent_events__created_by",
                "history_generalevent_events__album__images",
                "history_generalevent_events__created_by",
                # Prefetch carbon entries to avoid N+1 in serializer
                Prefetch(
                    "carbonentry_set",
                    queryset=CarbonEntry.objects.only(
                        "id",
                        "co2e_amount",
                        "amount",
                        "usda_factors_based",
                        "data_source",
                        "description",
                        "created_at",
                        "production_id",
                    ).order_by("-created_at"),
                ),
                # Note: 'members' is a SerializerMethodField, not a relation, so it can't be prefetched
            )
            .get(pk=parcel.current_history.id)
        )

        return Response(HistorySerializer(current_history, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None, parcel_pk=None, company_pk=None, establishment_pk=None):
        """
        OPTIMIZED: Get parcel history using the optimized serializer to prevent USDA API calls.
        This endpoint was causing performance issues by using HistorySerializer which triggers
        expensive carbon calculations and USDA API calls.
        """
        from history.serializers import OptimizedHistoryListSerializer

        parcel = self.get_object()

        # Use optimized queryset to prevent N+1 queries
        histories = (
            parcel.histories.select_related("product", "parcel", "crop_type")
            .only(
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
            .filter(published=True)
            .order_by("-id")
        )

        if parcel.current_history is not None:
            histories = histories.exclude(id=parcel.current_history.id)

        # Use the optimized serializer that avoids expensive operations
        return Response(OptimizedHistoryListSerializer(histories, many=True, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def finish_history(self, request, pk=None, parcel_pk=None, company_pk=None, establishment_pk=None):
        parcel = self.get_object()
        history_data = request.data
        images = request.FILES.getlist("album[images]")
        history = parcel.finish_current_history(history_data, images)
        if history is not None:
            # Compute finalization hash of all events for blockchain integrity
            self._store_finalization_hash(history)

            # Trigger immediate blockchain submission if company has the add-on.
            # Uses on_commit to ensure finalization hash is persisted before
            # the Celery task reads it.
            self._trigger_blockchain_submission(history)

            return Response(HistorySerializer(history).data)
        return Response(
            {"error": "No active production found for this parcel."},
            status=400,
        )

    def _trigger_blockchain_submission(self, history):
        """Dispatch immediate blockchain submission if the company has an active subscription."""
        try:
            company = history.parcel.establishment.company if history.parcel and history.parcel.establishment else None
            if company and company.blockchain_subscription_status:
                from carbon.tasks import submit_production_to_blockchain

                transaction.on_commit(lambda: submit_production_to_blockchain.delay(history.id))
                logger.info(
                    "Queued immediate blockchain submission for production %s (company %s)",
                    history.id,
                    company.id,
                )
        except Exception as e:
            # Never let blockchain submission failure block production finalization
            logger.error("Failed to queue blockchain submission for production %s: %s", history.id, e)

    def _store_finalization_hash(self, history):
        """Compute and store a keccak256 hash of all event data at completion time.

        The finalization hash cryptographically commits the final state of all events.
        The next monthly Celery batch task will include this hash in its blockchain submission.
        """
        try:
            events = history.get_events()  # Already sorted by index
            event_data = json.dumps(events, sort_keys=True, default=str, separators=(",", ":"))

            finalization_hash = None
            try:
                from web3 import Web3

                raw_hex = Web3.keccak(text=event_data).hex()
                finalization_hash = raw_hex.removeprefix("0x")
            except ImportError:
                import hashlib

                finalization_hash = hashlib.sha256(event_data.encode()).hexdigest()

            if history.extra_data is None:
                history.extra_data = {}
            history.extra_data["finalization_hash"] = finalization_hash
            history.extra_data["finalization_timestamp"] = timezone.now().isoformat()
            history.extra_data["finalization_event_count"] = len(events)
            history.save(update_fields=["extra_data"])
        except Exception as e:
            logger.error("Failed to store finalization hash for history %s: %s", history.id, e)

    # @action(detail=True, methods=["post"])
    # def update_parcel(
    #     self, request, pk=None, parcel_pk=None, company_pk=None, establishment_pk=None
    # ):
    #     import pdb

    #     pdb.set_trace()

    #     parcel = self.get_object()
    #     parsed_body = request.body
    #     print(request.FILES.getList("album"))
    #     name = request.data.get("id")
    #     images_data = request.data.get("album")
    #     images_post = request.POST.get("album")
    #     image = request.FILES.get("album")
    #     data = request.data
    #     data2 = request.POST
    #     data3 = request.data.get("album")
    #     # print(parsed_body)

    #     print("despues")

    #     print("images_data::::->>>>>>>")
    #     print(name)
    #     print(images_data)
    #     print(images_post)
    #     print(image)
    #     print(data)
    #     print(data2)
    #     print(data3)
    #     print(request)
    #     # parcel_data = request.data
    #     # serializer = CreateParcelSerializer(
    #     #     parcel, data=parcel_data, partial=True, context={"request": request}
    #     # )
    #     # if serializer.is_valid():
    #     #     serializer.save()
    #     #     return Response(serializer.data)
    #     return Response({}, status=400)

    # def partial_update(self, request, pk=None, company_pk=None, establishment_pk=None):
    #     parcel = self.get_object()
    #     parcel_data = request.data
    #     print(request.FILES)
    #     if parcel_data.get("album") is not None:
    #         album_data = parcel_data.get("album")
    #         parcel_data.pop("album")
    #     serializer = CreateParcelSerializer(
    #         parcel, data=parcel_data, partial=True, context={"request": request}
    #     )
    #     if serializer.is_valid():
    #         serializer.save()
    #         if album_data is None and album_data is not None:
    #             album = Gallery.objects.create()
    #             parcel.album = album
    #             parcel.save()
    #         if album_data is not None:
    #             print("entro1")
    #             for image_data in request.FILES:
    #                 print("entro2")
    #                 print(image_data)
    #                 print(request.FILES[image_data])
    #                 GalleryImage.objects.create(
    #                     image=request.FILES[image_data], gallery_id=1
    #                 )

    #         return Response(serializer.data)
    #     return Response(serializer.errors, status=400)

    # def update(self, request, pk=None, company_pk=None, establishment_pk=None):
    #     images_data = request.data.get("album")
    #     images_post = request.POST.get("album")
    #     image = request.FILES.get("album")
    #     data = request.data
    #     data2 = request.POST
    #     data3 = request.data.get("album")
    #     print("anntes")
    #     print(request.FILES)
    #     print("despues")

    #     print("images_data::::")
    #     print(images_data)
    #     print(images_post)
    #     print(image)
    #     print(data)
    #     print(data2)
    #     print(data3)
    #     parcel = self.get_object()
    #     parcel_data = request.data
    #     serializer = CreateParcelSerializer(
    #         parcel, data=parcel_data, partial=True, context={"request": request}
    #     )
    #     if serializer.is_valid():
    #         serializer.save()
    #         album = parcel_data.get("album")
    #         if album is not None:
    #             for image_data in album.get("images"):
    #                 parcel.album.images.create(
    #                     image=image_data.get("image"), gallery=parcel.album
    #                 )
    #         return Response(serializer.data)
    #     return Response(serializer.errors, status=400)


class ProductsViewSet(CompanyNestedViewSet, mixins.ListModelMixin):
    queryset = Product.objects.all()
    serializer_class = ProductListSerializer
    filter_backends = [filters.OrderingFilter]
