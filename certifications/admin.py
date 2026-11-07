from django.contrib import admin

from .models import (
    ApprovedInputChangeLog,
    Certification,
    CertificationVerificationLog,
    IngestionRun,
    NationalListRevision,
    OSPChangeNotification,
    PostHarvestFacility,
    WSDAMaterial,
)


@admin.register(OSPChangeNotification)
class OSPChangeNotificationAdmin(admin.ModelAdmin):
    list_display = [
        "osp",
        "change_category",
        "date_notified",
        "method",
        "certifier_acknowledged_at",
        "created_by",
    ]
    list_filter = ["change_category", "method", "documentation_timing"]
    search_fields = ["description", "osp__establishment__name"]


@admin.register(PostHarvestFacility)
class PostHarvestFacilityAdmin(admin.ModelAdmin):
    """
    White-glove entry for off-farm post-harvest handlers (CCOF G6.1). Operator
    records the handler's identity + organic certificate; the audit export reads
    it. Use the 'Verify handler cert against USDA OID' action to attempt
    automated verification.
    """

    list_display = [
        "name",
        "facility_type",
        "establishment",
        "verification_status",
        "effective_date",
        "expiry_date",
    ]
    list_filter = ["facility_type", "verification_status"]
    search_fields = ["name", "establishment__name", "certification_number", "certifier_name"]
    autocomplete_fields = ["establishment"]
    readonly_fields = [
        "public_id",
        "last_verified_at",
        "verification_source",
        "raw_api_response",
        "created_at",
        "updated_at",
    ]
    actions = ["verify_against_oid"]

    @admin.action(description="Verify handler cert against USDA Organic Integrity Database")
    def verify_against_oid(self, request, queryset):
        n = 0
        # An own facility has no certificate of its own to look up.
        for facility in queryset.exclude(operated_by="this_operation"):
            facility.verify()
            facility.save()
            n += 1
        self.message_user(request, f"Ran USDA-OID verification on {n} facility cert(s).")


@admin.register(WSDAMaterial)
class WSDAMaterialAdmin(admin.ModelAdmin):
    list_display = (
        "brand_name",
        "manufacturer",
        "category",
        "wsda_id",
        "is_cdfa_oim_registered",
        "cdfa_oim_reg_number",
    )
    list_filter = ("category", "is_cdfa_oim_registered")
    search_fields = ("brand_name", "manufacturer", "wsda_id", "cdfa_oim_reg_number")
    ordering = ("brand_name",)


@admin.register(IngestionRun)
class IngestionRunAdmin(admin.ModelAdmin):
    list_display = ("ran_at", "source", "status", "rows_created", "rows_updated")
    list_filter = ("source", "status")
    readonly_fields = ("ran_at", "source", "status", "rows_created", "rows_updated", "message")
    ordering = ("-ran_at",)


@admin.register(NationalListRevision)
class NationalListRevisionAdmin(admin.ModelAdmin):
    list_display = ("fetched_at", "cfr_section", "content_hash", "response_bytes", "change_detected")
    list_filter = ("cfr_section", "change_detected")
    readonly_fields = (
        "cfr_section",
        "fetched_at",
        "source_url",
        "content_hash",
        "response_bytes",
        "raw_json",
        "change_detected",
    )
    ordering = ("-fetched_at",)


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


@admin.register(ApprovedInputChangeLog)
class ApprovedInputChangeLogAdmin(admin.ModelAdmin):
    list_display = [
        "osp",
        "kind",
        "action",
        "target_name_at_change",
        "changed_by",
        "changed_at",
    ]
    list_filter = ["kind", "action"]
    search_fields = [
        "target_name_at_change",
        "change_notification_reference",
        "osp__establishment__name",
    ]
    readonly_fields = [
        "osp",
        "kind",
        "target_national_list",
        "target_omri",
        "target_name_at_change",
        "action",
        "changed_by",
        "changed_at",
    ]
    ordering = ["-changed_at"]
