from rest_framework import serializers

from .models import Gallery, GalleryImage


class GalleryImageSerializer(serializers.ModelSerializer):
    thumbnail_sm = serializers.SerializerMethodField()
    thumbnail_md = serializers.SerializerMethodField()

    class Meta:
        model = GalleryImage
        fields = [
            "id",
            "gallery",
            "image",
            "s3_key",
            "image_url",
            "file_size",
            "extra_data",
            "thumbnails",
            "thumbnail_sm",
            "thumbnail_md",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_thumbnail_sm(self, obj):
        return obj.thumbnail_url("sm")

    def get_thumbnail_md(self, obj):
        return obj.thumbnail_url("md")


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
