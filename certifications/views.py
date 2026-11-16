import hashlib
import logging
import math
import threading
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import connections, transaction
from django.db.models import F, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from backend.permissions import AuthPermission, CompanyNestedViewSet, IsCompanyAdminOrManager, IsSuperUser
from backend.security.client_ip import client_ip
from backend.security.throttling import AnonRateThrottle
from subscriptions.gating import require_compliance_exports

from .models import (
    AdjoiningLandAffidavit,
    ApprovedInputChangeLog,
    BrandOwner,
    Certification,
    CertifierAccessLink,
    CertifierAccessLog,
    CertifierInspection,
    CertifierNotice,
    FacilityProduct,
    LandownerAffidavit,
    NationalListSubstance,
    OMRIProduct,
    OperationContact,
    OrganicSystemPlan,
    OSPAnnualUpdate,
    OSPChangeNotification,
    PostHarvestFacility,
    ProductionEquipment,
    StateOrganicRegistration,
    Supplier,
    SupplierCertificate,
    SupplierName,
    normalize_supplier_name,
)
from .serializers import (
    AdjoiningLandAffidavitSerializer,
    BrandOwnerSerializer,
    CertificationSerializer,
    CertifierAccessLinkSerializer,
    CertifierInspectionSerializer,
    CertifierNoticeSerializer,
    FacilityProductSerializer,
    LandownerAffidavitSerializer,
    OperationContactSerializer,
    OrganicSystemPlanListSerializer,
    OrganicSystemPlanSerializer,
    OSPAnnualUpdateSerializer,
    OSPChangeNotificationSerializer,
    PlanMaterialEntrySerializer,
    PostHarvestFacilitySerializer,
    ProductionEquipmentSerializer,
    StateOrganicRegistrationSerializer,
    SupplierCertificateSerializer,
    SupplierNameSerializer,
    SupplierSerializer,
)
from .services.common_osp_records import OSP_SECTION_KEY as OSP_RECORDKEEPING_SECTION_KEY
from .services.common_osp_records import RECORD_TYPES_BY_KEY, confirm, derive_record_types, reaffirm_carried, summarize
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
            # A § 205.602 row the rule allows for one stated use. The client words the condition
            # by paragraph (`subsection`, "c"), so a Spanish screen does not quote English prose;
            # `restriction_notes` is the rule's text for any paragraph it has no words for.
            "national_list_conditional": matched_nl.is_conditionally_permitted if matched_nl else None,
            "national_list_subsection": matched_nl.subsection if matched_nl else None,
            "national_list_restriction_notes": matched_nl.restriction_notes if matched_nl else None,
            # A § 205.601 row the rule allows only under a condition of use (zinc and boron need a
            # documented deficiency, boric acid is for structural pest control). The client must not
            # call it plain "allowed" (OV-MT-C01). `rule_words` is the rule's own text for the row's
            # paragraph, verbatim and in English, for any § 205.601 row whose entry has words; it is
            # never the paraphrase in `restriction_notes`.
            "national_list_allowed_with_condition": matched_nl.allowed_with_condition if matched_nl else None,
            "national_list_rule_paragraph": (matched_nl.rule_words or (None, None))[0] if matched_nl else None,
            "national_list_rule_words": (matched_nl.rule_words or (None, None))[1] if matched_nl else None,
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
                    "is_conditionally_permitted": s.is_conditionally_permitted,
                    "restriction_notes": s.restriction_notes,
                    "allowed_with_condition": s.allowed_with_condition,
                    "rule_paragraph": (s.rule_words or (None, None))[0],
                    "rule_words": (s.rule_words or (None, None))[1],
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
        return (
            PostHarvestFacility.objects.filter(
                establishment_id=self.kwargs.get("establishment_pk"),
                establishment__company=self.company,
            )
            .select_related("establishment")
            .prefetch_related("products__ingredient_statement_document")
        )

    def perform_create(self, serializer):
        facility = serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )
        if facility.needs_own_certificate:
            self._trigger_background_verification(facility)

    @action(detail=True, methods=["post"])
    def verify(self, request, **kwargs):
        """Re-check this handler against the USDA Organic Integrity Database."""
        facility = self.get_object()
        if not facility.needs_own_certificate:
            return Response(
                {"detail": "The operation's own facility has no certificate of its own to verify."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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


class FacilityProductViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """The product rows of the farm's facilities (CCOF G6.1 C2, OTCO C7 7.10-2): category, detail,
    packaging form, label claim, brand and the ingredient statement of a multi-ingredient product.

    Same permissions as the facility route it hangs off. `?facility=<id>` narrows the list to one facility.
    """

    serializer_class = FacilityProductSerializer

    def get_queryset(self):
        queryset = FacilityProduct.objects.filter(
            facility__establishment_id=self.kwargs.get("establishment_pk"),
            facility__establishment__company=self.company,
        ).select_related("facility", "ingredient_statement_document")
        facility = self.request.query_params.get("facility")
        if facility:
            if not str(facility).isdigit():
                return queryset.none()
            queryset = queryset.filter(facility_id=int(facility))
        return queryset.order_by("facility_id", "pk")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user if self.request.user.is_authenticated else None)


class BrandOwnerViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """The companies whose brands this farm packs into, with their certificate or agreement copies.

    Admins and farm managers only, like the supplier register: a brand-owner list is commercial
    relationship data.
    """

    serializer_class = BrandOwnerSerializer
    permission_classes = [IsSuperUser | (IsCompanyAdminOrManager & AuthPermission)]

    def get_queryset(self):
        return (
            BrandOwner.objects.filter(
                establishment_id=self.kwargs.get("establishment_pk"),
                establishment__company=self.company,
            )
            .select_related("certificate_document", "agreement_document")
            .order_by("name", "pk")
        )

    def perform_create(self, serializer):
        serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )


class OperationContactViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """The people the operation names to its certifying agent (OTCO O1 §B; CCOF Contract A4, C1, C2). Admins and
    farm managers only, like the other registers: names, phones and emails of the people behind the operation."""

    serializer_class = OperationContactSerializer
    permission_classes = [IsSuperUser | (IsCompanyAdminOrManager & AuthPermission)]

    def get_queryset(self):
        return OperationContact.objects.filter(
            establishment_id=self.kwargs.get("establishment_pk"),
            establishment__company=self.company,
        ).order_by("pk")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["establishment_id"] = self.kwargs.get("establishment_pk")
        return context

    def perform_create(self, serializer):
        serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )


class CertifierInspectionViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """The farm's own record of its certifier's inspections. Admins and farm managers only, like the
    other registers: an inspection report is the certifier's finding about this operation."""

    serializer_class = CertifierInspectionSerializer
    permission_classes = [IsSuperUser | (IsCompanyAdminOrManager & AuthPermission)]

    def get_queryset(self):
        return (
            CertifierInspection.objects.filter(
                establishment_id=self.kwargs.get("establishment_pk"),
                establishment__company=self.company,
            )
            .select_related("report_document")
            .order_by("-inspected_on", "-pk")
        )

    def perform_create(self, serializer):
        serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )

    def destroy(self, request, *args, **kwargs):
        inspection = self.get_object()
        if inspection.notices.exists():
            # PROTECT on the link: say so by code instead of a server error.
            raise ValidationError(
                {
                    "detail": "Items from the agent are recorded under this inspection. Remove or move them first.",
                    "code": "inspection_has_notices",
                }
            )
        return super().destroy(request, *args, **kwargs)


class CertifierNoticeViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """Items the certifying agent sent the farm (§ 205.662 notices and the agent's other items), each
    with the operation's response and the agent's resolution. Admins and farm managers only."""

    serializer_class = CertifierNoticeSerializer
    permission_classes = [IsSuperUser | (IsCompanyAdminOrManager & AuthPermission)]

    def get_queryset(self):
        return (
            CertifierNotice.objects.filter(
                establishment_id=self.kwargs.get("establishment_pk"),
                establishment__company=self.company,
            )
            .select_related("notice_document", "resolution_document", "inspection")
            .prefetch_related("response_links__document")
            .order_by(F("received_on").desc(nulls_last=True), "-pk")
        )

    def perform_create(self, serializer):
        serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )


class ProductionEquipmentViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """The farm equipment that contacts organic crops (G6.0 page F). Admins and farm managers, like
    the other registers the plan reads."""

    serializer_class = ProductionEquipmentSerializer
    permission_classes = [IsSuperUser | (IsCompanyAdminOrManager & AuthPermission)]

    def get_queryset(self):
        return ProductionEquipment.objects.filter(
            establishment_id=self.kwargs.get("establishment_pk"),
            establishment__company=self.company,
        ).order_by("name", "pk")

    def perform_create(self, serializer):
        serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )


class SupplierViewSet(CompanyNestedViewSet, viewsets.ModelViewSet):
    """The farm's seed and planting-stock suppliers and their organic certificates.

    Read and write are limited to company admins and farm managers, like
    `productions/seed-suppliers/`: a supplier list is commercial relationship data, the same class of
    counterparty name the consumer payload scrubs. A viewer reads none of it.

    A supplier that a record resolves to is archived, never deleted, so a finished season keeps
    the supplier its records name. Spellings and certificate copies are the grower's corrections
    and may be removed.
    """

    serializer_class = SupplierSerializer
    permission_classes = [IsSuperUser | (IsCompanyAdminOrManager & AuthPermission)]

    def get_queryset(self):
        return (
            Supplier.objects.filter(
                establishment_id=self.kwargs.get("establishment_pk"),
                establishment__company=self.company,
            )
            .prefetch_related(
                "names", Prefetch("certificates", queryset=SupplierCertificate.objects.select_related("document"))
            )
            .order_by("name", "pk")
        )

    def _spelling_counts(self):
        from history.services.supplier_certificates import spelling_counts

        if not hasattr(self, "_counts"):
            self._counts = spelling_counts(self.kwargs["establishment_pk"])
        return self._counts

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if getattr(self, "company", None) is not None and self.kwargs.get("establishment_pk"):
            context["spelling_counts"] = self._spelling_counts()
        return context

    def perform_create(self, serializer):
        serializer.save(
            establishment_id=self.kwargs["establishment_pk"],
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )

    def perform_destroy(self, instance):
        counts = self._spelling_counts()
        if any(counts.get(n.normalized, (None, 0))[1] for n in instance.names.all()):
            raise ValidationError({"detail": "Records name this supplier, so it stays on file. Archive it instead."})
        instance.delete()

    @action(detail=False, methods=["get"], url_path="unconfirmed-spellings")
    def unconfirmed_spellings(self, request, **kwargs):
        """Supplier names on the farm's planting and transplanting records that no supplier holds.

        The suggestion half of suggest-then-confirm: each one is attached to a supplier, or a
        supplier is created from it, by the grower. Nothing is matched for them.
        """
        confirmed = set(
            SupplierName.objects.filter(establishment_id=self.kwargs["establishment_pk"]).values_list(
                "normalized", flat=True
            )
        )
        rows = [
            {"name": shown, "records": count}
            for key, (shown, count) in self._spelling_counts().items()
            if key not in confirmed
        ]
        rows.sort(key=lambda r: (-r["records"], r["name"].casefold()))
        return Response(rows)

    @action(detail=True, methods=["post"], url_path="names")
    def add_name(self, request, **kwargs):
        """Confirm that records spelling the supplier this way mean this supplier."""
        supplier = self.get_object()
        serializer = SupplierNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = " ".join(serializer.validated_data["name"].split())
        if not name:
            raise ValidationError({"name": "Enter the spelling used on the records."})
        if SupplierName.objects.filter(
            establishment_id=supplier.establishment_id, normalized=normalize_supplier_name(name)
        ).exists():
            raise ValidationError({"name": "A supplier on this farm already holds this spelling."})
        row = SupplierName.objects.create(supplier=supplier, name=name)
        return Response(SupplierNameSerializer(row).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"names/(?P<name_id>\d+)")
    def remove_name(self, request, name_id=None, **kwargs):
        supplier = self.get_object()
        row = get_object_or_404(supplier.names.all(), pk=name_id)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="certificates")
    def add_certificate(self, request, **kwargs):
        """File a copy of the supplier's organic certificate. A new copy never replaces an older
        one: each purchase is judged against the copy that covered it."""
        supplier = self.get_object()
        serializer = SupplierCertificateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        cert = serializer.save(
            supplier=supplier,
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(SupplierCertificateSerializer(cert).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"certificates/(?P<certificate_id>\d+)")
    def remove_certificate(self, request, certificate_id=None, **kwargs):
        """Take a copy off the supplier (a wrong file). The file stays in Documents."""
        supplier = self.get_object()
        cert = get_object_or_404(supplier.certificates.all(), pk=certificate_id)
        cert.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        from certifications.services.osp_sections import sections_missing_text

        return sections_missing_text(osp)

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
        from subscriptions.pilot_operator import refuse_setup_operator

        refusal = refuse_setup_operator(request.user, "submitting the Organic System Plan")
        if refusal:
            return Response({"error": refusal}, status=status.HTTP_403_FORBIDDEN)
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
                # A first version leaving draft: what the certifier holds is the operator's to say now.
                from .services.annual_update_filing import release_server_answered_basis

                release_server_answered_basis(osp)

                # This render IS the frozen submission copy: never labelled a reconstruction.
                pdf_bytes = generate_osp_snapshot_pdf(osp, generated_from_records=False)
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
                        f"This plan is {osp_status_phrase(osp.status)}, so its materials "
                        "list is locked until that review finishes. Wait for your certifier to "
                        "approve the plan, or start a new version now to revise the list."
                    )
                }
            )

    @action(detail=True, methods=["post"], url_path="add-approved-input")
    def add_approved_input(self, request, **kwargs):
        """
        Attach a NationalListSubstance or OMRIProduct to this OSP's approved
        inputs. Payload: { "kind": "national_list" | "omri" | "wsda", "id": <pk>,
        "change_notification_reference": "<optional>", "notes": "<optional>",
        "status": "<optional, in_use|planned>", "category": "<optional>" }.

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
        # The three § 205.602 rows the rule allows for a stated use ((c) calcium chloride, (e)
        # potassium chloride, (h) sodium nitrate) are accepted: a Honeycrisp grower lists calcium
        # chloride for bitter pit, and the plan prints the condition beside it (`plan_materials`).
        if kind == "national_list" and getattr(target, "is_refused_on_a_plan", False):
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
        # OTCO C11 asks every material "in use or intended for use", and its Intended Use column; CCOF and
        # WSDA ask the same per row. A catalog listing answers neither, so the attach takes them with it
        # (2026-11-16) and files them on the operator's row for this product, the row the Materials List
        # editor writes. Both optional here: an older client attaches as before and the list states the
        # cells as not stated.
        answers = {f: request.data[f] for f in ("status", "category") if request.data.get(f)}

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
            if answers:
                self._file_attach_answers(osp, request, kind, target, target_name, answers)

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
    def _file_attach_answers(osp, request, kind, target, target_name, answers) -> None:
        """The use and section given with a catalog attach, on the operator's row for that product.

        Found the way the editor finds it (`_find_material_entry`, by name), else created carrying the
        catalog FK, so its listing basis is the one the attachment really has. Called inside the
        attach's transaction: a refused answer leaves nothing attached.
        """
        from certifications.models import PlanMaterialEntry

        OrganicSystemPlan.objects.select_for_update().filter(pk=osp.pk).first()
        entry = OrganicSystemPlanViewSet._find_material_entry(osp, target_name)
        if entry is not None:
            serializer = PlanMaterialEntrySerializer(entry, data=answers, partial=True, context={"osp": osp})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return
        basis, field = {
            "national_list": (PlanMaterialEntry.BASIS_NATIONAL_LIST, "national_list_substance"),
            "wsda": (PlanMaterialEntry.BASIS_WSDA, "wsda_material"),
        }.get(kind, (PlanMaterialEntry.BASIS_OMRI, "omri_product"))
        payload = {**answers, "product_name": target_name, "listing_basis": basis, field: target.pk}
        serializer = PlanMaterialEntrySerializer(data=payload, context={"osp": osp})
        serializer.is_valid(raise_exception=True)
        serializer.save(osp=osp, created_by=request.user if request.user.is_authenticated else None)

    @staticmethod
    def _remove_attach_answers(osp, kind, target, target_name) -> None:
        from certifications.models import PlanMaterialEntry
        from certifications.services.plan_materials import _norm

        link = {"national_list": "national_list_substance_id", "wsda": "wsda_material_id"}.get(kind, "omri_product_id")
        name = _norm(target_name)
        for entry in PlanMaterialEntry.objects.filter(osp_id=osp.pk, **{link: target.pk}):
            if _norm(entry.product_name) == name:
                entry.delete()

    @staticmethod
    def _carried_by_a_catalog_attach(osp, entry) -> bool:
        """True when this operator row holds answers about a product the plan carries from a catalog.

        Such a row is not a material of its own: the catalog attach put the product on the plan and
        logged it, and `plan_materials` prints the two as one row. Read from the database, not the
        viewset's prefetch, for the same reason `_find_material_entry` does.
        """
        from certifications.services.plan_materials import _norm

        plan = OrganicSystemPlan.objects.get(pk=osp.pk)
        name = _norm(entry.product_name)
        for relation, attr, link in (
            (plan.approved_national_list_substances, "substance_name", "national_list_substance_id"),
            (plan.approved_omri_products, "product_name", "omri_product_id"),
            (plan.approved_wsda_materials, "brand_name", "wsda_material_id"),
        ):
            for row in relation.all():
                if _norm(getattr(row, attr, "")) == name or getattr(entry, link, None) == row.pk:
                    return True
        return False

    @staticmethod
    def _log_operator_material(osp, request, name, action) -> None:
        """A dated, append-only row for an operator-entered material added to or removed from the plan.

        The catalog paths always wrote one; an operator row did not, so a compost added mid-year left
        nothing for `plan_review` to flag and nothing to mark as an addition (OTCO C11 "to be added to
        my current Materials List", CCOF's materials list update).
        """
        ApprovedInputChangeLog.objects.create(
            osp=osp,
            kind=ApprovedInputChangeLog.KIND_OPERATOR,
            target_name_at_change=name,
            action=action,
            changed_by=request.user if request.user.is_authenticated else None,
        )

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
        so CCOF ORGB41 §A's own examples — compost, manure, gypsum, limestone — and any
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
        with transaction.atomic():
            entry = serializer.save(
                osp=osp,
                created_by=request.user if request.user.is_authenticated else None,
            )
            if not self._carried_by_a_catalog_attach(osp, entry):
                self._log_operator_material(osp, request, entry.product_name, ApprovedInputChangeLog.ACTION_ADDED)
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
            with transaction.atomic():
                stands_alone = not self._carried_by_a_catalog_attach(osp, entry)
                name = entry.product_name
                entry.delete()
                if stands_alone:
                    self._log_operator_material(osp, request, name, ApprovedInputChangeLog.ACTION_REMOVED)
            self._recompute_drift_for_establishment(osp.establishment_id)
            self._recompile_after_materials_change(osp)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = PlanMaterialEntrySerializer(entry, data=request.data, partial=True, context={"osp": osp})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self._recompute_drift_for_establishment(osp.establishment_id)
        self._recompile_after_materials_change(osp)
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"], url_path="material-identities")
    def material_identities(self, request, **kwargs):
        """What each logged product name IS, decided by the operator (OSP alignment T18, Phase 5).

        GET: every logged name not exactly on the plan (or under a decision), its events with their
        coverage state, the current decision and its history. POST: record a decision; see
        `services/material_identity.py` for the rules. A decision writes nothing on an event or on the
        plan; it is kept as evidence, superseded and never edited.
        """
        from certifications.services.material_identity import (
            IdentityError,
            _decision_json,
            identities,
            plan_targets,
            record_decision,
        )

        osp = self.get_object()
        if request.method == "GET":
            return Response({"identities": identities(osp), "targets": plan_targets(osp)})
        try:
            if request.data.get("withdraw") is not None:
                from certifications.services.material_identity import withdraw_decision

                decision = withdraw_decision(osp, request.user, request.data)
                self._recompute_drift_for_name(osp.establishment_id, decision.source, decision.name_key)
                return Response(_decision_json(decision))
            decision = record_decision(osp, request.user, request.data)
        except IdentityError as err:
            body = {err.field: [str(err)]} if err.field else {"detail": str(err)}
            return Response(body, status=err.status_code)
        # The drift detector may answer "not matched" through a covering decision: only this name's
        # events can change.
        self._recompute_drift_for_name(osp.establishment_id, decision.source, decision.name_key)
        return Response(_decision_json(decision), status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], url_path="material-restrictions")
    def material_restrictions(self, request, **kwargs):
        """How each restriction on this plan's materials is met, as the operator states it (T18).

        GET: every material on the plan, the regulation restriction Trazo holds for it (if any), its
        current statements with their review state, and the history. POST: record a statement; see
        `services/material_restrictions.py`. A statement approves nothing and clears no finding.
        """
        from certifications.services.material_restrictions import (
            RestrictionError,
            _statement_json,
            record_statement,
            restrictions_view,
        )

        osp = self.get_object()
        if request.method == "GET":
            return Response({"materials": restrictions_view(osp)})
        try:
            if request.data.get("withdraw") is not None:
                from certifications.services.material_restrictions import withdraw_statement

                return Response(_statement_json(withdraw_statement(osp, request.user, request.data), osp))
            statement = record_statement(osp, request.user, request.data)
        except RestrictionError as err:
            body = {err.field: [str(err)]} if err.field else {"detail": str(err)}
            return Response(body, status=err.status_code)
        return Response(_statement_json(statement, osp), status=status.HTTP_201_CREATED)

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

        Body: {"name": "...", "reason_for_use": "...", "status": "in_use"|"planned"|"discontinued",
               "manufacturer": "...", "category": "...", "agent_review": "...",
               "agent_review_date": "YYYY-MM-DD", "agent_review_reference": "...",
               "agent_review_use": "...", "label_document": <document id or null>} — every field but
               `name` optional.

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
            for field in (
                "reason_for_use",
                "status",
                "manufacturer",
                "category",
                "agent_review",
                "agent_review_date",
                "agent_review_reference",
                "agent_review_use",
                "label_document",
                "facility_material_type",
                "where_used",
                "applied_by_fumigation",
                "other_review_agency",
                "other_review_reference",
            )
            if field in request.data
        }
        if not payload:
            raise ValidationError({"detail": "Nothing to record — send a reason, a manufacturer or a use status."})
        # A blank date arrives as "" from a cleared date input; it means "no date", not a bad date.
        if payload.get("agent_review_date") == "":
            payload["agent_review_date"] = None
        if payload.get("label_document") == "":
            payload["label_document"] = None
        # A cleared fumigation select arrives as ""; it means "not stated".
        if payload.get("applied_by_fumigation") == "":
            payload["applied_by_fumigation"] = None
        # The agent a review came from is the plan's own agent, set here, never by the client.
        review_agent = None
        if "agent_review" in payload:
            from certifications.services.packet_coverage import packet_agent

            review_agent = (packet_agent(osp).slug or "") if payload["agent_review"] else ""

        # Find-or-create, under a lock on the plan row. Two answers for the SAME material can
        # overlap in one sitting — a use picked from the select and a reason blurred a moment
        # later are two requests — and unserialised they both find nothing and both create. The
        # duplicate would then be FOLDED out of sight by `plan_materials`, so the operator's
        # second answer would save, return 201, and never appear anywhere.
        with transaction.atomic():
            OrganicSystemPlan.objects.select_for_update().filter(pk=osp.pk).first()
            entry = self._find_material_entry(osp, name)
            extra = {} if review_agent is None else {"agent_review_agent": review_agent}
            if entry is not None:
                serializer = PlanMaterialEntrySerializer(entry, data=payload, partial=True, context={"osp": osp})
                serializer.is_valid(raise_exception=True)
                serializer.save(**extra)
                created = False
            else:
                payload["product_name"] = name
                payload.update(self._listing_basis_for(osp, name))
                serializer = PlanMaterialEntrySerializer(data=payload, context={"osp": osp})
                serializer.is_valid(raise_exception=True)
                entry = serializer.save(
                    osp=osp,
                    created_by=request.user if request.user.is_authenticated else None,
                    **extra,
                )
                created = True
                # A material the records showed and the plan did not is now ON the plan: an addition.
                # An answer about a catalog-attached product adds nothing; its attach was logged.
                if not self._carried_by_a_catalog_attach(osp, entry):
                    self._log_operator_material(osp, request, entry.product_name, ApprovedInputChangeLog.ACTION_ADDED)

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
            # The operator's answers about this product (use, section, reason, review, label) leave with
            # it. Left behind, the row came back as a material of its own, still saying "OMRI listed"
            # through its foreign key, on a plan the product had just been taken off (2026-11-16). A row
            # under another name that links this listing (a brand of a National List substance) is a
            # material in its own right and stays.
            self._remove_attach_answers(osp, kind, target, target_name)

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

        from .services.drift_detector import evaluate_chemical_event, evaluate_soil_event, shared_catalog_lookups

        chem_qs = ChemicalEvent.objects.filter(history__parcel__establishment_id=establishment_id)
        soil_qs = SoilManagementEvent.objects.filter(history__parcel__establishment_id=establishment_id)
        with shared_catalog_lookups():
            for e in chem_qs.iterator():
                evaluate_chemical_event(e)
            for e in soil_qs.iterator():
                evaluate_soil_event(e)

    @staticmethod
    def _recompute_drift_for_name(establishment_id: int, source: str, name_key: str):
        """Re-run the drift detector for the events logged under one name: all an identity decision
        can change. The whole-farm recompute took ~11 s on the demo farm (browser test, 2026-10-03)."""
        from certifications.services.material_identity import events_for

        from .services.drift_detector import evaluate_chemical_event, evaluate_soil_event, shared_catalog_lookups

        evaluate = {"chemical": evaluate_chemical_event, "amendment": evaluate_soil_event}.get(source)
        if evaluate is None:
            return
        with shared_catalog_lookups():
            for event in events_for(establishment_id, source, name_key):
                evaluate(event)

    @action(detail=True, methods=["post"], url_path="new-version")
    def new_version(self, request, **kwargs):
        """
        Clone this OSP into a new draft with version_number=max+1. The frontend
        uses this when the farmer is starting the next year's OSP from last year.
        """
        from certifications.services.osp_fork import fork_plan

        clone = fork_plan(self.get_object(), self.request.user)
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

        # How a confirmed record the operation keeps outside Trazo links to the next and previous
        # document (OTCO C12 12.2-6), one record type at a time, in the operator's words.
        if "linking_element" in request.data:
            from certifications.services.common_osp_records import set_linking_element

            if len(keys) != 1:
                raise ValidationError({"keys": "State one record type's linking element at a time."})
            text = request.data.get("linking_element")
            if text is not None and not isinstance(text, str):
                raise ValidationError({"linking_element": "Must be a string."})
            try:
                set_linking_element(osp, keys[0], text or "", user=request.user)
            except ValueError as exc:
                raise ValidationError({"linking_element": str(exc)}) from exc
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

        from certifications.services.osp_module_pdf import generate_module_pdf, module_document_title
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
            title=module_document_title(module_key, parcel),
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
        function is the DMS seam; this action files and streams its bytes.

        `?scope=changed` builds it with only the module PDFs whose answers changed since the prior
        plan version (`packet_scope`); every other document stays in. When the two versions cannot
        be compared the request is refused with the reason, never built as a full packet under the
        changed-sections name. Without `scope` (or `scope=full`) the packet is unchanged."""
        from io import BytesIO

        from django.http import FileResponse

        from certifications.services.osp_module_pdf import generate_osp_packet
        from certifications.services.packet_scope import CHANGED, SCOPES, PacketScopeUnavailable, changed_only_scope
        from documents.services.filing import file_document

        osp = self.get_object()
        establishment = osp.establishment
        # Plan gate, before generating anything. `generate_osp_packet` builds every module PDF,
        # a Parcel Application per parcel and four workbooks — running all of that and then
        # refusing to hand it over would burn the work and file a document (see file_document
        # below) that the farm is not entitled to download.
        require_compliance_exports(establishment.company, user=request.user)
        requested = request.query_params.get("scope") or "full"
        if requested not in SCOPES:
            raise ValidationError({"scope": f"Unknown scope. Expected one of: {', '.join(SCOPES)}"})
        scope = None
        if requested == CHANGED:
            try:
                scope = changed_only_scope(osp)
            except PacketScopeUnavailable as exc:
                raise ValidationError({"scope": exc.message, "code": exc.code})
        data = generate_osp_packet(osp, scope=scope)
        stem = slugify(establishment.name) or "operation"
        if scope is not None:
            filename = f"{stem}-osp-v{osp.version_number}-packet-changed-sections.zip"
            title = f"OSP renewal packet, changed sections only, v{osp.version_number}"
        else:
            filename = f"{stem}-osp-v{osp.version_number}-packet.zip"
            title = f"OSP renewal packet — v{osp.version_number}"
        file_document(
            establishment=establishment,
            source="packet",
            folder="organic_system_plan",
            title=title,
            filename=filename,
            content=data,
            content_type="application/zip",
            created_by=request.user if request.user.is_authenticated else None,
        )
        return FileResponse(BytesIO(data), as_attachment=True, filename=filename)

    @action(detail=True, methods=["get"], url_path="packet-scope")
    def packet_scope(self, request, **kwargs):
        """What a changed-sections packet built from this plan would carry, or why it cannot be built.

        A read, not an export: nothing is generated or filed. It sits behind the packet's own plan
        gate because it is the packet's option, and the client shows the choice only when it is
        available, so an anchor download never lands on a refusal.
        """
        from certifications.services.packet_scope import scope_preview

        osp = self.get_object()
        require_compliance_exports(osp.establishment.company, user=request.user)
        return Response(scope_preview(osp))

    @action(detail=True, methods=["get"], url_path="agent-form-sheet")
    def agent_form_sheet(self, request, **kwargs):
        """What to copy onto the certifying agent's own renewal form, step by step.

        Read from the same records as the renewal packet, so it sits behind the same plan gate. It
        is a read, not an export: nothing is generated or filed. 404 when Trazo has no copy sheet
        for the plan's agent, so the client shows nothing rather than a borrowed agent's form.
        """
        from certifications.services.agent_form_sheet import agent_form_sheet

        osp = self.get_object()
        require_compliance_exports(osp.establishment.company, user=request.user)
        sheet = agent_form_sheet(osp)
        if sheet is None:
            return Response({"detail": "No copy sheet for this plan's certifying agent."}, status=404)
        return Response(sheet)

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
            # The form's own name ("Field and Crop Information Form"), not the file stem
            # ("Field_and_Crop_Information"), which is what the shelf printed before.
            title=f"Common OSP workbook — {spec.title}",
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
    def _module_status(entry: dict, module=None, osp=None, blocked=None) -> str:
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

                    # `blocked`: the caller already ran the gate for this module (the list row
                    # does, to name the questions). It is not cheap: the materials gate scans the
                    # establishment's input records once per reconciled question.
                    if blocked is None:
                        blocked = blocked_attestations(module, answers, osp)
                    if blocked:
                        return "in_progress"
            return "completed"
        if entry.get("answers"):
            return "in_progress"
        return "not_started"

    def _module_progress_row(self, module, entry: dict, osp=None, asks=None) -> dict:
        from certifications.osp_modules.conditions import progress
        from certifications.services.agent_question_refs import blank_asked_questions

        blocked = self._blocked_attestations(module, entry, osp)
        return {
            "key": module.key,
            "code": module.code,
            "status": self._module_status(entry, module, osp, blocked=blocked),
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
            # Blank, showing, not required by Trazo, and asked by the plan's own agent. A soft flag:
            # completion never waits on it (the agent decides what it needs).
            "agent_asks_blank": (blank_asked_questions(module, entry, asks[1].get(module.key, {})) if asks else []),
            # Attestations answered Yes over a list that cannot carry them (empty, or missing what
            # the records show). `_module_status` already reports such a module "in_progress"; the
            # list row printed "5 of 5 required answers" beside the open circle and said nothing
            # about why, so the grower saw a finished module that would not close (2026-11-11).
            "blocked_attestations": sorted(blocked),
        }

    @staticmethod
    def _blocked_attestations(module, entry: dict, osp) -> dict:
        """The gate, run ONCE per module row and shared with `_module_status`."""
        if osp is None or module is None or entry.get("not_applicable"):
            return {}
        from certifications.services.attestation_gates import blocked_attestations

        return blocked_attestations(module, entry.get("answers") or {}, osp)

    @action(
        detail=True,
        methods=["get"],
        url_path="seedling-suppliers",
        permission_classes=[IsSuperUser | (IsCompanyAdminOrManager & AuthPermission)],
    )
    def seedling_suppliers(self, request, **kwargs):
        """The suppliers G3.0a prints, for the wizard's panel (`supplier_certificates.seedling_suppliers`).

        Admins and farm managers only, like the supplier register: a supplier list is commercial data.
        """
        from history.services.supplier_certificates import (
            buys_certified_seedlings,
            needs_certificate,
            seedling_suppliers,
        )

        osp = self.get_object()
        rows = seedling_suppliers(osp.establishment)
        buys = buys_certified_seedlings(osp)
        return Response(
            {
                "suppliers": [
                    {
                        "name": row["name"],
                        "supplier_id": row["supplier"]["id"] if row["supplier"] else None,
                        "certifier": (row["supplier"] or {}).get("certifier") or "",
                        "nop_operation_id": (row["supplier"] or {}).get("nop_operation_id") or "",
                        "purchases": row["purchases"],
                        "latest": row["latest"].isoformat() if row["latest"] else None,
                        "status": row["status"],
                        "certificate_issued_on": (
                            row["certificate"].issued_on.isoformat() if row["certificate"] else None
                        ),
                        "not_covered": row["not_covered"],
                        "claims_certified": row["claims_certified"],
                        # The rule the plan's [REVIEW] lines and the coverage page read.
                        "needs_certificate": needs_certificate(row, buys),
                    }
                    for row in rows
                ]
            }
        )

    @action(detail=True, methods=["get"], url_path="modules")
    def modules(self, request, **kwargs):
        """Per-module progress for the module list page (farm-wide modules).

        Per-parcel module rows land with WS-5 (they are computed against live Parcel
        state, not against module_responses — Appendix A §f).
        """
        from certifications.osp_modules import MODULE_REGISTRY
        from certifications.services.agent_question_refs import agent_asks

        osp = self.get_object()
        responses = (osp.module_responses or {}).get("modules", {})
        asks = agent_asks(osp)
        rows = [self._module_progress_row(m, responses.get(m.key) or {}, osp, asks) for m in MODULE_REGISTRY]
        # The agent the `agent_asks_blank` lists speak for; null when Trazo holds no register for it.
        return Response({"modules": rows, "agent": asks[0] if asks else None})

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
            from certifications.services.agent_question_refs import agent_asks, agent_question_refs
            from certifications.services.osp_prefill import resolve_suggestions

            osp = self.get_object()
            entry = ((osp.module_responses or {}).get("modules", {})).get(module.key) or {}
            asks = agent_asks(osp)
            return Response(
                {
                    "definition": serialize_module(module),
                    "content_version": CONTENT_VERSION,
                    "response": self._module_progress_row(module, entry, osp, asks),
                    "answers": entry.get("answers") or {},
                    # Evidence → suggestion only. Resolved fresh on every GET, never
                    # stored; the sole path into `answers` is the operator accepting
                    # one in the wizard (§ 205.201(a) — the producer authors the plan).
                    "suggestions": resolve_suggestions(module, osp.establishment, osp=osp),
                    # Where this plan's own agent asks each question, for the caption under it.
                    # Beside the definition, never inside it: the definition is the same for
                    # every agent (the golden fixture holds it agent-neutral).
                    "agent_refs": agent_question_refs(osp, module.key, asks),
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

        from certifications.services.agent_question_refs import agent_asks

        return Response(
            {
                # Read after the write, so the row reflects the answers just saved.
                "response": self._module_progress_row(module, entry, osp, agent_asks(osp)),
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
        return (
            OSPAnnualUpdate.objects.filter(
                prior_osp__establishment_id=self.kwargs.get("establishment_pk"),
                prior_osp__establishment__company=self.company,
            )
            .select_related("prior_osp", "new_osp")
            .prefetch_related("supporting_links__document")
        )

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
        from django.db.models import Max

        from certifications.services.annual_update_linking import link_filing_to_open_draft

        prior = serializer.validated_data["prior_osp"]
        # 1 for a new year. After a withdrawal the year starts again as the next revision, so the
        # withdrawn one keeps its number and the new one does not collide with it.
        highest = OSPAnnualUpdate.objects.filter(
            establishment_id=prior.establishment_id, reporting_year=serializer.validated_data["reporting_year"]
        ).aggregate(n=Max("revision_number"))["n"]
        instance = serializer.save(
            created_by=self.request.user,
            establishment_id=prior.establishment_id,
            revision_number=(highest or 0) + 1,
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
            return Response({"error": exc.detail, "detail": exc.detail, **exc.extra}, status=exc.status_code)
        result.refresh_from_db()
        return Response(self.get_serializer(result).data, status=success_status)

    @action(detail=True, methods=["post"])
    def sign(self, request, *args, **kwargs):
        from certifications.services.annual_update_filing import sign_filing

        # The signer's NAME never comes from the payload (SignerComesFromTheRequestTests): it is
        # the responsible person on the farm profile, else the account; the account is the recorder.
        return self._run(sign_filing, self.get_object(), request.user, request.data.get("signer_title", ""))

    @action(detail=True, methods=["post"], url_path="file")
    def file_with_agent(self, request, *args, **kwargs):
        import datetime

        from django.utils import timezone
        from django.utils.dateparse import parse_date, parse_datetime

        from certifications.services.annual_update_filing import file_filing

        raw = str(request.data.get("submitted_at") or "").strip()
        when = None
        if raw:
            # A date alone is the usual answer ("filed on 3 September"). It is stored at midday so
            # the calendar day reads the same in any timezone. Checked first: `parse_datetime`
            # also accepts a bare date and returns midnight, which is the previous day west of UTC.
            day = parse_date(raw) if len(raw) == 10 else None
            if day is not None:
                when = timezone.make_aware(datetime.datetime.combine(day, datetime.time(12, 0)))
            else:
                when = parse_datetime(raw)
                if when is None:
                    return Response(
                        {"submitted_at": "Give the date the update was filed as YYYY-MM-DD."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if timezone.is_naive(when):
                    when = timezone.make_aware(when)
        # The account recording the filing owns its Documents copy (`created_by`).
        return self._run(file_filing, self.get_object(), request.data.get("filing_method", ""), when, request.user)

    @action(detail=True, methods=["post"])
    def correct(self, request, *args, **kwargs):
        from certifications.services.annual_update_filing import correct_filing

        return self._run(correct_filing, self.get_object(), request.user, success_status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, *args, **kwargs):
        from certifications.services.annual_update_filing import withdraw_filing

        return self._run(withdraw_filing, self.get_object(), request.data.get("reason", ""))

    @action(detail=True, methods=["get", "post"], url_path="company-details")
    def company_details(self, request, *args, **kwargs):
        """§ 205.406(a)(3): the § 205.401(b) details Trazo holds, each confirmed or changed.

        GET is read-only for any member. POST needs the write role this viewset already checks
        (a viewer is refused there), and a change to the business name or trade name also needs
        the company admin role `CompanyViewSet` requires for the same write. The records written
        are this filing's own, never ones named in the payload. See
        `certifications/services/application_info_review.py`.
        """
        from backend.permissions import IsCompanyAdmin
        from certifications.services.application_info_review import (
            ApplicationInfoReviewSerializer,
            ReviewRefused,
            apply_review,
            review_payload,
        )
        from subscriptions.pilot_operator import refuse_setup_operator
        from users.models import WorksIn

        filing = self.get_object()
        establishment = filing.prior_osp.establishment
        user = request.user
        can_answer = user.is_superuser or (
            WorksIn.objects.filter(
                user=user, company=self.company, role__in=[WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER]
            ).exists()
            and not refuse_setup_operator(user, "")
        )
        can_edit_company = IsCompanyAdmin().has_permission(request, self)

        def payload(row):
            return review_payload(row, establishment, can_answer=can_answer, can_edit_company=can_edit_company)

        if request.method == "GET":
            return Response(payload(filing))
        refusal = refuse_setup_operator(user, "confirming the company details on the annual update")
        if refusal:
            return Response({"error": refusal, "detail": refusal}, status=status.HTTP_403_FORBIDDEN)
        if filing.is_locked:
            return self._locked_response(filing, status.HTTP_409_CONFLICT)
        serializer = ApplicationInfoReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            saved = apply_review(
                filing, establishment, serializer.validated_data["answers"], request, can_edit_company=can_edit_company
            )
        except ReviewRefused as exc:
            return Response(exc.body, status=exc.status_code)
        establishment.refresh_from_db()
        return Response(payload(saved))


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
    return client_ip(request)


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


def _link_over_hourly_limit(link, action):
    """A 429 when this link has used its hourly allowance for `action`, else None.

    The DRF throttles on these routes count in the cache, and production's cache is DummyCache
    while REDIS_URL is unset, so on their own they never refuse anything. This ceiling counts
    the link's own access-log rows, which every served request already writes, so it holds
    without a cache. Refusals write no row: a refused caller does not extend its own wait.
    Two requests racing at the boundary can both pass; the ceiling is a bound, not a quota.

    The frontend reads 429 as "temporarily unavailable" (`reviewLinkFailure.ts`), never as
    revoked, so a reviewer who hits it is not told the grower withdrew the link.
    """
    limit = getattr(settings, "CERTIFIER_REVIEW_LINK_HOURLY_LIMITS", {}).get(action)
    if not limit:
        return None
    now = timezone.now()
    recent = CertifierAccessLog.objects.filter(link=link, action=action, accessed_at__gte=now - timedelta(hours=1))
    if recent.count() < limit:
        return None
    oldest = recent.order_by("accessed_at").values_list("accessed_at", flat=True).first()
    retry_after = max(1, math.ceil((oldest + timedelta(hours=1) - now).total_seconds()))
    logger.warning(
        "review link over its hourly limit: link=%s action=%s limit=%s retry_after=%ss",
        link.pk,
        action,
        limit,
        retry_after,
    )
    return Response(
        {"error": "This link has been opened many times in the last hour. Please try again later."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(retry_after)},
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
def certifier_review_metadata(request, token):
    """Context for the certifier landing page — no records, just what this link is.

    Kept separate from the dossier download so the certifier sees whose operation
    and which window they are about to open, rather than an unexplained file.
    """
    link = _resolve_link_or_404(token)
    limited = _link_over_hourly_limit(link, "metadata")
    if limited is not None:
        return limited

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
    limited = _link_over_hourly_limit(link, "readiness")
    if limited is not None:
        return limited

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
        productions = service.readiness_rows_for_certifier()
    except Exception:
        # Same posture as the dossier view: a reviewer reading this must never see a raw 500
        # that reads as "this grower's records are broken". Log the real cause for us.
        logger.exception("Certifier readiness rows failed for establishment %s", link.establishment_id)
        return Response(
            {"error": "Readiness details could not be loaded right now. Please try again shortly."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    total_findings = sum(len(p["findings"]) for p in productions)
    total_not_assessed = sum(len(p["not_assessed"]) for p in productions)

    return Response(
        {
            "productions": productions,
            "total_findings": total_findings,
            "total_not_assessed": total_not_assessed,
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
    # Checked before the cached copy and before a build: once the allowance is spent this link
    # starts nothing either.
    limited = _link_over_hourly_limit(link, "dossier")
    if limited is not None:
        return limited
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


def _review_link_source_files(link):
    """The files a link can open: exactly the uploads the dossier's document index lists.

    Same query as `AuditExportService._build_attached_documents_section` in its establishment
    scope (every upload of the operation, Trazo-generated files excluded), so the page and the
    PDF cannot disagree about what exists. Empty unless the grower chose to include source files
    when the link was created.
    """
    from documents.models import GeneratedDocument

    if not link.include_source_files or not _profile_lists_documents(link.certification_type):
        return GeneratedDocument.objects.none()
    return GeneratedDocument.objects.filter(establishment=link.establishment, source="upload").exclude(file="")


def _profile_lists_documents(certification_type):
    """Whether this dossier profile carries the document index at all (review of back #183).

    The files a link opens are the ones its dossier lists. A profile without the index
    (fsma204, globalgap, scs) lists none, so it opens none, whatever the opt-in says.
    """
    from history.services.audit_export_service import AuditExportService

    return "attached_documents" in AuditExportService.CERTIFICATION_SECTIONS.get(certification_type or "", [])


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
def certifier_review_documents(request, token):
    """The operation's source files for this link (H-3, handoff rehearsal 2026-10-18).

    `enabled: false` when the grower did not include source files: the page then says so, and
    the dossier's index still names every file. Listing writes no access row; opening a file does.
    """
    from history.services.audit_export_service import AuditExportService

    link = _resolve_link_or_404(token)
    docs = list(_review_link_source_files(link).select_related("history").order_by("-created_at"))
    labels = AuditExportService._document_record_labels(docs)
    return Response(
        {
            "enabled": link.include_source_files,
            "documents": [
                {
                    "id": str(doc.public_id),
                    "title": doc.title,
                    "folder": doc.get_folder_display(),
                    "linked_to": labels.get((doc.event_type, doc.event_id))
                    or (doc.history.name if doc.history_id and doc.history else None),
                    "size_bytes": doc.size_bytes,
                    "content_type": doc.content_type,
                    "uploaded_at": doc.created_at,
                }
                for doc in docs
            ],
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
def certifier_review_document_file(request, token, document_id):
    """Stream one source file through the link, never a storage URL.

    The file goes through this route so that revoking or expiring the link ends access to it
    at once, as it does for the dossier (a signed storage URL would outlive revocation until its
    own expiry). Every open is logged with the file on the grower's card, and the per-link
    hourly ceiling applies. A file outside this link's scope is a 404, like an unknown id.
    """
    from django.http import FileResponse

    link = _resolve_link_or_404(token)
    limited = _link_over_hourly_limit(link, "document")
    if limited is not None:
        return limited
    try:
        public_id = uuid.UUID(str(document_id))
    except ValueError:
        raise Http404("No such file for this link.")
    doc = _review_link_source_files(link).filter(public_id=public_id).first()
    if doc is None:
        raise Http404("No such file for this link.")

    # Open BEFORE logging (review of back #183): a file missing from storage must neither write
    # an access row saying it was opened nor surface as a raw 500 on a certifier's page.
    try:
        handle = doc.file.open("rb")
    except Exception:
        logger.exception("Review-link source file could not be opened: document %s", doc.pk)
        return Response(
            {"error": "This file could not be opened right now. Please try again shortly."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    CertifierAccessLog.objects.create(
        link=link,
        action="document",
        document=doc,
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )
    # Django builds Content-Disposition from `filename`, escaping quotes and encoding non-ASCII
    # names (RFC 5987); a hand-written header broke on both.
    return FileResponse(
        handle,
        as_attachment=True,
        filename=doc.file.name.rsplit("/", 1)[-1],
        content_type=doc.content_type or "application/octet-stream",
    )


def _review_link_sales(link):
    """The sales a certifier link can trace: live sales of the seasons its dossier covers.

    The dossier windows by SEASON (`OperationAuditExportService.window_q`), not by sale date: a
    storage sale lands after its season finishes. Filtering by sale date traced sales of seasons
    the dossier excludes, and missed covered seasons' later sales (review of back #194). Another
    farm's or a voided sale is not found here.
    """
    from history.models import SalesRecord
    from history.services.operation_audit_export_service import OperationAuditExportService

    sales = SalesRecord.objects.live().filter(
        OperationAuditExportService.window_q(link.period_start, link.period_end, prefix="production__"),
        production__parcel__establishment=link.establishment,
    )
    return sales.select_related("production__parcel__establishment", "production__product", "production__crop_type")


def _log_traceback(link, request):
    CertifierAccessLog.objects.create(
        link=link,
        action="traceback",
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
def certifier_review_traceback_search(request, token):
    """Find a sale by the number on a document, as the inspector does at inspection.

    The operation's own search (`history.services.traceback.search_sales`), on this link's farm
    and window only. Every request is logged on the grower's card ("Traced a sale"), and the
    link's hourly ceiling applies. No new content class: the dossier this link opens already
    carries the sales, invoices, picks and inputs a trace shows.
    """
    from history.services.traceback import search_sales

    link = _resolve_link_or_404(token)
    limited = _link_over_hourly_limit(link, "traceback")
    if limited is not None:
        return limited
    random = request.query_params.get("random") in ("1", "true")
    q = (request.query_params.get("q") or "").strip()
    if not random and not q:
        return Response({"error": "q or random=1 is required"}, status=status.HTTP_400_BAD_REQUEST)
    _log_traceback(link, request)
    return Response(search_sales(_review_link_sales(link), q=q, random=random))


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
def certifier_review_traceback(request, token, sale_id):
    """One sale's chain for the reviewer: the operation's own trace, read-only.

    A sale outside the link's farm or window is the same 404 as an unknown id. Files: a file the
    link can open (the grower included source files, and the dossier lists it) carries its public
    id for the token route; any other file keeps its title only, so the reviewer sees it exists
    without opening it. Internal ids (company, establishment, parcel, season) are not sent.
    """
    from history.services.traceback import trace_sale

    link = _resolve_link_or_404(token)
    limited = _link_over_hourly_limit(link, "traceback")
    if limited is not None:
        return limited
    sale = _review_link_sales(link).filter(pk=sale_id if str(sale_id).isdigit() else None).first()
    if sale is None:
        raise Http404("No such sale for this link.")
    _log_traceback(link, request)
    return Response(_trace_for_reviewer(trace_sale(sale).as_dict(), link))


def _trace_for_reviewer(trace, link):
    """A trace (from a sale or from a pick) as the anonymous reviewer receives it.

    Files: a file the link can open carries its public id for the token route; any other keeps its
    title only. Internal ids (company, establishment, parcel, season, pick, input) are not sent.
    Sale ids stay where they already reach this caller through the search (a lot trace's forward
    sales), so the reviewer can open that sale's own trace, itself scoped to the link.
    """
    openable = dict(_review_link_source_files(link).values_list("pk", "public_id"))

    def review_docs(docs):
        return [
            {"title": d["title"], "kind": d["kind"], "file_id": str(openable[d["id"]]) if d["id"] in openable else None}
            for d in docs
        ]

    # Every internal primary key becomes an opaque label local to this response ("p1", "i3"), so a
    # gap still points at its row and no sequential pk reaches an anonymous caller (review of back
    # #194: pick ids, input event ids and the gaps' refs, which re-included the sale's pk).
    labels = {}
    for n, row in enumerate(trace["picks"], 1):
        labels[("picks", row["id"])] = f"p{n}"
        row["id"] = f"p{n}"
        row["documents"] = review_docs(row["documents"])
    for n, row in enumerate(trace["inputs"], 1):
        labels[("inputs", row["kind"], row["event_id"])] = f"i{n}"
        row["event_id"] = f"i{n}"
        row["documents"] = review_docs(row["documents"])
    for gap in trace["gaps"]:
        key = ("picks", gap["ref"]) if gap["hop"] == "picks" else ("inputs", gap["kind"], gap["ref"])
        gap["ref"] = labels.get(key)
    if "sale" in trace:
        trace["sale"]["documents"] = review_docs(trace["sale"]["documents"])
        trace["sale"].pop("id", None)
    for key in ("id", "public_id", "parcel_id", "establishment_id", "company_id"):
        trace["season"].pop(key, None)
    return trace


def _review_link_picks(link):
    """The harvest picks a certifier link can trace: picks of the seasons its dossier covers, on
    its farm. The same season window as `_review_link_sales`, so a lot and the sales that name it
    are in or out of the link together."""
    from history.models import ProductionEvent
    from history.services.operation_audit_export_service import OperationAuditExportService

    return ProductionEvent.objects.filter(
        OperationAuditExportService.window_q(link.period_start, link.period_end, prefix="history__"),
        type=ProductionEvent.HARVESTING,
        history__parcel__establishment=link.establishment,
    ).select_related("history__parcel__establishment", "history__product", "history__crop_type")


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
def certifier_review_lot_traceback_search(request, token):
    """Find a harvest pick by the number on stored product (a lot code, a packer's receipt, the
    season's lot ID), on this link's farm and window only. Logged and rate-limited as a sale
    search is: the dossier this link opens already carries the picks a lot trace shows."""
    from history.services.traceback import search_picks

    link = _resolve_link_or_404(token)
    limited = _link_over_hourly_limit(link, "traceback")
    if limited is not None:
        return limited
    q = (request.query_params.get("q") or "").strip()
    if not q:
        return Response({"error": "q is required"}, status=status.HTTP_400_BAD_REQUEST)
    _log_traceback(link, request)
    return Response(search_picks(_review_link_picks(link), q))


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([CertifierReviewThrottle])
def certifier_review_lot_traceback(request, token, pick_id):
    """One harvest pick's chain for the reviewer, read-only: product in storage, walked back to its
    season and inputs and forward to the sales that name it. A pick outside the link's farm or
    window is the same 404 as an unknown id."""
    from history.services.traceback import trace_pick

    link = _resolve_link_or_404(token)
    limited = _link_over_hourly_limit(link, "traceback")
    if limited is not None:
        return limited
    pick = _review_link_picks(link).filter(pk=pick_id if str(pick_id).isdigit() else None).first()
    if pick is None:
        raise Http404("No such harvest record for this link.")
    _log_traceback(link, request)
    return Response(_trace_for_reviewer(trace_pick(pick).as_dict(), link))


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
    limited = _link_over_hourly_limit(link, "metadata")
    if limited is not None:
        return limited

    CertifierAccessLog.objects.create(
        link=link,
        action="metadata",
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
    )

    from history.models import Production

    seasons = []
    qs = (
        Production.objects.filter(parcel__establishment=link.establishment)
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
            # select_related on the log: `document_title` would otherwise query once per row.
            .prefetch_related(
                Prefetch("accesses", queryset=CertifierAccessLog.objects.select_related("document"))
            ).order_by("-created_at")
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
