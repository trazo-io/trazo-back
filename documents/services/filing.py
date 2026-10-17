"""
The single filing seam (WS-3).

Every generator view that produces a certifier-bound artifact on an EXPLICIT user
action calls `file_document()` with the bytes it is about to stream, then streams them
unchanged. One seam means: one place that decides folders, one place the packet
builder (WS-2.6) plugs into, and no generator ever grows its own persistence logic.

Filing failures must never break the download the farmer asked for — the artifact in
hand beats the archive copy. Failures log loudly and the response proceeds.
"""

from __future__ import annotations

import logging

from django.core.files import File
from django.core.files.base import ContentFile

from documents.models import GeneratedDocument

logger = logging.getLogger(__name__)


def file_document(
    *,
    establishment,
    source: str,
    folder: str,
    title: str,
    filename: str,
    content: bytes | None = None,
    file_obj=None,
    content_type: str = "",
    linked_section: str = "",
    parcel=None,
    history=None,
    created_by=None,
    tags=None,
    requirement: str = "",
    sales_record=None,
    source_kind: str = "",
    event_type: int | None = None,
    event_id: int | None = None,
) -> GeneratedDocument | None:
    """Persist one generated artifact (or upload) into the DMS. Returns the row, or
    None when filing failed (logged; caller streams the artifact regardless).

    Pass EITHER `content` (bytes already in memory — every generator holds the PDF/ZIP
    it is about to stream, so there is nothing to save by streaming it) OR `file_obj`
    (an uploaded file, streamed to storage in chunks).

    `file_obj` exists because the upload path used to do `content=f.read()`: the whole
    file into RAM before a single byte reached storage, on an endpoint with no size cap.
    Django's `FieldFile.save` writes a `File` through `.chunks()`, so handing it the
    upload directly keeps peak memory at one chunk regardless of file size.
    """
    try:
        # Checked INSIDE the try, deliberately.
        #
        # This module's contract is that filing never breaks the download — "failures log
        # loudly and the response proceeds". A `raise` here sat outside the try and broke
        # exactly that: a caller who forgot the kwarg would take down the generator view it
        # was filing for, which is the one thing the whole try/except exists to prevent.
        # `logger.exception` below is the "loudly"; the stack trace names the bad call site.
        if (content is None) == (file_obj is None):
            raise ValueError("file_document() takes exactly one of `content` or `file_obj`")

        if file_obj is not None:
            payload = File(file_obj, name=filename)
            size_bytes = getattr(file_obj, "size", None)
            if size_bytes is None:
                size_bytes = payload.size
        else:
            payload = ContentFile(content)
            size_bytes = len(content)

        doc = GeneratedDocument(
            establishment=establishment,
            source=source,
            folder=folder,
            title=title[:255],
            content_type=content_type,
            size_bytes=size_bytes,
            linked_section=linked_section or "",
            parcel=parcel,
            history=history,
            requirement=requirement or "",
            sales_record=sales_record,
            source_kind=source_kind or "",
            event_type=event_type,
            event_id=event_id,
            created_by=created_by if getattr(created_by, "is_authenticated", False) else None,
            tags=list(tags or []),
        )
        doc.file.save(filename, payload, save=True)
        return doc
    except Exception:
        logger.exception(
            "DMS filing failed (source=%s, establishment=%s) — download proceeds without an archive copy",
            source,
            getattr(establishment, "pk", None),
        )
        return None
