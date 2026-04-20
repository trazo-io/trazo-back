from rest_framework import serializers

from .models import (
    OSP_SECTION_KEYS,
    ApprovedInputChangeLog,
    Certification,
    CertificationVerificationLog,
    LandownerAffidavit,
    OrganicSystemPlan,
    OSPAnnualUpdate,
)


class CertificationVerificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificationVerificationLog
        fields = [
            "id",
            "attempted_at",
            "status_before",
            "status_after",
            "verification_source",
            "success",
            "error_message",
        ]
        read_only_fields = fields


class CertificationSerializer(serializers.ModelSerializer):
    """Full serializer for producer dashboard CRUD."""

    is_active = serializers.BooleanField(read_only=True)
    consumer_display_status = serializers.CharField(read_only=True)
    certification_type_display = serializers.CharField(source="get_certification_type_display", read_only=True)
    verification_status_display = serializers.CharField(source="get_verification_status_display", read_only=True)

    class Meta:
        model = Certification
        fields = [
            "id",
            "public_id",
            "certification_type",
            "certification_type_display",
            "certification_number",
            "certifier_name",
            "effective_date",
            "expiry_date",
            "certification_scope",
            "certified_items",
            "verification_status",
            "verification_status_display",
            "last_verified_at",
            "verification_source",
            "verification_source_url",
            "verification_notes",
            "usda_operation_name",
            "notes",
            "document_url",
            "is_active",
            "consumer_display_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
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


class ConsumerCertificationSerializer(serializers.ModelSerializer):
    """Minimal serializer for consumer QR page. FTC-compliant language only."""

    display_name = serializers.CharField(source="get_certification_type_display", read_only=True)
    status = serializers.CharField(source="consumer_display_status", read_only=True)

    class Meta:
        model = Certification
        fields = [
            "display_name",
            "certifier_name",
            "status",
            "effective_date",
            "expiry_date",
            "verification_source_url",
        ]


# ---------------------------------------------------------------------------
# Sprint 5A — OSP / Annual Update / Landowner Affidavit serializers
# ---------------------------------------------------------------------------


class OrganicSystemPlanListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — omits full sections JSONB."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    section_completion = serializers.FloatField(read_only=True)

    class Meta:
        model = OrganicSystemPlan
        fields = [
            "id",
            "public_id",
            "version_number",
            "status",
            "status_display",
            "effective_date",
            "submitted_at",
            "approved_at",
            "certifier_template_name",
            "section_completion",
            "created_at",
            "updated_at",
        ]


class _ApprovedNationalListInline(serializers.Serializer):
    """Compact read-only view of an approved NationalListSubstance on an OSP."""

    id = serializers.IntegerField()
    substance_name = serializers.CharField()
    cfr_section = serializers.CharField(required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_null=True)


class _ApprovedOMRIInline(serializers.Serializer):
    """Compact read-only view of an approved OMRIProduct on an OSP."""

    id = serializers.IntegerField()
    product_name = serializers.CharField()
    omri_id = serializers.CharField(required=False, allow_null=True)
    manufacturer = serializers.CharField(required=False, allow_null=True)
    is_cdfa_oim_registered = serializers.BooleanField(required=False)
    cdfa_oim_reg_number = serializers.CharField(required=False, allow_null=True)


class _ApprovedWSDAInline(serializers.Serializer):
    """Compact read-only view of an approved WSDAMaterial on an OSP."""

    id = serializers.IntegerField()
    brand_name = serializers.CharField()
    wsda_id = serializers.CharField(required=False, allow_null=True)
    manufacturer = serializers.CharField(required=False, allow_null=True)
    category = serializers.CharField(required=False, allow_null=True)
    is_cdfa_oim_registered = serializers.BooleanField(required=False)
    cdfa_oim_reg_number = serializers.CharField(required=False, allow_null=True)


class ApprovedInputChangeLogSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for ApprovedInputChangeLog rows.

    Exposed on OSP retrieve responses as approved_input_changes (newest-first,
    per model Meta ordering = ["-changed_at"]). Write access is intentionally
    not exposed — rows are created only by add/remove_approved_input actions.
    """

    changed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ApprovedInputChangeLog
        fields = [
            "id",
            "kind",
            "target_name_at_change",
            "action",
            "changed_by_name",
            "changed_at",
            "change_notification_reference",
            "notes",
        ]
        read_only_fields = fields

    def get_changed_by_name(self, obj):
        """Return a display name for the user who made the change, or None."""
        user = obj.changed_by
        if user is None:
            return None
        full = (f"{user.first_name} {user.last_name}").strip()
        return full or getattr(user, "email", None) or str(user)


class OrganicSystemPlanSerializer(serializers.ModelSerializer):
    """Full OSP serializer for dashboard CRUD."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    section_completion = serializers.FloatField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    # Sprint 5.1 — Read-only projections of the approved-inputs M2Ms. Writes
    # go through the add_approved_input / remove_approved_input viewset
    # actions, not via PATCH, to keep audit trails clean and validations
    # explicit.
    approved_national_list_substances = _ApprovedNationalListInline(many=True, read_only=True)
    approved_omri_products = _ApprovedOMRIInline(many=True, read_only=True)
    approved_wsda_materials = _ApprovedWSDAInline(many=True, read_only=True)

    # Sprint 5.1 GA — append-only change log. Nested read-only; writes happen
    # exclusively inside add/remove_approved_input viewset actions.
    approved_input_changes = ApprovedInputChangeLogSerializer(many=True, read_only=True)

    # P0-5 — registry ↔ narrative sync diff. Inspector signal: narrative mentions
    # inputs but registry has fewer structured entries, or registry entries don't
    # appear in the narrative. Frontend surfaces as a yellow warning banner.
    registry_sync_diff = serializers.SerializerMethodField()

    def get_registry_sync_diff(self, osp):
        from history.services.audit_export_service import (
            OSP_NARRATIVE_MATERIAL_FLOOR,
            REGISTRY_THIN_THRESHOLD,
            _compute_registry_sync_diff,
        )

        sections = osp.sections or {}
        narrative = (sections.get("inputs_list") or {}).get("narrative", "") or ""
        diff = _compute_registry_sync_diff(
            inputs_narrative=narrative,
            omri_products=list(osp.approved_omri_products.all()),
            wsda_materials=list(osp.approved_wsda_materials.all()),
            nl_substances=list(osp.approved_national_list_substances.all()),
        )
        narrative_len = len(narrative.strip())
        missing_from_narrative = [e for e in diff["registry_entries"] if not e["in_narrative"]]
        # Derive the same REVIEW condition the PDF surfaces so the frontend banner
        # can show an identical message and farmers don't get mixed signals.
        has_warning = bool(missing_from_narrative) or (
            narrative_len >= OSP_NARRATIVE_MATERIAL_FLOOR and diff["registry_total"] < REGISTRY_THIN_THRESHOLD
        )
        return {
            "registry_total": diff["registry_total"],
            "narrative_char_count": narrative_len,
            "entries_not_in_narrative": [{"source": e["source"], "name": e["name"]} for e in missing_from_narrative],
            "has_warning": has_warning,
        }

    class Meta:
        model = OrganicSystemPlan
        fields = [
            "id",
            "public_id",
            "establishment",
            "certification",
            "version_number",
            "previous_version",
            "status",
            "status_display",
            "effective_date",
            "submitted_at",
            "approved_at",
            "sections",
            "pdf_document",
            "submission_pdf",
            "approval_document",
            "approval_certificate_number",
            "approval_certifier_name",
            "approved_national_list_substances",
            "approved_omri_products",
            "approved_wsda_materials",
            "approved_input_changes",
            "registry_sync_diff",
            "certifier_template_name",
            "certifier_template_url",
            "notes",
            "section_completion",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "establishment",
            "version_number",
            "previous_version",
            "submission_pdf",  # Set only by submit() action.
            "approved_at",
            "approved_national_list_substances",
            "approved_omri_products",
            "approved_wsda_materials",
            "approved_input_changes",
            "registry_sync_diff",
            "created_at",
            "updated_at",
        ]

    def validate_sections(self, value):
        """
        Enforce that every required § 205.201(a)(1)-(6) section key is present.
        Unknown keys are allowed (certifier-specific extensions) but required keys
        cannot be dropped — the frontend editor must always show all six.
        """
        if not isinstance(value, dict):
            raise serializers.ValidationError("sections must be a JSON object.")
        missing = [k for k in OSP_SECTION_KEYS if k not in value]
        if missing:
            raise serializers.ValidationError(f"Missing required OSP sections per 7 CFR 205.201(a): {missing}")
        return value


class OSPAnnualUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OSPAnnualUpdate
        fields = [
            "id",
            "public_id",
            "prior_osp",
            "new_osp",
            "reporting_year",
            "changes_summary",
            "additions",
            "deletions",
            "sections_unchanged_attestation",
            "submitted_at",
            "certifier_acknowledged_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "certifier_acknowledged_at",
            "created_at",
            "updated_at",
        ]


class LandownerAffidavitSerializer(serializers.ModelSerializer):
    attestation_default = serializers.SerializerMethodField()

    class Meta:
        model = LandownerAffidavit
        fields = [
            "id",
            "public_id",
            "parcel",
            "osp",
            "farm_name",
            "field_name",
            "field_acres",
            "previous_manager_name",
            "previous_manager_address",
            "previous_manager_phone",
            "landowner_name",
            "landowner_address",
            "landowner_phone",
            "yearly_history",
            "last_prohibited_date",
            "attestation_text",
            "attestation_default",
            "previous_manager_signed_date",
            "landowner_signed_date",
            "signed_document",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]

    def get_attestation_default(self, obj):
        """
        Expose the canonical MOFGA attestation text as a read-only hint for the UI
        so the form can pre-fill while still allowing the operator to review/edit.
        """
        return LandownerAffidavit.ATTESTATION_TEXT
