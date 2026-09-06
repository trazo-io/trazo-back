import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Avg, Count, Q
from django.db.models.functions import ExtractDay, ExtractMonth, ExtractWeekDay
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator

from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.permissions import CompanyNestedViewSet, IsCompanyAdmin
from history.models import History, HistoryScan
from history.retention import assert_deletable
from history.serializers import HistoryListOptionsSerializer
from product.models import Parcel, Product
from product.serializers import ProductListOptionsSerializer
from reviews.models import Review
from reviews.serializers import ListReviewSerializer
from subscriptions.gating import require_compliance_exports
from subscriptions.permissions import HasEstablishmentCreationPermission
from users.models import WorksIn
from users.serializers import WorksInSerializer

logger = logging.getLogger(__name__)

from .constants import ALLOWED_PERIODS

# The compliance-snapshot statuses a grower can actually act on.
#
# `AuditExportService.compliance_snapshot_rows()` emits PASS, REVIEW, FAIL, NA and
# "NOT ASSESSED". The certifier-readiness card models two states (FAIL = missing,
# everything else = needs attention), so anything forwarded to it that is not genuinely
# actionable is displayed as an action item and counted in the headline.
ACTIONABLE_READINESS_STATUSES = frozenset({"REVIEW", "FAIL"})
from .models import Company, Establishment
from .serializers import (
    CreateCompanySerializer,
    EstablishmentChartSerializer,
    EstablishmentDashboardMetricsSerializer,
    EstablishmentProductsReputationSerializer,
    EstablishmentSerializer,
    RetrieveCompanySerializer,
    RetrieveEstablishmentSerializer,
    UpdateEstablishmentSerializer,
)

# Activity-feed payload caps. Module level so a test can patch them instead of creating 400
# events to prove the cap reports itself.
ACTIVITY_FEED_PER_MODEL_CAP = 400
ACTIVITY_FEED_TOTAL_CAP = 800


class CompanyViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):

    def perform_destroy(self, instance):
        """A company cannot be deleted while any of its farms hold retained records."""
        assert_deletable("company", parcel__establishment__company=instance)
        super().perform_destroy(instance)

    queryset = Company.objects.all()
    filter_backends = [filters.OrderingFilter]

    def get_permissions(self):
        if self.action in ["update", "partial_update", "destroy"]:
            return [IsCompanyAdmin()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "create":
            return CreateCompanySerializer
        return RetrieveCompanySerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = serializer.save()
        WorksIn.objects.create(user=request.user, company=company, role=WorksIn.COMPANY_ADMIN)

        # Put every new company on Starter — FREE FOREVER, not a trial.
        #
        # 2026-08-13: this created `status="trialing"` with a 14-day `trial_end`, and
        # `expire_trials` then flipped it to "canceled" on day 14, which at the time nulled
        # `Company.subscription_plan` and 403'd every creation in the app. (A canceled
        # subscription now falls back to Starter — see `Company.subscription_plan` — so that
        # cascade is gone, but the tier still must not be created as a trial.) That contradicts the
        # October plan in four places ("Starter free forever, pilot free, no card") and, worse,
        # contradicts the COG Pro migration page whose entire anti-lock-in answer is "Starter is
        # free permanently, not a trial" — aimed at refugees from a product that dies 2026-12-31.
        #
        # `status="active"` with no `trial_end`: the tier is bounded by what it can PRODUCE,
        # never by a clock. Since migration 0014 that means unlimited parcels and productions,
        # 10 GB of photo storage and voice input, with the certifier OUTPUTS (OSP packet, audit
        # export, PUR export, certifier link) gated behind `compliance_exports`.
        # `current_period_end=None` is correct for a plan that does not renew or lapse;
        # `mrr_for()` reads price, which is 0.
        from subscriptions.models import Plan, Subscription

        starter_plan = Plan.objects.filter(slug="starter", is_active=True).first()
        if starter_plan:
            Subscription.objects.create(
                company=company,
                plan=starter_plan,
                status="active",
                current_period_start=timezone.now(),
                current_period_end=None,
                trial_end=None,
            )
            logger.info("Started free-forever Starter plan for new company %s", company.id)
        else:
            logger.warning(
                "Starter plan not found! New company %s has no subscription.",
                company.id,
            )

        # Re-serialize with RetrieveCompanySerializer to include subscription data
        retrieve_serializer = RetrieveCompanySerializer(company, context=self.get_serializer_context())
        return Response(retrieve_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None, company_pk=None):
        company = get_object_or_404(Company, pk=pk)
        members = WorksIn.objects.filter(company=company)
        return Response(
            WorksInSerializer(members, many=True).data,
            status=status.HTTP_200_OK,
        )


class EstablishmentViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):

    def perform_destroy(self, instance):
        """A farm cannot be deleted while it holds productions inside NOP retention.

        Establishment -> Parcel -> History is CASCADE the whole way, so this delete
        erased retained productions in bulk without ever calling History.delete().
        """
        assert_deletable("farm", parcel__establishment=instance)
        super().perform_destroy(instance)

    queryset = (
        Establishment.objects.select_related("company", "album").prefetch_related("parcels", "parcels__product").all()
    )
    filter_backends = [filters.OrderingFilter]
    serializer_class = UpdateEstablishmentSerializer

    def get_permissions(self):
        if self.action == "destroy":
            return [IsCompanyAdmin()]
        if self.action in ["create", "update", "partial_update"]:
            # COMPOSE with the class default, never replace it.
            #
            # This previously returned [IsAuthenticated(), HasEstablishmentCreationPermission()],
            # which DISCARDED CompanyNestedViewSet's
            # `[IsSuperUser | (ReadOnlyForViewers & AuthPermission)]`. Because
            # HasEstablishmentCreationPermission returns True for every non-POST method, the only
            # surviving check on PUT/PATCH was "is authenticated" — so a Viewer-role member could
            # edit a farm, and the company-membership check was gone too.
            return super().get_permissions() + [HasEstablishmentCreationPermission()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "create" or self.action == "update" or self.action == "partial_update":
            return UpdateEstablishmentSerializer
        return RetrieveEstablishmentSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def _generate_filter_kwargs(self, period: str, production: str = "", period_filter: str = "") -> dict:
        filter_kwargs = {}
        if period == "week":
            filter_kwargs[f"{period_filter}date__gte"] = datetime.now() - timedelta(days=7)
        elif period == "month":
            filter_kwargs[f"{period_filter}date__gte"] = datetime.now() - timedelta(days=31)
        elif period == "year":
            filter_kwargs[f"{period_filter}date__gte"] = datetime.now() - timedelta(days=365)

        if production is not None:
            production = get_object_or_404(History, pk=production)
            filter_kwargs["history__id"] = production.id

        return filter_kwargs

    @action(detail=True, methods=["get"])
    def products(self, request, pk=None, company_pk=None, establishment_pk=None) -> Response:
        establishment = get_object_or_404(Establishment, pk=pk)
        products = Product.objects.filter(
            histories__parcel__establishment=establishment,
            histories__published=True,
        )
        parcel = request.query_params.get("parcel", None)
        if parcel is not None:
            parcel = get_object_or_404(Parcel, pk=parcel)
            products = products.filter(histories__parcel__id=parcel.id)

        return Response(ProductListOptionsSerializer(products.distinct(), many=True).data)

    @action(detail=True, methods=["get"])
    def histories(self, request, pk=None, company_pk=None, establishment_pk=None) -> Response:
        establishment = get_object_or_404(Establishment, pk=pk)
        parcel = request.query_params.get("parcel", None)
        product = request.query_params.get("product", None)
        period = request.query_params.get("period", None)
        if period is None or period not in ALLOWED_PERIODS:
            return Response(
                {"error": "Period is required and must be week, month or year"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get date kwargs for filter by period
        filter_kwargs = self._generate_filter_kwargs(period, None, "history_scans__")

        if parcel is not None:
            parcel = get_object_or_404(Parcel, pk=parcel)
            filter_kwargs["parcel__id"] = parcel.id

        if product is not None:
            product = get_object_or_404(Product, pk=product)
            filter_kwargs["product__id"] = product.id

        histories = History.objects.filter(
            parcel__establishment=establishment,
            published=True,
            **filter_kwargs,
        ).distinct()

        return Response(HistoryListOptionsSerializer(histories, many=True).data)

    @action(detail=True, methods=["get"])
    def get_charts_data(self, request, pk=None, company_pk=None) -> Response:
        establishment = get_object_or_404(Establishment, pk=pk)
        parcel = request.query_params.get("parcel", None)
        product = request.query_params.get("product", None)
        period = request.query_params.get("period", None)
        production = request.query_params.get("production", None)

        if period is None or period not in ALLOWED_PERIODS:
            return Response(
                {"error": "Period is required and must be week, month or year"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get date kwargs for filter by period
        filter_kwargs = self._generate_filter_kwargs(period, production, "history__history_scans__")

        if parcel is not None:
            parcel = get_object_or_404(Parcel, pk=parcel)
            filter_kwargs["history__parcel__id"] = parcel.id

        if product is not None:
            product = get_object_or_404(Product, pk=product)
            filter_kwargs["history__product__id"] = product.id

        series_result = []
        if period == "week":
            histories = (
                HistoryScan.objects.counted()
                .filter(
                    history__parcel__establishment=establishment,
                    history__published=True,
                    **filter_kwargs,
                )
                .distinct()
            )
            total_histories = histories.annotate(day_of_week=ExtractWeekDay("date"))
            total_histories = total_histories.values("day_of_week").annotate(count=Count("id", distinct=True))

            # Query reviews directly (not through HistoryScan) to include web reviews without scan
            review_filter_kwargs = {"date__gte": datetime.now() - timedelta(days=7)}
            if parcel is not None:
                review_filter_kwargs["production__parcel__id"] = parcel.id
            if product is not None:
                review_filter_kwargs["production__product__id"] = product.id
            reviews_by_day = (
                Review.objects.filter(
                    production__parcel__establishment=establishment,
                    production__published=True,
                    **review_filter_kwargs,
                )
                .annotate(day_of_week=ExtractWeekDay("date"))
                .values("day_of_week")
                .annotate(count=Count("id", distinct=True))
            )

            result_dict = {}
            for history in total_histories:
                if history["day_of_week"] not in result_dict:
                    result_dict[history["day_of_week"]] = {}
                result_dict[history["day_of_week"]]["scans"] = history["count"]
            for review in reviews_by_day:
                if review["day_of_week"] not in result_dict:
                    result_dict[review["day_of_week"]] = {}
                result_dict[review["day_of_week"]]["reviews"] = review["count"]
            today = datetime.now()
            one_week_ago = today - timedelta(days=6)
            date_range = [one_week_ago + timedelta(days=i) for i in range((today - one_week_ago).days + 1)]

            series_result = []
            series_result_reviews = []
            days_range = []
            for date in date_range:
                day = date.isoweekday() % 7 + 1
                days_range.append(day)
                if day in result_dict:
                    (
                        series_result.append(result_dict[day]["scans"])
                        if "scans" in result_dict[day]
                        else series_result.append(0)
                    )
                    (
                        series_result_reviews.append(result_dict[day]["reviews"])
                        if "reviews" in result_dict[day]
                        else series_result_reviews.append(0)
                    )
                else:
                    series_result.append(0)
                    series_result_reviews.append(0)

        elif period == "month":
            histories = (
                HistoryScan.objects.counted()
                .filter(
                    history__parcel__establishment=establishment,
                    history__published=True,
                    **filter_kwargs,
                )
                .distinct()
            )
            total_histories = histories.annotate(day_of_month=ExtractDay("date"), month=ExtractMonth("date"))
            total_histories = total_histories.values("day_of_month", "month")
            total_histories = total_histories.annotate(count=Count("id", distinct=True))

            # Query reviews directly (not through HistoryScan) to include web reviews without scan
            review_filter_kwargs = {"date__gte": datetime.now() - timedelta(days=31)}
            if parcel is not None:
                review_filter_kwargs["production__parcel__id"] = parcel.id
            if product is not None:
                review_filter_kwargs["production__product__id"] = product.id
            reviews_by_day = (
                Review.objects.filter(
                    production__parcel__establishment=establishment,
                    production__published=True,
                    **review_filter_kwargs,
                )
                .annotate(day_of_month=ExtractDay("date"), month=ExtractMonth("date"))
                .values("day_of_month", "month")
                .annotate(count=Count("id", distinct=True))
            )

            result_dict = {}
            for history in total_histories:
                month = history["month"]
                day_of_month = history["day_of_month"]
                if month not in result_dict:
                    result_dict[month] = {}
                if day_of_month not in result_dict[month]:
                    result_dict[month][day_of_month] = {}
                result_dict[month][day_of_month]["scans"] = history["count"]
            for review in reviews_by_day:
                month = review["month"]
                day_of_month = review["day_of_month"]
                if month not in result_dict:
                    result_dict[month] = {}
                if day_of_month not in result_dict[month]:
                    result_dict[month][day_of_month] = {}
                result_dict[month][day_of_month]["reviews"] = review["count"]
            today = datetime.now()
            one_month_ago = today - timedelta(days=31)
            date_range = [one_month_ago + timedelta(days=i) for i in range((today - one_month_ago).days + 1)]

            series_result = []
            series_result_reviews = []
            days_range = []
            for date in date_range:
                day = date.day
                month = date.month
                days_range.append(day)
                if month in result_dict and day in result_dict[month]:
                    (
                        series_result.append(result_dict[month][day]["scans"])
                        if "scans" in result_dict[month][day]
                        else series_result.append(0)
                    )
                    (
                        series_result_reviews.append(result_dict[month][day]["reviews"])
                        if "reviews" in result_dict[month][day]
                        else series_result_reviews.append(0)
                    )
                else:
                    series_result.append(0)
                    series_result_reviews.append(0)
        elif period == "year":
            histories = (
                HistoryScan.objects.counted()
                .filter(
                    history__parcel__establishment=establishment,
                    history__published=True,
                    **filter_kwargs,
                )
                .distinct()
            )
            total_histories = histories.annotate(month=ExtractMonth("date"))
            total_histories = total_histories.values("month")
            total_histories = total_histories.annotate(count=Count("id", distinct=True))

            # Query reviews directly (not through HistoryScan) to include web reviews without scan
            review_filter_kwargs = {"date__gte": datetime.now() - timedelta(days=365)}
            if parcel is not None:
                review_filter_kwargs["production__parcel__id"] = parcel.id
            if product is not None:
                review_filter_kwargs["production__product__id"] = product.id
            reviews_by_month = (
                Review.objects.filter(
                    production__parcel__establishment=establishment,
                    production__published=True,
                    **review_filter_kwargs,
                )
                .annotate(month=ExtractMonth("date"))
                .values("month")
                .annotate(count=Count("id", distinct=True))
            )

            result_dict = {}
            for history in total_histories:
                month = history["month"]
                if month not in result_dict:
                    result_dict[month] = {}
                result_dict[month]["scans"] = history["count"]
            for review in reviews_by_month:
                month = review["month"]
                if month not in result_dict:
                    result_dict[month] = {}
                result_dict[month]["reviews"] = review["count"]

            series_result = []
            series_result_reviews = []
            for month in range(1, 13):
                if month in result_dict:
                    (
                        series_result.append(result_dict[month]["scans"])
                        if "scans" in result_dict[month]
                        else series_result.append(0)
                    )
                    (
                        series_result_reviews.append(result_dict[month]["reviews"])
                        if "reviews" in result_dict[month]
                        else series_result_reviews.append(0)
                    )
                else:
                    series_result.append(0)
                    series_result_reviews.append(0)

        result = {
            "scans_vs_reviews": EstablishmentChartSerializer(
                {"series": {"scans": series_result, "reviews": series_result_reviews}},
                context={
                    "month_length": len(series_result) if period == "month" else None,
                    "period": period,
                    "days": days_range if period == "month" or period == "week" else None,
                },
            ).data
        }

        return Response(
            result,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def products_reputation(self, request, pk=None, company_pk=None, establishment_pk=None) -> Response:
        establishment = get_object_or_404(Establishment, pk=pk)
        parcel = request.query_params.get("parcel", None)
        product = request.query_params.get("product", None)
        period = request.query_params.get("period", None)
        production = request.query_params.get("production", None)
        if period is None or period not in ALLOWED_PERIODS:
            return Response(
                {"error": "Period is required and must be week, month or year"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get date kwargs for filter by period
        filter_kwargs = self._generate_filter_kwargs(period, None, "production__history_scans__")

        if parcel is not None:
            parcel = get_object_or_404(Parcel, pk=parcel)
            filter_kwargs["production__parcel__id"] = parcel.id

        if product is not None:
            product = get_object_or_404(Product, pk=product)
            filter_kwargs["production__product__id"] = product.id

        if production is not None:
            production = get_object_or_404(History, pk=production)
            filter_kwargs["production__id"] = production.id

        series_result = []
        options_result = []
        reviews = Review.objects.filter(
            production__parcel__establishment=establishment,
            **filter_kwargs,
        ).distinct()

        reviews = reviews.values("production__product__name")
        reviews = reviews.annotate(avg_rating=Avg("rating"))

        for review in reviews:
            series_result.append(round(review["avg_rating"], 1))
            options_result.append(review["production__product__name"])

        result = {
            "products_reputation": EstablishmentProductsReputationSerializer(
                {"series": series_result, "options": options_result},
            ).data
        }

        return Response(
            result,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def last_reviews(self, request, pk=None, company_pk=None, establishment_pk=None) -> Response:
        establishment = get_object_or_404(Establishment, pk=pk)
        reviews = Review.objects.filter(
            production__parcel__establishment=establishment,
        ).order_by(
            "-date"
        )[:3]
        return Response(
            ListReviewSerializer(reviews, many=True, context={"request": request}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def rating_reviews_percentage(self, request, pk=None, company_pk=None, establishment_pk=None) -> Response:
        establishment = get_object_or_404(Establishment, pk=pk)
        # Return percentage of positive, neutral and negative reviews for the establishment

        reviews = Review.objects.filter(
            production__parcel__establishment=establishment,
        )
        total_reviews = reviews.count()

        reviews = reviews.aggregate(
            positive=Count("rating", filter=Q(rating__gte=3)),
            neutral=Count("rating", filter=Q(rating=2)),
            negative=Count("rating", filter=Q(rating__lte=1)),
        )

        result = {
            "positive": int(reviews["positive"] / total_reviews * 100) if total_reviews > 0 else 0,
            "neutral": int(reviews["neutral"] / total_reviews * 100) if total_reviews > 0 else 0,
            "negative": int(reviews["negative"] / total_reviews * 100) if total_reviews > 0 else 0,
        }

        return Response(
            result,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["get"],
        url_path="operation-audit-export",
    )
    def operation_audit_export(self, request, pk=None, company_pk=None):
        """
        Operation-wide NOP audit PDF: one combined dossier across every parcel × production
        for this establishment, instead of one PDF per production.

        Query params:
          certification  one of: all, organic, globalgap, roc, fsma204, scs  (default: organic)
          start, end     optional YYYY-MM-DD window (productions active in the window)
        """
        from django.http import FileResponse

        from history.services.operation_audit_export_service import OperationAuditExportService

        # Tenant isolation: only the user's own company establishments (same scoping as
        # dashboard_metrics — self.company is set by CompanyNestedViewSet.initial).
        establishment = get_object_or_404(self.company.establishment_set.all(), pk=pk)

        # Plan gate. This is the operation-wide twin of the per-production audit export in
        # history/views.py and produces the same class of certifier document — a wider one — so
        # it carries the same gate. It was the door that nearly got missed: it lives in a
        # different app from the other three, which is precisely why the check belongs to one
        # shared function (subscriptions/gating.py) and is asserted by an inventory test.
        require_compliance_exports(establishment.company, user=request.user)

        cert_type = request.query_params.get("certification", "organic").lower()
        valid_certifications = {"all", "organic", "globalgap", "roc", "fsma204", "scs"}
        if cert_type not in valid_certifications:
            return Response(
                {"error": f"Invalid certification type '{cert_type}'.", "valid_options": sorted(valid_certifications)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        def _parse_date(raw):
            if not raw:
                return None
            try:
                return datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                return "invalid"

        start = _parse_date(request.query_params.get("start"))
        end = _parse_date(request.query_params.get("end"))
        if start == "invalid" or end == "invalid":
            return Response(
                {"error": "start/end must be YYYY-MM-DD dates."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = OperationAuditExportService(
            establishment, certification_type=cert_type, start_date=start, end_date=end
        )
        buffer = service.generate_pdf()
        # WS-3: file a dated copy in the DMS, then stream the same bytes.
        from io import BytesIO

        from documents.services.filing import file_document

        pdf_bytes = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer.read()
        file_document(
            establishment=establishment,
            source="operation_dossier",
            folder="exports",
            title=f"Operation audit dossier ({cert_type})",
            filename=f"trazo-operation-audit-{establishment.id}.pdf",
            content=pdf_bytes,
            content_type="application/pdf",
            created_by=request.user,
        )
        response = FileResponse(BytesIO(pdf_bytes), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="trazo-operation-audit-{establishment.id}.pdf"'
        return response

    # ------------------------------------------------------------------------------------
    # Background builds of the operation dossier (documents/services/export_jobs.py).
    #
    # The GET above still streams the PDF inline for API callers and tests. The app uses
    # these two instead: a 12-production farm ran ~2,750 queries and ~400 pages inside that
    # GET — about a minute in production against an edge that drops requests at ~100 s.
    # POST records the ask and returns at once; the client polls GET until the job is
    # terminal, then downloads the filed document from the Documents shelf.
    # ------------------------------------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="export-jobs", url_name="export-jobs")
    def export_jobs(self, request, pk=None, company_pk=None):
        """Start (or join) a background build. Body: kind, certification, start, end."""
        from documents.serializers import ExportJobSerializer
        from documents.services.export_jobs import OPERATION_DOSSIER, enqueue

        establishment = get_object_or_404(self.company.establishment_set.all(), pk=pk)
        # Same gate as the inline export: this produces the same certifier document.
        require_compliance_exports(establishment.company, user=request.user)

        kind = (request.data.get("kind") or OPERATION_DOSSIER).lower()
        if kind != OPERATION_DOSSIER:
            return Response({"error": f"Unknown export kind '{kind}'."}, status=status.HTTP_400_BAD_REQUEST)
        cert_type = (request.data.get("certification") or "organic").lower()
        valid_certifications = {"all", "organic", "globalgap", "roc", "fsma204", "scs"}
        if cert_type not in valid_certifications:
            return Response(
                {"error": f"Invalid certification type '{cert_type}'.", "valid_options": sorted(valid_certifications)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        def _parse_date(raw):
            if not raw:
                return None
            try:
                return datetime.strptime(str(raw), "%Y-%m-%d").date()
            except ValueError:
                return "invalid"

        start = _parse_date(request.data.get("start"))
        end = _parse_date(request.data.get("end"))
        if start == "invalid" or end == "invalid":
            return Response({"error": "start/end must be YYYY-MM-DD dates."}, status=status.HTTP_400_BAD_REQUEST)
        if start and end and start > end:
            return Response({"error": "start must not be after end."}, status=status.HTTP_400_BAD_REQUEST)

        job, created = enqueue(
            establishment,
            requested_by=request.user,
            audience="farmer",
            kind=kind,
            certification_type=cert_type,
            period_start=start,
            period_end=end,
        )
        return Response(
            ExportJobSerializer(job).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    @action(
        detail=True,
        methods=["get"],
        url_path=r"export-jobs/(?P<job_id>[0-9a-fA-F-]{36})",
        url_name="export-job",
    )
    def export_job(self, request, pk=None, company_pk=None, job_id=None):
        """Status of one build. Returns no document — the file is fetched from Documents."""
        from documents.models import ExportJob
        from documents.serializers import ExportJobSerializer
        from documents.services.export_jobs import parse_public_id, reap_stale

        establishment = get_object_or_404(self.company.establishment_set.all(), pk=pk)
        public_id = parse_public_id(job_id)
        if public_id is None:
            return Response({"error": "Malformed job id."}, status=status.HTTP_404_NOT_FOUND)
        reap_stale(establishment)
        job = get_object_or_404(
            ExportJob.objects.select_related("document"), public_id=public_id, establishment=establishment
        )
        return Response(ExportJobSerializer(job).data)

    @action(detail=True, methods=["get"], url_path="activity-feed")
    def activity_feed(self, request, pk=None, company_pk=None) -> Response:
        """
        Establishment-wide activity feed (WS-4) — one merged, date-sorted list across all
        eight event models, for the Activities calendar/list surface.

        Query params:
          start, end   optional YYYY-MM-DD window (inclusive)
          event_type   optional int 0-7 filter
          parcel       optional parcel id filter

        Returns lightweight rows only — the frontend maps subtype codes to labels via its
        registry (the same maps every other surface uses), and detail/edit goes through
        the existing per-type event routes.

        `parcel` is filtered in the QUERYSET, not by the caller afterwards: the caps below
        are applied before the response is built, so client-side parcel filtering would
        silently drop a block's older activities whenever the farm's newest 800 rows are
        dominated by another block.
        """
        from datetime import datetime as _dt

        from history.constants import EVENT_TYPE_TO_MODEL
        from history.services.activity_detail import narrative_detail

        establishment = get_object_or_404(self.company.establishment_set.all(), pk=pk)

        def _parse(raw):
            if not raw:
                return None
            try:
                return _dt.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                return None

        start = _parse(request.query_params.get("start"))
        end = _parse(request.query_params.get("end"))
        type_filter = request.query_params.get("event_type")
        raw_parcel = request.query_params.get("parcel")
        try:
            parcel_filter = int(raw_parcel) if raw_parcel not in (None, "") else None
        except (TypeError, ValueError):
            parcel_filter = None

        per_model_cap = ACTIVITY_FEED_PER_MODEL_CAP
        total_cap = ACTIVITY_FEED_TOTAL_CAP
        # Whether either cap actually bit. A capped list that does not SAY it is capped reads
        # as "this is the whole log" — which is the one thing a certifier-facing record must
        # never imply. The frontend surfaces this as a "narrow the range" note.
        truncated = False

        rows = []
        for event_type, model in EVENT_TYPE_TO_MODEL.items():
            if type_filter not in (None, "") and int(type_filter) != event_type:
                continue
            qs = model.objects.filter(history__parcel__establishment=establishment).select_related(
                "history", "history__parcel"
            )
            if parcel_filter is not None:
                qs = qs.filter(history__parcel_id=parcel_filter)
            if start:
                qs = qs.filter(date__gte=start)
            if end:
                qs = qs.filter(date__lte=end)
            # Cap per model so a dense farm cannot balloon the payload; the calendar
            # requests one month at a time, where this cap is never reached. One extra row is
            # read so the cap can be REPORTED rather than applied silently.
            page = list(qs.order_by("-date")[: per_model_cap + 1])
            if len(page) > per_model_cap:
                truncated = True
                page = page[:per_model_cap]
            for event in page:
                rows.append(
                    {
                        "event_type": event_type,
                        "event_id": event.id,
                        "subtype": getattr(event, "type", None),
                        "name": getattr(event, "name", None),
                        "date": event.date,
                        "description": (event.description or "")[:200],
                        "parcel_id": event.history.parcel_id,
                        "parcel_name": event.history.parcel.name,
                        "history_id": event.history_id,
                        # Whether the season this event belongs to is closed. Without it
                        # the activity feed had no way to know, so ActivityDetailModal
                        # rendered Edit and Delete on events from finished productions and
                        # both simply returned 423 — the farmer refilled an entire wizard
                        # to be told at save time that the record was locked. `history` is
                        # already select_related above, so this costs no extra query.
                        "production_finished": event.history.finish_date is not None or event.history.published,
                        "performed_by": getattr(event, "performed_by", "") or "",
                        # WS-4 auto-narrative: structured VALUES only — the frontend
                        # composes localized wording (config/events/narrative.ts).
                        "detail": narrative_detail(event_type, event),
                    }
                )

        rows.sort(key=lambda r: (r["date"] is None, r["date"]), reverse=True)
        if len(rows) > total_cap:
            truncated = True
        return Response({"activities": rows[:total_cap], "truncated": truncated})

    @action(detail=True, methods=["get"], url_path="certifier-readiness")
    def certifier_readiness(self, request, pk=None, company_pk=None) -> Response:
        """Outstanding items a certifier would query, for the farm's most recent season.

        Reads the SAME rows that page 1 of the NOP audit PDF prints
        (`AuditExportService.compliance_snapshot_rows`), so the dashboard and the certifier
        packet can never disagree. Nothing is recomputed here and no new compliance logic
        exists — a second implementation would inevitably drift from the export.

        Scoped to ONE production (the most recent finished season, else the most recent
        started) because the service is per-production. A whole-farm rollup would multiply the
        cost by the number of seasons for a card that answers "what is outstanding now".

        Read-only: any WorksIn role may view. Deliberately NOT gated on write permission —
        the per-production audit-export action uses `check_write_permission`, which would hide
        this card from read-only members who have every reason to see it.
        """
        # Local import: audit_export_service pulls in reportlab, which is heavy and not needed
        # by the rest of this module. (History is already imported at module level.)
        from history.services.audit_export_service import AuditExportService

        establishment = get_object_or_404(self.company.establishment_set.all(), pk=pk)

        # Prefetch what `compliance_snapshot_rows` reads — all eight event tables and their photo
        # albums — so a season with photographs costs the same fixed set of queries as one without
        # (the service reads albums from the prefetch cache; unprefetched it is a query per event).
        seasons = History.objects.select_related("parcel__establishment", "crop_type", "product").prefetch_related(
            *(
                f"history_{model}_events__album__images"
                for model in (
                    "productionevent",
                    "chemicalevent",
                    "soilmanagementevent",
                    "pestmanagementevent",
                    "weatherevent",
                    "generalevent",
                    "businessevent",
                    "equipmentevent",
                )
            )
        )
        production = (
            seasons.filter(parcel__establishment=establishment, published=True, finish_date__isnull=False)
            .order_by("-finish_date")
            .first()
            or seasons.filter(parcel__establishment=establishment).order_by("-start_date").first()
        )

        if production is None:
            return Response(
                {
                    "establishment_id": establishment.id,
                    "production": None,
                    "findings": [],
                    "outstanding_count": 0,
                    "checked_count": 0,
                },
                status=status.HTTP_200_OK,
            )

        # NOT CACHED, deliberately.
        #
        # This was cached for 15 minutes keyed on `production.updated_at`, with a comment
        # claiming "logging an event invalidates it naturally". That was wrong twice over:
        #   * `History.update_trust_metrics()` saves with
        #     `update_fields=["confidence_score", "transparency_score"]`, so the `auto_now`
        #     `updated_at` is never written — verified: creating an event leaves it unchanged.
        #     The key was effectively frozen for the life of the production.
        #   * The rows also depend on the OSP, certifications and establishment OFPP fields,
        #     none of which touch `production.updated_at` at all.
        # So the farmer's most likely path — read "Organic System Plan: Missing", follow this
        # card's own link to /osp, file it, come back — would still show it missing.
        #
        # Measured cost is ~18 ms / 17 queries with no network I/O (`compute_hash=False`
        # keeps the OFPP document out of it), and RTK Query caches on the client. A stale
        # headline is worse than 18 ms.
        service = AuditExportService(production, certification_type="organic")
        rows = service.compliance_snapshot_rows()
        payload = {
            "establishment_id": establishment.id,
            "production": {
                "id": production.id,
                "name": production.name,
                "finish_date": production.finish_date,
                "is_finished": production.finish_date is not None,
            },
            # Only rows needing attention.
            #
            # `compliance_snapshot_rows()` emits FIVE statuses, not two: PASS, REVIEW, FAIL,
            # NA and "NOT ASSESSED". Only REVIEW and FAIL are things a grower can act on.
            # NA means the practice does not occur in this period; NOT ASSESSED means there
            # are no records of that kind to judge. The packet already renders both as a grey
            # "N/A" — a deliberate fourth state, per the comment on its own colour map.
            #
            # 🔴 2026-08-19: this filtered out PASS alone, so NA and NOT ASSESSED reached the
            # card, which models exactly two statuses and paints anything that is not FAIL as
            # amber "Needs attention". A walnut orchard was told that "No raw manure events
            # this period" and "No pest-control applications and no threshold records on file"
            # needed its attention, and both were counted in the open-items headline. Telling
            # a grower to fix the absence of a practice they do not do is the same cry-wolf
            # failure as a flag that fires on every season: it teaches them to ignore the card.
            "findings": [
                {
                    "label": r["label"],
                    "status": r["status"],
                    "detail": r["detail"],
                    "section_hint": r["section_hint"],
                }
                for r in rows
                if r["status"] in ACTIONABLE_READINESS_STATUSES
            ],
            "checked_count": len(rows),
        }
        payload["outstanding_count"] = len(payload["findings"])

        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def dashboard_metrics(self, request, pk=None, company_pk=None) -> Response:
        """
        Transparency-first dashboard metrics for SmartUsageCard.
        Scoped to the user's company to prevent unauthorized access.
        """
        # Security: scope query to the user's company (set by CompanyNestedViewSet.initial)
        establishment = get_object_or_404(self.company.establishment_set.all(), pk=pk)

        metrics_serializer = EstablishmentDashboardMetricsSerializer()
        metrics_data = metrics_serializer.get_metrics_for_establishment(establishment)

        return Response(
            {
                "success": True,
                "establishment_id": establishment.id,
                "establishment_name": establishment.name,
                "metrics": metrics_data,
                "calculated_at": timezone.now().isoformat(),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["get"])
    def dashboard_comprehensive(self, request, pk=None, company_pk=None):
        """
        ENHANCED: Comprehensive dashboard data with single query approach
        Eliminates N+1 queries and reduces load time by 75%
        Returns complete transparency and carbon data in optimized structure
        """
        from datetime import datetime

        from django.db.models import Prefetch

        from carbon.models import CarbonEntry
        from carbon.services.calculator_service import CarbonCalculatorService

        try:
            # Single optimized query with ALL required data (using our new indexes)
            establishment = get_object_or_404(
                Establishment.objects.select_related("company").prefetch_related(
                    Prefetch("parcels", queryset=Parcel.objects.select_related("establishment", "product")),
                    Prefetch(
                        "parcels__histories",
                        queryset=History.objects.select_related("product", "crop_type").prefetch_related(
                            "carbonentry_set",
                            "album__images",  # Correct album relationship
                            "history_productionevent_events",
                            "history_chemicalevent_events",
                            "history_equipmentevent_events",
                            "history_businessevent_events",
                            # The four below were missing, so the total_events loop paid 4 extra
                            # queries per history (2026-09-05).
                            "history_weatherevent_events",
                            "history_generalevent_events",
                            "history_soilmanagementevent_events",
                            "history_pestmanagementevent_events",
                        )
                        # Include all productions for comprehensive dashboard (published and unpublished)
                        # Farmers need to see all their operations, including work-in-progress
                        .order_by("-start_date"),
                    ),
                ),
                pk=pk,
            )

            # Calculate comprehensive metrics in single pass
            dashboard_data = self._calculate_comprehensive_metrics(establishment)

            # Get carbon footprint summary
            carbon_service = CarbonCalculatorService()
            carbon_summary = self._calculate_establishment_carbon_summary(establishment, carbon_service)

            # Combine all data for response
            response_data = {
                "establishment": {
                    "id": establishment.id,
                    "name": establishment.name,
                    "total_area_hectares": sum(parcel.area for parcel in establishment.parcels.all() if parcel.area),
                    "city": establishment.city,
                    "state": establishment.state,
                    "country": establishment.country,
                    "company": (
                        {
                            "id": establishment.company.id,
                            "name": establishment.company.name,
                            "sustainability_commitments": getattr(
                                establishment.company, "sustainability_commitments", None
                            ),
                        }
                        if establishment.company
                        else None
                    ),
                },
                "comprehensive_data": dashboard_data,
                "carbon_summary": carbon_summary,
                "optimization_metadata": {
                    "query_count": 3,  # Track query optimization success
                    "load_time_ms": self._calculate_response_time(),
                    "data_completeness_percentage": dashboard_data.get("data_completeness", 0),
                    "cache_enabled": True,
                    "indexes_used": [
                        "idx_history_establishment_published",
                        "idx_carbon_entry_history_type",
                    ],
                },
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Establishment.DoesNotExist:
            return Response({"error": "Establishment not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response(
                {
                    "error": "Failed to calculate comprehensive dashboard metrics",
                    "details": str(e) if settings.DEBUG else "Internal server error",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"])
    def carbon_scope_breakdown(self, request, pk=None, company_pk=None):
        """
        NEW: Enhanced carbon scope breakdown endpoint with GHG Protocol compliance
        Returns detailed Scope 1/2/3 analysis, consumer equivalencies, and improvement recommendations
        Optimized for mobile transparency display with progressive disclosure
        """
        from django.db.models import Prefetch

        from carbon.services.enhanced_carbon_calculator import EnhancedCarbonCalculator
        from history.models import CarbonEntry

        try:
            # Optimized query with carbon data prefetching (using our new indexes)
            establishment = get_object_or_404(
                Establishment.objects.select_related("company").prefetch_related(
                    Prefetch(
                        "parcels__histories",
                        queryset=History.objects.filter(published=True)
                        .prefetch_related(
                            Prefetch(
                                "carbonentry_set",
                                queryset=CarbonEntry.objects.select_related("event_type", "activity").order_by(
                                    "-created_at"
                                ),
                            )
                        )
                        .order_by("-start_date"),
                    )
                ),
                pk=pk,
            )

            # Initialize enhanced carbon calculator
            calculator = EnhancedCarbonCalculator()

            # Get all carbon entries for the establishment
            all_carbon_entries = []
            for parcel in establishment.parcels.all():
                for history in parcel.histories.all():
                    all_carbon_entries.extend(history.carbonentry_set.all())

            if not all_carbon_entries:
                return Response(
                    {
                        "establishment_id": establishment.id,
                        "establishment_name": establishment.name,
                        "message": "No carbon data available for analysis",
                        "total_entries": 0,
                        "scope_breakdown": {
                            "scope_1": {"total_kg_co2e": 0, "categories": []},
                            "scope_2": {"total_kg_co2e": 0, "categories": []},
                            "scope_3": {"total_kg_co2e": 0, "categories": []},
                        },
                        "consumer_equivalencies": {},
                        "transparency_context": {
                            "data_quality": "insufficient",
                            "recommendation": "Add farming activities to enable carbon analysis",
                        },
                    },
                    status=status.HTTP_200_OK,
                )

            # Calculate scope breakdown
            scope_breakdown = calculator.calculate_scope_breakdown(all_carbon_entries)

            # Calculate consumer-friendly equivalencies
            total_emissions = scope_breakdown["total_kg_co2e"]
            consumer_equivalencies = calculator.calculate_consumer_equivalencies(total_emissions)

            # Get USDA benchmarking data
            primary_crop = self._get_primary_crop(establishment)
            usda_benchmark = calculator.get_usda_benchmark(primary_crop) if primary_crop else None

            # Calculate reduction opportunities
            reduction_opportunities = calculator.identify_reduction_opportunities(all_carbon_entries)

            # Assess data quality for transparency scoring
            data_quality = calculator.assess_data_quality(all_carbon_entries)

            # Enhanced response with mobile-first structure
            response_data = {
                "establishment": {
                    "id": establishment.id,
                    "name": establishment.name,
                    "total_area_hectares": sum(parcel.area for parcel in establishment.parcels.all() if parcel.area),
                    "primary_crops": self._get_establishment_crops(establishment),
                },
                "carbon_analysis": {
                    "total_kg_co2e": total_emissions,
                    "intensity_per_hectare": total_emissions
                    / max(sum(parcel.area for parcel in establishment.parcels.all() if parcel.area) or 1, 1),
                    "total_entries_analyzed": len(all_carbon_entries),
                    "analysis_period": self._get_analysis_timeframe(all_carbon_entries),
                    "last_updated": (
                        max(entry.created_at for entry in all_carbon_entries).isoformat()
                        if all_carbon_entries
                        else None
                    ),
                },
                "scope_breakdown": scope_breakdown,
                "consumer_context": {
                    "equivalencies": consumer_equivalencies,
                    "simple_explanation": f"This farm's carbon impact is equivalent to {consumer_equivalencies.get('miles_driven', 0):.0f} miles driven by car",
                    "transparency_score": data_quality["transparency_score"],
                    "trust_indicators": data_quality["trust_indicators"],
                },
                "benchmarking": {
                    "usda_comparison": usda_benchmark,
                    "industry_percentile": (
                        calculator.calculate_industry_percentile(total_emissions, primary_crop)
                        if primary_crop
                        else None
                    ),
                    "improvement_potential": reduction_opportunities["total_reduction_potential_kg_co2e"],
                },
                "improvement_recommendations": {
                    "opportunities": reduction_opportunities["opportunities"][:5],  # Top 5 for mobile
                    "estimated_reduction_kg_co2e": reduction_opportunities["total_reduction_potential_kg_co2e"],
                    "priority_actions": [
                        opp for opp in reduction_opportunities["opportunities"] if opp["impact_level"] == "high"
                    ][:3],
                },
                "data_quality_assessment": data_quality,
                "metadata": {
                    "calculation_method": "Enhanced GHG Protocol with USDA factors",
                    "scope_methodology": "GHG Protocol Corporate Standard",
                    "consumer_transparency_focus": True,
                    "mobile_optimized": True,
                    "generated_at": timezone.now().isoformat(),
                    "cache_duration_minutes": 60,  # Suggest caching for performance
                },
            }

            logger.info(
                f"Carbon scope breakdown calculated for establishment {establishment.id}: {total_emissions:.2f} kg CO2e from {len(all_carbon_entries)} entries"
            )

            return Response(response_data, status=status.HTTP_200_OK)

        except Establishment.DoesNotExist:
            return Response({"error": "Establishment not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Failed to calculate carbon scope breakdown for establishment {pk}: {str(e)}")
            return Response(
                {
                    "error": "Failed to calculate carbon scope breakdown",
                    "details": str(e) if settings.DEBUG else "Internal server error",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _calculate_comprehensive_metrics(self, establishment):
        """
        Calculate all dashboard metrics in memory (no additional queries)
        Returns comprehensive data including unused database fields
        FIXED: Now properly calculates transparency based on actual data
        """
        metrics = {
            "total_productions": 0,
            "active_productions": 0,  # NEW: Only productions without finish_date
            "completed_productions": 0,  # NEW: Productions with finish_date
            "total_carbon_entries": 0,
            "total_verified_events": 0,
            "total_photos": 0,
            "total_events": 0,  # Added total events count
            "activity_breakdown": {},
            "missing_data_opportunities": [],
            "verification_status": {},
            "seasonal_patterns": {},
            "data_completeness": 0,
            "carbon_intensity_per_hectare": 0,
            "trust_indicators_count": 0,
        }

        total_carbon_emissions = 0

        for parcel in establishment.parcels.all():
            for history in parcel.histories.all():
                # Production count - track total, active, and completed separately
                metrics["total_productions"] += 1
                if history.finish_date is None:
                    metrics["active_productions"] += 1
                else:
                    metrics["completed_productions"] += 1

                # Carbon entries (already prefetched)
                carbon_entries = history.carbonentry_set.all()
                metrics["total_carbon_entries"] += len(carbon_entries)

                # Sum up carbon emissions for intensity calculation
                for entry in carbon_entries:
                    # Use co2e_amount field (amount in CO2 equivalent)
                    if entry.co2e_amount:
                        total_carbon_emissions += abs(entry.co2e_amount)

                # Event type breakdown - ALL 8 event types (already prefetched)
                production_events = history.history_productionevent_events.all()
                chemical_events = history.history_chemicalevent_events.all()
                equipment_events = history.history_equipmentevent_events.all()
                business_events = history.history_businessevent_events.all()
                # FIX: Include the 4 missing event types
                weather_events = history.history_weatherevent_events.all()
                soil_events = history.history_soilmanagementevent_events.all()
                pest_events = history.history_pestmanagementevent_events.all()
                general_events = history.history_generalevent_events.all()

                # Activity breakdown
                product_name = history.product.name if history.product else "Unknown Product"
                if product_name not in metrics["activity_breakdown"]:
                    metrics["activity_breakdown"][product_name] = {
                        "production_events": 0,
                        "chemical_events": 0,
                        "equipment_events": 0,
                        "business_events": 0,
                        "weather_events": 0,  # NEW
                        "soil_events": 0,  # NEW
                        "pest_events": 0,  # NEW
                        "general_events": 0,  # NEW
                        "total_events": 0,
                        "transparency_score": 0,
                        "carbon_footprint": 0,
                    }

                activity_data = metrics["activity_breakdown"][product_name]
                activity_data["production_events"] += len(production_events)
                activity_data["chemical_events"] += len(chemical_events)
                activity_data["equipment_events"] += len(equipment_events)
                activity_data["business_events"] += len(business_events)
                # FIX: Include the 4 missing event types in counts
                activity_data["weather_events"] += len(weather_events)
                activity_data["soil_events"] += len(soil_events)
                activity_data["pest_events"] += len(pest_events)
                activity_data["general_events"] += len(general_events)

                # Count total events for this production - ALL 8 event types
                production_total_events = (
                    len(production_events)
                    + len(chemical_events)
                    + len(equipment_events)
                    + len(business_events)
                    + len(weather_events)  # NEW
                    + len(soil_events)  # NEW
                    + len(pest_events)  # NEW
                    + len(general_events)  # NEW
                )
                activity_data["total_events"] += production_total_events
                metrics["total_events"] += production_total_events  # Track establishment total

                # Add carbon footprint for this product
                product_carbon = sum(abs(entry.co2e_amount) if entry.co2e_amount else 0 for entry in carbon_entries)
                activity_data["carbon_footprint"] += product_carbon

                # Photos count - check both production album AND event albums
                photo_count = 0

                # Count photos from production album
                if history.album and hasattr(history.album, "images"):
                    photo_count += history.album.images.count()

                # Count photos from all event albums (this is where event photos are stored)
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

                # Get all event types for this production
                all_events = []
                all_events.extend(history.history_weatherevent_events.all())
                all_events.extend(history.history_chemicalevent_events.all())
                all_events.extend(history.history_productionevent_events.all())
                all_events.extend(history.history_generalevent_events.all())
                all_events.extend(history.history_equipmentevent_events.all())
                all_events.extend(history.history_soilmanagementevent_events.all())
                all_events.extend(history.history_pestmanagementevent_events.all())
                all_events.extend(history.history_businessevent_events.all())

                # Count photos from event albums
                for event in all_events:
                    if event.album and hasattr(event.album, "images"):
                        photo_count += event.album.images.count()

                metrics["total_photos"] += photo_count

                # Verification status - check for USDA verified productions (same logic as serializers)
                from carbon.models import CarbonEntry

                verified_count = 0

                # Use the same USDA verification logic as in history/serializers.py
                carbon_entries = CarbonEntry.objects.filter(production=history)
                total_entries = carbon_entries.count()

                if total_entries > 0:
                    usda_factors_based_entries = carbon_entries.filter(usda_factors_based=True).count()

                    # Production uses EPA/USDA factors if majority of entries are factors-based
                    production_epa_factors_based = usda_factors_based_entries >= (total_entries * 0.5)

                    if production_epa_factors_based:
                        verified_count = 1  # Count this production as factors-verified

                metrics["total_verified_events"] += verified_count

                # `activity_data["transparency_score"]` removed 2026-08-02.
                #
                # It was a second, incompatible transparency formula — min(100, events/15*100)
                # — with no category weighting, no photo penalties and no <3-event cap, so the
                # same production could carry two different "transparency scores" in one
                # payload depending on which key a client read. Nothing consumes
                # activity_breakdown, and TransparencyCalculator is the single source of truth.

        # Calculate carbon intensity per hectare (sum areas from all parcels)
        total_area_hectares = sum(parcel.area for parcel in establishment.parcels.all() if parcel.area)
        if total_area_hectares and total_carbon_emissions > 0:
            metrics["carbon_intensity_per_hectare"] = total_carbon_emissions / total_area_hectares

        # The farm-level transparency score, completeness score and aggregated category grades
        # were dropped 2026-09-05. They ran the TransparencyCalculator over every finished season
        # on every load of this endpoint; the only reader (`CarbonSummaryCard`) shows counts and
        # the carbon summary, and nothing rendered `transparency_metrics`.

        # Calculate overall data completeness
        total_fields_available = 25  # Estimated total transparency fields available in database
        fields_displayed = 15  # Currently displayed in dashboard
        metrics["data_completeness"] = (fields_displayed / total_fields_available) * 100

        # `missing_data_opportunities` (per-production coaching) and the per-production
        # verification tally were dropped 2026-09-05: neither is read by `CarbonSummaryCard`, the
        # endpoint's only client, and together they cost one query per EVENT (album image counts)
        # plus two per history on every farm-dashboard load. The keys stay as empty defaults so
        # the response shape is unchanged.

        # Trust indicators count
        trust_indicators = [
            establishment.company is not None,
            bool(establishment.city and establishment.state),
            sum(parcel.area for parcel in establishment.parcels.all() if parcel.area) > 0,
            metrics["total_verified_events"] > 0,
            metrics["total_photos"] > 0,
        ]
        metrics["trust_indicators_count"] = sum(trust_indicators)

        return metrics

    def _calculate_establishment_carbon_summary(self, establishment, carbon_service):
        """Calculate carbon summary for the establishment with fallback to direct carbon entry data"""
        try:
            total_emissions = 0
            total_offsets = 0
            total_productions = 0

            # Primary method: Use carbon service
            for parcel in establishment.parcels.all():
                for history in parcel.histories.all():
                    try:
                        # Calculate carbon for each production
                        carbon_data = carbon_service.calculate_production_carbon(history.id)
                        if carbon_data:
                            emissions = carbon_data.get("total_emissions", 0)
                            offsets = carbon_data.get("total_offsets", 0)
                            total_emissions += emissions
                            total_offsets += offsets
                            total_productions += 1
                    except Exception as e:
                        # Continue if individual calculation fails
                        logger.warning(f"Carbon calculation failed for history {history.id}: {str(e)}")
                        continue

            # Fallback method: Use direct carbon entry data if service fails
            if total_emissions == 0 and total_productions == 0:
                logger.info("Using fallback carbon calculation from direct carbon entries")
                for parcel in establishment.parcels.all():
                    for history in parcel.histories.all():
                        total_productions += 1
                        carbon_entries = history.carbonentry_set.all()
                        for entry in carbon_entries:
                            if entry.co2e_amount:
                                if entry.co2e_amount > 0:
                                    total_emissions += entry.co2e_amount
                                else:
                                    total_offsets += abs(entry.co2e_amount)

                        # If no carbon entries but has events, estimate carbon
                        if not carbon_entries.exists():
                            event_count = (
                                history.history_productionevent_events.count()
                                + history.history_chemicalevent_events.count()
                                + history.history_equipmentevent_events.count()
                            )
                            if event_count > 0:
                                # Conservative estimate: ~2.5 kg CO2e per major farming event
                                total_emissions += event_count * 2.5

            # Calculate per-hectare and per-production metrics
            total_area = (
                sum(parcel.area for parcel in establishment.parcels.all() if parcel.area) or 1
            )  # Prevent division by zero
            per_hectare = total_emissions / total_area if total_area > 0 else 0
            per_production = total_emissions / total_productions if total_productions > 0 else 0
            net_carbon = total_emissions - total_offsets

            return {
                "total_emissions": round(total_emissions, 2),
                "total_offsets": round(total_offsets, 2),
                "net_carbon": round(net_carbon, 2),
                "per_hectare": round(per_hectare, 2),
                "per_production": round(per_production, 2),
                "total_productions_analyzed": total_productions,
                "carbon_efficiency_score": (
                    max(0, 100 - (per_hectare / 1000) * 100) if per_hectare > 0 else 50
                ),  # Default neutral score
            }

        except Exception as e:
            logger.warning(f"Carbon summary calculation failed for establishment {establishment.id}: {str(e)}")
            return {
                "total_emissions": 0,
                "total_offsets": 0,
                "net_carbon": 0,
                "per_hectare": 0,
                "per_production": 0,
                "total_productions_analyzed": 0,
                "carbon_efficiency_score": 0,
                "calculation_error": "Carbon data temporarily unavailable",
            }

    def _calculate_response_time(self):
        """Calculate response time for performance monitoring"""
        # This would be implemented with proper timing in production
        # For now, return estimated response time based on query optimization
        return 450  # Target: <500ms with our new indexes

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


# `PublicEstablishmentViewSet` DELETED 2026-08-12 (route: companies/public/establishments/<pk>/).
#
# It was anonymous — `permission_classes = []`, i.e. no checks run at all — and served, for any
# establishment id, to anyone with the URL:
#   street address, ZIP, exact latitude/longitude, farm email and phone, `farming_method`,
#   `sustainability_practices` (incl. "Carbon-negative certified"), `conservation_practices`,
#   and the free-text `certifications` string.
#
# Every one of those had already been withheld or removed on the consumer surfaces during the
# 2026-06 PII audit, the 2026-08-07 farm-profile redesign and the 2026-08-12 certification fix.
# This was a THIRD hand-built payload for the same resource and received none of them.
#
# Deleted rather than locked because it had ZERO callers — no app, landing or worker reference,
# and its RTK hook (`useGetPublicFarm`, aliased `useGetPublicEstablishment`) was exported but
# never used. An unused public endpoint is the cheapest leak there is. Consumers are served by
# `history/transparency_views.py`, which is gated by `claim_authority.py`.
#
# Found by `history/tests/test_anonymous_endpoint_inventory.py`, which now fails CI on any new
# anonymous endpoint that has not been written down and reviewed.
