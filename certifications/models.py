import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from backend.storage import private_records_storage

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

    # The only source that substantiates the consumer-facing "Verified via USDA Organic
    # Integrity Database" claim. Stamped by VerificationManager.verify_certification from
    # USDAOrganicVerifier.source_identifier; test_consumer_display_status_substantiation pins
    # the two to the same string, since a drift there silently downgrades every real badge.
    DATABASE_VERIFICATION_SOURCE = "usda_organic_integrity_db"

    @property
    def consumer_display_status(self):
        """FTC-compliant status for consumer display.

        `verified_via_database` renders as the literal claim "Verified via USDA Organic
        Integrity Database" on the public QR page. That claim was previously derived from
        `verification_status == "verified"` alone, with no reference to where the
        verification actually came from — so a row marked verified by a manual admin edit, a
        data import, or a fixture asserted a database match that never happened. Gate the
        claim on the source that substantiates it (16 CFR 260.6); anything else falls back to
        the honest `self_reported` label rather than silently upgrading a farmer attestation
        into a third-party verification.
        """
        if self.verification_status == "verified":
            if self.verification_source == self.DATABASE_VERIFICATION_SOURCE:
                return "verified_via_database"
            return "self_reported"
        elif self.verification_status in ("self_reported", "possible_match", "listing_match"):
            # Run 8: a possible database entry is not a confirmed one, and a material listing
            # never verifies a farm. Both read exactly as the farm's own report.
            return "self_reported"
        elif self.verification_status in ("expired", "revoked", "suspended"):
            return "inactive"
        return "pending"


