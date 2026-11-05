"""
Documents / DMS — the farm's document shelf (WS-3).

## Why this exists

Before WS-3, every PDF Trazo generated was streamed and discarded, and uploaded files
were FileFields scattered across eight models with no unified "your farm's documents"
view — the single biggest structural gap against a certification assistant, whose core
promise is "everything lands in one organized place." This model is that place: one row
per generated artifact or farmer upload, folder-organized, establishment-scoped.

## Rules

- **Generated documents are immutable history.** A dossier generated on a date is a
  record of what existed that day; the viewset refuses to delete anything whose source
  is not `upload`. Regenerating creates a NEW row (dated), never mutates an old one.
- **The certifier link deliberately does NOT file here.** Its dossier regenerates on
  every open — freshness is that feature; the DMS holds the dated copies the farmer
  explicitly generates.
- Filing happens through exactly one seam — `documents.services.filing.file_document()`
  — called by generator views at explicit generate actions. Nothing files from signals
  or background jobs (a document appearing that the farmer didn't ask for is the
  fabrication failure class again, in file form).
"""

import uuid

from django.conf import settings
from django.db import models

from backend.storage import private_records_storage


class GeneratedDocument(models.Model):
    # Trazo-shaped folder taxonomy (plan §1.6 #54) — organized by what the document IS,
    # not by which app produced it.
    FOLDER_CHOICES = [
        ("organic_system_plan", "Organic System Plan"),
        ("certifications", "Certifications"),
        ("activity_attachments", "Activity Attachments"),
        ("exports", "Exports"),
        ("uploads", "Uploads"),
    ]

    SOURCE_CHOICES = [
        ("osp_snapshot", "OSP submission snapshot"),
        ("module_pdf", "OSP module PDF"),
        ("packet", "OSP packet ZIP"),
        ("workbook", "Common OSP workbook"),
        ("dossier", "Audit dossier"),
        ("operation_dossier", "Operation audit dossier"),
        ("pur", "California PUR export"),
        ("lot_tag", "Lot tag sheet"),
        # "Upload", not "Farmer upload": the operator, a consultant or a crew lead uploads as
        # often as the grower does, and the label printed on the Documents page claimed farmer
        # authorship for every one of them (pilot rehearsal 2026-10, finding 5). Who uploaded
        # it is `created_by`, which the page shows by name.
        ("upload", "Upload"),
        # The preview an operator files before loading transcribed records (`import_records`):
        # the dated copy of what the grower approved. Not an upload, so it is undeletable and
        # stays out of the certifier's upload index.
        ("import_preview", "Record import preview"),
        # The § 205.406(a) annual update as filed: `OSPAnnualUpdate.filed_pdf`, the same bytes,
        # filed by `annual_update_filing.file_filing` at the moment the operator records the
        # filing. One row per filed revision; a correction files its own.
        ("annual_update", "Annual update filing"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey(
        "company.Establishment",
        on_delete=models.CASCADE,
        related_name="documents",
    )
    folder = models.CharField(max_length=32, choices=FOLDER_CHOICES, db_index=True)
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, db_index=True)
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/%Y/%m/", storage=private_records_storage)
    content_type = models.CharField(max_length=100, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)

    # Optional context links — which OSP module section / parcel / production this
    # document belongs to (drives "documents for this module" and activity-attachment
    # filtering without a folder explosion).
    linked_section = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="OSP module key this document supports (e.g. g8_0_record_keeping)",
    )
    parcel = models.ForeignKey(
        "product.Parcel", on_delete=models.SET_NULL, null=True, blank=True, related_name="documents"
    )
    history = models.ForeignKey(
        "history.History", on_delete=models.SET_NULL, null=True, blank=True, related_name="documents"
    )

    # The one requirement a file answers (OSP alignment audit 2026-10, T19). `linked_section`
    # says which module a file was uploaded under; that is not the same as answering a named
    # attachment, and a coverage page that counted section uploads as answers would close the
    # label question with an unrelated soil test. A qualified upload question key
    # ("g7_0_labeling.label_files_upload"), validated against the module registry on upload.
    requirement = models.CharField(max_length=128, blank=True, default="", db_index=True)
    # The sale a source document belongs to (T22): the invoice, bill of lading or pack-out
    # summary behind a sale the audit-trail exhibit prints. Until this, the exhibit printed the
    # invoice NUMBER and nothing could say whether the document behind it was held anywhere.
    sales_record = models.ForeignKey(
        "history.SalesRecord", on_delete=models.SET_NULL, null=True, blank=True, related_name="source_documents"
    )
    SOURCE_KIND_CHOICES = [
        ("invoice", "Invoice"),
        ("bill_of_lading", "Bill of lading"),
        ("packout", "Pack-out summary"),
        ("other", "Other"),
        # The purchase receipt behind a spray, amendment or seed purchase record's invoice number, filed ON that
        # record (event_type/event_id). Only this kind counts as the record's receipt
        # (history/services/record_receipts.py): the same link also carries a soil test's lab
        # report or a photo, and none of those is a receipt.
        ("receipt", "Purchase receipt"),
    ]
    source_kind = models.CharField(max_length=20, choices=SOURCE_KIND_CHOICES, blank=True, default="")

    # The one activity record a document belongs to (pilot rehearsal 2026-10, finding 4): the
    # supplier invoice behind a May 15 spray, the lab report behind a soil test. Until this, an
    # upload could name the season and no finer, so an inspector tracing an application to its
    # invoice had to search the season's whole shelf. Keyed by (event_type, event_id) for the
    # same reason EventAmendment is: 8 concrete event models, addressed that way everywhere
    # (history.constants.EVENT_TYPE_TO_MODEL). Both set or both NULL (CheckConstraint below).
    event_type = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="history.constants EVENT_TYPE_TO_MODEL key of the activity record this document belongs to.",
    )
    event_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    # The linked record's identity (history.Activity), written with the pair above; `save()`
    # resolves it from the pair when a writer only holds the pair (file_document, the admin).
    activity = models.ForeignKey(
        "history.Activity",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="documents",
    )

    # Farmer-managed labels (QO's DMS carries Owner + Tags per document; owner here is
    # created_by, tags are free labels). Per-document org ACLs are deliberately NOT
    # modeled — Trazo's sharing primitive is the scoped CertifierAccessLink.
    tags = models.JSONField(default=list, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["establishment", "folder", "-created_at"]),
            models.Index(fields=["establishment", "source"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(event_type__isnull=True, event_id__isnull=True)
                    | models.Q(event_type__isnull=False, event_id__isnull=False)
                ),
                name="document_event_link_is_whole",
            )
        ]

    def save(self, *args, **kwargs):
        # The identity follows the pair (see `activity`); a tombstone link is kept.
        from history.activity_ref import sync_activity_link

        sync_activity_link(self, "event_type", "event_id", "activity_id")
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "activity" not in update_fields:
            kwargs["update_fields"] = list(update_fields) + ["activity"]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_folder_display()} · {self.title}"

    @property
    def is_deletable(self) -> bool:
        """Only farmer uploads may be deleted — generated documents are dated history."""
        return self.source == "upload"


