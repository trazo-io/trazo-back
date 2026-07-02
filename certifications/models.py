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


class PostHarvestFacility(models.Model):
    """
    An off-farm post-harvest handler (huller, sheller, dryer, cold storage,
    packer) that a production's crop is sent to. Under CCOF G6.1 (NOPB39) and
    NOP 7 CFR 205.272, when an organic crop is handled by another certified
    operation the audit trail must carry that handler's name + current organic
    certificate (issued within 15 months). Mirrors the Certification model's
    verification fields so the same USDA-OID verifier can validate the handler.
    """

    FACILITY_TYPE_CHOICES = [
        ("huller", "Huller / Sheller"),
        ("dryer", "Dryer"),
        ("cold_storage", "Cold Storage"),
        ("packer", "Packer / Packing Shed"),
        ("custom", "Custom Post-Harvest Handler"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="post_harvest_facilities",
        help_text="Farm operation that sends crop to this handler",
    )
    name = models.CharField(max_length=200, help_text="Handler / facility name")
    facility_type = models.CharField(max_length=20, choices=FACILITY_TYPE_CHOICES, default="huller")
    address = models.CharField(max_length=200, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)

    # Handler's organic certificate (G6.1: must be current, issued within 15 months)
    certification_number = models.CharField(max_length=100, blank=True, null=True)
    certifier_name = models.CharField(max_length=200, blank=True, null=True)
    effective_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    cert_document = models.FileField(
        upload_to="facility_certs/",
        blank=True,
        null=True,
        help_text="Uploaded copy of the handler's organic certificate (S3)",
    )

    # Verification state — mirrors Certification; validated via USDAOrganicVerifier.
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default="pending",
    )
    last_verified_at = models.DateTimeField(blank=True, null=True)
    verification_source = models.CharField(max_length=50, blank=True, null=True)
    raw_api_response = models.JSONField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_post_harvest_facilities",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Post-Harvest Facility"
        verbose_name_plural = "Post-Harvest Facilities"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["establishment", "facility_type"])]

    def __str__(self):
        return f"{self.name} ({self.get_facility_type_display()})"

    @property
    def is_verified(self):
        return self.verification_status == "verified"

    @property
    def cert_is_current(self):
        """
        CCOF G6.1 / NOP 7 CFR 205.272 freshness rule: a handler's organic
        certificate must be current — issued within ~15 months (and not past its
        expiry). Returns True (current), False (expired/stale), or None when there
        is no effective_date to evaluate (unknown -> flag for inspector review).
        """
        from datetime import timedelta

        if not self.effective_date:
            return None
        today = timezone.now().date()
        if self.expiry_date and self.expiry_date < today:
            return False
        return self.effective_date >= (today - timedelta(days=456))  # ~15 months

    def verify(self):
        """
        Best-effort verification of the handler's organic certificate against the
        USDA Organic Integrity Database, reusing the verifier the farm's own certs
        use. Falls back to self_reported when OID has no match (third-party hullers
        frequently are not resolvable by name).
        """
        from certifications.services.usda_organic_verifier import USDAOrganicVerifier

        result = USDAOrganicVerifier().verify(self.name, self.state or "", self.certification_number)
        # Only a positive OID match upgrades to "verified". A no-match is NOT proof
        # the handler is uncertified (our OID mirror may be incomplete or the name may
        # not fuzzy-match), so fall back to self_reported rather than "not_found" —
        # which would misleadingly read as "handler not certified" on the audit PDF.
        self.verification_status = "verified" if getattr(result, "status", None) == "verified" else "self_reported"
        self.last_verified_at = timezone.now()
        self.verification_source = "usda_organic_integrity_db"
        self.raw_api_response = {
            "found": getattr(result, "found", None),
            "notes": getattr(result, "notes", ""),
        }
        return result


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


