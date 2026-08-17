import os

from django.conf import settings

from rest_framework import serializers

from .models import GeneratedDocument

# What a certified operation legitimately puts on its document shelf: the certifier-facing
# paperwork, the spreadsheets certifiers send, scans and photos of labels and receipts, and
# the ZIP/XLSX artifacts Trazo itself generates.
#
# Validated by EXTENSION, not by the browser-declared Content-Type. The declared type is
# client-controlled and trivially spoofed, so it cannot be the gate; the extension is what
# the filename is stored and served under. Downloads already stream with
# `Content-Disposition: attachment` (never inline), so the allowlist is about keeping the
# shelf coherent and refusing executables, not about trusting either value.
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
            "parcel",
            "history",
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
