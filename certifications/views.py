import logging
import threading

from django.db import connections, transaction

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from backend.permissions import CompanyNestedViewSet

from .models import (
    ApprovedInputChangeLog,
    Certification,
    LandownerAffidavit,
    NationalListSubstance,
    OMRIProduct,
    OrganicSystemPlan,
    OSPAnnualUpdate,
)
from .serializers import (
    CertificationSerializer,
    LandownerAffidavitSerializer,
    OrganicSystemPlanListSerializer,
    OrganicSystemPlanSerializer,
    OSPAnnualUpdateSerializer,
)
from .services.omri_verifier import OMRIProductVerifier

logger = logging.getLogger(__name__)


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

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return super().get_permissions()
        return [IsAuthenticated()]

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

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return super().get_permissions()
        return [IsAuthenticated()]

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
                        f"Cannot edit an OSP in status '{osp.status}'. Start a new "
                        "version instead (POST /new-version/)."
                    )
                }
            )
        serializer.save()

    # Minimum narrative length to consider a § 205.201(a) section materially filled.
    # Kept in sync with AuditExportService.OSP_NARRATIVE_MATERIAL_FLOOR (400 chars)
    # so the submit gate and the audit PDF apply the same bar. Research basis:
    # real CCOF/Oregon Tilth OSP sections average 150-500 words — 400 chars (~70
    # words) is the floor below which a narrative would be flagged as a
    # Notice-of-Noncompliance item per 7 CFR 205.662(c).
    OSP_NARRATIVE_MATERIAL_FLOOR = 400

    def _missing_osp_sections(self, osp):
        """Return the list of § 205.201(a)(1)-(6) section keys that are blank or too brief."""
        from certifications.models import OSP_SECTION_KEYS

        missing = []
        for key in OSP_SECTION_KEYS:
            section = (osp.sections or {}).get(key, {}) or {}
            narrative = (section.get("narrative") or "").strip()
            if len(narrative) < self.OSP_NARRATIVE_MATERIAL_FLOOR:
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
                {"error": f"Cannot submit OSP in status '{osp.status}'. Must be 'draft'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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

        with transaction.atomic():
            osp.status = "submitted"
            osp.submitted_at = dj_tz.now()
            # Save FIRST so submitted_at is in the PDF.
            osp.save(update_fields=["status", "submitted_at", "updated_at"])

            try:
                pdf_bytes = generate_osp_snapshot_pdf(osp)
                filename = f"osp_v{osp.version_number}_{osp.public_id}_" f"{osp.submitted_at.date().isoformat()}.pdf"
                osp.submission_pdf.save(filename, ContentFile(pdf_bytes), save=True)
            except Exception as e:  # pragma: no cover — PDF gen failure is non-fatal
                logger.error(f"OSP snapshot PDF generation failed for OSP {osp.id}: {e}")

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
                        f"Cannot activate OSP in status '{osp.status}'. Must be "
                        "'submitted' (certifier review must be complete)."
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
                        f"Cannot modify approved inputs on an OSP in status "
                        f"'{osp.status}'. Wait for certifier review to complete, "
                        "or start a new version to revise the inputs list."
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
                certifier_template_name=source.certifier_template_name,
                certifier_template_url=source.certifier_template_url,
                created_by=self.request.user,
            )
        return Response(OrganicSystemPlanSerializer(clone).data, status=status.HTTP_201_CREATED)


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

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return super().get_permissions()
        return [IsAuthenticated()]

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

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return super().get_permissions()
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
