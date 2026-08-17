"""
DMS endpoints (WS-3) — nested under /companies/{c}/establishments/{e}/documents/.

Read = any company member; writes ride the standard ReadOnlyForViewers gate. Deletion
is refused for anything the system generated — those rows are dated history (a dossier
generated last March is a record of what existed last March). Downloads stream through
an authenticated action rather than exposing storage URLs.
"""

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
from .serializers import DocumentUploadSerializer, GeneratedDocumentSerializer


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
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(title__icontains=search)
        return qs

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
        doc = file_document(
            establishment=establishment,
            source="upload",
            folder=payload.get("folder") or "uploads",
            title=(payload.get("title") or f.name)[:255],
            filename=f.name,
            # Streamed, not `f.read()`. The old form pulled the entire file into memory
            # before a byte reached storage, on an endpoint that had no size cap either.
            file_obj=f,
            content_type=getattr(f, "content_type", "") or "",
            linked_section=payload.get("linked_section") or "",
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
