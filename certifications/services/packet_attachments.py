"""Every file the packet carries, decided once, with what actually happened to each.

WHY THIS MODULE EXISTS
----------------------
OSP alignment audit 2026-10, T19 and T22. Uploaded label files never reached the packet, a sale's
invoice and bill of lading travelled only as numbers typed on the record, and the three kinds of
file that did ride along (parcel maps, signed affidavits, purchase receipts) were each read in
their own loop that skipped, without a word, any file it could not open. The coverage page counted
uploads from the database, so a map that failed to read was "answered" on page 04 and absent from
the ZIP.

The manifest is built before any page is written. Each candidate file is read, and its state is
what happened to its bytes:

    attached              read and written into the ZIP at `zip_path`
    held_outside_packet   readable, but past the packet's size budget; named, not attached
    unreadable            the storage read failed or the file is empty; named, not attached

Only `attached` answers an attachment question (`packet_answers`). The other two are printed by
name, on page 04 and beside the question they were uploaded for, so nothing drops silently. A
packet never fails because of an attachment.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

ATTACHED = "attached"
HELD_OUTSIDE_PACKET = "held_outside_packet"
UNREADABLE = "unreadable"

#: The requirement whose files are the operation's own label artwork (CCOF G7.0 A1/B1, WSDA §N).
LABEL_REQUIREMENT = "g7_0_labeling.label_files_upload"
PARCEL_MAP_REQUIREMENT = "parcel_application.map_upload"

_DEFAULT_BUDGET = 150 * 1024 * 1024

_current: contextvars.ContextVar = contextvars.ContextVar("packet_attachments", default=None)


@dataclass
class Attachment:
    kind: str  # parcel_map | affidavit | receipt | requirement | sale_source | lot_tag | label_photo
    label: str
    zip_path: str
    state: str = ATTACHED
    detail: str = ""
    requirement: str = ""
    parcel_id: int | None = None
    sales_record_id: int | None = None
    source_kind: str = ""
    size: int = 0
    data: bytes | None = field(default=None, repr=False)
    #: The stored object behind the entry ("doc:12", "affidavit:3", "label:7"). One document can be
    #: reachable by two routes (a receipt also uploaded for a requirement, a file uploaded for a
    #: requirement AND linked to a sale); it is read, budgeted and written once.
    source_id: str = ""


@dataclass
class Manifest:
    entries: list = field(default_factory=list)

    def for_requirement(self, requirement: str, parcel_id: int | None = None) -> list:
        return [
            e for e in self.entries if e.requirement == requirement and (parcel_id is None or e.parcel_id == parcel_id)
        ]

    def for_sale(self, sales_record_id: int) -> list:
        return [e for e in self.entries if e.sales_record_id == sales_record_id]

    def not_attached(self) -> list:
        return [e for e in self.entries if e.state != ATTACHED]

    def attached(self) -> list:
        return [e for e in self.entries if e.state == ATTACHED]


def current_manifest() -> Manifest | None:
    """The manifest of the packet being built, or None outside a packet build."""
    return _current.get()


@contextmanager
def building(manifest: Manifest):
    token = _current.set(manifest)
    try:
        yield manifest
    finally:
        _current.reset(token)


def upload_requirements() -> set[str]:
    """Every attachment a plan section asks for, as `module.question` keys."""
    from certifications.osp_modules import MODULE_REGISTRY
    from certifications.osp_modules.parcel_application import PARCEL_APPLICATION

    keys = set()
    for module in [*MODULE_REGISTRY, PARCEL_APPLICATION]:
        for page in module.pages:
            for question in page.questions:
                if question.kind == "upload":
                    keys.add(f"{module.key}.{question.key}")
    return keys


def _ext(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1]) if "." in (name or "") else ""


def _safe(title: str, fallback: str) -> str:
    return (title or fallback).replace("/", "-")[:60]


def requirement_path(requirement: str, doc) -> str:
    """Where a requirement-matched upload rides in the ZIP. Label artwork has its own folder."""
    name = f"{doc.pk}-{_safe(doc.title, 'file')}{_ext(doc.file.name)}"
    if requirement == LABEL_REQUIREMENT:
        return f"labels/{name}"
    module_key, _, question_key = requirement.partition(".")
    return f"attachments/{module_key}/{question_key}/{name}"


def sale_path(doc) -> str:
    return f"audit-trail/sale-{doc.sales_record_id}/{doc.pk}-{_safe(doc.title, 'source')}{_ext(doc.file.name)}"


def _read(open_file) -> tuple[bytes | None, str]:
    """(bytes, "") or (None, why). Never raises."""
    try:
        with open_file() as fh:
            data = fh.read()
    except Exception as exc:  # noqa: BLE001 — a storage failure is reported, never raised
        logger.warning("Packet attachment could not be read: %s", exc)
        return None, "could not be read from storage"
    if not data:
        return None, "the stored file is empty"
    return data, ""


def _candidates(osp):
    """(Attachment without bytes, opener) for every file the packet should carry, in the order
    the size budget is spent: the files that rode before this module first."""
    from certifications.services.osp_module_pdf import _parcel_map_upload, parcel_map_documents
    from certifications.services.parcel_land_history import affidavit_attachment_name
    from documents.models import GeneratedDocument
    from history.models import ChemicalEvent, LabelImage, SoilManagementEvent

    est = osp.establishment
    out = []
    for parcel in est.parcels.order_by("id"):
        maps = parcel_map_documents(parcel)
        if maps:
            doc = maps[0]  # the newest map is the one the Parcel Application names
            out.append(
                (
                    Attachment(
                        "parcel_map",
                        f"Map for {parcel.name}",
                        f"parcels/maps/{_parcel_map_upload(parcel)}",
                        requirement=PARCEL_MAP_REQUIREMENT,
                        parcel_id=parcel.pk,
                        source_id=f"doc:{doc.pk}",
                    ),
                    lambda doc=doc: doc.file.open("rb"),
                )
            )
    from certifications.services.certified_parcel_branch import CERTIFICATE_SECTION, CONTINUITY_SECTION, document_path

    for parcel in est.parcels.order_by("id"):
        for section, folder, label in (
            (CERTIFICATE_SECTION, "certificates", "Certificate copy"),
            (CONTINUITY_SECTION, "continuity", "Verification of no lapse"),
        ):
            docs = list(parcel.documents.filter(linked_section=section).order_by("-created_at")[:1])
            for doc in docs:
                out.append(
                    (
                        Attachment(
                            folder.rstrip("s"),
                            f"{label} for {parcel.name}",
                            document_path(doc, folder),
                            parcel_id=parcel.pk,
                            source_id=f"doc:{doc.pk}",
                        ),
                        lambda doc=doc: doc.file.open("rb"),
                    )
                )
    for parcel in est.parcels.order_by("id"):
        for aff in parcel.landowner_affidavits.all():
            name = affidavit_attachment_name(aff)
            if name:
                out.append(
                    (
                        Attachment(
                            "affidavit",
                            f"Signed affidavit for {parcel.name}",
                            f"parcels/affidavits/{name}",
                            source_id=f"affidavit:{aff.pk}",
                        ),
                        lambda aff=aff: aff.signed_document.open("rb"),
                    )
                )
    receipts = {}
    for model in (ChemicalEvent, SoilManagementEvent):
        for event in model.objects.filter(
            history__parcel__establishment=est, receipt_document__isnull=False
        ).select_related("receipt_document"):
            receipts[event.receipt_document_id] = event.receipt_document
    for doc in receipts.values():
        out.append(
            (
                Attachment(
                    "receipt",
                    doc.title or "Receipt",
                    f"receipts/{doc.pk}-{_safe(doc.title, 'receipt')}{_ext(doc.file.name)}",
                    source_id=f"doc:{doc.pk}",
                ),
                lambda doc=doc: doc.file.open("rb"),
            )
        )
    requirements = upload_requirements() - {PARCEL_MAP_REQUIREMENT}
    for doc in (
        GeneratedDocument.objects.filter(establishment=est, requirement__in=requirements)
        .exclude(requirement="")
        .order_by("requirement", "-created_at")
    ):
        out.append(
            (
                Attachment(
                    "requirement",
                    doc.title or "Uploaded file",
                    requirement_path(doc.requirement, doc),
                    requirement=doc.requirement,
                    sales_record_id=doc.sales_record_id,
                    source_kind=doc.source_kind,
                    source_id=f"doc:{doc.pk}",
                ),
                lambda doc=doc: doc.file.open("rb"),
            )
        )
    for doc in (
        GeneratedDocument.objects.filter(establishment=est, sales_record__isnull=False)
        .select_related("sales_record")
        .order_by("sales_record_id", "created_at")
    ):
        out.append(
            (
                Attachment(
                    "sale_source",
                    doc.title or "Source document",
                    sale_path(doc),
                    sales_record_id=doc.sales_record_id,
                    source_kind=doc.source_kind,
                    requirement=doc.requirement,
                    source_id=f"doc:{doc.pk}",
                ),
                lambda doc=doc: doc.file.open("rb"),
            )
        )
    for doc in GeneratedDocument.objects.filter(establishment=est, source="lot_tag").order_by("-created_at"):
        out.append(
            (
                Attachment(
                    "lot_tag",
                    doc.title or "Lot tag sheet",
                    f"labels/lot-tags/{doc.pk}-{_safe(doc.title, 'lot-tag')}{_ext(doc.file.name)}",
                    source_id=f"doc:{doc.pk}",
                ),
                lambda doc=doc: doc.file.open("rb"),
            )
        )
    for label in LabelImage.objects.filter(history__parcel__establishment=est).select_related("gallery_image"):
        image = label.gallery_image
        if image is None:
            continue
        stored = image.image.name if image.image else (image.s3_key or "")
        if not stored:
            continue

        def opener(image=image, stored=stored):
            if image.image:
                return image.image.open("rb")
            from django.core.files.storage import default_storage

            return default_storage.open(stored, "rb")

        out.append(
            (
                Attachment(
                    "label_photo",
                    f"Label photo ({label.get_label_type_display()}), {label.history.name}",
                    f"labels/photos/{label.pk}{_ext(stored)}",
                    source_id=f"label:{label.pk}",
                ),
                opener,
            )
        )
    return out


def build_manifest(osp, budget: int | None = None) -> Manifest:
    """Read every candidate once and decide its state. Never raises."""
    budget = budget if budget is not None else getattr(settings, "PACKET_ATTACHMENT_BUDGET_BYTES", _DEFAULT_BUDGET)
    manifest = Manifest()
    try:
        candidates = _candidates(osp)
    except Exception:  # noqa: BLE001 — the packet builds without attachments rather than not at all
        logger.exception("Packet attachments could not be listed for OSP %s", getattr(osp, "pk", None))
        return manifest
    used = 0
    kept: dict[str, Attachment] = {}
    for entry, opener in candidates:
        # One document can be reachable twice: a receipt also uploaded for a requirement, a file
        # uploaded for a requirement AND linked to a sale. It is read, charged to the budget and
        # written ONCE, under the first route's path; the second route's links are merged onto
        # that entry so a lookup by requirement or by sale finds the one copy (review of back #81:
        # the dedup keyed on the path, which differs between routes, so it never fired).
        key = entry.source_id or entry.zip_path
        if key in kept:
            first = kept[key]
            first.requirement = first.requirement or entry.requirement
            first.sales_record_id = first.sales_record_id or entry.sales_record_id
            first.source_kind = first.source_kind or entry.source_kind
            first.parcel_id = first.parcel_id or entry.parcel_id
            continue
        kept[key] = entry
        data, why = _read(opener)
        if data is None:
            entry.state, entry.detail = UNREADABLE, why
        elif used + len(data) > budget:
            entry.state = HELD_OUTSIDE_PACKET
            entry.size = len(data)
            entry.detail = "kept in Trazo's document store; the packet's size limit was reached"
        else:
            entry.state, entry.size, entry.data = ATTACHED, len(data), data
            used += len(data)
        manifest.entries.append(entry)
    return manifest


def state_words(entry: Attachment) -> str:
    """The sentence a certifier reads for one file."""
    if entry.state == ATTACHED:
        return f"{entry.label}: {entry.zip_path}"
    return f"{entry.label}: not in this packet ({entry.detail})"
