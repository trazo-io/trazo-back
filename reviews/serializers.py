import uuid

from rest_framework import serializers

from history.models import Production

from .models import Review


class ListReviewSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()
    production = serializers.SerializerMethodField()
    date = serializers.DateTimeField(format="%d/%m/%Y", required=False)

    class Meta:
        model = Review
        fields = [
            "id",
            "headline",
            "written_review",
            "date",
            "rating",
            "user",
            "user_avatar",
            "production",
            "images",
        ]

    def get_user(self, review):
        if review.user:
            return review.user.get_full_name()
        return "Anonymous"

    def get_user_avatar(self, review):
        if review.user and review.user.image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(review.user.image.url)
            return review.user.image.url
        return None

    def get_production(self, review):
        return (
            review.production.product.name
            + " - "
            + review.production.parcel.name
            + " - "
            + review.production.finish_date.strftime("%d/%m/%Y")
        )


class ReviewSerializer(serializers.ModelSerializer):
    production_public_id = serializers.UUIDField(write_only=True, required=False)
    production = serializers.PrimaryKeyRelatedField(queryset=Production.objects.all(), required=False)

    class Meta:
        model = Review
        fields = [
            "id",
            "headline",
            "written_review",
            "date",
            "rating",
            "user",
            "production",
            "production_public_id",
            "scan",
            "images",
        ]
        # `user` is set from the session in ReviewsViewSet.perform_create, never from the body.
        read_only_fields = ["id", "date", "user"]

    def validate_production(self, production):
        """Only a PUBLISHED season can be reviewed: it is the one a shopper can see. Any season id
        was accepted until 2026-10-21, and `my_reviews` then echoed the reviewed season back in
        full. An author editing a review keeps its season even if it was unpublished since. The
        refusal reads exactly like DRF's missing-pk error, so it does not confirm the id exists."""
        if production.published or (self.instance is not None and production == self.instance.production):
            return production
        raise serializers.ValidationError(f'Invalid pk "{production.pk}" - object does not exist.')

    def validate(self, data):
        """Support both integer production ID and UUID production_public_id."""
        production_public_id = data.pop("production_public_id", None)

        if production_public_id and not data.get("production"):
            # Same rule as the integer path, including the author's carve-out on update.
            try:
                data["production"] = self.validate_production(Production.objects.get(public_id=production_public_id))
            except (Production.DoesNotExist, serializers.ValidationError):
                raise serializers.ValidationError({"production_public_id": "Production not found."})

        if not data.get("production"):
            raise serializers.ValidationError({"production": "Production is required."})

        # A scan marks the review as a verified purchase (`bool(scan_id)`), so it must be a scan OF
        # this season, made by THIS reviewer, and not already behind another review. Scan ids are
        # sequential, so "any scan of the season" let anyone cite somebody else's.
        scan = data.get("scan")
        if scan is not None:
            if scan.history_id != data["production"].id:
                raise serializers.ValidationError({"scan": "This scan is not of the reviewed product."})
            if not self._scan_is_the_reviewers(scan):
                # Kept, not refused: the QR page sends its scan id on anonymous reviews too. The
                # review is recorded; it just does not claim a verified purchase it cannot prove.
                data["scan"] = None

        return data

    def _scan_is_the_reviewers(self, scan):
        if self.instance is not None and self.instance.scan_id == scan.id:
            return True  # an author editing keeps the scan they already had
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or scan.user_id != user.id:
            return False
        return not Review.objects.filter(scan=scan).exists()
