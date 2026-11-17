"""Sales of a production's lots, and buyers' document requests."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .production import ORGANIC_LABEL_CATEGORY_CHOICES, Production


class BuyerDocRequest(models.Model):
    """
    Phase 4 — buyer documentation request from the consumer proof view.

    A retail/wholesale buyer scanning a product can request supplier
    documentation (certificates, audit packet) without calling anyone. Each
    request becomes a lead on the farmer's dashboard plus an in-app
    notification. Public endpoint is rate-limited and deduplicated (same
    email + production within 24h is idempotent).
    """

    STATUS_CHOICES = [
        ("new", "New"),
        ("contacted", "Contacted"),
        ("closed", "Closed"),
    ]

    production = models.ForeignKey(
        Production,
        on_delete=models.CASCADE,
        related_name="buyer_doc_requests",
    )
    requester_name = models.CharField(max_length=120)
    requester_email = models.EmailField()
    organization = models.CharField(max_length=160, blank=True, default="")
    message = models.TextField(blank=True, default="", max_length=1000)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new", db_index=True)
    # SHA-256 like HistoryScan.ip_hash — rate limiting without storing raw IPs.
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Buyer Documentation Request"
        verbose_name_plural = "Buyer Documentation Requests"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["production", "-created_at"], name="buyerdocreq_prod_date_idx"),
            models.Index(fields=["requester_email", "created_at"], name="buyerdocreq_email_date_idx"),
        ]

    def __str__(self):
        return f"{self.requester_email} -> {self.production_id} ({self.status})"


class SalesRecordQuerySet(models.QuerySet):
    """`objects` deliberately returns VOIDED rows too.

    The default has to be "everything", because the two places that must never lose a voided
    row are the certifier dossier and the records export — § 205.103(b)(4) is the reason the
    row was kept instead of deleted, and a manager that hid it would re-create the deletion it
    replaced. Callers that mean "sales that happened" ask for `.live()`.
    """

    def live(self):
        """Sales that still count: not voided."""
        return self.filter(voided_at__isnull=True)

    def voided(self):
        return self.filter(voided_at__isnull=False)


class SalesRecord(models.Model):
    """
    Lightweight sales record per production lot — the SOE traceback unit.

    Inspectors verify "crop and quantity sold, date of sale, buyer" at every
    annual inspection, and mass-balance audits are mandatory under the
    Strengthening Organic Enforcement rule. The legacy single History.sold_to
    field can't represent multiple sales from one lot; these records feed the
    audit PDF's Traceability + Mass-Balance sections.

    NOT consumer-facing — buyer identity and quantities are commercially
    sensitive (same policy as ChemicalEvent supplier fields).
    """

    production = models.ForeignKey(
        Production,
        on_delete=models.CASCADE,
        related_name="sales_records",
    )
    #: WHICH harvest pass(es) this sale drew from — the other half of the § 205.103(b)(2)
    #: trace, added 2026-08-15.
    #:
    #: The production FK above says which SEASON; on a multi-pick operation that is not enough
    #: to answer "which pick went to this buyer", which is exactly the question a trace-back
    #: exercise asks. Many-to-many rather than a FK because a real load routinely combines
    #: several picks — a packer takes a truckload, not a pass.
    #:
    #: Optional on purpose. A grower who sells one lot per season should not be forced to
    #: build a link that carries no information, and pre-existing records have none; the
    #: packet degrades to the production-level trace and says so, rather than printing a gap.
    harvest_events = models.ManyToManyField(
        "history.ProductionEvent",
        blank=True,
        related_name="sales_records",
        limit_choices_to={"type": "HA"},
        help_text=(
            "Harvest pass(es) this sale drew from. Links buyer → lot → harvest for the "
            "7 CFR 205.103(b)(2) trace-back."
        ),
    )
    sale_date = models.DateField()
    buyer_name = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    #: MUST share History.UNIT_CHOICES — the harvest amount and the sale quantity are the two
    #: halves of the mass balance, and the audit export only prints the Balance line and the
    #: "sold exceeds harvest" review flag when `harvest_unit == sold_unit` (see
    #: audit_export_service._build_mass_balance_section). This field was the one unit column in
    #: the schema with no `choices` — History.production_unit and History.quantity_sold_unit
    #: both had them — so the frontend drifted to its own vocabulary and offered `tonnes` where
    #: harvest offers `tons`. Same pounds, different string, and § 205.103(b)(2) reconciliation
    #: silently disappeared from the packet with no warning printed.
    #:
    #: `default="kg"` is deliberately left alone rather than flipped to "lb": the model cannot
    #: know the farm's country, and the US-first resolution belongs in the editor
    #: (useDefaultUnits, which now seeds this field from the production's own harvest unit).
    quantity_unit = models.CharField(max_length=20, choices=Production.UNIT_CHOICES, default="kg")
    invoice_number = models.CharField(max_length=80, blank=True, default="")

    #: What the operation was PAID for this sale.
    #:
    #: 🔴 2026-08-16, CCOF grower-checklist audit. CCOF item 7 has four parts — "what you sell,
    #: how much you sell, who you sold it to, and how much money you received" — and this model
    #: answered the first three and had no column for the fourth. The itemized sales table in
    #: the certifier packet had no value column either, so an inspector could verify volume but
    #: not consideration, and the operation could not produce the "sales summaries" CCOF names
    #: as an acceptable record.
    #:
    #: NULL, not 0.00. A recorded zero (a donation, a rejected load taken at no charge) is a
    #: fact; "not entered" is the absence of one, and collapsing them is the same conflation
    #: that made `Boolean("not_organic")` read as True on the consumer page (2026-07-31) and
    #: that `BusinessEvent.clean` tests with `is None` for exactly this reason.
    #:
    #: No currency column: Trazo has one market (US) and inventing a per-row currency the UI
    #: never asks for would put an unattested "USD" on a regulatory document. When a second
    #: market arrives, currency belongs on the OPERATION, not on each sale.
    sale_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Amount received for this sale, in USD. Blank means not recorded, never zero.",
    )

    # § 205.307 — sales documents for organic product must identify it as organic.
    organic_on_invoice = models.BooleanField(default=False)
    # § 205.103(b)(3) — records must identify the product by its § 205.301 labeling category,
    # which the boolean above cannot express. Blank = not documented (see the note on
    # `clean_transport_method` below for why this is not a defaulted value).
    organic_label_category = models.CharField(
        max_length=24,
        choices=ORGANIC_LABEL_CATEGORY_CHOICES,
        blank=True,
        default="",
    )

    # --- Shipment / transport block (§ 205.272(a); § 205.103(b)(2)) ---
    # One row is one sale AND its shipment: in wholesale practice each load is
    # invoiced, so the BOL pairs 1:1 with the invoice. The per-production
    # History.transport_* fields remain as the single-shipment legacy path.
    CLEAN_TRANSPORT_CHOICES = [
        ("affidavit", "Clean-transport affidavit on file"),
        ("inspected", "Inspected clean before loading"),
        ("dedicated_organic", "Dedicated organic vehicle"),
    ]
    bill_of_lading = models.CharField(max_length=80, blank=True, default="")
    carrier_name = models.CharField(max_length=120, blank=True, default="")
    vehicle_id = models.CharField(max_length=60, blank=True, default="")
    destination = models.CharField(
        max_length=160,
        blank=True,
        default="",
        help_text="Ship-to location when different from the buyer (packer, drop yard, port).",
    )
    # A set method IS the documentation that transport integrity was addressed;
    # blank means not documented. Deliberately no separate boolean — a
    # default=False bool reads as an explicit "no" in evidence derivation
    # (see certifications.services.common_osp_records._has_content).
    clean_transport_method = models.CharField(max_length=20, choices=CLEAN_TRANSPORT_CHOICES, blank=True, default="")

    # --- USDA Clean Transport Affidavit (form #22) content ---
    # `clean_transport_method` above answers "how do you know the unit was clean" (affidavit /
    # inspected / dedicated). USDA's affidavit asks what that affidavit SAYS, and until now
    # Trazo stored only the fact that a document existed — a certifier reading the packet
    # learned a file was attached, not what it attested to.
    TRANSPORT_CLEANING_CHOICES = [
        ("swept", "Swept"),
        ("vacuum", "Vacuum"),
        ("air_blown", "Air blown"),
        ("washed", "Washed"),
        ("other", "Other — described in the notes"),
        ("not_required", "Not required — dedicated organic unit"),
    ]
    transport_cleaning_method = models.CharField(
        max_length=20,
        choices=TRANSPORT_CLEANING_CHOICES,
        blank=True,
        default="",
        help_text=(
            "How the transport unit was cleaned before loading (USDA's Swept / Vacuum / Air "
            "blown / Washed checkboxes). Distinct from clean_transport_method, which records "
            "how transport INTEGRITY was assured rather than how the unit was cleaned. Blank "
            "means not documented, never 'no cleaning'."
        ),
    )
    #: USDA: "Only used for organic products? ☐ yes ☐ no — if no, state products transported
    #: prior to organic." This is the single most useful line on the form when the unit is not
    #: dedicated: it is what lets an inspector judge the contamination risk (grain vs treated
    #: seed vs conventional produce are not equivalent).
    prior_products_transported = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "What the transport unit carried immediately before this organic load, when it is "
            "not a dedicated organic unit (7 CFR 205.272). Blank means not documented — it "
            "does NOT mean the unit was dedicated; `clean_transport_method` records that."
        ),
    )
    #: USDA: "Inspected and found free of ☐ foreign odors ☐ residues ☐ conventional products
    #: ☐ other". Conjunctive and multi-valued, so a list rather than the single-choice enum
    #: used for disjunctive questions like seed nonavailability.
    #:
    #: An EMPTY list means no inspection findings were recorded. It must never be rendered as
    #: "inspected and found clean" — that is an attestation nobody made.
    TRANSPORT_INSPECTION_CODES = {
        "foreign_odors": "Free of foreign odors",
        "residues": "Free of residues",
        "conventional_products": "Free of conventional products",
        "other": "Other findings — see notes",
    }
    transport_inspected_free_of = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "What the pre-loading inspection found the unit free of — list of codes from "
            "TRANSPORT_INSPECTION_CODES. Empty means no inspection was recorded, NOT a clean "
            "finding."
        ),
    )
    #: The notes both "Other" options above promise. TRANSPORT_CLEANING_CHOICES renders "Other —
    #: described in the notes" and TRANSPORT_INSPECTION_CODES renders "Other findings — see
    #: notes", and the packet printed both strings verbatim while this model had no notes column
    #: at all: a certifier read a pointer to a document that could not exist. Either the labels
    #: stop promising a description or the description exists; a compliance record earns more
    #: from the second. `clean()` refuses "other" without it, so the pointer is never dangling.
    transport_notes = models.CharField(
        max_length=300,
        blank=True,
        default="",
        help_text=(
            "What the 'Other' cleaning method or 'Other' inspection finding actually was. "
            "Required whenever either is selected; blank otherwise means nothing to add."
        ),
    )

    def transport_inspection_display(self):
        """USDA's "Inspected and found free of" line, or "" when nothing was recorded.

        Unknown codes are passed through rather than dropped: a value someone stored is
        evidence of something, and silently discarding it would be the packet editing the
        record. Returns "" for empty so the caller decides how absence reads.
        """
        codes = self.transport_inspected_free_of
        if not isinstance(codes, list):
            return ""
        labels = [self.TRANSPORT_INSPECTION_CODES.get(c, str(c)) for c in codes if c]
        return ", ".join(labels)

    created_at = models.DateTimeField(auto_now_add=True)

    # --- Void, not delete -------------------------------------------------------------
    # 🔴 2026-09-07. Deleting a sale on a closed season is refused (§ 205.103(b)(4), and the
    # sale is the far end of the (b)(2) trail). But there was no update path either, so a
    # mistyped sale had no correction route at all. Voiding is what a paper audit trail does:
    # the row STAYS, struck through, with a stated reason — the same shape events use, where
    # the original is kept alongside the correction.
    #
    # ⛔ A voided row is not a deleted row. It stays in the certifier dossier and the records
    # export, marked. What it must NOT do is keep counting as a sale: see `live()`.
    voided_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this sale was voided. The row is kept; it stops counting as a sale.",
    )
    void_reason = models.TextField(
        blank=True,
        default="",
        help_text="Why it was voided, in the operator's words — a void with no reason is a "
        "deletion with extra steps.",
    )
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Who voided it. Kept because § 205.103(b)(2) asks who the record's author is.",
    )

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None

    objects = SalesRecordQuerySet.as_manager()

    class Meta:
        verbose_name = "Sales Record"
        verbose_name_plural = "Sales Records"
        ordering = ["-sale_date", "-created_at"]
        indexes = [
            models.Index(fields=["production", "-sale_date"], name="salesrecord_prod_date_idx"),
        ]

    def clean(self):
        """A labeling category on a sale whose invoice does not identify it as organic is a
        contradictory record, and the packet would print both halves.

        Refuse rather than reconcile: which half is true is the operation's call, not ours.
        """
        from django.core.exceptions import ValidationError

        if self.organic_label_category and not self.organic_on_invoice:
            raise ValidationError(
                {
                    "organic_label_category": (
                        "This sale records a § 205.301 labeling category but is not marked as "
                        "identifying the product as organic on the invoice. Set "
                        "'organic on invoice', or clear the labeling category."
                    )
                }
            )

        # "Other" is the only answer on this form that carries no information by itself, and
        # both labels tell the certifier a description follows. Refuse the pointer without the
        # target rather than print "Other — described in the notes" over an empty column.
        # "Not required — dedicated organic unit" is an answer ABOUT the unit being dedicated.
        # Against an affidavit/inspected load it is self-contradictory, and the packet would
        # print both halves as fact. Same treatment as the labeling-category contradiction
        # above: refuse rather than reconcile — which half is true is the operation's call.
        if self.transport_cleaning_method == "not_required" and self.clean_transport_method in (
            "affidavit",
            "inspected",
        ):
            raise ValidationError(
                {
                    "transport_cleaning_method": (
                        "'Not required — dedicated organic unit' contradicts a clean-transport "
                        "method of affidavit or pre-load inspection, which both describe a "
                        "NON-dedicated unit. Record how this unit was actually cleaned, or set "
                        "clean transport to 'Dedicated organic vehicle'."
                    )
                }
            )

        codes = self.transport_inspected_free_of if isinstance(self.transport_inspected_free_of, list) else []
        needs_notes = self.transport_cleaning_method == "other" or "other" in codes
        if needs_notes and not (self.transport_notes or "").strip():
            raise ValidationError(
                {
                    "transport_notes": (
                        "'Other' was selected for the cleaning method or the pre-load "
                        "inspection, and both print as 'see notes' in the certifier packet. "
                        "Describe what it was, or choose a listed option."
                    )
                }
            )

    def __str__(self):
        return f"{self.sale_date} {self.buyer_name} {self.quantity} {self.quantity_unit}"
