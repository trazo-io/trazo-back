import os

from django.conf import settings

from rest_framework import serializers

from .models import ExportJob, GeneratedDocument

# What a certified operation legitimately puts on its document shelf: the certifier-facing
# paperwork, the spreadsheets certifiers send, scans and photos of labels and receipts, and
# the ZIP/XLSX artifacts Trazo itself generates.
#
# Validated by EXTENSION, not by the browser-declared Content-Type. The declared type is
# client-controlled and trivially spoofed, so it cannot be the gate; the extension is what
# the filename is stored and served under. Downloads already stream with
# `Content-Disposition: attachment` (never inline), so the allowlist is about keeping the
# shelf coherent and refusing executables, not about trusting either value.
#: The one message for a receipt filed on a record that cannot hold one, from the serializer (wrong
#: record type) and the view (a production record that is not a seed purchase).
RECEIPT_RECORD_MESSAGE = "A purchase receipt is filed on a spray, amendment or seed purchase record."

ALLOWED_DOCUMENT_EXTENSIONS = {
    # Certifier paperwork
    ".pdf",
    # Scans and label/receipt photos
    ".jpg",
    ".jpeg",
    ".png",
    ".heic",
    ".heif",
    ".webp",
    ".tif",
    ".tiff",
    # Spreadsheets and documents certifiers exchange
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".csv",
    ".txt",
    # Trazo's own packet artifacts, re-uploaded
    ".zip",
}


