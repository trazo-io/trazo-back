import re
import uuid

from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils.html import format_html

from backend.storage import using_s3_storage

from .models import (
    ChemicalEvent,
    GeneralEvent,
    HistoryScan,
    LabelImage,
    Production,
    ProductionEvent,
    ProductionPostHarvestFacility,
    SoilManagementEvent,
    WeatherEvent,
)


class LabelImageInline(admin.TabularInline):
    """Container-label artifacts (CCOF G7.0). Add labels even after a production is
    finished — labels are post-harvest records. Create the image as a GalleryImage
    first (Common > Gallery images, paste a public URL or upload), then link it."""

    model = LabelImage
    extra = 0
    raw_id_fields = ("gallery_image",)


class FinishedProductionReadOnlyInlineMixin:
    """Make inline fields read-only when the parent production is finished."""

    def has_add_permission(self, request, obj=None):
        if obj and (obj.finish_date is not None or obj.published):
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and (obj.finish_date is not None or obj.published):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.finish_date is not None or obj.published):
            return False
        return super().has_delete_permission(request, obj)


class ChemicalEventInline(FinishedProductionReadOnlyInlineMixin, admin.TabularInline):
    model = ChemicalEvent
    extra = 1
    ordering = ("index",)


class WeatherEventInline(FinishedProductionReadOnlyInlineMixin, admin.TabularInline):
    model = WeatherEvent
    extra = 1
    ordering = ("index",)


class GeneralEventInline(FinishedProductionReadOnlyInlineMixin, admin.TabularInline):
    model = GeneralEvent
    extra = 1
    ordering = ("index",)


class ProductionEventInline(FinishedProductionReadOnlyInlineMixin, admin.TabularInline):
    model = ProductionEvent
    extra = 1
    ordering = ("index",)


class SoilManagementEventInline(FinishedProductionReadOnlyInlineMixin, admin.TabularInline):
    model = SoilManagementEvent
    extra = 1
    ordering = ("index",)


class EventAdmin(admin.ModelAdmin):
    list_display = ("date",)
    list_filter = ("date", "description")
    search_fields = ("date", "description")

    def has_change_permission(self, request, obj=None):
        if obj and hasattr(obj, "history") and obj.history:
            if obj.history.finish_date is not None or obj.history.published:
                return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj and hasattr(obj, "history") and obj.history:
            if obj.history.finish_date is not None or obj.history.published:
                return False
        return super().has_delete_permission(request, obj)


class HistoryAdminForm(forms.ModelForm):
    """Adds a one-shot file uploader for the consumer hero/cover photo.

    The production model stores the cover as a URL (``cover_image_url``) so it travels the same
    publicly-readable-S3-URL path as every other consumer photo. This non-model field lets staff
    upload a local file: ``save_model`` pushes it to the media bucket and writes the resulting URL
    back to ``cover_image_url``. Leave it blank to keep the current cover or paste a URL directly.
    """

    cover_image_file = forms.ImageField(
        required=False,
        label="Upload hero photo",
        help_text=(
            "Upload a photo to use as the consumer QR hero/cover. It is saved to the media bucket "
            "and set as the cover, overriding the auto-picked first timeline photo. Leave blank to "
            "keep the current cover, or paste a public image URL in the field above instead."
        ),
    )

    class Meta:
        model = Production
        fields = "__all__"


class PostHarvestFacilityLinkInline(admin.TabularInline):
    """The off-farm handlers a lot was sent to. An inline since 2026-11-14: the link table became an
    explicit model (the History -> Production rename), and admin cannot edit such a relation as a
    plain many-to-many field."""

    model = ProductionPostHarvestFacility
    extra = 0
    verbose_name = "Post-harvest facility this lot was sent to"
    verbose_name_plural = (
        "Audit records (CCOF G6.1): off-farm post-harvest handlers this lot was sent to. A lot with "
        "a fresh grade and a process grade has two. Create each facility under Certifications first."
    )


