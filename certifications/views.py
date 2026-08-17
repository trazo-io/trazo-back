import logging
import threading

from django.db import connections, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.text import slugify

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from backend.permissions import CompanyNestedViewSet
from subscriptions.gating import require_compliance_exports

from .models import (
    AdjoiningLandAffidavit,
    ApprovedInputChangeLog,
    Certification,
    CertifierAccessLink,
    CertifierAccessLog,
    LandownerAffidavit,
    NationalListSubstance,
    OMRIProduct,
    OrganicSystemPlan,
    OSPAnnualUpdate,
    OSPChangeNotification,
    StateOrganicRegistration,
)
from .serializers import (
    AdjoiningLandAffidavitSerializer,
    CertificationSerializer,
    CertifierAccessLinkSerializer,
    LandownerAffidavitSerializer,
    OrganicSystemPlanListSerializer,
    OrganicSystemPlanSerializer,
    OSPAnnualUpdateSerializer,
    OSPChangeNotificationSerializer,
    StateOrganicRegistrationSerializer,
)
from .services.common_osp_records import RECORD_TYPES_BY_KEY, confirm, derive_record_types, summarize
from .services.common_osp_workbooks import WORKBOOKS_BY_KEY, build_workbook, workbook_summary
from .services.omri_verifier import OMRIProductVerifier

logger = logging.getLogger(__name__)


# Farmer-facing phrasing for OSP.status, for use inside a sentence. The model's
# own get_status_display() strings ("Draft (not yet submitted)", "Active /
# Approved") are label text for a select box and read badly mid-sentence. These
# messages surface verbatim in the app's error toasts, so they name the state and
# the next action — never an endpoint path.
_OSP_STATUS_PHRASE = {
    "draft": "a draft",
    "submitted": "submitted to your certifier",
    "active": "approved and active",
    "superseded": "superseded by a newer version",
    "withdrawn": "withdrawn",
}


