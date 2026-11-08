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
    kind: str  # parcel_map | affidavit | handler_certificate | facility_layout | supplier_certificate | supplier_affidavit | brand_owner_document | receipt | requirement | sale_source | lot_tag | label_photo | material_label | notice_document | annual_update_document | inspection_document
    label: str
    zip_path: str
    state: str = ATTACHED
    detail: str = ""
    requirement: str = ""
    parcel_id: int | None = None
    #: The parcel's name, beside its id: the question index names parcels, and a per-parcel upload
    #: answered only by this file lost its parcel there (packet specimen with maps, 2026-10-31).
    parcel: str = ""
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

    def for_source(self, source_id: str) -> list:
        return [e for e in self.entries if e.source_id == source_id]

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


def safe_title(title: str, fallback: str) -> str:
    """A document title as a ZIP filename part: at most 60 characters, cut at a word boundary.

    A plain `[:60]` cut mid-word and could leave a trailing space ("…, Bottom Groun.pdf",
    "River Block .pdf"), which read as a broken name on the page that cites the path.
    """
    text = " ".join((title or fallback).replace("/", "-").split())
    if len(text) > 60:
        head = text[:61]
        text = (head.rsplit(" ", 1)[0] if " " in head else text[:60]).rstrip(" ,;:-")
    return text or fallback


def requirement_path(requirement: str, doc) -> str:
    """Where a requirement-matched upload rides in the ZIP. Label artwork has its own folder."""
    name = f"{doc.pk}-{safe_title(doc.title, 'file')}{_ext(doc.file.name)}"
    if requirement == LABEL_REQUIREMENT:
        return f"labels/{name}"
    module_key, _, question_key = requirement.partition(".")
    return f"attachments/{module_key}/{question_key}/{name}"