class PostHarvestFacility(models.Model):
    """
    An off-farm post-harvest handler (huller, sheller, dryer, cold storage,
    packer) that a production's crop is sent to. Under CCOF G6.1 (ORGB39) and
    NOP 7 CFR 205.272, when an organic crop is handled by another certified
    operation the audit trail must carry that handler's name + current organic
    certificate (issued within 15 months). Mirrors the Certification model's
    verification fields so the same USDA-OID verifier can validate the handler.
    """

    FACILITY_TYPE_CHOICES = [
        ("huller", "Huller / Sheller"),
        ("dryer", "Dryer"),
        ("cold_storage", "Cold Storage"),
        ("dry_storage", "Dry Storage / Warehouse"),
        ("packer", "Packer / Packing Shed"),
        ("custom", "Custom Post-Harvest Handler"),
    ]

    # Who runs the facility. OTCO C7 7.1 and CCOF G6.4 A1 ask the name and address of the operation's
    # OWN handling or storage site, and OTCO 7.7-2 lists every storage facility with its documentation
    # class (OC = another operation's organic certificate, IS = an uncertified facility's statement,
    # OWN = the operation's own). Until 2026-11-07 this table held only facilities the crop is sent TO,
    # so a farm's own shed or cooler had no row. An own facility is covered by the operation's own
    # certificate: it has no certificate of its own to look up, date or attach, and every certificate
    # check skips it (`needs_own_certificate`).
    OPERATED_BY_CHOICES = [
        ("another_operation", "Another operation"),
        ("this_operation", "This operation (our own facility)"),
    ]

    # What the facility DOES for this operation, which is a different axis from what it IS.
    # CCOF asks about handling on G6.1 §C and about storage on G6.2 §A — two forms, two
    # questions — and WSDA splits them again across sections K and L. A cold store can be
    # either: it holds the crop (storage) or it also packs and ships it (handling). Without
    # this axis the same row answers both questions or neither, which is how the storage
    # table and the handler table read as two defects for a while when they are one.
    # Blank is the default and it is load-bearing: a row created before this field existed has
    # never been asked, and defaulting it to "handling" would print "Handles the crop (packs,
    # hulls, dries, conditions)" in the plan for a cold store nobody described that way. Unset
    # prints as unset, exactly like `cert_is_current`'s None.
    ROLE_CHOICES = [
        ("handling", "Handles the crop (packs, hulls, dries, conditions)"),
        ("storage", "Stores the crop only"),
        ("both", "Stores and handles the crop"),
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
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        blank=True,
        default="",
        help_text="Whether this facility handles the crop, only stores it, or both",
    )
    operated_by = models.CharField(
        max_length=20,
        choices=OPERATED_BY_CHOICES,
        default="another_operation",
        help_text="Whether another operation runs this facility, or it is the operation's own",
    )
    address = models.CharField(max_length=200, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)
    # OTCO C7 7.1 asks the zip or postal code and the country of an on-farm facility.
    postal_code = models.CharField(max_length=20, blank=True, default="")
    country = models.CharField(max_length=60, blank=True, default="")
    # OTCO C7 7.2-1: "Attach a facility layout, either hand drawn or digital, that shows the areas used for
    # organic processing and storage", per on-farm facility.
    layout_document = models.FileField(
        upload_to="facility_layouts/",
        storage=private_records_storage,
        blank=True,
        null=True,
        help_text="Layout of an own facility showing the areas used for organic handling and storage",
    )

    # Handler's organic certificate (G6.1: must be current, issued within 15 months)
    certification_number = models.CharField(max_length=100, blank=True, null=True)
    certifier_name = models.CharField(max_length=200, blank=True, null=True)
    effective_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    cert_document = models.FileField(
        upload_to="facility_certs/",
        storage=private_records_storage,
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
    # CCOF G6.1 C2 and OTCO C7 7.10-2 ask the finished products and their packaging form per handler; the
    # crops themselves are read from the production records linked to the facility
    # (`facility_crops`). This holds what the records cannot say: detail and packaging form.
    products_detail = models.TextField(
        blank=True,
        default="",
        help_text="Products it handles or stores for you, with detail and packaging form, one per line",
    )
    # WSDA AGR 2519 ("Additional Facilities and Third-Parties"), filed for each such facility when the
    # crop OSP's §J 13, §K 1 or §L 1 is Yes: which of the form's activities happen there
    # (`certifications.facility_activities`), as the operator states them. Never inferred from the
    # facility's type or role.
    activities = models.JSONField(
        blank=True,
        default=list,
        help_text="The activities that happen at this facility, in WSDA AGR 2519's terms",
    )
    # AGR 2519's third responsibility statement: a third party that is not certified "but is responsible
    # for the activities described", with "Briefly explain how the third-party is exempt from
    # certification" (§ 205.101). Asked of another operation's facility only.
    exemption_basis = models.TextField(
        blank=True,
        default="",
        help_text="How an uncertified third party is exempt from certification (§ 205.101)",
    )

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
    def is_own(self) -> bool:
        return self.operated_by == "this_operation"

    @property
    def certificate_on_record(self) -> bool:
        """Whether the record names an organic certificate for this facility: a certificate number or a
        certifier. The one definition the module PDF's handler table and the AGR 2519 copy sheet both read,
        so one packet cannot call a facility certified on one page and uncertified on another (review of
        back #349). Whitespace is not a value."""
        return bool((self.certification_number or "").strip() or (self.certifier_name or "").strip())

    @property
    def needs_own_certificate(self) -> bool:
        """False for the operation's own facility: its own certificate covers it."""
        return not self.is_own

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

        if self.is_own:
            # The operation's own facility is not a separate certified operation; looking its name up in
            # the OID would compare a shed's name against the register of certified businesses.
            return None
        result = USDAOrganicVerifier().verify(
            self.name, self.state or "", self.certification_number, certifier_name=self.certifier_name
        )
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


class FacilityProduct(models.Model):
    """One finished product a facility handles, processes or stores for this operation, as a row of the
    agents' product tables.

    CCOF G6.1 C2 asks, per product: Product Category / Product Detail (if any) / Packaging Form (retail,
    nonretail, unpackaged) / Certified Operation where Product is Handled or Processed, and for each
    multi-ingredient product the manufacturer's ingredient statement (not required if the co-packer is
    CCOF certified). OTCO C7 7.10-2 asks: Type of Product / Product Detail (optional) / Organic Label Claim
    (100% Organic, Organic, Made With Organic) / Label or Brand Name / Name of operation doing the
    processing / Certifier. The facility row carries the operation and its certifier; this row carries the
    rest.

    Every column is what the operator typed or picked. Blank is "not stated" and prints as such: the label
    claim is never defaulted from G7.0's label categories, because a default would print a claim nobody
    made for this product. `PostHarvestFacility.products_detail` stays, as the operator's free text.
    """

    PACKAGING_FORM_CHOICES = [
        ("retail", "Retail"),
        ("nonretail", "Nonretail"),
        ("unpackaged", "Unpackaged"),
    ]
    # § 205.301(a)-(c), in OTCO's words and order.
    LABEL_CLAIM_CHOICES = [
        ("100_percent_organic", "100% Organic"),
        ("organic", "Organic"),
        ("made_with_organic", "Made With Organic"),
    ]
    MULTI_INGREDIENT_CHOICES = [
        ("yes", "Multi-ingredient"),
        ("no", "Single ingredient"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    facility = models.ForeignKey(PostHarvestFacility, on_delete=models.CASCADE, related_name="products")
    category = models.CharField(max_length=120, help_text="Product category or type, e.g. Almonds")
    detail = models.CharField(max_length=200, blank=True, default="", help_text="Product detail, e.g. Shelled")
    packaging_form = models.CharField(max_length=20, choices=PACKAGING_FORM_CHOICES, blank=True, default="")
    label_claim = models.CharField(max_length=30, choices=LABEL_CLAIM_CHOICES, blank=True, default="")
    brand_name = models.CharField(max_length=200, blank=True, default="", help_text="Label or brand name, if any")
    multi_ingredient = models.CharField(max_length=5, choices=MULTI_INGREDIENT_CHOICES, blank=True, default="")
    # The manufacturer's ingredient statement CCOF G6.1 C2 asks for a multi-ingredient product. A file in the
    # farm's Documents; PROTECT, like a brand owner's certificate: the documents route refuses to delete it.
    ingredient_statement_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="facility_ingredient_statements",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_facility_products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["facility_id", "pk"]

    def __str__(self):
        return f"{self.category} at {self.facility.name}"


def normalize_supplier_name(name) -> str:
    """The one spelling rule a record's supplier text is compared with: trim, casefold, single
    spaces. Nothing looser. "Gurney's" and "Gurneys" stay two spellings until the grower says
    they are one supplier; a closer match is the fuzzy class Trazo never uses for a claim."""
    return " ".join(str(name or "").split()).casefold()


class Supplier(models.Model):
    """A seed or planting-stock supplier this farm buys from, and its organic certificates.

    Every supplier used to be a string on a record (`ProductionEvent.seed_supplier_name`), and
    `histories/seed-suppliers/` derived the list from those strings on purpose: a derived list
    cannot carry what the records do not have. The organic certificate is exactly that. CCOF
    G3.0, OTCO C3 and WSDA 2121-B ask for the certificate of each supplier of certified organic
    seedlings or planting stock, and 205.201(a)(3) (SOE) asks how the operation verifies its
    suppliers' organic status. Until this register Trazo printed the grower's "certified organic"
    claim with nothing behind it.

    Records are NOT linked by a foreign key. A season's records lock when it is finished and a
    correction cannot target a foreign key (`history/amendments.py`), so last season's plantings,
    the ones a renewal packet prints, could never be linked. A record resolves to a supplier when
    its text equals one of the supplier's confirmed spellings (`SupplierName`), exactly. Reading
    that never touches the record.

    Organic status here is the grower's record. Nothing on this model is checked against the
    Organic Integrity Database yet; `nop_operation_id` is kept so that check can be by ID, never
    by name.
    """

    ORGANIC_STATUS_CHOICES = [
        ("certified", "Certified organic operation"),
        ("not_certified", "Not a certified organic operation"),
        ("unknown", "Not stated"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="suppliers",
        help_text="Farm that buys from this supplier",
    )
    name = models.CharField(max_length=200)
    organic_status = models.CharField(max_length=20, choices=ORGANIC_STATUS_CHOICES, default="unknown")
    # The NOP operation ID printed on a certificate generated from the Organic Integrity Database.
    # Stored as the grower typed it; not looked up.
    nop_operation_id = models.CharField(max_length=40, blank=True, default="")
    certifier_name = models.CharField(max_length=200, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    # CCOF G6.5 A1/A2, OTCO C12 12.2-4 (2026.11.08): organic crops or products the operation buys
    # from this supplier for its own sales, one per line (category and detail). Non-empty makes the
    # supplier a sourcing supplier on the plan's G6.5.
    sourced_products = models.TextField(
        blank=True,
        default="",
        help_text="Organic crops or products bought from this supplier for resale or co-marketing, one per line",
    )
    # For an uncertified supplier (a broker or distributor): the certified operation it sources from,
    # and the Exempt Handler Affidavit it completed (CCOF G6.5 A1).
    source_operation = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="If this supplier is not certified, the certified operation it sources from",
    )
    exempt_handler_affidavit = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supplier_affidavits",
    )
    # Archived, never deleted, once a record resolves to it: a finished season keeps its supplier.
    archived_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_suppliers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        indexes = [models.Index(fields=["establishment", "archived_at"])]

    def __str__(self):
        return self.name


class SupplierName(models.Model):
    """One spelling of a supplier as this farm's records write it, confirmed by the grower.

    Unique per farm on the normalised spelling: one spelling names at most one supplier.
    """

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="names")
    # Denormalised from the supplier so the uniqueness below is a database constraint.
    establishment = models.ForeignKey("company.Establishment", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=200)
    normalized = models.CharField(max_length=200, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["normalized", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["establishment", "normalized"], name="supplier_spelling_unique_per_farm")
        ]

    def save(self, *args, **kwargs):
        self.establishment_id = self.supplier.establishment_id
        self.normalized = normalize_supplier_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class SupplierCertificate(models.Model):
    """One copy of a supplier's organic certificate. Append-only by design: next year's copy is a
    new row, so a purchase keeps being judged against the copy that covered it.

    `issued_on` is the date the 15-month freshness runs from. A NOP certificate's "effective date"
    is usually the operation's FIRST certification, years back; judging freshness on it would call
    most valid certificates stale.
    """

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="certificates")
    # The copy itself, filed in the farm's Documents. PROTECT: the documents route refuses to
    # delete a file a certificate still names.
    document = models.ForeignKey(
        "documents.GeneratedDocument", on_delete=models.PROTECT, related_name="supplier_certificates"
    )
    issued_on = models.DateField(help_text="Issue date printed on the certificate")
    anniversary_date = models.DateField(null=True, blank=True)
    original_effective_date = models.DateField(
        null=True, blank=True, help_text="First certification date, as printed; not used for freshness"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_supplier_certificates",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-issued_on", "-pk"]

    def __str__(self):
        return f"{self.supplier} certificate issued {self.issued_on}"


class OperationContact(models.Model):
    """A person the operation names to its certifying agent, with the roles that person holds.

    OTCO O1 §B asks the Legally Responsible Contact, the Primary Contact, the Billing Contact, the Additional
    Contacts authorized to act on the operation's behalf ("Oregon Tilth will not conduct business with any
    individual whose name does not appear on this list") and every person Responsibly Connected (7 CFR 205.2:
    a partner, officer, director, holder, manager, or owner of 10 percent or more of the voting stock), each with
    name, title, phone and email. CCOF's Certification Contract asks the owners or officers with their titles
    (A4), the Primary Contact (C1) and the Additional Contacts (C2). One person may hold several roles, so the
    roles are flags on one row, never one row per role.
    """

    CONNECTION_CHOICES = [
        ("partner", "Partner"),
        ("officer", "Officer"),
        ("director", "Director"),
        ("holder", "Holder"),
        ("manager", "Manager"),
        ("owner_10_percent", "Owner of 10 percent or more of the voting stock"),
        ("other", "Other"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="operation_contacts",
        help_text="The operation this person is named for",
    )
    name = models.CharField(max_length=200)
    title = models.CharField(max_length=120, blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    is_legally_responsible = models.BooleanField(
        default=False, help_text="CEO, COO, executive or managing director, or registered agent (OTCO O1 B-2)"
    )
    is_primary_contact = models.BooleanField(
        default=False, help_text="The certifier's primary contact (O1 B-3, CCOF C1)"
    )
    is_billing_contact = models.BooleanField(default=False, help_text="Contact for payment questions (O1 B-4)")
    is_authorized_representative = models.BooleanField(
        default=False,
        help_text="Authorized to take part in inspections, meet inspectors, modify the OSP or act for the operation "
        "(O1 B-5, CCOF C2)",
    )
    is_responsibly_connected = models.BooleanField(
        default=False, help_text="7 CFR 205.2 responsibly connected (O1 B-6)"
    )
    connection = models.CharField(max_length=20, choices=CONNECTION_CHOICES, blank=True, default="")
    connection_other = models.CharField(max_length=200, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_operation_contacts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["establishment_id", "pk"]

    def __str__(self):
        return f"{self.name} ({self.establishment_id})"

    def role_labels(self) -> list:
        """The roles this person holds, in the order the forms list them."""
        out = []
        for flag, label in (
            ("is_legally_responsible", "Legally responsible"),
            ("is_primary_contact", "Primary contact"),
            ("is_billing_contact", "Billing contact"),
            ("is_authorized_representative", "Authorized to act for the operation"),
            ("is_responsibly_connected", "Responsibly connected"),
        ):
            if getattr(self, flag):
                out.append(label)
        return out


class BrandOwner(models.Model):
    """A company whose brand or label this farm packs its own organic crop into.

    CCOF G7.0 C1/C2, OTCO C8 8.3-2 to 8.3-4 and WSDA 2121 N 6 and 7 ask who each brand owner is,
    whether it is certified, and for its certificate (or, when it is not certified, the agent's
    private-label agreement: CCOF's Co-Packer Application, OTCO's Private Label Agreement). Until
    2026-11 the plan held one checkbox option, "Sold under the buyer's own label", with nothing
    behind it.

    The certificate and the agreement are the operation's own copies, filed in the farm's
    Documents. Nothing here is checked against the Organic Integrity Database; `nop_operation_id`
    is kept as typed so a later check can be by ID, never by name.
    """

    CERTIFICATION_STATUS_CHOICES = [
        ("certified", "Certified organic operation"),
        ("not_certified", "Not a certified organic operation"),
        ("unknown", "Not stated"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="brand_owners",
        help_text="Farm that packs into this company's brand",
    )
    name = models.CharField(max_length=200, help_text="The brand owner's legal name")
    brand_names = models.TextField(blank=True, default="", help_text="The brands this farm packs into")
    # OTCO C8 8.3-4 asks product by product, with each label's organic claim. Free text, one per line.
    products = models.TextField(
        blank=True, default="", help_text="Each product packed under this brand, with its label's organic claim"
    )
    certification_status = models.CharField(max_length=20, choices=CERTIFICATION_STATUS_CHOICES, default="unknown")
    certifier_name = models.CharField(max_length=200, blank=True, default="")
    nop_operation_id = models.CharField(max_length=40, blank=True, default="")
    # PROTECT, like a supplier certificate: the documents route refuses to delete a file named here.
    certificate_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="brand_owner_certificates",
    )
    certificate_issued_on = models.DateField(null=True, blank=True, help_text="Issue date printed on the certificate")
    # The agent's agreement for an uncertified brand owner (CCOF ORGB26 Co-Packer Application, OTCO PLA).
    agreement_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="brand_owner_agreements",
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_brand_owners",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name


class CertifierInspection(models.Model):
    """One on-site inspection of this farm by its certifying agent, as the operation recorded it.

    The agent keeps its own copy of every report and hands it to the next inspector
    (§ 205.501(a)(18)); this row is the OPERATION's copy, so it can answer "date of your last organic
    inspection" (WSDA AGR 2262 5a(i)) and send a past notice with any application to another agent
    (§ 205.401(c)). The report itself is a file in the farm's Documents; it often arrives weeks after
    the visit, so it is optional.

    Nothing here is a Trazo judgement of the inspection: every field is what the operator typed or
    filed.
    """

    KIND_CHOICES = [
        ("annual", "Annual inspection"),
        ("additional", "Additional inspection"),
        ("unannounced", "Unannounced inspection"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey(
        "company.Establishment", on_delete=models.CASCADE, related_name="certifier_inspections"
    )
    inspected_on = models.DateField(help_text="Date of the on-site inspection")
    # The Organic Integrity Database name `CertifyingAgentPicker` stores (or free text under
    # "Other"). NOT the slug `Establishment.certifier_renewal_date_agent` holds.
    certifying_agent = models.CharField(max_length=200, blank=True, default="")
    inspector_name = models.CharField(max_length=200, blank=True, default="")
    # § 205.403(a)(1) annual, (a)(2) additional, announced or not. Blank: not stated.
    inspection_kind = models.CharField(max_length=20, choices=KIND_CHOICES, blank=True, default="")
    # PROTECT, like a supplier certificate: the documents route refuses to delete a file named here.
    report_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inspection_reports",
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_certifier_inspections",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-inspected_on", "-pk"]

    def __str__(self):
        return f"{self.certifying_agent or 'Inspection'} {self.inspected_on}"


class CertifierNotice(models.Model):
    """One item the certifying agent sent the operation, with the operation's answer to it.

    `notice_of_noncompliance` is the § 205.662(a) notice: a description, the facts, and "the date by
    which the certified operation must rebut or correct each noncompliance and submit supporting
    documentation" ((a)(3)). (b) is the agent's written resolution. Anything else the agent sends
    ("issue of concern", "item for next inspection") is `other_item`, under the agent's OWN words in
    `agent_label`: the post-SOE rule has no minor-noncompliance or condition category for a certified
    operation, so Trazo names none.

    Whether an item is resolved is never stored: `services.certifier_notices.notice_status` derives
    it, and only an attached resolution notice reads as resolved.
    """

    KIND_CHOICES = [
        ("notice_of_noncompliance", "Notice of noncompliance (§ 205.662(a))"),
        ("other_item", "Other item from the certifying agent"),
    ]
    # The two answers § 205.662(a)(3) allows: rebut or correct.
    RESPONSE_KIND_CHOICES = [
        ("corrected", "Corrected"),
        ("rebutted", "Rebutted"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey(
        "company.Establishment", on_delete=models.CASCADE, related_name="certifier_notices"
    )
    # A notice can follow a review or an investigation, not only an inspection (§ 205.662(a)).
    # PROTECT: an inspection with notices under it is not deleted out from under them.
    inspection = models.ForeignKey(
        CertifierInspection, on_delete=models.PROTECT, null=True, blank=True, related_name="notices"
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    agent_label = models.CharField(max_length=120, blank=True, default="")
    received_on = models.DateField(null=True, blank=True, help_text="Date on the agent's letter")
    description = models.TextField(help_text="The item as the agent wrote it")
    notice_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="certifier_notice_letters",
    )
    respond_by = models.DateField(null=True, blank=True, help_text="§ 205.662(a)(3) rebut-or-correct date")
    response_kind = models.CharField(max_length=20, choices=RESPONSE_KIND_CHOICES, blank=True, default="")
    response_text = models.TextField(blank=True, default="")
    response_sent_on = models.DateField(null=True, blank=True)
    response_documents = models.ManyToManyField(
        "documents.GeneratedDocument",
        through="CertifierNoticeResponseDocument",
        blank=True,
        related_name="certifier_notices_supported",
    )
    # § 205.662(b): the agent's written notification of noncompliance resolution.
    resolution_received_on = models.DateField(null=True, blank=True)
    resolution_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="certifier_notice_resolutions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_certifier_notices",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Newest first, undated last: Postgres puts NULLs FIRST on a DESC sort (review of back #351).
        ordering = [models.F("received_on").desc(nulls_last=True), "-pk"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.received_on or ''}".strip()

    def replace_response_documents(self, documents):
        """Set the response's documents in the order given. `.set()` would lose the order.

        Atomic, and a file named twice is linked once: without both, `[5, 5]` deleted every link and
        then failed on the unique constraint, leaving the response with none (review of back #351).
        """
        with transaction.atomic():
            CertifierNoticeResponseDocument.objects.filter(notice=self).delete()
            for document in dict.fromkeys(documents):
                CertifierNoticeResponseDocument.objects.create(notice=self, document=document)


class CertifierNoticeResponseDocument(models.Model):
    """One document the operation sent with its response to a notice (§ 205.662(a)(3) "supporting
    documentation"). RESTRICT on the document, like an annual update's supporting file: the documents
    route refuses the delete first, by code."""

    notice = models.ForeignKey(CertifierNotice, on_delete=models.CASCADE, related_name="response_links")
    document = models.ForeignKey(
        "documents.GeneratedDocument", on_delete=models.RESTRICT, related_name="certifier_notice_response_links"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["notice", "document"], name="unique_certifier_notice_response_doc"),
        ]

    def __str__(self):
        return f"{self.notice_id} supported by document {self.document_id}"


class ProductionEquipment(models.Model):
    """A piece of farm equipment that contacts organic crops, seeds, transplants or inputs.

    CCOF G6.0 C2 and G6.1 B1, OTCO C9 9.1-1 and WSDA AGR 2121 I 1-2b ask for the same table: each
    item, whether it is dedicated to organic production, whether it is owned, rented, borrowed or
    custom hired, how it is cleaned before organic use and with what, and whether it is rinsed.
    Until 2026-11 Trazo held these facts only per Equipment-Maintenance event, so no plan could
    print the table.

    Unknown is not no: `dedicated_organic` and `rinsed` are null until the operation says.
    """

    USE_CHOICES = [
        ("planting", "Planting or seeding"),
        ("input_application", "Input material application (sprayers, spreaders)"),
        ("harvest", "Harvest"),
        ("washing_packing", "In-field washing or packing"),
        ("transport", "Transport"),
        ("other", "Other"),
    ]
    OWNERSHIP_CHOICES = [
        ("own", "Owned"),
        ("rent", "Rented"),
        ("borrow", "Borrowed"),
        ("custom_hire", "Custom hire"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="production_equipment",
    )
    name = models.CharField(max_length=200, help_text="What the item is, as the crew calls it")
    use = models.CharField(max_length=20, choices=USE_CHOICES)
    dedicated_organic = models.BooleanField(
        null=True, blank=True, help_text="Used only for certified organic production; null until stated"
    )
    ownership = models.CharField(max_length=20, choices=OWNERSHIP_CHOICES, blank=True, default="")
    cleaning_method = models.TextField(
        blank=True, default="", help_text="How it is cleaned or purged before organic use"
    )
    cleaning_materials = models.TextField(blank=True, default="", help_text="Materials used to clean or purge it")
    rinsed = models.BooleanField(null=True, blank=True, help_text="Rinsed before organic use; null until stated")
    rinse_detail = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_production_equipment",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]

    def __str__(self):
        return self.name


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

    #: Not a National List section. A NONSYNTHETIC substance is allowed in organic crop production
    #: without any listing — § 205.105(b) prohibits only the nonsynthetics § 205.602 names — so a
    #: row for one (spinosad, Bt, d-limonene) records Trazo's classification and cites nothing.
    #: Until 2026-09-10 those three were filed at § 205.601(e), which lists SYNTHETICS, and every
    #: surface that printed the section told a certifier the product was a listed synthetic.
    NONSYNTHETIC = "nonsyn"

    CFR_SECTION_CHOICES = [
        ("205.105", "§205.105 — Excluded substances & methods (prohibited)"),
        ("205.601", "§205.601 — Synthetic allowed (crops)"),
        ("205.602", "§205.602 — Nonsynthetic prohibited (crops)"),
        ("205.603", "§205.603 — Synthetic allowed (livestock)"),
        ("205.605", "§205.605 — Nonagricultural allowed (handling)"),
        ("205.606", "§205.606 — Nonorganic agricultural allowed (handling)"),
        (NONSYNTHETIC, "Nonsynthetic — allowed without a National List entry"),
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
    # 🔴 2026-08-20 — annotations on a National List entry come in two kinds that read
    # identically as prose but mean opposite things, and NOTHING may distinguish them by
    # sniffing the text:
    #
    #   condition_of_use — the CFR permits the substance FOR THE STATED USE.
    #       § 205.602(c) calcium chloride: "prohibited ... except as a foliar spray to treat a
    #       physiological disorder associated with calcium uptake."
    #   rationale        — the note explains WHY the substance is listed and grants nothing.
    #       § 205.105 glyphosate: "Synthetic herbicide; not on § 205.601 (NOP 5034-2)."
    #
    # Both rows are status="prohibited" and both have restriction_notes. A first pass at the
    # certifier packet used `if restriction_notes:` as the test for "conditionally permitted",
    # which would have printed GLYPHOSATE as "Restricted use" and filed it under [REVIEW]
    # instead of [WARNING]. Type the distinction; never re-derive it from the prose.
    ANNOTATION_NONE = "none"
    ANNOTATION_CONDITION = "condition_of_use"
    ANNOTATION_RATIONALE = "rationale"
    ANNOTATION_KIND_CHOICES = [
        (ANNOTATION_NONE, "No annotation"),
        (ANNOTATION_CONDITION, "Condition of use — the CFR permits the stated use"),
        (ANNOTATION_RATIONALE, "Rationale — explains the listing, grants no allowance"),
    ]
    annotation_kind = models.CharField(
        max_length=20,
        choices=ANNOTATION_KIND_CHOICES,
        default=ANNOTATION_NONE,
        db_index=True,
        help_text=(
            "What the restriction_notes text DOES. Only 'condition_of_use' may soften a "
            "prohibited listing; 'rationale' never does."
        ),
    )

    @property
    def is_conditionally_permitted(self) -> bool:
        """A prohibited listing the CFR permits for one stated use.

        The single test every surface must use before softening a "prohibited" verdict.
        Whether the operation's ACTUAL use meets the condition is not knowable here — the
        recorded purpose is farmer-written free text — so callers must present the condition
        and the recorded purpose side by side, never assert that the two match.
        """
        return self.status == "prohibited" and self.annotation_kind == self.ANNOTATION_CONDITION

    @property
    def is_refused_on_a_plan(self) -> bool:
        """Prohibited with no use the rule allows: no organic system plan may carry it.

        The one test both write paths share (`add_approved_input`, `PlanMaterialEntrySerializer`).
        A conditionally permitted row ((c) calcium chloride, (e) potassium chloride, (h) sodium
        nitrate) is accepted, and the plan prints its condition beside it."""
        return (self.status or "").lower() == "prohibited" and not self.is_conditionally_permitted

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

    @property
    def is_national_list_entry(self) -> bool:
        """False for a nonsynthetic row, which Trazo catalogues and the regulation does not list."""
        return self.cfr_section != self.NONSYNTHETIC

    @property
    def citation(self) -> str:
        """The rule's citation, e.g. "§ 205.601(e)"; empty for a row that has no citation to give.

        The letter comes from the rule (`national_list_citations`), not from the stored `subsection`:
        a substance the rule lists under several letters (elemental sulfur: (e), (h), (i), (j)) is
        cited by its section alone, never by the one letter the catalogue happened to store. A row the
        table does not name keeps the stored form."""
        if not self.cfr_section or not self.is_national_list_entry:
            return ""
        from certifications.services.national_list_citations import citation_letter

        return citation_letter(self) or (f"§ {self.cfr_section}" + (f"({self.subsection})" if self.subsection else ""))

    @property
    def rule_words(self) -> tuple[str, str] | None:
        """(paragraph, the rule's words) for a § 205.601 row whose entry carries words beyond its name;
        None otherwise. Verbatim from eCFR, never the paraphrase in `restriction_notes`."""
        from certifications.services.national_list_citations import rule_words

        return rule_words(self)

    @property
    def allowed_with_condition(self) -> bool:
        """An allowed § 205.601 row the rule permits only under a condition of use (documented
        deficiency, structural use only, minimise copper in the soil). No surface may call it plain
        "allowed". Typed by paragraph in `national_list_citations.USE_CONDITION_601`."""
        if (self.status or "").lower() != "allowed":
            return False
        from certifications.services.national_list_citations import use_condition

        return use_condition(self) is not None

    def __str__(self):
        if not self.is_national_list_entry:
            return f"{self.substance_name} (nonsynthetic, no National List entry — {self.status})"
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
        ("usda_organic", "USDA Organic Integrity — monthly XLSX mirror"),
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
    A product on the OMRI (Organic Materials Review Institute) Products List.

    ⛔ The "OMRI is a paid subscription we cannot read" premise that used to sit here was
    FALSE, and it is why this catalogue was hand-typed. The full Crop Products List is a
    FREE public PDF — https://www.omri.org/sites/default/files/opl_pdf/CropByProduct-NOP-EN.pdf
    (and CropByCompany-NOP-EN.pdf) — and every row in `certifications/data/omri_seed.csv` is
    now transcribed from it rather than recalled. Verified 2026-09-06 against the September 5,
    2026 edition.

    `source_url` + `list_edition_date` say which published edition a row came from, so a row
    can be aged against the current one instead of being trusted indefinitely.

    ⚠️ `listing_expiration_date` is NOT in the PDF — OMRI prints it only on the per-product
    certificate page (`omri_certificate_url()`), so it is NULL for every PDF-sourced row. A
    null means UNKNOWN, never "current": no surface may render an unset expiry as if the
    listing had been confirmed live. OMRI listings do expire (dow-2900 expires 1-Dec-2026),
    and 5 codes carried in this catalogue until 2026-09-06 had already lapsed — they were
    absent from BOTH published PDFs and returned HTTP 404 at their certificate URL.
    """

    omri_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text=(
            "OMRI's own published product code: company letters, a hyphen, a product "
            "number (e.g. 'dow-2900'). Deep-links to a free public certificate at "
            "https://www.omri.org/mfg/<letters>/certificate/<number>."
        ),
    )
    product_name = models.CharField(
        max_length=200,
        help_text="Product name EXACTLY as printed on the OMRI Products List",
    )
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
    # Provenance. `verified_on_omri_website_date` stood here and was DEAD — nothing ever
    # wrote it, and its name asserted a check that had not happened. Replaced by the two
    # facts a seeder can actually state: which document a row came from, and which edition
    # of it. Both are written by `seed_omri_minimal` from the committed CSV.
    source_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Published document this row was transcribed from",
    )
    list_edition_date = models.DateField(
        blank=True,
        null=True,
        help_text="Edition date printed on that document (OMRI stamps 'Updated <date>')",
    )
    listing_expiration_date = models.DateField(
        blank=True,
        null=True,
        help_text=(
            "Date this OMRI listing expires. NOT published in the Products List PDF — it "
            "appears only on the per-product certificate — so it is NULL for PDF-sourced "
            "rows. NULL means UNKNOWN and must never render as 'current'."
        ),
    )
    # California-specific: CDFA OIM (Organic Input Material) registration is a
    # state-law requirement for fertilizing materials sold/used in CA. A product
    # can be NOP/OMRI-compliant but CDFA-unregistered, which is itself a
    # violation for CA operators. These fields let the drift detector escalate
    # a CA-establishment finding when the resolved input lacks a CDFA reg #.
    delisted_on = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Edition date on which this product was first found ABSENT from the published "
            "OMRI Crop Products List. NULL means it was on the most recently seeded edition. "
            "A value here does NOT mean the product is prohibited, only that OMRI no longer "
            "lists it, so Trazo may not state an OMRI listing for it."
        ),
    )

    is_cdfa_oim_registered = models.BooleanField(
        default=False,
        help_text="Whether this product carries a current CDFA OIM registration (CA only)",
    )
    cdfa_oim_reg_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text=(
            "⛔ UNPOPULATABLE. The published CDFA Registered OIM Products list has three "
            "columns — Firm | Product Name | Annotations — and NO identifier at all, so no "
            "seeder may write this. Every 'CDFA-OIM-*' value that used to sit here was "
            "invented. Kept only to carry a number a certifier supplies out-of-band."
        ),
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

    Source (free, no licence): the WSDA Organic Input Material List PDF at
    https://cms.agr.wa.gov/WSDAKentico/Documents/FSCS/Organic/Pubs_organic/WSDA_Organic_Input_Material_List.pdf
    Program page: https://agr.wa.gov/departments/organic/input-material-registration
    Published quarterly; `list_effective_date` is the edition date printed on the
    document and `source_url` is the document itself.

    Every row in `certifications/data/wsda_seed.csv` is transcribed from that PDF
    (782 rows, March 06, 2026 edition, verified 2026-09-06). The 42 rows that stood
    here before were hand-typed, and most of them were not on the list at all.
    The Annotation column was transcribed from the same edition on 2026-11-17 (360 of the
    782 products carry one, such as "Deficiency must be documented.").

    This is a second global catalog alongside OMRIProduct. Drift detector
    Layer-2 name matching checks WSDA after OMRI so WSDA-only products clear
    when approved on the OSP.
    """

    wsda_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text=(
            "The list's own 'WSDA Product #', a BARE INTEGER (1123, 2948, 3376). Anything "
            "else is a Trazo-invented placeholder and is withheld from every reader — see "
            "certifications.services.registry_identifiers."
        ),
    )
    brand_name = models.CharField(
        max_length=200,
        help_text="ProductName column, exactly as printed by WSDA",
    )
    manufacturer = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Registrant, from the firm heading that groups the row in the published list",
    )
    category = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text=(
            "WSDA's own 'Product Type' code, expanded via the legend printed on every page "
            "(FSA -> fertilizer-and-soil-amendment, DPC -> disease-and-pest-control, ...)"
        ),
    )
    subtype = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="WSDA's 'SubType' column (e.g. 'Kelp Extract', 'Worm Castings')",
    )
    initial_approval_year = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="WSDA's 'Initial Approval Year' column",
    )
    annotation = models.TextField(
        blank=True,
        null=True,
        help_text=(
            "WSDA's 'Annotation' column, verbatim. The list states that registered products must be "
            "used in accordance with all noted annotations. '' = WSDA prints NONE for this product; "
            "NULL = not transcribed (a row from an older seed, or one entered by hand). A NONE is "
            "never read as 'no restrictions': the label can still restrict use."
        ),
    )
    list_effective_date = models.DateField(
        blank=True,
        null=True,
        help_text="Edition date printed on the WSDA list this row was synced from",
    )
    delisted_on = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text=(
            "Edition date of the first WSDA list Trazo loaded that no longer carried this product. "
            "NULL means it was on the most recently seeded edition. A value here does NOT mean the "
            "product is prohibited, only that WSDA no longer lists it, so Trazo may not state a WSDA "
            "listing for it (overall review 2026-11, OV-MT-C04; mirrors OMRIProduct.delisted_on)."
        ),
    )
    source_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Published document this row was transcribed from",
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
        help_text=(
            "⛔ UNPOPULATABLE. The published CDFA Registered OIM Products list has three "
            "columns — Firm | Product Name | Annotations — and NO identifier at all, so no "
            "seeder may write this. Every 'CDFA-OIM-*' value that used to sit here was "
            "invented. Kept only to carry a number a certifier supplies out-of-band."
        ),
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
        # Only a real WSDA Product # (a bare integer) is shown — see
        # certifications.services.registry_identifiers. This string reaches the admin
        # and every ModelChoiceField label, and a fabricated `WSDA-REG-…` reads there
        # as a registration too.
        from certifications.services.registry_identifiers import wsda_identifier_label

        label = wsda_identifier_label(self.wsda_id)
        return f"{self.brand_name} ({label})" if label else self.brand_name


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


def _empty_module_responses():
    """Default factory for `module_responses` (guided OSP modules, WS-2).

    Shape (documented in certifications/osp_modules/schema.py and conditions.py):

        {
          "schema_version": 1,
          "modules": {
            "<module_key>": {
              "status": "not_started|in_progress|completed|not_applicable",
              "not_applicable": bool,
              "na_attestation": {"by": <user_id>, "at": "<iso>"} | None,
              "answers": {"<question_key>": {"value": <json>, "at": "<iso>"}},
              "completed_at": "<iso>" | None,
              "completed_by": <user_id> | None,
              "definition_version": "<osp_modules.CONTENT_VERSION at last write>",
            }
          },
          "parcel_modules": {"<parcel_id>": {...same shape...}},
        }

    Answers hold ONLY values the operator explicitly entered or explicitly accepted from a
    prefill suggestion — nothing here is ever written by derivation (the
    `common_osp_records.confirm()` red line applies to module answers identically).
    Writes go exclusively through the module viewset action (select_for_update
    read-modify-write); the serializer exposes this field read-only.
    """
    return {"schema_version": 1, "modules": {}, "parcel_modules": {}}


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

    # Guided OSP module answers (WS-2). Rides this row's lifecycle deliberately:
    # the draft edit-lock, new-version cloning, auditlog JSON diffs, and the
    # immutable submit snapshot all apply to module answers for free. Shape and
    # write rules documented on _empty_module_responses().
    module_responses = models.JSONField(
        default=_empty_module_responses,
        help_text="Guided OSP module answers keyed by module key — see _empty_module_responses()",
    )

    # Uploaded PDF of the certifier-signed OSP (if the farm submitted a PDF form).
    pdf_document = models.FileField(
        upload_to="osp/",
        storage=private_records_storage,
        blank=True,
        null=True,
        help_text="Uploaded OSP PDF (optional — source of truth is `sections` JSONB)",
    )

    # Snapshot PDF frozen at submit() time. Never mutated after creation — the
    # immutable artifact the farmer sends to the certifier. Satisfies the "what
    # exactly did you submit?" inspector question with a checksum-friendly file.
    submission_pdf = models.FileField(
        upload_to="osp/submissions/",
        storage=private_records_storage,
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
        storage=private_records_storage,
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
    # The plan's materials list: inputs the OPERATOR adds to this OSP (the certifier reviews the
    # plan; Trazo does not know whether it approved each entry). Run 8b (8b-06).
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
        help_text="National List entries (7 CFR 205.601/602) the operator added to this plan's materials list.",
    )
    approved_omri_products = models.ManyToManyField(
        "certifications.OMRIProduct",
        blank=True,
        related_name="approving_osps",
        help_text="OMRI-listed products the operator added to this plan's materials list.",
    )
    approved_wsda_materials = models.ManyToManyField(
        "certifications.WSDAMaterial",
        blank=True,
        related_name="approving_osps",
        help_text=(
            "WSDA Brand Name Materials List entries the operator added to this "
            "plan's materials list. WSDA is treated co-equally with OMRI by CCOF and "
            "most US certifiers — many products carry WSDA but not OMRI listing."
        ),
    )

    # 🔴 2026-09-10 — the certifying agent this plan is filed with, as the operator stated it (the
    # picker at plan start and on the plan page). The two agent fields above are approval EVIDENCE,
    # filled when the plan is already approved, and `Certification.certifier_name` exists only once
    # the operation holds a certificate — so a first-year applicant had nowhere to say who would
    # review the plan, and the packet numbered itself to CCOF's forms. `packet_agent` reads this
    # first. Organic Integrity Database spelling when picked, the operator's text when typed.
    certifier_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Certifying agent this plan is filed with, as the operator stated it.",
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
        help_text=(
            "Continuation year: the certification year this update continues (e.g., 2026). A renewal "
            "due 1 March 2026 continues 2026 and reports on the 2025 season; the additions and "
            "deletions under § 205.406(a)(2) are intended for this year."
        ),
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

    # § 205.406(a)(3). "No change" is the operator's statement under
    # `sections_unchanged_attestation[APPLICATION_INFO_KEY]`, which predates this field; this is
    # the other half, the changes themselves. Neither set means the filing does not say.
    application_info_changes = models.TextField(
        blank=True,
        default="",
        help_text="Additions to or deletions from the § 205.401(b) application information",
    )
    # § 205.406(a)(4). Three states, kept apart: None = not answered, True = the agent asked for
    # nothing further, text = what it asked for. "Nothing requested" is never inferred from an
    # empty text box.
    agent_requested_info = models.TextField(
        blank=True,
        default="",
        help_text="Other information the certifying agent requires for the year",
    )
    agent_requested_info_none = models.BooleanField(
        null=True,
        blank=True,
        help_text="True only when the operator states the agent asked for nothing further",
    )
    # The 12 months the operation reports its sales for. Each agent's fee form sets its own: Oregon
    # Tilth asks for a full 12-month period kept the same year to year, WSDA for the previous
    # calendar year. The operator states it; with none stated, the sales subtotal falls back to the
    # prior calendar year and says so.
    sales_period_start = models.DateField(null=True, blank=True)
    sales_period_end = models.DateField(null=True, blank=True)

    # What the certifier holds as "the previous plan", asked only when `prior_osp` is the
    # operation's first plan version in Trazo (no `previous_version`). Overall review 2026-11,
    # OV-PK-C01/W03/O02: in a grower's first year on Trazo the certifier holds the plan filed before
    # Trazo, on its own forms, and Trazo has no copy of it, so no comparison Trazo makes is a change
    # list against it. Status cannot answer this: `activate` takes the certificate a grower already
    # holds for the old plan. Blank on every later version (the comparison is between Trazo
    # versions) and on filings signed before the question existed.
    PRIOR_BASIS_AGENT_FILE = "agent_file"
    PRIOR_BASIS_TRAZO_VERSION = "trazo_version"
    PRIOR_PLAN_BASIS_CHOICES = [
        (PRIOR_BASIS_AGENT_FILE, "The certifier holds a plan filed before Trazo"),
        (PRIOR_BASIS_TRAZO_VERSION, "The certifier received this plan version from Trazo"),
    ]
    prior_plan_basis = models.CharField(max_length=20, choices=PRIOR_PLAN_BASIS_CHOICES, blank=True, default="")
    # What changed against that plan, as the operation states it, when the certifier holds a plan filed
    # before Trazo (`agent_file`): module keys (`MODULE_REGISTRY`), or "nothing changed". The two are
    # exclusive; both empty is "not stated", never "nothing changed". Trazo compares nothing here: it has
    # no copy of the plan these are measured against (overall review 2026-11, OV-PK-O02).
    agent_file_changed_modules = models.JSONField(default=list, blank=True)
    agent_file_nothing_changed = models.BooleanField(
        null=True,
        blank=True,
        help_text="True only when the operation states nothing in the plan on file with its agent changed",
    )

    # ------------------------------------------------------------------
    # Revisions. A filed update is never edited: a correction is the next revision, and the
    # one it corrects stays exactly as signed and filed.
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        null=True,
        related_name="osp_annual_updates",
        help_text="Denormalised from prior_osp so a year's revisions can be constrained",
    )
    revision_number = models.PositiveIntegerField(default=1)
    #: What this revision corrects in the one before it, in the operator's words. Printed on the
    #: revision's own 02 so a reader of a corrected filing sees what changed and why without diffing
    #: two PDFs (run 3, 2026-10-02). Signed when set; see `signed_content`.
    correction_note = models.TextField(blank=True, default="")
    corrects = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="correction",
        help_text="The revision this one corrects",
    )
    superseded_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When a filed correction replaced this revision as the year's current filing",
    )
    withdrawn_at = models.DateTimeField(blank=True, null=True)
    withdrawal_reason = models.TextField(blank=True, default="")

    # Signature. Written by the server from the signing user, never from a payload.
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="signed_osp_annual_updates",
    )
    signer_name = models.CharField(max_length=255, blank=True, default="")
    signer_title = models.CharField(max_length=255, blank=True, default="")
    signed_at = models.DateTimeField(blank=True, null=True)
    signed_content_sha256 = models.CharField(max_length=64, blank=True, default="")

    # Filing state. Separate from the signature: who signed is not how or when it reached
    # the agent. Each is write-once.
    FILING_METHOD_CHOICES = [
        ("agent_web_form", "Agent's web form"),
        ("agent_portal", "Agent's client portal"),
        ("email", "Email"),
        ("mail", "Mail"),
        ("in_person", "In person"),
    ]
    submitted_at = models.DateTimeField(
        blank=True, null=True, help_text="When the update was submitted to the certifier"
    )
    filing_method = models.CharField(max_length=20, choices=FILING_METHOD_CHOICES, blank=True, default="")
    certifier_acknowledged_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the certifier confirmed receipt/acceptance",
    )

    # The document as filed. Stored in the row, not in the media bucket: the bucket is
    # public-read and an object there can be overwritten, and this has to be the same bytes
    # in every packet built afterwards.
    SNAPSHOT_FROZEN = "frozen_at_filing"
    SNAPSHOT_LEGACY_NONE = "legacy_none"
    SNAPSHOT_STATE_CHOICES = [
        (SNAPSHOT_FROZEN, "Frozen when filed"),
        (SNAPSHOT_LEGACY_NONE, "Filed before Trazo kept a frozen copy"),
    ]
    snapshot_state = models.CharField(max_length=20, choices=SNAPSHOT_STATE_CHOICES, blank=True, default="")
    filed_pdf = models.BinaryField(blank=True, null=True, editable=False)
    filed_sha256 = models.CharField(max_length=64, blank=True, default="")
    # The farm's Documents copy of `filed_pdf`, filed in the same transaction as the filing
    # (`annual_update_filing.file_filing`). Revisions filed before 2026-11-02 have none and are
    # not backfilled: a document appearing on the shelf that nobody filed is the class the
    # documents module forbids.
    filed_document = models.OneToOneField(
        "documents.GeneratedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        editable=False,
        related_name="annual_update_filing",
    )

    # § 205.406(a)(1): the summary is "supported by documentation". Files already on the farm's
    # Documents shelf (uploads or generated), same establishment only (serializer field). Part of
    # the signed content once any is attached (`signed_content`), so a signed filing's evidence
    # list cannot change without breaking the signature, and the documents route refuses to
    # delete a file a filing names (RESTRICT on the link).
    supporting_documents = models.ManyToManyField(
        "documents.GeneratedDocument",
        through="OSPAnnualUpdateSupportingDocument",
        blank=True,
        related_name="annual_updates_supported",
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
                fields=["establishment", "reporting_year", "revision_number"],
                name="unique_annual_update_revision",
            ),
            # One filing stands for a year at a time, whichever plan versions it moved between.
            models.UniqueConstraint(
                fields=["establishment", "reporting_year"],
                condition=models.Q(
                    submitted_at__isnull=False,
                    superseded_at__isnull=True,
                    withdrawn_at__isnull=True,
                ),
                name="one_current_filed_annual_update_per_year",
            ),
        ]

    # The fields a signature covers. `new_osp` is not one of them: it is the backlink to the
    # version a later fork produced (see `annual_update_linking`), set by the server once and
    # never re-pointed. Filing and status fields are not either; each is write-once or set only
    # by its own action.
    SIGNED_FIELDS = (
        "prior_osp_id",
        "reporting_year",
        "changes_summary",
        "additions",
        "deletions",
        "sections_unchanged_attestation",
        "application_info_changes",
        "agent_requested_info",
        "agent_requested_info_none",
        "revision_number",
        "corrects_id",
    )

    def signed_content(self) -> dict:
        content = {name: getattr(self, name) for name in self.SIGNED_FIELDS}
        # Added 2026-10-02. Hashed only when set, so every revision signed before the field existed
        # (none has a note) keeps the hash it was signed with; a note written after signing breaks
        # the match, as any other edit does.
        if self.correction_note:
            content["correction_note"] = self.correction_note
        # Added 2026-10-23, hashed only when stated, for the same reason.
        if self.sales_period_start or self.sales_period_end:
            content["sales_period"] = [self.sales_period_start, self.sales_period_end]
        # Added 2026-11-02, hashed only when any is attached, for the same reason. The document's
        # public id stands for its bytes: a filed document's file is never replaced (the documents
        # route edits only title and tags) and a linked one cannot be deleted.
        if self.pk is not None:
            attached = sorted(str(pid) for pid in self.supporting_documents.values_list("public_id", flat=True))
            if attached:
                content["supporting_documents"] = attached
        # Added 2026-11-14, hashed only when stated, for the same reason.
        if self.prior_plan_basis:
            content["prior_plan_basis"] = self.prior_plan_basis
        # The statement is hashed only while the basis asks for it: a statement left stored after the
        # basis moved off `agent_file` is printed nowhere, so a signature must not cover it (review of
        # back #439).
        if self.holds_no_agent_copy and self.agent_file_changed_modules:
            content["agent_file_changed_modules"] = list(self.agent_file_changed_modules)
        if self.holds_no_agent_copy and self.agent_file_nothing_changed is not None:
            content["agent_file_nothing_changed"] = self.agent_file_nothing_changed
        return content

    @property
    def holds_no_agent_copy(self) -> bool:
        """True when the operation states its certifier holds a plan filed before Trazo, so Trazo has
        no copy of the plan the changes are measured against."""
        return self.prior_plan_basis == self.PRIOR_BASIS_AGENT_FILE

    @property
    def states_agent_file_changes(self) -> bool:
        """The operation said what changed against the plan its agent holds: modules, or nothing."""
        return self.holds_no_agent_copy and (
            bool(self.agent_file_changed_modules) or self.agent_file_nothing_changed is True
        )

    def content_sha256(self) -> str:
        import hashlib
        import json

        canonical = json.dumps(self.signed_content(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def replace_supporting_documents(self, documents) -> None:
        """Make the attached list exactly `documents`, in the order given, first occurrence wins.

        NOT `supporting_documents.set()`: Django's M2M add collects the target ids into a Python
        set and bulk-inserts the through rows in that set's iteration order, which follows the
        ids' hash slots, not the order the operator attached the files. 02 prints and the packet
        ships the list in link order (`OSPAnnualUpdateSupportingDocument.Meta.ordering`), so a
        filing attached as [invoice, map] read back as [map, invoice] whenever the two ids fell
        that way in the set (CI, 2026-11-02: [144, 143] != [143, 144]). Rewriting every link in
        one ordered bulk insert keeps created_at and id ascending in attach order. The signed
        content hashes the sorted public ids, so the order itself is never part of a signature.
        """
        ordered, seen = [], set()
        for document in documents:
            if document.pk not in seen:
                seen.add(document.pk)
                ordered.append(document)
        # One unit: a failed insert must not leave the filing with its old links deleted and no new
        # ones (the serializer path is not otherwise wrapped in a transaction).
        with transaction.atomic():
            self.supporting_links.all().delete()
            OSPAnnualUpdateSupportingDocument.objects.bulk_create(
                [OSPAnnualUpdateSupportingDocument(annual_update=self, document=document) for document in ordered]
            )

    def save(self, *args, **kwargs):
        # Seeds and tests create filings straight through the ORM; the year's constraints need
        # the establishment whichever way the row was made.
        if self.establishment_id is None and self.prior_osp_id is not None:
            self.establishment_id = (
                OrganicSystemPlan.objects.filter(pk=self.prior_osp_id)
                .values_list("establishment_id", flat=True)
                .first()
            )
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"establishment"}
        super().save(*args, **kwargs)

    @property
    def is_signed(self) -> bool:
        return self.signed_at is not None

    @property
    def is_locked(self) -> bool:
        """Signed or filed: the content is the record and changes only by correction."""
        return self.signed_at is not None or self.submitted_at is not None

    def __str__(self):
        return f"Annual Update {self.reporting_year} r{self.revision_number} — {self.prior_osp}"


class OSPAnnualUpdateSupportingDocument(models.Model):
    """One document a § 205.406(a) filing names as support for its (a)(1) summary.

    RESTRICT on the document: deleting an upload a filing names is refused (the documents route
    says so first, by code), while deleting the whole establishment still cascades through both.
    """

    annual_update = models.ForeignKey(OSPAnnualUpdate, on_delete=models.CASCADE, related_name="supporting_links")
    document = models.ForeignKey(
        "documents.GeneratedDocument", on_delete=models.RESTRICT, related_name="annual_update_links"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["annual_update", "document"], name="unique_annual_update_supporting_doc"),
        ]

    def __str__(self):
        return f"{self.annual_update_id} supported by document {self.document_id}"


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

    #: Who signs. OTCO C2 2.5 requires every party that managed the parcel in the past 36 months to sign,
    #: the current landowner/manager requesting certification included, and CCOF ORGB49 §G asks an Affidavit
    #: of Land History "signed and dated by each person identified in question F6": when the operation itself
    #: managed the parcel, it signs one for its own period. Such an affidavit is the operation's, never a
    #: previous manager's: it does not appear among prior parties and it does not count toward "every prior
    #: party signed". The signed copy is the agent's own form, uploaded; Trazo does not sign anything.
    SIGNER_ROLE_CHOICES = [
        ("prior_manager", "A previous manager or owner"),
        ("this_operation", "This operation, for its own period"),
    ]
    signer_role = models.CharField(max_length=20, choices=SIGNER_ROLE_CHOICES, default="prior_manager")

    # Prior land manager/user (MOFGA field 3) — the signer of record
    previous_manager_name = models.CharField(max_length=200)
    previous_manager_address = models.CharField(max_length=300, blank=True, null=True)
    previous_manager_phone = models.CharField(max_length=30, blank=True, null=True)

    # Landowner if different from manager (MOFGA field 4)
    landowner_name = models.CharField(max_length=200, blank=True, null=True)
    landowner_address = models.CharField(max_length=300, blank=True, null=True)
    landowner_phone = models.CharField(max_length=30, blank=True, null=True)

    # 3-year history table (MOFGA field 5) — list of dicts covering the transition window.
    # We store 3 years by convention but allow more (some certifiers ask for 5).
    #
    # 2026-08-12: the USDA Land Use History Verification form asks for "Material /
    # Manufacturer" and "Date Applied" as separate columns. `inputs` alone answers neither
    # — a 36-month eligibility determination turns on the DATE. New rows should carry
    # `manufacturer` and `date_applied`; `inputs` stays for rows already on file and is
    # never parsed into the new keys (splitting prose means guessing, and the guess would
    # land in an eligibility determination).
    #
    # Shape: [{year, land_use, inputs, applied_by, manufacturer, date_applied}]
    #
    # 2026-11-11: optional `material_type` (CCOF ORGB49 Affidavit D's "Type" column, one of
    # `AFFIDAVIT_MATERIAL_TYPES`), and `period_from` / `period_to` ("YYYY-MM") and `acres` for the use the row
    # describes (WSDA AGR 2262 ref 7: dates produced and acreage). Validated by the serializer.
    yearly_history = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of {year, land_use, inputs, applied_by, manufacturer, date_applied} dicts "
            "covering the 3+ year transition window"
        ),
    )

    # ------------------------------------------------------------------
    # USDA Land Use History Verification (form #2) — fields MOFGA's layout omits
    # ------------------------------------------------------------------
    #: USDA prints a "☐ No materials applied" checkbox. Without it an EMPTY `yearly_history`
    #: is ambiguous in the worst possible direction: it could mean "the signer declared
    #: nothing was applied" or "nobody filled this in yet", and a packet that renders the
    #: second as the first manufactures a § 205.202(b) attestation nobody made.
    #:
    #: This is the same rule as `attestation_absence_is_not_denial`. Three states, not two:
    #: True = affirmatively declared none, False = materials are listed, None = unanswered.
    no_materials_applied = models.BooleanField(
        blank=True,
        null=True,
        help_text=(
            "Signer's affirmative declaration that NO materials were applied during their "
            "management (USDA's checkbox). NULL means the question was never answered — "
            "which is NOT the same as a declaration of none, and must never be rendered as one."
        ),
    )
    #: USDA asks for the "Dates of management/control" the signer is attesting FOR. Without
    #: the window, the affidavit does not say which part of the 36 months it covers, and a
    #: signer who managed the land for one of the three years reads as covering all three.
    management_period_start = models.DateField(
        blank=True,
        null=True,
        help_text="Start of the period the signer managed or controlled this land (USDA 'Dates of management/control')",
    )
    management_period_end = models.DateField(
        blank=True,
        null=True,
        help_text="End of the period the signer managed or controlled this land",
    )
    #: USDA: "assessor's parcel number, county, township/section/range, or other regulatory
    #: description". `field_name` is the operation's internal name for the block, which is
    #: not something a certifier or a county office can look up.
    parcel_legal_description = models.CharField(
        max_length=300,
        blank=True,
        null=True,
        help_text=(
            "Regulatory description of the land — assessor's parcel number, county, "
            "township/section/range, or equivalent. Distinct from field_name, which is the "
            "operation's own label for the block."
        ),
    )

    def declared_no_materials_applied(self):
        """True only when the signer AFFIRMATIVELY declared no materials were applied.

        Named to mirror its backing field `no_materials_applied`, and deliberately NOT
        `declares_no_materials` — that is a real BooleanField on the sibling
        `AdjoiningLandAffidavit`. Two models one screen apart, one where the name is a column
        and one where it is a method, is a trap: `aff.declares_no_materials` without parens
        returns a bound method, which is always truthy, and would have rendered
        "None applied (declared)" for every affidavit ever filed.

        Deliberately not `not self.yearly_history`. An empty history is an unanswered
        question, and treating it as a declaration would fabricate the exact attestation
        § 205.202(b) eligibility rests on.
        """
        return self.no_materials_applied is True

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
        storage=private_records_storage,
        blank=True,
        null=True,
        help_text="Scanned copy of the signed affidavit",
    )

    notes = models.TextField(blank=True, null=True)

    # ------------------------------------------------------------------
    # CCOF ORGB49 Affidavit of Land History B and C; WSDA AGR 2262 refs 5a, 5b, 6 and the attestation block.
    # All optional and blank by default: a blank is "not stated", never a default answer.
    # ------------------------------------------------------------------
    #: CCOF B: "I have this knowledge because: I owned the parcel / I managed the parcel / Other". Inferred
    #: before from whether `landowner_name` differs from the signer, which is a guess, not an attestation.
    SIGNER_BASIS_CHOICES = [
        ("owned", "Owned the parcel and controlled activities there"),
        ("managed", "Managed the parcel and controlled activities there"),
        ("other", "Other"),
    ]
    signer_basis = models.CharField(max_length=10, choices=SIGNER_BASIS_CHOICES, blank=True, default="")
    signer_basis_other = models.CharField(max_length=300, blank=True, default="")
    #: CCOF C signature block: Name, Title, Company, Email, Phone; WSDA AGR 2262: print name, email, phone.
    signer_title = models.CharField(max_length=120, blank=True, default="")
    signer_company = models.CharField(max_length=200, blank=True, default="")
    signer_email = models.EmailField(blank=True, default="")
    #: WSDA AGR 2262 5a(i): the date of the signer's last organic inspection, when the site was certified.
    last_inspection_date = models.DateField(blank=True, null=True)
    #: WSDA AGR 2262 5b: whether part of the site stays on the signer's certificate, and how many acres.
    PORTION_CHOICES = [("yes", "A portion remains with the signer"), ("no", "The whole site was transferred")]
    portion_remains = models.CharField(max_length=3, choices=PORTION_CHOICES, blank=True, default="")
    acres_remaining = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    #: WSDA AGR 2262 6 and 6a: treated seed planted during the signer's own management, with brand and date.
    TREATED_SEED_CHOICES = [("yes", "Yes"), ("no", "No")]
    treated_seed_planted = models.CharField(max_length=3, choices=TREATED_SEED_CHOICES, blank=True, default="")
    treated_seed_detail = models.TextField(blank=True, default="")

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


