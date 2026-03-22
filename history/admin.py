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

    def _render_gallery_images(self, gallery, label=None):
        """Render image thumbnails for a gallery with edit/delete links."""
        parts = []
        if label:
            parts.append(format_html(
                '<div style="font-weight:bold; margin:8px 0 4px; font-size:12px; '
                'color:#666;">{}</div>',
                label,
            ))
        for img in gallery.images.all():
            url = img.url
            if not url:
                continue
            edit_url = reverse("admin:common_galleryimage_change", args=[img.pk])
            delete_url = reverse("admin:common_galleryimage_delete", args=[img.pk])
            parts.append(format_html(
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
                url, url, edit_url, delete_url,
            ))
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

        html_parts.insert(0, format_html(
            '<div style="margin-bottom:8px; font-size:13px;"><strong>{} image(s)</strong> total</div>',
            total,
        ))
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