class NationalListSubstance(models.Model):
    """
    The National List of Allowed and Prohibited Substances — 7 CFR 205.601–205.606.

    Seeded from the eCFR (see certifications/fixtures/national_list.json and the
    seed_national_list management command). This is a small, stable, public list
    updated ~twice/year by the NOSB; no subscription or scraping needed.

    Used to cross-reference chemical and soil-amendment inputs against the regulation
    so inspectors see "Allowed per §205.601(i)" rather than just "farmer self-reported."
    """

    CFR_SECTION_CHOICES = [
        ("205.105", "§205.105 — Excluded substances & methods (prohibited)"),
        ("205.601", "§205.601 — Synthetic allowed (crops)"),
        ("205.602", "§205.602 — Nonsynthetic prohibited (crops)"),
        ("205.603", "§205.603 — Synthetic allowed (livestock)"),
        ("205.605", "§205.605 — Nonagricultural allowed (handling)"),
        ("205.606", "§205.606 — Nonorganic agricultural allowed (handling)"),
    ]

    STATUS_CHOICES = [
        ("allowed", "Allowed"),
        ("prohibited", "Prohibited"),
    ]

    substance_name = models.CharField(
        max_length=200, db_index=True, help_text="Substance name as listed in the regulation"
    )
    substance_name_normalized = models.CharField(
        max_length=200, db_index=True, help_text="Lowercased normalized form for fuzzy matching"
    )
    cfr_section = models.CharField(max_length=10, choices=CFR_SECTION_CHOICES, db_index=True)
    subsection = models.CharField(
        max_length=4,
        blank=True,
        null=True,
        help_text="Regulatory subsection letter (a, b, c, ...)",
    )
    category = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="Functional category (e.g., 'insecticide', 'disease_control', 'amendment')",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    restriction_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Usage restrictions from the regulation (e.g., 'minimize soil accumulation')",
    )
    effective_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date this entry became effective in the CFR",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "National List Substance"
        verbose_name_plural = "National List Substances"
        ordering = ["cfr_section", "subsection", "substance_name"]
        indexes = [
            models.Index(fields=["substance_name_normalized", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["substance_name_normalized", "cfr_section"],
                name="unique_substance_per_section",
            ),
        ]

    def __str__(self):
        return f"{self.substance_name} ({self.cfr_section}{self.subsection or ''} — {self.status})"


class IngestionRun(models.Model):
    """
    Audit record per source-catalog sync run.

    One row per (source, run) so the admin can answer:
        "When was WSDA last synced? Did it succeed? How many rows changed?"

    Surfaced in a simple admin widget and in the audit PDF footer so auditors
    can tell that Trazo keeps input catalogs fresh.
    """

    SOURCE_CHOICES = [
        ("omri", "OMRI Products (committed CSV)"),
        ("wsda", "WSDA Materials List (committed CSV)"),
        ("cdfa_oim", "CDFA OIM cross-reference (committed CSV)"),
        ("national_list_ecfr", "National List — eCFR API snapshot"),
        ("national_list_seed", "National List — committed seed"),
    ]
    STATUS_CHOICES = [
        ("ok", "OK"),
        ("unchanged", "Unchanged"),
        ("changed", "Changed — review committed seed"),
        ("error", "Error"),
        ("skipped", "Skipped"),
    ]

    source = models.CharField(max_length=40, choices=SOURCE_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    ran_at = models.DateTimeField(auto_now_add=True, db_index=True)
    rows_created = models.PositiveIntegerField(default=0)
    rows_updated = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True, help_text="Optional human-readable detail")

    class Meta:
        verbose_name = "Ingestion Run"
        verbose_name_plural = "Ingestion Runs"
        ordering = ["-ran_at"]
        indexes = [
            models.Index(fields=["source", "-ran_at"]),
        ]

    def __str__(self):
        return f"{self.source} @ {self.ran_at.isoformat()} ({self.status})"


class NationalListRevision(models.Model):
    """
    Append-only snapshot of the live § 205.601 / § 205.602 text fetched from
    the eCFR API (https://www.ecfr.gov/developers/documentation/api/v1).

    Each row captures a point-in-time fetch so the audit trail can answer:
      "On {sync_date} the National List at § 205.601 hashed to {content_hash};
       that's the regulation text we evaluated against on this audit."

    Drift against NOSB sunset decisions (every 5 years) or interim amendments
    is detected by `content_hash` changing between runs. When the hash
    changes, the sync command logs a warning so a human can update the
    committed seed_national_list.py list + its test fixtures.
    """

    CFR_SECTION_CHOICES = [
        ("205.601", "§205.601 — Synthetic allowed (crops)"),
        ("205.602", "§205.602 — Nonsynthetic prohibited (crops)"),
    ]

    cfr_section = models.CharField(max_length=10, choices=CFR_SECTION_CHOICES, db_index=True)
    fetched_at = models.DateTimeField(auto_now_add=True, db_index=True)
    source_url = models.URLField(max_length=500, help_text="Exact eCFR API URL hit")
    content_hash = models.CharField(max_length=64, db_index=True, help_text="SHA-256 of the response body")
    response_bytes = models.PositiveIntegerField(help_text="Size of fetched response in bytes")
    raw_json = models.JSONField(help_text="Raw response body (subset) for audit trail")
    change_detected = models.BooleanField(
        default=False,
        help_text="Whether this revision's hash differs from the previous one",
    )

    class Meta:
        verbose_name = "National List Revision (eCFR snapshot)"
        verbose_name_plural = "National List Revisions (eCFR snapshots)"
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["cfr_section", "-fetched_at"]),
        ]

    def __str__(self):
        return f"{self.cfr_section} @ {self.fetched_at.isoformat()} ({self.content_hash[:12]})"


