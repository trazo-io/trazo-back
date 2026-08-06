from django.utils import timezone

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from .models import (
    OSP_SECTION_KEYS,
    ApprovedInputChangeLog,
    Certification,
    CertificationVerificationLog,
    CertifierAccessLink,
    CertifierAccessLog,
    LandownerAffidavit,
    OrganicSystemPlan,
    OSPAnnualUpdate,
    OSPChangeNotification,
    PostHarvestFacility,
    StateOrganicRegistration,
)


class PostHarvestFacilitySerializer(serializers.ModelSerializer):
    """Producer-dashboard CRUD for off-farm post-harvest handlers (CCOF G6.1)."""

    facility_type_display = serializers.CharField(source="get_facility_type_display", read_only=True)
    verification_status_display = serializers.CharField(source="get_verification_status_display", read_only=True)
    is_verified = serializers.BooleanField(read_only=True)
    cert_is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = PostHarvestFacility
        fields = [
            "id",
            "public_id",
            "establishment",
            "name",
            "facility_type",
            "facility_type_display",
            "address",
            "city",
            "state",
            "certification_number",
            "certifier_name",
            "effective_date",
            "expiry_date",
            "cert_document",
            "verification_status",
            "verification_status_display",
            "is_verified",
            "cert_is_current",
            "last_verified_at",
            "verification_source",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "verification_status",
            "last_verified_at",
            "verification_source",
            "raw_api_response",
            "created_at",
            "updated_at",
        ]


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


# Values that are obviously scratch input rather than a real answer. A length floor
# was rejected as the tool here: "No material changes." is a valid annual-update
# summary and would fail one, while "Test" would pass a short one. Match the
# failure mode instead — the same approach as the OFPP suspicious-filename check.
PLACEHOLDER_VALUES = {
    "test",
    "tests",
    "testing",
    "tbd",
    "todo",
    "n/a",
    "na",
    "none",
    "asdf",
    "qwerty",
    "xxx",
    "aaa",
    "foo",
    "bar",
    "sample",
    "placeholder",
    "prueba",
}


# Punctuation stripped from each word before matching. "/" is deliberately absent so
# "n/a" stays matchable.
_ENTRY_PUNCTUATION = ".,!?;:\"'()[]{}-–—_*"


