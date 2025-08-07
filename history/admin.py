from django.contrib import admin

from .models import (
    History,
    ChemicalEvent,
    WeatherEvent,
    GeneralEvent,
    HistoryScan,
    ProductionEvent,
)


class ChemicalEventInline(admin.TabularInline):
    model = ChemicalEvent
    extra = 1
    ordering = ("index",)


class WeatherEventInline(admin.TabularInline):
    model = WeatherEvent
    extra = 1
    ordering = ("index",)


class GeneralEventInline(admin.TabularInline):
    model = GeneralEvent
    extra = 1
    ordering = ("index",)


class ProductionEventInline(admin.TabularInline):
    model = ProductionEvent
    extra = 1
    ordering = ("index",)


class EventAdmin(admin.ModelAdmin):
    list_display = ("date",)
    list_filter = ("date", "description")
    search_fields = ("date", "description")


class HistoryAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "public_views", "unique_visitors", "confidence_score", "transparency_score", "published")
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
    ]
    
    # Trust metrics and analytics in readonly fields
    readonly_fields = ('public_views', 'unique_visitors', 'confidence_score', 'transparency_score', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'type', 'description', 'published')
        }),
        ('Timeline', {
            'fields': ('start_date', 'finish_date')
        }),
        ('Production Details', {
            'fields': ('product', 'parcel', 'production_amount', 'earning')
        }),
        ('Trust Metrics & Analytics', {
            'fields': ('public_views', 'unique_visitors', 'confidence_score', 'transparency_score', 'reputation', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Media & QR', {
            'fields': ('album', 'qr_code'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['recalculate_trust_metrics', 'reset_view_counts']
    
    def recalculate_trust_metrics(self, request, queryset):
        """Recalculate trust metrics for selected productions"""
        updated = 0
        for production in queryset:
            try:
                production.update_trust_metrics()
                updated += 1
            except Exception as e:
                self.message_user(request, f'Error updating {production.name}: {str(e)}', level='ERROR')
        
        self.message_user(request, f'Successfully updated trust metrics for {updated} productions.')
    recalculate_trust_metrics.short_description = "Recalculate trust metrics"
    
    def reset_view_counts(self, request, queryset):
        """Reset view counts for selected productions"""
        count = queryset.update(public_views=0, unique_visitors=0)
        self.message_user(request, f'Reset view counts for {count} productions.')
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
