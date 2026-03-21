import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .constants import CERTIFICATION_TYPE_CHOICES, VERIFICATION_STATUS_CHOICES


class Certification(models.Model):
    """
    Structured certification record linked to an Establishment.
    Supports automated verification against external databases (USDA, etc.).
    """

    public_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
    )

    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="structured_certifications",
        help_text="Establishment this certification belongs to",
    )

    # Certification details
    certification_type = models.CharField(
        max_length=30,
        choices=CERTIFICATION_TYPE_CHOICES,
        help_text="Type of agricultural certification",
    )
    certification_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Certificate number or reference ID",
    )
    certifier_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Name of the certifying organization",
    )
    effective_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date certification became effective",
    )
    expiry_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date certification expires",
    )
    certification_scope = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Scope of certification (e.g., Crops, Handling, Livestock)",
    )
    certified_items = models.JSONField(
        default=list,
        blank=True,
        help_text="List of certified products/items from the certifying body",
    )

    # Verification state
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default="pending",
        help_text="Current verification status",
    )
    last_verified_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Timestamp of last successful verification check",
    )
    verification_source = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Source used for verification (e.g., usda_organic_integrity_db)",
    )
    verification_source_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="URL to the verification source record",
    )
    raw_api_response = models.JSONField(
        blank=True,
        null=True,
        help_text="Raw response from the verification API for audit trail",
    )
    verification_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Notes from the verification process (e.g., fuzzy match details)",
    )

    # User-provided metadata
    usda_operation_name = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text="USDA-registered operation name if different from establishment name",
    )
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="User-provided notes about this certification",
    )
    document_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="URL to uploaded certification document",
    )

    # Tracking
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_certifications",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Certification"
        verbose_name_plural = "Certifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["establishment", "certification_type"]),
            models.Index(fields=["verification_status"]),
            models.Index(fields=["expiry_date"]),
        ]
        unique_together = [
            ("establishment", "certification_type", "certification_number"),
        ]

    def __str__(self):
        return f"{self.get_certification_type_display()} - {self.establishment.name}"

    @property
    def is_active(self):
        """Check if certification is currently active (not expired/revoked)."""
        if self.verification_status in ("revoked", "suspended"):
            return False
        if self.expiry_date and self.expiry_date < timezone.now().date():
            return False
        return True

    @property
    def is_verified(self):
        return self.verification_status == "verified"

    @property
    def consumer_display_status(self):
        """FTC-compliant status for consumer display."""
        if self.verification_status == "verified":
            return "verified_via_database"
        elif self.verification_status == "self_reported":
            return "self_reported"
        elif self.verification_status in ("expired", "revoked", "suspended"):
            return "inactive"
        return "pending"


class CertificationVerificationLog(models.Model):
    """Audit trail for all verification attempts."""

    certification = models.ForeignKey(
        Certification,
        on_delete=models.CASCADE,
        related_name="verification_logs",
    )
    attempted_at = models.DateTimeField(auto_now_add=True)
    status_before = models.CharField(max_length=20)
    status_after = models.CharField(max_length=20)
    verification_source = models.CharField(max_length=50)
    success = models.BooleanField()
    error_message = models.TextField(blank=True, null=True)
    raw_response = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = "Verification Log"
        verbose_name_plural = "Verification Logs"

    def __str__(self):
        return f"{self.certification} - {self.status_before} → {self.status_after}" f" ({self.attempted_at:%Y-%m-%d})"


class USDAOrganicOperation(models.Model):
    """
    Local cache of USDA Organic Integrity Database records.
    Populated monthly from the USDA bulk XLSX export.
    Source: https://organic.ams.usda.gov/integrity/Reports/DataHistory
    """

    op_name = models.CharField(max_length=300, db_index=True, help_text="Operation business name")
    op_name_normalized = models.CharField(
        max_length=300, db_index=True, help_text="Lowercased, stripped name for fuzzy search"
    )
    state = models.CharField(max_length=100, db_index=True, help_text="Physical address state")
    country = models.CharField(max_length=100, default="United States of America (the)")
    status = models.CharField(max_length=30, help_text="Certified / Surrendered / Suspended / Revoked")
    status_effective_date = models.CharField(max_length=20, blank=True, null=True)
    certifier_name = models.CharField(max_length=200, blank=True, null=True)
    certified_products = models.TextField(blank=True, null=True, help_text="Comma-separated certified products")
    scope_crops = models.CharField(max_length=30, blank=True, null=True)
    scope_livestock = models.CharField(max_length=30, blank=True, null=True)
    scope_handling = models.CharField(max_length=30, blank=True, null=True)
    scope_wild_crops = models.CharField(max_length=30, blank=True, null=True)
    total_acreage = models.FloatField(blank=True, null=True)

    # Metadata
    data_snapshot_date = models.DateField(help_text="Date of the USDA bulk export this record came from")
    imported_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "USDA Organic Operation"
        verbose_name_plural = "USDA Organic Operations"
        indexes = [
            models.Index(fields=["op_name_normalized", "state"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.op_name} ({self.state}) - {self.status}"