def looks_like_placeholder(value) -> bool:
    """True when *every* word in the value is scratch input.

    Whole-string matching let "test test" through — the same failure this guard exists
    to stop, one space wider. Matching per word still clears "Latest soil test results",
    where only one word is a placeholder.
    """
    if not value:
        return False
    tokens = [token.strip(_ENTRY_PUNCTUATION).lower() for token in str(value).split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return False
    return all(token in PLACEHOLDER_VALUES for token in tokens)


def _quote_all(items) -> str:
    """Quote offending entries for a farmer-facing message.

    repr() was leaking Python's quoting conventions into a message a grower reads.
    """
    return ", ".join('"{}"'.format(item) for item in items)


class OSPAnnualUpdateSerializer(serializers.ModelSerializer):
    def validate_changes_summary(self, value):
        # 7 CFR 205.406 annual update goes to the certifier. "Test" reached a real
        # dossier and rendered verbatim into the regulatory filing (2026-08-03 review).
        if looks_like_placeholder(value):
            raise serializers.ValidationError(
                "Describe the actual changes for the reporting year, or state that there were none."
            )
        return value

    # Arbitrary keyboard noise ("TNe") is not matchable as a placeholder word, but an
    # additions/deletions entry is meant to DESCRIBE a change to the certifier, and
    # three characters cannot. Deliberately low so a real short entry ("Lime") passes.
    MIN_CHANGE_ENTRY_CHARS = 4

    def _clean_entry_list(self, value):
        """Reject entries that cannot describe a change to a certifier.

        The two failure modes are kept apart on purpose. A placeholder word and a
        three-character string need different instructions — "replace it" versus "write
        more" — and the single shared sentence this replaces gave neither. The field name
        is also gone from the text: DRF already keys the error under `additions` /
        `deletions`, so repeating it produced "additions: Additions contains entries...".
        """
        if not value:
            return value
        placeholders = []
        too_short = []
        for item in value:
            text = str(item).strip()
            if looks_like_placeholder(text):
                placeholders.append(text)
            elif len(text) < self.MIN_CHANGE_ENTRY_CHARS:
                too_short.append(text)
        problems = []
        if placeholders:
            problems.append(
                "Placeholder text, not a change: {}. Replace or delete {}.".format(
                    _quote_all(placeholders),
                    "that line" if len(placeholders) == 1 else "those lines",
                )
            )
        if too_short:
            problems.append(
                "Too short to describe a change: {}. Use at least {} characters, or delete {}.".format(
                    _quote_all(too_short),
                    self.MIN_CHANGE_ENTRY_CHARS,
                    "that line" if len(too_short) == 1 else "those lines",
                )
            )
        if problems:
            raise serializers.ValidationError(" ".join(problems))
        return value

    def validate_additions(self, value):
        return self._clean_entry_list(value)

    def validate_deletions(self, value):
        return self._clean_entry_list(value)

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
        # The model's UniqueConstraint(prior_osp, reporting_year) is not picked up as a
        # serializer validator, so filing the same year twice reached the database and
        # surfaced as a 500 IntegrityError page instead of a field error. The UI guards
        # against it too, but that guard reads a client-side list — a second tab, a
        # retried request, or any non-UI caller would still hit the raw constraint.
        validators = [
            UniqueTogetherValidator(
                queryset=OSPAnnualUpdate.objects.all(),
                fields=["prior_osp", "reporting_year"],
                message="An annual update has already been filed for this OSP and reporting year.",
            )
        ]


class OSPChangeNotificationSerializer(serializers.ModelSerializer):
    """Notification-of-Changes record — 7 CFR 205.400(f) / NOP 2615 §3.4."""

    change_category_display = serializers.CharField(source="get_change_category_display", read_only=True)
    method_display = serializers.CharField(source="get_method_display", read_only=True)
    documentation_timing_display = serializers.CharField(source="get_documentation_timing_display", read_only=True)
    cfr_reference = serializers.CharField(read_only=True)
    is_immediate = serializers.BooleanField(read_only=True)

    class Meta:
        model = OSPChangeNotification
        fields = [
            "id",
            "osp",
            "change_category",
            "change_category_display",
            "description",
            "date_notified",
            "method",
            "method_display",
            "documentation_timing",
            "documentation_timing_display",
            "supporting_document",
            "certifier_acknowledged_at",
            "cfr_reference",
            "is_immediate",
            "created_at",
        ]
        read_only_fields = ["id", "osp", "created_at"]


class LandownerAffidavitSerializer(serializers.ModelSerializer):
    attestation_default = serializers.SerializerMethodField()
    # The form hint says "leave blank to use the standard wording". The model TextField has
    # default="" but no blank=True, so DRF's mapped field rejects an explicit "" with
    # "This field may not be blank" (a silent 400 for a farmer following the hint). Allow
    # blank here and fill the canonical MOFGA attestation in validate() so the stored/exported
    # attestation is never empty.
    attestation_text = serializers.CharField(required=False, allow_blank=True, default="")

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

    def validate(self, attrs):
        """Blank attestation → the canonical MOFGA wording (honors the form's own hint).

        Only fills when attestation_text is actually being written (present in attrs). On a
        partial PATCH that omits the field entirely (e.g. editing just a phone number), we must
        NOT inject the default — that would overwrite a previously-saved custom attestation.
        On create, DRF applies the field default ("") so the key is present and gets filled.
        """
        if "attestation_text" in attrs and not (attrs.get("attestation_text") or "").strip():
            attrs["attestation_text"] = LandownerAffidavit.ATTESTATION_TEXT
        return attrs


class StateOrganicRegistrationSerializer(serializers.ModelSerializer):
    def validate_county(self, value):
        """CDFA registration is per-county and CalAgPermits validates on the county.

        Catching a bad county here beats discovering it at PUR-export time, where it
        surfaces as "County 'X' is not a recognized CA county" on a document already
        headed to the County Agricultural Commissioner.
        """
        if not value:
            return value
        from history.services.pur_export_service import _CA_COUNTY_CODES

        known = {name.strip().lower() for name in _CA_COUNTY_CODES}
        candidate = value.strip().lower().replace(" county", "")
        if candidate not in known:
            raise serializers.ValidationError(
                f"'{value}' is not a California county. CDFA registration is filed per county."
            )
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        registration = attrs.get("registration_date") or getattr(self.instance, "registration_date", None)
        renewal = attrs.get("renewal_date") or getattr(self.instance, "renewal_date", None)
        # A renewal dated the same day as the registration carries no information and
        # makes is_current() meaningless — it was rendering that way on a live record.
        if registration and renewal and renewal <= registration:
            raise serializers.ValidationError({"renewal_date": "Renewal date must be after the registration date."})
        return attrs

    """Producer-dashboard CRUD for State Organic Program registration (CDFA SOP).

    Distinct from CDFA OIM (input-material) registration — this is the
    producer/operation registration CA wholesale (> $5,000 organic) operations
    must hold before their first organic sale (CA Food & Ag Code §§ 46000-46029).
    """

    operation_type_display = serializers.CharField(source="get_operation_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = StateOrganicRegistration
        fields = [
            "id",
            "public_id",
            "establishment",
            "state",
            "program_name",
            "operation_type",
            "operation_type_display",
            "status",
            "status_display",
            "registration_number",
            "county",
            "commodities",
            "prior_year_organic_gross_sales",
            "registration_date",
            "renewal_date",
            "registration_document",
            "notes",
            "is_current",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]


class CertifierAccessLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = CertifierAccessLog
        fields = ["id", "action", "action_display", "accessed_at", "ip_address"]
        read_only_fields = fields


class CertifierAccessLinkSerializer(serializers.ModelSerializer):
    """Farmer-facing view of a certifier review link.

    `token` is exposed to the OWNER only (this serializer is used behind the
    authenticated, company-scoped viewset) so the farmer can copy the URL to send
    their certifier. It is never rendered on any anonymous surface.
    """

    accesses = CertifierAccessLogSerializer(many=True, read_only=True)
    # Optional on input; create() falls back to the 90-day default.
    expires_at = serializers.DateTimeField(required=False)
    access_count = serializers.SerializerMethodField()
    last_accessed_at = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_revoked = serializers.BooleanField(read_only=True)

    class Meta:
        model = CertifierAccessLink
        fields = [
            "id",
            "token",
            "label",
            "certification_type",
            "period_start",
            "period_end",
            "expires_at",
            "revoked_at",
            "created_at",
            "is_active",
            "is_expired",
            "is_revoked",
            "access_count",
            "last_accessed_at",
            "accesses",
        ]
        # establishment/token/created_by are set server-side in perform_create;
        # accepting them from the client would let a caller mint a link for
        # another operation or choose a guessable token.
        read_only_fields = [
            "id",
            "token",
            "revoked_at",
            "created_at",
            "is_active",
            "is_expired",
            "is_revoked",
            "access_count",
            "last_accessed_at",
            "accesses",
        ]

    # Both read the prefetched list rather than issuing a query per link.
    # `.count()` and `.first()` each bypass the prefetch cache (they add their own
    # COUNT / LIMIT), so on a farm with N links the list view fired 2N extra queries.
    def get_access_count(self, obj):
        return len(obj.accesses.all())

    def get_last_accessed_at(self, obj):
        accesses = list(obj.accesses.all())  # Meta.ordering = -accessed_at
        return accesses[0].accessed_at if accesses else None

    def validate_expires_at(self, value):
        if value and value <= timezone.now():
            raise serializers.ValidationError("Expiry must be in the future.")
        return value

    def validate_certification_type(self, value):
        # Single source of truth: the export profiles the dossier builder actually
        # knows about. A hardcoded copy here would silently drift and let a farmer
        # mint a link whose profile falls back to "all" — a broader dossier than
        # they chose to share.
        from history.services.audit_export_service import AuditExportService

        valid = set(AuditExportService.CERTIFICATION_SECTIONS)
        if value not in valid:
            raise serializers.ValidationError(f"Invalid certification type. Choose from: {sorted(valid)}")
        return value

    def create(self, validated_data):
        validated_data.setdefault("expires_at", CertifierAccessLink.default_expiry())
        return super().create(validated_data)
