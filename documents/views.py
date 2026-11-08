"""
DMS endpoints (WS-3) — nested under /companies/{c}/establishments/{e}/documents/.

Read = any company member; writes ride the standard ReadOnlyForViewers gate. Deletion
is refused for anything the system generated — those rows are dated history (a dossier
generated last March is a record of what existed last March). Downloads stream through
an authenticated action rather than exposing storage URLs.
"""

from django.db import connection
from django.db.models import BooleanField, Q
from django.db.models.expressions import RawSQL
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from backend.permissions import CompanyNestedViewSet
from documents.services.filing import file_document
from subscriptions.storage_utils import CATEGORY_DOCUMENTS, check_storage_quota

from .models import GeneratedDocument
from .serializers import RECEIPT_RECORD_MESSAGE, DocumentUploadSerializer, GeneratedDocumentSerializer


def _codes_matching(choices, term):
    """The stored codes whose code or display label contains `term`, case-insensitively.

    Matched in Python against the fixed choice list rather than in SQL: the label lives only
    in the model, never in a column, and a farmer types what the page SHOWS ("bill of lading",
    "Audit dossier"), not the snake_case code.
    """
    needle = term.casefold()
    return [code for code, label in choices if needle in code.casefold() or needle in label.casefold()]


def _like_contains(term):
    """`term` as an ILIKE "contains" pattern with its own wildcards escaped (backslash escape).

    Without this a search for "%" or "_" is a wildcard and returns the whole shelf.
    """
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _apply_search(qs, term):
    """One search term matched against title, tags, document kind and source label.

    Tags are matched element by element (`jsonb_array_elements_text`), not with
    `tags__icontains`: that casts the whole JSON value to text, so a search for `"` or `,`
    or `[` would hit every tagged document. The CASE keeps a malformed non-array value (the
    column is a bare JSONField; the serializer is the only thing that makes it a list) from
    raising "cannot extract elements from a scalar" and taking the whole list down with it.
    One correlated subquery per row inside the same SELECT, so no extra queries.
    """
    tags_col = f"{connection.ops.quote_name(qs.model._meta.db_table)}.{connection.ops.quote_name('tags')}"
    tag_match = RawSQL(
        "EXISTS (SELECT 1 FROM jsonb_array_elements_text("
        f"CASE WHEN jsonb_typeof({tags_col}) = 'array' THEN {tags_col} ELSE '[]'::jsonb END"
        ") AS tag(value) WHERE tag.value ILIKE %s ESCAPE '\\')",
        [_like_contains(term)],
        output_field=BooleanField(),
    )
    model = qs.model
    return qs.alias(search_tag_match=tag_match).filter(
        Q(title__icontains=term)
        | Q(search_tag_match=True)
        | Q(source_kind__in=_codes_matching(model.SOURCE_KIND_CHOICES, term))
        | Q(source__in=_codes_matching(model.SOURCE_CHOICES, term))
    )


#: Plan statuses whose material links do not hold a label file: neither can be edited again.
MATERIAL_LABEL_RELEASED_STATUSES = ("superseded", "withdrawn")


class GeneratedDocumentViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    serializer_class = GeneratedDocumentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = GeneratedDocument.objects.filter(
            establishment_id=self.kwargs.get("establishment_pk"),
            establishment__company=self.company,
        ).select_related("created_by", "parcel", "history")
        folder = self.request.query_params.get("folder")
        if folder:
            qs = qs.filter(folder=folder)
        source = self.request.query_params.get("source")
        if source:
            qs = qs.filter(source=source)
        linked_section = self.request.query_params.get("linked_section")
        if linked_section:
            qs = qs.filter(linked_section=linked_section)
        requirement = self.request.query_params.get("requirement")
        if requirement:
            qs = qs.filter(requirement=requirement)
        sales_record = self.request.query_params.get("sales_record")
        if sales_record:
            qs = qs.filter(sales_record_id=sales_record)
        # The documents filed against one activity record (event detail view). Both halves or
        # neither: an event id alone is ambiguous across the 8 event tables.
        event_type = self.request.query_params.get("event_type")
        event_id = self.request.query_params.get("event_id")
        if event_type or event_id:
            try:
                qs = qs.filter(event_type=int(event_type), event_id=int(event_id))
            except (TypeError, ValueError):
                raise ValidationError({"event_id": "Filter by event_type and event_id together, as integers."})
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = _apply_search(qs, search)
        return qs

    @staticmethod
    def _resolve_link(pk, establishment, kind):
        """Resolve an optional production / parcel link, scoped to this establishment.

        Returns None when nothing was sent. Raises rather than silently dropping an id the
        caller supplied: an upload that quietly loses its link looks filed and is not, and the
        farmer finds out at inspection.
        """
        if pk in (None, ""):
            return None
        if kind == "history":
            from history.models import History

            obj = History.objects.filter(pk=pk, parcel__establishment=establishment).first()
        elif kind == "sales_record":
            from history.models import SalesRecord

            obj = SalesRecord.objects.filter(pk=pk, production__parcel__establishment=establishment).first()
        else:
            from product.models import Parcel

            obj = Parcel.objects.filter(pk=pk, establishment=establishment).first()
        if obj is None:
            raise ValidationError({kind: f"No {kind} with id {pk} belongs to this farm."})
        return obj

    @staticmethod
    def _resolve_event(event_type, event_id, establishment):
        """Resolve an optional activity-record link, scoped to this establishment.

        Same contract as `_resolve_link`: nothing sent returns None, an id that is not this
        farm's is a 400 that says so. The error does not distinguish "no such event" from
        "another farm's event", so the endpoint is not an existence oracle for foreign ids.
        """
        if event_type is None or event_id is None:
            return None
        from history.constants import EVENT_TYPE_TO_MODEL

        model = EVENT_TYPE_TO_MODEL[event_type]
        event = (
            model.objects.filter(pk=event_id, history__parcel__establishment=establishment)
            .select_related("history")
            .first()
        )
        if event is None:
            raise ValidationError({"event_id": f"No activity record with id {event_id} belongs to this farm."})
        return event

    def create(self, request, *args, **kwargs):
        """Farmer upload — multipart. Generated rows are created only by filing.py."""
        upload = DocumentUploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        payload = upload.validated_data
        f = payload["file"]

        # Storage gate.
        #
        # This endpoint had no gate at all: `check_storage_quota` was wired into the three
        # gallery upload paths in `common/views.py` and nowhere else, so a farm at 100% of
        # its photo quota could still upload unlimited PDFs. The DMS shipped a second door
        # and only the first one had a lock.
        #
        # The DOCUMENTS category never refuses on quota — see
        # `subscriptions.storage_accounting` for why (immutable generated rows, no storage
        # add-on to sell, and a refused certificate during renewal week is the failure the
        # paid tier exists to prevent). What it DOES catch is the case that has nothing to
        # do with how full the farm is: no subscription, or a plan with no storage at all.
        # The size ceiling lives on the serializer, per file.
        allowed, error_detail = check_storage_quota(
            request.user,
            f.size or 0,
            category=CATEGORY_DOCUMENTS,
            # Scoped explicitly: this endpoint already knows which company it is serving, so
            # it must not let the helper fall back to "the user's first active company".
            company=self.company,
        )
        if not allowed:
            return Response(error_detail, status=413)

        establishment = get_object_or_404(self.company.establishment_set.all(), pk=self.kwargs.get("establishment_pk"))

        # Context links are resolved against THIS establishment, never taken on trust from the
        # body. An unscoped lookup would let one farm file a document against another farm's
        # production, and the certifier packet reads these links.
        history = self._resolve_link(payload.get("history"), establishment, "history")
        parcel = self._resolve_link(payload.get("parcel"), establishment, "parcel")
        sales_record = self._resolve_link(payload.get("sales_record"), establishment, "sales_record")
        event = self._resolve_event(payload.get("event_type"), payload.get("event_id"), establishment)
        if event is not None:
            # A record belongs to exactly one season. Naming a different one is a contradiction
            # the server cannot settle, so it refuses; naming none files it under the record's.
            if history is not None and history.pk != event.history_id:
                raise ValidationError({"event_id": "This activity record belongs to a different production."})
            history = event.history
            if payload.get("source_kind") == "receipt":
                from history.services.record_receipts import is_receipt_record

                # The serializer let a production record through by type; only a seed purchase
                # takes a receipt. Checked here, after the farm scope above, so a foreign id never
                # reaches this question.
                if not is_receipt_record(payload.get("event_type"), event):
                    raise ValidationError({"source_kind": RECEIPT_RECORD_MESSAGE})

        doc = file_document(
            establishment=establishment,
            source="upload",
            folder=payload.get("folder") or "uploads",
            title=(payload.get("title") or f.name)[:255],
            filename=f.name,
            history=history,
            parcel=parcel,
            # Streamed, not `f.read()`. The old form pulled the entire file into memory
            # before a byte reached storage, on an endpoint that had no size cap either.
            file_obj=f,
            content_type=getattr(f, "content_type", "") or "",
            linked_section=payload.get("linked_section") or "",
            requirement=payload.get("requirement") or "",
            sales_record=sales_record,
            source_kind=payload.get("source_kind") or "",
            event_type=payload.get("event_type") if event is not None else None,
            event_id=event.pk if event is not None else None,
            created_by=request.user,
            tags=payload.get("tags") or [],
        )
        if doc is None:
            raise ValidationError({"file": "Upload could not be stored. Try again."})
        return Response(GeneratedDocumentSerializer(doc).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        """Only farmer-managed labels are editable — title and tags. The artifact,
        its folder, and its provenance are frozen at filing time."""
        doc = self.get_object()
        allowed = {k: v for k, v in request.data.items() if k in ("title", "tags")}
        if not allowed:
            raise ValidationError({"detail": "Only 'title' and 'tags' can be edited."})
        serializer = self.get_serializer(doc, data=allowed, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        doc = self.get_object()
        if not doc.is_deletable:
            raise ValidationError(
                {
                    "detail": (
                        "Generated documents are dated records and cannot be deleted. "
                        "Only your own uploads can be removed."
                    )
                }
            )
        if doc.supplier_certificates.exists():
            # Checked before the file goes: the row is PROTECTed, and deleting the stored file first
            # would leave a certificate pointing at nothing.
            raise ValidationError(
                {
                    "detail": "This file is a supplier's organic certificate copy. Remove it from the supplier first.",
                    # The app says it in the reader's language, keyed on this.
                    "code": "supplier_certificate_in_use",
                }
            )
        if doc.supplier_affidavits.exists():
            # A supplier's Exempt Handler Affidavit: the link is PROTECT, like its certificates.
            raise ValidationError(
                {
                    "detail": "This file is a supplier's Exempt Handler Affidavit. Remove it from the supplier first.",
                    "code": "supplier_affidavit_in_use",
                }
            )
        if doc.brand_owner_certificates.exists() or doc.brand_owner_agreements.exists():
            # Same reason as a supplier copy: both brand-owner links are PROTECT.
            raise ValidationError(
                {
                    "detail": "This file is a brand owner's certificate or agreement copy. Remove it from the brand "
                    "owner first.",
                    "code": "brand_owner_document_in_use",
                }
            )
        if doc.facility_ingredient_statements.exists():
            # A product's ingredient statement (CCOF G6.1 C2): the link is PROTECT, like a brand owner's copy.
            raise ValidationError(
                {
                    "detail": "This file is a product's ingredient statement. Remove it from the product first.",
                    "code": "ingredient_statement_in_use",
                }
            )
        if doc.material_labels.exclude(osp__status__in=MATERIAL_LABEL_RELEASED_STATUSES).exists():
            # Same reason: the label of a material on a plan's materials list (OTCO C11 11.1), PROTECT.
            # Only a plan the operator can still change (or one under review, which becomes editable
            # when the review ends) holds the file: "remove it from the material first" is an answer
            # there. A superseded or withdrawn version cannot be edited, so its link is released
            # below instead of holding the file forever (review of back #292).
            raise ValidationError(
                {
                    "detail": "This file is the label of a material on a materials list. Remove it from the material "
                    "first.",
                    "code": "material_label_in_use",
                }
            )
        if doc.inspection_reports.exists():
            # PROTECT, like a supplier copy: the farm's record of an inspection names this report.
            raise ValidationError(
                {
                    "detail": "This file is the report of a recorded inspection. Remove it from the inspection first.",
                    "code": "inspection_document_in_use",
                }
            )
        if (
            doc.certifier_notice_letters.exists()
            or doc.certifier_notice_resolutions.exists()
            or doc.certifier_notice_response_links.exists()
        ):
            # The agent's letter, its resolution notice, or a file sent with the response: PROTECT or
            # RESTRICT on every link.
            raise ValidationError(
                {
                    "detail": "This file belongs to an item from the certifying agent. Remove it from that item first.",
                    "code": "notice_document_in_use",
                }
            )
        if doc.annual_update_links.exists():
            # Same reason: a § 205.406(a) filing names this file as support for its summary, and a
            # signed filing's list of documents is part of what was signed (RESTRICT on the link).
            raise ValidationError(
                {
                    "detail": (
                        "This file supports an annual update. Remove it from the update first; a signed "
                        "or filed update keeps it."
                    ),
                    "code": "annual_update_attachment_in_use",
                }
            )
        # Every refusal above has passed: release the links of versions nobody can edit any more, so
        # PROTECT does not refuse the delete. Their filed packets keep the bytes they were filed with.
        doc.material_labels.update(label_document=None)
        doc.file.delete(save=False)
        doc.delete()
        return Response(status=204)

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, **kwargs):
        doc = self.get_object()
        if not doc.file:
            raise Http404("Document has no file")
        response = FileResponse(doc.file.open("rb"), content_type=doc.content_type or "application/octet-stream")
        filename = doc.file.name.rsplit("/", 1)[-1]
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