class OMRIProduct(models.Model):
    """
    Farmer-confirmed OMRI (Organic Materials Review Institute) product identifier.

    Trazo does NOT subscribe to the OMRI Products List (paid) and does NOT scrape
    the OMRI website (ToS violation). Instead, when a farmer enters an organic-approved
    chemical, they may paste the OMRI ID they looked up on omri.org themselves.

    We store the ID + product name. We do NOT cross-verify. The audit export makes this
    explicit: "Farmer-reported OMRI ID {omri_id}" — inspector can verify at omri.org.

    Future upgrade path: if Trazo subscribes to OMRI's licensed list, replace this
    model with a synced local cache (see USDAOrganicOperation for the pattern).
    """

    omri_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Product identifier as shown on omri.org (e.g., 'OMRI-01234')",
    )
    product_name = models.CharField(max_length=200, help_text="Product name as shown on omri.org")
    manufacturer = models.CharField(max_length=200, blank=True, null=True)
    category = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="OMRI category (e.g., 'crop-fertilizer', 'crop-pest-control')",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="omri_products_added",
        help_text="User who first entered this OMRI ID into Trazo",
    )
    verified_on_omri_website_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the farmer reports having checked this product on omri.org",
    )
    # California-specific: CDFA OIM (Organic Input Material) registration is a
    # state-law requirement for fertilizing materials sold/used in CA. A product
    # can be NOP/OMRI-compliant but CDFA-unregistered, which is itself a
    # violation for CA operators. These fields let the drift detector escalate
    # a CA-establishment finding when the resolved input lacks a CDFA reg #.
    is_cdfa_oim_registered = models.BooleanField(
        default=False,
        help_text="Whether this product carries a current CDFA OIM registration (CA only)",
    )
    cdfa_oim_reg_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="CDFA OIM registration number, e.g. '#1234-05'",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "OMRI Product (farmer-reported)"
        verbose_name_plural = "OMRI Products (farmer-reported)"
        ordering = ["product_name"]

    def __str__(self):
        return f"{self.product_name} ({self.omri_id})"


class WSDAMaterial(models.Model):
    """
    Washington State Department of Agriculture Organic Brand Name Materials List.

    CCOF and most US certifiers treat WSDA as **co-equal** with OMRI for input
    approval — many products carry WSDA listing but NOT OMRI (the two programs
    have different review cadences and fee structures, so manufacturers often
    pick one). A compliance tool that checks only OMRI produces a high
    false-positive drift rate for CA/PNW growers.

    Source: https://agr.wa.gov/departments/organic/input-material-registration
    Public list: https://cms.agr.wa.gov/getmedia/6322228c-c949-44a2-926c-2a86739269e3/WSDA_Organic_Input_Material_List
    (Updated monthly; field `list_effective_date` tracks the edition this row
    was synced from.)

    This is a second global catalog alongside OMRIProduct. Drift detector
    Layer-2 name matching checks WSDA after OMRI so WSDA-only products clear
    when approved on the OSP.
    """

    wsda_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Product identifier from the WSDA Organic Input Material List",
    )
    brand_name = models.CharField(max_length=200, help_text="Brand / product name as listed by WSDA")
    manufacturer = models.CharField(max_length=200, blank=True, null=True)
    category = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="WSDA category (e.g., 'fertilizer', 'pesticide', 'inoculant')",
    )
    list_effective_date = models.DateField(
        blank=True,
        null=True,
        help_text="Edition date of the WSDA list this row was synced from",
    )
    # CA state-law requirement — see OMRIProduct above for rationale.
    is_cdfa_oim_registered = models.BooleanField(
        default=False,
        help_text="Whether this product carries a current CDFA OIM registration (CA only)",
    )
    cdfa_oim_reg_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="CDFA OIM registration number, e.g. '#1234-05'",
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="wsda_materials_added",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "WSDA Material"
        verbose_name_plural = "WSDA Materials"
        ordering = ["brand_name"]
        indexes = [
            models.Index(fields=["brand_name"]),
        ]

    def __str__(self):
        return f"{self.brand_name} ({self.wsda_id})"


# ---------------------------------------------------------------------------
# Sprint 5A — Organic System Plan (7 CFR 205.201) + Annual Update (205.406)
# + Landowner Affidavit (MOFGA FM-2024-20 canonical structure).
#
# Sources (verified):
#   - eCFR 7 CFR 205.201: https://www.ecfr.gov/current/title-7/subtitle-B/
#       chapter-I/subchapter-M/part-205/subpart-C/section-205.201
#   - Cornell LII 7 CFR 205.406:
#       https://www.law.cornell.edu/cfr/text/7/205.406
#   - AMS SOE (88 FR 3622, effective 2024-03-19):
#       https://www.ams.usda.gov/rules-regulations/strengthening-organic-enforcement
#   - MOFGA Landowner Affidavit FM-2024-20:
#       https://mofgacertification.org/wp-content/uploads/Crop_2024_LandownerAffidavit.pdf
# ---------------------------------------------------------------------------


# JSONB section keys mandated by § 205.201(a)(1)-(6). Frozen list — if a certifier
# wants extra sections (e.g., CCOF G-forms), store them under additional_certifier_info.
OSP_SECTION_KEYS = (
    "practices_procedures",  # (a)(1)
    "inputs_list",  # (a)(2)
    "monitoring_plan",  # (a)(3) — includes SOE fraud_prevention block
    "recordkeeping_description",  # (a)(4)
    "commingling_barriers",  # (a)(5)
    "additional_certifier_info",  # (a)(6)
)


def _empty_osp_sections():
    """Default factory for the `sections` JSONB — every required key present, empty narrative."""
    return {key: {"narrative": "", "last_updated": None} for key in OSP_SECTION_KEYS}


