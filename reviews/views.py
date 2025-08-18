from django.db.models import Q
from django.shortcuts import render

from dateutil import parser as date_parser
from rest_framework import filters, generics, permissions, status, viewsets
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
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.OrderingFilter]

    def get_serializer_class(self):
        if self.action == "list":
            return ListReviewSerializer
        else:
            return ReviewSerializer

    def create(self, request, *args, **kwargs):
        data = request.data.copy()

        # Handle scan_id if provided
        if "scan_id" in data:
            # If it's a web review (starts with 'web-'), remove it as it's not a real scan
            if isinstance(data["scan_id"], str) and data["scan_id"].startswith("web-"):
                data.pop("scan_id", None)
                data.pop("scan", None)
            else:
                # Otherwise, treat it as a real scan ID
                data["scan"] = data.pop("scan_id", None)

        serializer = self.get_serializer(data=data)
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
                    "user_avatar": None,  # Add avatar logic if needed
                    "date": review.date.strftime("%Y-%m-%d") if review.date else None,
                    "rating": review.rating,
                    "headline": review.headline or "",
                    "written_review": review.written_review or "",
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
