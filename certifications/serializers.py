from rest_framework import serializers

from .models import Certification, CertificationVerificationLog


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