class OrganicSystemPlan(models.Model):
    """
    Organic System Plan (OSP) — 7 CFR 205.201.

    The OSP is the master regulatory document every certified organic operation must
    submit to its certifier. It describes practices, inputs, monitoring, recordkeeping,
    commingling prevention, and (post-SOE) fraud prevention.

    Versioned: each amendment creates a new row with a link to `previous_version`.
    § 205.406(a) requires an annual continuation which may or may not create a new
    version; a minor annual update without OSP changes is captured by OSPAnnualUpdate
    alone without superseding the active plan.

    The six required sections in § 205.201(a)(1)-(6) are stored as a single JSONB
    `sections` field rather than six related tables. This is deliberate:
      - the regulation treats them as narrative descriptions, not enumerated items
      - auditlog.register() captures per-field diffs of JSON content
      - the frontend editor is a form, not a spreadsheet
      - certifier-specific extensions go under `additional_certifier_info`
    """

    STATUS_CHOICES = [
        ("draft", "Draft (not yet submitted)"),
        ("submitted", "Submitted to certifier"),
        ("active", "Active / Approved"),
        ("superseded", "Superseded by newer version"),
        ("withdrawn", "Withdrawn"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="organic_system_plans",
        help_text="Establishment this OSP covers",
    )
    certification = models.ForeignKey(
        Certification,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="system_plans",
        help_text="The active Certification this OSP supports (if any)",
    )

    version_number = models.PositiveIntegerField(
        help_text="Monotonically increasing per establishment (v1, v2, v3...)",
    )
    previous_version = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="next_versions",
        help_text="Prior OSP version this one supersedes",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)

    effective_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date this OSP became active with the certifier",
    )
    submitted_at = models.DateTimeField(blank=True, null=True, help_text="When this OSP was submitted to the certifier")
    approved_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the certifier approved this OSP (sets status to active)",
    )

    # Six required sections per 7 CFR 205.201(a)(1)-(6). Shape documented by
    # OSP_SECTION_KEYS above. Default factory ensures every required key is present.
    sections = models.JSONField(
        default=_empty_osp_sections,
        help_text="Six required sections per 7 CFR 205.201(a)(1)-(6) as JSONB",
    )

    # Uploaded PDF of the certifier-signed OSP (if the farm submitted a PDF form).
    pdf_document = models.FileField(
        upload_to="osp/",
        blank=True,
        null=True,
        help_text="Uploaded OSP PDF (optional — source of truth is `sections` JSONB)",
    )

    # Snapshot PDF frozen at submit() time. Never mutated after creation — the
    # immutable artifact the farmer sends to the certifier. Satisfies the "what
    # exactly did you submit?" inspector question with a checksum-friendly file.
    submission_pdf = models.FileField(
        upload_to="osp/submissions/",
        blank=True,
        null=True,
        help_text=(
            "Immutable PDF snapshot auto-generated when OSP is submitted. "
            "This is the exact content the certifier received."
        ),
    )

    # Certifier-provided approval evidence required to move 'submitted' -> 'active'.
    # Without these, a farmer could self-flip status to active without any
    # certifier involvement (7 CFR 205.400 enforcement gap).
    approval_document = models.FileField(
        upload_to="osp/approvals/",
        blank=True,
        null=True,
        help_text=("Certifier's approval letter / signed OSP (PDF or scan) required " "to mark this OSP Active."),
    )
    approval_certificate_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Certificate number issued by certifier on approval (e.g., CCOF-2026-4287).",
    )
    approval_certifier_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Certifier organization that approved this OSP (e.g., CCOF).",
    )

    # Sprint 5.1 — Drift detector approved-inputs registry.
    # Structured list of inputs the certifier has approved for use on this OSP.
    # When a ChemicalEvent or SoilManagementEvent is saved with an input NOT in
    # these sets, post_save signals stamp a drift_warning on the event. The
    # audit export PDF then renders a "Drift Findings" section the inspector
    # can cross-reference against § 205.400(f)(2) change-notification.
    #
    # Two separate M2Ms (rather than a GenericForeignKey) so the admin, ORM
    # joins, and serializer all work naturally and match ChemicalEvent's own
    # FK structure to these same two tables.
    approved_national_list_substances = models.ManyToManyField(
        "certifications.NationalListSubstance",
        blank=True,
        related_name="approving_osps",
        help_text=("National List entries (7 CFR 205.601/602) the certifier has " "approved for use under this OSP."),
    )
    approved_omri_products = models.ManyToManyField(
        "certifications.OMRIProduct",
        blank=True,
        related_name="approving_osps",
        help_text="OMRI-listed products the certifier has approved under this OSP.",
    )
    approved_wsda_materials = models.ManyToManyField(
        "certifications.WSDAMaterial",
        blank=True,
        related_name="approving_osps",
        help_text=(
            "WSDA Brand Name Materials List entries the certifier has approved "
            "under this OSP. WSDA is treated co-equally with OMRI by CCOF and "
            "most US certifiers — many products carry WSDA but not OMRI listing."
        ),
    )

    # Certifier template provenance — e.g., "CCOF Grower OSP 2025", "Oregon Tilth Crop OSP"
    certifier_template_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Name/version of the certifier's OSP template this plan follows",
    )
    certifier_template_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="URL to the certifier's published OSP template for provenance",
    )

    notes = models.TextField(blank=True, null=True)

    # Tracking
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_osps",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organic System Plan"
        verbose_name_plural = "Organic System Plans"
        ordering = ["-effective_date", "-version_number"]
        indexes = [
            models.Index(fields=["establishment", "status"]),
            models.Index(fields=["establishment", "-version_number"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["establishment", "version_number"],
                name="unique_osp_version_per_establishment",
            ),
        ]

    def __str__(self):
        return f"OSP v{self.version_number} — {self.establishment.name} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status == "active"

    @property
    def section_completion(self):
        """
        Returns fraction of required sections with non-empty narratives. Used by the
        admin/editor UI and by the "compliance health" dashboard (Sprint 5B).
        """
        filled = sum(1 for key in OSP_SECTION_KEYS if (self.sections or {}).get(key, {}).get("narrative", "").strip())
        return filled / len(OSP_SECTION_KEYS)


class OSPAnnualUpdate(models.Model):
    """
    Annual continuation of certification — 7 CFR 205.406(a).

    Each calendar year, every certified operation must submit:
      (a)(1) summary of any deviations/changes/modifications to the prior OSP
      (a)(2) additions or deletions planned for the coming year
      (a)(3) additions/deletions to § 205.401(b) application info
      (a)(4) any other info the certifier requires

    Captured here as a diff against the `prior_osp` version. If the update produces a
    new OSP version, `new_osp` is set — otherwise it's a pure attestation of "no
    material changes" (common for mature operations).
    """

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    prior_osp = models.ForeignKey(
        OrganicSystemPlan,
        on_delete=models.PROTECT,
        related_name="annual_updates_filed",
        help_text="The OSP version this annual update references",
    )
    new_osp = models.ForeignKey(
        OrganicSystemPlan,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="annual_updates_created",
        help_text="New OSP version created by this update (if material changes were made)",
    )
    reporting_year = models.PositiveIntegerField(
        help_text="Calendar year this annual update covers (e.g., 2026)",
    )

    # § 205.406(a)(1)
    changes_summary = models.TextField(
        blank=True,
        default="",
        help_text="Narrative summary of deviations/changes/modifications since prior OSP",
    )
    # § 205.406(a)(2) — typed as JSONB lists of {section, field, old, new} dicts
    additions = models.JSONField(default=list, blank=True)
    deletions = models.JSONField(default=list, blank=True)

    # Per-section "unchanged" attestations. Keys are OSP_SECTION_KEYS; values are
    # bool (True = operator attests this section has not changed since prior_osp).
    sections_unchanged_attestation = models.JSONField(default=dict, blank=True)

    submitted_at = models.DateTimeField(
        blank=True, null=True, help_text="When the update was submitted to the certifier"
    )
    certifier_acknowledged_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the certifier confirmed receipt/acceptance",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_osp_annual_updates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "OSP Annual Update"
        verbose_name_plural = "OSP Annual Updates"
        ordering = ["-reporting_year", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["prior_osp", "reporting_year"],
                name="unique_annual_update_per_osp_year",
            ),
        ]

    def __str__(self):
        return f"Annual Update {self.reporting_year} — {self.prior_osp}"


