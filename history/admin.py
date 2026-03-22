from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    ChemicalEvent,
    GeneralEvent,
    History,
    HistoryScan,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)


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


class HistoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "public_id",
        "start_date",
        "public_views",
        "unique_visitors",
        "confidence_score",
        "transparency_score",
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
    ]

    # Trust metrics and analytics in readonly fields
    readonly_fields = (
        "public_id",
        "public_views",
        "unique_visitors",
        "confidence_score",
        "transparency_score",
        "updated_at",
        "production_images",
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
                    "transparency_score",
                    "reputation",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Production Images",
            {
                "fields": ("production_images", "qr_code"),
            },
        ),
    )

    def production_images(self, obj):
        if not obj.album:
            return format_html("<em>No album attached to this production.</em>")

        images = obj.album.images.all()
        if not images.exists():
            gallery_url = reverse("admin:common_gallery_change", args=[obj.album.pk])
            return format_html(
                '<em>No images yet.</em> <a href="{}">Manage album</a>',
                gallery_url,
            )

        html_parts = []
        for img in images:
            url = img.url
            edit_url = reverse("admin:common_galleryimage_change", args=[img.pk])
            delete_url = reverse("admin:common_galleryimage_delete", args=[img.pk])
            if url:
                html_parts.append(
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

        gallery_url = reverse("admin:common_gallery_change", args=[obj.album.pk])
        html_parts.append(
            format_html(
                '<div style="margin-top:8px; clear:both;">'
                '<a href="{}">Manage all images in album</a>'
                "</div>",
                gallery_url,
            )
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
admin.site.register(History, HistoryAdmin)
admin.site.register(HistoryScan, HistoryScanAdmin)
