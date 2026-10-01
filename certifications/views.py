import hashlib
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
    PostHarvestFacility,
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
    PlanMaterialEntrySerializer,
    PostHarvestFacilitySerializer,
    StateOrganicRegistrationSerializer,
)
from .services.common_osp_records import OSP_SECTION_KEY as OSP_RECORDKEEPING_SECTION_KEY
from .services.common_osp_records import (
    RECORD_TYPES_BY_KEY,
    confirm,
    derive_record_types,
    mark_carried_forward,
    reaffirm_carried,
    summarize,
)
from .services.common_osp_workbooks import WORKBOOKS_BY_KEY, build_workbook, workbook_summary
from .services.omri_verifier import OMRIProductVerifier, looks_like_omri_code
from .services.registry_identifiers import wsda_product_number

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


#: How many catalog matches the lookup card shows at once. The grower is picking a product
#: off a label, so a long list is worse than a prompt to type more of the name — but the
#: response also carries `omri_candidate_count`, and the UI says when it has capped.
_OMRI_CANDIDATE_DISPLAY_LIMIT = 12


#: Fewest certified operations in a state for an agent to rank there. One or two operations is an
#: agent that happens to have a client across the border, not a choice a local grower weighs.
_IN_STATE_MIN = 5


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def certifying_agents(request):
    """The agents the certifier picker offers, and which of them the packet numbers to their own forms.

    `own_numbering` is the promise the picker makes before the plan is written: true means the
    coverage page lists the packet against that agent's form numbers; false means it falls back to
    the Common OSP numbering and says so. It is read from the same register the packet reads, so
    the two cannot disagree. Alphabetical, as the grower scans for their own agent's name.

    `?state=WA` (a code or a full name) adds `in_state_rank`: 1 for the agent certifying the most
    operations in that state in the USDA Organic Integrity Database snapshot, and so on, for agents
    with at least `_IN_STATE_MIN` there. 36+ agencies is right for naming and too many to scan; a
    Washington farm's realistic choices are three. Null for every agent when the state is unknown or
    the snapshot is not loaded, so the picker falls back to its ungrouped list rather than guessing.
    ⚠️ The snapshot places an operation by its PHYSICAL address and Oregon Tilth files none, so
    OTCO never ranks anywhere. The picker therefore groups the agents whose forms the packet speaks
    separately, instead of trusting in-state counts to surface them.
    """
    from django.db.models import Count

    from certifications.certifying_agents import AGENTS, agent_for_name, normalize_agent_name
    from certifications.models import USDAOrganicOperation
    from certifications.services.packet_coverage import registered_certifiers
    from common.us_states import US_STATE_NAMES, normalize_state

    registered = registered_certifiers()
    ranks: dict[str, int] = {}
    code = normalize_state(request.query_params.get("state"))
    if code:
        per_agent: dict[str, int] = {}
        for row in (
            USDAOrganicOperation.objects.filter(status="Certified", state=US_STATE_NAMES[code])
            .values("certifier_name")
            .annotate(n=Count("id"))
        ):
            agent = agent_for_name(row["certifier_name"])
            if agent:
                per_agent[agent.slug] = per_agent.get(agent.slug, 0) + row["n"]
        ordered = sorted(
            (slug for slug, n in per_agent.items() if n >= _IN_STATE_MIN), key=lambda slug: -per_agent[slug]
        )
        ranks = {slug: position for position, slug in enumerate(ordered, start=1)}

    return Response(
        [
            {
                "slug": agent.slug,
                "name": agent.name,
                "short_name": agent.short_name,
                "own_numbering": agent.slug in registered,
                "in_state_rank": ranks.get(agent.slug),
            }
            for agent in sorted(AGENTS, key=lambda a: normalize_agent_name(a.name))
        ]
    )


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

    # A grower with the OMRI certificate open pastes the product code into the search box, not
    # into a separate "OMRI ID" field — the OSP panel has no such field and only ever sends
    # `name`. Recognising the code HERE means every caller of this endpoint gets code lookup
    # without having to know the parameter exists, and the verdict below (`found` / `status` /
    # `notes`) is computed from the same code the candidate list resolves.
    if not omri_id and looks_like_omri_code(name):
        omri_id = name

    verifier = OMRIProductVerifier()
    result = verifier.verify(operation_name=name, certification_number=omri_id)

    # Re-resolve the matched objects so the frontend can POST the FK pk back.
    # We resolve OMRI, WSDA, and NL independently so the typeahead can surface
    # whichever matches exist — a product like Neptune's Harvest may be on both
    # OMRI and WSDA catalogs (CCOF treats WSDA as co-equal), while an elemental
    # substance like copper hydroxide may have no brand listing but a strong
    # NL hit. The UI renders all three independently and the farmer picks.
    from certifications.services.omri_verifier import (
        _omri_candidates_by_name,
        _wsda_candidates_by_name,
        national_list_candidates_by_name,
    )

    matched_omri = None
    matched_nl = None
    matched_wsda = None
    omri_candidates = []
    wsda_candidates = []
    nl_candidates = []
    if omri_id:
        matched_omri = OMRIProduct.objects.filter(omri_id__iexact=omri_id).first()
        if matched_omri:
            omri_candidates = [matched_omri]
    if matched_omri is None and name:
        # The shortlist, not just the winner. A single guessed row carrying a one-tap
        # "use this listing" turns a fuzzy search result into a persisted third-party
        # claim; when the query matches several products the grower has to choose.
        #
        # `allow_prefix` is ON here and nowhere else. This is the farmer typing into a search
        # box, where "Serenad" must reach "Serenade ASO"; the drift detector and the CDFA
        # seeder call the same matcher with it OFF, because there a match becomes an assertion
        # rather than an option. See `_token_subsequence_score`.
        omri_candidates = _omri_candidates_by_name(name, allow_prefix=True)
        matched_omri = omri_candidates[0] if omri_candidates else None

    if name:
        # All three catalogues now answer with a LIST. Returning one row each is what made a
        # search for "Serenade" show a single brand while the plan's own Serenade Opti sat
        # unreachable two rows down, and made "copper" collapse several § 205.601 entries into
        # whichever had the shortest name. The UI shows every match and the grower picks.
        wsda_candidates = _wsda_candidates_by_name(name, allow_prefix=True)
        matched_wsda = wsda_candidates[0] if wsda_candidates else None

        nl_candidates = national_list_candidates_by_name(name)
        # The single "match" is what the spray form's helper reads for its status line, so it is a
        # crop row. Handling rows (§ 205.605/606) stay in the candidate list, labelled by section,
        # for the plan's approved-inputs panel to offer (review, 2026-09-10).
        from certifications.services.reference_data_status import HANDLING_SECTIONS

        matched_nl = next((s for s in nl_candidates if s.cfr_section not in HANDLING_SECTIONS), None)

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
            # Every row the query matched, best first. One entry (or none) means the answer
            # is unambiguous; more means the UI must let the grower pick rather than offering
            # a one-tap attach on a guess.
            "omri_candidates": [
                {
                    "pk": o.pk,
                    "omri_id": o.omri_id,
                    "product_name": o.product_name,
                    "manufacturer": o.manufacturer,
                    # WHICH published edition this row came from. OMRI republishes its lists
                    # daily, so a listing shown without its edition date can go stale on the
                    # screen with nobody able to tell. `list_edition_date` was stored from the
                    # first import and never surfaced; added 2026-09-17 after Trazo described
                    # this surface to OMRI's Deputy Director as showing "the listing and its
                    # date", which was true of the database and not of the UI.
                    "list_edition_date": o.list_edition_date.isoformat() if o.list_edition_date else None,
                }
                for o in omri_candidates[:_OMRI_CANDIDATE_DISPLAY_LIMIT]
            ],
            # The TRUE number of matches, which is not `len(omri_candidates)` once the list
            # above is capped. Reporting the capped length as the total would tell a grower
            # "6 products match" when 7 do — and the one left out could be theirs.
            "omri_candidate_count": len(omri_candidates),
            "national_list_substance_pk": matched_nl.pk if matched_nl else None,
            "national_list_substance_name": matched_nl.substance_name if matched_nl else None,
            "national_list_cfr_section": matched_nl.cfr_section if matched_nl else None,
            # What the client prints. Empty for a nonsynthetic row, which has no citation to give.
            "national_list_citation": matched_nl.citation if matched_nl else None,
            # False for a nonsynthetic row, so the client badges it as such and not as "National List".
            "national_list_is_entry": matched_nl.is_national_list_entry if matched_nl else None,
            "national_list_status": matched_nl.status if matched_nl else None,
            # Every § 205.601/602 entry the query could mean. `status` travels with each row:
            # the catalogue holds PROHIBITED substances too, and both answer the same search,
            # so a row the UI must refuse to add has to be distinguishable per-row, not just
            # for whichever one happened to rank first.
            "national_list_candidates": [
                {
                    "pk": s.pk,
                    "substance_name": s.substance_name,
                    "cfr_section": s.cfr_section,
                    "citation": s.citation,
                    "is_national_list_entry": s.is_national_list_entry,
                    "subsection": s.subsection,
                    "status": s.status,
                    "restriction_notes": s.restriction_notes,
                }
                for s in nl_candidates[:_OMRI_CANDIDATE_DISPLAY_LIMIT]
            ],
            "national_list_candidate_count": len(nl_candidates),
            # WSDA Materials List — co-equal with OMRI per CCOF. See
            # feedback_input_source_catalogs for why checking WSDA is required
            # for a realistic false-positive rate on US organic crops.
            # ⛔ `wsda_product_number()`, not the raw column. A real WSDA key is the bare
            # integer of the list's `WSDA Product #` column; Trazo's seeded catalogue also
            # holds placeholders shaped `WSDA-REG-BIOAG-2025-001`, which WSDA issues nothing
            # like — a certifier who searches one finds nothing. Both readers of this endpoint
            # already refuse to render a non-number, but a claim should not be filtered at the
            # far end of the wire: the API must not EMIT an identifier it cannot stand behind,
            # or the next reader inherits the defect. Empty string means "we have no
            # identifier for this row", which is the truth.
            "wsda_material_pk": matched_wsda.pk if matched_wsda else None,
            "wsda_material_id": (wsda_product_number(matched_wsda.wsda_id) or None) if matched_wsda else None,
            "wsda_material_name": matched_wsda.brand_name if matched_wsda else None,
            "wsda_material_category": matched_wsda.category if matched_wsda else None,
            "wsda_candidates": [
                {
                    "pk": m.pk,
                    "wsda_id": wsda_product_number(m.wsda_id) or None,
                    "brand_name": m.brand_name,
                    "manufacturer": m.manufacturer,
                    "category": m.category,
                }
                for m in wsda_candidates[:_OMRI_CANDIDATE_DISPLAY_LIMIT]
            ],
            "wsda_candidate_count": len(wsda_candidates),
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


class PostHarvestFacilityViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """CRUD for off-farm post-harvest handlers — CCOF G6.1 / 7 CFR 205.272.

    🔴 2026-08-16. The model, its serializer and the audit export's
    ``_facility_cert_block`` all shipped; this route did not, and neither did a write path
    on ``History.post_harvest_facilities``. So the one record CCOF's grower checklist calls
    for when a crop is sent to another certified operation — the handler's current organic
    certificate — was reachable only from Django admin, and the packet's G6.1 block could
    never render for a real operation. The export was already compensating by scraping
    handler names out of free-text narratives with a regex.

    Verification mirrors ``CertificationViewSet``: a background thread calls the same USDA
    Organic Integrity Database verifier the farm's own certificates use, and a no-match
    degrades to ``self_reported`` rather than asserting the handler is uncertified.
    """

    serializer_class = PostHarvestFacilitySerializer

    def get_queryset(self):
        return PostHarvestFacility.objects.filter(
            establishment_id=self.kwargs.get("establishment_pk"),
            establishment__company=self.company,
        ).select_related("establishment")

    def perform_create(self, serializer):
        facility = serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )
        self._trigger_background_verification(facility)

    @action(detail=True, methods=["post"])
    def verify(self, request, **kwargs):
        """Re-check this handler against the USDA Organic Integrity Database."""
        facility = self.get_object()
        self._trigger_background_verification(facility)
        return Response(
            {"status": "verification_initiated", "facility_id": facility.id},
            status=status.HTTP_202_ACCEPTED,
        )

    def _trigger_background_verification(self, facility):
        def _bg_verify(facility_id):
            try:
                connections.close_all()
                target = PostHarvestFacility.objects.get(id=facility_id)
                target.verify()
                target.save(
                    update_fields=[
                        "verification_status",
                        "last_verified_at",
                        "verification_source",
                        "raw_api_response",
                        "updated_at",
                    ]
                )
            except Exception as e:
                logger.error(f"Background verification failed for post-harvest facility {facility_id}: {e}")
            finally:
                connections.close_all()

        transaction.on_commit(
            lambda: threading.Thread(
                target=_bg_verify,
                args=(facility.id,),
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
                # The fourth source. `plan_materials()` reads it, so a prefetch list that knows
                # about three registries is the same off-by-one as a renderer that does.
                "plan_material_entries",
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

        # The plan review rides back with the submission. It does not block — the operator may
        # have read a section and decided it still holds — but it is in front of them at the
        # moment the decision was made, and it prints on the packet cover for the same reason.
        from certifications.services.plan_review import plan_review

        data = OrganicSystemPlanSerializer(osp).data
        data["review"] = plan_review(osp).as_dict()
        return Response(data)

    @action(detail=True, methods=["get"], url_path="review")
    def review(self, request, **kwargs):
        """What the operation's records did after this plan's answers were last written.

        `new-version` copies every answer across, and nothing then said which answers the
        records had overtaken. A pilot's renewal went out reading "six parcels" and "86.9 acres"
        with seven and 96.7 on file, every section stamped eighteen months before submission.
        This lists — from dated records only, never by reading the prose — the ground begun,
        seasons started and closed, § 205.400(f) notices, materials changes, certificate
        changes, affidavits and incidents since the newest answer, the parcels the plan never
        names, and the modules not revisited in a year. See services/plan_review.py.
        """
        from django.utils import timezone as dj_tz

        from certifications.services.plan_review import plan_review

        # `reference=now`: the screen shows the RUNNING list — on an active plan, everything the
        # next annual update will have to mention. The packet cover keeps the filing date.
        return Response(plan_review(self.get_object(), reference=dj_tz.now()).as_dict())

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

        # § 205.602 substances are PROHIBITED in organic crop production, and 33 of them sit in the
        # same National List catalogue the search reads — "Ash from manure burning" comes back for
        # a search on "manure". The API served each row's status all along and nothing read it, so
        # a prohibited substance could be attached to the plan and would then print in the
        # certifier packet as an input on this operation's approved list. Refused here rather than
        # only in the panel, because a disabled button is a UI courtesy, not an access rule.
        if kind == "national_list" and (getattr(target, "status", "") or "").lower() == "prohibited":
            raise ValidationError(
                {
                    "id": (
                        f"{target.substance_name} is prohibited in organic production "
                        f"(\u00a7 {target.cfr_section or '205.602'}) and cannot be added to an organic "
                        "system plan. If it was applied to this land, record it as a land-history "
                        "or change-notification entry instead."
                    )
                }
            )

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

        self._recompile_after_materials_change(osp)
        # Re-fetch so serializer reflects the freshly prefetched relations.
        osp.refresh_from_db()
        return Response(OrganicSystemPlanSerializer(osp).data)

    @staticmethod
    def _recompile_after_materials_change(osp) -> None:
        """Keep the on-screen § 205.201(a) narrative in step with the materials list.

        The packet recompiles at assembly (`_refresh_narratives_if_editable`), and that is what
        guarantees the FILED document. This is the other half: between packets the farmer reads
        their narrative in the app, and a material added here belongs in it immediately rather
        than at whatever module save happens to come next.
        """
        from certifications.services.osp_module_compiler import compile_modules_to_sections

        # 🔴 Re-read the plan, WITHOUT this viewset's prefetches. `get_queryset` prefetches
        # `plan_material_entries` and the three catalog M2Ms, and a prefetch cache is not
        # invalidated by a write: `plan_materials()` called on the instance the request started
        # with returns the list as it stood BEFORE the material was added, so the narrative it
        # recompiled was the one this call exists to replace. The material appeared in the app
        # only after some later, unrelated save happened to refetch.
        osp = OrganicSystemPlan.objects.filter(pk=osp.pk).first() or osp

        try:
            if compile_modules_to_sections(osp):
                osp.save(update_fields=["sections", "updated_at"])
        except Exception:  # noqa: BLE001 — never fail the write over the prose it feeds
            logger.exception("Could not recompile narratives after a materials change on OSP %s", osp.pk)

    @action(detail=True, methods=["get", "post"], url_path="plan-materials")
    def plan_materials_entries(self, request, **kwargs):
        """List (GET) or add (POST) an operator-authored materials-list row.

        The defect this closes: the only path onto an OSP's materials list was a catalog match,
        so CCOF NOPB41 §A's own examples — compost, manure, gypsum, limestone — and any
        home-formulated product had nowhere to go, while the module printed five attestations
        that every material in use was on the list. § 205.201(a) makes the producer the author;
        a catalog is a shortcut, never the gate.

        Editable on the same statuses as the approved-inputs list, for the same reason: the
        materials list is part of the plan under review.
        """
        osp = self.get_object()
        if request.method == "GET":
            return Response(PlanMaterialEntrySerializer(osp.plan_material_entries.all(), many=True).data)

        self._ensure_approved_inputs_editable(osp)
        serializer = PlanMaterialEntrySerializer(data=request.data, context={"osp": osp})
        serializer.is_valid(raise_exception=True)
        entry = serializer.save(
            osp=osp,
            created_by=request.user if request.user.is_authenticated else None,
        )
        # Adding a material may clear a drift warning raised for it, exactly as attaching a
        # catalog input does.
        self._recompute_drift_for_establishment(osp.establishment_id)
        self._recompile_after_materials_change(osp)
        return Response(PlanMaterialEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"plan-materials/(?P<entry_id>\d+)",
    )
    def plan_material_entry_detail(self, request, entry_id=None, **kwargs):
        """Correct or remove one operator-authored row.

        Removal is never gated on the material's standing — a row that should not be on the plan
        must always be removable. (The § 205.602 refusal added on 2026-08-28 applies to putting a
        prohibited substance ON a plan, never to taking one off.)
        """
        osp = self.get_object()
        self._ensure_approved_inputs_editable(osp)
        entry = osp.plan_material_entries.filter(pk=entry_id).first()
        if entry is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.method == "DELETE":
            entry.delete()
            self._recompute_drift_for_establishment(osp.establishment_id)
            self._recompile_after_materials_change(osp)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = PlanMaterialEntrySerializer(entry, data=request.data, partial=True, context={"osp": osp})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self._recompute_drift_for_establishment(osp.establishment_id)
        self._recompile_after_materials_change(osp)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="materials-list")
    def materials_list(self, request, **kwargs):
        """The Materials List attachment as rows, with the two per-row answers only the operator has.

        The Common OSP Materials List asks four things per product: name, manufacturer, reason
        for use, and whether it is IN USE or INTENDED for use. Trazo could answer the first from
        any of its four material sources — and the last three only for the operator's own rows,
        because a catalog listing says a product is allowed and cannot say this operation uses
        it or why. So a plan whose materials came from OMRI or WSDA generated an attachment with
        those three columns blank on every row, the attachments panel counted them as "cells to
        fill in Trazo", and there was nowhere in Trazo to fill them. This endpoint and its
        writer are that somewhere.
        """
        from certifications.services.plan_materials import materials_list_rows

        osp = self.get_object()
        return Response({"materials": materials_list_rows(osp)})

    @action(detail=True, methods=["post"], url_path="materials-list/answer")
    def materials_list_answer(self, request, **kwargs):
        """Record the operator's per-row answers for one material.

        Body: {"name": "...", "reason_for_use": "...", "status": "in_use"|"planned",
               "manufacturer": "..."} — every field but `name` optional.

        The answers live on `PlanMaterialEntry`, which already owns them for operator-authored
        rows; a catalog-attached product gets an entry created for it, carrying the catalog FK
        so its listing basis is the one it really has rather than a claim typed by hand. The
        catalog attachment itself is untouched: the M2M is what the drift detector reads, and
        two writers of "is this material approved" is the defect this codebase keeps removing.
        `plan_materials()` folds the two into one printed row.
        """
        osp = self.get_object()
        self._ensure_approved_inputs_editable(osp)

        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "Name the material this answer is about."})

        payload = {
            field: request.data[field]
            for field in ("reason_for_use", "status", "manufacturer")
            if field in request.data
        }
        if not payload:
            raise ValidationError({"detail": "Nothing to record — send a reason, a manufacturer or a use status."})

        # Find-or-create, under a lock on the plan row. Two answers for the SAME material can
        # overlap in one sitting — a use picked from the select and a reason blurred a moment
        # later are two requests — and unserialised they both find nothing and both create. The
        # duplicate would then be FOLDED out of sight by `plan_materials`, so the operator's
        # second answer would save, return 201, and never appear anywhere.
        with transaction.atomic():
            OrganicSystemPlan.objects.select_for_update().filter(pk=osp.pk).first()
            entry = self._find_material_entry(osp, name)
            if entry is not None:
                serializer = PlanMaterialEntrySerializer(entry, data=payload, partial=True, context={"osp": osp})
                serializer.is_valid(raise_exception=True)
                serializer.save()
                created = False
            else:
                payload["product_name"] = name
                payload.update(self._listing_basis_for(osp, name))
                serializer = PlanMaterialEntrySerializer(data=payload, context={"osp": osp})
                serializer.is_valid(raise_exception=True)
                serializer.save(
                    osp=osp,
                    created_by=request.user if request.user.is_authenticated else None,
                )
                created = True

        # A material the records showed but the plan did not now IS on the plan, so the drift
        # finding it raised has to be recomputed here exactly as it is on the other two write
        # paths. Skipping it would leave the operator staring at a warning they just answered.
        self._recompute_drift_for_establishment(osp.establishment_id)
        self._recompile_after_materials_change(osp)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @staticmethod
    def _find_material_entry(osp, name):
        """The operator's existing row for this product, matched the way the list matches.

        `product_name__iexact` in the database is NOT the same rule `plan_materials` uses to
        fold a catalog row into an entry: that one collapses whitespace too, because a name
        pasted off a label arrives with a double space. Matching more loosely here than the
        list folds would create a second entry that the list then hides — the operator's answer
        would save, return 201, and never appear.
        """
        from certifications.models import PlanMaterialEntry
        from certifications.services.plan_materials import _norm

        # A direct query, NOT `osp.plan_material_entries.all()`: the viewset prefetches that
        # relation, so the manager would hand back a cache filled before the row lock was taken
        # — and a lock whose read is served from a stale cache protects nothing.
        target = _norm(name)
        for entry in PlanMaterialEntry.objects.filter(osp_id=osp.pk):
            if _norm(entry.product_name) == target:
                return entry
        return None

    @staticmethod
    def _listing_basis_for(osp, name):
        """The listing basis this product genuinely has, from the catalog row it is attached to.

        Never asserted from the name alone: an entry created here may say "OMRI listed" only
        because the plan holds the OMRI product it was resolved against, and the FK is stored so
        a reviewer can check the claim rather than take it. A product with no catalog attachment
        gets `none_unlisted`, which is the truth about it.
        """
        from certifications.models import PlanMaterialEntry
        from certifications.services.plan_materials import _norm

        target = _norm(name)
        for prod in osp.approved_omri_products.all():
            if _norm(getattr(prod, "product_name", "")) == target:
                return {"listing_basis": PlanMaterialEntry.BASIS_OMRI, "omri_product": prod.pk}
        for mat in osp.approved_wsda_materials.all():
            if _norm(getattr(mat, "brand_name", "")) == target:
                return {"listing_basis": PlanMaterialEntry.BASIS_WSDA, "wsda_material": mat.pk}
        for sub in osp.approved_national_list_substances.all():
            if _norm(getattr(sub, "substance_name", "")) == target:
                return {
                    "listing_basis": PlanMaterialEntry.BASIS_NATIONAL_LIST,
                    "national_list_substance": sub.pk,
                }
        return {"listing_basis": PlanMaterialEntry.BASIS_NONE}

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

        serializer = OSPChangeNotificationSerializer(data=request.data, context={"osp": osp, "request": request})
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

        Once the entry is a record of what was communicated to a third party it
        stays frozen — correcting THAT is a new notification, not an edit of the
        old one.

        🔴 2026-09-07 — THE FREEZE NEVER FIRED. It tested `certifier_acknowledged_at`
        alone, and nothing in the product writes that field (it is read-only on the
        serializer and set only via admin), so every § 205.400(f)(1) drift notice
        stayed withdrawable for ever — including after it had printed into a packet
        as document 03. The one field the OPERATION actually writes to say it has
        notified its certifier is `date_notified`, so that is the second half of the
        freeze: with a date, the row asserts a communication happened and must be
        kept; blank, it is still a draft the operation has not sent, which
        `clean()` deliberately allows so an urgent drift record can be entered
        before the phone call.
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
        if notification.date_notified is not None:
            return Response(
                {
                    "error": (
                        "This notification records that the certifier was notified on "
                        f"{notification.date_notified}, so it is evidence that the "
                        "communication 7 CFR 205.400(f) requires actually happened. It cannot "
                        "be withdrawn — record a new notification describing the correction "
                        "instead. A notification still being drafted, with no date yet, can "
                        "still be withdrawn."
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
        self._recompile_after_materials_change(osp)
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
                # § 11 confirmations ride inside `sections`, so a verbatim clone re-dated last
                # year's attestation as this year's. `mark_carried_forward` keeps the answers
                # (the operator did make them) and marks them carried until re-stated — see the
                # service docstring. It also deep-copies, which `sections=source.sections` did
                # not: both rows held the SAME dict object.
                sections=mark_carried_forward(source.sections, source.version_number),
                # Next season starts guided from last year's answers (Appendix A §h.5).
                module_responses=source.module_responses,
                certifier_template_name=source.certifier_template_name,
                certifier_template_url=source.certifier_template_url,
                # Next year's plan goes to the same agent unless the operator says otherwise.
                certifier_name=source.certifier_name,
                created_by=self.request.user,
            )
            # 🔴 2026-08-21 — the clone copied `sections` and `module_responses` and stopped
            # there, so the approved-inputs registry did NOT come across: v2 opened with an
            # empty materials list while v1 held eight verified entries. The dialog promises
            # "copies every answer across", and the registry is an answer — the operator
            # searched each product against OMRI / WSDA / the National List and accepted the
            # match. Losing it is worse than an inconvenience: the § 205.201(a)(2) narrative is
            # compiled from this list, the audit dossier reports "No approved-inputs list is on
            # file for this operation" against a plan that had one, and an operator who submits
            # the new version has filed a plan with no materials list at all — a § 205.201(a)(2)
            # deficiency the tool created. Found on a pilot renewal: v1 4 OMRI / 2 National List
            # / 2 WSDA, v2 zero of each.
            #
            # M2M, so this must happen after create(). The change log is deliberately NOT
            # copied: it is the audit trail of edits made to THAT version (§ 205.400(f)(1)),
            # and the new version starts its own.
            clone.approved_national_list_substances.set(source.approved_national_list_substances.all())
            clone.approved_omri_products.set(source.approved_omri_products.all())
            clone.approved_wsda_materials.set(source.approved_wsda_materials.all())
            # 🔴 2026-09-07 — the fourth source, missed when it shipped a week after the fix
            # above. `PlanMaterialEntry` holds exactly the materials no catalog can supply
            # (CCOF NOPB41 §A: compost, manure, gypsum, limestone), so a renewal cloned from
            # last year's plan lost precisely the rows the operator had to type by hand — the
            # ones hardest to notice missing and most laborious to re-enter.
            #
            # Rows, not an M2M: each is copied rather than shared, so editing next year's plan
            # cannot rewrite what was filed last year. `id`/`osp` are dropped and everything
            # else — including the catalog FKs and `certifier_letter_reference` a basis depends
            # on — travels, or `listing_statement` would come out saying less than it should.
            from certifications.models import PlanMaterialEntry

            carried = []
            for entry in source.plan_material_entries.all():
                carried.append(
                    PlanMaterialEntry(
                        osp=clone,
                        product_name=entry.product_name,
                        manufacturer=entry.manufacturer,
                        category=entry.category,
                        reason_for_use=entry.reason_for_use,
                        status=entry.status,
                        listing_basis=entry.listing_basis,
                        omri_product=entry.omri_product,
                        wsda_material=entry.wsda_material,
                        national_list_substance=entry.national_list_substance,
                        certifier_letter_reference=entry.certifier_letter_reference,
                        notes=entry.notes,
                        # The person filing THIS version, not the original author — the row is
                        # genuinely created today, and attributing it to whoever typed it last
                        # year would put a false name on a new record.
                        created_by=self.request.user,
                    )
                )
            if carried:
                PlanMaterialEntry.objects.bulk_create(carried)
            # 🔴 2026-09-07 — the fifth thing the clone forgot, and the one that emptied a
            # document: the § 205.406(a) filing this renewal is being made under. See
            # `certifications/services/annual_update_linking.py` for the invariant and for the
            # other half of it, which runs when the filing is written after the fork.
            from certifications.services.annual_update_linking import carry_open_filing

            carry_open_filing(source, clone)
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

        POST payload: { "keys": ["harvest_records", ...], "confirmed": true|false,
        "label": "Pool closings from the huller" }. `label` names the free-text "Other" row and
        is required to confirm it — see `common_osp_records.confirm()`.

        Several keys may be sent in ONE request, and the panel batches an operator's rapid
        ticking that way. That is a transport detail: each key in the list is still one box the
        operator ticked on screen. There is deliberately no "confirm everything suggested"
        control anywhere — a confirmation the operator did not make row by row is the
        auto-attestation this whole module refuses.

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

        # "The operation does not keep this record" (OSP alignment audit T17-F1): a statement
        # with a reason, one record type at a time. It never satisfies the records attestation.
        if request.data.get("not_kept") is True:
            from certifications.services.common_osp_records import mark_not_kept

            if len(keys) != 1:
                raise ValidationError({"keys": "State one record type at a time as not kept."})
            reason = request.data.get("reason")
            if reason is not None and not isinstance(reason, str):
                raise ValidationError({"reason": "Must be a string."})
            try:
                mark_not_kept(osp, keys[0], reason or "", user=request.user)
            except ValueError as exc:
                raise ValidationError({"reason": str(exc)}) from exc
            rows = derive_record_types(establishment, osp=osp)
            return Response({"summary": summarize(rows), "record_types": rows})

        unknown = [k for k in keys if k not in RECORD_TYPES_BY_KEY]
        if unknown:
            raise ValidationError({"keys": f"Unknown record type(s): {', '.join(sorted(unknown))}"})

        confirmed = request.data.get("confirmed", True)
        if not isinstance(confirmed, bool):
            raise ValidationError({"confirmed": "Must be a boolean."})

        label = request.data.get("label")
        if label is not None and not isinstance(label, str):
            raise ValidationError({"label": "Must be a string."})

        try:
            confirm(
                osp,
                keys,
                user=request.user if request.user.is_authenticated else None,
                confirmed=confirmed,
                label=label,
            )
        except ValueError as exc:
            # The free-text rules (a label names exactly one row; an "Other" row cannot be
            # confirmed unnamed) are stated once, in the service, because the PDF and any
            # future importer must obey them too. Surface them as field errors.
            raise ValidationError({"label": str(exc)}) from exc
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
            return Response({"workbooks": workbook_summary(establishment, osp=osp)})

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
        buffer = build_workbook(establishment, key, osp=osp)
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
    def _module_status(entry: dict, module=None, osp=None) -> str:
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

                answers = entry.get("answers") or {}
                if missing_required(module, answers):
                    return "in_progress"
                # A module completed before the attestation gate existed can still hold an
                # affirmative attestation over an empty list. Report it honestly rather than
                # showing a green tick a certifier will send back.
                if osp is not None:
                    from certifications.services.attestation_gates import blocked_attestations

                    if blocked_attestations(module, answers, osp):
                        return "in_progress"
            return "completed"
        if entry.get("answers"):
            return "in_progress"
        return "not_started"

    def _module_progress_row(self, module, entry: dict, osp=None) -> dict:
        from certifications.osp_modules.conditions import progress

        return {
            "key": module.key,
            "code": module.code,
            "status": self._module_status(entry, module, osp),
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
        rows = [self._module_progress_row(m, responses.get(m.key) or {}, osp) for m in MODULE_REGISTRY]
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
            retired_additions,
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
                    "response": self._module_progress_row(module, entry, osp),
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
                retired = retired_additions(module, incoming, entry.get("answers") or {})
                if retired:
                    raise ValidationError(
                        {
                            "answers": {
                                k: f"No longer offered; choose one of the current options: {', '.join(v)}"
                                for k, v in retired.items()
                            }
                        }
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
                # Refuse the untrue value at the WRITE, not only at completion. The attestation
                # is a statement to the certifier; storing it and blocking completion later would
                # leave "Yes" sitting in the plan, and the compiler reads stored answers.
                from certifications.services.attestation_gates import blocked_attestations

                blocked = blocked_attestations(module, incoming, osp)
                if blocked:
                    raise ValidationError({"answers": blocked})

                from certifications.osp_modules.conditions import answer_value

                for key, value in incoming.items():
                    if value is None:
                        if key in entry["answers"]:
                            entry["answers"].pop(key)
                            content_changed = True
                    else:
                        # Same two-shape hazard as the module PDF: an answer already stored
                        # in the BARE shape by the module wizard makes `.get("value")` raise on
                        # a str/list. Compare through the tolerant accessor.
                        previous = answer_value(entry["answers"], key)
                        if previous != value:
                            entry["answers"][key] = {"value": value, "at": now}
                            content_changed = True

                # F25 — a bound answer also owns an `Establishment` column. Written in the
                # SAME transaction as the answer so the packet can never read one without
                # the other. See certifications/osp_modules/bindings.py for why the OSP
                # is the editor and the column is the follower.
                from certifications.osp_modules.bindings import establishment_writes, is_unchanged

                bound = establishment_writes(module, incoming)
                if bound:
                    est = osp.establishment
                    changed = [f for f, v in bound.items() if not is_unchanged(getattr(est, f), v)]
                    if changed:
                        for f in changed:
                            setattr(est, f, bound[f])
                        est.save(update_fields=changed)

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
                # An attestation over an empty embed is the module reporting "complete" while
                # its own PDF prints a signature line with nothing above it. See
                # certifications/services/attestation_gates.py.
                from certifications.services.attestation_gates import blocked_attestations

                blocked = blocked_attestations(module, stored, osp)
                if blocked:
                    raise ValidationError(
                        {
                            "complete": "An attestation refers to a list that is still empty.",
                            "attestations": blocked,
                        }
                    )
                entry["completed_at"] = now
                entry["completed_by"] = user_id

            entry["definition_version"] = CONTENT_VERSION
            entry["status"] = self._module_status(entry, module, osp)
            osp.module_responses = responses

            # Recompile the § 205.201(a) narratives from the new answers in the same
            # transaction — the sections a certifier reads are never stale relative to
            # module answers (WS-2.3).
            from certifications.services.osp_module_compiler import compile_modules_to_sections

            compile_modules_to_sections(osp)
            osp.save(update_fields=["module_responses", "sections", "updated_at"])

        return Response(
            {
                "response": self._module_progress_row(module, entry, osp),
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
        from certifications.services.annual_update_linking import link_filing_to_open_draft

        prior = serializer.validated_data["prior_osp"]
        instance = serializer.save(
            created_by=self.request.user,
            establishment_id=prior.establishment_id,
            revision_number=1,
        )
        # The other half of the fork's `carry_open_filing`: an update filed while the next
        # version is already open produced that draft, and nothing else will ever say so.
        link_filing_to_open_draft(instance)
        self._reaffirm_carried_record_types(instance)

    def perform_update(self, serializer):
        from certifications.services.annual_update_linking import link_filing_to_open_draft

        instance = serializer.save()
        link_filing_to_open_draft(instance)
        self._reaffirm_carried_record_types(instance)

    def _reaffirm_carried_record_types(self, filing):
        """An "unchanged" attestation on the recordkeeping section re-dates the § 11 answers.

        § 11 confirmations ride inside `OrganicSystemPlan.sections`, so cloning a plan for the
        next year carried last year's ticks forward marked `carried_from_version` — confirmed,
        but not re-stated by anyone this year. This is where a human re-states them: the
        operator attests on the § 205.406(a)(1) filing that the recordkeeping section is
        unchanged since the prior plan, and that attestation is dated, theirs, and the very
        thing the regulation provides for. Making them click a second control to say the same
        sentence again would be ceremony.

        Applies to the plan this filing PRODUCED where there is one — that is the plan carrying
        the cloned answers — and otherwise to the plan it references.

        ⛔ This can never create a confirmation; `reaffirm_carried` only touches rows the
        operation already confirmed. Attesting "unchanged" over a section the operator never
        filled leaves it empty, which is the honest outcome.
        """
        attestation = filing.sections_unchanged_attestation or {}
        if attestation.get(OSP_RECORDKEEPING_SECTION_KEY) is not True:
            return
        target = filing.new_osp or filing.prior_osp
        try:
            reaffirm_carried(target, user=self.request.user if self.request.user.is_authenticated else None)
        except Exception:  # noqa: BLE001 — a filing must not fail over a bookkeeping stamp
            logger.exception("Could not re-affirm carried § 11 confirmations for OSP %s", getattr(target, "pk", None))

    # ------------------------------------------------------------------
    # A § 205.406 filing is edited only while it is an unsigned draft (2026-10-01, OSP alignment
    # audit T20). Before this, a submitted filing stayed editable until the certifier
    # acknowledged it, nothing in the product ever recorded the acknowledgement, and document 02
    # was rendered from the live row, so what the packet said an operation filed could change
    # after it was filed. Now:
    #
    #   draft     (not signed, not filed) -> freely editable and deletable
    #   signed    (signed_at set)         -> content frozen: an edit is 409, delete is 423
    #   filed     (submitted_at set)      -> the document is frozen too (`filed_pdf`)
    #
    # A mistake in a signed or filed revision is fixed by `correct`, which opens the next
    # revision and leaves this one exactly as it was. A filed revision that should not stand is
    # withdrawn, with a reason, never deleted. Rows filed before signatures existed are locked
    # the same way: they reached the agent, so they are part of the record.
    LOCKED_DETAIL = (
        "Revision {revision} of the {year} annual update is {state}. It stays as it is; create a "
        "correction to change what it says."
    )

    def _locked_state(self, instance):
        if instance.submitted_at is not None:
            return f"filed ({instance.submitted_at.date().isoformat()})"
        return f"signed ({instance.signed_at.date().isoformat()})"

    def _locked_response(self, instance, http_status):
        return Response(
            {
                "error": "Annual update revision is locked",
                "detail": self.LOCKED_DETAIL.format(
                    revision=instance.revision_number,
                    year=instance.reporting_year,
                    state=self._locked_state(instance),
                ),
                "correctable": True,
                "reporting_year": instance.reporting_year,
                "revision_number": instance.revision_number,
            },
            status=http_status,
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return self._locked_response(instance, status.HTTP_409_CONFLICT)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_locked:
            return self._locked_response(instance, status.HTTP_423_LOCKED)
        return super().destroy(request, *args, **kwargs)

    def _run(self, fn, *args, success_status=status.HTTP_200_OK):
        from certifications.services.annual_update_filing import FilingStateError

        try:
            result = fn(*args)
        except FilingStateError as exc:
            return Response({"error": exc.detail, "detail": exc.detail}, status=exc.status_code)
        result.refresh_from_db()
        return Response(self.get_serializer(result).data, status=success_status)

    @action(detail=True, methods=["post"])
    def sign(self, request, *args, **kwargs):
        from certifications.services.annual_update_filing import sign_filing

        return self._run(sign_filing, self.get_object(), request.user, request.data.get("signer_title", ""))

    @action(detail=True, methods=["post"], url_path="file")
    def file_with_agent(self, request, *args, **kwargs):
        import datetime

        from django.utils import timezone
        from django.utils.dateparse import parse_date, parse_datetime

        from certifications.services.annual_update_filing import file_filing

        raw = request.data.get("submitted_at")
        when = None
        if raw:
            when = parse_datetime(str(raw))
            if when is None:
                day = parse_date(str(raw))
                if day is None:
                    return Response(
                        {"submitted_at": "Give the date the update was filed as YYYY-MM-DD."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                when = timezone.make_aware(datetime.datetime.combine(day, datetime.time(12, 0)))
            elif timezone.is_naive(when):
                when = timezone.make_aware(when)
        return self._run(file_filing, self.get_object(), request.data.get("filing_method", ""), when)

    @action(detail=True, methods=["post"])
    def correct(self, request, *args, **kwargs):
        from certifications.services.annual_update_filing import correct_filing

        return self._run(correct_filing, self.get_object(), request.user, success_status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, *args, **kwargs):
        from certifications.services.annual_update_filing import withdraw_filing

        return self._run(withdraw_filing, self.get_object(), request.data.get("reason", ""))


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


class CertifierPollThrottle(AnonRateThrottle):
    """The dossier-status poll: a reviewer waiting on a build asks every few seconds, which
    the 50/hour anonymous default would cut off mid-build. Rate in DEFAULT_THROTTLE_RATES."""

    scope = "certifier_poll"


class CertifierReviewThrottle(AnonRateThrottle):
    """The review LANDING pages, off the shared `anon` bucket.

    🔴 2026-09-08. `certifier-review/<token>/` and its `/readiness/` sibling both carried the
    default `anon` scope, so ONE page load cost two of a certifier's 50 hourly requests — 25
    loads an hour for everyone behind the same IP, and a certifier's office is behind one NAT.
    Worse, the frontend rendered a 429 as "This link is no longer available", so exhausting the
    bucket told the reviewer the grower's link had been revoked. Two independent defects, and
    the throttle was the cause of the one that lies.

    ⚠️ Inert in production TODAY: `prod.py` falls back to `DummyCache` when `REDIS_URL` is
    unset, and DRF throttling counts in the cache. This scope is what makes the review pages
    survive the day Redis is switched on, and the frontend's 429 handling is what stops that
    day being reported as revoked links.
    """

    scope = "certifier_review"


def _resolve_link_or_404(token, audience="certifier"):
    """Resolve an ACTIVE link of the expected AUDIENCE, or raise 404.

    Expired and revoked links deliberately return 404 rather than 410/403: a
    distinct status would confirm to an unauthenticated caller that the token was
    once real, which is information they should not get. The farmer sees the true
    state (expired vs revoked) on their own authenticated dashboard.

    Audience is part of the lookup, not a post-check: a buyer token must never
    open the certifier dossier surface (it exposes supplier invoices, prices and
    applicator names), and a certifier token must never widen the buyer surface.
    Cross-audience use reads as "no such link".
    """
    link = CertifierAccessLink.objects.filter(token=token, audience=audience).select_related("establishment").first()
    if link is None or not link.is_active:
        # The CALLER is told nothing (see above). The operator is a different matter: when a
        # grower reports "the link I sent my inspector does not open", there was previously no
        # way to tell an expired link from a revoked one from a token typed with a trailing
        # character from a buyer token pasted into the certifier route. Logged as a
        # FINGERPRINT, never the token itself — a log line that grants dossier access is a
        # second copy of the credential.
        fingerprint = hashlib.sha256((token or "").encode()).hexdigest()[:12]
        if link is None:
            reason = "no link with this token for this audience"
        elif link.is_revoked:
            reason = "revoked"
        elif link.is_expired:
            reason = "expired"
        else:  # pragma: no cover - is_active is the conjunction of the two above
            reason = "inactive"
        logger.warning(
            "certifier review link refused: audience=%s reason=%s token_sha256_12=%s",
            audience,
            reason,
            fingerprint,
        )
        raise Http404("No active certifier review link for this address.")
    return link


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
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
@throttle_classes([CertifierReviewThrottle])
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
# ⛔ Deliberately NOT `CertifierReviewThrottle`. That scope exists because the LANDING pages are
# cheap and cost two requests per view; this endpoint streams a PDF that takes ~a minute to build
# on a 12-production farm and pins a gthread worker while it does. Moving it to 240/hour would
# have quadrupled the anonymous ceiling on the most expensive route in the product as a side
# effect of fixing page loads. It keeps the tighter shared default; the cheap status poll beside
# it has its own generous scope, which is what a waiting reviewer actually hits.
@throttle_classes([AnonRateThrottle])
def certifier_review_dossier(request, token):
    """The operation audit dossier for this link — current, and built at most once per change.

    Until 2026-09-05 this regenerated the whole PDF on every open so the reviewer always saw
    current records. On a 12-production farm that was ~a minute of build per click, inside a
    request the edge drops at ~100 s, from an anonymous URL. "Always current" is kept a
    different way: builds are keyed by a fingerprint of the records
    (`history/services/records_fingerprint.py`). Same records → the filed copy streams at
    once. Changed records → a build starts and this returns 202 with the job; the page polls
    `…/dossier/status/` and then fetches `…/dossier/?job=<id>` for exactly the build it
    watched, so a record edited mid-build cannot send it round again.
    """
    from django.http import FileResponse

    from documents.models import ExportJob
    from documents.serializers import ExportJobSerializer
    from documents.services.export_jobs import OPERATION_DOSSIER, enqueue, fresh_document, job_key, parse_public_id

    link = _resolve_link_or_404(token)
    key = job_key(
        kind=OPERATION_DOSSIER,
        certification_type=link.certification_type,
        period_start=link.period_start,
        period_end=link.period_end,
    )

    def _stream(document):
        CertifierAccessLog.objects.create(
            link=link,
            action="dossier",
            ip_address=_client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
        )
        filename = f"{slugify(link.establishment.name)}-audit-dossier.pdf"
        return FileResponse(
            document.file.open("rb"), as_attachment=True, filename=filename, content_type="application/pdf"
        )

    requested_job = request.query_params.get("job")
    if requested_job:
        public_id = parse_public_id(requested_job)
        job = (
            ExportJob.objects.filter(
                public_id=public_id, establishment=link.establishment, status="succeeded", document__isnull=False, **key
            )
            .select_related("document")
            .first()
            if public_id
            else None
        )
        if job is None:
            raise Http404("No finished dossier build with that id for this link.")
        return _stream(job.document)

    try:
        document = fresh_document(link.establishment, **key)
        if document is not None:
            return _stream(document)
        job, _created = enqueue(link.establishment, requested_by=None, audience="certifier", **key)
        if job.status == "succeeded" and job.document_id:
            # The eager runner finished inside this request; nothing to poll for.
            return _stream(job.document)
    except Exception:
        # This page is read by a certification reviewer judging the farmer's operation. A raw
        # 500 there reads as "this grower's records are broken", so fail with a neutral message
        # and log the real cause for us.
        logger.exception("Certifier dossier build could not be started for establishment %s", link.establishment_id)
        return Response(
            {"error": "The dossier could not be generated right now. Please try again shortly."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(ExportJobSerializer(job).data, status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierPollThrottle])
def certifier_review_dossier_status(request, token):
    """JSON side of the dossier handshake. Never streams a document.

    Without `?job=`: is a current build on file? `{"status": "ready"}` when the newest
    succeeded build still matches the records (the page then navigates to `…/dossier/`);
    otherwise a build is started (or joined) and its job is returned with 202. The page used
    to probe `…/dossier/` itself, which started a PDF stream it then cancelled and logged a
    download that never happened.

    With `?job=<public_id>`: that build's status and progress. On success the page navigates
    to `…/dossier/?job=<public_id>`.
    """
    from documents.models import ExportJob
    from documents.serializers import ExportJobSerializer
    from documents.services.export_jobs import (
        OPERATION_DOSSIER,
        enqueue,
        fresh_document,
        job_key,
        parse_public_id,
        reap_stale,
    )

    link = _resolve_link_or_404(token)
    raw_job = request.query_params.get("job")
    if not raw_job:
        key = job_key(
            kind=OPERATION_DOSSIER,
            certification_type=link.certification_type,
            period_start=link.period_start,
            period_end=link.period_end,
        )
        try:
            if fresh_document(link.establishment, **key) is not None:
                return Response({"status": "ready"})
            job, _created = enqueue(link.establishment, requested_by=None, audience="certifier", **key)
        except Exception:
            logger.exception("Certifier dossier build could not be started for establishment %s", link.establishment_id)
            return Response(
                {"error": "The dossier could not be generated right now. Please try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(_neutral_job_payload(job), status=status.HTTP_202_ACCEPTED)

    public_id = parse_public_id(raw_job)
    if public_id is None:
        raise Http404("No such build.")
    reap_stale(link.establishment)
    job = get_object_or_404(ExportJob, public_id=public_id, establishment=link.establishment)
    return Response(_neutral_job_payload(job))


def _neutral_job_payload(job):
    from documents.serializers import ExportJobSerializer

    data = ExportJobSerializer(job).data
    if job.status == "failed":
        # The reviewer is not the person who can fix a failed build; keep the neutral wording.
        data["error"] = "The dossier could not be generated right now. Please try again shortly."
    return data


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
def buyer_review_metadata(request, token):
    """Landing payload for a BUYER review link: operation context + season list.

    The buyer surface serves NO records here — season detail is opened on the
    consumer product page (`public_history` + transparency detail) with this same
    token as `review_token`, so every field a buyer sees flows through the exact
    claim-safe serializers the public page uses. This endpoint only answers
    "whose operation, which seasons, how current" — including OPEN seasons, which
    is the point: wholesale diligence happens before harvest.
    """
    link = _resolve_link_or_404(token, audience="buyer")

    CertifierAccessLog.objects.create(
        link=link,
        action="metadata",
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )

    from history.models import History

    seasons = []
    qs = (
        History.objects.filter(parcel__establishment=link.establishment)
        .select_related("product", "parcel")
        .order_by("-start_date")
    )
    for h in qs:
        seasons.append(
            {
                "public_id": str(h.public_id),
                "name": h.name,
                "product": h.product.name if h.product else None,
                "parcel": h.parcel.name if h.parcel else None,
                "start_date": h.start_date,
                "finish_date": h.finish_date,
                "in_progress": h.finish_date is None,
                "published": bool(h.published),
            }
        )

    return Response(
        {
            "operation_name": link.establishment.name,
            "operation_city": link.establishment.city,
            "operation_state": link.establishment.state,
            "label": link.label,
            "expires_at": link.expires_at,
            "seasons": seasons,
        }
    )


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
        queryset = (
            CertifierAccessLink.objects.filter(establishment=self.establishment)
            .prefetch_related("accesses")
            .order_by("-created_at")
        )
        # `?audience=certifier|buyer`. Both cards on the farm page render from this one list and
        # filtered it client-side, so the split was a rendering convention rather than a
        # contract — and a buyer token pasted into the certifier route is a hard 404 whose cause
        # nobody could see. Server-side filtering makes the two lists mean what they say.
        audience = self.request.query_params.get("audience")
        valid = {choice for choice, _ in CertifierAccessLink.AUDIENCE_CHOICES}
        if audience in valid:
            queryset = queryset.filter(audience=audience)
        return queryset

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
        # The readiness blocker is a CERTIFIER-submission gate ("do not send this to
        # your certifier yet"). A buyer link is the opposite case: in-season diligence,
        # minted precisely while seasons are still open — blocking it on certification
        # readiness would defeat its purpose. The buyer surface is claim-safe by
        # construction (same serializers as the public page), so nothing a buyer can
        # open depends on readiness.
        if serializer.validated_data.get("audience", "certifier") == "certifier":
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