class AdjoiningLandAffidavit(models.Model):
    """Neighbor-signed adjoining-land attestation (USDA form #25, 7 CFR 205.202(c)).

    Deliberately a separate model from `Parcel.buffer_zones`, not extra keys on it. They
    answer the same question from two different authorities:

        buffer_zones            what the OPERATOR says about the boundary
        AdjoiningLandAffidavit  what the NEIGHBOR signs about their own practices

    Folding the second into the first would let an operator's own entry render as a
    third-party attestation, which is the claim-shape failure this codebase has hit
    repeatedly. Distance is stored in FEET because that is the unit USDA's form prints and
    the unit a neighbour will say out loud; `buffer_zones.buffer_width_m` is metres, and
    converting between them silently is how a 25 ft buffer becomes a 25 m one.

    Follows the `LandownerAffidavit` pattern — one row per neighbour per bordering side.
    """

    MATERIAL_CHOICES = {
        "synthetic_fertilizers": "Synthetic fertilizers",
        "herbicides": "Herbicides",
        "insecticides": "Insecticides",
        "fungicides": "Fungicides",
        "treated_wood": "Treated wood",
        "other": "Other",
    }

    BORDER_SIDE_CHOICES = [
        ("N", "North"),
        ("E", "East"),
        ("S", "South"),
        ("W", "West"),
        ("NE", "Northeast"),
        ("NW", "Northwest"),
        ("SE", "Southeast"),
        ("SW", "Southwest"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    parcel = models.ForeignKey(
        "product.Parcel",
        on_delete=models.CASCADE,
        related_name="adjoining_land_affidavits",
        help_text="Parcel whose boundary this attestation covers",
    )

    neighbor_name = models.CharField(max_length=200)
    neighbor_farm_name = models.CharField(max_length=200, blank=True, default="")
    neighbor_address = models.CharField(max_length=300, blank=True, default="")
    neighbor_phone = models.CharField(max_length=30, blank=True, default="")
    border_side = models.CharField(
        max_length=2,
        choices=BORDER_SIDE_CHOICES,
        blank=True,
        default="",
        help_text="Which side of the organic parcel this neighbour borders",
    )

    #: TRI-STATE. NULL means the neighbour did not answer, which is NOT "they are not
    #: organic" — an unanswered question rendered as a negative is the same fabrication the
    #: landowner affidavit's `no_materials_applied` exists to prevent.
    neighbor_is_certified_organic = models.BooleanField(
        blank=True,
        null=True,
        help_text=(
            "Neighbour's own declaration that they are certified organic (or exempt by sales "
            "volume). NULL means unanswered — never render it as 'not organic'."
        ),
    )
    neighbor_certifier_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Certifying agent named by the neighbour, when they declared they are certified",
    )

    #: USDA prints "☐ none of the above" alongside the material checkboxes, so absence of
    #: ticks and an affirmative "none" are different answers and are stored differently:
    #: an empty list is unanswered; `declares_no_materials` True is the signed negative.
    materials_used = models.JSONField(
        default=list,
        blank=True,
        help_text="Codes from MATERIAL_CHOICES the neighbour routinely uses. Empty = unanswered.",
    )
    declares_no_materials = models.BooleanField(
        blank=True,
        null=True,
        help_text=(
            "Neighbour ticked USDA's 'none of the above'. NULL means unanswered — distinct "
            "from an affirmative declaration that they use none of the listed materials."
        ),
    )
    not_used_on_adjoining_fields = models.BooleanField(
        blank=True,
        null=True,
        help_text=(
            "Neighbour uses the materials above but NOT on the fields adjoining this parcel "
            "(USDA's separate checkbox). NULL means unanswered."
        ),
    )
    distance_to_organic_property_ft = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text=(
            "Distance in FEET from the neighbour's material use to the organic property, as "
            "the neighbour states it. Feet because that is the unit USDA's form prints — "
            "buffer_zones.buffer_width_m is metres and the two must not be silently mixed."
        ),
    )
    agrees_to_notify = models.BooleanField(
        blank=True,
        null=True,
        help_text=(
            "Neighbour agreed to notify the operation before applying materials "
            "(a drift-prevention practice, § 205.201(a)(5)). NULL means unanswered."
        ),
    )

    neighbor_signed_date = models.DateField(blank=True, null=True)
    signed_document = models.FileField(
        upload_to="adjoining_land_affidavits/",
        storage=private_records_storage,
        blank=True,
        null=True,
        help_text="Scanned copy of the signed attestation",
    )
    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_adjoining_land_affidavits",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Adjoining Land Affidavit"
        verbose_name_plural = "Adjoining Land Affidavits"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["parcel", "border_side"])]

    def __str__(self):
        return f"Adjoining-land affidavit — {self.neighbor_name} ({self.get_border_side_display() or '—'})"

    def materials_display(self):
        """The neighbour's declared materials, or "" when nothing was recorded.

        Returns "" rather than "none" for an empty list: absence of ticks is an unanswered
        question, and `declares_no_materials` is where an affirmative "none" lives.
        Unknown codes pass through instead of being dropped.
        """
        codes = self.materials_used
        if not isinstance(codes, list):
            return ""
        return ", ".join(self.MATERIAL_CHOICES.get(c, str(c)) for c in codes if c)

    def is_signed(self):
        """A third-party attestation is only third-party evidence once the third party signed.

        Without this the packet would present a form someone typed on a neighbour's behalf as
        a signed statement from that neighbour.
        """
        return bool(self.neighbor_signed_date or self.signed_document)


