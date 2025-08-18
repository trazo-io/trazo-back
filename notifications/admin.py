from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import Notification, NotificationChannel, NotificationPreference, NotificationTemplate


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "type", "priority", "read_status", "delivered_status", "created_at")
    list_filter = ("type", "priority", "read", "delivered", "created_at")
    search_fields = ("title", "message", "recipient__email", "recipient__first_name", "recipient__last_name")
    readonly_fields = ("created_at", "updated_at", "read_at", "delivered_at")

    fieldsets = (
        ("Notification Details", {"fields": ("recipient", "actor", "type", "priority")}),
        ("Content", {"fields": ("title", "message", "extra_data")}),
        ("Related Object", {"fields": ("content_type", "object_id"), "classes": ("collapse",)}),
        ("Status", {"fields": ("read", "read_at", "delivered", "delivered_at")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    actions = ["mark_as_read", "mark_as_unread"]

    def read_status(self, obj):
        if obj.read:
            return format_html('<span style="color: green;">✓ Read</span>')
        return format_html('<span style="color: red;">✗ Unread</span>')

    read_status.short_description = "Read Status"

    def delivered_status(self, obj):
        if obj.delivered:
            return format_html('<span style="color: green;">✓ Delivered</span>')
        return format_html('<span style="color: orange;">✗ Pending</span>')

    delivered_status.short_description = "Delivery Status"

    def mark_as_read(self, request, queryset):
        updated = 0
        for notification in queryset:
            if not notification.read:
                notification.mark_as_read()
                updated += 1
        self.message_user(request, f"{updated} notifications marked as read.")

    mark_as_read.short_description = "Mark selected notifications as read"

    def mark_as_unread(self, request, queryset):
        updated = queryset.update(read=False, read_at=None)
        self.message_user(request, f"{updated} notifications marked as unread.")

    mark_as_unread.short_description = "Mark selected notifications as unread"


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "product_scan_enabled",
        "product_review_enabled",
        "carbon_verification_enabled",
        "system_alert_enabled",
        "realtime_notifications",
    )
    list_filter = (
        "product_scan_enabled",
        "product_review_enabled",
        "carbon_verification_enabled",
        "system_alert_enabled",
        "email_notifications",
        "push_notifications",
        "realtime_notifications",
    )
    search_fields = ("user__email", "user__first_name", "user__last_name")

    fieldsets = (
        ("User", {"fields": ("user",)}),
        (
            "Notification Types",
            {
                "fields": (
                    "product_scan_enabled",
                    "product_review_enabled",
                    "carbon_verification_enabled",
                    "system_alert_enabled",
                )
            },
        ),
        ("Delivery Methods", {"fields": ("email_notifications", "push_notifications", "realtime_notifications")}),
        ("Timing", {"fields": ("quiet_hours_start", "quiet_hours_end")}),
    )


@admin.register(NotificationChannel)
class NotificationChannelAdmin(admin.ModelAdmin):
    list_display = ("user", "channel_name", "connected_at", "last_activity", "is_active")
    list_filter = ("connected_at", "last_activity")
    search_fields = ("user__email", "channel_name", "user_agent")
    readonly_fields = ("connected_at", "last_activity")

    def is_active(self, obj):
        """Check if channel is still active (last activity within 5 minutes)"""
        threshold = timezone.now() - timezone.timedelta(minutes=5)
        if obj.last_activity > threshold:
            return format_html('<span style="color: green;">✓ Active</span>')
        return format_html('<span style="color: red;">✗ Inactive</span>')

    is_active.short_description = "Status"


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ("type", "active", "created_at", "updated_at")
    list_filter = ("type", "active")
    search_fields = ("title_template", "message_template")

    fieldsets = (
        ("Template Details", {"fields": ("type", "active")}),
        ("Content Templates", {"fields": ("title_template", "message_template")}),
        (
            "Variables",
            {"fields": ("variables",), "description": "JSON object documenting available template variables"},
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:  # editing an existing object
            return self.readonly_fields + ("type",)
        return self.readonly_fields
