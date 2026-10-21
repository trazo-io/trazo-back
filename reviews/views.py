from django.db.models import Q
from django.http import Http404

from dateutil import parser as date_parser
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from notifications.services import notification_service

from .models import Review
from .serializers import ListReviewSerializer, ReviewSerializer

# Create your views here.


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ReviewsViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    filter_backends = [filters.OrderingFilter]

    def get_permissions(self):
        # Create is open: a shopper reviews from the QR page without an account. Everything else
        # needs a session. `list`/`retrieve` were AllowAny over every review until 2026-10-21 (every
        # tenant's reviews with reviewer names, unpublished seasons included); nothing in the app
        # reads them anonymously. NOTE: `get_permissions` is invisible to
        # test_anonymous_endpoint_inventory, which reads only the permission class.
        if self.action == "create":
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        # Reading: the reviewer's own reviews, and reviews of the caller's companies' seasons.
        if self.action in ["list", "retrieve"] and not self.request.user.is_superuser:
            user = self.request.user
            queryset = queryset.filter(
                Q(user=user) | Q(production__parcel__establishment__company__in=user.companies.all())
            ).distinct()
        # Reading and posting reviews is public by design (the consumer QR page). Changing or
        # deleting one is not: only the review's own author, or staff. Until 2026-09-28 any
        # signed-in account could edit or delete any review.
        if self.action in ["update", "partial_update", "destroy"]:
            user = self.request.user
            if not user.is_superuser:
                queryset = queryset.filter(user=user)
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return ListReviewSerializer
        else:
            return ReviewSerializer

    def perform_create(self, serializer):
        # The author is the session, never the body: `user` was writable until 2026-10-21, so a
        # review could be posted under any account's name.
        user = self.request.user
        serializer.save(user=user if user.is_authenticated else None)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        # Send notification to product owner about the review
        try:
            review = serializer.instance
            if review.production and review.production.parcel and review.production.parcel.establishment:
                # Get the company and find company admins via WorksIn relationship
                company = review.production.parcel.establishment.company
                reviewer = review.user if review.user else None

                # Get company admins (users with 'CA' role)
                from users.models import WorksIn

                company_admins = WorksIn.objects.filter(
                    company=company, role="CA"  # Company Admin role
                ).select_related("user")

                # Send notification to all company admins who are not the reviewer
                for admin_relation in company_admins:
                    product_owner = admin_relation.user

                    # Only send notification if reviewer is different from product owner
                    if reviewer != product_owner:
                        # Get product name
                        product_name = (
                            review.production.product.name
                            if review.production.product
                            else f"Production {review.production.id}"
                        )

                        # Create notification
                        notification_service.create_product_review_notification(
                            product_owner=product_owner,
                            reviewer=reviewer,
                            product_name=product_name,
                            rating=review.rating,
                            review_text=review.written_review,
                            production_id=review.production.id,
                            establishment_id=(
                                review.production.parcel.establishment.id
                                if review.production.parcel and review.production.parcel.establishment
                                else None
                            ),
                            product_id=review.production.product.id if review.production.product else None,
                            parcel_id=review.production.parcel.id if review.production.parcel else None,
                        )
        except Exception as e:
            # Log error but don't break the review functionality
            print(f"Error creating review notification: {e}")

        return Response(serializer.data, status=201)

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAuthenticated])
    def establishment_reviews_paginated(self, request):
        """
        Paginated endpoint for establishment reviews with filtering.
        Used by the commercial dashboard's "view all reviews" functionality.
        """
        establishment_id = request.query_params.get("establishment_id")
        company_id = request.query_params.get("company_id")

        if not establishment_id or not company_id:
            return Response(
                {"error": "establishment_id and company_id are required"}, status=status.HTTP_400_BAD_REQUEST
            )
        if not (str(establishment_id).isdigit() and str(company_id).isdigit()):
            return Response(
                {"error": "establishment_id and company_id must be integers"}, status=status.HTTP_400_BAD_REQUEST
            )

        # NEVER: drop this check. The action's own permission_classes replace any membership check,
        # so until 2026-10-21 any signed-in account read any farm's reviews (and could confirm a
        # reviewer's email through ?search=) by naming its ids. The filters below pin the farm to
        # this company. Guard: reviews/tests/test_reviews_scoped.py.
        if not request.user.is_superuser and not request.user.companies.filter(id=company_id).exists():
            raise Http404

        # Get reviews for the establishment
        reviews_queryset = (
            Review.objects.filter(
                production__parcel__establishment_id=establishment_id,
                production__parcel__establishment__company_id=company_id,
            )
            .select_related(
                "production",
                "production__product",
                "production__parcel",
                "production__parcel__establishment",
                "scan",
                "scan__history",
            )
            .order_by("-date")
        )

        # Apply date filtering if provided
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        if date_from:
            try:
                date_from_parsed = date_parser.parse(date_from)
                reviews_queryset = reviews_queryset.filter(date__gte=date_from_parsed)
            except ValueError:
                pass

        if date_to:
            try:
                date_to_parsed = date_parser.parse(date_to)
                reviews_queryset = reviews_queryset.filter(date__lte=date_to_parsed)
            except ValueError:
                pass

        # Apply product filtering if provided
        product_id = request.query_params.get("product_id")
        if product_id:
            reviews_queryset = reviews_queryset.filter(production__product_id=product_id)

        # Apply parcel filtering if provided
        parcel_id = request.query_params.get("parcel_id")
        if parcel_id:
            reviews_queryset = reviews_queryset.filter(production__parcel_id=parcel_id)

        # Apply rating filtering if provided
        min_rating = request.query_params.get("min_rating")
        if min_rating:
            try:
                min_rating_val = float(min_rating)
                reviews_queryset = reviews_queryset.filter(rating__gte=min_rating_val)
            except ValueError:
                pass

        max_rating = request.query_params.get("max_rating")
        if max_rating:
            try:
                max_rating_val = float(max_rating)
                reviews_queryset = reviews_queryset.filter(rating__lte=max_rating_val)
            except ValueError:
                pass

        # Apply search filtering if provided
        search = request.query_params.get("search")
        if search:
            from django.db.models import Q

            reviews_queryset = reviews_queryset.filter(
                Q(headline__icontains=search)
                | Q(written_review__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(user__email__icontains=search)
                | Q(production__product__name__icontains=search)
                | Q(production__parcel__name__icontains=search)
            )

        # Paginate results
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(reviews_queryset, request)

        if page is not None:
            # Transform to the expected format
            reviews_data = []
            for review in page:
                review_data = {
                    "id": review.id,
                    "user": review.user.get_full_name() if review.user else "Anonymous",
                    "user_avatar": (
                        request.build_absolute_uri(review.user.image.url) if review.user and review.user.image else None
                    ),
                    "date": review.date.strftime("%Y-%m-%d") if review.date else None,
                    "rating": review.rating,
                    "headline": review.headline or "",
                    "written_review": review.written_review or "",
                    "images": review.images or [],
                    "production": (
                        review.production.period
                        if review.production and hasattr(review.production, "period")
                        else "Unknown"
                    ),
                    "product": (
                        review.production.product.name if review.production and review.production.product else "Unknown"
                    ),
                    "product_id": (
                        review.production.product.id if review.production and review.production.product else None
                    ),
                    "parcel": (
                        review.production.parcel.name if review.production and review.production.parcel else "Unknown"
                    ),
                    "parcel_id": (
                        review.production.parcel.id if review.production and review.production.parcel else None
                    ),
                    "verified_purchase": bool(review.scan_id),
                    "helpful_count": getattr(review, "helpful_count", 0),
                    "location": getattr(review.scan, "city", "") if review.scan else "",
                }
                reviews_data.append(review_data)

            return paginator.get_paginated_response(reviews_data)

        return Response([])
