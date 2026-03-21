from django.contrib import admin

from .models import Certification, CertificationVerificationLog


class CertificationVerificationLogInline(admin.TabularInline):
    model = CertificationVerificationLog
    extra = 0
    readonly_fields = [
        "attempted_at",
        "status_before",
        "status_after",
        "verification_source",
        "success",
        "error_message",
    ]
    ordering = ["-attempted_at"]


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = [
        "establishment",
        "certification_type",
        "verification_status",
        "certifier_name",
        "effective_date",
        "expiry_date",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "certification_type",
        "verification_status",
    ]
    search_fields = [
        "establishment__name",
        "certifier_name",
        "certification_number",
    ]
    readonly_fields = [
        "public_id",
        "verification_status",
        "last_verified_at",
        "verification_source",
        "verification_source_url",
        "raw_api_response",
        "verification_notes",
        "created_at",
        "updated_at",
    ]
    inlines = [CertificationVerificationLogInline]


@admin.register(CertificationVerificationLog)
class CertificationVerificationLogAdmin(admin.ModelAdmin):
    list_display = [
        "certification",
        "attempted_at",
        "status_before",
        "status_after",
        "success",
    ]
    list_filter = ["success", "verification_source"]
    readonly_fields = [
        "certification",
        "attempted_at",
        "status_before",
        "status_after",
        "verification_source",
        "success",
        "error_message",
        "raw_response",
    ]