class HistoryAdmin(admin.ModelAdmin):
    form = HistoryAdminForm
    list_display = (
        "name",
        "public_id",
        "start_date",
        "public_views",
        "unique_visitors",
        "confidence_score",
        "published",
    )
    list_filter = (
        "published",
        "start_date",
        "product__name",
        "parcel__establishment__name",
    )
    search_fields = (
        "name",
        "public_id",
        "product__name",
        "parcel__establishment__name",
        "start_date",
    )
    inlines = [
        ChemicalEventInline,
        WeatherEventInline,
        GeneralEventInline,
        ProductionEventInline,
        SoilManagementEventInline,
        LabelImageInline,
        PostHarvestFacilityLinkInline,
    ]

    # Trust metrics and analytics in readonly fields
    readonly_fields = (
        "public_id",
        "public_views",
        "unique_visitors",
        "confidence_score",
        "updated_at",
        "production_images",
        "cover_preview",
    )

    fieldsets = (
        ("Basic Information", {"fields": ("name", "public_id", "type", "description", "published")}),
        ("Timeline", {"fields": ("start_date", "finish_date")}),
        ("Production Details", {"fields": ("product", "parcel", "production_amount", "earning")}),
        (
            "Trust Metrics & Analytics",
            {
                "fields": (
                    "public_views",
                    "unique_visitors",
                    "confidence_score",
                    "reputation",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Hero / Cover Photo (consumer QR)",
            {
                "fields": ("cover_preview", "cover_image_url", "cover_image_file"),
                "description": (
                    "The hero photo shown at the top of the public consumer page "
                    "(consumer.trazo.io/production/&lt;public_id&gt;). Upload a file OR paste a "
                    "public image URL. When set it overrides the auto-picked first timeline photo. "
                    "Clear the URL to fall back to auto-pick."
                ),
            },
        ),
        (
            "Production Images",
            {
                "fields": ("production_images", "qr_code"),
            },
        ),
    )

    def cover_preview(self, obj):
        """Thumbnail of the current consumer hero/cover photo."""
        url = getattr(obj, "cover_image_url", None) if obj else None
        if url:
            return format_html(
                '<a href="{}" target="_blank">'
                '<img src="{}" style="max-height:160px; max-width:280px; object-fit:cover; '
                'border-radius:8px; border:1px solid #ddd;" /></a>',
                url,
                url,
            )
        return format_html(
            '<span style="color:#888;">No cover set — the consumer hero auto-picks the first ' "timeline photo.</span>"
        )

    cover_preview.short_description = "Current cover"

    def save_model(self, request, obj, form, change):
        """If a hero file was uploaded, store it in the media bucket and set cover_image_url.

        Mirrors the app upload flow (common.views.get_presigned_url): the file lands under the
        public ``media/`` prefix and the permanent (non-presigned) S3 URL is persisted, so the
        consumer page renders it exactly like every other photo.
        """
        upload = form.cleaned_data.get("cover_image_file")
        if upload:
            # Sanitize the filename (spaces/unicode would yield a broken, unencoded
            # S3 URL) — mirrors common.views.get_presigned_url.
            safe_name = re.sub(r"[^\w\-.]", "_", upload.name)
            is_s3 = using_s3_storage()
            # On S3 the photo must live under the proven-public "media/" prefix (where the
            # app uploads consumer photos). On the local filesystem MEDIA_URL already adds
            # "media/", so the storage key must NOT repeat it.
            prefix = "media/production_hero" if is_s3 else "production_hero"
            saved_key = default_storage.save(f"{prefix}/{uuid.uuid4()}-{safe_name}", upload)
            if is_s3:
                obj.cover_image_url = (
                    f"https://{settings.AWS_STORAGE_BUCKET_NAME}.s3."
                    f"{settings.AWS_S3_REGION_NAME}.amazonaws.com/{saved_key}"
                )
            else:
                obj.cover_image_url = request.build_absolute_uri(default_storage.url(saved_key))
        super().save_model(request, obj, form, change)

    def _render_gallery_images(self, gallery, label=None):
        """Render image thumbnails for a gallery with edit/delete links."""
        parts = []
        if label:
            parts.append(
                format_html(
                    '<div style="font-weight:bold; margin:8px 0 4px; font-size:12px; ' 'color:#666;">{}</div>',
                    label,
                )
            )
        for img in gallery.images.all():
            url = img.url
            if not url:
                continue
            edit_url = reverse("admin:common_galleryimage_change", args=[img.pk])
            delete_url = reverse("admin:common_galleryimage_delete", args=[img.pk])
            parts.append(
                format_html(
                    '<div style="display:inline-block; margin:4px; text-align:center; '
                    'vertical-align:top;">'
                    '<a href="{}" target="_blank">'
                    '<img src="{}" style="max-height:120px; max-width:160px; '
                    "object-fit:cover; border-radius:4px; border:1px solid #ddd; "
                    'cursor:pointer;" />'
                    "</a>"
                    '<br/><a href="{}" style="font-size:11px;">Edit</a>'
                    ' | <a href="{}" style="font-size:11px; color:#c00;">Delete</a>'
                    "</div>",
                    url,
                    url,
                    edit_url,
                    delete_url,
                )
            )
        return parts

    def production_images(self, obj):
        html_parts = []
        total = 0

        # Production's own album
        if obj.album and obj.album.images.exists():
            parts = self._render_gallery_images(obj.album, "Production Album")
            html_parts.extend(parts)
            total += obj.album.images.count()

        # Collect images from all event types
        event_relations = [
            ("history_productionevent_events", "Production Events"),
            ("history_chemicalevent_events", "Chemical Events"),
            ("history_weatherevent_events", "Weather Events"),
            ("history_generalevent_events", "General Events"),
            ("history_soilmanagementevent_events", "Soil Management Events"),
            ("history_pestmanagementevent_events", "Pest Management Events"),
            ("history_equipmentevent_events", "Equipment Events"),
            ("history_businessevent_events", "Business Events"),
        ]
        for relation, label in event_relations:
            manager = getattr(obj, relation, None)
            if not manager:
                continue
            for event in manager.select_related("album").all():
                if event.album and event.album.images.exists():
                    event_label = f"{label} - {event.description[:50]}" if event.description else label
                    parts = self._render_gallery_images(event.album, event_label)
                    html_parts.extend(parts)
                    total += event.album.images.count()

        if not html_parts:
            return format_html("<em>No images found in this production or its events.</em>")

        html_parts.insert(
            0,
            format_html(
                '<div style="margin-bottom:8px; font-size:13px;"><strong>{} image(s)</strong> total</div>',
                total,
            ),
        )
        return format_html("".join(str(p) for p in html_parts))

    production_images.short_description = "Images"

    actions = ["recalculate_trust_metrics", "reset_view_counts"]

    def recalculate_trust_metrics(self, request, queryset):
        """Recalculate trust metrics for selected productions"""
        updated = 0
        for production in queryset:
            try:
                production.update_trust_metrics()
                updated += 1
            except Exception as e:
                self.message_user(request, f"Error updating {production.name}: {str(e)}", level="ERROR")

        self.message_user(request, f"Successfully updated trust metrics for {updated} productions.")

    recalculate_trust_metrics.short_description = "Recalculate trust metrics"

    def reset_view_counts(self, request, queryset):
        """Reset view counts for selected productions"""
        count = queryset.update(public_views=0, unique_visitors=0)
        self.message_user(request, f"Reset view counts for {count} productions.")

    reset_view_counts.short_description = "Reset view counts"


class HistoryScanAdmin(admin.ModelAdmin):
    list_display = ("history", "ip_address", "city", "country", "date")
    list_filter = ("history", "ip_address", "city", "country", "date")


admin.site.register(WeatherEvent, EventAdmin)
admin.site.register(ChemicalEvent, EventAdmin)
admin.site.register(GeneralEvent, EventAdmin)
admin.site.register(ProductionEvent, EventAdmin)
admin.site.register(Production, HistoryAdmin)
admin.site.register(HistoryScan, HistoryScanAdmin)


@admin.register(LabelImage)
class LabelImageAdmin(admin.ModelAdmin):
    """Standalone view of container labels (CCOF G7.0). Usually managed via the
    inline on a production; this is for cross-production review."""

    list_display = ["history", "label_type", "container_type", "gallery_image", "created_at"]
    list_filter = ["label_type", "container_type"]
    search_fields = ["history__name", "history__lot_id", "lot_link_note"]
    raw_id_fields = ("history", "gallery_image")