class PlanMaterialEntry(models.Model):
    """A material the operator put on the plan in their own words.

    🔴 The defect this closes (certifier register, `materials-list-cannot-hold-a-material`,
    4 blocker rows across CCOF and WSDA): the only path onto an OSP's materials list was a
    catalog match against Trazo's OMRI subset, the WSDA Brand Name list, or the seeded National
    List. CCOF ORGB41 §A names compost, manure, gypsum and limestone in its own prompt; the
    pilot's Rexius Organic Compost and Douglas-fir sawdust dead-ended at "No match — record it
    under Notification of Changes"; WSDA AGR 2196 is one undifferentiated table with no category
    split at all. Meanwhile the module printed five attestations that every material in use was
    "entered in the materials list on this plan", so the packet asserted a completeness the
    product made impossible — the only remaining defect that makes the packet lie.

    § 205.201(a)(2) asks for "a description of the … substances to be used as production inputs".
    The producer is the author (§ 205.201(a)); a catalog is a convenience, never the gate.

    ⛔ THE CLAIM RULE THIS MODEL EXISTS UNDER. A row here is the OPERATOR'S statement, and its
    `listing_basis` is what may be said about it and nothing more. `none_unlisted` must never
    render as listed, approved or verified — it renders as what it is: a material on the plan
    with no third-party listing behind it, which is a perfectly legitimate thing for a certifier
    to review and decide. Only a genuine catalog resolution may name OMRI, WSDA or the National
    List, and `certifier_letter` must name the letter.
    """

    CATEGORY_CHOICES = [
        ("fertilizer_amendment", "Fertilizers and soil amendments (CCOF §A)"),
        ("pest_disease_weed", "Pest, weed and disease control materials (CCOF §B)"),
        ("production_aid", "Other crop production materials — seed treatments, growing media, adjuvants (CCOF §C)"),
        ("post_harvest", "Post-harvest materials — wash-water additives, sanitizers (CCOF §D)"),
        ("facility_pest", "Pest control in handling and storage facilities (CCOF §F, §G)"),
        ("other", "Other"),
    ]

    #: CCOF Materials Application §F lists facility pest control "by National List material type";
    #: §G any material that "does not fit a §F National List type". § 205.271(c) allows a substance
    #: on the National List when prevention and mechanical controls are not effective, and (d) a
    #: synthetic not on it only when the handler and the certifying agent agree on the substance, the
    #: method and the measures that keep it from the product.
    FACILITY_MATERIAL_TYPE_CHOICES = [
        ("ammonium_carbonate", "Ammonium carbonate"),
        ("boric_acid", "Boric acid"),
        ("botanical_pesticides", "Botanical pesticides"),
        ("carbon_dioxide", "Carbon dioxide"),
        ("diatomaceous_earth", "Diatomaceous earth"),
        ("nitrogen_gas", "Nitrogen gas"),
        ("nonsynthetic_bait_lure_repellent", "Nonsynthetic bait, lure or repellent"),
        ("pheromones", "Pheromones"),
        ("pyrethrum_pyrethrins", "Pyrethrum or pyrethrins"),
        ("sticky_traps", "Sticky traps"),
        ("vitamin_d3", "Vitamin D3"),
        ("not_national_list", "Not a National List type (CCOF §G)"),
    ]

    BASIS_OMRI = "omri"
    BASIS_WSDA = "wsda"
    BASIS_NATIONAL_LIST = "national_list"
    BASIS_CERTIFIER_LETTER = "certifier_letter"
    BASIS_NONE = "none_unlisted"
    LISTING_BASIS_CHOICES = [
        (BASIS_OMRI, "OMRI listed"),
        (BASIS_WSDA, "WSDA Brand Name Materials List"),
        (BASIS_NATIONAL_LIST, "National List substance (7 CFR 205.601-606)"),
        (BASIS_CERTIFIER_LETTER, "Approved by our certifier in writing"),
        (BASIS_NONE, "No third-party listing — for certifier review"),
    ]

    #: What each catalog basis is allowed to SAY, once its catalog row is confirmed present.
    #: Deliberately NOT `dict(LISTING_BASIS_CHOICES)`: those labels are picker text and carry
    #: "(7 CFR 205.601-606)", which has no business riding along on a statement whose listing
    #: cannot be produced.
    #:
    #: ⛔ No " — " in any of these. `plan_materials.PlanMaterial.display()` joins name,
    #: manufacturer and this string with " — ", so an em dash here silently adds a fourth
    #: segment to a three-segment row, and a cell that truncates at the boundary prints the
    #: bare claim — the very thing this rule exists to stop.
    BASIS_STATEMENT = {
        BASIS_OMRI: "OMRI listed",
        # WSDA's own name for it ("Brand Name Material List", the list's footer, read 2026-11-04).
        BASIS_WSDA: "WSDA Brand Name Material List",
        BASIS_NATIONAL_LIST: "National List substance",
    }

    #: Which catalog FK has to still resolve for each basis to be sayable. The write path
    #: (PlanMaterialEntrySerializer.validate) refuses a catalog basis with no FK; the READ side
    #: has to state the same rule, because the FK can go away after the write.
    BASIS_CATALOG_FIELD = {
        BASIS_OMRI: "omri_product",
        BASIS_WSDA: "wsda_material",
        BASIS_NATIONAL_LIST: "national_list_substance",
    }

    STATUS_PLANNED = "planned"
    STATUS_IN_USE = "in_use"
    #: 2026-11-04. Kept on the plan, not deleted: the records still name it for the year it was used,
    #: and CCOF advises against removing a material that may be used again. It prints as no longer
    #: used, and an agent's list keeps it until the operator asks the agent to remove it.
    STATUS_DISCONTINUED = "discontinued"
    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned for use"),
        (STATUS_IN_USE, "In use"),
        (STATUS_DISCONTINUED, "No longer used"),
    ]

    #: What the certifying agent did with this material, as the OPERATOR records it from the agent's
    #: own list or letter (CCOF's "OSP Materials List listing approved materials", OTCO's MyOTCO
    #: "approved materials list", WSDA "approved for them in the previous year"). A different axis
    #: from `listing_basis`: OTCO and CCOF approve OMRI-listed products too, and an OMRI listing is
    #: not an approval. Blank means not recorded, never "not approved". Never inferred, never set by
    #: Trazo (2026-11-04, the CCOF, WSDA and OTCO materials audits).
    REVIEW_REQUESTED = "requested"
    REVIEW_APPROVED = "approved"
    REVIEW_NOT_APPROVED = "not_approved"
    REVIEW_INCOMPLETE = "review_incomplete"
    AGENT_REVIEW_CHOICES = [
        (REVIEW_REQUESTED, "Submitted to the agent for review"),
        (REVIEW_APPROVED, "On the agent's approved materials list"),
        (REVIEW_NOT_APPROVED, "Not approved by the agent"),
        (REVIEW_INCOMPLETE, "The agent could not complete its review"),
    ]

    osp = models.ForeignKey(
        OrganicSystemPlan,
        on_delete=models.CASCADE,
        related_name="plan_material_entries",
        help_text="OSP whose materials list this row belongs to",
    )
    product_name = models.CharField(
        max_length=300,
        help_text="Full product name including formulation, as it appears on the label",
    )
    manufacturer = models.CharField(max_length=200, blank=True, default="")
    # Blank until the operator picks a section. The default was "fertilizer_amendment", so a material
    # nobody sorted printed as a fertilizer on WSDA's AGR 2196 (review of back #294): a default the
    # form cannot tell from an answer is a claim the operator never made.
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES, blank=True, default="")
    reason_for_use = models.TextField(
        blank=True,
        default="",
        help_text="Why this material is used — CCOF and WSDA both ask for it per row",
    )
    listing_basis = models.CharField(
        max_length=32,
        choices=LISTING_BASIS_CHOICES,
        default=BASIS_NONE,
        help_text="What may be said about this material, and nothing more",
    )
    certifier_letter_reference = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Which certifier letter approved it — required when listing_basis is certifier_letter",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PLANNED)
    notes = models.TextField(blank=True, default="")

    agent_review = models.CharField(max_length=20, choices=AGENT_REVIEW_CHOICES, blank=True, default="")
    agent_review_date = models.DateField(
        null=True, blank=True, help_text="Date on the agent's list or letter, as the operator records it"
    )
    agent_review_reference = models.CharField(
        max_length=200, blank=True, default="", help_text="Which list, letter or message of the agent shows it"
    )
    #: The agent the review came from, set by the server from the plan's agent when the review is
    #: recorded, so an operation that changes agent never shows one agent's approval as another's.
    agent_review_agent = models.CharField(max_length=32, blank=True, default="")
    #: The use the agent reviewed it for (WSDA: "approved ... for their specific use"); blank when
    #: it is the reason for use above.
    agent_review_use = models.CharField(max_length=300, blank=True, default="")
    # CCOF §F and §G, asked of a `facility_pest` row only: which National List type it is (or that it is
    # none), where in the facility it is used, and whether it is applied by fumigation or fogging.
    facility_material_type = models.CharField(
        max_length=40, choices=FACILITY_MATERIAL_TYPE_CHOICES, blank=True, default=""
    )
    where_used = models.CharField(max_length=200, blank=True, default="")
    applied_by_fumigation = models.BooleanField(null=True, blank=True)
    #: OTCO C11 11.1 asks, per row, which third party reviewed the product: OMRI, WSDA or OTHER. The first
    #: two are the catalog listing above; OTHER is anyone else, most often a manufacturer's OTCO Crop
    #: Input Verification Evaluation or another certifying agent's review. As the operator records it,
    #: from the review's own document; Trazo never names a reviewer. Refused on an OMRI or WSDA row,
    #: whose reviewer is the listing (2026-11-16).
    other_review_agency = models.CharField(max_length=200, blank=True, default="")
    other_review_reference = models.CharField(
        max_length=200, blank=True, default="", help_text="The review's own number, date or document"
    )
    #: The product's label, or a photo of its container, filed in the farm's Documents. OTCO C11 11.1
    #: asks for one "for each product that is not OMRI or WSDA listed" (read live 2026-11-04). PROTECT:
    #: the documents route refuses to delete a file a material still names.
    label_document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="material_labels",
    )

    # Optional shortcut, never the gate: when the operator's material DID resolve against a
    # catalog, the resolution is kept so the listing basis is checkable rather than asserted.
    national_list_substance = models.ForeignKey(
        NationalListSubstance, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    omri_product = models.ForeignKey(OMRIProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    wsda_material = models.ForeignKey(WSDAMaterial, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Plan material entry"
        verbose_name_plural = "Plan material entries"
        ordering = ["category", "product_name"]
        indexes = [models.Index(fields=["osp", "category"])]

    def __str__(self):
        return f"{self.product_name} ({self.get_category_display()})"

    @property
    def catalog_basis_unresolved(self) -> bool:
        """True when this row claims a catalog listing whose catalog row is no longer there.

        🔴 2026-09-07: `omri_product` is SET_NULL and `listing_statement` read `listing_basis`
        alone, so removing the material from the plan's approved-inputs M2M and re-seeding the
        catalog left the row printing "OMRI listed" with no OMRI row anywhere in the database —
        into the module PDF, the § 205.201(a)(2) narrative, the workbook and the dossier. The
        write-path guard could not help: nothing was being written.
        """
        field = self.BASIS_CATALOG_FIELD.get(self.listing_basis)
        return bool(field) and getattr(self, f"{field}_id", None) is None

    @property
    def listing_review_position(self) -> str:
        """Which box of OTCO C11's review-agency cell this row's own listing fills: "omri", "wsda" or
        "other". A lapsed OMRI listing, or one whose catalog row is gone, is no longer OMRI's review, so
        the row may name another agency (review of back #457: the stored basis alone kept it stuck)."""
        if self.listing_basis == self.BASIS_OMRI:
            product = self.omri_product if self.omri_product_id else None
            return "omri" if product is not None and not product.delisted_on else "other"
        if self.listing_basis == self.BASIS_WSDA:
            material = self.wsda_material if self.wsda_material_id else None
            return "wsda" if material is not None and not material.delisted_on else "other"
        return "other"

    @property
    def agent_review_statement(self) -> str:
        """The agent's review as the operator recorded it, or "" when none is. Never "approved by
        Trazo", never "verified": the operator's statement about the agent's own document."""
        if not self.agent_review:
            return ""
        from certifications.certifying_agents import agent_by_slug

        agent = agent_by_slug(self.agent_review_agent)
        name = (agent.short_name or agent.name) if agent else "the certifying agent"
        when = self.agent_review_date.isoformat() if self.agent_review_date else ""
        ref = self.agent_review_reference.strip()
        lead = {
            self.REVIEW_REQUESTED: f"submitted to {name} for review" + (f" on {when}" if when else ""),
            self.REVIEW_APPROVED: f"on {name}'s approved materials list" + (f" dated {when}" if when else ""),
            self.REVIEW_NOT_APPROVED: f"not approved by {name}" + (f" on {when}" if when else ""),
            self.REVIEW_INCOMPLETE: f"{name} could not complete its review" + (f" ({when})" if when else ""),
        }.get(self.agent_review, "")
        if not lead:
            return ""
        text = lead + (f" ({ref})" if ref else "")
        use = self.agent_review_use.strip()
        if use and use.lower() != (self.reason_for_use or "").strip().lower():
            text += f", reviewed for: {use}"
        return text + ", as recorded by the operator"

    @property
    def listing_statement(self) -> str:
        """What may be printed about this row's standing. Never more than the basis supports."""
        if self.listing_basis == self.BASIS_CERTIFIER_LETTER:
            ref = self.certifier_letter_reference.strip()
            return f"approved by our certifier in writing{f' ({ref})' if ref else ''}"
        if self.catalog_basis_unresolved:
            # Say what the operator claimed AND that it cannot be substantiated right now.
            # Silently degrading to "no third-party listing" would delete the operator's own
            # statement; keeping the bare claim would assert a listing with nothing behind it.
            #
            # The QUALIFIER LEADS, and there is no " — " in the string. Both are load-bearing:
            # this sentence is joined into a " — "-separated row and rendered into table cells,
            # so a trailing qualifier is the half that gets truncated away, leaving the bare
            # claim standing on its own.
            claimed = self.BASIS_STATEMENT.get(self.listing_basis, self.listing_basis)
            return f"unverified: cited as {claimed}, catalog listing not on file"
        if self.listing_basis in self.BASIS_STATEMENT:
            return self.BASIS_STATEMENT[self.listing_basis]
        # Not "operator-entered; no third-party listing" — every surface that prints this already
        # groups or labels the row as operator-entered, so saying it twice read as padding on the
        # pilot's own packet. The half that carries information is the listing.
        return "no third-party listing on file"


class ApprovedInputChangeLog(models.Model):
    """
    Immutable audit record written every time an input is added to or removed
    from OrganicSystemPlan.approved_national_list_substances /
    approved_omri_products.

    Satisfies the inspector question "when did Copper hydroxide enter the
    approved list, and which certifier letter authorised it?" under
    7 CFR 205.400(f)(2) change-notification obligations (operation change).

    Write-only from the API perspective: rows are created by
    OrganicSystemPlanViewSet.add_approved_input / remove_approved_input, and since
    2026-11-16 by the operator-entered materials paths when they add or remove a
    material the plan carried no other way (`KIND_OPERATOR`).
    No update / delete endpoints are exposed; the log is append-only.
    """

    KIND_NATIONAL_LIST = "national_list"
    KIND_OMRI = "omri"
    KIND_WSDA = "wsda"
    #: A material the operator put on the plan in their own words (`PlanMaterialEntry`), with no catalog
    #: attachment behind it. Until 2026-11-16 only catalog attaches were logged, so a compost added
    #: mid-year left no dated row: nothing for `plan_review` to flag and nothing to mark as an addition
    #: on OTCO's C11 ("to be added to my current Materials List") or CCOF's materials list update.
    KIND_OPERATOR = "operator_entered"
    KIND_CHOICES = [
        (KIND_NATIONAL_LIST, "National List substance (7 CFR 205.601–606)"),
        (KIND_OMRI, "OMRI-listed product (farmer-reported)"),
        (KIND_WSDA, "WSDA Brand Name Materials List (Washington State Dept of Ag)"),
        (KIND_OPERATOR, "Operator-entered material"),
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
        storage=private_records_storage,
        blank=True,
        null=True,
        help_text="Supporting document / certifier acknowledgment letter, if any.",
    )
    # WSDA AGR 2516: "If acreage is removed from organic production, include a map identifying the new
    # boundaries and include details on why the acreage was removed (transferred to another grower,
    # converted to conventional, etc.)". The map rides `supporting_document`; the reason had no field,
    # and `description` is illustrated with an addition. Required for a NEW field-removal notice by the
    # serializer; a notice recorded before 2026-10-24 reads as "reason not recorded", never guessed.
    removal_reason = models.TextField(
        blank=True,
        default="",
        help_text="Why the acreage left organic production (field removal notices only).",
    )
    certifier_acknowledged_at = models.DateField(
        null=True,
        blank=True,
        help_text="Date the certifier acknowledged the change (blank until acknowledged).",
    )
    # The FIELD a notice is about, when it is about one. A certifier's letter names the field
    # ("buffer on Home Field West widened to 45 ft"); until 2026-08-23 the notice had no link to
    # the parcel, so it lived only on the OSP screen while that parcel's application went on
    # printing the old buffer width — the two statements never met on one page. Optional,
    # because a change of buyer or a new material is not about a field. SET_NULL: a notice is a
    # record of what the certifier was told and outlives a parcel row.
    parcel = models.ForeignKey(
        "product.Parcel",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="change_notifications",
        help_text="The parcel this notice concerns, if it concerns one (prints on that parcel's application).",
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

    def clean(self):
        """Only the impossible is refused: a notification dated in the future.

        A blank `date_notified` is deliberately still allowed, including for the § 205.400(f)(1)
        immediate category. Requiring it there was tried and reverted: a grower discovering drift
        this morning must be able to RECORD it before they have phoned the certifier, and a hard
        requirement makes the most urgent category the only one that cannot be entered promptly.
        Blank means "not documented", exactly as everywhere else in this schema — the certifier
        packet names the gap instead (see the (f)(1) review flag in the audit export), which
        surfaces it without refusing a legitimate record.

        A future date IS refused: it cannot have happened, and a typo'd year silently reorders
        the packet's audit trail, which sorts on this column.
        """
        from django.core.exceptions import ValidationError

        if self.date_notified and self.date_notified > timezone.localdate():
            raise ValidationError({"date_notified": "The certifier cannot have been notified on a future date."})

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

    Every California operation producing or handling raw agricultural products sold as
    organic must register annually with the CDFA State Organic Program BEFORE the first
    sale (CA Food & Ag Code § 46013.1(a); 3 CCR 1380-1394), declaring
    commodities, operation type, and prior-year organic gross sales, and renew
    each year. A NOP "$5,000-exempt" producer is still subject to CA state
    registration. This is a hard inspection item Trazo previously could not
    record at all.

    Modeled generically (``state`` field) so other state programs reuse it;
    California (CDFA) is the only one enforced today.

    Scope note, CDFA vs CDPH: California registers an organic operation with one of two
    agencies. CDFA takes crops, raw-ag handling (hull/shell/wash/sort/pack) and produce
    brokers; CDPH takes processed products (roasting, grinding to butter/flour, oil
    pressing, blanching, adding ingredients). CCOF's Certification Contract (E1, E2) and
    OTCO's O1 (E-1, E-2) ask both numbers, and CCOF's says an operation holds one.
    2026-11-15: each row names its agency (`registering_agency`), and the packet cover
    prints the latest row of each agency on file, so a CDPH number is never printed under
    CDFA's name and an operation that does hold both shows both.
    """

    OPERATION_TYPE_CHOICES = [
        ("producer", "Producer / Grower"),
        # "handler" = CDFA raw-ag handling (hull/shell/wash/sort/pack). A processed
        # organic product (roast/grind/press/blanch) needs a separate CDPH registration.
        ("handler", "Handler (CDFA raw-ag handling)"),
        ("producer_handler", "Producer & Handler"),
        ("retailer", "Retailer"),
        ("processor", "Processor (CDPH processed products)"),
    ]
    AGENCY_CHOICES = [
        ("cdfa", "CDFA California Organic Program (crops, post-harvest handling, produce brokers)"),
        ("cdph", "CDPH organic registration (processed products)"),
    ]
    #: The program each agency's row is filed under. Kept in step by `save()` for a California
    #: row, so the audit dossier's "Program" line can never name the other agency.
    CA_PROGRAM_NAMES = {
        "cdfa": "CDFA State Organic Program",
        "cdph": "CDPH Organic Processed Product Registration",
    }
    STATUS_CHOICES = [
        ("registered", "Registered"),
        ("pending", "Pending"),
        ("expired", "Expired"),
        # Food & Agr. Code § 46013.1(a): an operation under $5,000 is "only exempt from
        # certification under federal organic standards and [is] still required to be registered".
        # The label said "Exempt" alone, which read as exempt from registering.
        ("exempt", "Registered, exempt from certification (under $5,000 organic sales)"),
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
    registering_agency = models.CharField(
        max_length=4,
        choices=AGENCY_CHOICES,
        default="cdfa",
        help_text="California agency the registration is held with: CDFA, or CDPH for processed products",
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
        storage=private_records_storage,
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

    @classmethod
    def latest_per_agency(cls, establishment, state=None) -> list:
        """The latest row of each agency on file, CDFA first, then CDPH.

        One reader for the packet cover and the audit dossier (PDF and CSV): a single
        `.order_by("-registration_date").first()` let a pending CDPH row with no date yet sort first
        (Postgres puts NULL first in a descending sort) and print under CDFA's name, flagged as not
        current, for an operation validly registered with CDFA (review of back #433). Undated rows
        sort after dated ones, and each agency is read on its own.
        """
        from django.db.models import F

        rows = cls.objects.filter(establishment=establishment)
        if state:
            rows = rows.filter(state=state)
        latest: dict = {}
        for reg in rows.order_by(F("registration_date").desc(nulls_last=True), "-pk"):
            latest.setdefault(reg.registering_agency, reg)
        return [latest[agency] for agency, _label in cls.AGENCY_CHOICES if agency in latest]

    def save(self, *args, **kwargs):
        # A California row's program follows its agency. A name typed by hand for another program is
        # left alone; only the two names this model writes are kept in step.
        if self.state == "CA" and (not self.program_name or self.program_name in self.CA_PROGRAM_NAMES.values()):
            self.program_name = self.CA_PROGRAM_NAMES[self.registering_agency]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.program_name} — {self.establishment.name} ({self.registration_number or 'unregistered'})"

    @property
    def is_current(self):
        """True if the operation is covered today: a 'registered' record, or an exempt one
        with its registration number, whose renewal_date has not passed. Used by the audit
        export to decide whether to fire the missing/expired-registration REVIEW
        flag, and by any first-organic-sale gate."""
        # An exempt operation is exempt from certification only, never from registration
        # (Food & Agr. Code § 46013.1(a)), so it is current only with a number on file.
        if self.status == "exempt" and not self.registration_number:
            return False
        if self.status not in ("registered", "exempt"):
            return False
        if self.renewal_date is None:
            return True
        return self.renewal_date >= timezone.now().date()

    @property
    def not_current_reason(self):
        """Why `is_current` is False, in words a reviewer can act on, or None when it is current.

        One wording for the packet cover and the audit dossier (PDF and CSV), so the three cannot name
        different causes for one registration.
        """
        if self.is_current:
            return None
        if self.status == "exempt":
            return (
                "The registration number is not recorded. An operation under $5,000 is exempt from "
                "certification only; California still requires it to register (Food & Agr. Code § 46013.1(a))."
            )
        if self.status in ("pending", "expired"):
            return f"The registration on file is {self.status}, not registered."
        return f"The registration's renewal date ({self.renewal_date.isoformat()}) has passed."


class CertifierAccessLink(models.Model):
    """A no-account, read-only link that lets a certifier open an operation's audit dossier.

    Closes the one capability COG Pro advertises that Trazo lacked: "your
    certification provider can even inspect your records online, with your
    permission." Trazo's answer is strictly better for the certifier — COG Pro
    makes them log in; this needs nothing but the URL.

    The dossier itself is NOT new: `OperationAuditExportService` already builds a
    whole-operation NOP packet for a certification window, and it is
    user-independent, carries no self-graded transparency score and no
    subscription coupling. This model only solves DELIVERY, and it beats emailing
    a PDF because the dossier is regenerated on open (never a stale attachment),
    can be revoked, and every open is logged back to the farmer.

    SECURITY. This exposes far more than the consumer QR page — supplier names and
    invoices, purchase prices, applicator names, and open drift/nonconformance
    findings. Controls: a 32-byte urlsafe token, a default 90-day expiry, farmer
    revocation at any time, an access log, and scoping to exactly one
    establishment. The token is deliberately NOT hashed at rest: the same database
    already holds every underlying record, so hashing buys nothing against a DB
    compromise while making the link impossible to re-copy. Expiry, revocation and
    logging are the controls that actually matter.
    """

    DEFAULT_VALIDITY_DAYS = 90

    #: Who this link is FOR decides what it can open — two disjoint content classes.
    #: "certifier" resolves the audit dossier surface, which deliberately exposes MORE
    #: than the consumer page (supplier names, invoices, prices, applicator names,
    #: open findings). "buyer" resolves ONLY the claim-safe consumer payload — the
    #: same uniform-policy view the public product page serves — but in-season and
    #: before publish, because the farmer consented by minting the link. A buyer
    #: token on a certifier endpoint (or vice versa) is a 404, never a downgrade.
    AUDIENCE_CHOICES = [
        ("certifier", "Certifier"),
        ("buyer", "Buyer"),
    ]

    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="certifier_access_links",
        help_text="The single operation this link exposes. Never company-wide.",
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Unguessable URL secret (secrets.token_urlsafe(32)).",
    )
    label = models.CharField(
        max_length=120,
        blank=True,
        help_text='Farmer-facing note, e.g. "CCOF 2026 renewal".',
    )
    certification_type = models.CharField(
        max_length=20,
        default="organic",
        help_text="Dossier profile passed to OperationAuditExportService.",
    )
    audience = models.CharField(
        max_length=12,
        choices=AUDIENCE_CHOICES,
        default="certifier",
        help_text="Which review surface this token opens: certifier dossier or buyer (claim-safe) view.",
    )
    period_start = models.DateField(
        null=True,
        blank=True,
        help_text="Optional start of the certification window the dossier covers.",
    )
    period_end = models.DateField(
        null=True,
        blank=True,
        help_text="Optional end of the certification window the dossier covers.",
    )
    # Source files (handoff rehearsal 2026-10-18, H-3). The dossier lists the operation's uploads
    # by title only; with this set, the reviewer can also open each listed file through the link
    # while it is active. Chosen when the link is created, never changed afterwards: consent is to
    # THIS link, and revoking it ends the access. All uploads in scope or none, never a per-file
    # pick (uniform policy). A downloaded copy stays with the recipient after revocation; the
    # grower is told so before choosing. Certifier links only.
    include_source_files = models.BooleanField(
        default=False,
        help_text="If set, the reviewer can open the operation's uploaded files through this link.",
    )
    expires_at = models.DateTimeField(help_text="After this instant the link stops resolving.")
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set when the farmer revokes; revocation is immediate and permanent.",
    )
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_certifier_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["establishment", "-created_at"]),
        ]

    def __str__(self):
        return f"Certifier link for {self.establishment.name} ({self.label or 'unlabelled'})"

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(32)

    @classmethod
    def resolve_buyer_token(cls, token):
        """Return the ACTIVE buyer-audience link for `token`, or None.

        Used by the anonymous consumer endpoints (`public_history`, transparency
        detail) to let a buyer link open an UNPUBLISHED / in-season production.
        Audience is filtered here, not by the caller: a certifier token must never
        widen the consumer surface, and a buyer token must never open the dossier.
        """
        if not token:
            return None
        link = cls.objects.filter(token=token, audience="buyer").select_related("establishment").first()
        if link is None or not link.is_active:
            return None
        return link

    @staticmethod
    def default_expiry():
        return timezone.now() + timedelta(days=CertifierAccessLink.DEFAULT_VALIDITY_DAYS)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_active(self) -> bool:
        """Only an active link resolves. Callers must check this, not just existence."""
        return not self.is_revoked and not self.is_expired

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class CertifierAccessLog(models.Model):
    """One row per open of a CertifierAccessLink.

    Surfaced back to the farmer so "did my certifier actually look at this?" is a
    fact rather than a guess — the thing a mailed PDF can never tell them. Kept on
    delete of the link's establishment only (CASCADE via the link).
    """

    ACTION_CHOICES = [
        ("metadata", "Opened link"),
        ("readiness", "Viewed readiness findings"),
        ("dossier", "Downloaded dossier"),
        ("production", "Viewed a production page"),
        ("document", "Opened a source file"),
        ("traceback", "Traced a sale"),
    ]

    link = models.ForeignKey(
        CertifierAccessLink,
        on_delete=models.CASCADE,
        related_name="accesses",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default="metadata")
    accessed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    # Which file, for a `document` open. SET_NULL so the log outlives a deleted upload.
    document = models.ForeignKey(
        "documents.GeneratedDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="review_link_accesses",
    )

    class Meta:
        ordering = ["-accessed_at"]

    def __str__(self):
        return f"{self.get_action_display()} at {self.accessed_at:%Y-%m-%d %H:%M}"


#: The only fields an append-only Phase 5 record may write after creation: closing it, by supersession
#: or by withdrawal.
_CLOSING_FIELDS = frozenset({"superseded_at", "withdrawn_at", "withdrawal_reason", "withdrawn_by", "withdrawn_by_name"})


class _IdentityDecisionQuerySet(models.QuerySet):
    """Bulk writes refused, matching the instance guard: a row is superseded, never edited. Shared by the
    Phase 5 append-only records (identity decisions, restriction statements)."""

    def update(self, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError("This record is append-only: never edited; record a new one.")

    def delete(self):
        from django.core.exceptions import ValidationError

        raise ValidationError("This record is append-only: never deleted.")

    def bulk_update(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError("This record is append-only: never edited in bulk.")

    def bulk_create(self, objs, *args, **kwargs):
        if kwargs.get("update_conflicts"):
            from django.core.exceptions import ValidationError

            raise ValidationError("This record is append-only: never overwritten.")
        return super().bulk_create(objs, *args, **kwargs)


class MaterialIdentityDecision(models.Model):
    """The operator's decision about what a logged product name IS. Append-only.

    WHY THIS EXISTS (OSP alignment audit 2026-10, T18; Phase 5 slice 2)
    ------------------------------------------------------------------
    Materials were matched by exact name only, so 28 sprays logged as "Neptune's Harvest Fish
    Fertilizer 2-3-1" never met the plan's "…2-4-1", and nothing said whether they were one product
    or two. Matching by resemblance is the error the National List alias rule forbids. The operator
    decides instead, once per logged name, and the decision is kept as evidence:

      * `same_as`: these events used this product on the plan (a plan entry, or an OMRI or WSDA
        product the plan approves). Never a National List substance: a substance is a
        classification, not a product.
      * `different_product`: the name is its own product, not the plan's.

    What a decision covers is exact: the events it lists, each with the FINGERPRINT of its
    identity-relevant content when reviewed (name as logged, manufacturer, EPA number, lot, the
    event's own catalog links). An edit to any of those, or a later event under the same name, is not
    covered until the operator reviews it. A change of mind is a new row that supersedes this one;
    `superseded_at` is the only field ever written after creation.

    A decision is not classification and not approval: it writes no event field, changes no National
    List classification and adds nothing to the plan. Readers that use it state its basis.
    """

    SOURCE_CHEMICAL = "chemical"
    SOURCE_AMENDMENT = "amendment"
    SOURCE_SANITIZER = "sanitizer"
    SOURCE_CHOICES = [
        (SOURCE_CHEMICAL, "Chemical application"),
        (SOURCE_AMENDMENT, "Soil amendment"),
        (SOURCE_SANITIZER, "Post-harvest sanitizer"),
    ]
    SAME_AS = "same_as"
    DIFFERENT_PRODUCT = "different_product"
    DECISION_CHOICES = [(SAME_AS, "Same product as a plan material"), (DIFFERENT_PRODUCT, "A different product")]
    TARGET_PLAN_ENTRY = "plan_entry"
    TARGET_OMRI = "omri"
    TARGET_WSDA = "wsda"
    TARGET_CHOICES = [
        (TARGET_PLAN_ENTRY, "Plan materials entry"),
        (TARGET_OMRI, "OMRI product on the plan"),
        (TARGET_WSDA, "WSDA material on the plan"),
    ]

    establishment = models.ForeignKey(
        "company.Establishment", on_delete=models.CASCADE, related_name="material_identity_decisions"
    )
    #: The plan the decision was made against; a `same_as` target was on this plan then.
    osp = models.ForeignKey(OrganicSystemPlan, on_delete=models.PROTECT, related_name="material_identity_decisions")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES)
    logged_name = models.CharField(max_length=255)
    name_key = models.CharField(max_length=255, db_index=True)
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES)
    target_kind = models.CharField(max_length=16, choices=TARGET_CHOICES, blank=True, default="")
    target_id = models.PositiveIntegerField(null=True, blank=True)
    target_name = models.CharField(max_length=255, blank=True, default="")
    #: [{"event_id": int, "fingerprint": str}]: the events reviewed, with their content when reviewed.
    reviewed = models.JSONField(default=list)
    #: [{"event_id": int, "reason": str}]: reviewed events the operator excluded from the decision.
    exceptions = models.JSONField(default=list, blank=True)
    formulation_difference_acknowledged = models.BooleanField(default=False)
    formulation_note = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by_name = models.CharField(max_length=255, blank=True, default="")
    decided_at = models.DateTimeField()
    supersedes = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="superseded_by"
    )
    superseded_at = models.DateTimeField(null=True, blank=True)
    # Withdrawn by the operator (a mistaken entry), with a reason. Written once, with superseded_at, so
    # the row stops being current and stays in the history (browser test, 2026-10-03).
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True, default="")
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    withdrawn_by_name = models.CharField(max_length=255, blank=True, default="")

    objects = _IdentityDecisionQuerySet.as_manager()

    class Meta:
        ordering = ["decided_at", "id"]
        indexes = [models.Index(fields=["establishment", "source", "name_key"], name="material_identity_key_idx")]
        constraints = [
            # One current decision per logged name: two concurrent first decisions cannot both stand.
            models.UniqueConstraint(
                fields=["establishment", "source", "name_key"],
                condition=models.Q(superseded_at__isnull=True),
                name="one_current_identity_per_name",
            )
        ]

    def __str__(self):
        state = "superseded" if self.superseded_at else "current"
        return f"{self.logged_name} ({self.source}): {self.decision} ({state})"

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        if self.pk is not None:
            allowed = set(kwargs.get("update_fields") or ())
            if not allowed or not allowed <= _CLOSING_FIELDS:
                raise ValidationError("A material identity decision is never edited; record a new one.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError("A material identity decision is never deleted.")


class PlanMaterialRestrictionStatement(models.Model):
    """How one restriction on one plan material is met, in the operator's words. Append-only.

    OSP alignment audit T18 (Phase 5 slice 2b; Oscar's rules, 2026-10-02). WSDA AGR 2196 and CCOF's
    Materials Application ask how each material's restrictions are met. Trazo holds verified wording
    for few restrictions (§ 205.602 conditions of use), WSDA's own annotation for each product on its
    list (transcribed 2026-11-17, printed as WSDA's words), and nothing for OMRI listings, so:

      * a statement is bound to ONE material on ONE plan version and ONE identified restriction; a
        material can carry several;
      * the restriction is either REGULATION text Trazo holds (citation, its effective date and when
        Trazo last read it), WSDA'S OWN ANNOTATION for a WSDA-listed product (the list's edition date),
        or TRANSCRIBED by the operator (the copied wording, the kind of source, its
        identifier, page or section, and an optional attachment or reference). Transcribed text prints
        as "transcribed by the operator; not independently verified by Trazo". Verified wording says
        nothing about whether the restriction applies to this material or use;
      * "how it is met" is the operator's statement, attributed and dated, never a compliance result;
      * a change of mind is a new row that supersedes this one; `superseded_at` is the only field
        written after creation.

    A statement approves nothing, classifies nothing and clears no finding.
    """

    MATERIAL_PLAN_ENTRY = "plan_entry"
    MATERIAL_OMRI = "omri"
    MATERIAL_WSDA = "wsda"
    MATERIAL_NATIONAL_LIST = "national_list"
    MATERIAL_CHOICES = [
        (MATERIAL_PLAN_ENTRY, "Plan materials entry"),
        (MATERIAL_OMRI, "OMRI product"),
        (MATERIAL_WSDA, "WSDA material"),
        (MATERIAL_NATIONAL_LIST, "National List substance"),
    ]
    SOURCE_REGULATION = "regulation"
    SOURCE_TRANSCRIBED = "operator_transcribed"
    #: The annotation WSDA prints for the product on its Organic Input Material List
    #: (`WSDAMaterial.annotation`), held by Trazo with the list's edition date (2026-11-17).
    SOURCE_WSDA_LIST = "wsda_list_annotation"
    SOURCE_CHOICES = [
        (SOURCE_REGULATION, "Regulation text held by Trazo"),
        (SOURCE_TRANSCRIBED, "Transcribed by the operator"),
        (SOURCE_WSDA_LIST, "WSDA list annotation held by Trazo"),
    ]
    DOC_LABEL = "product_label"
    DOC_OMRI = "omri_listing"
    DOC_WSDA = "wsda_listing"
    DOC_CERTIFIER = "certifier_letter"
    DOC_OTHER = "other"
    DOC_CHOICES = [
        (DOC_LABEL, "Product label"),
        (DOC_OMRI, "OMRI listing"),
        (DOC_WSDA, "WSDA listing"),
        (DOC_CERTIFIER, "Certifier letter"),
        (DOC_OTHER, "Other document"),
    ]

    osp = models.ForeignKey(OrganicSystemPlan, on_delete=models.PROTECT, related_name="restriction_statements")
    material_kind = models.CharField(max_length=16, choices=MATERIAL_CHOICES)
    material_id = models.PositiveIntegerField()
    material_name = models.CharField(max_length=255)
    restriction_source = models.CharField(max_length=24, choices=SOURCE_CHOICES)
    #: "nl:<id>" for regulation text; a hash of the transcription for operator text. One current
    #: statement per (plan, material, restriction).
    restriction_key = models.CharField(max_length=80)
    restriction_text = models.TextField()
    # Regulation text
    national_list_substance = models.ForeignKey(
        NationalListSubstance, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    citation = models.CharField(max_length=40, blank=True, default="")
    source_effective_date = models.DateField(null=True, blank=True)
    source_read_at = models.DateTimeField(null=True, blank=True)
    # Operator-transcribed text
    source_type = models.CharField(max_length=20, choices=DOC_CHOICES, blank=True, default="")
    source_identifier = models.CharField(max_length=255, blank=True, default="")
    source_locator = models.CharField(max_length=255, blank=True, default="")
    source_reference = models.TextField(blank=True, default="")
    attachment = models.ForeignKey(
        "documents.GeneratedDocument", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # The operator's statement
    how_met = models.TextField()
    stated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    stated_by_name = models.CharField(max_length=255, blank=True, default="")
    stated_at = models.DateTimeField()
    supersedes = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="superseded_by"
    )
    superseded_at = models.DateTimeField(null=True, blank=True)
    # Withdrawn by the operator (a mistaken entry), with a reason. Written once, with superseded_at, so
    # the row stops being current and stays in the history (browser test, 2026-10-03).
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True, default="")
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    withdrawn_by_name = models.CharField(max_length=255, blank=True, default="")

    objects = _IdentityDecisionQuerySet.as_manager()

    class Meta:
        ordering = ["stated_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["osp", "material_kind", "material_id", "restriction_key"],
                condition=models.Q(superseded_at__isnull=True),
                name="one_current_statement_per_restriction",
            )
        ]

    def __str__(self):
        return f"{self.material_name}: {self.restriction_key} ({'superseded' if self.superseded_at else 'current'})"

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        if self.pk is not None:
            allowed = set(kwargs.get("update_fields") or ())
            if not allowed or not allowed <= _CLOSING_FIELDS:
                raise ValidationError("A restriction statement is never edited; record a new one.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        raise ValidationError("A restriction statement is never deleted.")