class LandownerAffidavit(models.Model):
    """
    Prior landowner / manager affidavit — 3-year transition proof under 7 CFR 205.202(b).

    Verbatim attestation and structure follow MOFGA Certification Services
    FM-2024-20 (Crop_2024_LandownerAffidavit.pdf). MOFGA is chosen as the
    canonical template because it is the simplest superset; CCOF and Oregon Tilth
    integrate equivalent data into their Parcel Application forms, so this schema
    round-trips cleanly.

    One affidavit per parcel per applicable period. If the applicant farmed the
    parcel themselves for 3+ years, their own records + OSP attestation suffice —
    the affidavit is required only when someone else managed the land during the
    transition window.
    """

    # Exact wording from MOFGA FM-2024-20. DO NOT alter — regulators/certifiers
    # expect this specific attestation. Treat as a regulatory constant.
    ATTESTATION_TEXT = (
        "I verify that this field has not had any prohibited materials as "
        "defined by the USDA National Organic Program since the date provided above."
    )

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    parcel = models.ForeignKey(
        "product.Parcel",
        on_delete=models.CASCADE,
        related_name="landowner_affidavits",
        help_text="Parcel this affidavit covers",
    )
    osp = models.ForeignKey(
        OrganicSystemPlan,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="landowner_affidavits",
        help_text="OSP this affidavit was filed under (optional cross-link)",
    )

    # Operation identification (MOFGA fields 1-2)
    farm_name = models.CharField(max_length=200, blank=True, null=True)
    field_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Name of the field/parcel as referenced in the OSP",
    )
    field_acres = models.FloatField(blank=True, null=True)

    # Prior land manager/user (MOFGA field 3) — the signer of record
    previous_manager_name = models.CharField(max_length=200)
    previous_manager_address = models.CharField(max_length=300, blank=True, null=True)
    previous_manager_phone = models.CharField(max_length=30, blank=True, null=True)

    # Landowner if different from manager (MOFGA field 4)
    landowner_name = models.CharField(max_length=200, blank=True, null=True)
    landowner_address = models.CharField(max_length=300, blank=True, null=True)
    landowner_phone = models.CharField(max_length=30, blank=True, null=True)

    # 3-year history table (MOFGA field 5) — list of {year, land_use, inputs, applied_by}
    # dicts. We store 3 years by convention but allow more (some certifiers ask for 5).
    yearly_history = models.JSONField(
        default=list,
        blank=True,
        help_text=("List of {year, land_use, inputs, applied_by} dicts covering the " "3+ year transition window"),
    )

    # MOFGA field 6 — the critical date for § 205.202(b) 36-month calculation.
    last_prohibited_date = models.DateField(
        blank=True,
        null=True,
        help_text=(
            "Most recent date any prohibited substance was applied to this field. "
            "NULL means the signer attests none have ever been applied in living memory."
        ),
    )

    # MOFGA field 7 — the attestation. Stored verbatim so we can show the exact wording
    # the signer agreed to, even if ATTESTATION_TEXT is updated in the future.
    attestation_text = models.TextField(
        default="",
        help_text="Verbatim attestation wording the signer agreed to (see ATTESTATION_TEXT)",
    )

    # Signatures (MOFGA signature block)
    previous_manager_signed_date = models.DateField(blank=True, null=True)
    landowner_signed_date = models.DateField(
        blank=True, null=True, help_text="Only set if landowner is different from manager"
    )
    signed_document = models.FileField(
        upload_to="affidavits/",
        blank=True,
        null=True,
        help_text="Scanned copy of the signed affidavit",
    )

    notes = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_landowner_affidavits",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Landowner Affidavit"
        verbose_name_plural = "Landowner Affidavits"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["parcel", "-last_prohibited_date"]),
        ]

    def __str__(self):
        return f"Affidavit — {self.field_name or self.parcel_id} (signed {self.previous_manager_signed_date or '—'})"

    def save(self, *args, **kwargs):
        # Default attestation text to the canonical MOFGA wording if the caller
        # didn't supply one. Do not overwrite an explicitly set value — historical
        # affidavits may predate wording updates.
        if not self.attestation_text:
            self.attestation_text = self.ATTESTATION_TEXT
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Sprint 5.1 GA — Approved-inputs change log
# ---------------------------------------------------------------------------