def sale_path(doc) -> str:
    return f"audit-trail/sale-{doc.sales_record_id}/{doc.pk}-{safe_title(doc.title, 'source')}{_ext(doc.file.name)}"


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
    from history.models import LabelImage
    from history.services.record_receipts import establishment_receipts

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
                        parcel=parcel.name,
                        source_id=f"doc:{doc.pk}",
                    ),
                    lambda doc=doc: doc.file.open("rb"),
                )
            )
    from certifications.services.certified_parcel_branch import (
        CERTIFICATE,
        CERTIFICATE_SECTION,
        CONTINUITY,
        CONTINUITY_SECTION,
        assess_for_plan,
        document_path,
    )

    for parcel in est.parcels.order_by("id"):
        # Only what the parcel's route shows on its page: an uncertified parcel, or a route that does not
        # list the item, ships no file nobody names (review of back #86).
        route = assess_for_plan(parcel, osp)
        shown = {i.key for i in route.items} if route is not None else set()
        for key, section, folder, label in (
            (CERTIFICATE, CERTIFICATE_SECTION, "certificates", "Certificate copy"),
            (CONTINUITY, CONTINUITY_SECTION, "continuity", "Verification of no lapse"),
        ):
            if key not in shown:
                continue
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
    # The organic certificate of each off-farm handler or storage facility, when the plan prints the
    # facility table (CCOF G6.1 C3 and G6.2 A2, OTCO C7 7.10-3 ask for it attached).
    if facility_table_shown(osp):
        for facility in est.post_harvest_facilities.exclude(operated_by="this_operation").order_by("id"):
            if facility.cert_document:
                out.append(
                    (
                        Attachment(
                            "handler_certificate",
                            f"Organic certificate of {facility.name}",
                            f"handlers/{facility.pk}-{safe_title(facility.name, 'handler')}"
                            f"{_ext(facility.cert_document.name)}",
                            source_id=facility_certificate_source(facility),
                        ),
                        lambda facility=facility: facility.cert_document.open("rb"),
                    )
                )
    # The manufacturer's ingredient statement of each multi-ingredient product on a facility's product table
    # (CCOF G6.1 C2), when the plan prints the table that lists that facility.
    from certifications.models import FacilityProduct
    from certifications.services import facility_products as fp

    shown = {"another_operation": facility_table_shown(osp), "this_operation": own_facility_table_shown(osp)}
    statements = (
        FacilityProduct.objects.filter(
            facility__establishment=est,
            multi_ingredient="yes",
            ingredient_statement_document__isnull=False,
        )
        .select_related("facility", "ingredient_statement_document")
        .order_by("facility_id", "pk")
    )
    for product in statements:
        if not shown.get(product.facility.operated_by):
            continue
        out.append(
            (
                Attachment(
                    "ingredient_statement",
                    fp.ingredient_statement_label(product),
                    fp.ingredient_statement_path(product),
                    source_id=fp.ingredient_statement_source(product),
                ),
                lambda doc=product.ingredient_statement_document: doc.file.open("rb"),
            )
        )
    # The layout of each of the operation's own facilities (OTCO C7 7.2-1), when the plan prints the own-facility
    # table on G6.4 or G6.2.
    if own_facility_table_shown(osp):
        for facility in est.post_harvest_facilities.filter(operated_by="this_operation").order_by("id"):
            if facility.layout_document:
                out.append(
                    (
                        Attachment(
                            "facility_layout",
                            f"Layout of {facility.name}",
                            f"facilities/{facility.pk}-{safe_title(facility.name, 'facility')}-layout"
                            f"{_ext(facility.layout_document.name)}",
                            source_id=facility_layout_source(facility),
                        ),
                        lambda facility=facility: facility.layout_document.open("rb"),
                    )
                )
    # The organic certificate copy G3.0a names for each seedling supplier (CCOF G3.0 A2, OTCO C3
    # 3.1-2, WSDA 2121-B 1/1a), when the plan prints the supplier panel. Keyed on the document, so a
    # copy also uploaded for `seedlings_upload` is read and written once.
    if seedling_suppliers_shown(osp):
        from history.services.supplier_certificates import seedling_suppliers

        for row in seedling_suppliers(est):
            cert = row["certificate"]
            if cert is None:
                continue
            ident = row["supplier"]["id"] if row["supplier"] else "x"
            out.append(
                (
                    Attachment(
                        "supplier_certificate",
                        f"Organic certificate of {row['name']}, issued {cert.issued_on.isoformat()}",
                        f"suppliers/{ident}-{safe_title(row['name'], 'supplier')}-{cert.issued_on.isoformat()}"
                        f"{_ext(cert.document.file.name)}",
                        source_id=supplier_certificate_source(cert),
                    ),
                    lambda doc=cert.document: doc.file.open("rb"),
                )
            )
    # Each sourcing supplier's newest certificate (or, uncertified, its Exempt Handler Affidavit) that
    # G6.5 names (CCOF G6.5 A1/A2), when the plan asks about sourcing. Keyed on the document, so a copy
    # the seedling panel also names is written once.
    from certifications.services import sourced_products as sp

    if sp.sourcing_shown(osp):
        for row in sp.sourcing_rows(est):
            document = row["document"]
            if document is None:
                continue
            supplier = row["supplier"]
            kind = "certificate" if supplier.organic_status == "certified" else "exempt-handler-affidavit"
            out.append(
                (
                    Attachment(
                        "supplier_certificate" if kind == "certificate" else "supplier_affidavit",
                        f"{'Organic certificate' if kind == 'certificate' else 'Exempt Handler Affidavit'} of "
                        f"{supplier.name}",
                        f"suppliers/{supplier.pk}-{safe_title(supplier.name, 'supplier')}-{kind}"
                        f"{_ext(document.file.name)}",
                        source_id=sp.document_source(document),
                    ),
                    lambda doc=document: doc.file.open("rb"),
                )
            )
    # Each brand owner's certificate (or, uncertified, the agent's agreement) that G7.0 page C names
    # (CCOF G7.0 C2, OTCO C8 8.3-2, WSDA N 7), when the plan prints that page.
    from certifications.services import brand_owners as bo

    if bo.brand_owners_shown(osp):
        for row in bo.brand_owner_rows(est):
            document = row["document"]
            if document is None:
                continue
            owner = row["owner"]
            kind = "certificate" if owner.certification_status == "certified" else "agreement"
            out.append(
                (
                    Attachment(
                        "brand_owner_document",
                        f"{'Organic certificate' if kind == 'certificate' else 'Agreement'} of {owner.name}",
                        f"brand-owners/{owner.pk}-{safe_title(owner.name, 'brand-owner')}-{kind}"
                        f"{_ext(document.file.name)}",
                        source_id=bo.document_source(document),
                    ),
                    lambda doc=document: doc.file.open("rb"),
                )
            )
    # The record's receipt field AND files filed on the record (a traceback "Fix it here" upload),
    # same farm only: see `record_receipts`.
    for doc in establishment_receipts(est):
        out.append(
            (
                Attachment(
                    "receipt",
                    doc.title or "Receipt",
                    f"receipts/{doc.pk}-{safe_title(doc.title, 'receipt')}{_ext(doc.file.name)}",
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
                    f"labels/lot-tags/{doc.pk}-{safe_title(doc.title, 'lot-tag')}{_ext(doc.file.name)}",
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
    # The label or container photo of each material on THIS plan's list (OTCO C11 11.1). Keyed on the
    # document, like a receipt: the same file uploaded for a requirement is written once.
    for entry in osp.plan_material_entries.filter(label_document__isnull=False).select_related("label_document"):
        doc = entry.label_document
        if not doc.file:
            continue
        out.append(
            (
                Attachment(
                    "material_label",
                    f"Label of {entry.product_name}",
                    material_label_path(entry),
                    source_id=material_label_source(entry),
                ),
                lambda doc=doc: doc.file.open("rb"),
            )
        )
    # The file filed with a § 205.400(f) notice: for a field removal, the map of the new boundaries
    # WSDA AGR 2516 asks for. It was a writable field nothing uploaded to and no packet carried
    # (register root cause `change-notification-attachment-dead`); 03 names it by this path.
    from certifications.services.osp_module_pdf import lineage_change_notifications

    for notice in lineage_change_notifications(osp):
        if notice.supporting_document:
            out.append(
                (
                    Attachment(
                        "notice_document",
                        f"Supporting document, {notice.get_change_category_display()}",
                        notice_document_path(notice),
                        parcel_id=notice.parcel_id,
                        source_id=f"notice:{notice.pk}",
                    ),
                    lambda notice=notice: notice.supporting_document.open("rb"),
                )
            )
    # The files the year's § 205.406(a) revisions name as support for their (a)(1) summary. 02 and
    # each revision under annual-update/ print these same paths, frozen into the filed copies. So
    # the entry has a source id of its own, not `doc:<pk>`: a file that is also a parcel map or a
    # receipt is written twice rather than merged onto the other route's path, because a filed
    # document's stated path cannot follow a later dedup and the map's page names its own path.
    # Every revision of the year, not only the current one: a superseded revision names its own.
    from certifications.services.annual_update_filing import renewal_packet_filing, year_revisions

    seen_docs = set()
    for revision in year_revisions(renewal_packet_filing(osp)):
        for link in revision.supporting_links.select_related("document").order_by("created_at", "id"):
            doc = link.document
            if doc.pk in seen_docs or not doc.file:
                continue
            seen_docs.add(doc.pk)
            out.append(
                (
                    Attachment(
                        "annual_update_document",
                        f"Supporting document for the {revision.reporting_year} annual update: "
                        f"{doc.title or 'Untitled document'}",
                        annual_update_document_path(doc),
                        source_id=f"annual-update-doc:{doc.pk}",
                    ),
                    lambda doc=doc: doc.file.open("rb"),
                )
            )
    # The certifier inspection record behind 02s (inspection reports, the agent's letters, the
    # response files, resolution notices). Guarded on its own: an error listing these must not
    # empty the manifest of every other file (build_manifest returns nothing on an exception).
    try:
        out.extend(_inspection_candidates(osp))
    except Exception:  # noqa: BLE001
        logger.exception("Inspection-record attachments could not be listed for OSP %s", getattr(osp, "pk", None))
    return out


def material_label_source(entry) -> str:
    """The label's document, the same key any other route to that file uses."""
    return f"doc:{entry.label_document_id}"


def material_label_path(entry) -> str:
    return (
        f"attachments/materials/{entry.pk}-{safe_title(entry.product_name, 'label')}"
        f"{_ext(entry.label_document.file.name)}"
    )


def supplier_certificate_source(certificate) -> str:
    """The copy's document, the same key a requirement upload of that file uses."""
    return f"doc:{certificate.document_id}"


def seedling_suppliers_shown(osp) -> bool:
    """Whether G3.0a prints the supplier panel: the module is not attested not applicable."""
    entry = ((osp.module_responses or {}).get("modules") or {}).get("g3_1_seedlings") or {}
    return not entry.get("not_applicable")


def annual_update_document_path(doc) -> str:
    """Where a file supporting an annual update rides in the ZIP. 02 prints this same path, frozen
    into the filed copy, so it is built only from what never changes on a document: its id and its
    stored file's extension. Not the title, which stays editable on the Documents page; a rename
    after filing would otherwise ship the file under a name the signed 02 does not cite (review of
    back #262)."""
    return f"annual-update/supporting/{doc.pk}{_ext(doc.file.name)}"


def facility_certificate_source(facility) -> str:
    return f"facility:{facility.pk}"


def facility_layout_source(facility) -> str:
    return f"facility-layout:{facility.pk}"


#: The questions that print the facility table (the `post_harvest_facilities` embed).
_FACILITY_TABLES = (
    ("g6_1_harvest_transport", "off_farm_handler_table"),
    ("g6_2_storage", "off_farm_storage_table"),
)


#: The questions that print the operation's own facilities (the `on_farm_facilities` embed).
_OWN_FACILITY_TABLES = (
    ("g6_4_handling", "on_farm_facility_table"),
    ("g6_2_storage", "on_farm_storage_table"),
)


def own_facility_table_shown(osp) -> bool:
    """Whether the plan prints the own-facility table anywhere; a layout ships only beside the line that names
    its facility, as a certificate does."""
    return _any_question_shown(osp, _OWN_FACILITY_TABLES)


def _any_question_shown(osp, pairs) -> bool:
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.conditions import visible_questions

    modules = (osp.module_responses or {}).get("modules") or {}
    for module_key, question_key in pairs:
        entry = modules.get(module_key) or {}
        if entry.get("not_applicable"):
            continue
        answers = entry.get("answers") or {}
        if any(q.key == question_key for _page, q in visible_questions(MODULES_BY_KEY[module_key], answers)):
            return True
    return False


def facility_table_shown(osp) -> bool:
    """Whether the plan prints the facility table anywhere. A certificate ships only beside the line
    that names it: a plan that never shows the table names no facility (review of back #86)."""
    from certifications.osp_modules import MODULES_BY_KEY
    from certifications.osp_modules.conditions import visible_questions

    modules = (osp.module_responses or {}).get("modules") or {}
    for module_key, question_key in _FACILITY_TABLES:
        answers = (modules.get(module_key) or {}).get("answers") or {}
        if any(q.key == question_key for _page, q in visible_questions(MODULES_BY_KEY[module_key], answers)):
            return True
    return False


def inspection_document_source(doc) -> str:
    """One key per stored file across every inspection route: a file named twice ships once."""
    return f"inspection-doc:{doc.pk}"


def inspection_document_path(prefix: str, doc) -> str:
    """Where an inspection record's file rides in the ZIP: `inspections/<prefix>-<doc id><ext>`.
    Built from the document id and the stored file's extension only, never the editable title."""
    return f"inspections/{prefix}-{doc.pk}{_ext(doc.file.name)}"


def _inspection_candidates(osp) -> list:
    """The files behind what 02s lists from the certifier inspection record: each listed
    inspection's report, and each listed item's letter, response files and resolution notice."""
    from certifications.services.certifier_notices import packet_records

    _latest, inspections, notices = packet_records(osp.establishment)
    out = []

    def add(label, prefix, doc):
        if doc is None or not doc.file:
            return
        out.append(
            (
                Attachment(
                    "inspection_document",
                    label,
                    inspection_document_path(prefix, doc),
                    source_id=inspection_document_source(doc),
                ),
                lambda doc=doc: doc.file.open("rb"),
            )
        )

    for inspection in inspections:
        add(f"Inspection report, {inspection.inspected_on.isoformat()}", "report", inspection.report_document)
    for notice in notices:
        add(f"Certifying agent's letter: {notice.get_kind_display()}", "letter", notice.notice_document)
        for link in notice.response_links.all():
            add("Supporting document sent with the operation's response", "response", link.document)
        add("Certifying agent's resolution notice", "resolution", notice.resolution_document)
    return out


def notice_document_path(notice) -> str:
    """Where a notice's supporting document sits in the ZIP. 03 prints this same path."""
    return f"notices/{notice.pk}-{notice.change_category.replace('_', '-')}{_ext(notice.supporting_document.name)}"


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