def _validate_document_file(uploaded):
    """Size and extension gate for one uploaded document.

    Raised as a field error rather than checked in the view so the refusal arrives as a
    400 the form can render against the file input, not a 500 or a truncated write.
    """
    max_bytes = getattr(settings, "DOCUMENT_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)
    size = getattr(uploaded, "size", None)
    if size is not None and size > max_bytes:
        raise serializers.ValidationError(
            f"File is {size / (1024 * 1024):.1f} MB. The limit is " f"{max_bytes // (1024 * 1024)} MB per document."
        )

    ext = os.path.splitext(getattr(uploaded, "name", "") or "")[1].lower()
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        allowed = ", ".join(sorted(e.lstrip(".") for e in ALLOWED_DOCUMENT_EXTENSIONS))
        raise serializers.ValidationError(f"{ext or 'This file type'} is not accepted. Allowed types: {allowed}.")
    return uploaded


class GeneratedDocumentSerializer(serializers.ModelSerializer):
    folder_display = serializers.CharField(source="get_folder_display", read_only=True)
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    is_deletable = serializers.BooleanField(read_only=True)
    created_by_name = serializers.SerializerMethodField()

    def get_created_by_name(self, obj):
        user = obj.created_by
        if not user:
            return None
        full = f"{user.first_name} {user.last_name}".strip()
        return full or user.email

    class Meta:
        model = GeneratedDocument
        fields = [
            "id",
            "public_id",
            "folder",
            "folder_display",
            "source",
            "source_display",
            "title",
            "content_type",
            "size_bytes",
            "linked_section",
            "requirement",
            "parcel",
            "history",
            "sales_record",
            "source_kind",
            "event_type",
            "event_id",
            "tags",
            "is_deletable",
            "created_by_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "public_id",
            "folder_display",
            "source_display",
            "content_type",
            "size_bytes",
            "is_deletable",
            "created_by_name",
            "created_at",
        ]


class DocumentUploadSerializer(serializers.Serializer):
    """Multipart upload payload — uploads always land with source='upload'."""

    file = serializers.FileField(validators=[_validate_document_file])
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)
    folder = serializers.ChoiceField(
        choices=[c for c, _ in GeneratedDocument.FOLDER_CHOICES],
        default="uploads",
    )
    linked_section = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    tags = serializers.ListField(child=serializers.CharField(max_length=64), required=False, default=list)
    # 🔴 2026-08-16 (CCOF grower-checklist audit). Four of the eight checklist items name a
    # DOCUMENT as the record — purchase receipts, the handler's organic certificate, delivery
    # documents, pack-out summaries — and each of those belongs to a specific lot or field. The
    # model has carried `history` and `parcel` since WS-3 and the upload endpoint never accepted
    # them, so every farmer upload landed unattached in a flat "uploads" folder and no export
    # could find it. Integers rather than PrimaryKeyRelatedField: the view resolves them against
    # the URL's establishment, so an unscoped default queryset never gets the chance to accept
    # another farm's row.
    history = serializers.IntegerField(required=False, allow_null=True)
    parcel = serializers.IntegerField(required=False, allow_null=True)
    sales_record = serializers.IntegerField(required=False, allow_null=True)
    source_kind = serializers.ChoiceField(
        choices=[c for c, _ in GeneratedDocument.SOURCE_KIND_CHOICES], required=False, allow_blank=True, default=""
    )
    requirement = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    # The activity record this file belongs to (pilot rehearsal 2026-10, finding 4). Integers for
    # the same reason as `history`: the view resolves the pair against the URL's establishment,
    # so another farm's event id is refused there, never looked up unscoped.
    event_type = serializers.IntegerField(required=False, allow_null=True)
    event_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_event_type(self, value):
        if value is None:
            return None
        from history.constants import EVENT_TYPE_TO_MODEL

        if value not in EVENT_TYPE_TO_MODEL:
            raise serializers.ValidationError(f"{value} is not an activity type.")
        return value

    def validate(self, attrs):
        # Half a link is refused rather than dropped: a file that silently lost its record
        # looks attached and is not, and the grower finds out at inspection.
        has_type = attrs.get("event_type") is not None
        has_id = attrs.get("event_id") is not None
        if has_type != has_id:
            missing = "event_id" if has_type else "event_type"
            raise serializers.ValidationError({missing: "An activity link needs both event_type and event_id."})
        # A purchase receipt is a receipt OF a spray, amendment or seed purchase record: filed on
        # one, never on a sale and never loose, or the packet would list a receipt that belongs to
        # nothing. Only the record TYPE is checked here. Whether a production record is a seed
        # purchase (planting, transplanting, seed search) needs the record, and the view loads it
        # scoped to the farm first: checking the subtype here, before that scope, would answer
        # "harvest or planting?" about another farm's id through a different error key.
        if attrs.get("source_kind") == "receipt":
            from history.services.record_receipts import RECEIPT_EVENT_TYPES

            if attrs.get("event_type") not in RECEIPT_EVENT_TYPES or attrs.get("sales_record"):
                raise serializers.ValidationError({"source_kind": RECEIPT_RECORD_MESSAGE})
        return attrs

    def validate_requirement(self, value):
        """Only a real upload question is a requirement. Free text would let a file claim to
        answer anything, and the coverage page trusts this field."""
        if not value:
            return ""
        from certifications.services.packet_attachments import upload_requirements

        if value not in upload_requirements():
            raise serializers.ValidationError(f"{value} is not an attachment any plan section asks for.")
        return value


class ExportJobSerializer(serializers.ModelSerializer):
    """What a client polls. `document_id` is the handle for the Documents download route; the
    bytes never travel through this endpoint."""

    document_id = serializers.IntegerField(read_only=True)
    document_title = serializers.CharField(source="document.title", read_only=True, default=None)
    document_size_bytes = serializers.IntegerField(source="document.size_bytes", read_only=True, default=None)
    is_terminal = serializers.BooleanField(read_only=True)

    class Meta:
        model = ExportJob
        fields = [
            "public_id",
            "kind",
            "audience",
            "certification_type",
            "period_start",
            "period_end",
            "status",
            "is_terminal",
            "progress_current",
            "progress_total",
            "progress_label",
            "error",
            "document_id",
            "document_title",
            "document_size_bytes",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields
