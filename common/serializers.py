from rest_framework import serializers
from rest_framework.serializers import ModelSerializer

from .models import Gallery, GalleryImage


class GalleryImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = GalleryImage
        fields = [
            "id",
            "gallery",
            "image",
            "s3_key",
            "image_url",
            "extra_data",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class GallerySerializer(serializers.ModelSerializer):
    images = GalleryImageSerializer(many=True, required=False, allow_null=True)

    class Meta:
        model = Gallery
        fields = [
            "id",
            "images",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    # def create(self, validated_data):
    #     images_data = self.context.get("request").FILES
    #     gallery = Gallery.objects.create(**validated_data)
    #     for image_data in images_data.values():
    #         GalleryImage.objects.create(gallery=gallery, image=image_data)
    #     return gallery