class ExportJob(models.Model):
    """A document build that runs OUTSIDE the request that asked for it.

    Why (2026-09-05): the operation audit dossier for a 12-production farm ran ~2,750 queries
    and laid out ~400 pages inside one GET — about a minute in production, against an edge
    that drops requests at ~100 s, holding one of eight gunicorn threads the whole time. A
    PDF that can take longer than a page load is a JOB: the request records what was asked
    for and returns at once; a runner builds it, files the result in the DMS (the artifact the
    farm keeps anyway), and the requester is told where it is. The row is also the cache key
    for the certifier link — a build whose `fingerprint` still matches the records is served
    again instead of rebuilt (`history/services/records_fingerprint.py`).

    Status is the only contract the clients read: queued → running → succeeded | failed.
    `progress_*` is advisory ("Production 4 of 12"). `heartbeat_at` lets a reaper tell a
    build that is still running from one whose process died mid-way.
    """

    KIND_CHOICES = [
        ("operation_dossier", "Operation audit dossier"),
    ]
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]
    AUDIENCE_CHOICES = [
        ("farmer", "Farm member"),
        ("certifier", "Certifier review link"),
    ]
    TERMINAL_STATUSES = ("succeeded", "failed")

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    establishment = models.ForeignKey("company.Establishment", on_delete=models.CASCADE, related_name="export_jobs")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="export_jobs",
        help_text="Null for a build started by an anonymous certifier review link.",
    )
    audience = models.CharField(max_length=16, choices=AUDIENCE_CHOICES, default="farmer")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    certification_type = models.CharField(max_length=32, default="organic")
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued", db_index=True)
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    progress_label = models.CharField(max_length=200, blank=True, default="")
    fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="records_fingerprint() of the establishment at the moment the build started.",
    )
    document = models.ForeignKey(
        GeneratedDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name="export_jobs"
    )
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["establishment", "kind", "status"], name="documents_exportjob_lookup"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} for establishment {self.establishment_id} [{self.status}]"

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL_STATUSES

    def key(self) -> dict:
        """The parameters that make two builds interchangeable (given equal records)."""
        return {
            "kind": self.kind,
            "certification_type": self.certification_type,
            "period_start": self.period_start,
            "period_end": self.period_end,
        }