def osp_status_phrase(osp_status):
    return _OSP_STATUS_PHRASE.get(osp_status, f"in status '{osp_status}'")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def verify_input(request):
    """
    NOP input verifier — Sprint 3.

    Query params:
      name    (required)  Chemical/amendment commercial name to verify.
      omri_id (optional)  Farmer-supplied OMRI product ID for direct lookup.

    Returns a JSON payload with the VerificationResult plus the matched
    NationalListSubstance / OMRIProduct primary keys the frontend can assign
    to ChemicalEvent.omri_product / .national_list_substance.
    """
    name = request.query_params.get("name", "").strip()
    omri_id = request.query_params.get("omri_id", "").strip() or None

    if not name and not omri_id:
        return Response(
            {"error": "Provide 'name' and/or 'omri_id' query parameter."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    verifier = OMRIProductVerifier()
    result = verifier.verify(operation_name=name, certification_number=omri_id)

    # Re-resolve the matched objects so the frontend can POST the FK pk back.
    # We resolve OMRI, WSDA, and NL independently so the typeahead can surface
    # whichever matches exist — a product like Neptune's Harvest may be on both
    # OMRI and WSDA catalogs (CCOF treats WSDA as co-equal), while an elemental
    # substance like copper hydroxide may have no brand listing but a strong
    # NL hit. The UI renders all three independently and the farmer picks.
    from certifications.models import WSDAMaterial
    from certifications.services.omri_verifier import _normalize, _resolve_omri_by_name, _resolve_wsda_by_name

    matched_omri = None
    matched_nl = None
    matched_wsda = None
    if omri_id:
        matched_omri = OMRIProduct.objects.filter(omri_id__iexact=omri_id).first()
    if matched_omri is None and name:
        matched_omri = _resolve_omri_by_name(name)

    if name:
        matched_wsda = _resolve_wsda_by_name(name)

        normalized = _normalize(name)
        nl = NationalListSubstance.objects.filter(substance_name_normalized=normalized).first()
        if not nl:
            # Pass 1 — farmer pasted a full label that CONTAINS a NL substance
            # name (e.g., "Kocide 3000 (Copper Hydroxide 46.1%)" contains
            # "copper hydroxide"). Drift detector uses the same rule.
            forward_candidates = [
                n
                for n in NationalListSubstance.objects.values_list("substance_name_normalized", flat=True)
                if len(n) >= 5 and n in normalized
            ]
            if forward_candidates:
                best = max(forward_candidates, key=len)
                nl = NationalListSubstance.objects.filter(substance_name_normalized=best).first()
        if not nl and len(normalized) >= 3:
            # Pass 2 — farmer typed a SHORT query that is contained inside a
            # NL substance name (e.g., "copper" -> "copper hydroxide"). This
            # only runs in the farmer-facing verifier, NOT in the drift
            # detector, which stays strict to avoid false positives at save-
            # time. When multiple NL entries contain the query we return the
            # shortest (most specific single-word) match to bias toward the
            # farmer's likely intent.
            reverse_candidates = list(
                NationalListSubstance.objects.filter(substance_name_normalized__contains=normalized).values_list(
                    "id", "substance_name_normalized"
                )
            )
            if reverse_candidates:
                best_id = min(reverse_candidates, key=lambda pair: (len(pair[1]), pair[0]))[0]
                nl = NationalListSubstance.objects.filter(pk=best_id).first()
        matched_nl = nl

    return Response(
        {
            "found": result.found,
            "status": result.status,
            "confidence_score": result.confidence_score,
            "notes": result.notes,
            "certifier_name": result.certifier_name,
            "source_url": result.source_url,
            "omri_product_pk": matched_omri.pk if matched_omri else None,
            "omri_product_id": matched_omri.omri_id if matched_omri else None,
            "omri_product_name": matched_omri.product_name if matched_omri else None,
            "national_list_substance_pk": matched_nl.pk if matched_nl else None,
            "national_list_substance_name": matched_nl.substance_name if matched_nl else None,
            "national_list_cfr_section": matched_nl.cfr_section if matched_nl else None,
            "national_list_status": matched_nl.status if matched_nl else None,
            # WSDA Materials List — co-equal with OMRI per CCOF. See
            # feedback_input_source_catalogs for why checking WSDA is required
            # for a realistic false-positive rate on US organic crops.
            "wsda_material_pk": matched_wsda.pk if matched_wsda else None,
            "wsda_material_id": matched_wsda.wsda_id if matched_wsda else None,
            "wsda_material_name": matched_wsda.brand_name if matched_wsda else None,
            "wsda_material_category": matched_wsda.category if matched_wsda else None,
        }
    )


class CertificationViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """CRUD + manual verification for establishment certifications."""

    serializer_class = CertificationSerializer

    def get_queryset(self):
        return Certification.objects.filter(
            establishment_id=self.kwargs.get("establishment_pk"),
            establishment__company=self.company,
        ).select_related("establishment")

    def perform_create(self, serializer):
        certification = serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user,
        )
        self._trigger_background_verification(certification)

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"])
    def verify(self, request, **kwargs):
        """Manually trigger re-verification."""
        certification = self.get_object()
        self._trigger_background_verification(certification)
        return Response(
            {"status": "verification_initiated", "certification_id": certification.id},
            status=status.HTTP_202_ACCEPTED,
        )

    def _trigger_background_verification(self, certification):
        """Trigger verification in background thread (MVP pattern)."""

        def _bg_verify(cert_id):
            try:
                connections.close_all()
                from .services.verification_manager import VerificationManager

                cert = Certification.objects.get(id=cert_id)
                manager = VerificationManager()
                manager.verify_certification(cert)
            except Exception as e:
                logger.error(f"Background verification failed for cert {cert_id}: {e}")
            finally:
                connections.close_all()

        transaction.on_commit(
            lambda: threading.Thread(
                target=_bg_verify,
                args=(certification.id,),
                daemon=True,
            ).start()
        )


# ---------------------------------------------------------------------------
# Sprint 5A — OSP / Annual Update / Landowner Affidavit ViewSets
# ---------------------------------------------------------------------------


class OrganicSystemPlanViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """
    CRUD + lifecycle actions for Organic System Plans (7 CFR 205.201).

    Nested under /companies/{company_pk}/establishments/{establishment_pk}/osps/.

    Lifecycle actions:
      POST /osps/{id}/submit/       — mark status='submitted' (stamps submitted_at)
      POST /osps/{id}/activate/     — mark status='active', supersede prior version
      POST /osps/{id}/new_version/  — clone this OSP into a draft vNext
    """

    lookup_field = "pk"

    def get_serializer_class(self):
        if self.action == "list":
            return OrganicSystemPlanListSerializer
        return OrganicSystemPlanSerializer

    def get_queryset(self):
        return (
            OrganicSystemPlan.objects.filter(
                establishment_id=self.kwargs.get("establishment_pk"),
                establishment__company=self.company,
            )
            .select_related("establishment", "certification", "previous_version")
            .prefetch_related(
                "approved_national_list_substances",
                "approved_omri_products",
                "approved_wsda_materials",
                "approved_input_changes__changed_by",
            )
        )

    def perform_create(self, serializer):
        establishment_id = self.kwargs["establishment_pk"]
        # Version numbers are monotonic per establishment. Compute next number
        # inside a transaction so concurrent creates can't collide.
        with transaction.atomic():
            last = (
                OrganicSystemPlan.objects.select_for_update()
                .filter(establishment_id=establishment_id)
                .order_by("-version_number")
                .first()
            )
            next_version = (last.version_number + 1) if last else 1
            serializer.save(
                establishment_id=establishment_id,
                created_by=self.request.user,
                version_number=next_version,
                previous_version=last,
            )

    def perform_update(self, serializer):
        """
        Block edits to OSPs that have already left 'draft' status. Once an OSP
        is submitted or active, it is an attested record — the farmer must
        start a new version via POST /new-version/ rather than mutate history.
        This is the digital-recordkeeping equivalent of not ripping pages out
        of a certifier's binder (21 CFR Part 11 trustworthy records principle).
        """
        osp = serializer.instance
        if osp.status != "draft":
            raise ValidationError(
                {
                    "status": (
                        f"This plan is {osp_status_phrase(osp.status)}, so it can no longer be "
                        "edited — it is the record your certifier reviewed. Start a new version "
                        "to make changes: it copies everything across and leaves this one intact."
                    )
                }
            )
        # WS-2.3 — a client PATCH of `sections` writes MANUAL text only. Whatever the
        # client sends as `narrative` is normalized into `narrative_manual` (generated
        # prose has exactly one author: the compiler), then the composed narrative is
        # rebuilt so every downstream reader of `narrative` stays coherent.
        if "sections" in serializer.validated_data:
            from certifications.services.osp_module_compiler import (
                compile_modules_to_sections,
                normalize_incoming_sections,
            )

            normalized = normalize_incoming_sections(osp.sections, serializer.validated_data["sections"])
            merged = dict(osp.sections or {})
            merged.update(normalized)
            serializer.validated_data["sections"] = merged
            instance = serializer.save()
            compile_modules_to_sections(instance)
            instance.save(update_fields=["sections", "updated_at"])
            return
        serializer.save()

    # Minimum narrative length to consider a § 205.201(a) section materially filled.
    # Kept in sync with AuditExportService.OSP_NARRATIVE_MATERIAL_FLOOR (400 chars)
    # so the submit gate and the audit PDF apply the same bar. Research basis:
    # real CCOF/Oregon Tilth OSP sections average 150-500 words — 400 chars (~70
    # words) is the floor below which a narrative would be flagged as a
    # Notice-of-Noncompliance item per 7 CFR 205.662(c).
    OSP_NARRATIVE_MATERIAL_FLOOR = 400

    def _missing_osp_sections(self, osp):
        """Return the list of § 205.201(a)(1)-(6) section keys that are blank,
        too brief, or padded.

        Length alone was gameable: "Test " repeated to 602 characters cleared
        the floor here and let a padded OSP reach 'submitted' and 'active',
        while the audit dossier — which does check padding — kept stamping it
        DRAFT / DO-NOT-SUBMIT. The farmer got a green submit and a red PDF with
        nothing explaining the difference. Same detector, same answer.
        """
        from certifications.models import OSP_SECTION_KEYS
        from history.services.audit_export_service import looks_like_padding

        missing = []
        for key in OSP_SECTION_KEYS:
            section = (osp.sections or {}).get(key, {}) or {}
            narrative = (section.get("narrative") or "").strip()
            if len(narrative) < self.OSP_NARRATIVE_MATERIAL_FLOOR or looks_like_padding(narrative):
                missing.append(key)
        return missing

    @action(detail=True, methods=["post"])
    def submit(self, request, **kwargs):
        """
        Transition OSP from 'draft' to 'submitted' and freeze an immutable
        PDF snapshot of the content.

        Validates that every § 205.201(a)(1)-(6) section has a substantive
        narrative (≥ OSP_NARRATIVE_MATERIAL_FLOOR chars). On success:
          1. Sets status='submitted' + submitted_at
          2. Generates `submission_pdf` — the exact content the certifier
             receives — and saves it to the OSP. Future edits are blocked
             by the perform_update guard, so this PDF is effectively
             tamper-evident (hashable for inspector verification).

        This is not a real transmission integration yet — the farmer
        downloads the PDF and forwards it to their certifier. Email/webhook
        delivery is a follow-up capability. But the artifact IS real.
        """
        osp = self.get_object()
        if osp.status != "draft":
            return Response(
                {
                    "error": (
                        f"This plan is {osp_status_phrase(osp.status)}, so there is nothing to "
                        "submit. Only a draft can be sent to your certifier."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        # WS-2.3 — idempotent recompile so the submitted narrative (and its frozen
        # snapshot PDF) reflects the final module answers, not the last PUT's view.
        from certifications.services.osp_module_compiler import compile_modules_to_sections

        if compile_modules_to_sections(osp):
            osp.save(update_fields=["sections", "updated_at"])
        missing = self._missing_osp_sections(osp)
        if missing:
            return Response(
                {
                    "error": "OSP is incomplete",
                    "missing_sections": missing,
                    "detail": (
                        f"Each § 205.201(a) section needs a substantive narrative "
                        f"(at least {self.OSP_NARRATIVE_MATERIAL_FLOOR} characters, "
                        "roughly 70 words). Real CCOF/Oregon Tilth templates average "
                        "150–500 words per section. Complete the sections listed "
                        "below before submitting to the certifier."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        from django.core.files.base import ContentFile
        from django.utils import timezone as dj_tz

        from .services.osp_pdf_snapshot import generate_osp_snapshot_pdf

        # Submission is atomic: a 'submitted' OSP MUST carry its immutable snapshot
        # PDF (the exact artifact the certifier receives). If snapshot generation
        # fails, roll the status change back and fail loudly rather than leave a
        # 'submitted' OSP with no snapshot — a silent gap the inspector can't detect.
        try:
            with transaction.atomic():
                osp.status = "submitted"
                osp.submitted_at = dj_tz.now()
                # Save FIRST so submitted_at is in the PDF.
                osp.save(update_fields=["status", "submitted_at", "updated_at"])

                pdf_bytes = generate_osp_snapshot_pdf(osp)
                filename = f"osp_v{osp.version_number}_{osp.public_id}_" f"{osp.submitted_at.date().isoformat()}.pdf"
                osp.submission_pdf.save(filename, ContentFile(pdf_bytes), save=True)

                # WS-3: the frozen snapshot also lands on the farm's document shelf.
                from documents.services.filing import file_document

                file_document(
                    establishment=osp.establishment,
                    source="osp_snapshot",
                    folder="organic_system_plan",
                    title=f"OSP v{osp.version_number} submission snapshot",
                    filename=filename,
                    content=pdf_bytes,
                    content_type="application/pdf",
                    created_by=request.user,
                )
        except Exception as e:
            logger.error(f"OSP snapshot PDF generation failed for OSP {osp.id}: {e}")
            return Response(
                {
                    "error": "OSP submission failed",
                    "detail": (
                        "Could not generate the immutable OSP snapshot PDF, so the submission was "
                        "rolled back (the OSP is still 'draft'). Please try again; if it persists, "
                        "contact support."
                    ),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(OrganicSystemPlanSerializer(osp).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, **kwargs):
        """
        Mark this OSP active — the farmer's certifier has approved it and
        issued an updated certificate.

        Preconditions:
          - status == 'submitted'
          - approval_document is attached (certifier's approval letter / signed OSP)
          - approval_certificate_number is set
          - approval_certifier_name is set

        These preconditions prevent a farmer from self-flipping an OSP to
        'active' without actual certifier involvement — which would
        undermine the § 205.400 certification workflow.

        The fields can be set via PATCH /osps/{id}/ BEFORE calling activate,
        OR via multipart POST directly to /activate/ (files supported).
        """
        osp = self.get_object()
        if osp.status != "submitted":
            return Response(
                {
                    "error": (
                        f"This plan is {osp_status_phrase(osp.status)}, so its approval cannot "
                        "be recorded yet. It must be submitted to your certifier first — then "
                        "come back and record their approval here."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Accept approval evidence inline on this request (multipart or JSON).
        # Multipart: approval_document as a file, plus cert_number + certifier_name.
        approval_doc = request.FILES.get("approval_document")
        cert_number = request.data.get("approval_certificate_number") or request.POST.get("approval_certificate_number")
        certifier_name = request.data.get("approval_certifier_name") or request.POST.get("approval_certifier_name")

        if approval_doc:
            osp.approval_document = approval_doc
        if cert_number:
            osp.approval_certificate_number = cert_number
        if certifier_name:
            osp.approval_certifier_name = certifier_name

        # Re-check evidence (either set inline or already on the record).
        missing_evidence = []
        if not osp.approval_document:
            missing_evidence.append("approval_document")
        if not osp.approval_certificate_number:
            missing_evidence.append("approval_certificate_number")
        if not osp.approval_certifier_name:
            missing_evidence.append("approval_certifier_name")
        if missing_evidence:
            return Response(
                {
                    "error": "Certifier approval evidence is required",
                    "missing_evidence": missing_evidence,
                    "detail": (
                        "Activating an OSP records that a USDA-accredited certifier "
                        "has reviewed and approved it. Upload the certifier's "
                        "approval letter / signed OSP and provide the issued "
                        "certificate number + certifier name."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone as dj_tz

        with transaction.atomic():
            # Supersede the current active version, if any.
            OrganicSystemPlan.objects.filter(establishment=osp.establishment, status="active").exclude(
                pk=osp.pk
            ).update(status="superseded", updated_at=dj_tz.now())
            osp.status = "active"
            osp.approved_at = dj_tz.now()
            if not osp.effective_date:
                osp.effective_date = dj_tz.now().date()
            osp.save(
                update_fields=[
                    "status",
                    "approved_at",
                    "effective_date",
                    "approval_document",
                    "approval_certificate_number",
                    "approval_certifier_name",
                    "updated_at",
                ]
            )
        # Activation changes which OSP the drift detector reads (via the
        # active-OSP lookup in drift_detector._current_active_osp). Existing
        # ChemicalEvent / SoilManagementEvent drift_warnings were computed
        # against the prior active OSP (or against "no OSP"). Recompute so
        # stale warnings from the old scope are cleared and new drift under
        # the new scope is surfaced immediately.
        self._recompute_drift_for_establishment(osp.establishment_id)
        return Response(OrganicSystemPlanSerializer(osp).data)

    # ------------------------------------------------------------------
    # Sprint 5.1 — approved-inputs management for the drift detector.
    # ------------------------------------------------------------------

    def _normalize_input_kind(self, kind: str) -> str:
        mapping = {
            "national_list": "national_list",
            "nl": "national_list",
            "omri": "omri",
            "omri_product": "omri",
            "wsda": "wsda",
            "wsda_material": "wsda",
        }
        if kind not in mapping:
            raise ValidationError({"kind": "Must be 'national_list', 'omri', or 'wsda'."})
        return mapping[kind]

    def _resolve_input(self, kind: str, pk):
        """Fetch the linked catalog row by pk. Raises if missing."""
        if kind == "national_list":
            try:
                return NationalListSubstance.objects.get(pk=pk)
            except NationalListSubstance.DoesNotExist:
                raise ValidationError({"id": f"NationalListSubstance {pk} not found."})
        if kind == "wsda":
            from certifications.models import WSDAMaterial

            try:
                return WSDAMaterial.objects.get(pk=pk)
            except WSDAMaterial.DoesNotExist:
                raise ValidationError({"id": f"WSDAMaterial {pk} not found."})
        try:
            return OMRIProduct.objects.get(pk=pk)
        except OMRIProduct.DoesNotExist:
            raise ValidationError({"id": f"OMRIProduct {pk} not found."})

    # Approved-inputs edits are gated by OSP status. Rationale: the submission
    # PDF snapshot (osp_pdf_snapshot.py) is generated on transition to
    # 'submitted' and is the immutable artifact the certifier reviews. Allowing
    # edits to approved_inputs after submission would let a farmer silently
    # expand the approved-substances scope without the certifier ever seeing
    # it — bypassing the § 205.400 review. Edits are permitted on drafts
    # (pre-submission drafting) and on active OSPs (change-notifications per
    # 7 CFR 205.400(f)(2) arrive over the year and must be recorded).
    _APPROVED_INPUTS_EDITABLE_STATUSES = {"draft", "active"}

    def _ensure_approved_inputs_editable(self, osp):
        if osp.status not in self._APPROVED_INPUTS_EDITABLE_STATUSES:
            raise ValidationError(
                {
                    "status": (
                        f"This plan is {osp_status_phrase(osp.status)}, so its approved-inputs "
                        "list is locked until that review finishes. Wait for your certifier to "
                        "approve the plan, or start a new version now to revise the list."
                    )
                }
            )

    @action(detail=True, methods=["post"], url_path="add-approved-input")
    def add_approved_input(self, request, **kwargs):
        """
        Attach a NationalListSubstance or OMRIProduct to this OSP's approved
        inputs. Payload: { "kind": "national_list" | "omri", "id": <pk>,
        "change_notification_reference": "<optional>", "notes": "<optional>" }.

        Drives the drift detector: once attached, future ChemicalEvent /
        SoilManagementEvent saves referencing this input will not raise a
        drift_warning.

        Writes an ApprovedInputChangeLog row inside an atomic block so the
        M2M mutation and the audit record are always consistent.
        """
        osp = self.get_object()
        self._ensure_approved_inputs_editable(osp)
        kind = self._normalize_input_kind((request.data.get("kind") or "").strip())
        target_id = request.data.get("id")
        if target_id in (None, ""):
            raise ValidationError({"id": "id is required."})
        target = self._resolve_input(kind, target_id)
        ref = (request.data.get("change_notification_reference") or "").strip()
        notes = (request.data.get("notes") or "").strip()

        with transaction.atomic():
            if kind == "national_list":
                osp.approved_national_list_substances.add(target)
                target_name = target.substance_name
            elif kind == "wsda":
                osp.approved_wsda_materials.add(target)
                target_name = target.brand_name
            else:
                osp.approved_omri_products.add(target)
                target_name = target.product_name

            log_kwargs = dict(
                osp=osp,
                kind=kind,
                target_name_at_change=target_name,
                action=ApprovedInputChangeLog.ACTION_ADDED,
                changed_by=request.user if request.user.is_authenticated else None,
                change_notification_reference=ref,
                notes=notes,
            )
            if kind == "national_list":
                log_kwargs["target_national_list"] = target
            elif kind == "wsda":
                log_kwargs["target_wsda"] = target
            else:
                log_kwargs["target_omri"] = target
            ApprovedInputChangeLog.objects.create(**log_kwargs)

        # Recompute drift warnings on this establishment's existing events —
        # adding an input may clear warnings that were raised for it.
        self._recompute_drift_for_establishment(osp.establishment_id)

        # Re-fetch so serializer reflects the freshly prefetched relations.
        osp.refresh_from_db()
        return Response(OrganicSystemPlanSerializer(osp).data)

    @action(detail=True, methods=["get", "post"], url_path="change-notifications")
    def change_notifications(self, request, **kwargs):
        """
        List (GET) or record (POST) OSP Notification-of-Changes entries —
        7 CFR 205.400(f) / NOP 2615 §3.4.

        POST payload: { "change_category": <enum>, "description": "...",
        "date_notified": "YYYY-MM-DD" (optional), "method": "verbal"|"written"
        (optional), "documentation_timing": <enum> (optional) }.
        supporting_document may be included as multipart.
        """
        osp = self.get_object()
        if request.method == "GET":
            qs = osp.change_notifications.all()
            return Response(OSPChangeNotificationSerializer(qs, many=True).data)

        serializer = OSPChangeNotificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            osp=osp,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"change-notifications/(?P<notification_id>\d+)",
    )
    def delete_change_notification(self, request, notification_id=None, **kwargs):
        """
        Withdraw a Notification-of-Changes entry that the certifier has NOT yet
        acknowledged — 7 CFR 205.400(f).

        The panel was append-only with no edit and no delete, so a mistyped
        entry ("tetretertertertrtret" on the demo farm) rode into the certifier
        dossier permanently with no way to correct it. Approved inputs are
        removable; change notifications were not, for no stated reason.

        Once `certifier_acknowledged_at` is set the entry is a record of what
        was communicated to a third party and stays frozen — correcting THAT is
        a new notification, not an edit of the old one.
        """
        osp = self.get_object()
        notification = osp.change_notifications.filter(pk=notification_id).first()
        if notification is None:
            return Response(
                {"error": "Change notification not found on this OSP."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if notification.certifier_acknowledged_at is not None:
            return Response(
                {
                    "error": (
                        "This notification was already acknowledged by the certifier on "
                        f"{notification.certifier_acknowledged_at}. It cannot be withdrawn — "
                        "record a new notification describing the correction instead."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        notification.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="remove-approved-input")
    def remove_approved_input(self, request, **kwargs):
        """
        Detach an input from approved_inputs. Inverse of add_approved_input.

        Payload: { "kind": "national_list" | "omri", "id": <pk>,
        "change_notification_reference": "<optional>", "notes": "<optional>" }.

        Writes an ApprovedInputChangeLog row (action="removed") inside an
        atomic block alongside the M2M removal.
        """
        osp = self.get_object()
        self._ensure_approved_inputs_editable(osp)
        kind = self._normalize_input_kind((request.data.get("kind") or "").strip())
        target_id = request.data.get("id")
        if target_id in (None, ""):
            raise ValidationError({"id": "id is required."})
        target = self._resolve_input(kind, target_id)
        ref = (request.data.get("change_notification_reference") or "").strip()
        notes = (request.data.get("notes") or "").strip()

        with transaction.atomic():
            if kind == "national_list":
                osp.approved_national_list_substances.remove(target)
                target_name = target.substance_name
            elif kind == "wsda":
                osp.approved_wsda_materials.remove(target)
                target_name = target.brand_name
            else:
                osp.approved_omri_products.remove(target)
                target_name = target.product_name

            log_kwargs = dict(
                osp=osp,
                kind=kind,
                target_name_at_change=target_name,
                action=ApprovedInputChangeLog.ACTION_REMOVED,
                changed_by=request.user if request.user.is_authenticated else None,
                change_notification_reference=ref,
                notes=notes,
            )
            if kind == "national_list":
                log_kwargs["target_national_list"] = target
            elif kind == "wsda":
                log_kwargs["target_wsda"] = target
            else:
                log_kwargs["target_omri"] = target
            ApprovedInputChangeLog.objects.create(**log_kwargs)

        self._recompute_drift_for_establishment(osp.establishment_id)
        osp.refresh_from_db()
        return Response(OrganicSystemPlanSerializer(osp).data)

    def _recompute_drift_for_establishment(self, establishment_id: int):
        """Re-run the drift detector against this establishment's events.

        Cheap: only touches events on this establishment's parcels. Done
        synchronously so the response reflects the updated drift_warning
        counts the frontend UI depends on.
        """
        from history.models import ChemicalEvent, SoilManagementEvent

        from .services.drift_detector import evaluate_chemical_event, evaluate_soil_event

        chem_qs = ChemicalEvent.objects.filter(history__parcel__establishment_id=establishment_id)
        soil_qs = SoilManagementEvent.objects.filter(history__parcel__establishment_id=establishment_id)
        for e in chem_qs.iterator():
            evaluate_chemical_event(e)
        for e in soil_qs.iterator():
            evaluate_soil_event(e)

    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request, **kwargs):
        """
        Clone this OSP into a new draft with version_number=max+1. The frontend
        uses this when the farmer is starting the next year's OSP from last year.
        """
        source = self.get_object()
        with transaction.atomic():
            last = (
                OrganicSystemPlan.objects.select_for_update()
                .filter(establishment=source.establishment)
                .order_by("-version_number")
                .first()
            )
            next_version = (last.version_number + 1) if last else 1
            clone = OrganicSystemPlan.objects.create(
                establishment=source.establishment,
                certification=source.certification,
                version_number=next_version,
                previous_version=source,
                status="draft",
                sections=source.sections,
                # Next season starts guided from last year's answers (Appendix A §h.5).
                module_responses=source.module_responses,
                certifier_template_name=source.certifier_template_name,
                certifier_template_url=source.certifier_template_url,
                created_by=self.request.user,
            )
        return Response(OrganicSystemPlanSerializer(clone).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="record-types")
    def record_types(self, request, **kwargs):
        """
        Common OSP § 11 "Records Maintained" — evidence (GET) and the operator's own
        confirmation (POST).

        GET returns one row per § 11 record type with an evidence verdict derived from what the
        farm has actually logged, plus whether the operator has confirmed it. **Evidence is not
        an answer**: § 205.201(a) makes the producer the author of the plan, so a row is only a
        ticked checkbox once it carries `confirmed: true`. Rows with `suggested: true` are
        evidenced but unconfirmed and must never be rendered as ticked — see the module docstring
        in `services/common_osp_records.py`.

        POST payload: { "keys": ["harvest_records", ...], "confirmed": true|false }.
        This is the ONLY path from evidence to an assertion, and it must stay operator-initiated
        — never called from a signal, seeder, import, or derivation.
        """
        osp = self.get_object()
        establishment = osp.establishment

        if request.method == "GET":
            rows = derive_record_types(establishment, osp=osp)
            return Response({"summary": summarize(rows), "record_types": rows})

        # A submitted/superseded/withdrawn plan is a record of what a third party was already
        # sent — confirming a § 11 box on one would silently change what the certifier received.
        # The panel disables the controls for these statuses; enforce it here too, because a
        # disabled checkbox is a UI courtesy, not an access rule.
        if osp.status not in ("draft", "active"):
            raise ValidationError(
                {
                    "status": (
                        f"This plan is {osp.get_status_display()}. Record types can only be "
                        "confirmed on a draft or active plan — create a new version to make changes."
                    )
                }
            )

        keys = request.data.get("keys")
        if not isinstance(keys, list) or not keys:
            raise ValidationError({"keys": "Provide a non-empty list of record-type keys."})

        unknown = [k for k in keys if k not in RECORD_TYPES_BY_KEY]
        if unknown:
            raise ValidationError({"keys": f"Unknown record type(s): {', '.join(sorted(unknown))}"})

        confirmed = request.data.get("confirmed", True)
        if not isinstance(confirmed, bool):
            raise ValidationError({"confirmed": "Must be a boolean."})

        confirm(osp, keys, user=request.user if request.user.is_authenticated else None, confirmed=confirmed)
        rows = derive_record_types(establishment, osp=osp)
        return Response({"summary": summarize(rows), "record_types": rows})

    @action(detail=True, methods=["get"], url_path="module-pdf")
    def module_pdf(self, request, **kwargs):
        """One module as a certifier-readable PDF (WS-2.5).

        `?module=<key>` — farm-wide module from the registry.
        `?module=parcel_application&parcel=<id>` — one parcel's application,
        rendered from LIVE model state.
        Files a dated copy in the DMS, then streams the same bytes.
        """
        from io import BytesIO

        from django.http import FileResponse

        from certifications.services.osp_module_pdf import generate_module_pdf
        from documents.services.filing import file_document

        osp = self.get_object()
        establishment = osp.establishment
        # Plan gate. The module PDFs are the COMPONENTS of the renewal packet, so gating only the
        # ZIP would leave the whole artifact reassemblable one download at a time — a paywall with
        # a documented way around it is not a paywall.
        require_compliance_exports(establishment.company, user=request.user)
        module_key = request.query_params.get("module")
        if not module_key:
            raise ValidationError({"module": "Required."})

        parcel = None
        if module_key == "parcel_application":
            parcel_id = request.query_params.get("parcel")
            if not parcel_id:
                raise ValidationError({"parcel": "Required for parcel_application."})
            parcel = get_object_or_404(establishment.parcels.all(), pk=parcel_id)

        try:
            data = generate_module_pdf(osp, module_key, parcel=parcel)
        except ValueError as exc:
            raise ValidationError({"module": str(exc)})

        stem = slugify(establishment.name) or "operation"
        suffix = f"-{slugify(parcel.name)}" if parcel is not None else ""
        filename = f"{stem}-osp-v{osp.version_number}-{module_key}{suffix}.pdf"
        file_document(
            establishment=establishment,
            source="module_pdf",
            folder="organic_system_plan",
            title=f"OSP module PDF — {module_key}{f' ({parcel.name})' if parcel else ''}",
            filename=filename,
            content=data,
            content_type="application/pdf",
            created_by=request.user if request.user.is_authenticated else None,
        )
        return FileResponse(BytesIO(data), as_attachment=True, filename=filename)

    @action(detail=True, methods=["get"], url_path="packet")
    def packet(self, request, **kwargs):
        """The renewal packet ZIP (WS-2.6) — cover, narrative, module PDFs,
        one Parcel Application per parcel, four workbooks. Single generator
        function is the DMS seam; this action files and streams its bytes."""
        from io import BytesIO

        from django.http import FileResponse

        from certifications.services.osp_module_pdf import generate_osp_packet
        from documents.services.filing import file_document

        osp = self.get_object()
        establishment = osp.establishment
        # Plan gate, before generating anything. `generate_osp_packet` builds every module PDF,
        # a Parcel Application per parcel and four workbooks — running all of that and then
        # refusing to hand it over would burn the work and file a document (see file_document
        # below) that the farm is not entitled to download.
        require_compliance_exports(establishment.company, user=request.user)
        data = generate_osp_packet(osp)
        stem = slugify(establishment.name) or "operation"
        filename = f"{stem}-osp-v{osp.version_number}-packet.zip"
        file_document(
            establishment=establishment,
            source="packet",
            folder="organic_system_plan",
            title=f"OSP renewal packet — v{osp.version_number}",
            filename=filename,
            content=data,
            content_type="application/zip",
            created_by=request.user if request.user.is_authenticated else None,
        )
        return FileResponse(BytesIO(data), as_attachment=True, filename=filename)

    @action(detail=True, methods=["get"], url_path="attachments")
    def attachments(self, request, **kwargs):
        """
        Common OSP required attachments — the four workbooks.

        Without `?workbook=`, returns a per-workbook summary (row count + how many cells Trazo
        could not fill). With it, downloads that workbook as .xlsx.

        `blank_cells` is work remaining for the operator, not a completeness score: these forms
        are a starting point they review and finish, and Trazo leaves a cell blank rather than
        guessing at an answer on a regulatory attachment.
        """
        from django.http import FileResponse

        osp = self.get_object()
        establishment = osp.establishment

        key = request.query_params.get("workbook")
        if not key:
            return Response({"workbooks": workbook_summary(establishment)})

        if key not in WORKBOOKS_BY_KEY:
            raise ValidationError(
                {"workbook": f"Unknown workbook. Expected one of: {', '.join(sorted(WORKBOOKS_BY_KEY))}"}
            )

        # Plan gate — on the DOWNLOAD branch only.
        #
        # The four Common OSP attachment workbooks are named on the price list as part of what
        # Compliance buys, and this streams them as .xlsx. It was the seventh export door and the
        # one the inventory test originally missed: its route is named "attachments", which
        # matched none of the hint words, so widening those hints was part of the same fix.
        #
        # The `?workbook=`-less branch above is left open deliberately: it returns a per-workbook
        # row count and a count of cells Trazo could not fill. That is a progress figure the
        # operator needs in order to decide whether the packet is worth buying — a number about
        # their own records, not a document they hand to anyone.
        require_compliance_exports(establishment.company, user=request.user)

        spec = WORKBOOKS_BY_KEY[key]
        buffer = build_workbook(establishment, key)
        # WS-3: file a dated copy in the DMS, then stream the same bytes.
        from io import BytesIO

        from documents.services.filing import file_document

        data = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer.read()
        stem = slugify(establishment.name) or "operation"
        file_document(
            establishment=establishment,
            source="workbook",
            folder="organic_system_plan",
            title=f"Common OSP workbook — {spec.filename}",
            filename=f"{stem}-{spec.filename}.xlsx",
            content=data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            created_by=request.user,
        )
        response = FileResponse(
            BytesIO(data),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{stem}-{spec.filename}.xlsx"'
        return response

    @action(detail=True, methods=["get"], url_path="module-definitions")
    def module_definitions(self, request, **kwargs):
        """
        Guided OSP module questionnaire definitions (WS-2.1).

        Returns the full serialized module registry plus `content_version`, both locales
        inline (the wizard picks the locale client-side — module content deliberately does
        not ride the react-intl catalogs, see osp_modules/schema.py).

        OSP-scoped (detail=True) rather than global so a future certifier overlay can key
        off `certifier_template_name` without an API change. The payload is
        definition-only — answers live in `module_responses` and are returned by the
        module actions (WS-2.2), never here.
        """
        from certifications.osp_modules import serialize_registry

        self.get_object()  # 404/permission gate; payload is OSP-independent today
        return Response(serialize_registry())

    # ------------------------------------------------------------------
    # Guided OSP modules — responses (WS-2.2)
    # ------------------------------------------------------------------

    @staticmethod
    def _module_status(entry: dict, module=None) -> str:
        """Status as it stands against the CURRENT questionnaire, not as it was stamped.

        Adding a required question to a shipped module makes every previously-completed
        answer set incomplete. `completed_at` stays in storage — it is the audit record of
        when the operator first completed the module — but reporting "completed" while
        required questions are unanswered would put a green tick on a module a certifier
        will send back. The stamped `definition_version` records which questionnaire the
        answers were given against; this makes the status honest about the current one.

        Downgrades to `in_progress` rather than inventing a status: every surface already
        handles it, and the module genuinely is in progress again.
        """
        if entry.get("not_applicable"):
            return "not_applicable"
        if entry.get("completed_at"):
            if module is not None:
                from certifications.osp_modules.conditions import missing_required

                if missing_required(module, entry.get("answers") or {}):
                    return "in_progress"
            return "completed"
        if entry.get("answers"):
            return "in_progress"
        return "not_started"

    def _module_progress_row(self, module, entry: dict) -> dict:
        from certifications.osp_modules.conditions import progress

        return {
            "key": module.key,
            "code": module.code,
            "status": self._module_status(entry, module),
            "not_applicable": bool(entry.get("not_applicable")),
            "na_attestation": entry.get("na_attestation"),
            "completed_at": entry.get("completed_at"),
            "completed_by": entry.get("completed_by"),
            "definition_version": entry.get("definition_version"),
            "progress": progress(
                module,
                entry.get("answers") or {},
                not_applicable=bool(entry.get("not_applicable")),
            ),
        }

    @action(detail=True, methods=["get"], url_path="modules")
    def modules(self, request, **kwargs):
        """Per-module progress for the module list page (farm-wide modules).

        Per-parcel module rows land with WS-5 (they are computed against live Parcel
        state, not against module_responses — Appendix A §f).
        """
        from certifications.osp_modules import MODULE_REGISTRY

        osp = self.get_object()
        responses = (osp.module_responses or {}).get("modules", {})
        rows = [self._module_progress_row(m, responses.get(m.key) or {}) for m in MODULE_REGISTRY]
        return Response({"modules": rows})

    @action(detail=True, methods=["get", "put"], url_path=r"modules/(?P<module_key>[a-z0-9_]+)")
    def module_detail(self, request, module_key=None, **kwargs):
        """One module's answers — read (GET) and the operator's writes (PUT).

        PUT payload — all keys optional:
          answers          {question_key: value} merged into stored answers; value null
                           deletes the answer. Values are enveloped {"value", "at"} on
                           write; only operator-entered/accepted values ever arrive here
                           (prefill suggestions are resolved on GET and never stored).
          not_applicable   bool — module-level attestation; stamps who/when. Refused for
                           modules that don't allow it.
          complete         true → server-side required-if-visible validation, then stamps
                           completed_at/by. Any later content write clears the stamp — a
                           completed module that changes must be re-completed (the honest
                           version of QO's "re-generate after edits" warning).

        Draft-only, same rule as perform_update: answers on a submitted/active OSP are an
        attested record; changes go through a new version.
        """
        from certifications.osp_modules import CONTENT_VERSION, MODULES_BY_KEY, serialize_module
        from certifications.osp_modules.conditions import (
            exclusive_conflicts,
            invalid_choice_answers,
            invalid_typed_answers,
            missing_required,
            validate_answer_keys,
        )

        module = MODULES_BY_KEY.get(module_key)
        if module is None:
            raise Http404(f"Unknown module '{module_key}'")
        if module.repeat_per_parcel:
            raise ValidationError({"module": "Per-parcel modules are addressed via WS-5 endpoints."})

        if request.method == "GET":
            from certifications.services.osp_prefill import resolve_suggestions

            osp = self.get_object()
            entry = ((osp.module_responses or {}).get("modules", {})).get(module.key) or {}
            return Response(
                {
                    "definition": serialize_module(module),
                    "content_version": CONTENT_VERSION,
                    "response": self._module_progress_row(module, entry),
                    "answers": entry.get("answers") or {},
                    # Evidence → suggestion only. Resolved fresh on every GET, never
                    # stored; the sole path into `answers` is the operator accepting
                    # one in the wizard (§ 205.201(a) — the producer authors the plan).
                    "suggestions": resolve_suggestions(module, osp.establishment),
                }
            )

        with transaction.atomic():
            osp = (
                OrganicSystemPlan.objects.select_for_update()
                .select_related("establishment")
                .get(pk=self.get_object().pk)
            )
            if osp.status != "draft":
                raise ValidationError(
                    {
                        "status": (
                            f"This plan is {osp_status_phrase(osp.status)}, so its answers are "
                            "locked — it is the record your certifier reviewed. Start a new "
                            "version to make changes: it copies your answers across and leaves "
                            "this plan intact."
                        )
                    }
                )

            responses = osp.module_responses or {"schema_version": 1, "modules": {}, "parcel_modules": {}}
            responses.setdefault("modules", {})
            entry = responses["modules"].setdefault(
                module.key,
                {
                    "status": "not_started",
                    "not_applicable": False,
                    "na_attestation": None,
                    "answers": {},
                    "completed_at": None,
                    "completed_by": None,
                    "definition_version": CONTENT_VERSION,
                },
            )
            from django.utils import timezone as dj_tz

            now = dj_tz.now().isoformat()
            user_id = request.user.id if request.user.is_authenticated else None
            content_changed = False

            # Entries cloned or written by earlier shapes may lack keys — never KeyError
            # on a farmer's own data.
            entry.setdefault("answers", {})

            if "answers" in request.data:
                incoming = request.data.get("answers")
                if not isinstance(incoming, dict):
                    raise ValidationError({"answers": "Must be an object of {question_key: value}."})
                unknown = validate_answer_keys(module, incoming)
                if unknown:
                    raise ValidationError({"answers": f"Unknown question key(s): {', '.join(unknown)}"})
                bad = invalid_choice_answers(module, incoming)
                if bad:
                    raise ValidationError(
                        {"answers": {k: f"Value not among the defined options: {v}" for k, v in bad.items()}}
                    )
                mistyped = invalid_typed_answers(module, incoming)
                if mistyped:
                    raise ValidationError({"answers": mistyped})
                conflicted = exclusive_conflicts(module, incoming)
                if conflicted:
                    raise ValidationError(
                        {
                            "answers": {
                                k: (
                                    f"'{v}' is a none-of-the-above option and cannot be "
                                    "combined with other selections."
                                )
                                for k, v in conflicted.items()
                            }
                        }
                    )
                for key, value in incoming.items():
                    if value is None:
                        if key in entry["answers"]:
                            entry["answers"].pop(key)
                            content_changed = True
                    else:
                        previous = (entry["answers"].get(key) or {}).get("value")
                        if previous != value:
                            entry["answers"][key] = {"value": value, "at": now}
                            content_changed = True

            if "not_applicable" in request.data:
                flag = request.data.get("not_applicable")
                if not isinstance(flag, bool):
                    raise ValidationError({"not_applicable": "Must be a boolean."})
                if flag and not module.allows_not_applicable:
                    raise ValidationError(
                        {
                            "not_applicable": (
                                f"Module '{module.key}' has no not-applicable path — its "
                                "questions apply to every operation."
                            )
                        }
                    )
                if flag != bool(entry.get("not_applicable")):
                    content_changed = True
                entry["not_applicable"] = flag
                entry["na_attestation"] = {"by": user_id, "at": now} if flag else None

            # A content change after completion invalidates the completion stamp —
            # the module must be reviewed and completed again.
            if content_changed and entry.get("completed_at") and not request.data.get("complete"):
                entry["completed_at"] = None
                entry["completed_by"] = None

            if request.data.get("complete"):
                stored = entry.get("answers") or {}
                missing = missing_required(
                    module,
                    stored,
                    not_applicable=bool(entry.get("not_applicable")),
                )
                if missing:
                    raise ValidationError(
                        {
                            "complete": ("Required questions are unanswered: " + ", ".join(missing)),
                            "missing": missing,
                        }
                    )
                # Belt: stored answers written before a validator existed must not be
                # sealed into a completion — completion re-checks the whole stored set,
                # not just this request's delta.
                stale_bad = {**invalid_typed_answers(module, stored), **invalid_choice_answers(module, stored)}
                stale_conflicts = exclusive_conflicts(module, stored)
                if stale_bad or stale_conflicts:
                    raise ValidationError(
                        {
                            "complete": "Stored answers need correction before completing.",
                            "invalid": {
                                **stale_bad,
                                **{k: f"conflicts with '{v}'" for k, v in stale_conflicts.items()},
                            },
                        }
                    )
                entry["completed_at"] = now
                entry["completed_by"] = user_id

            entry["definition_version"] = CONTENT_VERSION
            entry["status"] = self._module_status(entry, module)
            osp.module_responses = responses

            # Recompile the § 205.201(a) narratives from the new answers in the same
            # transaction — the sections a certifier reads are never stale relative to
            # module answers (WS-2.3).
            from certifications.services.osp_module_compiler import compile_modules_to_sections

            compile_modules_to_sections(osp)
            osp.save(update_fields=["module_responses", "sections", "updated_at"])

        return Response(
            {
                "response": self._module_progress_row(module, entry),
                "answers": entry.get("answers") or {},
            }
        )


class OSPAnnualUpdateViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """
    CRUD for § 205.406(a) annual continuation filings.

    Nested under /companies/{company_pk}/establishments/{establishment_pk}/osp-annual-updates/.
    """

    serializer_class = OSPAnnualUpdateSerializer
    lookup_field = "pk"

    def get_queryset(self):
        return OSPAnnualUpdate.objects.filter(
            prior_osp__establishment_id=self.kwargs.get("establishment_pk"),
            prior_osp__establishment__company=self.company,
        ).select_related("prior_osp", "new_osp")

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        # Cross-tenant FK guard: prior_osp must belong to THIS establishment. get_queryset only
        # scopes reads; without this a write could reference another operation's OSP. Scoping the
        # field queryset makes a foreign prior_osp fail validation on both create and update.
        est_pk = self.kwargs.get("establishment_pk")
        fields = getattr(serializer, "fields", None)
        if est_pk and fields and "prior_osp" in fields and hasattr(fields["prior_osp"], "queryset"):
            fields["prior_osp"].queryset = OrganicSystemPlan.objects.filter(establishment_id=est_pk)
        return serializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class LandownerAffidavitViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """
    CRUD for landowner affidavits (3-year transition proof, MOFGA FM-2024-20).

    Nested under /companies/{company_pk}/establishments/{establishment_pk}/affidavits/.
    Filter by parcel via ?parcel=<id>.
    """

    serializer_class = LandownerAffidavitSerializer
    lookup_field = "pk"

    def get_queryset(self):
        qs = LandownerAffidavit.objects.filter(
            parcel__establishment_id=self.kwargs.get("establishment_pk"),
            parcel__establishment__company=self.company,
        ).select_related("parcel", "osp")
        parcel_id = self.request.query_params.get("parcel")
        if parcel_id:
            qs = qs.filter(parcel_id=parcel_id)
        return qs

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        # Cross-tenant FK guard: the affidavit's parcel must belong to THIS establishment.
        est_pk = self.kwargs.get("establishment_pk")
        fields = getattr(serializer, "fields", None)
        if est_pk and fields and "parcel" in fields and hasattr(fields["parcel"], "queryset"):
            from product.models import Parcel

            fields["parcel"].queryset = Parcel.objects.filter(establishment_id=est_pk)
        return serializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AdjoiningLandAffidavitViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """CRUD for neighbour-signed adjoining-land attestations (USDA form #25, § 205.202(c)).

    Nested under /companies/{company_pk}/establishments/{establishment_pk}/adjoining-land/.
    Filter by parcel via ?parcel=<id>. Mirrors LandownerAffidavitViewSet, including its
    cross-tenant FK guard — without it a client could attach an attestation to another
    company's parcel by posting a foreign id.
    """

    serializer_class = AdjoiningLandAffidavitSerializer
    lookup_field = "pk"

    def get_queryset(self):
        qs = AdjoiningLandAffidavit.objects.filter(
            parcel__establishment_id=self.kwargs.get("establishment_pk"),
            parcel__establishment__company=self.company,
        ).select_related("parcel")
        parcel_id = self.request.query_params.get("parcel")
        if parcel_id:
            qs = qs.filter(parcel_id=parcel_id)
        return qs

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        est_pk = self.kwargs.get("establishment_pk")
        fields = getattr(serializer, "fields", None)
        if est_pk and fields and "parcel" in fields and hasattr(fields["parcel"], "queryset"):
            from product.models import Parcel

            fields["parcel"].queryset = Parcel.objects.filter(establishment_id=est_pk)
        return serializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class StateOrganicRegistrationViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """
    CRUD for State Organic Program (CDFA SOP) producer registrations.

    Nested under
    /companies/{company_pk}/establishments/{establishment_pk}/state-organic-registrations/.
    """

    serializer_class = StateOrganicRegistrationSerializer
    lookup_field = "pk"

    def get_queryset(self):
        return StateOrganicRegistration.objects.filter(
            establishment_id=self.kwargs.get("establishment_pk"),
            establishment__company=self.company,
        ).select_related("establishment")

    def get_serializer(self, *args, **kwargs):
        serializer = super().get_serializer(*args, **kwargs)
        # Cross-tenant FK guard: the registration's establishment must be THIS one (the URL
        # establishment). Scoping the field queryset blocks a payload that points at another
        # company's establishment on both create and update.
        est_pk = self.kwargs.get("establishment_pk")
        fields = getattr(serializer, "fields", None)
        if est_pk and fields and "establishment" in fields and hasattr(fields["establishment"], "queryset"):
            from company.models import Establishment

            fields["establishment"].queryset = Establishment.objects.filter(pk=est_pk)
        return serializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


# ---------------------------------------------------------------------------
# Certifier review links — anonymous, read-only, revocable
# ---------------------------------------------------------------------------


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _resolve_link_or_404(token):
    """Resolve an ACTIVE link, or raise 404.

    Expired and revoked links deliberately return 404 rather than 410/403: a
    distinct status would confirm to an unauthenticated caller that the token was
    once real, which is information they should not get. The farmer sees the true
    state (expired vs revoked) on their own authenticated dashboard.
    """
    link = CertifierAccessLink.objects.filter(token=token).select_related("establishment").first()
    if link is None or not link.is_active:
        raise Http404("No active certifier review link for this address.")
    return link


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def certifier_review_metadata(request, token):
    """Context for the certifier landing page — no records, just what this link is.

    Kept separate from the dossier download so the certifier sees whose operation
    and which window they are about to open, rather than an unexplained file.
    """
    link = _resolve_link_or_404(token)

    CertifierAccessLog.objects.create(
        link=link,
        action="metadata",
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )

    return Response(
        {
            "operation_name": link.establishment.name,
            "operation_city": link.establishment.city,
            "operation_state": link.establishment.state,
            "certification_type": link.certification_type,
            "period_start": link.period_start,
            "period_end": link.period_end,
            "expires_at": link.expires_at,
            "label": link.label,
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def certifier_review_readiness(request, token):
    """The readiness findings for this link's operation + window, readable without a download.

    Added 2026-08-04. Until now this page's only offer was a PDF — a certifier had to download
    a file to learn anything, which is the download-only experience the "top-tier recordkeeping"
    review flagged: COG Pro's pitch is "your certification provider can inspect your records
    online, with your permission." The token link itself already worked (anonymous, revocable,
    logged); this is what was missing from the PAGE it opens.

    Delegates entirely to `OperationAuditExportService.readiness_rows()`, which walks the exact
    same production set the PDF dossier covers — the page and the PDF cannot disagree about what
    is in scope, because both read the same method.
    """
    from history.services.operation_audit_export_service import OperationAuditExportService

    link = _resolve_link_or_404(token)

    CertifierAccessLog.objects.create(
        link=link,
        action="readiness",
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )

    service = OperationAuditExportService(
        link.establishment,
        certification_type=link.certification_type,
        start_date=link.period_start,
        end_date=link.period_end,
    )
    try:
        productions = service.readiness_rows()
    except Exception:
        # Same posture as the dossier view: a reviewer reading this must never see a raw 500
        # that reads as "this grower's records are broken". Log the real cause for us.
        logger.exception("Certifier readiness rows failed for establishment %s", link.establishment_id)
        return Response(
            {"error": "Readiness details could not be loaded right now. Please try again shortly."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    total_findings = sum(len(p["findings"]) for p in productions)

    return Response(
        {
            "productions": productions,
            "total_findings": total_findings,
            "total_productions": len(productions),
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def certifier_review_dossier(request, token):
    """Stream the operation audit dossier for this link.

    Regenerated on every open, which is the point: a certifier following this link
    always sees current records, where an emailed PDF is stale the moment the
    farmer logs the next event.
    """
    from django.http import FileResponse

    from history.services.operation_audit_export_service import OperationAuditExportService

    link = _resolve_link_or_404(token)

    CertifierAccessLog.objects.create(
        link=link,
        action="dossier",
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )

    service = OperationAuditExportService(
        link.establishment,
        certification_type=link.certification_type,
        start_date=link.period_start,
        end_date=link.period_end,
    )
    try:
        pdf = service.generate_pdf()
    except Exception:
        # This page is read by a certification reviewer judging the farmer's
        # operation. A raw 500 there reads as "this grower's records are broken",
        # so fail with a neutral message and log the real cause for us.
        logger.exception("Certifier dossier generation failed for establishment %s", link.establishment_id)
        return Response(
            {"error": "The dossier could not be generated right now. Please try again shortly."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    filename = f"{slugify(link.establishment.name)}-audit-dossier.pdf"
    return FileResponse(pdf, as_attachment=True, filename=filename, content_type="application/pdf")


class CertifierAccessLinkViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """Farmer-side management of certifier review links.

    Nested under the establishment so tenant isolation comes from
    CompanyNestedViewSet rather than being re-implemented here. Links are created
    and revoked, never edited: changing the window or profile of a link a
    certifier already holds would silently change what they see.
    """

    serializer_class = CertifierAccessLinkSerializer
    # Deliberately does NOT override permission_classes. The inherited
    # CompanyNestedViewSet default is `IsSuperUser | (ReadOnlyForViewers &
    # AuthPermission)`, which checks company membership AND restricts writes to
    # CA/FM — so a VIEWER cannot mint a link that exposes supplier invoices and
    # applicator names. An earlier draft here narrowed this to `IsAuthenticated`
    # and, in doing so, let any authenticated grower read and mint links for
    # somebody else's operation.
    http_method_names = ["get", "post", "delete"]

    def get_queryset(self):
        # `self.establishment` is resolved and tenant-checked by
        # CompanyNestedViewSet.initial — do not re-derive it from kwargs here, or
        # the isolation guarantee moves out of one audited place into many.
        return (
            CertifierAccessLink.objects.filter(establishment=self.establishment)
            .prefetch_related("accesses")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        # Refuse to mint a link over a submission blocker. The dossier already
        # stamps DO-NOT-SUBMIT, but by then the farmer has sent the URL and the
        # reviewer has read it — the moment to stop them is BEFORE sharing, not
        # inside the PDF the certifier also opens.
        from history.services.operation_readiness_service import OperationReadinessService

        # Plan gate first. The certifier link is a Compliance artifact like the packet, and the
        # readiness evaluation below walks the whole operation — no reason to spend that on a
        # request that cannot mint a link anyway. Checked on CREATE only: revoking a link and
        # listing the ones already issued must keep working if a farm lapses to Starter, or
        # lapsing would leave live tokens the grower can see but not withdraw.
        require_compliance_exports(self.establishment.company, user=self.request.user)

        certification_type = serializer.validated_data.get("certification_type", "organic")
        readiness = OperationReadinessService(self.establishment, certification_type).evaluate()
        if not readiness["ready"]:
            raise ValidationError(
                {
                    "readiness": "This operation is not ready to share with a certifier.",
                    "blockers": readiness["blockers"],
                }
            )

        serializer.save(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            created_by=self.request.user,
        )

    @action(detail=False, methods=["get"], url_path="readiness")
    def readiness(self, request, **kwargs):
        """What a certifier would reject this operation over, before anything is shared.

        Powers both the pre-share warning on the sharing card and the
        pre-inspection checklist on the dashboard, so the two can never disagree.
        """
        from history.services.operation_readiness_service import OperationReadinessService

        certification_type = request.query_params.get("certification_type", "organic")
        return Response(OperationReadinessService(self.establishment, certification_type).evaluate())

    def destroy(self, request, *args, **kwargs):
        """DELETE revokes rather than deletes — the access log is evidence of who
        looked at the operation's records and must survive revocation."""
        link = self.get_object()
        link.revoke()
        return Response(self.get_serializer(link).data, status=status.HTTP_200_OK)