class ApprovedInputChangeLog(models.Model):
    """
    Immutable audit record written every time an input is added to or removed
    from OrganicSystemPlan.approved_national_list_substances /
    approved_omri_products.

    Satisfies the inspector question "when did Copper hydroxide enter the
    approved list, and which certifier letter authorised it?" under
    7 CFR 205.400(f)(2) change-notification obligations (operation change).

    Write-only from the API perspective — rows are created exclusively by
    OrganicSystemPlanViewSet.add_approved_input / remove_approved_input.
    No update / delete endpoints are exposed; the log is append-only.
    """

    KIND_NATIONAL_LIST = "national_list"
    KIND_OMRI = "omri"
    KIND_WSDA = "wsda"
    KIND_CHOICES = [
        (KIND_NATIONAL_LIST, "National List substance (7 CFR 205.601–606)"),
        (KIND_OMRI, "OMRI-listed product (farmer-reported)"),
        (KIND_WSDA, "WSDA Brand Name Materials List (Washington State Dept of Ag)"),
    ]

    ACTION_ADDED = "added"
    ACTION_REMOVED = "removed"
    ACTION_CHOICES = [
        (ACTION_ADDED, "Added"),
        (ACTION_REMOVED, "Removed"),
    ]

    osp = models.ForeignKey(
        OrganicSystemPlan,
        on_delete=models.CASCADE,
        related_name="approved_input_changes",
        help_text="OSP this log entry belongs to",
    )
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        help_text="Whether this is a NationalList or OMRI entry",
    )
    # FK references preserved where the underlying object still exists; NULLed
    # via SET_NULL if the NL substance or OMRI product is later deleted. The
    # target_name_at_change snapshot below ensures the audit record is still
    # human-readable even after FK removal.
    target_national_list = models.ForeignKey(
        "certifications.NationalListSubstance",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="National List substance at time of change (nullable if later deleted)",
    )
    target_omri = models.ForeignKey(
        "certifications.OMRIProduct",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="OMRI product at time of change (nullable if later deleted)",
    )
    target_wsda = models.ForeignKey(
        "certifications.WSDAMaterial",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="WSDA material at time of change (nullable if later deleted)",
    )
    # Frozen snapshot — remains readable even if the FK target is deleted.
    target_name_at_change = models.CharField(
        max_length=255,
        help_text=(
            "Substance/product name frozen at the moment of the change. "
            "Preserved for audit continuity even if the FK is later NULLed."
        ),
    )
    action = models.CharField(
        max_length=10,
        choices=ACTION_CHOICES,
        help_text="Whether the input was added or removed",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        help_text="User who performed the change (NULLed if user is later deleted)",
    )
    changed_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Timestamp of the change (UTC)",
    )
    # Free-text reference to the certifier letter / change-notification document
    # that authorised or acknowledged this change. Inspectors use this to pull
    # the supporting paperwork for § 205.400(f)(2) compliance review.
    change_notification_reference = models.TextField(
        blank=True,
        help_text=(
            "Free-text citation of the certifier letter/email/change-notification. "
            "Ex: 'CCOF change-notification acknowledgment 2026-03-15, ref #CCOF-CN-4821.'"
        ),
    )
    notes = models.TextField(
        blank=True,
        help_text="Internal notes from the operator about this change",
    )

    class Meta:
        verbose_name = "Approved Input Change Log"
        verbose_name_plural = "Approved Input Change Logs"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.action} {self.target_name_at_change} on OSP v{self.osp.version_number}"


