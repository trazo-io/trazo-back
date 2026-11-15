import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, Q
from django.db.models.functions import ExtractDay, ExtractMonth, ExtractWeekDay
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator

from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.permissions import CALLER_SCOPED, CompanyNestedViewSet, IsCompanyAdmin, scope_to_caller_companies
from history.models import History, HistoryScan
from history.retention import assert_deletable
from product.models import Parcel, Product
from product.serializers import ProductListOptionsSerializer
from reviews.models import Review
from reviews.serializers import ListReviewSerializer
from subscriptions.gating import require_compliance_exports
from subscriptions.permissions import HasEstablishmentCreationPermission
from users import team
from users.models import WorksIn
from users.serializers import CompanyMemberSerializer, MemberRoleSerializer
from users.signup_alerts import alert_new_company

logger = logging.getLogger(__name__)

from .constants import ALLOWED_PERIODS

# The compliance-snapshot statuses a grower can actually act on.
#
# `AuditExportService.compliance_snapshot_rows()` emits PASS, REVIEW, FAIL, NA and
# "NOT ASSESSED". The certifier-readiness card models two states (FAIL = missing,
# everything else = needs attention), so anything forwarded to it that is not genuinely
# actionable is displayed as an action item and counted in the headline.
ACTIONABLE_READINESS_STATUSES = frozenset({"REVIEW", "FAIL"})
from .models import Applicator, Company, Establishment
from .serializers import (
    ApplicatorSerializer,
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

    flat_route_tenancy = CALLER_SCOPED  # see backend/permissions.py; detail routes set self.company from pk

    def perform_destroy(self, instance):
        """A company cannot be deleted while any of its farms hold retained records."""
        assert_deletable("company", parcel__establishment__company=instance)
        super().perform_destroy(instance)

    # The nested SubscriptionSerializer reads `subscription.plan` and walks `subscription.addons`
    # (+ `.addon`) once per limit it computes; prefetched here that is one query instead of six.
    queryset = Company.objects.select_related("subscription__plan").prefetch_related("subscription__addons__addon")
    filter_backends = [filters.OrderingFilter]

    def initial(self, request, *args, **kwargs):
        # On this viewset the URL's own `pk` IS the company. `CompanyNestedViewSet` only sets
        # `self.company` from `company_pk`, and every permission in `backend/permissions.py`
        # returns True when `self.company` is None, so until 2026-09-28 any signed-in account
        # could list every company with its join code, read its members and PATCH it. Setting
        # the company here makes those permissions check membership as they were written to.
        if (pk := kwargs.get("pk")) is not None:
            self.company = get_object_or_404(Company, pk=pk)
        super().initial(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(company_workers__user=self.request.user).distinct()

    def get_permissions(self):
        if self.action in ["update", "partial_update", "destroy", "rotate_invitation_code", "member"]:
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
        alert_new_company(company, request.user)

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
        company = self.get_object()
        members = WorksIn.objects.filter(company=company).select_related("user", "company").order_by("pk")
        caller = next((row for row in members if row.user_id == request.user.pk), None)
        return Response(
            CompanyMemberSerializer(members, many=True, context={"caller_membership": caller}).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["patch", "delete"], url_path=r"members/(?P<member_id>[0-9]+)", url_name="member")
    def member(self, request, pk=None, company_pk=None, member_id=None):
        """Change one member's role (PATCH {"role": "CA"|"FM"|"VW"}) or remove them (DELETE).

        Company Admins of the URL's company only (`get_permissions`); the rules are `users.team`.
        The member is looked up INSIDE the URL's company, so another company's membership id gets
        the same 404 as an id that does not exist, before the body is read.

        Removal deletes the WorksIn row and nothing else: the records the person wrote stay, under
        their name. Their next request is refused, because every company permission and queryset
        reads WorksIn on each request; the JWT carries the account, never its memberships.
        """
        with transaction.atomic():
            # Lock the whole team and read the caller's row under the lock: of two admins removing or
            # demoting each other at once, the second finds its own row gone or demoted and is
            # refused (NOT_ADMIN), so one Company Admin always remains.
            rows = list(WorksIn.objects.select_for_update().filter(company=self.company).order_by("pk"))
            target = next((row for row in rows if str(row.pk) == member_id), None)
            if target is None:
                raise NotFound()
            caller = next((row for row in rows if row.user_id == request.user.pk), None)

            new_role = None
            if request.method == "PATCH":
                body = MemberRoleSerializer(data=request.data)
                body.is_valid(raise_exception=True)
                new_role = body.validated_data["role"]

            refusal = team.change_refusal(caller, target, new_role, rows)
            if refusal in (team.NOT_ADMIN, team.SETUP_OPERATOR_CALLER):
                raise PermissionDenied({"detail": team.REFUSALS[refusal], "code": refusal})
            if refusal:
                return Response({"detail": team.REFUSALS[refusal], "code": refusal}, status=status.HTTP_400_BAD_REQUEST)

            if request.method == "DELETE":
                logger.info(
                    "team: user %s removed membership %s (user %s, role %s) from company %s",
                    request.user.pk,
                    target.pk,
                    target.user_id,
                    target.role,
                    self.company.pk,
                )
                target.delete()
                return Response(status=status.HTTP_204_NO_CONTENT)

            if new_role != target.role:
                if target.role == WorksIn.COMPANY_ADMIN:
                    # A Company Admin reaches every farm without a farm list. Keep exactly that
                    # reach after the demotion, rather than whatever list the row happened to hold.
                    target.establishments_in_charge.set(self.company.establishment_set.all())
                logger.info(
                    "team: user %s changed membership %s (user %s) in company %s from %s to %s",
                    request.user.pk,
                    target.pk,
                    target.user_id,
                    self.company.pk,
                    target.role,
                    new_role,
                )
                target.role = new_role
                target.save(update_fields=["role"])

        return Response(
            CompanyMemberSerializer(target, context={"caller_membership": caller}).data, status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["post"], url_path="rotate-invitation-code")
    def rotate_invitation_code(self, request, pk=None, company_pk=None):
        """Replace the join code, so a code that was forwarded or leaked stops working.

        People who already joined keep their access; remove them from the team to revoke it.
        """
        company = self.get_object()
        company.invitation_code = company.generate_invitation_code()
        company.save(update_fields=["invitation_code"])
        return Response({"invitation_code": company.invitation_code}, status=status.HTTP_200_OK)


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

    def get_queryset(self):
        # The permission layer checks membership in the URL's `company_pk`, never that the
        # establishment belongs to it, so /companies/<own>/establishments/<someone else's>/
        # read and edited another company's farm until 2026-09-28.
        #
        # NEVER: fetch the farm in an action with get_object_or_404(Establishment, pk=pk). That
        # skips this queryset, and seven actions did until 2026-10-20 (dashboard_comprehensive
        # served another company's unpublished seasons). Use self.get_object(). Guard:
        # company/tests/test_establishment_actions_scoped.py.
        queryset = super().get_queryset()
        if self.company is not None:
            queryset = queryset.filter(company=self.company)
        return scope_to_caller_companies(queryset, self.request.user, "company")

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

    def _generate_filter_kwargs(
        self, period: str, production: str = "", period_filter: str = "", establishment=None
    ) -> dict:
        filter_kwargs = {}
        if period == "week":
            filter_kwargs[f"{period_filter}date__gte"] = datetime.now() - timedelta(days=7)
        elif period == "month":
            filter_kwargs[f"{period_filter}date__gte"] = datetime.now() - timedelta(days=31)
        elif period == "year":
            filter_kwargs[f"{period_filter}date__gte"] = datetime.now() - timedelta(days=365)

        if production is not None:
            # Resolved inside the farm, so another company's season id 404s exactly like a missing one.
            production = get_object_or_404(History.objects.filter(parcel__establishment=establishment), pk=production)
            filter_kwargs["history__id"] = production.id

        return filter_kwargs

    @action(detail=True, methods=["get"])
    def products(self, request, pk=None, company_pk=None, establishment_pk=None) -> Response:
        establishment = self.get_object()
        products = Product.objects.filter(
            histories__parcel__establishment=establishment,
            histories__published=True,
        )
        parcel = request.query_params.get("parcel", None)
        if parcel is not None:
            parcel = get_object_or_404(establishment.parcels.all(), pk=parcel)
            products = products.filter(histories__parcel__id=parcel.id)

        return Response(ProductListOptionsSerializer(products.distinct(), many=True).data)

    @action(detail=True, methods=["get"], url_path="parcel-geometry")
    def parcel_geometry(self, request, pk=None, company_pk=None) -> Response:
        """Every parcel of this farm with its boundary, for the parcel picker's map.

        The establishment payload deliberately carries no polygons (`has_boundaries` only), and
        the parcel list route filters by company, not by farm, with the heavy retrieve serializer.
        This is the slim, farm-scoped read the List | Map picker needs, in a fixed number of
        queries whatever the number of parcels.

        Owner side only: members of the farm's company, through `self.get_object()` (see
        `get_queryset`). It returns the full drawn boundary, which no public payload may: those
        go through `history.services.privacy.public_parcel_geo` and the disclosure level.
        """
        from history.services.block_ids import known_block_ids_for_parcels
        from product.serializers import with_open_season_count
        from product.services.parcel_geometry import latlng_path, map_center

        farm = self.get_object()
        parcels = list(
            with_open_season_count(farm.parcels.all())
            .only("id", "establishment_id", "name", "area", "polygon", "map_metadata")
            .order_by("name", "id")
        )
        sections = known_block_ids_for_parcels([parcel.id for parcel in parcels])

        payload = []
        for parcel in parcels:
            path = latlng_path(parcel.polygon)
            payload.append(
                {
                    "id": parcel.id,
                    "name": parcel.name,
                    "area": parcel.area,  # hectares
                    "path": path,
                    "has_boundary": path is not None,
                    "center": map_center(parcel.map_metadata),
                    "open_season_count": parcel.open_season_count,
                    "known_block_ids": sections[parcel.id],
                }
            )
        return Response(payload)

    @action(detail=True, methods=["get"])
    def get_charts_data(self, request, pk=None, company_pk=None) -> Response:
        establishment = self.get_object()
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
        filter_kwargs = self._generate_filter_kwargs(period, production, "history__history_scans__", establishment)

        if parcel is not None:
            parcel = get_object_or_404(establishment.parcels.all(), pk=parcel)
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
        establishment = self.get_object()
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
        filter_kwargs = self._generate_filter_kwargs(period, None, "production__history_scans__", establishment)

        if parcel is not None:
            parcel = get_object_or_404(establishment.parcels.all(), pk=parcel)
            filter_kwargs["production__parcel__id"] = parcel.id

        if product is not None:
            product = get_object_or_404(Product, pk=product)
            filter_kwargs["production__product__id"] = product.id

        if production is not None:
            production = get_object_or_404(History.objects.filter(parcel__establishment=establishment), pk=production)
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
        establishment = self.get_object()
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
        establishment = self.get_object()
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
                qs = qs.filter(date__date__gte=start)
            if end:
                # `date__date`, not `date`: event dates are DATETIMES, so `date__lte=<a date>` meant
                # midnight at the START of the end day, and every activity logged later that day
                # fell out. The calendar asks for its month as start..last-day, so the last day of
                # every month showed empty while the list showed its activities (2026-11-06).
                qs = qs.filter(date__date__lte=end)
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
                        # A spray whose time is not on the source record is stored at a noon
                        # placeholder; the row prints the phrase, never that noon.
                        "time_not_recorded": bool(getattr(event, "time_not_recorded", False)),
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
        #   * `History.update_trust_metrics()` saved with `update_fields=[...]` (confidence only
        #     since the transparency_score column went in history 0237/0238), so the `auto_now`
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
                # The season's parcel, so each row on the card can link straight to the
                # production page that holds the record to fix (Oscar, 2026-10-07).
                "parcel_id": production.parcel_id,
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
                    "row_key": r.get("row_key"),
                    "status": r["status"],
                    "detail": r["detail"],
                    "section_hint": r["section_hint"],
                    # The sentence the detail says and the data behind it, so the card can say
                    # it in the reader's language (recordkeeping review F-01; every actionable
                    # row since 2026-10-08).
                    "detail_code": r.get("detail_code"),
                    "params": r.get("params"),
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

        # Tenancy first, OUTSIDE the try: get_object() goes through the scoped queryset, so a farm
        # outside the URL's company 404s here; inside, `except Exception` would turn it into a 500.
        # The fetch below is only the prefetch shape.
        self.get_object()

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

    # carbon_scope_breakdown() removed 2026-09-30, with
    # carbon/services/enhanced_carbon_calculator.py.
    #
    # It had been answering HTTP 500 for every establishment that had any carbon entry.
    # All six methods it called on EnhancedCarbonCalculator (calculate_scope_breakdown,
    # calculate_consumer_equivalencies, get_usda_benchmark, identify_reduction_opportunities,
    # assess_data_quality, calculate_industry_percentile) had been renamed to private
    # variants and no longer existed. There is no __getattr__, so the first call raised
    # AttributeError into the broad `except Exception` below it, which returned 500. The only
    # 200 path left was the early return for a farm with NO carbon data, which is why nothing
    # ever reported it: the empty case worked.
    #
    # NEVER restore it from the response shape. What it declared it would serve, and what
    # trazo-app's deleted RTK type declared it received, were claims with no source:
    #   * transparency_score, from a method that did not exist;
    #   * industry_percentile, via _calculate_percentile_ranking(), whose own comment read
    #     "This would use real benchmark data in production" above hardcoded returns of
    #     95/75/50/25/10 chosen by emission thresholds;
    #   * usda_comparison and a methodology string reading "USDA/EPA emission factors",
    #     which is the blanket EPA/USDA provenance claim compliance.md puts in the UNSAFE
    #     column. Provenance is per input class (.claude/rules/carbon-methodology.md).
    #
    # Scope breakdown itself is not forbidden. If it is wanted, it needs a new endpoint over
    # measured quantities only, and no percentile, no benchmark and no quality grade.
    # Guard: company/tests/test_retired_establishment_routes.py.

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

                # `activity_data["transparency_score"]` removed 2026-08-02; the KEY itself
                # removed 2026-09-30.
                #
                # It was a second, incompatible transparency formula — min(100, events/15*100)
                # — with no category weighting, no photo penalties and no <3-event cap, so the
                # same production could carry two different "transparency scores" in one
                # payload depending on which key a client read.
                #
                # NEVER: removing the writer is not removing the claim. The 2026-08-02 change
                # deleted the assignment and left the key initialised to 0 in the dict above,
                # so every product in activity_breakdown reported a transparency score of
                # ZERO for two months. A zero is a grade, not a "no data" signal.

        # Calculate carbon intensity per hectare (sum areas from all parcels)
        total_area_hectares = sum(parcel.area for parcel in establishment.parcels.all() if parcel.area)
        if total_area_hectares and total_carbon_emissions > 0:
            metrics["carbon_intensity_per_hectare"] = total_carbon_emissions / total_area_hectares

        # The farm-level transparency score, completeness score and aggregated category grades
        # were dropped 2026-09-05. They ran the TransparencyCalculator over every finished season
        # on every load of this endpoint; the only reader (`CarbonSummaryCard`) shows counts and
        # the carbon summary, and nothing rendered `transparency_metrics`.

        # NEVER: 2026-11-08 - `data_completeness` was DELETED: a hardcoded 15 / 25 * 100 (always 60)
        # served as `data_completeness_percentage`, a percentage about the farm's own records with
        # nothing measured behind it. No component rendered it.

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


class ApplicatorViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """`/api/companies/<company_pk>/applicators/`: the people a spray record names as applicator.

    The spray form offers the active ones and COPIES their details onto the record at save; the
    record keeps the text, never a link to this row (see `company.models.Applicator`).

    Permissions are the nested class default: any member reads, a Company Admin or Farm Manager
    writes, and a non-member is refused before any row is looked up. Tenancy is the queryset: only
    rows of the company in the URL exist here, so another company's applicator id answers exactly
    like an id that does not exist. The company is never read from the body.

    `?active=true` narrows the list to the people the picker may offer; `?active=false` to the
    deactivated ones. DELETE deactivates and answers with the row: past records keep their copies
    either way, and the row stays listed for reference.
    """

    serializer_class = ApplicatorSerializer
    # A nested object must belong to the URL's company (ReadOnlyForViewers.has_object_permission).
    object_company_path = "company"

    _ACTIVE_FILTER = {"true": True, "false": False}

    def get_queryset(self):
        return Applicator.objects.filter(company=self.company)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        active = request.query_params.get("active")
        if active is not None:
            if active not in self._ACTIVE_FILTER:
                return Response(
                    {"active": ["Use true or false."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=self._ACTIVE_FILTER[active])
        return Response(self.get_serializer(queryset, many=True).data)

    def perform_create(self, serializer):
        serializer.save(company=self.company)

    def destroy(self, request, *args, **kwargs):
        """Deactivate. The row is kept, and 200 carries it, because a 204 would read as "gone"."""
        applicator = self.get_object()
        if applicator.is_active:
            applicator.is_active = False
            applicator.save(update_fields=["is_active", "updated_at"])
        return Response(self.get_serializer(applicator).data)
