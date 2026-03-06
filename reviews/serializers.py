import uuid

from rest_framework import serializers

from history.models import History

from .models import Review


class ListReviewSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    user_avatar = serializers.SerializerMethodField()
    production = serializers.SerializerMethodField()
    date = serializers.DateTimeField(format="%d/%m/%Y", required=False)

    class Meta:
        model = Review
        fields = "__all__"

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
    production = serializers.PrimaryKeyRelatedField(
        queryset=History.objects.all(), required=False
    )

    class Meta:
        model = Review
        fields = "__all__"

    def validate(self, data):
        """Support both integer production ID and UUID production_public_id."""
        production_public_id = data.pop("production_public_id", None)

        if production_public_id and not data.get("production"):
            try:
                production = History.objects.get(public_id=production_public_id)
                data["production"] = production
            except History.DoesNotExist:
                raise serializers.ValidationError(
                    {"production_public_id": "Production not found."}
                )

        if not data.get("production"):
            raise serializers.ValidationError(
                {"production": "Production is required."}
            )

        return data