class OSPChangeNotification(models.Model):
    """
    Notification-of-Changes record — 7 CFR 205.400(f) / NOP 2615 §3.4.

    A certified operation must notify its certifier PRIOR to (or, for a
    prohibited-substance application, IMMEDIATELY after) any change that may
    affect its compliance. NOP 2615 §3.4 enumerates six change categories; the
    ApprovedInputChangeLog only captures ONE of them (input add/remove =
    § 205.400(f)(2)). This model captures the full set — including the
    § 205.400(f)(1) IMMEDIATE prohibited-substance-application notification that
    was previously unmodelled — so the audit export can show the complete
    change-notification trail, not just input changes.

    Append-only from the API perspective; edited only to record the certifier's
    acknowledgment.
    """

    # NOP 2615 §3.4 change categories. (f)(1) = immediate prohibited-substance
    # application/drift; the remaining categories are (f)(2) practice/operation
    # changes requiring prior notification.
    CATEGORY_PROHIBITED_SUBSTANCE = "prohibited_substance_application"
    CATEGORY_ACREAGE_FIELD_ADDITION = "acreage_field_addition"
    CATEGORY_FIELD_REMOVAL = "field_removal"
    CATEGORY_NEW_RETAIL_LABEL = "new_retail_label"
    CATEGORY_NEW_PROCESSING_HANDLING = "new_processing_handling"
    CATEGORY_PRACTICE_INPUT_PROCEDURE = "practice_input_procedure_change"
    CATEGORY_CHOICES = [
        (CATEGORY_PROHIBITED_SUBSTANCE, "Prohibited-substance application/drift — § 205.400(f)(1) (IMMEDIATE)"),
        (CATEGORY_ACREAGE_FIELD_ADDITION, "Added acreage / new field / product line / facility — § 205.400(f)(2)"),
        (CATEGORY_FIELD_REMOVAL, "Removed a field — § 205.400(f)(2)"),
        (CATEGORY_NEW_RETAIL_LABEL, "New retail label — § 205.400(f)(2)"),
        (CATEGORY_NEW_PROCESSING_HANDLING, "New processing / handling — § 205.400(f)(2)"),
        (CATEGORY_PRACTICE_INPUT_PROCEDURE, "Practice / input / procedure change — § 205.400(f)(2)"),
    ]

    METHOD_VERBAL = "verbal"
    METHOD_WRITTEN = "written"
    METHOD_CHOICES = [
        (METHOD_VERBAL, "Verbal"),
        (METHOD_WRITTEN, "Written"),
    ]

    DOC_AT_NOTIFICATION = "submitted_at_notification"
    DOC_DEFERRED_ANNUAL = "deferred_to_annual_update"
    DOCUMENTATION_TIMING_CHOICES = [
        (DOC_AT_NOTIFICATION, "Supporting documentation submitted at notification"),
        (DOC_DEFERRED_ANNUAL, "Deferred to the next annual update"),
    ]

    osp = models.ForeignKey(
        OrganicSystemPlan,
        on_delete=models.CASCADE,
        related_name="change_notifications",
        help_text="OSP this change notification belongs to",
    )
    change_category = models.CharField(
        max_length=40,
        choices=CATEGORY_CHOICES,
        db_index=True,
        help_text="NOP 2615 §3.4 change category (drives the § 205.400(f)(1) vs (f)(2) citation)",
    )
    description = models.TextField(
        help_text="What changed (e.g., 'Added 12-acre Block C to organic acreage').",
    )
    date_notified = models.DateField(
        null=True,
        blank=True,
        help_text="Date the certifier was notified.",
    )
    method = models.CharField(
        max_length=10,
        choices=METHOD_CHOICES,
        blank=True,
        null=True,
        help_text="How the certifier was notified (verbal or written).",
    )
    documentation_timing = models.CharField(
        max_length=30,
        choices=DOCUMENTATION_TIMING_CHOICES,
        blank=True,
        null=True,
        help_text="Whether supporting documentation was submitted now or deferred to the annual update.",
    )
    supporting_document = models.FileField(
        upload_to="osp_change_notifications/",
        blank=True,
        null=True,
        help_text="Supporting document / certifier acknowledgment letter, if any.",
    )
    certifier_acknowledged_at = models.DateField(
        null=True,
        blank=True,
        help_text="Date the certifier acknowledged the change (blank until acknowledged).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        help_text="User who recorded the notification (NULLed if user is later deleted).",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "OSP Change Notification"
        verbose_name_plural = "OSP Change Notifications"
        ordering = ["-date_notified", "-created_at"]

    @property
    def cfr_reference(self):
        """§ 205.400(f)(1) for prohibited-substance applications, else (f)(2)."""
        if self.change_category == self.CATEGORY_PROHIBITED_SUBSTANCE:
            return "7 CFR 205.400(f)(1)"
        return "7 CFR 205.400(f)(2)"

    @property
    def is_immediate(self):
        return self.change_category == self.CATEGORY_PROHIBITED_SUBSTANCE

    def __str__(self):
        return f"{self.get_change_category_display()} on OSP v{self.osp.version_number}"


# ---------------------------------------------------------------------------
# State Organic Program (SOP) producer registration
# ---------------------------------------------------------------------------


class StateOrganicRegistration(models.Model):
    """
    State Organic Program (SOP) PRODUCER registration.

    Distinct from the CDFA OIM (Organic Input Material) registration carried on
    OMRIProduct / WSDAMaterial — that is an INPUT-material registration. THIS is
    the producer/operation registration.

    California producers selling more than $5,000/yr of organic product must
    register annually with the CDFA State Organic Program BEFORE their first
    organic sale (CA Food & Ag Code §§ 46000-46029; 3 CCR 1380-1394), declaring
    commodities, operation type, and prior-year organic gross sales, and renew
    each year. A NOP "$5,000-exempt" producer is still subject to CA state
    registration. This is a hard inspection item Trazo previously could not
    record at all.

    Modeled generically (``state`` field) so other state programs reuse it;
    California (CDFA) is the only one enforced today.

    Scope note — CDFA vs CDPH: this registration is the CDFA producer/raw-ag
    *handler* registration. On-farm operations that turn a crop into a PROCESSED
    organic product (roasting, grinding to butter/flour, oil pressing, blanching,
    adding ingredients) cross into CDPH's "processed product" domain and require a
    SEPARATE CDPH registration — Trazo's "handler" type here means CDFA raw-ag
    handling (hull/shell/wash/sort/pack), not CDPH processing.
    """

    OPERATION_TYPE_CHOICES = [
        ("producer", "Producer / Grower"),
        # "handler" = CDFA raw-ag handling (hull/shell/wash/sort/pack). A processed
        # organic product (roast/grind/press/blanch) needs a separate CDPH registration.
        ("handler", "Handler (CDFA raw-ag handling)"),
        ("producer_handler", "Producer & Handler"),
        ("retailer", "Retailer"),
    ]
    STATUS_CHOICES = [
        ("registered", "Registered"),
        ("pending", "Pending"),
        ("expired", "Expired"),
        ("exempt", "Exempt (< $5,000 organic sales)"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)

    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="state_organic_registrations",
        help_text="Establishment this state registration belongs to",
    )

    state = models.CharField(
        max_length=2,
        default="CA",
        help_text="US state two-letter code of the State Organic Program (CA = CDFA SOP)",
    )
    program_name = models.CharField(
        max_length=120,
        default="CDFA State Organic Program",
        help_text="State Organic Program name (e.g. 'CDFA State Organic Program')",
    )
    operation_type = models.CharField(
        max_length=20,
        choices=OPERATION_TYPE_CHOICES,
        default="producer",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="registered",
    )

    registration_number = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="State / county registration number",
    )
    county = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="CA county of registration (CDFA SOP registers by county)",
    )

    commodities = models.JSONField(
        default=list,
        blank=True,
        help_text="Organic commodities declared on the registration, e.g. ['Navel orange', 'Lemon']",
    )
    prior_year_organic_gross_sales = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Prior-year organic gross sales (USD) — sets the CDFA fee tier and the >$5,000 trigger",
    )

    registration_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date this registration took effect",
    )
    renewal_date = models.DateField(
        blank=True,
        null=True,
        help_text="Date the registration must be renewed (annual)",
    )

    registration_document = models.FileField(
        upload_to="state_organic_registrations/",
        blank=True,
        null=True,
        help_text="Scanned copy of the state registration certificate",
    )
    notes = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_state_organic_registrations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "State Organic Registration"
        verbose_name_plural = "State Organic Registrations"
        ordering = ["-registration_date"]
        indexes = [
            models.Index(fields=["establishment", "state"]),
        ]

    def __str__(self):
        return f"{self.program_name} — {self.establishment.name} ({self.registration_number or 'unregistered'})"

    @property
    def is_current(self):
        """True if the operation is covered today: an exempt operation, or a
        'registered' record whose renewal_date has not passed. Used by the audit
        export to decide whether to fire the missing/expired-registration REVIEW
        flag, and by any first-organic-sale gate."""
        if self.status == "exempt":
            return True
        if self.status != "registered":
            return False
        if self.renewal_date is None:
            return True
        return self.renewal_date >= timezone.now().date()
