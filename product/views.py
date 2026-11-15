import json
import logging
from datetime import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from rest_framework import filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.permissions import CALLER_SCOPED, CATALOG_ROUTE, CompanyNestedViewSet, scope_to_caller_companies
from history.retention import assert_deletable
from history.serializers import HistorySerializer
from product.services.buffer_zones import BufferZoneError, normalize_buffer_rows
from subscriptions.permissions import HasParcelCreationPermission

from .models import Parcel, ParcelCropHistory, ParcelPlannedCrop, Product
from .serializers import (
    CreateParcelSerializer,
    ParcelCropHistorySerializer,
    ParcelPlannedCropSerializer,
    ProductListSerializer,
    RetrieveParcelSerializer,
)

logger = logging.getLogger(__name__)


class ParcelViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    flat_route_tenancy = CALLER_SCOPED  # see backend/permissions.py
    object_company_path = "establishment__company"

    queryset = (
        Parcel.objects.select_related("establishment", "establishment__company", "album", "product")
        .prefetch_related("histories")
        .all()
    )
    filter_backends = [filters.OrderingFilter]
    parser_classes = (MultiPartParser, FormParser)

    def get_queryset(self):
        # Registered flat at /api/parcels/ as well as nested; on the flat route the permission
        # layer only proves the caller is signed in. See `scope_to_caller_companies`.
        queryset = super().get_queryset()
        if self.company is not None:
            queryset = queryset.filter(establishment__company=self.company)
        return scope_to_caller_companies(queryset, self.request.user, "establishment__company")

    def get_permissions(self):
        if self.action == "create":
            # COMPOSE with the class default, never replace it.
            #
            # This previously returned [IsAuthenticated(), HasParcelCreationPermission()], which
            # DISCARDED CompanyNestedViewSet's
            # `[IsSuperUser | (ReadOnlyForViewers & AuthPermission)]` — so the role check and the
            # company-membership check both vanished, and any authenticated user satisfied the
            # endpoint as long as the target company was under quota.
            return super().get_permissions() + [HasParcelCreationPermission()]
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

    # WS-5 Parcel Application (plan #30, Appendix A §f) — the per-parcel § 205.202
    # module. Definition comes from the shared osp_modules schema; answers bind to
    # real Parcel columns (parcel_field whitelist) or land in application_answers.
    # Completion always reads LIVE model state via parcel_application_status.
    _APPLICATION_PARCEL_FIELDS = {
        "name": str,
        "apn": str,
        "section_township_range": str,
        "address": str,
        "container_production": bool,
        "treated_lumber_present": bool,
        "treated_lumber_description": str,
        "treated_lumber_install_date": "date",
        "date_began_managing": "date",
    }

    # Buffer-row keys are owned by product.services.buffer_zones (CANONICAL_KEYS +
    # LEGACY_ALIASES). This viewset deliberately keeps no second copy of that list.

    def _application_payload(self, parcel):
        from certifications.models import OSPChangeNotification
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
        from certifications.osp_modules.schema import serialize_module
        from certifications.services.parcel_application_lines import open_season_crops
        from certifications.services.parcel_land_history import land_history_summary
        from certifications.services.parcel_map import parcel_boundary_centre
        from history.models import GeneralEvent
        from product.services.parcel_application_status import parcel_application_status, parcel_application_values

        values = parcel_application_values(parcel)

        return {
            "definition": serialize_module(PARCEL_APPLICATION),
            "values": values,
            "buffer_zones": parcel.buffer_zones or [],
            "crop_history_count": parcel.crop_history.count(),
            "has_polygon": bool(parcel.polygon),
            # §A coordinates (CCOF ORGB49 A5, WSDA AGR 2264 ref 2, OTCO C2 2.1): the centre the parcel PDF
            # prints, from the same function, so the wizard shows the figure the certifier will read.
            "boundary_centre": parcel_boundary_centre(parcel),
            # §A crop table (CCOF ORGB49 A8, WSDA AGR 2264 ref 8, OTCO C2 2.1 10) and the crops of the seasons
            # still open here, which the wizard offers as a starting point and the PDF checks the list against.
            "planned_crops": ParcelPlannedCropSerializer(parcel.planned_crops.all().order_by("pk"), many=True).data,
            "open_season_crops": open_season_crops(parcel),
            # E-page map render (authenticated surface; CardWithMap wants both)
            "polygon": parcel.polygon or None,
            "map_metadata": parcel.map_metadata or None,
            "has_affidavit": parcel.landowner_affidavits.exists(),
            # 2026-09-09 — the facts the parcel PDF prints in §F (certificate of record, manager
            # table, 36-month accounting), so the wizard shows the operator what the certifier
            # will read rather than a bare "affidavit on file" glyph. One source for both.
            "land_history": land_history_summary(parcel),
            # § 205.202(c): the neighbour-signed boundary attestations, so the wizard card can say
            # which borders carry one rather than rendering a bare label.
            "adjoining_affidavits": [
                {
                    "neighbor_name": a.neighbor_name,
                    "neighbor_farm_name": a.neighbor_farm_name or "",
                    "border_side": a.get_border_side_display() if a.border_side else "",
                    "signed": a.neighbor_signed_date.isoformat() if a.neighbor_signed_date else None,
                }
                for a in parcel.adjoining_land_affidavits.all().order_by("border_side", "id")
            ],
            # §D's two record lists, so the wizard shows what the parcel PDF prints there
            # (2026-11-06; until then the wizard rendered their headings over nothing). Codes, not
            # English display text: the app words them in the reader's language.
            "change_notifications": [
                {
                    "date_notified": n.date_notified.isoformat() if n.date_notified else None,
                    "recorded": n.created_at.date().isoformat() if n.created_at else None,
                    "category": n.change_category,
                    "description": n.description or "",
                    "acknowledged": (n.certifier_acknowledged_at.isoformat() if n.certifier_acknowledged_at else None),
                }
                for n in OSPChangeNotification.objects.filter(parcel=parcel).order_by("date_notified", "id")
            ],
            "contamination_incidents": [
                {
                    "date": e.date.date().isoformat() if e.date else None,
                    "source": e.contamination_source or "",
                    "description": e.description or "",
                    "certifier_notified": bool(e.certifier_notified),
                    "certifier_notification_date": (
                        e.certifier_notification_date.isoformat() if e.certifier_notification_date else None
                    ),
                }
                for e in GeneralEvent.objects.filter(history__parcel=parcel, is_contamination_incident=True).order_by(
                    "date"
                )
            ],
            "status": parcel_application_status(parcel),
        }

    @action(detail=True, methods=["get", "put"], parser_classes=[JSONParser])
    def application(self, request, pk=None, parcel_pk=None, company_pk=None, establishment_pk=None):
        """Parcel Application module: definition + live-bound values (+ save)."""
        from datetime import date as _date

        establishments = self.company.establishment_set.all()
        parcel = get_object_or_404(Parcel, id=pk, establishment__in=establishments.all())

        if request.method == "PUT":
            question_to_field = {
                "parcel_name": "name",
                "apn": "apn",
                "section_township_range": "section_township_range",
                "address": "address",
                "container_production": "container_production",
                "treated_lumber_present": "treated_lumber_present",
                "treated_lumber_description": "treated_lumber_description",
                "treated_lumber_install_date": "treated_lumber_install_date",
                "date_began_managing": "date_began_managing",
            }
            incoming = request.data.get("values", {})
            if not isinstance(incoming, dict):
                return Response({"detail": "values must be an object"}, status=400)

            answers = dict(parcel.application_answers or {})
            update_fields = set()
            for key, value in incoming.items():
                field = question_to_field.get(key)
                if field:
                    expected = self._APPLICATION_PARCEL_FIELDS[field]
                    if expected == "date":
                        if value in (None, ""):
                            value = None
                        else:
                            try:
                                value = _date.fromisoformat(str(value))
                            except ValueError:
                                return Response({"detail": f"{key}: invalid date"}, status=400)
                    elif expected is bool:
                        # bool("false") is True — JSON clients send real booleans,
                        # but a string must not silently flip a compliance flag.
                        if isinstance(value, str):
                            value = value.strip().lower() in ("true", "1", "yes")
                        else:
                            value = bool(value)
                    elif value is not None:
                        value = str(value)
                    setattr(parcel, field, value)
                    update_fields.add(field)
                else:
                    # Non-model answer. None deletes; everything else stores as-is.
                    if value is None:
                        answers.pop(key, None)
                    else:
                        answers[key] = value

            if "buffer_zones" in request.data:
                # One vocabulary, owned by product.services.buffer_zones — the Parcel page
                # and this wizard MUST normalize identically, or a save on one surface
                # destroys what the other wrote.
                try:
                    parcel.buffer_zones = normalize_buffer_rows(request.data.get("buffer_zones"))
                except BufferZoneError as exc:
                    return Response({"detail": str(exc)}, status=400)
                update_fields.add("buffer_zones")

            parcel.application_answers = answers
            update_fields.add("application_answers")
            parcel.save(update_fields=list(update_fields))

        return Response(self._application_payload(parcel))

    # `ParcelViewSet` sets `parser_classes = (MultiPartParser, FormParser)` for the parcel form,
    # which uploads images. This action carries one enum value and no file, so it accepts JSON —
    # and needs to: a bodyless GET through MultiPartParser raises on `request.FILES`.
    @action(
        detail=True,
        methods=["get", "patch"],
        url_path="location-disclosure",
        parser_classes=[JSONParser, MultiPartParser, FormParser],
    )
    def location_disclosure(self, request, pk=None, parcel_pk=None, company_pk=None, establishment_pk=None):
        """How precisely this parcel's location may appear on the PUBLIC consumer page.

        Its own endpoint rather than a field on the parcel form, for the reason
        `.claude/rules/frontend.md` gives: a payload sends only what its UI renders. The prompt
        that collects this answer renders two buttons and nothing else, so folding it into the
        parcel form's payload would make a one-question dialog write forty unrelated fields —
        the clobber class that rule exists to prevent.

        Reaches the consumer surface ONLY. `public_parcel_geo` is the sole reader of
        `location_disclosure_level`, and the parcel application, the dashboard map and the
        add/update parcel form all read `Parcel.polygon` directly. Narrowing disclosure never
        removes the boundary from the operation's own records or from its certifier packet.

        PATCH records `location_disclosure_choice_made`, which is the point: migration 0013
        wrote `exact` onto every pre-existing parcel and the setting was never surfaced, so the
        product could not tell a farm that CHOSE to publish its boundary from one that inherited
        the value and was never asked. Answering either way settles it.
        """
        # Scoped by ACTUAL OWNERSHIP rather than `self.company`, which is populated only when
        # the request arrives on the company-nested route. Asking "does a company this user
        # belongs to own this parcel" is both route-independent and the correct question — the
        # 2026-08-19 quota bug came from a permission that consulted an "active company" while
        # the write landed on `parcel.establishment.company`, which made the check bypassable by
        # switching companies.
        parcel = get_object_or_404(
            Parcel,
            id=pk,
            establishment__company__in=request.user.companies.all(),
        )

        if request.method == "PATCH":
            level = request.data.get("location_disclosure_level")
            valid = {choice for choice, _label in Parcel.LOCATION_DISCLOSURE_CHOICES}
            if level not in valid:
                return Response(
                    {"location_disclosure_level": [f"Must be one of: {', '.join(sorted(valid))}."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            parcel.location_disclosure_level = level
            parcel.location_disclosure_choice_made = True
            parcel.save(update_fields=["location_disclosure_level", "location_disclosure_choice_made"])

        # The most recent PUBLISHED season on this parcel, so the setting can link to the page it
        # controls. Without it the farmer has no way to go and look at what they just changed —
        # which in testing produced the confusion this field exists to remove: a parcel's setting
        # was changed and a DIFFERENT parcel's public page was then checked, twice, because
        # finding the right lot means knowing which season belongs to which block.
        published = parcel.histories.filter(published=True).order_by("-finish_date", "-id").first()

        return Response(
            {
                "location_disclosure_level": parcel.location_disclosure_level,
                "location_disclosure_choice_made": parcel.location_disclosure_choice_made,
                "preview_production_public_id": str(published.public_id) if published else None,
                # Whether there is a boundary to publish at all. A parcel set to `exact` with no
                # polygon exposes nothing, so the prompt must not warn it about a boundary it
                # does not have.
                "has_boundary": bool(parcel.polygon),
            }
        )

    @action(detail=True, methods=["get"], url_path="transition-status")
    def transition_status(self, request, pk=None, parcel_pk=None, company_pk=None, establishment_pk=None):
        """
        NOP 7 CFR 205.202 organic transition status for this parcel.

        Returns earliest organic-eligible harvest date, days remaining, and the list
        of prohibited-substance findings driving the calculation.
        """
        from product.services.transition_status_service import compute_transition_status

        establishments = self.company.establishment_set.all()
        parcel = get_object_or_404(Parcel, id=pk, establishment__in=establishments.all())
        status_obj = compute_transition_status(parcel)
        return Response(status_obj.to_dict())

    # The same two actions under the model's name (History is Production since history 0264). Each
    # delegates to its `*_history` twin; those go once the app has moved over (expand/contract).
    @action(detail=True, methods=["get"])
    def current_production(self, request, *args, **kwargs):
        return self.current_history(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def finish_production(self, request, *args, **kwargs):
        return self.finish_history(request, *args, **kwargs)

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

        # `current_history` is a denormalised pointer; the fact it stands for is "a production
        # on this parcel that has not been finished yet". The two can drift — the pointer is
        # only maintained by the production-create and finish paths, so anything that writes a
        # History another way (an import, a fixture, a data repair) leaves it null while the
        # season is plainly open.
        #
        # 🔴 2026-08-19: that drift is visible ON ONE SCREEN. The parcel page renders this
        # endpoint as "Current Production" and, beside it, a Productions list that derives its
        # own status from `finish_date`. A parcel with an open season showed "No current
        # production yet" next to "1 ongoing" and the season itself. Two demo seeders already
        # shipped a `fix_parcel_current_history` helper, which is the tell: the derivation is
        # the real source of truth and the pointer is a cache.
        #
        # So fall back to deriving it, and heal the pointer when it was simply missing.
        current = parcel.current_history
        if current is None:
            current = (
                History.objects.filter(parcel=parcel, finish_date__isnull=True).order_by("-start_date", "-id").first()
            )
            if current is not None:
                parcel.current_history = current
                parcel.save(update_fields=["current_history"])

        if current is None:
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
            .get(pk=current.id)
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
            # Completed seasons for this parcel. This filtered on `published=True` for as
            # long as finishing a production also published it unconditionally, so the two
            # were the same set and the flag read as a synonym for "finished". Finishing no
            # longer implies publishing — the confirm dialog carries a checkbox — and this
            # is a company-scoped PRODUCER endpoint (CompanyNestedViewSet already enforces
            # tenancy), so `published` is not doing access control here. Left as-is it would
            # hide a farmer's own finished season from their own parcel history the moment
            # they chose not to publish it.
            .filter(finish_date__isnull=False)
            .order_by("-id")
        )

        if parcel.current_history is not None:
            histories = histories.exclude(id=parcel.current_history.id)

        # Use the optimized serializer that avoids expensive operations
        return Response(OptimizedHistoryListSerializer(histories, many=True, context={"request": request}).data)

    def perform_destroy(self, instance):
        """Refuse to delete a parcel that still carries a production inside retention.

        Deleting the parcel cascades to its productions in bulk, which never calls
        History.delete() and so never reaches the NOP retention guard. See
        history/retention.py — the same check guards farms and companies.
        """
        assert_deletable("parcel", parcel=instance)
        super().perform_destroy(instance)

    def _resolve_finish_target(self, parcel, history_data):
        """The season this request is closing, or a 400 Response explaining why it is unclear.

        Accepts the numeric pk or the public UUID, because the two callers that name a season
        disagree about which they send. Falls back to `parcel.current_history` only when the
        parcel has exactly one open season — where the fallback cannot be wrong.
        """
        from history.models import History

        raw = history_data.get("history") or history_data.get("production_id")
        raw = str(raw).strip() if raw is not None else ""

        if raw:
            qs = History.objects.filter(parcel=parcel)
            target = qs.filter(id=int(raw)).first() if raw.isdigit() else None
            if target is None and not raw.isdigit():
                try:
                    target = qs.filter(public_id=raw).first()
                except (ValueError, DjangoValidationError):
                    target = None
            if target is None:
                return Response(
                    {"history": [f"No production {raw!r} on this parcel."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if target.finish_date is not None:
                return Response(
                    {"history": ["That production is already finished."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return target

        open_seasons = list(History.objects.filter(parcel=parcel, finish_date__isnull=True).order_by("-start_date"))
        if len(open_seasons) > 1:
            return Response(
                {
                    "history": [
                        "This parcel has more than one open production, so it is unclear which "
                        "one you are closing: "
                        + "; ".join(
                            f"{h.name or 'Production'} (id {h.id}, started "
                            f"{h.start_date.date().isoformat() if h.start_date else 'unknown'})"
                            for h in open_seasons
                        )
                        + ". Close it from that production's own page."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return parcel.current_history

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def finish_history(self, request, pk=None, parcel_pk=None, company_pk=None, establishment_pk=None):
        import time

        _t0 = time.monotonic()

        parcel = self.get_object()
        _t1 = time.monotonic()

        history_data = request.data
        # Cover/album photos. Two shapes can arrive under "album[images]":
        #  - raw file uploads -> request.FILES (DRF-backed, available after request.data)
        #  - pre-uploaded S3 URL strings (the normal app flow — TrazoImageUpload uploads
        #    first, then submits the URLs) -> form fields in request.data.
        # NOTE: read the strings from request.data, NOT request.POST — once DRF parses the
        # multipart body via request.data (above), Django's request.POST is empty. Filter
        # request.data to str so file objects (also present there) aren't double-counted.
        file_images = list(request.FILES.getlist("album[images]"))
        raw_images = request.data.getlist("album[images]") if hasattr(request.data, "getlist") else []
        url_images = [u for u in raw_images if isinstance(u, str) and u]
        images = file_images + url_images
        # History.finish() assigns request values straight onto the model and saves, so
        # anything the database rejects (an over-length string, a bad numeric) surfaced
        # as a 500 DataError. Finalization is the moment a grower publishes their season
        # — it must fail with a usable field error, not a server error page.
        # 🔴 2026-08-20 — WHICH season is being closed must come from the caller.
        #
        # This acted on `parcel.current_history`, which holds whichever season started last. A
        # perennial block routinely carries two open seasons, and the finish page is reached
        # per-production, so closing the 2025 season validated against the 2026 one: the farmer
        # was told "finish date cannot be before the production's start date (2026-03-18)" for a
        # date they never entered and a season they were not closing. They could not complete
        # the close at all.
        #
        # The worse branch is the one that did not fire here: had the dates been compatible,
        # the click would have closed the WRONG season — and closing is irreversible by design
        # (it makes the record read-only and starts the § 205.103(b)(4) retention clock).
        target = self._resolve_finish_target(parcel, history_data)
        if isinstance(target, Response):
            return target

        invalid = self._validate_finalization_fields(history_data, current_history=target)
        if invalid:
            return Response(invalid, status=status.HTTP_400_BAD_REQUEST)

        history = parcel.finish_history_record(target, history_data, images)
        _t2 = time.monotonic()

        if history is not None:
            # Compute finalization hash of all events for blockchain integrity
            self._store_finalization_hash(history)
            _t3 = time.monotonic()

            # Trigger immediate blockchain submission if company has the add-on.
            # Uses on_commit to ensure finalization hash is persisted before
            # the Celery task reads it.
            self._trigger_blockchain_submission(history)
            _t4 = time.monotonic()

            response_data = HistorySerializer(history).data
            _t5 = time.monotonic()

            logger.info(
                "TIMING finish_history: TOTAL %.3fs (get_object=%.3f, finish=%.3f, hash=%.3f, blockchain=%.3f, serialize=%.3f)",
                _t5 - _t0,
                _t1 - _t0,
                _t2 - _t1,
                _t3 - _t2,
                _t4 - _t3,
                _t5 - _t4,
            )

            return Response(response_data)
        return Response(
            {"error": "No active production found for this parcel."},
            status=400,
        )

    # Fields History.finish() copies from the request onto the model. Validated here
    # because finish() bypasses serializer validation entirely.
    _FINALIZE_FIELDS = ("lot_id", "production_unit", "quality_grade", "harvest_method")

    def _validate_finalization_fields(self, history_data, current_history=None):
        """
        Return a DRF-shaped error dict for any finalization field the model would reject,
        or None when everything is acceptable.
        """
        from history.models import History

        errors = {}

        for field_name in self._FINALIZE_FIELDS:
            value = history_data.get(field_name)
            if value in (None, ""):
                continue
            value = str(value)
            field = History._meta.get_field(field_name)

            max_length = getattr(field, "max_length", None)
            if max_length and len(value) > max_length:
                errors[field_name] = [f"Ensure this value has at most {max_length} characters (it has {len(value)})."]
                continue

            choices = [c[0] for c in (field.choices or [])]
            if choices and value not in choices:
                errors[field_name] = [f'"{value}" is not a valid choice. Valid options: {", ".join(choices)}.']

        # finish() indexes history_data["production_amount"] and assigns it to a
        # FloatField; a non-numeric value would otherwise reach the database.
        amount = history_data.get("production_amount")
        if amount in (None, ""):
            errors.setdefault("production_amount", ["This field is required to finalize a production."])
        else:
            try:
                float(amount)
            except (TypeError, ValueError):
                errors["production_amount"] = ["Enter a number."]

        finish_raw = history_data.get("finish_date")
        if not finish_raw:
            errors.setdefault("finish_date", ["This field is required to finalize a production."])
        else:
            finish_dt = self._parse_finish_date(finish_raw)
            if finish_dt is None:
                errors["finish_date"] = ["Enter a valid date or ISO-8601 datetime."]
            # A season that has not ended cannot be finalized. Beyond being wrong on its
            # face, a future finish_date makes the parcel page contradict itself: the
            # card badge reads "COMPLETE" (finish_date exists) while the
            # completed/ongoing counters classify by date and still say "ongoing".
            elif finish_dt > timezone.now():
                errors["finish_date"] = ["A production cannot be finalized with a finish date in the future."]
            # A season cannot end before it starts — the operation dossier
            # otherwise prints windows like "2026-08-09 – 2026-08-08" verbatim.
            elif (
                current_history is not None
                and current_history.start_date
                and finish_dt.date() < current_history.start_date.date()
            ):
                errors["finish_date"] = [
                    "Finish date cannot be before the production's start date "
                    f"({current_history.start_date.date().isoformat()})."
                ]

        return errors or None

    @staticmethod
    def _parse_finish_date(raw):
        """
        Coerce a submitted finish_date to an aware datetime, or None if unusable.

        Accepts both a datetime and a date-only string: History.finish() parses with
        datetime.fromisoformat(), which takes "2026-07-30" as well as a full timestamp,
        so validating with parse_datetime() alone would have rejected input the model
        would happily have stored — a validator stricter than the thing it guards.
        """
        if not isinstance(raw, str):
            value = raw
        else:
            value = parse_datetime(raw)
            if value is None:
                parsed_date = parse_date(raw)
                if parsed_date is None:
                    return None
                # End-of-day so a same-day finish isn't read as "in the future" for
                # anyone whose local clock is ahead of midnight UTC. Uses
                # datetime.max.time() rather than importing `time`, which is already
                # shadowed by a function-local `import time` elsewhere in this file.
                value = datetime.combine(parsed_date, datetime.max.time())

        if timezone.is_naive(value):
            try:
                value = timezone.make_aware(value)
            except Exception:  # noqa: BLE001 — ambiguous/nonexistent local times (DST)
                return None
        return value

    def _trigger_blockchain_submission(self, history):
        """Dispatch immediate blockchain submission if the company has an active subscription.

        With CELERY_TASK_ALWAYS_EAGER=True (no Redis), .delay() runs synchronously
        which would block the HTTP response for 10-20s during blockchain TX.
        We use a background thread so the response returns immediately.
        """
        try:
            company = history.parcel.establishment.company if history.parcel and history.parcel.establishment else None
            logger.info(
                "BLOCKCHAIN: company=%s, blockchain_status=%s, history=%s",
                company.id if company else None,
                company.blockchain_subscription_status if company else None,
                history.id,
            )
            if company and company.blockchain_subscription_status:
                import threading

                def _submit_in_background(production_id):
                    from django.db import connections

                    try:
                        logger.info("BLOCKCHAIN: Background thread started for production %s", production_id)
                        from carbon.tasks import submit_production_to_blockchain

                        logger.info("BLOCKCHAIN: Calling submit_production_to_blockchain.delay(%s)", production_id)
                        result = submit_production_to_blockchain.delay(production_id)
                        logger.info("BLOCKCHAIN: Task completed for production %s, result=%s", production_id, result)
                    except Exception as exc:
                        logger.error(
                            "BLOCKCHAIN: Background submission failed for production %s: %s",
                            production_id,
                            exc,
                            exc_info=True,
                        )
                    finally:
                        connections.close_all()

                transaction.on_commit(
                    lambda: threading.Thread(
                        target=_submit_in_background,
                        args=(history.id,),
                        daemon=True,
                    ).start()
                )
                logger.info(
                    "BLOCKCHAIN: Queued on_commit thread for production %s (company %s)",
                    history.id,
                    company.id,
                )
            else:
                logger.info(
                    "BLOCKCHAIN: Skipped — no blockchain subscription for company %s", company.id if company else None
                )
        except Exception as e:
            # Never let blockchain submission failure block production finalization
            logger.error("BLOCKCHAIN: Failed to queue submission for production %s: %s", history.id, e, exc_info=True)

    def _store_finalization_hash(self, history):
        """Seal the season's events at completion time, with the current seal version.

        `history.seals` is the one implementation, and the same module checks the seal later.
        """
        try:
            from history.seals import seal

            seal(history)
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
    flat_route_tenancy = CATALOG_ROUTE  # Product has no tenant FK; see backend/permissions.py

    queryset = Product.objects.all()
    serializer_class = ProductListSerializer
    filter_backends = [filters.OrderingFilter]


class ParcelPlannedCropViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """The crops a parcel grows now or is planned to grow, with acres (CCOF ORGB49 A8, WSDA AGR 2264
    ref 8, OTCO C2 2.1 10). Nested under the parcel; the parcel is the URL's, and must be the URL's
    farm's, so another company's or farm's parcel reads exactly like a missing one."""

    serializer_class = ParcelPlannedCropSerializer

    def _parcel(self):
        return get_object_or_404(
            Parcel,
            pk=self.kwargs.get("parcel_pk"),
            establishment_id=self.kwargs.get("establishment_pk"),
            establishment__company=self.company,
        )

    def get_queryset(self):
        return ParcelPlannedCrop.objects.filter(
            parcel_id=self.kwargs.get("parcel_pk"),
            parcel__establishment_id=self.kwargs.get("establishment_pk"),
            parcel__establishment__company=self.company,
        ).order_by("pk")

    def perform_create(self, serializer):
        serializer.save(parcel=self._parcel())


class ParcelCropHistoryViewSet(viewsets.ModelViewSet):
    serializer_class = ParcelCropHistorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ParcelCropHistory.objects.filter(
            parcel__establishment__company__in=self.request.user.companies.all()
        ).select_related("parcel")
        parcel_id = self.request.query_params.get("parcel")
        if parcel_id:
            qs = qs.filter(parcel_id=parcel_id)
        return qs
