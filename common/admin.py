from django.contrib import admin
from django.utils.html import format_html

from .models import Gallery, GalleryImage


class GalleryImageInline(admin.TabularInline):
    model = GalleryImage
    extra = 1
    readonly_fields = ("image_preview", "file_size", "created_at")
    fields = ("image_preview", "image", "s3_key", "image_url", "file_size", "created_at")

    def image_preview(self, obj):
        url = obj.url
        if url:
            return format_html(
                '<a href="{}" target="_blank">'
                '<img src="{}" style="max-height:80px; max-width:120px; object-fit:cover; border-radius:4px;" />'
                "</a>",
                url,
                url,
            )
        return "-"

    image_preview.short_description = "Preview"


class GalleryAdmin(admin.ModelAdmin):
    model = Gallery
    inlines = [GalleryImageInline]
    list_display = ("id", "image_count", "created_at")
    readonly_fields = ("created_at", "updated_at")

    def image_count(self, obj):
        return obj.images.count()

    image_count.short_description = "Images"


class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ("id", "gallery", "image_preview_small", "file_size_display", "created_at")
    list_filter = ("created_at",)
    readonly_fields = ("image_preview_large", "file_size", "created_at", "updated_at")
    fields = (
        "gallery",
        "image_preview_large",
        "image",
        "s3_key",
        "image_url",
        "file_size",
        "extra_data",
        "created_at",
        "updated_at",
    )

    def image_preview_small(self, obj):
        url = obj.url
        if url:
            return format_html(
                '<img src="{}" style="max-height:50px; max-width:80px; object-fit:cover; border-radius:4px;" />',
                url,
            )
        return "-"

    image_preview_small.short_description = "Preview"

    def image_preview_large(self, obj):
        url = obj.url
        if url:
            return format_html(
                '<a href="{}" target="_blank">'
                '<img src="{}" style="max-height:300px; max-width:400px; object-fit:contain; border-radius:4px;" />'
                "</a>",
                url,
                url,
            )
        return "-"

    image_preview_large.short_description = "Image Preview"

    def file_size_display(self, obj):
        if obj.file_size:
            if obj.file_size > 1_048_576:
                return f"{obj.file_size / 1_048_576:.1f} MB"
            return f"{obj.file_size / 1024:.0f} KB"
        return "-"

    file_size_display.short_description = "Size"


admin.site.register(Gallery, GalleryAdmin)
admin.site.register(GalleryImage, GalleryImageAdmin)
