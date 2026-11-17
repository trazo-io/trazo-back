"""Consumer QR scans of a production."""

from django.db import models

from .production import Production

# Bot probability at or above which a scan is not counted as a person.
#
# Was written inline at two different values — 0.3 in `company/views.py`, 0.5 in
# `analytics_service.py` — so the same farm's scan total depended on which screen asked.
# 0.5 is the value the create path already uses to gate scan notifications and the one the
# analytics service applies in five places; it is also the more forgiving of the two, so
# unifying on it never silently drops borderline-human traffic from a farmer's own numbers.
COUNTED_SCAN_BOT_SCORE_MAX = 0.5


class HistoryScanQuerySet(models.QuerySet):
    """Queryset for HistoryScan, carrying the ONE definition of a countable scan."""

    def counted(self):
        """
        Scans that count as a visit — the single source of truth for every scan TOTAL.

        Excludes:
          - duplicates: another scan of the same production within
            `DeduplicationService.DEFAULT_TIMEFRAME_MINUTES` from the same session
            fingerprint (a reload or a re-scan, not a second person);
          - likely bots: `bot_score >= COUNTED_SCAN_BOT_SCORE_MAX`.

        Both fields are non-null with DB defaults (`is_duplicate=False`, `bot_score=0.0`), so
        this filter never silently drops rows written by a path that does not set them —
        `public_history` sets neither, and its scans still count.

        Use this for every count, chart, quota and stat. Do NOT use it for the machinery that
        has to see raw rows: deduplication lookups, GDPR retention cleanup, bot-detection
        pattern analysis.
        """
        return self.filter(is_duplicate=False, bot_score__lt=COUNTED_SCAN_BOT_SCORE_MAX)


class HistoryScan(models.Model):
    """
    Enhanced QR scan tracking with 2025 privacy, performance & security standards
    Supports dual functionality: page view analytics + consumer feedback collection
    """

    objects = HistoryScanQuerySet.as_manager()

    # EXISTING CORE FIELDS
    history = models.ForeignKey(
        Production,
        on_delete=models.CASCADE,
        related_name="history_scans",
    )
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, blank=True, null=True)
    date = models.DateTimeField(auto_now_add=True)
    comment = models.TextField(blank=True, null=True)

    # PRIVACY & GDPR COMPLIANCE (2025 Standard)
    ip_hash = models.CharField(
        max_length=64,
        db_index=True,
        blank=True,
        null=True,
        help_text="SHA-256 hash of IP address for privacy-safe analytics",
    )
    consent_given = models.BooleanField(default=False, help_text="GDPR consent for analytics tracking")
    consent_timestamp = models.DateTimeField(null=True, blank=True, help_text="When consent was given")
    data_retention_until = models.DateTimeField(null=True, blank=True, help_text="Auto-cleanup date (GDPR compliance)")

    # ENHANCED GEOLOCATION (Privacy-safe)
    country_code = models.CharField(max_length=2, blank=True, help_text="ISO country code (privacy-safe)")
    region = models.CharField(max_length=100, blank=True, help_text="State/region only (no city for privacy)")

    # LEGACY FIELDS (Deprecated - use privacy-safe alternatives above)
    ip_address = models.CharField(max_length=45, blank=True, null=True, help_text="DEPRECATED: Use ip_hash instead")
    city = models.CharField(max_length=100, blank=True, null=True, help_text="DEPRECATED: Use region instead")
    country = models.CharField(max_length=100, blank=True, null=True, help_text="DEPRECATED: Use country_code instead")

    # SESSION & DEDUPLICATION
    session_hash = models.CharField(
        max_length=64, db_index=True, blank=True, help_text="Privacy-safe browser fingerprint for deduplication"
    )
    is_duplicate = models.BooleanField(default=False, help_text="Mark duplicate scans within timeframe")
    original_scan = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Link to original scan if this is a duplicate",
    )

    # BOT DETECTION & QUALITY CONTROL
    bot_score = models.FloatField(default=0.0, help_text="Bot probability (0.0=human, 1.0=bot)")
    is_verified_human = models.BooleanField(default=False, help_text="Passed human verification checks")
    user_agent_hash = models.CharField(max_length=64, blank=True, help_text="Hashed user agent for pattern analysis")

    # CLAIM TOKEN — opaque token returned to the client so anonymous scans can be
    # linked to an account after sign-in, without exposing sequential IDs (IDOR prevention).
    claim_token = models.CharField(
        max_length=43,
        unique=True,
        db_index=True,
        blank=True,
        help_text="Opaque token for anonymous scan claiming (prevents IDOR)",
    )

    # ENGAGEMENT & ANALYTICS
    scan_type = models.CharField(
        max_length=20,
        choices=[
            ("qr", "QR Code Scan"),
            ("feedback", "Feedback Only"),
            ("review", "Full Review"),
            ("share", "Social Share"),
        ],
        default="qr",
        help_text="Type of interaction",
    )
    engagement_score = models.FloatField(default=0.0, help_text="Engagement quality (time spent, interactions)")
    referrer_type = models.CharField(
        max_length=50,
        blank=True,
        choices=[
            ("qr", "QR Code"),
            ("direct", "Direct Link"),
            ("social", "Social Media"),
            ("search", "Search Engine"),
            ("email", "Email"),
            ("other", "Other"),
        ],
        default="qr",
        help_text="How user reached the page",
    )

    # PERFORMANCE INDEXES
    class Meta:
        indexes = [
            # Time-series queries for dashboard analytics
            models.Index(fields=["date", "history"], name="historyscan_date_history_idx"),
            # Session deduplication queries
            models.Index(fields=["session_hash", "date"], name="historyscan_session_date_idx"),
            # Rate limiting by IP hash
            models.Index(fields=["ip_hash", "date"], name="historyscan_ip_date_idx"),
            # GDPR cleanup queries
            models.Index(fields=["data_retention_until"], name="historyscan_retention_idx"),
            # Quality filtering (exclude bots/duplicates)
            models.Index(fields=["is_duplicate", "bot_score"], name="historyscan_quality_idx"),
            # Consent management
            models.Index(fields=["consent_given", "date"], name="historyscan_consent_idx"),
            # Analytics queries by scan type
            models.Index(fields=["scan_type", "date"], name="historyscan_type_date_idx"),
        ]
        verbose_name = "History Scan"
        verbose_name_plural = "History Scans"

    def save(self, *args, **kwargs):
        if not self.claim_token:
            import secrets

            self.claim_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Scan {self.id} - {self.history} - {self.date.strftime('%Y-%m-%d')}"

    def is_privacy_compliant(self):
        """Check if scan data follows privacy best practices"""
        return bool(
            self.ip_hash  # Uses hashed IP, not raw
            and not self.ip_address  # No raw IP stored
            and self.consent_given  # Has user consent
            and self.data_retention_until  # Has cleanup date
        )

    def is_high_quality(self):
        """Check if scan is high quality (human, not duplicate, engaged)"""
        return bool(not self.is_duplicate and self.bot_score < 0.3 and self.engagement_score > 0.1)

    def get_location_display(self):
        """Get privacy-safe location display"""
        # Skip placeholder/default values
        has_country = self.country_code and self.country_code != "XX"
        has_region = self.region and self.region != "Unknown"

        if has_country and has_region:
            return f"{self.region}, {self.country_code.upper()}"
        elif has_country:
            return self.country_code.upper()
        # Fallback to legacy data if new data not available
        elif self.city and self.country:
            return f"{self.city}, {self.country}"
        elif self.country:
            return self.country
        return None
